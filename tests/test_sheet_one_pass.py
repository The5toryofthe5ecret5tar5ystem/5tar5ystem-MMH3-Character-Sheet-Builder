# ComfyUI-H3-Character-Sheet - the one-pass sheet.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Tests for the one-pass sheet: the whole sheet from ONE H3 render, sliced back into panels.

This is the pack's DEFAULT path, so what these tests pin is the contract it has to keep: one
sampling pass at H3's shortest grid, a canvas the resolution control (or the guidance ceiling)
decides, a prompt that describes every panel in the cells' own words, panels sliced back out at the
boxes the prompt asked for, and a sheet folder that reads like a per-cell render's while never
pretending to have per-cell frames it did not render.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from comfy_execution.graph_utils import GraphBuilder

from h3cs import one_pass as op
from h3cs import sheet_spec as ss
from h3cs import sheet_store as store_mod
from h3cs.nodes import grid as grid_node, onepass as onepass_node, sheet as sheet_node
from h3cs.planner import grid_payload, reference_plan

from tests.test_grid_node import _batch, _spec as _grid_spec  # noqa: E402  (shared fixtures)

#: Everything a one-pass expansion may use - the per-cell node set, minus everything that is
#: per-cell, plus the one-pass sink. Kept in step with ``test_sheet_graph.ALLOWED_NODE_TYPES``.
ALLOWED_ONE_PASS_TYPES = {
    "LoadImage",
    "LoadVideo",
    "GetVideoComponents",
    "LoadAudio",
    "MiniMaxH3ReferenceToVideo",
    "MiniMaxH3SigmaShift",
    "KSamplerSelect",
    "BasicScheduler",
    "BasicGuider",
    "RandomNoise",
    "SamplerCustomAdvanced",
    "VAEDecode",
    "H3SheetOnePassSink",
    # The suite's join: the pack's own pass-through that waits for every board (see join.py). It
    # only exists in a suite expansion, and the graph's type allow-list has to know it.
    "H3SheetJoin",
}

_FIVE_VIEWS = ("face", "portrait", "front", "profile", "back")


@pytest.fixture()
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "sheets_root", lambda: tmp_path / "minimax_sheets")
    return tmp_path


def _payload(**overrides):
    payload = {
        "name": "one-pass sheet",
        "globalPrompt": "a woman in her thirties with copper hair",
        "negativePrompt": "text, watermark",
        "refs": {"pictures": [{"imageFile": "face.png", "role": "face and hair"}]},
        "sheet": {"layout": "turnaround", "aspect": "21:9", "shortEdge": 2048, "captions": False},
        "cells": [{"id": view, "view": view} for view in _FIVE_VIEWS],
    }
    payload.update(overrides)
    return payload


def _spec(**overrides) -> ss.SheetSpec:
    return ss.parse_sheet_spec(_payload(**overrides))


# --------------------------------------------------------------------------- #
# canvas: the sheet's layout, at the size the control or the ceiling decides
# --------------------------------------------------------------------------- #
def test_the_canvas_is_the_sheet_canvas_snapped_to_the_one_pass_grid():
    spec = _spec(sheet={"layout": "hero-left", "aspect": "3:2", "shortEdge": 1536})
    width, height = op.one_pass_size(spec)
    # 1536 * 1.5 = 2304, already on both grids: a one-pass render of a normal sheet does not resize.
    assert (width, height) == (2304, 1536)
    assert width % ss.ONE_PASS_ALIGN == 0 and height % ss.ONE_PASS_ALIGN == 0


def test_a_canvas_nobody_chose_is_scaled_to_the_guidance_ceiling():
    spec = _spec()  # 21:9 at a 2048 short edge = 9.8 MP, far past one pass
    plan = op.one_pass_plan(spec)
    assert plan["pixels"] <= ss.ONE_PASS_MAX_PIXELS * 1.02, (
        f"a one-pass render must respect the guidance ceiling, got {plan['pixels']}"
    )
    assert plan["width"] % ss.ONE_PASS_ALIGN == 0 and plan["height"] % ss.ONE_PASS_ALIGN == 0
    # Same layout, fewer pixels: the aspect survives the scaling.
    assert abs(plan["width"] / plan["height"] - 21 / 9) < 0.1
    assert any("MP is the budget" in note for note in plan["notes"]), plan["notes"]


