"""Character Sheet Builder - latent continuation between cells.

Cells are independent H3 clips: each one starts from its own noise and its own
derived seed, which is what makes a sheet's poses independent. Continuation is the
opposite trade, opt-in and off by default: the tail of the previous cell is anchored
at frame 0 of the next clip with core ``MiniMaxH3AddGuide``, so a run of cells
continues from its predecessor instead of restarting.

Pinned here, because three places have to agree and only one of them is obvious:

* the plan (which cell continues, and how many frames are handed over),
* the graph (a guide node between the cell's conditioning and its guider, fed by the
  previous cell's DECODED frames),
* the frame picker (the hand-over frames are a re-render of the previous cell, so
  they must never be the frame the sheet shows).
"""

from __future__ import annotations

import numpy as np
from comfy_execution.graph_utils import GraphBuilder

from h3cs import planner as pl
from h3cs import sheet_layout as layout
from h3cs import sheet_spec as ss
from h3cs.nodes import sheet as sheet_node

SENTINEL = {"model": "MODEL", "clip": "CLIP", "video_vae": "VVAE", "audio_vae": "AVAE"}


def _spec(cells, render=None, **overrides):
    payload = {
        "name": "sheet run",
        "globalPrompt": "a woman in her thirties",
        "refs": {"pictures": [{"imageFile": "face.png", "role": "face and hair"}]},
        "render": dict(render or {}),
        "cells": list(cells),
    }
    payload.update(overrides)
    return ss.parse_sheet_spec(payload)


