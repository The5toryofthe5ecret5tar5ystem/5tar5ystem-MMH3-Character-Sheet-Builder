# ComfyUI-H3-Character-Sheet - tests for the panel's own live preview.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The step stream: one frame per sampling step, decoded from the latent, sent to the panel.

Everything here runs without a GPU and without a render: the wrapper is driven with the same
arguments the sampler passes, and the sender is a list. The decoder itself is exercised against
the real installed tiny VAE where there is one (and the latent2rgb fallback always works).
"""

from __future__ import annotations

import json

import pytest

from h3cs import preview_stream as ps


def _nested_latent(frames: int = 3, size: int = 8):
    import torch

    class FakeNested:  # the two things the wrapper looks at on a NestedTensor
        is_nested = True

        def __init__(self, video, audio):
            self.tensors = [video, audio]

    video = torch.zeros(1, 24, frames, size, size)
    audio = torch.zeros(1, 32, 2, frames * 2)
    return FakeNested(video, audio)


class _Sender:
    def __init__(self):
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)


class _StubSource:
    """A decoder that costs nothing: the real tiny VAE hands clips to a worker thread, which
    would make these tests a race. Its name is deliberately not "taeh3" so the wrapper decodes
    inline - the worker itself is covered by the real-decoder tests below."""

    name = "stub"

    def __init__(self, frames: int = 3) -> None:
        self.count = frames

    def clip(self, latent, *, tokens, max_frames, budget):
        from PIL import Image

        if getattr(latent, "ndim", 0) == 5:
            size = (latent.shape[-1], latent.shape[-2])
        else:
            size = (8, 8)
        made = [Image.new("RGB", size) for _ in range(min(self.count, max(1, tokens)))]
        return ps.strided(made, max_frames), max(1, tokens), 0.0


def _wrapper(**kwargs):
    sender = kwargs.pop("sender", None) or _Sender()
    kwargs.setdefault("source", _StubSource())
    return ps._SheetPreviewWrapper(sender=sender, **kwargs), sender


def executor_that_streams(steps: int = 1):
    """A sampler stand-in that calls the callback `steps` times."""

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for step in range(steps):
            callback(step, _nested_latent(), None, steps)
        return "sampled"

    return executor


# --------------------------------------------------------------------------- #
# reading the callback's latent
# --------------------------------------------------------------------------- #
def test_the_video_stream_is_read_out_of_the_nested_latent():
    latent = _nested_latent()
    video = ps.video_latent(latent)
    assert video is not None and tuple(video.shape) == (1, 24, 3, 8, 8)
    # A 4D latent is a single frame; anything else is "no preview from this step".
    assert ps.video_latent(video[:, :, 0]).shape == (1, 24, 1, 8, 8)
    assert ps.video_latent(None) is None
    assert ps.video_latent("nonsense") is None


def test_the_flat_packed_latent_is_refused_not_guessed():
    import torch

    # What the inner sampler works on: one row for every stream, no frame to decode on its own.
    assert ps.video_latent(torch.zeros(1, 24 * 3)) is None
    assert ps.video_latent(torch.zeros(1, 1, 84864)) is None


def test_the_packed_latent_a_render_hands_over_is_unpacked_into_a_frame():
    """This is the shape the sampler's callback actually receives, so it is the one that counts.

    ``comfy.samplers.sample_custom`` packs H3's video+audio streams into one flat row before
    sampling (measured ``(1, 1, 99136)`` for a 288x512 cell) and keeps the per-stream shapes in
    ``latent_shapes``, which is what the wrapper is given as an OUTER_SAMPLE argument.
    """
    import torch
    from comfy.latent_formats import MiniMaxH3AV

    nested = MiniMaxH3AV().fix_empty_latent(torch.zeros(1, 32, 6, 18, 32))
    packed, shapes = __import__("comfy.utils", fromlist=["pack_latents"]).pack_latents(nested.unbind())
    assert packed.ndim == 3, "the packed latent is a single flat row"
    assert len(shapes) > 1, "one shape per stream"

    video = ps.video_latent_from_pack(packed, shapes)
    assert video is not None and tuple(video.shape) == (1, 24, 6, 18, 32)
    assert ps.video_latent_from_pack(packed, None) is None, "no shapes, no frame"
    assert ps.video_latent_from_pack(torch.zeros(1, 24, 6, 18, 32), shapes) is None, (
        "a latent that is already unpacked does not need this path"
    )

    # ...and through the wrapper, end to end: the packed tensor in, a frame out.
    wrapper, sender = _wrapper(interval=0.0)

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for step in range(2):
            callback(step, packed, packed, 2)
        return "sampled"

    wrapper(executor, None, None, None, None, None, None, False, 1, latent_shapes=shapes)
    assert len(sender.payloads) == 2, "every step of a real pack streams"
    assert sender.payloads[0]["image"].startswith("data:image/jpeg;base64,")
    assert not wrapper._broken


# --------------------------------------------------------------------------- #
# the wrapper
# --------------------------------------------------------------------------- #
def test_the_wrapper_streams_frames_and_forwards_the_callback():
    wrapper, sender = _wrapper(name="sheet", cells_total=2, node_id=7, interval=0.0)
    seen = []

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for step in range(3):
            callback(step, _nested_latent(), None, 3)
        seen.append(latent_shapes)
        return "sampled"

    result = wrapper(
        executor, None, None, None, None, None,
        lambda step, x0, x, total: seen.append(("callback", step)),
        False, 1, latent_shapes=[(1, 24, 3, 8, 8)],
    )

    assert result == "sampled"
    assert seen[-1] == [(1, 24, 3, 8, 8)], "latent_shapes must be forwarded to the sampler"
    assert ("callback", 0) in seen, "the sampler's own callback must still run"
    assert len(sender.payloads) == 3, "one clip per step when the interval allows"
    first = sender.payloads[0]
    assert first["name"] == "sheet" and first["node_id"] == 7
    assert first["cell"] == 1 and first["cells"] == 2
    assert (first["step"], first["steps"]) == (1, 3)
    assert first["image"].startswith("data:image/jpeg;base64,"), "a frame the panel can show"
    assert first["width"] > 0 and first["height"] > 0


def test_a_clip_carries_its_frames_and_the_rate_to_play_them():
    """A still says nothing about a video render: the payload is a loop, and the panel is told
    how fast to play it."""
    wrapper, sender = _wrapper(interval=0.0, max_frames=8, fps=10)
    wrapper(executor_that_streams(), None, None, None, None, None, None, False, 1)
    clip = sender.payloads[0]
    assert clip["frame_count"] == 3
    assert len(clip["frames"]) == 3, "the panel loops `frames`"
    assert clip["frames"][0] == clip["image"], "`image` is the first frame, for a plain img"
    assert clip["fps"] == 10
    assert all(url.startswith("data:image/jpeg;base64,") for url in clip["frames"])


def test_the_cell_that_is_on_screen_is_named_in_every_clip():
    """The panel's re-roll button acts on the cell it is looking at, so it must be told which
    one that is - an index would have to be mapped back to the sheet by guesswork."""
    wrapper, sender = _wrapper(interval=0.0, cell_ids=["face-neutral-neutral", "front-a-pose"])

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for cell in range(2):
            for step in range(2):
                callback(step, _nested_latent(), None, 2)
        return None

    wrapper(executor, None, None, None, None, None, None, False, 1)
    assert [clip["cell_id"] for clip in sender.payloads] == [
        "face-neutral-neutral", "face-neutral-neutral", "front-a-pose", "front-a-pose",
    ]


def test_no_cell_ids_means_no_id_rather_than_a_wrong_one():
    wrapper, sender = _wrapper(interval=0.0)
    wrapper(executor_that_streams(), None, None, None, None, None, None, False, 1)
    assert sender.payloads[0]["cell_id"] == ""


def test_the_cell_counter_moves_on_every_new_sampler_call():
    wrapper, sender = _wrapper(interval=0.0)

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for cell in range(2):
            for step in range(2):
                callback(step, _nested_latent(), None, 2)
        return None

    wrapper(executor, None, None, None, None, None, None, False, 1)
    assert [payload["cell"] for payload in sender.payloads] == [1, 1, 2, 2]


def test_the_interval_throttles_but_never_drops_the_last_step():
    wrapper, sender = _wrapper(interval=999.0)

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for step in range(4):
            callback(step, _nested_latent(), None, 4)
        return None

    wrapper(executor, None, None, None, None, None, None, False, 1)
    steps = [(payload["step"], payload["steps"]) for payload in sender.payloads]
    assert steps[0] == (1, 4), "the first step always gets through"
    assert steps[-1] == (4, 4), "and the last one, however long the render took"
    assert len(steps) < 4, "the steps in between are throttled"


def test_a_dead_sender_does_not_fail_the_render():
    def explode(payload):
        raise RuntimeError("socket closed")

    wrapper = ps._SheetPreviewWrapper(sender=explode, interval=0.0)

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        callback(0, _nested_latent(), None, 1)
        return "sampled"

    assert wrapper(executor, None, None, None, None, None, None, False, 1) == "sampled"


def test_a_bad_step_is_swallowed_not_fatal():
    """A latent we cannot read stops the stream, and never the render.

    The latent's shape is fixed for a whole render, so one unreadable callback is the whole
    render's answer - which is why it is disabled rather than retried on every step.
    """
    wrapper, sender = _wrapper(interval=0.0)
    calls = []

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        callback(0, _nested_latent(), None, 2)   # a frame, as usual
        callback(1, object(), None, 2)           # then something unreadable
        calls.append("ran")
        return "sampled"

    assert wrapper(executor, None, None, None, None, None, None, False, 1) == "sampled"
    assert calls == ["ran"]
    assert [payload["step"] for payload in sender.payloads] == [1]
    assert wrapper._broken, "and the stream stands down for the rest of the run"


def test_a_latent_with_no_frame_disables_streaming_once_and_says_why():
    """The shape that made this feature silently do nothing before: logging it is the point."""
    wrapper, sender = _wrapper(interval=0.0)

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        callback(0, object(), None, 1)
        callback(0, object(), None, 1)
        return "sampled"

    assert wrapper(executor, None, None, None, None, None, None, False, 1) == "sampled"
    assert wrapper._broken, "a latent we cannot read stops the stream, it does not retry it"
    assert sender.payloads == []
    assert "nothing (callback got None)" in ps.describe_latent(None)
    assert "nested latent" in ps.describe_latent(_nested_latent())


def test_the_builtin_preview_is_muted_while_sampling_and_restored_after():
    original = {
        cls: cls.__dict__["decode_latent_to_preview_image"]
        for cls in ps.previewer_classes()
        if "decode_latent_to_preview_image" in cls.__dict__
    }
    assert original
    wrapper, _ = _wrapper(mute=True, stream=False, interval=0.0)
    seen = {}

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for cls in ps.previewer_classes():
            if "decode_latent_to_preview_image" in cls.__dict__:
                seen[cls.__name__] = cls.decode_latent_to_preview_image(None, "JPEG", None)
        return None

    try:
        wrapper(executor, None, None, None, None, None, None, False, 1)
    finally:
        for cls, method in original.items():
            cls.decode_latent_to_preview_image = method

    assert seen and all(value is None for value in seen.values())
    for cls, method in original.items():
        assert cls.decode_latent_to_preview_image is method


def test_streaming_alone_leaves_the_builtin_preview_alone():
    """`render.comfyPreview: true` means: keep ComfyUI's stream, and add ours."""
    wrapper, sender = _wrapper(mute=False, stream=True, interval=0.0)
    seen = {}

    def executor(noise, latent_image, sampler, sigmas, denoise_mask, callback, disable_pbar,
                 seed, latent_shapes=None):
        for cls in ps.previewer_classes():
            if "decode_latent_to_preview_image" in cls.__dict__:
                seen[cls.__name__] = cls.decode_latent_to_preview_image
        callback(0, _nested_latent(), None, 1)
        return None

    wrapper(executor, None, None, None, None, None, None, False, 1)
    assert seen and all(method is not ps._no_preview for method in seen.values())
    assert sender.payloads, "our own stream is independent of that switch"


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #
def test_the_encoder_always_returns_an_embeddable_jpeg():
    from PIL import Image

    payload = ps.encode_payload(Image.new("RGB", (1200, 800), (10, 20, 30)), {"step": 1})
    assert payload["image"].startswith("data:image/jpeg;base64,")
    assert payload["width"] == ps.MAX_WIDTH, "a wide frame is capped before it is sent"
    assert payload["height"] == round(800 * ps.MAX_WIDTH / 1200)