def test_a_chosen_resolution_is_honoured_above_the_ceiling():
    """4K is a little over the guidance ceiling, and it is the user's call - not a clamp."""
    spec = _spec(
        sheet={"layout": "hero-left", "aspect": "3:2", "shortEdge": 2176},
        render={"resolution": "4k"},
    )
    plan = op.one_pass_plan(spec)
    assert plan["pixels"] > ss.ONE_PASS_MAX_PIXELS, "the chosen size is rendered as chosen"
    assert (plan["width"], plan["height"]) == (3264, 2176)
    assert any("honoured as-is" in note for note in plan["notes"]), plan["notes"]
    # ... and the frame is reported as the cost it is, rather than hidden.
    assert any("whole cost of the render" in note for note in plan["notes"])


def test_a_sheet_within_the_ceiling_is_not_scaled():
    plan = op.one_pass_plan(
        _spec(sheet={"layout": "hero-left", "aspect": "3:2", "shortEdge": 1536})
    )
    assert plan["notes"] == []


def test_the_resolution_choices_pair_a_sheet_size_with_a_cell_size():
    assert [choice[0] for choice in ss.RESOLUTION_CHOICES] == ["1080p", "1440p", "4k"]
    for key, label, short_edge, cell_size in ss.RESOLUTION_CHOICES:
        assert label
        assert short_edge % ss.ONE_PASS_ALIGN == 0, f"{key}: the grid the pass snaps to"
        assert 256 <= cell_size <= 2048, f"{key}: inside the cell_size widget's own bounds"
        assert ss.parse_sheet_spec({"render": {"resolution": label}}).render.resolution == key


def test_the_resolution_flag_accepts_what_people_call_the_sizes():
    for written, expected in (
        ("4K", "4k"), ("2160p", "4k"), ("3840", "4k"), ("uhd", "4k"),
        ("1080", "1080p"), ("1920", "1080p"), ("1440p", "1440p"), ("2560", "1440p"),
    ):
        assert ss.parse_sheet_spec({"render": {"resolution": written}}).render.resolution == expected
    # Anything else means "set by hand", and the ceiling then applies.
    assert ss.parse_sheet_spec({"render": {"resolution": "8k"}}).render.resolution == ""
    assert ss.parse_sheet_spec({}).render.resolution == ""


# --------------------------------------------------------------------------- #
# prompt: every panel, in the cells' own words
# --------------------------------------------------------------------------- #
def test_the_prompt_describes_every_panel_once():
    spec = _spec()
    plan = op.one_pass_plan(spec)
    prompt = plan["prompt"]
    for position in range(1, len(_FIVE_VIEWS) + 1):
        assert f"Panel {position} of 5" in prompt, prompt
    assert "side by side in a single row" in prompt
    assert "The whole image is " in prompt
    # The geometry is the layout's own: one box per panel, from layout_rects.
    assert prompt.count("x=") == len(_FIVE_VIEWS)
    for x, y, width, height in plan["rects"]:
        assert f"x={x}, y={y}, {width}x{height}" in prompt


def test_the_shared_blocks_appear_exactly_once():
    spec = _spec()
    prompt = op.one_pass_plan(spec)["prompt"]
    assert prompt.count(spec.global_prompt) == 1
    assert prompt.count("Do not include:") == 1
    assert prompt.count("is the sole source of") == 1
    # The per-cell closing line ("Single person against ...") is hoisted: the backdrop is named
    # once in the header instead of once per panel.
    assert prompt.count("Single person against") == 0
    assert prompt.count("Across every panel the same person is shown") == 1


def test_the_panel_sentences_are_the_cells_own_sentences():
    spec = _spec()
    prompt = op.one_pass_plan(spec)["prompt"]
    for cell in spec.enabled_cells:
        shot = " ".join(ss.cell_shot_lines(spec, cell))
        assert shot in prompt, f"{cell.id}'s wording drifted from the cell prompt"
        assert shot in ss.build_cell_prompt(spec, cell)


