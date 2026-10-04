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

from h3cs import help as help_mod
from h3cs import planner as pl
from h3cs import sheet_spec as ss

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "example_workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.json"))

#: The plain one-click sheet: the Help tab points at it and the payload assertions below are
#: about that sheet. The ``+ RefMod`` example is the same graph with the export node appended,
#: and is checked in its own section further down.
CANONICAL = Path(help_mod.EXAMPLE_WORKFLOW).name


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _named(name: str) -> Path:
    for path in WORKFLOWS:
        if path.name == name:
            return path
    raise AssertionError(f"{name} is not checked in: {[p.name for p in WORKFLOWS]}")


def _refmod_path() -> Path:
    for path in WORKFLOWS:
        if "refmod" in path.name.lower():
            return path
    pytest.skip("no + RefMod example workflow is checked in")


def _workflow(path: Path | None = None) -> dict:
    if not WORKFLOWS:
        pytest.skip("no example workflow is checked in")
    return _load(path or _named(CANONICAL))


def test_the_pack_ships_both_examples():
    assert WORKFLOWS, f"expected an example workflow in {WORKFLOW_DIR}"
    for path in WORKFLOWS:
        assert path.name.endswith(".json")
    assert _named(CANONICAL), "the Help tab points at the plain sheet example"
    assert _refmod_path(), "the release highlights the + RefMod example"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_example_loads_as_a_graph(path):
    data = _workflow(path)
    assert data.get("version"), "a ComfyUI graph needs a version"
    node_types = [node["type"] for node in data["nodes"]]
    for expected in ("UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3CharacterSheet", "SaveImage"):
        assert expected in node_types, f"{expected} missing from {path.name}"
    assert node_types.count("VAELoader") == 2, "one VAE loader for video, one for audio"
    assert len(data["links"]) >= 5, "every input of the sheet node should be wired"
    for node in data["nodes"]:
        assert node.get("id") is not None and node.get("pos"), "nodes need an id and a position"
        assert "widgets_values" in node or node.get("inputs"), f"{node['type']} has no state"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_example_link_points_at_real_slots(path):
    data = _workflow(path)
    by_id = {node["id"]: node for node in data["nodes"]}
    for link in data["links"]:
        _link_id, from_id, from_slot, to_id, to_slot = link[:5]
        assert from_id in by_id and to_id in by_id, f"link {link[:5]} references a missing node"
        source = by_id[from_id]
        target = by_id[to_id]
        assert from_slot < len(source.get("outputs") or []), f"{source['type']} has no output {from_slot}"
        assert to_slot < len(target.get("inputs") or []), f"{target['type']} has no input {to_slot}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_example_ships_without_local_reference_paths(path):
    """A shipped example has to open for anyone, not just for its author.

    References are files on one machine: the first example has always shipped its
    References tab empty and left the pictures to the user. A payload naming
    "headshot.png" fails LoadImage validation on every other install, so the example
    would look broken rather than blank. That applies to the audio/video refs too.
    """
    data = _workflow(path)
    sheet = _node(data, "MiniMaxH3CharacterSheet")
    payload = next(value for value in sheet["widgets_values"]
                   if isinstance(value, str) and value.startswith("{"))
    spec = ss.parse_sheet_spec(payload)
    assert spec.refs == [], f"{path.name} ships references: {[ref.file for ref in spec.refs]}"


# --------------------------------------------------------------------------- #
# the + RefMod example: render the sheet and export the bundle in one queue
# --------------------------------------------------------------------------- #
def _node(data: dict, node_type: str) -> dict:
    return next(node for node in data["nodes"] if node["type"] == node_type)


def _wired_inputs(node: dict) -> dict[str, int]:
    """Input name -> slot index, for the inputs that actually carry a link."""
    return {entry["name"]: index
            for index, entry in enumerate(node.get("inputs") or [])
            if entry.get("link") is not None}


def _link_source(data: dict, link_id: int) -> tuple[int, int]:
    link = next(item for item in data["links"] if item[0] == link_id)
    return int(link[1]), int(link[2])


def test_the_refmod_example_renders_a_sheet_and_exports_it():
    """One queue does both, so both halves have to be wired and neither may be muted."""
    data = _workflow(_refmod_path())
    builder = _node(data, "MiniMaxH3CharacterSheet")
    export = _node(data, "H3SheetRefMod")
    assert builder.get("mode", 0) == 0, "the sheet node is muted in this example"
    assert export.get("mode", 0) == 0, "the export node is muted in this example"

    wired = _wired_inputs(export)
    # The three Builder outputs the export consumes, checked by the Builder's slot numbers
    # (sheet=0, cells=1, sheet_dir=3), so a reordered output surfaces here.
    for name, builder_slot in (("cells", 1), ("sheet", 0), ("sheet_dir", 3)):
        assert name in wired, f"{name} is not wired on the export node"
        source = _link_source(data, export["inputs"][wired[name]]["link"])
        assert source == (builder["id"], builder_slot), (
            f"{name} should come from the sheet node's output {builder_slot}, got {source}")
    for name in ("video_vae", "audio_vae"):
        assert name in wired, f"{name} must be wired or the export cannot encode anything"
    # The sheet image is still saved: the example yields the sheet *and* the mod.
    save = _node(data, "SaveImage")
    assert _link_source(data, save["inputs"][0]["link"])[0] == builder["id"]


def test_the_refmod_example_saves_something_loadable():
    data = _workflow(_refmod_path())
    settings = _node(data, "H3SheetRefMod")["widgets_values_named"]
    assert settings["save"] is True, "an example that does not save would be pointless"
    assert settings["name"] and settings["subfolder"], "the mod needs a name and a subfolder"
    assert settings["mode"] == "Full Reference", "identity needs the real encode, not pooling"
    assert settings["concept_type"] == "identity"
    assert settings["voice_cell"] == -1, "voice comes from the first cell that exported a clip"
    # Values the node's own widgets can produce (their declared steps).
    assert int(settings["ref_resolution"]) % 64 == 0
    assert int(settings["max_tokens"]) % 512 == 0


def test_the_refmod_example_keeps_every_cell_it_sends():
    """A token cap below what the cells cost silently drops views from the mod.

    Not hypothetical: the first draft of this example (ref_resolution 1472, the default
    max_tokens 9216) shipped 3 of 5 fidelity cells - 5 x 2806 = 14030 tokens against a
    9216 cap. Deriving the cost here means the next edit that re-caps it fails the suite
    instead of quietly trimming the character's views.
    """
    data = _workflow(_refmod_path())
    settings = _node(data, "MiniMaxH3CharacterSheet")["widgets_values_named"]
    export = _node(data, "H3SheetRefMod")["widgets_values_named"]
    spec = ss.parse_sheet_spec(settings["sheet_data"])
    width, height = pl.cell_render_size(int(settings["cell_size"]), str(settings["cell_aspect"]))
    short_edge = int(export["ref_resolution"])
    scale = min(1.0, short_edge / min(width, height))
    # Their resize keeps the aspect and rounds to the 32px grid; the VAE encodes at /16 and
    # H3 packs 2x2 patches, so one injected token is one 32px step on each axis.
    resized = (max(32, round(width * scale / 32) * 32), max(32, round(height * scale / 32) * 32))
    per_cell = (resized[1] // 32) * (resized[0] // 32)
    cost = per_cell * len(spec.enabled_cells)
    assert cost <= int(export["max_tokens"]), (
        f"{len(spec.enabled_cells)} cells cost {cost} tokens at ref_resolution {short_edge}, "
        f"but max_tokens is {export['max_tokens']} - lower ref_resolution or raise the cap, "
        "or the export drops views")


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
