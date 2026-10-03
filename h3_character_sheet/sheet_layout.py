# MiniMax H3 Motion Director - character sheet layout and compositing.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Character Sheet Builder: cell placement, frame picking and sheet compositing.

The sheet is composited locally with PIL from the frames the H3 render produced,
so a sheet can be rebuilt (different layout, different picked frames) without
re-sampling anything.

Layouts:

* ``hero-left``  - cell 0 is the hero and spans every row of the left column; the
  remaining cells fill a grid to its right (2 columns + 4 cells = the classic
  "portrait on the left, 2x2 full-body angles on the right").
* ``grid``       - uniform N-column grid, row-major.
* ``turnaround`` - one row, every cell side by side.
* ``custom``     - each cell declares ``place`` (row/col/rowSpan/colSpan).

Pure functions over pixel buffers: no ComfyUI, no torch model, no disk.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .sheet_spec import (
    DEFAULT_SHORT_EDGE,
    PICKS,
    SheetCell,
    SheetLayoutSpec,
    aspect_ratio,
)

CANVAS_ALIGN = 16
_MIN_CELL_PX = 32
_CAPTION_BAND = 22


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def sheet_canvas_size(layout: SheetLayoutSpec) -> tuple[int, int]:
    """Sheet pixel size from the short edge + aspect (aligned for H3 reuse)."""
    ratio = aspect_ratio(layout.aspect)
    short = max(256, int(layout.short_edge or DEFAULT_SHORT_EDGE))
    if ratio >= 1.0:
        height, width = short, int(round(short * ratio))
    else:
        width, height = short, int(round(short / ratio))
    width = max(_MIN_CELL_PX, (width // CANVAS_ALIGN) * CANVAS_ALIGN)
    height = max(_MIN_CELL_PX, (height // CANVAS_ALIGN) * CANVAS_ALIGN)
    return width, height


def _grid_slots(cells: Sequence[SheetCell], layout: SheetLayoutSpec) -> tuple[int, int]:
    """``(total_columns, rows)`` for a layout.

    ``layout.columns`` counts the *cell grid*: for ``hero-left`` that is the grid
    on the right of the hero (so 2 columns + 4 cells puts the four angles in a
    2x2 block beside the hero); for ``grid`` it is the whole sheet.
    """
    count = len(cells)
    if layout.layout == "turnaround":
        return max(1, count), 1
    columns = max(1, int(layout.columns or 1))
    if layout.layout == "hero-left":
        rows = max(1, math.ceil(max(0, count - 1) / columns))
        return columns + 1, rows
    rows = max(1, math.ceil(count / columns))
    return columns, rows


def _custom_slots(cells: Sequence[SheetCell]) -> tuple[int, int]:
    columns = 1
    rows = 1
    for position, cell in enumerate(cells):
        place = cell.place or {}
        col = int(place.get("col", position))
        row = int(place.get("row", 0))
        col_span = max(1, int(place.get("colSpan", 1)))
        row_span = max(1, int(place.get("rowSpan", 1)))
        columns = max(columns, col + col_span)
        rows = max(rows, row + row_span)
    return columns, rows


def layout_rects(
    cells: Sequence[SheetCell],
    layout: SheetLayoutSpec,
) -> tuple[tuple[int, int], list[tuple[int, int, int, int]]]:
    """``((sheet_w, sheet_h), [(x, y, w, h), ...])`` for each cell in order."""
    sheet_w, sheet_h = sheet_canvas_size(layout)
    pad = max(0, int(layout.padding or 0))
    gap = max(0, int(layout.gap or 0))
    content_w = max(_MIN_CELL_PX, sheet_w - 2 * pad)
    content_h = max(_MIN_CELL_PX, sheet_h - 2 * pad)
    count = len(cells)
    if count == 0:
        return (sheet_w, sheet_h), []

    def band_height(rows: int) -> int:
        return _CAPTION_BAND if layout.captions else 0

    if layout.layout == "custom":
        columns, rows = _custom_slots(cells)
        col_w = (content_w - gap * (columns - 1)) / columns
        row_h = (content_h - gap * (rows - 1)) / rows
        rects: list[tuple[int, int, int, int]] = []
        for position, cell in enumerate(cells):
            place = cell.place or {}
            col = int(place.get("col", position % columns))
            row = int(place.get("row", position // columns))
            col_span = max(1, int(place.get("colSpan", 1)))
            row_span = max(1, int(place.get("rowSpan", 1)))
            x = pad + round(col * (col_w + gap))
            y = pad + round(row * (row_h + gap))
            w = round(col_w * col_span + gap * (col_span - 1))
            h = round(row_h * row_span + gap * (row_span - 1))
            rects.append((x, y, max(_MIN_CELL_PX, w), max(_MIN_CELL_PX, h)))
        return (sheet_w, sheet_h), rects

    columns, rows = _grid_slots(cells, layout)
    col_w = (content_w - gap * (columns - 1)) / columns
    row_h = (content_h - gap * (rows - 1)) / rows
    rects = []
    for position in range(count):
        if layout.layout == "hero-left" and position == 0:
            col = 0
            row = 0
            col_span = 1
            row_span = rows
        elif layout.layout == "hero-left":
            slot = position - 1
            col = 1 + (slot % (columns - 1))
            row = slot // (columns - 1)
            col_span = row_span = 1
        else:
            col = position % columns
            row = position // columns
            col_span = row_span = 1
        x = pad + round(col * (col_w + gap))
        y = pad + round(row * (row_h + gap))
        w = round(col_w * col_span + gap * (col_span - 1))
        h = round(row_h * row_span + gap * (row_span - 1))
        if band_height(rows):
            h -= band_height(rows)
        rects.append((x, y, max(_MIN_CELL_PX, w), max(_MIN_CELL_PX, h)))
    return (sheet_w, sheet_h), rects


def _parse_color(text: str, fallback: tuple[int, int, int] = (16, 16, 20)) -> tuple[int, int, int]:
    value = str(text or "").strip().lstrip("#")
    if len(value) == 6:
        try:
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
        except ValueError:
            return fallback
    return fallback


def _fit(image: Image.Image, box: tuple[int, int], mode: str) -> Image.Image:
    """Place ``image`` into ``box`` (w, h) using contain / cover / stretch."""
    box_w, box_h = max(1, box[0]), max(1, box[1])
    src_w, src_h = max(1, image.width), max(1, image.height)
    if mode == "stretch":
        return image.resize((box_w, box_h), Image.LANCZOS)
    scale = min(box_w / src_w, box_h / src_h) if mode == "contain" else max(box_w / src_w, box_h / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    resized = image.resize(new_size, Image.LANCZOS)
    if mode == "cover" and (new_size[0] > box_w or new_size[1] > box_h):
        left = max(0, (new_size[0] - box_w) // 2)
        top = max(0, (new_size[1] - box_h) // 2)
        resized = resized.crop((left, top, left + box_w, top + box_h))
    return resized


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #
def compose_sheet(
    images: Sequence[Image.Image | None],
    layout: SheetLayoutSpec,
    *,
    cells: Sequence[SheetCell] = (),
    captions: Sequence[str] | None = None,
) -> Image.Image:
    """Composite one image per cell into the sheet.

    A missing cell renders as its slot left empty on the background colour, so a
    partially failed run still produces a usable sheet plus visible gaps.
    """
    (sheet_w, sheet_h), rects = layout_rects(cells, layout)
    sheet = Image.new("RGB", (sheet_w, sheet_h), _parse_color(layout.background))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for position, rect in enumerate(rects):
        image = images[position] if position < len(images) else None
        x, y, w, h = rect
        if image is not None:
            placed = _fit(image.convert("RGB"), (w, h), layout.fit)
            sheet.paste(placed, (x + (w - placed.width) // 2, y + (h - placed.height) // 2))
        if layout.captions:
            text = ""
            if captions is not None and position < len(captions):
                text = str(captions[position] or "")
            elif position < len(cells):
                text = cells[position].label
            if text:
                band_y = y + h + 2
                if band_y + _CAPTION_BAND <= sheet_h:
                    draw.text((x + 2, band_y), text, fill=(232, 232, 238), font=font)
    return sheet


def compose_from_arrays(
    arrays: Sequence[np.ndarray | None],
    layout: SheetLayoutSpec,
    *,
    cells: Sequence[SheetCell] = (),
    captions: Sequence[str] | None = None,
) -> Image.Image:
    """Compose straight from float/uint8 HxWx3 numpy arrays."""
    images: list[Image.Image | None] = []
    for array in arrays:
        images.append(array_to_image(array) if array is not None else None)
    return compose_sheet(images, layout, cells=cells, captions=captions)


def array_to_image(array: np.ndarray) -> Image.Image:
    """uint8 or float 0..1 HxWx3 (or HxWx4) array -> PIL RGB image."""
    arr = np.asarray(array)
    if arr.dtype != np.uint8:
        arr = np.clip(arr.astype(np.float32), 0.0, 1.0) * 255.0
        arr = arr.astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.shape[-1] == 4:
        return Image.fromarray(arr, mode="RGBA").convert("RGB")
    return Image.fromarray(arr[:, :, :3], mode="RGB")


# --------------------------------------------------------------------------- #
# frame picking
# --------------------------------------------------------------------------- #
def frame_sharpness(array: np.ndarray) -> float:
    """Variance of the Laplacian (numpy only) used to rank candidate frames.

    Computed on a downscaled grayscale copy: a sheet cell is judged at sheet
    scale, and this keeps the whole picker CPU-cheap for a 22-frame cell.
    """
    arr = np.asarray(array)
    if arr.size == 0:
        return 0.0
    if arr.dtype != np.uint8:
        arr = np.clip(arr.astype(np.float32), 0.0, 1.0) * 255.0
        arr = arr.astype(np.uint8)
    if arr.ndim == 3 and arr.shape[-1] >= 3:
        gray = arr[:, :, :3].mean(axis=2)
    elif arr.ndim == 3:
        gray = arr[:, :, 0].astype(np.float32)
    else:
        gray = arr.astype(np.float32)
    step = max(1, int(max(gray.shape) // 256))
    gray = gray[::step, ::step].astype(np.float32)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return float(gray.std())
    lap = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(lap.var())


def pick_frame_index(
    frames: Sequence[Any],
    *,
    mode: str = "auto",
    explicit: int | None = None,
    allow_sharpest: bool = True,
    skip: int = 0,
    settle: int = 0,
) -> int:
    """Index of the frame a cell should use.

    ``auto`` keeps the pack's reference-generator convention (the chunk's last
    frame is the settled pose), ``sharpest`` ranks by :func:`frame_sharpness`,
    and an explicit index always wins when it is inside the chunk.

    ``skip`` drops leading frames from consideration. With latent continuation the
    first frames of a cell are a re-render of the previous cell's tail, so they are
    a copy of the cell before it and must never be the picked frame.

    ``settle`` keeps only the LAST N frames of the clip. A continuing cell also has to
    *get somewhere*: measured on a real sheet, the body turn lands around frame 8 of 22
    and the clip holds still from there, while ``frame_sharpness`` ranks the frames
    before the turn highest (the hand-over is the sharpest part of the clip - the pose is
    the one the previous cell already had). Ranking the whole clip therefore picks the
    old pose. An explicit index is still honoured (it is the user's own choice) and at
    least one frame always stays a candidate.
    """
    count = len(frames)
    if count <= 0:
        return 0
    if explicit is not None:
        return max(0, min(count - 1, int(explicit)))
    chosen = str(mode or "auto").strip().lower()
    if chosen not in PICKS:
        chosen = "auto"
    start = max(0, int(skip or 0))
    if int(settle or 0) > 0 and count > int(settle):
        start = max(start, count - int(settle))
    start = max(0, min(start, count - 1))
    if chosen == "last":
        return count - 1
    if chosen == "sharpest" and allow_sharpest:
        scores = [frame_sharpness(frame) for frame in frames]
        return int(max(range(start, count), key=lambda index: scores[index]))
    return count - 1


__all__ = [
    "CANVAS_ALIGN",
    "array_to_image",
    "compose_from_arrays",
    "compose_sheet",
    "frame_sharpness",
    "layout_rects",
    "pick_frame_index",
    "sheet_canvas_size",
]