def test_a_one_pass_prompt_hides_only_what_no_panel_can_show():
    with_body = op.one_pass_plan(_spec(
        refs={"pictures": [
            {"imageFile": "face.png", "role": "face and hair"},
            {"imageFile": "outfit.png", "role": "body shape, clothing"},
        ]},
    ))["prompt"]
    assert "clothing" in with_body, "a full-body panel can show the outfit"
    assert "Wear the clothing exactly as in the reference" in with_body

    face_only = op.one_pass_plan(_spec(cells=[{"id": "face", "view": "face"}]))["prompt"]
    assert "clothing" not in face_only, (
        "a face-only sheet must not name an attribute no panel can show"
    )
    assert "Wear the clothing" not in face_only


def test_extra_prompts_travel_with_their_panel():
    spec = _spec(cells=[
        {"id": "front", "view": "front", "extraPrompt": "hands relaxed at the sides"},
        {"id": "back", "view": "back"},
    ])
    prompt = op.one_pass_plan(spec)["prompt"]
    panel = next(line for line in prompt.splitlines() if line.startswith("- Panel 1 of 2"))
    assert "hands relaxed at the sides" in panel


# --------------------------------------------------------------------------- #
# the sheet prompt: H3's own sections, and the layout said in words
# --------------------------------------------------------------------------- #
def test_the_sheet_prompt_is_written_in_h3_s_own_sections():
    """H3 is trained on the caption structure, so the sheet prompt is shaped like one."""
    prompt = op.one_pass_plan(_spec())["prompt"]
    order = ["subject_definitions:", "summary:", "retention_analysis:", "detailed_description:",
             "overall_soundscape:", "non_diegetic_music:"]
    positions = [prompt.find(label) for label in order]
    assert all(position >= 0 for position in positions), prompt
    assert positions == sorted(positions), "the blocks keep H3's order"
    # The summary names the views, and the sheet is asked for as ONE static image.
    summary = prompt[prompt.find("summary:"):prompt.find("retention_analysis:")]
    assert "static character sheet" in summary
    assert "5 views at the same time" in summary
    assert "Face close up" in summary and "Full body" in summary
    # A still sheet: H3 renders a clip, and the frames must not turn into a turntable.
    assert "stays completely unchanged to the last frame" in prompt
    # The audio branch is named rather than left to chance.
    assert "The sheet is a still image - no speech" in prompt
    assert prompt.rstrip().endswith("non_diegetic_music:\nNone.")


def test_a_hero_sheet_says_which_column_holds_what():
    """The reported failure: hero + 4 came out as three columns with two panels missing.

    Pixel boxes were the only word on the arrangement, and H3 flattened the 2x2 half into two
    more full-height columns. The prompt now also says the arrangement in the words a person
    would use, per column and per panel.
    """
    spec = _spec(sheet={"layout": "hero-left", "aspect": "3:2", "shortEdge": 1536})
    plan = op.one_pass_plan(spec)
    prompt = plan["prompt"]
    assert "5 panels in 3 columns of equal width" in prompt
    assert "the left column holds one tall panel that fills the full height" in prompt
    assert prompt.count("two panels stacked one above the other") == 2, "middle and right columns"
    assert "with even gaps between the panels" in prompt
    # ...and every panel line carries its own place, next to its box.
    assert "(the left column, full height; x=" in prompt
    assert "(the middle column, upper half; x=" in prompt
    assert "(the middle column, lower half; x=" in prompt
    assert "(the right column, upper half; x=" in prompt
    assert "(the right column, lower half; x=" in prompt
    # The panels are not allowed to merge, drop, reorder or stretch.
    assert "none is merged with another, dropped, reordered" in prompt
    # One scale and one ground line across the full-body panels, which is what makes a sheet
    # read as one sheet instead of three unrelated pictures.
    assert "one common ground line" in prompt
    assert "one common figure scale" in prompt
    # A hex-grid sheet without rows keeps the plain column wording.
    rows = op.one_pass_plan(_spec(sheet={"layout": "grid", "columns": 3, "aspect": "3:2",
                                        "shortEdge": 1536}))["prompt"]
    assert "3-column, 2-row grid" in rows


def test_a_sheet_of_one_panel_is_the_whole_frame():
    prompt = op.one_pass_plan(_spec(cells=[{"id": "front", "view": "front"}]))["prompt"]
    assert "(the whole frame; x=" in prompt, "one panel is not a column: it is the frame"
    assert "column" not in prompt.split("detailed_description:")[1], (
        "no column arithmetic for a sheet that has one panel"
    )
    assert "The panel is drawn:" in prompt, "and the number is not spelled out as '1 panels'"


