# ComfyUI-H3-Character-Sheet - LoRAs on the model input.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""A LoRA loader wired into ``model`` has to survive the sheet's own plumbing.

This pack owns no model code, and that is the whole reason LoRAs work: the MODEL socket is handed
over by a loader (core's ``LoraLoaderModelOnly``, rgthree's Power Lora Loader, a stack of them),
and what a loader hands over is a ``ModelPatcher`` with ``patches`` filled in - the LoRA itself.
The node then clones that patcher exactly once (that clone is where the live preview hangs itself)
and passes the same copy to H3's own nodes, so every cell - and every board of a suite - samples
through the patches. Verified against a real render at the time this was written (same seed, no
LoRA vs a style LoRA at 1.0: 62% of pixels changed).

These tests are the guard rails, because the failure that would silently break LoRAs is a future
change *re-loading* the model (a fresh ``ModelPatcher``, a re-``UNETLoader``, dropping the clone
and handing over the raw model):

* no node in any expansion is a loader - the graph the pack builds has one MODEL input and nothing
  else that could produce a model;
* the patcher that reaches ``MiniMaxH3SigmaShift`` still carries the patches, the ``object_patches``
  and the ``model_options`` it arrived with, and it is a copy (the caller's patcher is untouched);
* every board of a suite shares that one patched copy;
* the tooltip, the Help tab and the README keep saying so - undocumented support is support nobody
  uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 - ComfyUI's own dependency, and so is the rest
_MODEL_PATCHER = pytest.importorskip("comfy.model_patcher")
_WRAPPERS = pytest.importorskip("comfy.patcher_extension")
ModelPatcher = _MODEL_PATCHER.ModelPatcher
WrappersMP = _WRAPPERS.WrappersMP

from comfy_execution.graph_utils import GraphBuilder  # noqa: E402

from h3cs import help as help_mod  # noqa: E402
from h3cs import one_pass as op  # noqa: E402
from h3cs import preview_stream as ps  # noqa: E402
from h3cs import sheet_spec as ss  # noqa: E402
from h3cs import suite as suite_mod  # noqa: E402
from h3cs.nodes import sheet as sheet_node  # noqa: E402
from h3cs.planner import cell_work_items, grid_payload, reference_plan  # noqa: E402

from tests.test_sheet_one_pass import _spec  # noqa: E402  (shared payload fixture)
from tests.test_sheet_suite import _suite_spec  # noqa: E402

#: What a LoRA actually lands in: one key of ``ModelPatcher.patches``, the way
#: ``comfy.sd.load_lora_for_models`` writes it (`diffusion_model.<block>.<layer>`).
LORA_KEY = "diffusion_model.blocks.0.attn.wq.weight"

#: The node types that could *make* a model. If one of these ever shows up in an expansion, the
#: model the user wired in has been replaced (or reloaded) and their LoRA is gone.
MODEL_MAKERS = {
    "UNETLoader",
    "CheckpointLoaderSimple",
    "CheckpointLoader",
    "LoraLoader",
    "LoraLoaderModelOnly",
    "ModelSamplingSD3",
}


class _H3StandIn:
    """The least a model has to be for ``ModelPatcher`` to carry it.

    Nothing in these tests samples, so no weight is ever read: the stand-in only has to survive
    ``clone()`` and the attribute lookups along the way.
    """

    def __init__(self) -> None:
        self.model_options = {"transformer_options": {}}
        self.latent_format = None


@pytest.fixture(autouse=True)
def _quiet_patcher_teardown(monkeypatch):
    """``ModelPatcher.__del__`` detaches from a real model; a stand-in cannot answer that.

    It only fires while the test's garbage is collected, and the "Exception ignored" it prints
    would look like a failure without being one.
    """
    monkeypatch.setattr(
        ModelPatcher, "detach", lambda self, unpatch_all=True: self.model, raising=False
    )


def _lora_model(strength: float = 1.0) -> ModelPatcher:
    """The object a LoRA loader hands to the node: a patcher with the LoRA already in it."""
    device = torch.device("cpu")
    patcher = ModelPatcher(_H3StandIn(), load_device=device, offload_device=device, size=1)
    patcher.patches = {LORA_KEY: [("FlatAnime_MiniMax_H3.safetensors", torch.ones(2, 2), strength)]}
    patcher.model_options["lora_patches"] = ["FlatAnime_MiniMax_H3.safetensors"]
    patcher.object_patches = {"blocks.0": _H3StandIn()}
    return patcher


def _literal_models(nodes: dict) -> list:
    """Every MODEL that sits in a node input as an object (a wired model shows up as a link)."""
    return [
        value
        for node in nodes.values()
        for key, value in node["inputs"].items()
        if key == "model" and isinstance(value, ModelPatcher)
    ]


def _node_id(nodes: dict, class_type: str) -> str:
    return next(nid for nid, node in nodes.items() if node["class_type"] == class_type)


def _per_cell_graph(model):
    spec = _spec()
    graph = GraphBuilder()
    sheet_node.build_sheet_graph(
        graph,
        model=model,
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        work_items=cell_work_items(
            spec, cell_size=1024, ref_image_size="match", ref_scope=ss.DEFAULT_REF_SCOPE
        ),
        refs=reference_plan(spec),
        payload=grid_payload(spec, name="sheet run"),
        name="sheet run",
    )
    return graph.finalize()


def _one_pass_graph(model):
    spec = _spec()
    graph = GraphBuilder()
    sheet_node.build_one_pass_graph(
        graph,
        model=model,
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        plan=op.one_pass_plan(spec),
        refs=reference_plan(spec),
        payload=grid_payload(spec, name="one-pass sheet"),
        name="one-pass sheet",
    )
    return graph.finalize()


def _suite_graph(model):
    spec = _suite_spec()
    boards, warnings = suite_mod.suite_boards(spec)
    assert not warnings, warnings
    expand, _outputs, _lines = sheet_node.build_suite_graph(
        boards=boards, model=model, clip="CLIP", video_vae="VVAE", audio_vae="AVAE",
        name=str(spec.name),
    )
    return expand


# --------------------------------------------------------------------------- #
# the patched model survives every expansion
# --------------------------------------------------------------------------- #
def test_a_lora_reaches_the_sampler_of_a_per_cell_sheet():
    patcher = _lora_model()
    nodes = _per_cell_graph(patcher)

    assert not (MODEL_MAKERS & {node["class_type"] for node in nodes.values()}), (
        "the expansion may not load a model - that would discard the user's LoRA"
    )
    carried = _literal_models(nodes)
    assert len(carried) == 1, "one copy of the model, made once, is what every cell samples through"
    assert carried[0] is not patcher, "the copy is the pack's; the caller's patcher is untouched"
    assert LORA_KEY in carried[0].patches, "the LoRA patch has to ride along"
    assert carried[0].model is patcher.model, "same weights, same blocks - only the wrapper is new"

    # The chain the model travels: sigma shift -> the pack's render-order gate -> the guider that
    # samples. The gate is a pass-through (it hands on the very object it was given), so the LoRA is
    # on the model every cell's guider actually uses.
    shift_id = _node_id(nodes, "MiniMaxH3SigmaShift")
    assert nodes[shift_id]["inputs"]["model"] is carried[0]
    gates = {nid: node for nid, node in nodes.items()
             if node["class_type"] == "H3SheetOrderGate"}
    assert gates, "every cell hangs off the order gate"
    assert all(node["inputs"]["model"] == [shift_id, 0] for node in gates.values())
    guiders = [node for node in nodes.values() if node["class_type"] == "BasicGuider"]
    assert len(guiders) == len(gates), "one guider per cell"
    assert all(node["inputs"]["model"][0] in gates for node in guiders), (
        "the model the cell samples comes from the gate, which passes the patched object through"
    )


def test_a_lora_reaches_the_single_pass_of_a_one_pass_sheet():
    patcher = _lora_model()
    nodes = _one_pass_graph(patcher)

    assert not (MODEL_MAKERS & {node["class_type"] for node in nodes.values()})
    carried = _literal_models(nodes)
    assert len(carried) == 1, "one pass, one model - and it is the patched one"
    assert LORA_KEY in carried[0].patches
    shift_id = _node_id(nodes, "MiniMaxH3SigmaShift")
    assert nodes[shift_id]["inputs"]["model"] is carried[0]
    guider = next(n for n in nodes.values() if n["class_type"] == "BasicGuider")
    assert guider["inputs"]["model"] == [shift_id, 0]


def test_every_board_of_a_suite_shares_the_one_patched_model():
    patcher = _lora_model(strength=0.6)
    nodes = _suite_graph(patcher)

    assert not (MODEL_MAKERS & {node["class_type"] for node in nodes.values()})
    carried = _literal_models(nodes)
    assert len({id(model) for model in carried}) == 1, (
        "four boards, one model: a second copy would mean the preview wrapper (and so the LoRA "
        "bookkeeping) was rebuilt per board"
    )
    assert LORA_KEY in carried[0].patches
    shifts = [n for n in nodes.values() if n["class_type"] == "MiniMaxH3SigmaShift"]
    assert len(shifts) > 1, "a suite builds a render per board"
    assert all(shift["inputs"]["model"] is carried[0] for shift in shifts)


def test_the_preview_wrapper_keeps_every_patch_it_was_handed():
    """The one place the pack ever touches the model: a clone plus an OUTER_SAMPLE wrapper."""
    if ps.comfy is None:
        pytest.skip("no ComfyUI on the path")

    patcher = _lora_model(strength=0.6)
    wrapped = ps.attach_sheet_preview(patcher, name="sheet run", node_id=7, cells_total=5)

    assert wrapped is not patcher
    assert wrapped.model is patcher.model
    assert wrapped.patches == patcher.patches
    assert wrapped.object_patches == patcher.object_patches
    assert wrapped.model_options["lora_patches"] == patcher.model_options["lora_patches"]
    assert ps.STREAM_KEY in (wrapped.wrappers.get(WrappersMP.OUTER_SAMPLE) or {})
    assert ps.STREAM_KEY not in (patcher.wrappers.get(WrappersMP.OUTER_SAMPLE) or {}), (
        "the model the user wired in stays clean - the wrapper belongs to the pack's copy"
    )


def test_a_model_that_is_not_a_patcher_still_renders():
    """Belt and braces: the plumbing may not *require* a patcher to build a graph."""
    carried = _literal_models(_per_cell_graph("MODEL"))
    assert carried == [], "a plain value is passed through as the value it is"


# --------------------------------------------------------------------------- #
# it stays documented
# --------------------------------------------------------------------------- #
def test_the_model_input_says_it_takes_loras():
    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    tooltip = next(item for item in schema.inputs if item.id == "model").tooltip
    assert "LoRA" in tooltip, "the socket a user hovers has to say LoRAs are welcome"
    assert "LoraLoaderModelOnly" in tooltip or "Power Lora" in tooltip, tooltip
    assert "loads no model of its own" in schema.description, schema.description


def test_the_help_tab_says_where_the_loader_goes():
    tips = next(section for section in help_mod.SECTIONS if section.id == "tips")
    bullet = next((b for b in tips.bullets if b.startswith("**LoRAs**")), None)
    assert bullet, "the tips list is where a user looks for 'can I use a LoRA'"
    assert "model" in bullet and ("LoraLoaderModelOnly" in bullet or "Power Lora" in bullet), bullet
    unet = next(req for req in help_mod.REQUIREMENTS if req.id == "unet")
    assert "LoRA" in unet.note, unet.note


def test_the_readme_has_a_lora_section():
    readme = (Path(sheet_node.__file__).resolve().parents[2] / "README.md").read_text()
    assert "### LoRAs" in readme
    section = readme.split("### LoRAs", 1)[1].split("\n## ", 1)[0]
    for wanted in ("Power Lora Loader", "model", "0.4-0.6", "TURBO"):
        assert wanted in section, f"the LoRA section has to mention {wanted!r}"
