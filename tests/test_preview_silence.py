# ComfyUI-H3-Character-Sheet - tests for muting ComfyUI's own preview.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The pack mutes the sampler's built-in preview so a sheet render puts nothing under the node.

The mechanism is the one KJNodes' ModelPreviewOverrideKJ uses for its ``suppress_default_preview``:
an OUTER_SAMPLE wrapper that swaps ``decode_latent_to_preview_image`` out for the duration of the
sampling call. These tests run against the real ``latent_preview`` module (it is importable
wherever ComfyUI is), plus plain stubs for the patcher, so no GPU and no model are involved.
"""

from __future__ import annotations

import pytest

from h3cs import preview_silence


class _StubModel:
    """The two patcher methods ``silence_model_previews`` uses, and nothing else."""

    clones = 0

    def __init__(self, *, explode: bool = False, wrappers: dict | None = None) -> None:
        self.explode = explode
        self.wrappers: dict[tuple, dict] = wrappers or {}

    def clone(self):
        if self.explode:
            raise RuntimeError("patcher refused")
        type(self).clones += 1
        return _StubModel(wrappers=dict(self.wrappers))

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers[(wrapper_type, key)] = wrapper

    def get_wrappers(self, wrapper_type, key):
        value = self.wrappers.get((wrapper_type, key))
        return [] if value is None else [value]


def test_the_previewer_tree_is_walked_recursively():
    classes = preview_silence.previewer_classes()
    names = {cls.__name__ for cls in classes}
    if not names:
        pytest.skip("no ComfyUI latent_preview on the path")
    # The root plus the concrete implementations, including subclasses of subclasses.
    assert "LatentPreviewer" in names
    assert "TAESDPreviewerImpl" in names
    assert "TAEHVPreviewerImpl" in names, "TAEHV subclasses TAESD - the walk must recurse"
    assert "Latent2RGBPreviewer" in names


def test_sampling_runs_with_the_preview_muted_and_the_core_restored():
    """Inside the executor the decode returns None; after it, the original method is back."""
    original = {
        cls: cls.__dict__["decode_latent_to_preview_image"]
        for cls in preview_silence.previewer_classes()
        if "decode_latent_to_preview_image" in cls.__dict__
    }
    assert original, "expected concrete previewers to patch"

    seen: dict[str, object] = {}

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar, seed,
                 latent_shapes=None):
        # This is the moment the sampler would build its preview callback - every concrete
        # previewer must be muted here, while the sampler's own callback is untouched.
        for cls in preview_silence.previewer_classes():
            if "decode_latent_to_preview_image" in cls.__dict__:
                seen[cls.__name__] = cls.decode_latent_to_preview_image(None, "JPEG", None)
        seen["callback"] = callback
        seen["latent_shapes"] = latent_shapes
        return "sampled"

    wrapper = preview_silence._SilenceBuiltInPreview(node_id=7)
    sentinel = object()
    try:
        result = wrapper(
            executor=executor,
            noise="noise",
            latent_image="latent",
            sampler="sampler",
            sigmas="sigmas",
            denoise_mask=None,
            callback=sentinel,
            disable_pbar=True,
            seed=1234,
            latent_shapes={"video": (1, 24, 3, 8, 8)},
        )
    finally:
        for cls, method in original.items():
            cls.decode_latent_to_preview_image = method

    assert result == "sampled"
    assert seen and all(value is None for key, value in seen.items() if key not in {"callback", "latent_shapes"})
    assert seen["callback"] is sentinel, "the progress callback must pass through untouched"
    assert seen["latent_shapes"] == {"video": (1, 24, 3, 8, 8)}, "latent_shapes must be forwarded"
    assert wrapper.silenced, "the wrapper reports what it silenced"

    for cls, method in original.items():
        assert cls.decode_latent_to_preview_image is method


def test_a_failing_render_still_restores_the_core():
    original = {
        cls: cls.__dict__["decode_latent_to_preview_image"]
        for cls in preview_silence.previewer_classes()
        if "decode_latent_to_preview_image" in cls.__dict__
    }

    def executor(*args, **kwargs):
        raise RuntimeError("out of memory in the sampler")

    wrapper = preview_silence._SilenceBuiltInPreview()
    with pytest.raises(RuntimeError):
        wrapper(
            executor, "noise", "latent", "sampler", "sigmas", None, None, False, 1,
            latent_shapes=None,
        )

    for cls, method in original.items():
        assert cls.decode_latent_to_preview_image is method


def test_a_model_gains_the_wrapper():
    if preview_silence.comfy is None:
        pytest.skip("no ComfyUI on the path")
    model = _StubModel()
    _StubModel.clones = 0
    wrapped = preview_silence.silence_model_previews(model, node_id=3)

    assert wrapped is not model, "the original patcher must not be mutated"
    assert _StubModel.clones == 1
    assert preview_silence.is_silenced(wrapped)
    assert not preview_silence.is_silenced(model)


def test_the_wrapper_is_added_once():
    if preview_silence.comfy is None:
        pytest.skip("no ComfyUI on the path")
    model = _StubModel()
    _StubModel.clones = 0
    once = preview_silence.silence_model_previews(model)
    twice = preview_silence.silence_model_previews(once)
    assert twice is once, "a second call must not stack a second wrapper"
    assert _StubModel.clones == 1, "and must not clone the patcher again"


def test_a_patcher_that_refuses_is_not_fatal():
    """A preview is a convenience; nothing about a render may fail over it."""
    model = _StubModel(explode=True)
    assert preview_silence.silence_model_previews(model) is model


def test_no_model_is_not_an_error():
    assert preview_silence.silence_model_previews(None) is None
    assert preview_silence.is_silenced(None) is False


def test_the_sheet_graph_mutes_the_model_before_every_cell():
    """The one wiring assertion that matters: it happens at build time, before the shift."""
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parents[1] / "h3_character_sheet" / "nodes" / "sheet.py"
    text = source.read_text()
    call = text.find("silence_model_previews(model")
    shift = text.find('"MiniMaxH3SigmaShift"')
    assert call != -1, "build_sheet_graph must mute the preview"
    assert shift != -1
    assert call < shift, "mute the incoming model, so every cell inherits it"
    assert re.search(r"if not comfy_preview:\s*\n\s+model = silence_model_previews", text), (
        "the render spec's comfyPreview switch must be able to keep the preview"
    )
    assert re.search(r"from \.\.preview_silence import silence_model_previews", text)
    assert re.search(r"comfy_preview=bool\(spec\.render\.comfy_preview\)", text), (
        "execute must pass the switch through to the graph builder"
    )