def test_the_payload_is_json_serialisable():
    """It crosses a websocket: one non-serialisable value and the panel sees nothing."""
    from PIL import Image

    json.dumps(ps.encode_payload(Image.new("RGB", (32, 32)), {"cell": 1, "steps": 3}))


def test_the_latent2rgb_fallback_needs_no_model_and_decodes_in_milliseconds():
    from comfy.latent_formats import MiniMaxH3AV

    source = ps.build_frame_source(MiniMaxH3AV(), prefer_tiny_vae=False)
    assert source is not None and source.name == "latent2rgb"
    import torch

    latent = torch.zeros(1, 24, 4, 16, 24)
    frames, used, per_token = source.clip(latent, tokens=4, max_frames=8, budget=1.5)
    assert len(frames) == 4, "the cheap decoder loops the whole prefix it is asked for"
    assert frames[0] is not None and used == 4 and per_token == 0.0
    assert len(source.clip(latent, tokens=4, max_frames=2, budget=1.5)[0]) == 2, "and honours the cap"


def test_a_tiny_vae_is_preferred_when_it_is_installed():
    """On a box with vae_approx/taeh3* the preview is real frames, and how many of them is
    measured rather than guessed: the first clip is one token, the next spends the budget."""
    from comfy.latent_formats import MiniMaxH3AV

    source = ps.build_frame_source(MiniMaxH3AV())
    if source is None:
        pytest.skip("no ComfyUI latent_preview on the path")
    if source.name == "latent2rgb":
        pytest.skip("no taeh3 tiny VAE installed")
    import torch

    latent = torch.zeros(1, 24, 4, 16, 24)
    frames, used, per_token = source.clip(latent, tokens=1, max_frames=8, budget=1.5)
    assert frames and used == 1 and per_token > 0, "the first clip also measures the rate"
    # The chooser: as many as the budget affords, at least three so the panel gets a loop,
    # and a still only when even three would be too expensive.
    assert source.tokens_for(143.0, 10) == 10, "a cheap cell decodes the whole clip"
    assert source.tokens_for(1500.0, 10) == 3, "a slow one still loops the first three"
    assert source.tokens_for(4000.0, 10) == 1, "and an unaffordable one falls back to a still"
    assert source.tokens_for(0.0, 10) == 1, "an unmeasured rate stays at one token"
    assert source.tokens_for(100.0, 2) == 2, "never more than the cell has"


