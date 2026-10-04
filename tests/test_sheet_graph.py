"""Character Sheet Builder - the expansion into ComfyUI core MiniMax H3 nodes.

This is the independence test as much as a wiring test: the graph the sheet node
builds may only contain ComfyUI core nodes plus this pack's own grid node. If a
Motion Director class ever creeps back in, this fails.
"""

from __future__ import annotations

import json
import re

import pytest
from comfy_execution.graph_utils import GraphBuilder

from h3cs import planner as pl
from h3cs import sheet_spec as ss
from h3cs.nodes import sheet as sheet_node


def _core_minimax_source() -> str | None:
    """Text of ComfyUI's own MiniMax H3 node module, when it is importable."""
    try:
        import comfy_extras.nodes_minimax_h3 as core
    except Exception:  # noqa: BLE001 - core absent (standalone test run)
        return None
    try:
        with open(core.__file__, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:  # pragma: no cover
        return None

#: Everything the expansion is allowed to use. Core MiniMax H3 + core plumbing,
#: plus this pack's compositor. Anything else means the pack is not standalone.
ALLOWED_NODE_TYPES = {
    # ComfyUI core: loaders
    "LoadImage",
    "LoadVideo",
    "GetVideoComponents",
    "LoadAudio",
    # ComfyUI core: MiniMax H3 conditioning / patching
    "MiniMaxH3ReferenceToVideo",
    "MiniMaxH3SigmaShift",
    # ComfyUI core: latent continuation between cells (opt-in)
    "MiniMaxH3AddGuide",
    "ImageFromBatch",
    # ComfyUI core: sampling plumbing
    "KSamplerSelect",
    "BasicScheduler",
    "BasicGuider",
    "RandomNoise",
    "SamplerCustomAdvanced",
    # ComfyUI core: decode
    "VAEDecode",
    # ComfyUI core: the exported cell clips (opt out with export_video)
    "VAEDecodeAudio",
    "CreateVideo",
    "SaveVideo",
    # this pack
    "H3SheetGrid",
    "H3SheetCellSink",
    "H3SheetOrderGate",
}

SENTINEL = {"model": "MODEL", "clip": "CLIP", "video_vae": "VVAE", "audio_vae": "AVAE"}


def _spec(**overrides):
    payload = {
        "name": "sheet run",
        "globalPrompt": "a woman in her thirties",
        "refs": {
            "pictures": [{"imageFile": "face.png", "role": "face and hair"}],
            "videos": [{"videoFile": "cloth.mp4", "role": "clothing"}],
            "audios": [{"audioFile": "voice.wav", "role": "voice"}],
        },
        "render": {"framesPerCell": 5},
        "cells": [
            {"id": "hero", "view": "portrait", "expression": "smile"},
            {"id": "front", "view": "front", "pose": "t-pose"},
        ],
    }
    payload.update(overrides)
    return ss.parse_sheet_spec(payload)


def _build(spec=None, ref_scope=ss.DEFAULT_REF_SCOPE, **kwargs):
    spec = spec or _spec()
    work_items = pl.cell_work_items(
        spec, cell_size=1024, ref_image_size="match", ref_scope=ref_scope
    )
    graph = GraphBuilder()
    outputs = sheet_node.build_sheet_graph(
        graph,
        model=SENTINEL["model"],
        clip=SENTINEL["clip"],
        video_vae=SENTINEL["video_vae"],
        audio_vae=SENTINEL["audio_vae"],
        work_items=work_items,
        refs=pl.reference_plan(spec),
        payload=pl.grid_payload(spec, name="sheet run"),
        name="sheet run",
        **kwargs,
    )
    return graph, outputs


def _for_cell(mapping: dict, cell_id: str, prefix: str = "ref2va_"):
    """The reference-to-video entry for one cell (ids are prefixed when finalized)."""
    return next(
        value for key, value in mapping.items() if str(key).endswith(prefix + cell_id)
    )


def _wired_references(graph) -> dict[str, dict[str, str]]:
    """Per reference-to-video node: ``{autogrow slot: image file}`` as wired."""
    nodes = graph.finalize()
    loaders = {
        nid: node["inputs"].get("image")
        for nid, node in nodes.items()
        if node["class_type"] == "LoadImage"
    }
    wired: dict[str, dict[str, str]] = {}
    for nid, node in nodes.items():
        if node["class_type"] != "MiniMaxH3ReferenceToVideo":
            continue
        wired[nid] = {
            slot: loaders.get(source[0], "?")
            for slot, source in node["inputs"].items()
            if slot.startswith("ref_") and isinstance(source, list)
        }
    return wired


def _types(graph) -> list[str]:
    return [node["class_type"] for node in graph.finalize().values()]


# --------------------------------------------------------------------------- #
# independence
# --------------------------------------------------------------------------- #
def test_expansion_uses_only_core_h3_nodes_and_our_grid():
    graph, _ = _build()
    unexpected = sorted(set(_types(graph)) - ALLOWED_NODE_TYPES)
    assert unexpected == [], f"non-core/foreign node types in the sheet graph: {unexpected}"


def test_no_director_nodes_or_imports_anywhere_in_the_pack():
    graph, _ = _build()
    joined = json.dumps(graph.finalize())
    for forbidden in ("MotionDirector", "director.", "MiniMaxH3MotionDirector", "easy multitrack"):
        assert forbidden not in joined, f"expansion references {forbidden!r}"


# --------------------------------------------------------------------------- #
# per-cell references
# --------------------------------------------------------------------------- #
def test_a_face_cell_is_wired_only_the_references_it_can_show():
    """The close-up must not be handed the outfit photo: that is what it copied."""
    spec = _spec(
        refs={
            "pictures": [
                {"imageFile": "face.png", "role": "face and hair"},
                {"imageFile": "body.png", "role": "body and clothes"},
            ]
        },
        cells=[
            {"id": "close", "view": "face"},
            {"id": "whole", "view": "front"},
        ],
    )
    graph, _ = _build(spec)
    wired = _wired_references(graph)
    assert _for_cell(wired, "close") == {"ref_images.ref_image_0": "face.png"}, (
        "a face close-up is conditioned on the face picture alone"
    )
    assert _for_cell(wired, "whole") == {
        "ref_images.ref_image_0": "face.png",
        "ref_images.ref_image_1": "body.png",
    }, "a full body cell still gets both"

    nodes = graph.finalize()
    close_prompt = _for_cell(nodes, "close")["inputs"]["prompt"]
    assert "<Picture 1>" in close_prompt
    assert "<Picture 2>" not in close_prompt, "never name a reference the cell was not given"
    assert "<Picture 2>" in _for_cell(nodes, "whole")["inputs"]["prompt"]


def test_a_dropped_face_picture_is_renumbered_to_the_first_slot():
    """H3 numbers what it receives, so the wire and the prompt have to agree."""
    spec = _spec(
        refs={
            "pictures": [
                {"imageFile": "body.png", "role": "body and clothes"},
                {"imageFile": "face.png", "role": "face and hair"},
            ]
        },
        cells=[{"id": "close", "view": "face"}],
    )
    graph, _ = _build(spec)
    assert _for_cell(_wired_references(graph), "close") == {"ref_images.ref_image_0": "face.png"}
    assert "<Picture 2>" not in _for_cell(graph.finalize(), "close")["inputs"]["prompt"]


def test_the_scope_widget_can_hand_every_reference_to_every_cell():
    spec = _spec(
        refs={
            "pictures": [
                {"imageFile": "face.png", "role": "face and hair"},
                {"imageFile": "body.png", "role": "body and clothes"},
            ]
        },
        cells=[{"id": "close", "view": "face"}],
    )
    graph, _ = _build(spec, ref_scope="every cell")
    assert _for_cell(_wired_references(graph), "close") == {
        "ref_images.ref_image_0": "face.png",
        "ref_images.ref_image_1": "body.png",
    }


# --------------------------------------------------------------------------- #
# per-cell chain
# --------------------------------------------------------------------------- #
def test_every_cell_gets_the_full_reference_to_video_chain():
    graph, _ = _build()
    nodes = graph.finalize()
    types = [node["class_type"] for node in nodes.values()]
    for expected in (
        "MiniMaxH3ReferenceToVideo",
        "KSamplerSelect",
        "BasicScheduler",
        "BasicGuider",
        "RandomNoise",
        "SamplerCustomAdvanced",
        "VAEDecode",
    ):
        assert types.count(expected) == 2, f"{expected} should appear once per cell"
    assert types.count("MiniMaxH3SigmaShift") == 1, "the shifted model is shared"
    assert types.count("H3SheetGrid") == 1
    assert types.count("H3SheetCellSink") == 2, "one saver per cell: frames land as soon as a cell renders"
    assert types.count("LoadImage") == 1
    assert types.count("LoadVideo") == 1
    assert types.count("GetVideoComponents") == 1
    assert types.count("LoadAudio") == 1


def test_cell_parameters_land_on_the_reference_node():
    graph, _ = _build()
    nodes = graph.finalize()
    hero = next(node for node_id, node in nodes.items() if node_id.endswith("ref2va_hero"))
    assert hero["inputs"]["prompt"].startswith("a woman in her thirties")
    assert "Warm smile" in hero["inputs"]["prompt"]
    # 3:4 cells by default: cell_size is the short edge (the width here)
    assert hero["inputs"]["width"] == 768
    assert hero["inputs"]["height"] == 1024
    assert hero["inputs"]["length"] == 5
    assert hero["inputs"]["ref_image_size"] == "match"
    assert hero["inputs"]["clip"] == SENTINEL["clip"]
    assert hero["inputs"]["vae"] == SENTINEL["video_vae"]
    assert hero["inputs"]["audio_vae"] == SENTINEL["audio_vae"]


def test_reference_slots_are_wired_from_core_loaders():
    graph, _ = _build()
    nodes = graph.finalize()
    hero = next(node for node_id, node in nodes.items() if node_id.endswith("ref2va_hero"))
    assert any(node_id.endswith("ref_image_ref_image_0") for node_id in nodes), nodes.keys()
    # slot -> loader output, resolved through the link target's class type
    def source_type(link):
        return nodes[link[0]]["class_type"]

    assert source_type(hero["inputs"]["ref_images.ref_image_0"]) == "LoadImage"
    assert source_type(hero["inputs"]["ref_videos.ref_video_0"]) == "GetVideoComponents"
    assert source_type(hero["inputs"]["ref_video_audios.ref_video_audio_0"]) == "GetVideoComponents"
    assert source_type(hero["inputs"]["ref_audios.ref_audio_0"]) == "LoadAudio"
    # The autogrow keys must be the dotted group.template form the core node takes:
    # a flat ref_image_0 makes MiniMaxH3ReferenceToVideo.execute raise TypeError.
    for key in hero["inputs"]:
        assert "." not in key or key.split(".", 1)[0] in {
            "ref_images", "ref_videos", "ref_video_audios", "ref_audios",
        }, key


def test_reference_group_ids_and_prefixes_exist_in_the_core_node():
    """Pin our autogrow keys to ComfyUI's own definition (skipped without core)."""
    source = _core_minimax_source()
    if source is None:
        pytest.skip("ComfyUI core is not importable in this environment")
    for group in (pl.PICTURE_GROUP, pl.VIDEO_GROUP, pl.VIDEO_AUDIO_GROUP, pl.AUDIO_GROUP):
        assert f'Autogrow.Input("{group}"' in source, f"core no longer declares {group}"
    for prefix in ("ref_image_", "ref_video_", "ref_video_audio_", "ref_audio_"):
        assert f'prefix="{prefix}"' in source, f"core no longer uses the {prefix} prefix"
    # execute must accept the groups as dicts (that is what the dotted keys feed)
    assert "ref_images=None" in source and "ref_video_audios=None" in source


def test_each_cell_has_its_own_seed_and_its_own_sampler():
    graph, _ = _build()
    nodes = graph.finalize()
    seeds = [
        node["inputs"]["noise_seed"]
        for node in nodes.values()
        if node["class_type"] == "RandomNoise"
    ]
    assert len(set(seeds)) == 2, f"cells must not share a seed: {seeds}"


def test_sampler_and_scheduler_reach_the_sampler_node():
    graph, _ = _build(steps=18, sampler_name="euler", scheduler="beta")
    nodes = graph.finalize()
    sched = next(node for node in nodes.values() if node["class_type"] == "BasicScheduler")
    select = next(node for node in nodes.values() if node["class_type"] == "KSamplerSelect")
    assert sched["inputs"]["steps"] == 18
    assert sched["inputs"]["scheduler"] == "beta"
    assert select["inputs"]["sampler_name"] == "euler"
    assert sched["inputs"]["denoise"] == 1.0


def test_shift_node_is_fed_the_model_and_both_shifts():
    graph, _ = _build(shift_video=9.0, shift_audio=2.5)
    nodes = graph.finalize()
    shift = next(node for node in nodes.values() if node["class_type"] == "MiniMaxH3SigmaShift")
    assert shift["inputs"]["model"] == SENTINEL["model"]
    assert shift["inputs"]["shift_video"] == 9.0
    assert shift["inputs"]["shift_audio"] == 2.5


# --------------------------------------------------------------------------- #
# the grid
# --------------------------------------------------------------------------- #
def test_the_cells_are_sequenced_so_they_render_in_list_order():
    """ComfyUI discovers a graph backwards, so the order has to be imposed.

    Without this the executor starts with the LAST cell - the sheet came out with the
    "from behind" view rendered first and the hero last, the opposite of the Cells tab.
    Each gate carries the model and waits for the previous cell's frames.
    """
    graph, _ = _build()
    nodes = graph.finalize()
    types = [node["class_type"] for node in nodes.values()]
    assert types.count("H3SheetOrderGate") == 2, "one gate per cell"

    gates = {
        node_id.rsplit(".", 1)[-1]: node
        for node_id, node in nodes.items()
        if node["class_type"] == "H3SheetOrderGate"
    }
    first, second = gates["order_gate_hero"], gates["order_gate_front"]
    assert "after" not in first["inputs"], "the first cell has nothing to wait for"
    previous_saver = nodes[second["inputs"]["after"][0]]
    assert previous_saver["class_type"] == "H3SheetCellSink"
    assert previous_saver["inputs"]["cell_id"] == "hero", (
        "gate 2 must wait for cell 1's finished frames, not for cell 2's own work"
    )

    # The gate feeds the sampler, so the wait actually blocks the render.
    for suffix in ("sigmas_hero", "guider_hero"):
        node = next(node for node_id, node in nodes.items() if node_id.endswith(suffix))
        assert nodes[node["inputs"]["model"][0]]["class_type"] == "H3SheetOrderGate"


def test_grid_receives_one_slot_per_cell_in_order():
    graph, outputs = _build()
    nodes = graph.finalize()
    grid = next(node for node_id, node in nodes.items() if node_id.endswith("sheet_grid"))
    assert set(grid["inputs"]) >= {
        "cells.cell_0", "cells.cell_1", "sheet_data", "name", "keep_frames",
    }
    for slot in ("cells.cell_0", "cells.cell_1"):
        # each slot goes through that cell's saver, which writes the frames to disk
        # (so the panel fills in while the job runs) and passes them on.
        saver = nodes[grid["inputs"][slot][0]]
        assert saver["class_type"] == "H3SheetCellSink"
        assert nodes[saver["inputs"]["images"][0]]["class_type"] == "VAEDecode"
        assert saver["inputs"]["cell_id"] == ("hero" if slot.endswith("0") else "front")
        assert json.loads(saver["inputs"]["sheet_data"])["cells"], "the saver needs the plan"
        assert saver["inputs"]["name"] == "sheet run"
    assert grid["inputs"]["name"] == "sheet run"
    assert json.loads(grid["inputs"]["sheet_data"])["cells"][0]["id"] == "hero"
    # The node's own outputs ARE the grid's outputs (sheet, cells, report, sheet_dir).
    grid_id = next(node_id for node_id, node in nodes.items() if node_id.endswith("sheet_grid"))
    assert [link[0] for link in outputs] == [grid_id, grid_id, grid_id, grid_id]
    assert [link[1] for link in outputs] == [0, 1, 2, 3]


def test_keep_frames_reaches_the_grid():
    graph, _ = _build(keep_frames=False)
    nodes = graph.finalize()
    grid = next(node for node in nodes.values() if node["class_type"] == "H3SheetGrid")
    assert grid["inputs"]["keep_frames"] is False


# --------------------------------------------------------------------------- #
# the widget -> core-node contract
# --------------------------------------------------------------------------- #
def _declared_inputs(class_type: str):
    """``(plain names, autogrow slot names)`` for a node class ComfyUI knows.

    Returns ``None`` when core is not importable, so the guard degrades to a skip.
    """
    try:
        import nodes as core_nodes
    except Exception:  # noqa: BLE001
        return None
    cls = core_nodes.NODE_CLASS_MAPPINGS.get(class_type)
    if cls is None:
        return None

    schema = getattr(cls, "define_schema", None)
    if callable(schema):
        plain: set[str] = set()
        autogrow: set[str] = set()
        for item in schema().inputs:
            template = getattr(item, "template", None)
            names = getattr(template, "names", None)
            if isinstance(names, list):
                autogrow.update(f"{getattr(item, 'id', item)}.{name}" for name in names)
            else:
                plain.add(str(getattr(item, "id", item)))
        return plain, autogrow

    types = cls.INPUT_TYPES()
    plain = set()
    for section in ("required", "optional"):
        plain.update((types.get(section) or {}).keys())
    return plain, set()


def test_every_wired_input_key_exists_on_its_target_node():
    """The regression guard for the whole autogrow class of bugs.

    A flat ``ref_image_0`` or ``cell_0`` key looks right in the graph and then
    explodes inside ComfyUI with "unexpected keyword argument" at sampling time.
    This checks each key the expansion wires against the target node's own schema:
    either a declared input, or a real ``<group>.<template><index>`` slot.
    """
    graph, _ = _build()
    nodes = graph.finalize()
    checked = 0
    for node_id, node in nodes.items():
        declared = _declared_inputs(node["class_type"])
        if declared is None:
            pytest.skip("ComfyUI core is not importable in this environment")
        plain, autogrow = declared
        if not plain and not autogrow:
            continue
        for key in node["inputs"]:
            checked += 1
            assert key in plain or key in autogrow, (
                f"{node['class_type']} ({node_id}) has no input {key!r}; "
                f"autogrow slots look like {sorted(autogrow)[:3]}"
            )
    assert checked > 20, "the guard must actually inspect the graph"


def test_autogrow_slots_use_the_group_dot_template_shape():
    flat_slot = re.compile(r"^(ref_image|ref_video|ref_video_audio|ref_audio|cell)_\d+$")
    graph, _ = _build()
    nodes = graph.finalize()
    for node in nodes.values():
        for key in node["inputs"]:
            if flat_slot.match(key):
                pytest.fail(f"flat autogrow key {key!r} on {node['class_type']}")


# --------------------------------------------------------------------------- #
# widgets -> spec
# --------------------------------------------------------------------------- #
def _widgets(**overrides):
    base = {
        "output_name": "sheet run",
        "frames_per_cell": 22,
        "seed": 4242,
        "sheet_layout": "grid",
        "sheet_columns": 3,
        "sheet_aspect": "1:1",
        "sheet_short_edge": 1024,
        "sheet_captions": False,
        "sheet_background": "#000000",
        "sheet_fit": "cover",
    }
    base.update(overrides)
    return base


def test_widgets_drive_the_layout_and_render_knobs():
    spec = sheet_node._spec_from_widgets(
        json.dumps({"cells": [{"id": "c1", "view": "front"}]}), _widgets()
    )
    assert spec.name == "sheet_run"
    assert spec.layout.layout == "grid"
    assert spec.layout.columns == 3
    assert spec.layout.aspect == "1:1"
    assert spec.layout.short_edge == 1024
    assert spec.layout.captions is False
    assert spec.layout.fit == "cover"
    assert spec.render.seed == 4242


def test_frames_per_cell_is_only_a_fallback_for_cells_without_their_own():
    spec = sheet_node._spec_from_widgets(
        json.dumps({"cells": [{"id": "a"}, {"id": "b", "frames": 39}]}),
        _widgets(frames_per_cell=5),
    )
    assert [cell.frames for cell in spec.cells] == [5, 39]


def test_missing_cells_fall_back_to_the_default_matrix():
    """A payload without cells must render instead of failing the whole prompt.

    The panel writes the payload, so an empty cell list is a state a user can reach
    (or a stale panel can leave behind); the standard 8-view matrix is a far better
    answer than a hard error, and the report says what happened.
    """
    spec = sheet_node._spec_from_widgets("{}", _widgets())
    assert [cell.id for cell in spec.cells] == [
        "face-neutral-neutral",
        "face-neutral-smile",
        "portrait-neutral-neutral",
        "front-neutral-neutral",
        "front-a-pose-neutral",
        "front-t-pose-neutral",
        "profile-neutral-neutral",
        "back-neutral-neutral",
    ]
    assert any("no cells" in warning for warning in spec.warnings)
    # References in the same payload are still honoured.
    spec = sheet_node._spec_from_widgets(
        json.dumps({"refs": {"pictures": [{"imageFile": "a.png", "role": "face"}]}}), _widgets()
    )
    assert len(spec.cells) == 8
    assert spec.pictures[0].file == "a.png"
    # ...and an explicit cell list always wins over the default.
    spec = sheet_node._spec_from_widgets(json.dumps({"cells": [{"id": "only"}]}), _widgets())
    assert [cell.id for cell in spec.cells] == ["only"]
    assert not any("no cells" in warning for warning in spec.warnings)


def test_invalid_payload_is_a_clear_error():
    with pytest.raises(ValueError, match="Invalid sheet_data JSON"):
        sheet_node._spec_from_widgets("{not json", _widgets())


def test_cells_are_capped():
    payload = {"cells": [{"id": f"c{i}"} for i in range(40)]}
    spec = sheet_node._spec_from_widgets(json.dumps(payload), _widgets())
    assert len(spec.cells) == 24


def test_node_schema_is_registered_under_the_expected_names():
    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    assert schema.node_id == "MiniMaxH3CharacterSheet"
    names = {item.id for item in schema.inputs}
    assert {"model", "video_vae", "audio_vae", "clip", "sheet_data", "cell_size"} <= names
    assert {"frames_per_cell", "steps", "sampler_name", "scheduler", "ref_image_size"} <= names
    assert "sheet_data" in names and "sheet_layout" in names
    assert sheet_node.NODE_CLASS_MAPPINGS["MiniMaxH3CharacterSheet"] is sheet_node.MiniMaxH3CharacterSheet


def test_every_sheet_aspect_option_is_a_ratio_the_pack_honours():
    """The combo list and the ratio table must not drift.

    An option the table does not know falls back to 3:2, so picking it would silently
    render a 3:2 sheet - the failure mode a new option (21:9) has to avoid.
    """
    import re

    from h3cs import sheet_spec as ss

    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    combo = next(
        item for item in schema.inputs if getattr(item, "id", None) == "sheet_aspect"
    )
    options = list(getattr(combo, "options", None) or [])
    assert "21:9" in options, "the ultrawide option the panel offers must be in the combo"
    for label in options:
        match = re.match(r"^(\d+):(\d+)$", label)
        assert match, f"{label!r} is not a W:H label"
        width, height = int(match.group(1)), int(match.group(2))
        assert abs(ss.aspect_ratio(label) - width / height) < 1e-9, (
            f"{label} falls back to another ratio - add it to _ASPECTS"
        )
    cell_combo = next(
        item for item in schema.inputs if getattr(item, "id", None) == "cell_aspect"
    )
    assert list(getattr(cell_combo, "options", None) or []) == list(ss.CELL_ASPECTS)