def test_the_identity_picture_s_outfit_is_named_as_replaced():
    """The other half of "the clothing comes only from <Picture 2>".

    A reference has no per-picture weight, and the identity picture is usually a whole person in
    clothes - so a run whose face picture wore a low-cut dress kept rendering the dress even
    though the prompt named <Picture 2> as the clothing owner. The prompt now says outright that
    the outfit in the identity picture is replaced.
    """
    spec = _spec(refs={"pictures": [
        {"imageFile": "face.png", "role": "face and hair"},
        {"imageFile": "outfit.png", "role": "body and clothing"},
    ]})
    prompt = op.one_pass_plan(spec)["prompt"]
    assert "The person in <Picture 1> is wearing something else: that outfit is replaced." in prompt
    assert "do not mix the two garments" in prompt
    # A single reference has nothing to replace, and saying it would be nonsense.
    alone = op.one_pass_plan(_spec())["prompt"]
    assert "that outfit is replaced" not in alone
    # Nor when the identity picture is itself the clothing owner.
    same = op.one_pass_plan(_spec(refs={"pictures": [
        {"imageFile": "both.png", "role": "face, hair and clothing"},
    ]}))["prompt"]
    assert "that outfit is replaced" not in same


# --------------------------------------------------------------------------- #
# the render: one pass, H3's shortest grid
# --------------------------------------------------------------------------- #
def test_the_render_always_asks_for_h3_s_shortest_grid():
    plan = op.one_pass_plan(_spec())
    assert plan["frames"] == 5 == ss.align_h3_frames(plan["frames"])
    assert plan["sheetFrame"] == 0, "the sheet is the first frame of the clip"


def test_the_expansion_is_exactly_one_h3_pass():
    spec = _spec()
    plan = op.one_pass_plan(spec)
    graph = GraphBuilder()
    outputs = sheet_node.build_one_pass_graph(
        graph,
        model="MODEL",
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        plan=plan,
        refs=reference_plan(spec),
        payload=grid_payload(spec, name="one-pass sheet"),
        name="one-pass sheet",
    )
    assert len(outputs) == 4, "the one-pass render reports the same four outputs as the per-cell one"
    built = graph.finalize()
    types = [node["class_type"] for node in built.values()]
    assert set(types) <= ALLOWED_ONE_PASS_TYPES, sorted(set(types) - ALLOWED_ONE_PASS_TYPES)
    assert types.count("MiniMaxH3ReferenceToVideo") == 1, "one pass, not one per cell"

    ref2va = next(node for node in built.values() if node["class_type"] == "MiniMaxH3ReferenceToVideo")
    assert ref2va["inputs"]["length"] == 5
    assert ref2va["inputs"]["width"] == plan["width"]
    assert ref2va["inputs"]["height"] == plan["height"]
    assert ref2va["inputs"]["prompt"] == plan["prompt"]
    assert ref2va["inputs"]["ref_image_size"] == "match"

    # Nothing per-cell survives into a one-pass render: no ordering, no per-cell saves, no clips.
    for absent in ("H3SheetOrderGate", "H3SheetCellSink", "H3SheetGrid", "SaveVideo", "ImageFromBatch"):
        assert absent not in types, f"{absent} has no meaning in a one-pass render"


# --------------------------------------------------------------------------- #
# slicing: the panels come back out, where the prompt asked for them
# --------------------------------------------------------------------------- #
def _marked_sheet(plan: dict, *, frames: int = 5) -> torch.Tensor:
    """A fake clip whose sheet frame has one distinct colour per panel box."""
    width, height = int(plan["width"]), int(plan["height"])
    still = np.zeros((height, width, 3), dtype=np.uint8)
    for position, (x, y, box_w, box_h) in enumerate(plan["rects"], start=1):
        still[y : y + box_h, x : x + box_w] = (position * 20, position * 30, position * 40)
    clip = np.repeat(still[None, ...], frames, axis=0).astype(np.float32) / 255.0
    return torch.from_numpy(clip)