# --------------------------------------------------------------------------- #
# attaching
# --------------------------------------------------------------------------- #
class _StubModel:
    clones = 0

    class _Inner:
        latent_format = None

    model = _Inner()

    def __init__(self, *, explode: bool = False, wrappers: dict | None = None) -> None:
        self.explode = explode
        self.wrappers: dict[tuple, object] = wrappers or {}

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


def test_attaching_adds_one_wrapper_and_is_idempotent():
    if ps.comfy is None:
        pytest.skip("no ComfyUI on the path")
    _StubModel.clones = 0
    model = _StubModel()
    wrapped = ps.attach_sheet_preview(model, name="sheet", cells_total=3)
    assert wrapped is not model and _StubModel.clones == 1
    assert ps.attach_sheet_preview(wrapped) is wrapped, "a second call must not stack"
    assert _StubModel.clones == 1


def test_attaching_nothing_is_a_no_op():
    model = _StubModel()
    assert ps.attach_sheet_preview(model, mute=False, stream=False) is model
    assert ps.attach_sheet_preview(None) is None
    # A patcher that refuses to clone is a warning, not a failed render.
    assert ps.attach_sheet_preview(_StubModel(explode=True)) is not model


def test_the_sheet_graph_attaches_the_preview_before_every_cell():
    """The wiring: one wrapper on the model every cell samples through, switches honoured."""
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parents[1] / "h3_character_sheet" / "nodes" / "sheet.py"
    text = source.read_text()
    call = text.find("attach_sheet_preview(")
    shift = text.find('"MiniMaxH3SigmaShift"')
    assert call != -1 and shift != -1 and call < shift
    assert re.search(r"if live_preview or not comfy_preview:", text)
    assert re.search(r"stream=live_preview,", text) and re.search(r"mute=not comfy_preview,", text)
    assert re.search(r"live_preview=bool\(spec\.render\.live_preview\)", text), (
        "execute must pass the payload switch through"
    )

def test_strided_keeps_both_ends_of_a_clip():
    frames = list(range(10))
    assert ps.strided(frames, 20) == frames, "a short clip is left alone"
    assert ps.strided(frames, 1) == [0], "one frame means the first one"
    picked = ps.strided(frames, 4)
    assert len(picked) == 4 and picked[0] == 0 and picked[-1] == 9, "and both ends survive"
