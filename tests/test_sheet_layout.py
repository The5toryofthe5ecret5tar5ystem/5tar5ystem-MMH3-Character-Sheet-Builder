"""Character Sheet Builder - placement, compositing and frame picking.

Pinned here:

* the sheet canvas maths (short edge + aspect, aligned for H3 reuse),
* ``hero-left`` really puts the hero on the left and the rest in a 2x2 grid,
* captions/background/fit actually change pixels,
* the picker contract: auto = last frame, explicit index wins, sharpest ranks.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from h3cs import sheet_layout as sl
from h3cs import sheet_spec as ss


def _cells(count: int, **kwargs):
    return [
        ss.SheetCell(id=f"c{index}", view="front", **kwargs)
        for index in range(count)
    ]


def _solid(width: int, height: int, color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (width, height), color)


# --------------------------------------------------------------------------- #
# canvas
# --------------------------------------------------------------------------- #
def test_canvas_uses_the_short_edge_and_aspect_aligned_to_16():
    layout = ss.SheetLayoutSpec(short_edge=1536, aspect="3:2")
    assert sl.sheet_canvas_size(layout) == (2304, 1536)


def test_canvas_handles_portrait_aspects():
    layout = ss.SheetLayoutSpec(short_edge=1024, aspect="9:16")
    width, height = sl.sheet_canvas_size(layout)
    # The SHORT edge is the width for a portrait sheet; the long edge grows.
    assert width == 1024
    assert height > width
    assert width % sl.CANVAS_ALIGN == 0 and height % sl.CANVAS_ALIGN == 0


def test_canvas_handles_ultrawide_21_9():
    """21:9 is the widest sheet offered: a strip of cells that fills a 21:9 frame."""
    layout = ss.SheetLayoutSpec(short_edge=1536, aspect="21:9")
    assert sl.sheet_canvas_size(layout) == (3584, 1536)  # 1536 * 21/9 = 3584 exactly
    small = ss.SheetLayoutSpec(short_edge=1024, aspect="21:9")
    width, height = sl.sheet_canvas_size(small)
    assert (width, height) == (2384, 1024)
    assert width % sl.CANVAS_ALIGN == 0 and height % sl.CANVAS_ALIGN == 0


def test_a_composed_ultrawide_sheet_keeps_the_ratio():
    layout = ss.SheetLayoutSpec(layout="turnaround", columns=4, short_edge=1024, aspect="21:9", captions=False)
    cells = _cells(4, frames=1)
    sheet = sl.compose_from_arrays(
        [_solid(64, 64, (10, 10, 10)) for _ in cells], layout, cells=cells, captions=[]
    )
    width, height = sl.sheet_canvas_size(layout)
    assert sheet.size == (width, height)
    assert abs(width / height - 21 / 9) < 0.02, "the composite keeps the picked ratio"


# --------------------------------------------------------------------------- #
# placement
# --------------------------------------------------------------------------- #
def test_hero_left_puts_four_cells_in_a_2x2_beside_the_hero():
    cells = _cells(5)
    layout = ss.SheetLayoutSpec(
        layout="hero-left", columns=2, short_edge=1600, gap=0, padding=0, captions=False
    )
    (sheet_w, sheet_h), rects = sl.layout_rects(cells, layout)
    assert len(rects) == 5
    hero = rects[0]
    right = rects[1:]
    # Hero spans the full content height on the left.
    assert hero[0] == 0
    assert hero[3] == sheet_h
    assert hero[2] < sheet_w
    # The four angles form a 2x2 block to the right of the hero.
    assert len({rect[0] for rect in right}) == 2
    assert len({rect[1] for rect in right}) == 2
    assert all(rect[0] >= hero[2] for rect in right)


def test_grid_is_row_major_and_uses_the_requested_columns():
    cells = _cells(5)
    layout = ss.SheetLayoutSpec(layout="grid", columns=3, short_edge=1440, gap=10, padding=10)
    (_, _), rects = sl.layout_rects(cells, layout)
    assert len(rects) == 5
    assert len({rect[1] for rect in rects}) == 2  # two rows
    assert rects[3][1] > rects[0][1]  # row-major


def test_turnaround_is_one_row():
    cells = _cells(4)
    layout = ss.SheetLayoutSpec(layout="turnaround", short_edge=1024, gap=0, padding=0, captions=False)
    (_, sheet_h), rects = sl.layout_rects(cells, layout)
    assert len({rect[1] for rect in rects}) == 1
    assert all(rect[3] == sheet_h for rect in rects)


def test_custom_placement_honours_spans():
    cells = [
        ss.SheetCell(id="big", place={"row": 0, "col": 0, "rowSpan": 2, "colSpan": 1}),
        ss.SheetCell(id="b", place={"row": 0, "col": 1}),
        ss.SheetCell(id="c", place={"row": 1, "col": 1}),
    ]
    layout = ss.SheetLayoutSpec(layout="custom", short_edge=1200, gap=0, padding=0, captions=False)
    (_, sheet_h), rects = sl.layout_rects(cells, layout)
    assert rects[0][3] == sheet_h  # spans both rows
    assert rects[1][1] != rects[2][1]  # stacked in column 1


def test_empty_cell_list_is_not_a_crash():
    (width, height), rects = sl.layout_rects([], ss.SheetLayoutSpec())
    assert rects == []
    assert width > 0 and height > 0


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #
def _composite_cells():
    return [
        ss.SheetCell(id="big", view="portrait", caption="HERO"),
        ss.SheetCell(id="b", view="front"),
        ss.SheetCell(id="c", view="front"),
        ss.SheetCell(id="d", view="front"),
        ss.SheetCell(id="e", view="front"),
    ]


def test_compose_pastes_every_cell_and_keeps_the_background_between_them():
    cells = _composite_cells()
    layout = ss.SheetLayoutSpec(
        layout="hero-left", columns=2, short_edge=1200, gap=20, padding=20,
        captions=False, background="#000000", fit="stretch",
    )
    images = [
        _solid(200, 300, color)
        for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
    ]
    sheet = sl.compose_sheet(images, layout, cells=cells)
    expected_w, expected_h = sl.sheet_canvas_size(layout)
    assert (sheet.width, sheet.height) == (expected_w, expected_h)
    (_, _), rects = sl.layout_rects(cells, layout)
    pixels = sheet.load()
    for rect, color in zip(rects, [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]):
        x, y, w, h = rect
        assert pixels[x + w // 2, y + h // 2] == color
    # The gap column between the hero and the right-hand grid stays background.
    hero = rects[0]
    assert pixels[hero[0] + hero[2] + 5, hero[1] + 5] == (0, 0, 0)


def test_missing_cells_leave_the_slot_empty_instead_of_failing():
    cells = _composite_cells()
    layout = ss.SheetLayoutSpec(layout="grid", columns=2, short_edge=1024, captions=False)
    sheet = sl.compose_sheet([None, _solid(64, 64, (10, 200, 10)), None], layout, cells=cells)
    assert sheet.size[0] > 0


def test_captions_change_pixels():
    cells = _composite_cells()
    layout = ss.SheetLayoutSpec(
        layout="grid", columns=3, short_edge=1200, captions=True, background="#000000"
    )
    plain = sl.compose_sheet([None] * 5, layout, cells=cells, captions=["", "", "", "", ""])
    labelled = sl.compose_sheet([None] * 5, layout, cells=cells)
    assert labelled.tobytes() != plain.tobytes()


def test_fit_modes_differ_for_a_non_matching_cell_aspect():
    cells = [ss.SheetCell(id="c1")]
    layout = ss.SheetLayoutSpec(
        layout="grid", columns=1, short_edge=1024, aspect="1:1", captions=False, fit="stretch"
    )
    wide = _solid(800, 100, (255, 255, 255))
    stretched = sl.compose_sheet([wide], layout, cells=cells)
    layout_contain = ss.SheetLayoutSpec(
        layout="grid", columns=1, short_edge=1024, aspect="1:1", captions=False, fit="contain"
    )
    contained = sl.compose_sheet([wide], layout_contain, cells=cells)
    assert stretched.tobytes() != contained.tobytes()


# --------------------------------------------------------------------------- #
# frame picking
# --------------------------------------------------------------------------- #
def test_auto_picks_the_last_frame():
    frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(4)]
    assert sl.pick_frame_index(frames, mode="auto") == 3
    assert sl.pick_frame_index(frames, mode="last") == 3


def test_explicit_index_wins_and_is_clamped():
    frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(4)]
    assert sl.pick_frame_index(frames, explicit=1) == 1
    assert sl.pick_frame_index(frames, explicit=99) == 3
    assert sl.pick_frame_index(frames, explicit=-5) == 0


def test_sharpest_prefers_detail_over_a_flat_frame():
    flat = np.full((64, 64, 3), 128, dtype=np.uint8)
    checker = np.indices((64, 64)).sum(axis=0) % 2
    sharp = np.stack([(checker * 255).astype(np.uint8)] * 3, axis=-1)
    frames = [flat, sharp, flat]
    assert sl.frame_sharpness(sharp) > sl.frame_sharpness(flat)
    assert sl.pick_frame_index(frames, mode="sharpest") == 1


def test_unknown_pick_mode_falls_back_to_auto():
    frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(3)]
    assert sl.pick_frame_index(frames, mode="vibes") == 2


def test_empty_frames_are_safe():
    assert sl.pick_frame_index([]) == 0


# --------------------------------------------------------------------------- #
# array conversion
# --------------------------------------------------------------------------- #
def test_float_arrays_are_converted_to_uint8_rgb():
    image = sl.array_to_image(np.ones((4, 4, 3), dtype=np.float32) * 0.5)
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (127, 127, 127)


def test_grayscale_and_rgba_arrays_are_accepted():
    assert sl.array_to_image(np.zeros((4, 4), dtype=np.uint8)).mode == "RGB"
    assert sl.array_to_image(np.zeros((4, 4, 4), dtype=np.uint8)).mode == "RGB"


def test_compose_from_arrays_end_to_end():
    layout = ss.SheetLayoutSpec(layout="grid", columns=2, short_edge=512, captions=False)
    cells = _cells(3)
    arrays = [np.full((32, 32, 3), 200, dtype=np.uint8) for _ in range(3)]
    sheet = sl.compose_from_arrays(arrays, layout, cells=cells)
    assert sheet.size == sl.sheet_canvas_size(layout)
