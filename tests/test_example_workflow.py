# ComfyUI-H3-Character-Sheet - shipped example workflow.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Guards the example workflow that ships with the pack.

A workflow file rots silently: a renamed node, a widget that moved, or a payload
that no longer parses would only show up when a user opened it. These checks load
the file the way ComfyUI does (nodes + links) and push its payload through the real
spec parser, so "Open this and hit Queue" keeps being true.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from h3cs import sheet_spec as ss

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "example_workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.json"))


def _workflow() -> dict:
    if not WORKFLOWS:
        pytest.skip("no example workflow is checked in")
    return json.loads(WORKFLOWS[0].read_text(encoding="utf-8"))


def test_the_pack_ships_at_least_one_workflow():
    assert WORKFLOWS, f"expected an example workflow in {WORKFLOW_DIR}"
    assert WORKFLOWS[0].name.endswith(".json")


def test_workflow_loads_as_a_graph_with_links():
    data = _workflow()
    assert data.get("version"), "a ComfyUI graph needs a version"
    node_types = [node["type"] for node in data["nodes"]]
    for expected in ("UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3CharacterSheet", "SaveImage"):
        assert expected in node_types, f"{expected} missing from the example workflow"
    assert node_types.count("VAELoader") == 2, "one VAE loader for video, one for audio"
    assert len(data["links"]) >= 5, "every input of the sheet node should be wired"
    for node in data["nodes"]:
        assert node.get("id") is not None and node.get("pos"), "nodes need an id and a position"
        assert "widgets_values" in node or node.get("inputs"), f"{node['type']} has no state"


def test_every_link_points_at_real_slots():
    data = _workflow()
    by_id = {node["id"]: node for node in data["nodes"]}
    for link in data["links"]:
        _link_id, from_id, from_slot, to_id, to_slot = link[:5]
        assert from_id in by_id and to_id in by_id, f"link {link[:5]} references a missing node"
        source = by_id[from_id]
        target = by_id[to_id]
        assert from_slot < len(source.get("outputs") or []), f"{source['type']} has no output {from_slot}"
        assert to_slot < len(target.get("inputs") or []), f"{target['type']} has no input {to_slot}"


def test_the_payload_is_a_sheet_the_node_can_run():
    data = _workflow()
    sheet = next(node for node in data["nodes"] if node["type"] == "MiniMaxH3CharacterSheet")
    payload = next(value for value in sheet["widgets_values"] if isinstance(value, str) and value.startswith("{"))
    spec = ss.parse_sheet_spec(payload)
    assert len(spec.cells) == 5, f"the example builds {len(spec.cells)} cells"
    assert [cell.id for cell in spec.cells][0] == "face-neutral-neutral"
    assert {cell.view for cell in spec.cells} == {"face", "portrait", "front", "profile", "back"}
    assert not spec.warnings, f"the shipped payload must parse cleanly: {spec.warnings}"
    # Each cell gets a real prompt with the framing baked in: the shot size and the
    # crop limit are what the model reads first, so they are pinned here (a full-body
    # cell that stops naming the feet is how "her feet were cut off" ships).
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "close-up of the face" in prompt.lower()
    full_body = next(cell for cell in spec.cells if cell.view == "front")
    body_prompt = ss.build_cell_prompt(spec, full_body).lower()
    assert "full-length wide shot" in body_prompt
    assert "soles of the feet" in body_prompt and "nothing cropped" in body_prompt
    portrait = next(cell for cell in spec.cells if cell.view == "portrait")
    assert "not a face-only close-up" in ss.build_cell_prompt(spec, portrait)
    # References are intentionally empty: the user drops their own in the panel.
    assert spec.refs == []


def test_execute_accepts_every_widget_the_schema_declares():
    """A widget the schema offers but ``execute`` does not take fails at run time.

    Costly to miss: the graph validates, the model loads, and then the run dies with
    "execute() got an unexpected keyword argument" (which is how cell_aspect shipped
    for one build).
    """
    import inspect

    from h3cs.nodes import sheet as sheet_node

    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    params = set(inspect.signature(sheet_node.MiniMaxH3CharacterSheet.execute).parameters)
    link_inputs = {"model", "video_vae", "audio_vae", "clip"}
    missing = [
        getattr(item, "id", None)
        for item in schema.inputs
        if getattr(item, "id", None) and getattr(item, "id") not in link_inputs
        and getattr(item, "id") not in params
    ]
    assert not missing, f"execute() would reject {missing}"


def test_widget_values_match_the_node_schema_order():
    """The sheet node's widget list must line up with the shipped values.

    The frontend serialises three extra slots around the schema widgets: the panel's
    DOM widget (an empty leading value) and ComfyUI's ``control_after_generate``
    helper right after the seed. Pinning the order here means a schema change tells
    us to regenerate the workflow instead of shipping one that opens wrong.
    """
    from h3cs.nodes import sheet as sheet_node

    data = _workflow()
    node = next(item for item in data["nodes"] if item["type"] == "MiniMaxH3CharacterSheet")
    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    link_inputs = {"model", "video_vae", "audio_vae", "clip"}
    expected = [""]
    for item in schema.inputs:
        name = getattr(item, "id", None)
        if not name or name in link_inputs:
            continue
        expected.append(name)
        if name == "seed":
            expected.append("control_after_generate")

    values = list(node["widgets_values"])
    assert len(values) == len(expected), (
        f"the workflow has {len(values)} values but this build expects "
        f"{len(expected)}: {expected}"
    )
    settings = dict(zip(expected, values, strict=True))
    assert settings["cell_size"] == 1024
    assert settings["frames_per_cell"] == 22
    assert settings["sampler_name"] == "res_multistep"
    assert settings["scheduler"] == "simple"
    assert settings["sheet_layout"] == "hero-left"
    assert settings["sheet_columns"] == 2
    assert settings["keep_frames"] is True
    assert settings["verbose_logging"] is False
    # Render settings live on the node's widgets (the payload carries references and
    # cells), so the seed the node uses is the widget value. The shipped example is saved
    # with seed mode `randomize`, so its stored seed is whatever the last run drew: pinning
    # an exact number would only break the next time it is opened and saved.
    assert isinstance(settings["seed"], int)
    assert settings["control_after_generate"] == "randomize"
    spec = ss.parse_sheet_spec(settings["sheet_data"])
    assert len(spec.cells) == 5
    assert spec.global_prompt == "" and spec.negative_prompt == "", "the user fills these in"
    # The node reads its render settings from the widgets, not from this payload
    # (see test_sheet_graph.py for the widget-authority contract).
    assert settings["steps"] == 8
    assert settings["shift_video"] == 12.0
    # `match` (the node's default) rather than the identity preset's `max`: the shipped
    # example is the plain one-click sheet, not a fidelity recipe.
    assert settings["ref_image_size"] == "match"