def _three(sheet_mode=None, **cell_overrides):
    render = {"continuity": sheet_mode} if sheet_mode else {}
    cells = [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    for cell in cells:
        if cell["id"] in cell_overrides:
            cell.update(cell_overrides[cell["id"]])
    return _spec(cells, render)


def _build(spec):
    work_items = pl.cell_work_items(spec, cell_size=1024)
    graph = GraphBuilder()
    sheet_node.build_sheet_graph(
        graph,
        model=SENTINEL["model"],
        clip=SENTINEL["clip"],
        video_vae=SENTINEL["video_vae"],
        audio_vae=SENTINEL["audio_vae"],
        work_items=work_items,
        refs=pl.reference_plan(spec),
        payload=pl.grid_payload(spec, name="sheet run"),
        name="sheet run",
    )
    return graph.finalize(), work_items


def _by_type(nodes, class_type):
    return {nid: node for nid, node in nodes.items() if node["class_type"] == class_type}


def _for_cell(nodes, class_type, cell_id):
    return next(
        node
        for nid, node in nodes.items()
        if node["class_type"] == class_type and str(nid).endswith(cell_id)
    )


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #
def test_continuation_is_off_by_default():
    spec = _three()
    plan = ss.continuity_plan(spec)
    assert plan == {"c1": 0, "c2": 0, "c3": 0}
    assert spec.render.continuity == "off"


def test_sheet_switch_on_chains_every_cell_after_the_first():
    spec = _three("on")
    plan = ss.continuity_plan(spec)
    assert plan == {"c1": 0, "c2": ss.CONTINUITY_FRAMES, "c3": ss.CONTINUITY_FRAMES}


def test_the_first_cell_never_continues_and_says_so():
    spec = _three("off", c1={"continuity": "on"})
    warnings: list[str] = []
    plan = ss.continuity_plan(spec, warnings=warnings)
    assert plan["c1"] == 0
    assert any("first cell" in line for line in warnings)


def test_a_cell_can_opt_in_while_the_sheet_is_off():
    spec = _three("off", c2={"continuity": "on"})
    plan = ss.continuity_plan(spec)
    assert plan == {"c1": 0, "c2": ss.CONTINUITY_FRAMES, "c3": 0}


def test_a_cell_can_opt_out_while_the_sheet_is_on():
    spec = _three("on", c2={"continuity": "off"})
    plan = ss.continuity_plan(spec)
    assert plan == {"c1": 0, "c2": 0, "c3": ss.CONTINUITY_FRAMES}


def test_a_cell_that_could_not_show_the_hand_over_is_skipped_with_a_warning():
    """A 5-frame cell cannot take a 5-frame guide: it would be a copy of its predecessor."""
    spec = _spec([{"id": "c1"}, {"id": "c2", "frames": 5}], {"continuity": "on"})
    warnings: list[str] = []
    plan = ss.continuity_plan(spec, warnings=warnings)
    assert plan == {"c1": 0, "c2": 0}
    assert any("skipped" in line for line in warnings)


def test_a_disabled_cell_is_not_in_the_plan():
    spec = _spec(
        [{"id": "c1"}, {"id": "c2", "enabled": False}, {"id": "c3"}],
        {"continuity": "on"},
    )
    plan = ss.continuity_plan(spec)
    assert plan == {"c1": 0, "c3": ss.CONTINUITY_FRAMES}


def test_an_unknown_mode_falls_back_to_off_with_a_warning():
    spec = _spec([{"id": "c1"}, {"id": "c2"}], {"continuity": "sometimes"})
    assert spec.render.continuity == "off"
    assert any("unknown continuity" in line for line in spec.warnings)


def test_a_frame_count_means_on_because_the_length_is_fixed_by_the_h3_grid():
    spec = _spec([{"id": "c1"}, {"id": "c2"}], {"continuity": "5"})
    assert spec.render.continuity == "on"
    assert any("frame count" in line for line in spec.warnings)


def test_an_unknown_per_cell_mode_is_reported_and_inherits():
    spec = _spec([{"id": "c1"}, {"id": "c2", "continuity": "maybe"}], {"continuity": "on"})
    assert spec.cells[1].continuity == "inherit"
    assert any("unknown continuity" in line for line in spec.warnings)
    assert ss.continuity_plan(spec)["c2"] == ss.CONTINUITY_FRAMES


def test_continuity_round_trips_through_the_saved_payload():
    spec = _three("on", c2={"continuity": "off"})
    again = ss.parse_sheet_spec(spec.to_dict())
    assert again.render.continuity == "on"
    assert [cell.continuity for cell in again.cells] == ["inherit", "off", "inherit"]
    assert ss.continuity_plan(again) == ss.continuity_plan(spec)


# --------------------------------------------------------------------------- #
# auto: the framing-aware mode (the fix for "her feet were cut off")
# --------------------------------------------------------------------------- #
def _sheet(*views, mode="auto", **cell_overrides):
    cells = [{"id": f"c{index + 1}-{view}", "view": view} for index, view in enumerate(views)]
    for cell in cells:
        if cell["id"] in cell_overrides:
            cell.update(cell_overrides[cell["id"]])
    return _spec(cells, {"continuity": mode})


def test_framing_distance_knows_the_three_camera_distances():
    assert ss.framing_distance("face") == "close"
    assert ss.framing_distance("portrait") == "medium"
    assert ss.framing_distance("front") == ss.framing_distance("profile") == "full"
    assert ss.framing_distance("nonsense") == "", "an unknown view never matches another"


def test_auto_chains_only_where_the_camera_distance_AND_the_view_match():
    """A framing change is rendered on its own - and so is an ANGLE change.

    The hand-over carries the previous cell's scale, so chaining a full body after a
    chest-up cell lands mid-zoom - the feet cut off. It also carries the previous cell's
    POSTURE: chaining a profile cell after a frontal one renders frontal again, because
    the five handed-over frames outweigh a prompt that asks the subject to turn. Measured
    on a 5-cell turnaround (face / portrait / front / profile / back) with a frontal
    reference: with the angle chained, every full-body cell came back facing the camera.
    """
    spec = _sheet("face", "portrait", "front", "profile", "back")
    plan = ss.continuity_plan(spec)
    assert [plan[cell.id] for cell in spec.cells] == [0, 0, 0, 0, 0], (
        "a 90-degree walk of views is five independent cells, not one continuous move"
    )


def test_auto_still_chains_the_same_view_with_a_different_pose_or_expression():
    """That is what the hand-over is for: same camera, same angle, new state."""
    spec = _sheet("front", "front", "front")
    spec.cells[1].pose = "a-pose"
    spec.cells[2].expression = "smile"
    plan = ss.continuity_plan(spec)
    assert [plan[cell.id] for cell in spec.cells] == [0, 5, 5]


def test_auto_breaks_at_the_next_view_change():
    spec = _sheet("front", "front", "profile", "back", "three-quarter")
    plan = ss.continuity_plan(spec)
    assert [plan[cell.id] for cell in spec.cells] == [0, 5, 0, 0, 0]


def test_the_shared_rule_is_what_the_graph_and_the_report_use():
    """One rule, so "why is this cell not continuing?" cannot disagree with the wiring."""
    assert ss.continuation_keeps_scale_and_angle("front", "front") is True
    assert ss.continuation_keeps_scale_and_angle("front", "profile") is False
    assert ss.continuation_keeps_scale_and_angle("profile", "back") is False
    assert ss.continuation_keeps_scale_and_angle("face", "portrait") is False
    assert ss.continuation_keeps_scale_and_angle("front", "nonsense") is False


def test_a_cell_can_force_auto_inside_an_otherwise_independent_sheet():
    """Per-cell 'auto' still has to satisfy the rule (same camera AND same view)."""
    spec = _sheet("face", "front", "front", mode="off",
                  **{"c2-front": {"continuity": "auto"},
                     "c3-front": {"continuity": "auto"}})
    plan = ss.continuity_plan(spec)
    assert [plan[cell.id] for cell in spec.cells] == [0, 0, 5], (
        "c2 breaks (face -> front is a framing change), c3 continues (front -> front)"
    )


def test_a_cell_cannot_force_auto_across_a_view_change():
    spec = _sheet("front", "profile", mode="off",
                  **{"c2-profile": {"continuity": "auto"}})
    plan = ss.continuity_plan(spec)
    assert [plan[cell.id] for cell in spec.cells] == [0, 0]


def test_forcing_continuation_across_a_framing_change_is_reported():
    spec = _sheet("face", "portrait", mode="on")
    warnings: list[str] = []
    plan = ss.continuity_plan(spec, warnings=warnings)
    assert plan["c2-portrait"] == 5, "an explicit 'on' still does what it says"
    assert any("forced across a framing change" in line for line in warnings)


def test_auto_does_not_warn_because_breaking_the_chain_is_the_point():
    spec = _sheet("face", "portrait")
    warnings: list[str] = []
    plan = ss.continuity_plan(spec, warnings=warnings)
    assert plan["c2-portrait"] == 0
    assert not any("framing change" in line for line in warnings)


def test_the_summary_explains_an_auto_break():
    spec = _sheet("face", "portrait", "front", "profile")
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    joined = "\n".join(lines)
    assert "kept independent at a framing change" in joined
    assert "c4-profile" in joined.split("kept independent")[1].split("\n")[0], (
        "an angle change is a break too - the reason the profile cell used to stay frontal"
    )
    assert not any("continues 5f" in line for line in lines), (
        "nothing continues in a 90-degree walk of views"
    )


def test_the_summary_still_reports_a_real_continuation():
    """Same view, new pose: the report has to say which cell carries a hand-over."""
    spec = _sheet("front", "front")
    spec.cells[1].pose = "a-pose"
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    assert any("continues 5f" in line for line in lines)


# --------------------------------------------------------------------------- #
# the framing language the complaints came from
# --------------------------------------------------------------------------- #
def _view_prompt(view: str) -> str:
    spec = _spec([{"id": "c1", "view": view}])
    return ss.build_cell_prompt(spec, spec.cells[0])


def test_a_full_body_view_names_the_shot_size_and_forbids_cropping():
    """\"Whole figure inside the frame\" alone gave medium shots with the feet cut off."""
    for view in ("front", "profile", "back"):
        prompt = _view_prompt(view).lower()
        assert "full-length wide shot" in prompt, view
        assert "soles of the feet" in prompt, view
        assert "nothing cropped" in prompt, view
        assert "not a close-up" in prompt, view


def test_the_profile_view_no_longer_contradicts_itself():
    """It used to ask for a whole figure AND a camera level with the waist."""
    prompt = _view_prompt("profile")
    assert "camera level with the waist" not in prompt
    assert "90 degrees" in prompt and "no eye contact" in prompt


def test_a_portrait_view_is_told_what_it_is_not():
    """The `portrait` cell came back as a face close-up when it continued a face cell."""
    prompt = _view_prompt("portrait").lower()
    assert "medium close-up" in prompt
    assert "not a face-only close-up" in prompt
    assert "top of the head" in prompt and "chest" in prompt


def test_a_face_view_stays_a_tight_close_up():
    prompt = _view_prompt("face")
    assert "close-up of the face" in prompt.lower()
    assert "not a full body" in prompt.lower()


# --------------------------------------------------------------------------- #
# the work items + report
# --------------------------------------------------------------------------- #
def test_work_items_carry_the_hand_over_length():
    items = pl.cell_work_items(_three("on"))
    assert [item["continuity"] for item in items] == [0, ss.CONTINUITY_FRAMES, ss.CONTINUITY_FRAMES]


def test_the_summary_says_which_cells_continue():
    spec = _three("on")
    items = pl.cell_work_items(spec)
    lines = pl.work_summary(spec, items)
    assert any("Continuation: 2 cell(s)" in line for line in lines)
    assert any("continues 5f" in line for line in lines)
    assert not any(line.endswith("continues 5f") for line in lines if "c1" in line)


def test_the_summary_stays_quiet_when_nothing_continues():
    spec = _three("off")
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    assert not any("Continuation:" in line for line in lines)


# --------------------------------------------------------------------------- #
# the graph
# --------------------------------------------------------------------------- #
def test_off_wires_no_guide_at_all():
    nodes, _ = _build(_three("off"))
    assert _by_type(nodes, "MiniMaxH3AddGuide") == {}
    assert _by_type(nodes, "ImageFromBatch") == {}


def test_on_wires_a_guide_per_continuing_cell():
    nodes, _ = _build(_three("on"))
    guides = _by_type(nodes, "MiniMaxH3AddGuide")
    assert len(guides) == 2
    assert not any(str(nid).endswith("c1") for nid in guides)


def test_the_guide_is_fed_by_the_previous_cells_decoded_frames():
    nodes, _ = _build(_three("on"))
    tails = _by_type(nodes, "ImageFromBatch")
    assert len(tails) == 2
    for cell_id, previous in (("c2", "c1"), ("c3", "c2")):
        guide = _for_cell(nodes, "MiniMaxH3AddGuide", cell_id)
        tail = nodes[guide["inputs"]["image"][0]]
        assert tail["class_type"] == "ImageFromBatch"
        assert tail["inputs"]["batch_index"] == -ss.CONTINUITY_FRAMES
        assert tail["inputs"]["length"] == ss.CONTINUITY_FRAMES
        # The tail has to be the PREVIOUS cell's decode, never this cell's own.
        decode = nodes[tail["inputs"]["image"][0]]
        assert decode["class_type"] == "VAEDecode"
        assert str(decode["inputs"]["samples"][0]).endswith(f"sample_{previous}")


def test_the_guide_anchors_at_frame_zero_with_this_cells_own_latent():
    nodes, _ = _build(_three("on"))
    guide = _for_cell(nodes, "MiniMaxH3AddGuide", "c2")
    assert guide["inputs"]["frame_idx"] == 0
    # The guide consumes this cell's own AV latent and conditioning, so the
    # references and the hand-over meet in one conditioning for the guider.
    ref2va = _for_cell(nodes, "MiniMaxH3ReferenceToVideo", "c2")
    reference_id = guide["inputs"]["latent"][0]
    assert guide["inputs"]["positive"] == [reference_id, 0]
    assert guide["inputs"]["latent"] == [reference_id, 1]
    assert ref2va["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_the_guider_takes_the_guided_conditioning_and_an_independent_cell_does_not():
    nodes, _ = _build(_three("on"))
    guided = _for_cell(nodes, "BasicGuider", "c2")
    assert nodes[guided["inputs"]["conditioning"][0]]["class_type"] == "MiniMaxH3AddGuide"
    independent = _for_cell(nodes, "BasicGuider", "c1")
    assert nodes[independent["inputs"]["conditioning"][0]]["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_an_opted_out_cell_is_wired_exactly_like_a_sheet_without_continuation():
    with_opt_out = _three("on", c2={"continuity": "off"})
    nodes, _ = _build(with_opt_out)
    guider = _for_cell(nodes, "BasicGuider", "c3")
    assert nodes[guider["inputs"]["conditioning"][0]]["class_type"] == "MiniMaxH3AddGuide"
    second = _for_cell(nodes, "BasicGuider", "c2")
    assert nodes[second["inputs"]["conditioning"][0]]["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_every_cell_still_gets_its_own_sampler_and_frames():
    nodes, items = _build(_three("on"))
    assert len(_by_type(nodes, "SamplerCustomAdvanced")) == 3
    assert len(_by_type(nodes, "VAEDecode")) == 3
    assert len(_by_type(nodes, "H3SheetCellSink")) == 3
    assert [item["seed"] for item in items] == sorted({item["seed"] for item in items})


# --------------------------------------------------------------------------- #
# the frame picker
# --------------------------------------------------------------------------- #
def _frames(count, sharp_at=None):
    base = np.full((16, 16, 3), 40, dtype=np.uint8)
    out = []
    for index in range(count):
        if sharp_at is not None and index == sharp_at:
            checker = (np.indices((16, 16)).sum(axis=0) % 2).astype(np.uint8)
            out.append(np.stack([checker * 255] * 3, axis=-1))
        else:
            out.append(base.copy())
    return out


def test_sharpest_skips_the_hand_over_frames():
    frames = _frames(12, sharp_at=0)
    assert layout.pick_frame_index(frames, mode="sharpest") == 0
    picked = layout.pick_frame_index(frames, mode="sharpest", skip=5)
    assert picked >= 5, "the hand-over frames are a copy of the previous cell"


def test_skip_never_removes_every_candidate():
    frames = _frames(5)
    assert layout.pick_frame_index(frames, mode="sharpest", skip=99) == 4
    assert layout.pick_frame_index(frames, mode="auto", skip=99) == 4


def test_settle_never_removes_every_candidate_either():
    frames = _frames(5)
    assert layout.pick_frame_index(frames, mode="auto", settle=2) == 4
    # A settle window longer than the clip is meaningless, so it is ignored.
    assert layout.pick_frame_index(frames, mode="sharpest", settle=99) == layout.pick_frame_index(
        frames, mode="sharpest"
    )


def test_an_explicit_pick_still_wins_over_the_skip():
    """A hand-picked frame is the user's own choice - the panel shows the frames."""
    frames = _frames(12)
    assert layout.pick_frame_index(frames, mode="auto", explicit=1, skip=5) == 1


def test_last_frame_picks_are_unaffected_by_the_skip():
    frames = _frames(12)
    assert layout.pick_frame_index(frames, mode="auto", skip=5) == 11
    assert layout.pick_frame_index(frames, mode="last", skip=5) == 11
