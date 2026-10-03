"""Character Sheet Maker - run planning (pack standalone, no ComfyUI needed).

Pinned here: the cell work items the graph is built from (prompt / frames / seed /
size), the reference slot mapping the core H3 node expects, and the payload the
grid node receives.
"""

from __future__ import annotations

import pytest

from h3cs import planner as pl
from h3cs import sheet_spec as ss


def _spec(**overrides):
    payload = {
        "name": "hero sheet!",
        "globalPrompt": "a woman in her thirties",
        "refs": {
            "pictures": [
                {"imageFile": "face.png", "role": "face and hair"},
                {"imageFile": "body.png", "role": "body proportions"},
            ],
            "videos": [{"videoFile": "cloth.mp4", "role": "clothing and body"}],
            "audios": [{"audioFile": "voice.wav", "role": "voice"}],
        },
        "render": {"framesPerCell": 5, "seed": 100},
        "cells": [
            {"id": "hero", "view": "portrait", "expression": "smile"},
            {"id": "front", "view": "front", "pose": "t-pose", "frames": 22, "seed": 777},
            {"id": "off", "view": "back", "enabled": False},
        ],
    }
    payload.update(overrides)
    return ss.parse_sheet_spec(payload)


# --------------------------------------------------------------------------- #
# sizes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "requested,expected",
    [(1024, 1024), (1000, 992), (256, 256), (100, 256), (99999, 2048), ("junk", 1024)],
)
def test_cell_size_snaps_to_the_32px_grid(requested, expected):
    assert pl.align_cell_size(requested) == expected


# --------------------------------------------------------------------------- #
# work items
# --------------------------------------------------------------------------- #
def test_work_items_cover_only_enabled_cells_in_order():
    items = pl.cell_work_items(_spec(), cell_size=1024)
    assert [item["id"] for item in items] == ["hero", "front"]
    assert [item["index"] for item in items] == [0, 1]


def test_work_items_carry_the_cell_prompt_and_frames():
    spec = _spec()
    items = pl.cell_work_items(spec, cell_size=1024)
    assert items[0]["prompt"] == ss.build_cell_prompt(spec, spec.cells[0])
    assert items[0]["frames"] == 5
    assert items[1]["frames"] == 22  # the cell's own length wins over the default
    assert items[0]["ref_image_size"] == "match"
    # 9:16 by default: cell_size is the SHORT edge, so people are not cropped
    assert (items[0]["width"], items[0]["height"]) == (576, 1024)


def test_cell_aspect_shapes_the_cell_and_per_cell_aspect_wins():
    spec = _spec()
    spec.render.cell_aspect = "1:1"
    assert [(item["width"], item["height"]) for item in pl.cell_work_items(spec, cell_size=1024)] == [
        (1024, 1024),
        (1024, 1024),
    ]

    spec.render.cell_aspect = "9:16"
    spec.cells[1].aspect = "16:9"
    items = pl.cell_work_items(spec, cell_size=1024)
    assert (items[0]["width"], items[0]["height"]) == (576, 1024)
    assert (items[1]["width"], items[1]["height"]) == (1024, 576)


def test_cell_render_size_snaps_to_the_32px_grid_and_survives_junk():
    for aspect in ("9:16", "3:4", "2:3", "1:1", "4:3", "16:9", "21:9", "nonsense"):
        width, height = pl.cell_render_size(1024, aspect)
        assert width % 32 == 0 and height % 32 == 0, f"{aspect}: {width}x{height}"
        assert width >= pl.CELL_SIZE_STEP and height >= pl.CELL_SIZE_STEP
    assert pl.cell_render_size(1024, "nonsense") == pl.cell_render_size(1024, ss.DEFAULT_CELL_ASPECT)
    # 21:9 is ultrawide: the SHORT edge is the height, snapped to the 32px grid.
    assert pl.cell_render_size(1024, "21:9") == (1024, 416)


def test_work_items_give_every_cell_its_own_seed():
    items = pl.cell_work_items(_spec(), cell_size=1024)
    assert items[0]["seed"] == 100  # sheet seed + 0 * stride
    assert items[1]["seed"] == 777  # explicit per-cell seed wins
    assert pl.cell_seed(_spec(), ss.SheetCell(id="x", seed=5), 3) == 5
    assert pl.cell_seed(_spec(), ss.SheetCell(id="y"), 2) == 100 + 2 * pl.SEED_STRIDE


def test_cell_size_is_passed_through_to_the_render():
    items = pl.cell_work_items(_spec(), cell_size=1536)
    # 9:16 means the short edge is the WIDTH, so a 1536 short edge is 864x1536
    assert {item["width"] for item in items} == {864}
    assert {item["height"] for item in items} == {1536}


# --------------------------------------------------------------------------- #
# references
# --------------------------------------------------------------------------- #
def test_reference_slots_match_the_core_node_autogrow_keys():
    plan = pl.reference_plan(_spec())
    # Autogrow inputs are addressed as <group>.<template><index> in a prompt - the
    # group id and the template prefix are both declared by the core node.
    assert [item["slot"] for item in plan["pictures"]] == [
        "ref_images.ref_image_0", "ref_images.ref_image_1",
    ]
    assert [item["slot_id"] for item in plan["pictures"]] == ["ref_image_0", "ref_image_1"]
    assert plan["pictures"][0]["file"] == "face.png"
    assert plan["pictures"][0]["role"] == "face and hair"
    assert plan["videos"][0]["slot"] == "ref_videos.ref_video_0"
    assert plan["videos"][0]["audio_slot"] == "ref_video_audios.ref_video_audio_0"
    assert plan["videos"][0]["file"] == "cloth.mp4"
    assert [item["slot"] for item in plan["audios"]] == ["ref_audios.ref_audio_0"]


def test_disabled_references_are_not_wired():
    spec = _spec(refs={"pictures": [{"imageFile": "a.png"}, {"imageFile": "b.png", "enabled": False}]})
    plan = pl.reference_plan(spec)
    assert [item["file"] for item in plan["pictures"]] == ["a.png"]


def test_reference_limits_still_apply_to_the_wiring():
    spec = ss.parse_sheet_spec({"refs": {"pictures": [{"imageFile": f"{i}.png"} for i in range(12)]}})
    assert len(pl.reference_plan(spec)["pictures"]) == ss.MAX_PICTURES


def test_audio_references_are_detected():
    assert pl.uses_audio_references(_spec()) is True
    assert pl.uses_audio_references(_spec(refs={"pictures": [{"imageFile": "a.png"}]})) is False


# --------------------------------------------------------------------------- #
# payload + summary
# --------------------------------------------------------------------------- #
def test_grid_payload_drops_disabled_cells_and_renames():
    payload = pl.grid_payload(_spec(), name="final_name")
    assert payload["name"] == "final_name"
    assert [cell["id"] for cell in payload["cells"]] == ["hero", "front"]


def test_work_summary_reports_counts_and_warnings():
    spec = _spec()
    lines = pl.work_summary(spec, pl.cell_work_items(spec, cell_size=1024))
    text = "\n".join(lines)
    assert "2 cell(s)" in text
    assert "27 frame(s) to sample" in text
    assert "hero-left" in text
    assert "2 picture(s), 1 video(s), 1 audio(s)" in text


def test_cell_slots_are_sequential_and_capped():
    assert pl.cell_slots(3) == ["cells.cell_0", "cells.cell_1", "cells.cell_2"]
    assert pl.cell_slots(0) == []
    assert len(pl.cell_slots(999)) == 24