def test_the_panels_are_sliced_at_the_boxes_the_prompt_asked_for():
    plan = op.one_pass_plan(_spec())
    frames = _marked_sheet(plan)
    arrays = [frame.numpy() * 255 for frame in frames]
    sliced = op.slice_panels([array.astype(np.uint8) for array in arrays], plan)

    assert [cell_id for cell_id, _array in sliced] == list(_FIVE_VIEWS)
    for position, (_cell_id, array) in enumerate(sliced, start=1):
        x, y, box_w, box_h = plan["rects"][position - 1]
        assert array.shape[:2] == (box_h, box_w), f"panel {position} is its own box, not a stretch"
        # The slice really is that panel of the image, not an average of the whole sheet.
        assert tuple(int(value) for value in array[box_h // 2, box_w // 2]) == (
            position * 20, position * 30, position * 40,
        )


def test_a_slice_is_clamped_to_the_image_never_padded_over_it():
    """A backend that returns a different size must not become a wrong crop with black edges."""
    plan = op.one_pass_plan(_spec())
    still = np.zeros((64, 64, 3), dtype=np.uint8)
    still[:, :] = (10, 20, 30)
    sliced = op.slice_panels([still], plan)
    assert sliced, "the boxes still produce panels"
    for _cell_id, array in sliced:
        assert array.shape[0] <= 64 and array.shape[1] <= 64
        assert int(array.min()) == 10 and int(array.max()) == 30, "no pad colour crept in"


def test_panels_are_letterboxed_onto_one_batch_not_stretched():
    # hero-left: the hero panel spans the sheet's height and the rest are grid cells, so the
    # boxes really are different shapes - which is the case the batch has to cope with.
    plan = op.one_pass_plan(
        _spec(sheet={"layout": "hero-left", "columns": 2, "aspect": "3:2", "shortEdge": 1536})
    )
    # The clip, exactly as the sink hands it over: the slicer picks plan["sheetFrame"] itself.
    clip = [frame.numpy().astype(np.uint8) for frame in _marked_sheet(plan)]
    sliced = op.slice_panels(clip, plan)
    shapes = {array.shape[:2] for _cell, array in sliced}
    assert len(shapes) > 1, f"these panels really are different shapes: {shapes}"

    padded = op.pad_panels(sliced)
    assert len({array.shape for array in padded}) == 1, "one batch means one size"
    height, width = padded[0].shape[:2]
    for (cell_id, array), canvas in zip(sliced, padded):
        assert canvas.shape[:2] == (height, width)
        top = (height - array.shape[0]) // 2
        left = (width - array.shape[1]) // 2
        centre = canvas[top + array.shape[0] // 2, left + array.shape[1] // 2]
        assert tuple(int(value) for value in centre) == tuple(
            int(value) for value in array[array.shape[0] // 2, array.shape[1] // 2]
        ), f"{cell_id} kept its own pixels, centred"


# --------------------------------------------------------------------------- #
# the sheet folder: a one-pass sheet reads like a per-cell render
# --------------------------------------------------------------------------- #
def _run_one_pass(outputs, *, frames=5, keep=True, payload=None):
    plan = op.one_pass_plan(
        ss.parse_sheet_spec(payload if payload is not None else _payload())
    )
    return onepass_node.H3SheetOnePassSink.execute(
        images=_marked_sheet(plan, frames=frames),
        sheet_data=json.dumps(payload if payload is not None else _payload()),
        name="one-pass sheet",
        keep_frames=keep,
    )


def test_the_sink_writes_the_sheet_the_frames_the_panels_and_the_block(outputs):
    out = _run_one_pass(outputs)
    store = store_mod.SheetStore("one-pass sheet")

    assert store.sheet_path.is_file(), "the sheet takes the sheet's own file slot"
    assert [path.name for path in store.pass_frame_files()] == [
        f"f{position:04d}.png" for position in range(5)
    ]
    assert out.args[0].shape[0] == 1, "the sheet output is one image"
    assert out.args[1].shape[0] == len(_FIVE_VIEWS), "and the panels output is one per panel"
    assert out.args[3] == str(store.dir)

    # Each panel is written where a per-cell render writes its cell, so the panel's Results tab,
    # the picker, the composite path and the RefMod export all read it without knowing the mode.
    for view in _FIVE_VIEWS:
        assert store.cell_pick_path(view).is_file(), f"{view} has a picked still"
        assert len(store.frame_files(view)) == 1, f"{view} is a rendered one-frame cell"

    manifest = store.read_manifest()
    assert manifest["cells"] == {}, "a one-pass render must not claim per-cell frames"
    block = manifest["onePass"]
    assert block["frames"] == 5
    assert block["width"] and block["height"]
    assert block["panels"] == list(_FIVE_VIEWS)
    assert block["prompt"].startswith("a woman in her thirties with copper hair")
    assert "a woman in her thirties with copper hair" in block["prompt"]

    report = store.report_path.read_text()
    assert "One-pass sheet: the whole sheet from ONE H3 render" in report
    assert "Sliced 5 panel image(s)" in report
    assert "guidance, not a constraint" in report


def test_the_listing_shows_the_panels_and_the_pass(outputs):
    _run_one_pass(outputs)
    listing = store_mod.SheetStore("one-pass sheet").scan()
    assert listing["sheetUrl"], "the panel shows the sheet through the sheet slot"
    assert listing["onePass"]["active"] is True
    assert len(listing["onePass"]["frames"]) == 5
    assert listing["onePass"]["frames"][0]["url"]
    assert listing["onePass"]["size"][0] > 0
    # The panels look like rendered cells, because that is what a per-view consumer expects.
    assert [cell["id"] for cell in listing["cells"]] == list(_FIVE_VIEWS)
    assert listing["counts"]["rendered"] == len(_FIVE_VIEWS)
    assert all(cell["cellUrl"] for cell in listing["cells"])


def test_keep_frames_off_keeps_the_sheet_and_the_panels(outputs):
    _run_one_pass(outputs, keep=False)
    store = store_mod.SheetStore("one-pass sheet")
    assert store.pass_frame_files() == [], "the clip's frames are optional"
    assert store.sheet_path.is_file()
    assert store.cell_pick_path("face").is_file(), "but the panels are the per-view deliverable"


def test_a_rebuild_recomposites_the_panels_without_touching_the_render(outputs):
    """A one-pass sheet's panels ARE per-view images, so a re-compose is a real re-layout.

    It writes the next dated file and leaves the render's own sheet on disk: the sheet H3 drew in
    one pass is a finished image, not a draft to overwrite.
    """
    _run_one_pass(outputs)
    store = store_mod.SheetStore("one-pass sheet")
    rendered = store.sheet_path.name

    result = store.rebuild_sheet(store.read_manifest()["spec"], new_export=True)

    assert result["missing"] == [], "every panel has a frame to compose from"
    assert (store.dir / rendered).is_file(), "the render's own sheet is still on disk"
    assert store.sheet_path.name != rendered, "a re-compose writes the next dated file"
    assert set(store.read_picks()) == set(_FIVE_VIEWS)


def test_a_one_pass_sheet_with_no_panels_is_left_alone(outputs):
    """The guard: a render whose slices did not land must not be replaced by an empty canvas."""
    _run_one_pass(outputs)
    store = store_mod.SheetStore("one-pass sheet")
    rendered = store.sheet_path.name
    for view in _FIVE_VIEWS:
        for path in store.frame_files(view) + [store.cell_pick_path(view)]:
            path.unlink()
    before = sorted(path.name for path in store.dir.glob("*.png"))

    result = store.rebuild_sheet(store.read_manifest()["spec"], new_export=True)

    assert result.get("onePass") is True, "there is nothing to compose"
    assert store.sheet_path.name == rendered
    assert sorted(path.name for path in store.dir.glob("*.png")) == before


def test_notes_from_the_builder_land_in_the_report_on_disk(outputs):
    payload = _grid_spec()
    payload["notes"] = ["Live preview: off (render.livePreview)."]
    out = grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(payload),
        name="notes sheet",
        keep_frames=True,
        cells={"cell_0": _batch(2), "cell_1": _batch(2)},
    )
    report = store_mod.SheetStore("notes sheet").report_path.read_text()
    assert "Live preview: off (render.livePreview)." in report
    assert "Live preview: off" in out.args[2], "the report output carries the same text"


# --------------------------------------------------------------------------- #
# wiring: the schemas, the preview, and the knob that picks the mode
# --------------------------------------------------------------------------- #
#: Core modules whose V3 classes the one-pass graph uses. Named explicitly because
#: ``init_extra_nodes`` is async and only runs at server start, so a test process has to read them
#: itself - from the same ``define_schema()`` the server publishes as ``/object_info``.
_V3_MODULES = (
    "comfy_extras.nodes_minimax_h3",
    "comfy_extras.nodes_video",
    "comfy_extras.nodes_audio",
    "comfy_extras.nodes_custom_sampler",
)


def _installed_node_classes() -> dict:
    """Node type -> class, from ComfyUI's own registry (base nodes) plus the V3 extras."""
    import importlib
    import inspect

    import nodes as core_nodes

    mapping = dict(core_nodes.NODE_CLASS_MAPPINGS)
    for module_name in _V3_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - a lean core simply resolves fewer types
            continue
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            schema_fn = getattr(cls, "define_schema", None)
            if not callable(schema_fn):
                continue
            try:
                node_id = getattr(schema_fn(), "node_id", None)
            except Exception:  # noqa: BLE001
                continue
            if node_id and str(node_id) not in mapping:
                mapping[str(node_id)] = cls
    return mapping


def _declared_inputs(cls) -> dict:
    schema = cls.INPUT_TYPES() or {}
    return {**schema.get("required", {}), **schema.get("optional", {})}


def _autogrow_prefix(entry) -> str:
    """The child-name prefix an autogrow input declares (``"ref_image_"``), or ``""``."""
    meta = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
    template = meta.get("template")
    if isinstance(template, dict):
        return str(template.get("prefix") or "")
    return str(getattr(template, "prefix", "") or "")


def test_every_wired_input_exists_in_the_target_node_s_schema():
    """The expansion is checked against ComfyUI's own schemas, not against a list here.

    A typo in an input name (or a core node renaming one - the reference inputs are V3 autogrow
    groups, so they are wired as ``ref_images.ref_image_0``) would otherwise only surface when
    someone queued a render, after a model load. Types this process cannot resolve are covered by
    the allowed-types test instead.
    """
    mapping = _installed_node_classes()
    mapping["H3SheetOnePassSink"] = onepass_node.H3SheetOnePassSink
    spec = _spec(
        refs={
            "pictures": [{"imageFile": "face.png", "role": "face and hair"}],
            "videos": [{"videoFile": "body.mp4", "role": "body and clothing"}],
            "audios": [{"audioFile": "voice.wav", "role": "voice"}],
        },
        cells=[{"id": "front", "view": "front"}, {"id": "profile", "view": "profile"}],
    )
    graph = GraphBuilder()
    sheet_node.build_one_pass_graph(
        graph,
        model="MODEL",
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        plan=op.one_pass_plan(spec),
        refs=reference_plan(spec),
        payload=grid_payload(spec, name="one-pass sheet"),
        name="one-pass sheet",
    )

    validated: list[str] = []
    for node in graph.finalize().values():
        class_type = node["class_type"]
        cls = mapping.get(class_type)
        if cls is None:
            assert class_type in ALLOWED_ONE_PASS_TYPES, f"{class_type} is unknown"
            continue
        declared = _declared_inputs(cls)
        for name in node["inputs"]:
            if name in declared:
                continue
            # A V3 autogrow input is wired as ``<group>.<child>``: the group is declared, and the
            # child has to carry the prefix that group's own template declares.
            group, _, child = name.partition(".")
            entry = declared.get(group)
            assert entry is not None, f"{class_type} has no input {name!r}"
            assert child, f"{class_type}.{group} is not a list, but {name!r} addresses one"
            prefix = _autogrow_prefix(entry)
            assert prefix and child.startswith(prefix), (
                f"{class_type}.{group} children start with {prefix!r}, not {child!r}"
            )
        absent = [name for name in (cls.INPUT_TYPES() or {}).get("required", {})
                  if name not in node["inputs"]]
        assert absent == [], f"{class_type} is missing required inputs {absent}"
        validated.append(class_type)

    assert "H3SheetOnePassSink" in validated, "the render's own sink is always checkable"
    if "MiniMaxH3ReferenceToVideo" in mapping:
        assert "MiniMaxH3ReferenceToVideo" in validated, "the reference wiring must be checked"
    assert len(set(validated)) >= 3, f"almost nothing was validated: {sorted(set(validated))}"


def test_the_one_pass_render_streams_to_the_panel_as_a_whole_sheet():
    """The one-pass render uses the pack's own live preview, and says which kind of stream it is.

    It is ONE render: without the stream there is nothing on screen until the whole sheet is done,
    which is the case where the panel's preview matters most. The per-cell pass's switches
    (``livePreview`` / ``comfyPreview``) mean exactly the same thing here.
    """
    from tests.test_preview_stream import _StubModel

    from h3cs import preview_stream as ps

    if ps.comfy is None:
        pytest.skip("no ComfyUI on the path")

    def build(model, **kwargs):
        spec = _spec()
        graph = GraphBuilder()
        sheet_node.build_one_pass_graph(
            graph, model=model, clip="CLIP", video_vae="VVAE", audio_vae="AVAE",
            plan=op.one_pass_plan(spec), refs=reference_plan(spec),
            payload=grid_payload(spec, name="one-pass sheet"), name="one-pass sheet", **kwargs,
        )
        shift = next(n for n in graph.finalize().values()
                     if n["class_type"] == "MiniMaxH3SigmaShift")
        return shift["inputs"]["model"]

    # Defaults: our stream on, ComfyUI's own preview muted - the same as the per-cell pass.
    model = _StubModel()
    wrapped = build(model)
    assert wrapped is not model, "the model every step samples through carries the wrapper"
    wrapper = next(iter(wrapped.wrappers.values()))
    assert wrapper.stream is True and wrapper.mute is True
    assert wrapper.cells_total == 1 and wrapper.cell_ids == [sheet_node.ONE_PASS_CELL_ID]
    assert wrapper.whole_sheet is True, "the panel is told this clip IS the sheet"

    # comfyPreview: ComfyUI's preview stays, ours still streams.
    both = next(iter(build(_StubModel(), comfy_preview=True).wrappers.values()))
    assert both.mute is False and both.stream is True

    # livePreview off with ComfyUI's preview kept: nothing is wrapped at all.
    quiet = _StubModel()
    assert build(quiet, live_preview=False, comfy_preview=True) is quiet


def test_the_node_wires_the_one_pass_expansion_and_reports_it():
    payload = _payload(render={"continuity": "auto"})
    out = sheet_node.MiniMaxH3CharacterSheet.execute(
        model="MODEL",
        video_vae="VVAE",
        audio_vae="AVAE",
        clip="CLIP",
        sheet_data=json.dumps(payload),
        output_name="one-pass sheet",
        single_pass=True,
        continuity="auto",
    )
    # The report output is the sink's own report LINK. It used to be a formatted Python list repr,
    # which is why the notes now travel in the payload instead.
    assert isinstance(out.args[2], list), f"report must be a link, got {out.args[2]!r}"
    built = getattr(out, "expand")
    types = [node["class_type"] for node in built.values()]
    assert types.count("H3SheetOnePassSink") == 1
    assert "H3SheetGrid" not in types, "a one-pass render does not composite anything"

    sink = next(node for node in built.values() if node["class_type"] == "H3SheetOnePassSink")
    sent = json.loads(sink["inputs"]["sheet_data"])
    assert sent["render"]["singlePass"] is True
    notes = " ".join(sent["notes"])
    assert "One-pass sheet: one H3 render for the whole sheet" in notes
    assert "export clips" in notes, "clip export is ignored in a one-pass render, and says so"
    assert any("ignores continuation" in warning for warning in sent["warnings"]), sent["warnings"]


def test_the_mode_is_on_by_default_and_the_widget_decides():
    assert _spec().render.single_pass is True, "the one-pass sheet is the default render"
    assert _spec(render={"singlePass": False}).render.single_pass is False
    assert _spec(render={"draft": False}).render.single_pass is False, "the old name still reads"
    round_tripped = json.loads(json.dumps(_spec().to_dict()))
    assert ss.parse_sheet_spec(round_tripped).render.single_pass is True

    # The node's own knob wins over the payload, exactly like continuity and clip export.
    widgets = {
        "output_name": "w", "frames_per_cell": 22, "seed": 42, "sheet_layout": "hero-left",
        "sheet_columns": 2, "sheet_aspect": "3:2", "sheet_short_edge": 1536,
        "sheet_captions": True, "sheet_background": "#101014", "sheet_fit": "contain",
        "cell_aspect": "3:4", "continuity": "off", "export_video": False, "single_pass": False,
    }
    spec = sheet_node._spec_from_widgets(json.dumps(_payload()), widgets)
    assert spec.render.single_pass is False, "turning the knob off gives the per-cell pass"
