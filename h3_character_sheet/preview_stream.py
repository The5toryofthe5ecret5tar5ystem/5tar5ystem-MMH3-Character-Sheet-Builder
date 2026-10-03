# ComfyUI-H3-Character-Sheet - the panel's own live preview.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""A frame per sampling step, streamed to the panel.

ComfyUI's own per-step preview is muted for sheet renders (see ``preview_silence``) because it
is a stream this pack does not control and does not need. This is the other half of the KJNodes
*Model Preview Override* idea: our own preview, of our own render, delivered to our own panel.

Where it comes from. The sampler's callback is the only place a render is legible while it
runs, and an ``OUTER_SAMPLE`` wrapper is the only place to stand in front of it. What that
callback is handed is H3's latent in the sampler's own **flat packed** form - ``(B, 1, N)``,
every stream's features in one row (measured: ``(1, 1, 99136)`` for a 288x512 cell) - so a frame
is taken by unpacking it with the ``latent_shapes`` the wrapper was given, exactly as
``comfy.samplers.sample_custom`` unpacks it for ComfyUI's own previewer. Stream 0 is the 24-channel
video stream; the frame is ``[:, :, :1]`` of it.

How it is decoded. The same tiny VAE the rest of ComfyUI previews with (``taeh3``), because it
turns a latent into something that reads as the render rather than as coloured fog. Two
constraints decide how it is run:

* **On the CPU, in float32.** During a render the GPU belongs to the sampler - this box has
  710 MB free with an H3 model resident, and a preview that OOMs a render is not a preview.
  (Both halves matter: fp16 on the CPU is 350x slower - 50s for a frame that takes 143ms in
  fp32.)
* **On a worker thread.** A frame is ~110-150ms for a 288x512 cell, which the sampler's thread
  must not spend. The callback only copies one latent frame to the host (~55 KB) and hands it
  over; the worker decodes and drops previews it cannot keep up with, because a late preview of
  an old step is worth nothing.

When the tiny VAE is not installed (or will not build), the preview falls back to ComfyUI's own
latent2rgb factors: 3ms, no model, no thread - blurrier, but never absent and never expensive.

Nothing here may fail a render: every step is wrapped, a failure disables streaming for the run
and logs once.
"""

from __future__ import annotations

import base64
import io
import logging
import queue
import threading
import time
from typing import Any, Callable

try:  # ComfyUI is always present at runtime; soft so the tests can run without the server.
    import comfy.patcher_extension
    import latent_preview
except Exception:  # noqa: BLE001 - a unit test without ComfyUI on the path
    comfy = None  # type: ignore[assignment]
    latent_preview = None  # type: ignore[assignment]

from .preview_silence import _no_preview, previewer_classes

log = logging.getLogger(__name__)

#: The wrapper key and the websocket event name. One event for the whole pack: the panel
#: filters by node id and sheet name.
STREAM_KEY = "h3_sheet_preview"
EVENT = "h3_sheet_preview"

#: At most one preview per this many seconds. A preview is a look at the run, not a video
#: stream: on a 22-frame cell a step takes ~130ms, so this is roughly every third step.
MIN_INTERVAL = 0.35
#: JPEG quality for the streamed frame.
JPEG_QUALITY = 78
#: Widest the frame is sent at (a 1536px cell decodes to 1536px wide, which is 300 KB per frame
#: and pointless in a 620px node).
MAX_WIDTH = 512
#: Frames the worker may have waiting. Two: one being decoded, one ahead. Older ones are
#: dropped - a preview of a step that already passed helps nobody.
QUEUE_SIZE = 2
#: The vae_approx file this preview wants, by prefix (``taeh3`` matches ``taeh3.safetensors``
#: and ``taeh3_decoder.safetensors``).
TINY_VAE_PREFIX = "taeh3"


def describe_latent(x0: Any) -> str:
    """A short, honest description of what the callback was handed (for the run log)."""
    if x0 is None:
        return "nothing (callback got None)"
    if getattr(x0, "is_nested", False):
        shapes = [tuple(getattr(t, "shape", ())) for t in (getattr(x0, "tensors", None) or [])]
        return f"nested latent {shapes}"
    shape = tuple(getattr(x0, "shape", ())) or None
    return f"{type(x0).__name__} {shape} ndim={getattr(x0, 'ndim', '?')}"


def video_latent(x0: Any) -> Any:
    """The 5D video latent inside whatever the callback was handed, or ``None``.

    ``None`` means "no preview from this step", which is a normal answer: anything unexpected is
    skipped rather than guessed at. A flat packed latent is unpacked first (see
    :func:`video_latent_from_pack`).
    """
    if x0 is None:
        return None
    if getattr(x0, "is_nested", False):
        tensors = getattr(x0, "tensors", None) or []
        if not tensors:
            return None
        x0 = tensors[0]
    ndim = getattr(x0, "ndim", None)
    if ndim == 5:
        return x0
    if ndim == 4:  # a single frame, already unbatched of time
        return x0.unsqueeze(2)
    return None


def video_latent_from_pack(x0: Any, latent_shapes: Any) -> Any:
    """The video stream of a flat packed latent - the form the sampler's callback receives.

    ``latent_shapes`` is what ``sample_custom`` recorded when it packed the nested streams, and
    passing it back to ``unpack_latents`` restores them exactly (checked as a round trip in the
    tests). The first 5D stream is the video one; H3 packs video before audio.
    """
    if comfy is None or x0 is None or not latent_shapes:
        return None
    if getattr(x0, "ndim", None) != 3:
        return None
    try:
        streams = comfy.utils.unpack_latents(x0, latent_shapes)
    except Exception as exc:  # noqa: BLE001 - a shape we cannot read is a skipped frame
        log.debug("Character sheet preview: could not unpack the latent (%s)", exc)
        return None
    for stream in streams or []:
        if getattr(stream, "ndim", 0) == 5:
            return stream
    return None


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #
class _Latent2RgbSource:
    """ComfyUI's own cheap preview math: the latent projected onto RGB factors."""

    name = "latent2rgb"

    def __init__(self, latent_format: Any) -> None:
        self.previewer = latent_preview.Latent2RGBPreviewer(
            latent_format.latent_rgb_factors,
            getattr(latent_format, "latent_rgb_factors_bias", None),
            getattr(latent_format, "latent_rgb_factors_reshape", None),
        )

    def frame(self, latent: Any) -> Any:
        return self.previewer.decode_latent_to_preview(latent)


class _TinyVaeSource:
    """The ``taeh3`` tiny VAE, on the CPU in float32 (see the module docstring)."""

    name = "taeh3"

    def __init__(self, model: Any, label: str) -> None:
        self.model = model
        self.label = label

    def frame(self, latent: Any) -> Any:
        import torch

        with torch.no_grad():
            frames = self.model.decode(latent.to(dtype=torch.float32))
        # (B, 3, T, H, W) -> the first frame, as the float [0,1] image preview_to_image wants.
        while frames.ndim > 4:
            frames = frames[:, :, 0]
        return latent_preview.preview_to_image(frames[0].movedim(0, -1), do_scale=False)


def _tiny_vae_candidates() -> list[tuple[str, str]]:
    """``(label, path)`` for every installed tiny VAE that can preview H3, best first.

    The full checkpoint (encoder + decoder) is preferred over the decoder-only file: they decode
    H3's 24-channel latent to the same picture at different resolutions, and the full one is the
    one ComfyUI's own previewer and KJNodes' *Model Preview Override* use.
    """
    import folder_paths

    try:
        names = [n for n in folder_paths.get_filename_list("vae_approx") if n.startswith(TINY_VAE_PREFIX)]
    except Exception:  # noqa: BLE001 - no model folders configured
        return []
    full = [n for n in names if "decoder" not in n.lower()]
    rest = [n for n in names if n not in full]
    out: list[tuple[str, str]] = []
    for name in [*full, *rest]:
        path = folder_paths.get_full_path("vae_approx", name)
        if path:
            out.append((name, path))
    return out


def _build_tiny_vae(path: str) -> Any:
    """Load a ``taehv`` checkpoint for H3's 24-channel latent.

    Two things core cannot do and this does: size the model from the checkpoint (H3's patch
    size is not the one core infers from 24 latent channels) and accept a decoder-only file
    (``taeh3_decoder.safetensors`` ships without the encoder, so the encoder can simply be
    dropped rather than demanded).
    """
    import comfy.utils
    import torch
    from comfy.taesd.taehv import TAEHV, conv

    state = comfy.utils.load_torch_file(path, safe_load=True)
    if "decoder.1.weight" not in state:
        raise ValueError(f"{path} is not a taehv checkpoint")

    latent_channels = int(state["decoder.1.weight"].shape[1])
    patch_size = max(1, int(round((state["decoder.22.bias"].shape[0] / 3) ** 0.5)))
    model = TAEHV(latent_channels=latent_channels)
    if model.patch_size != patch_size:
        model.patch_size = patch_size
        model.encoder[0] = conv(3 * patch_size ** 2, model.encoder[0].out_channels)
        model.decoder[-1] = conv(model.decoder[-1].in_channels, 3 * patch_size ** 2)
    model.load_state_dict(state, strict=False)
    if "encoder.0.weight" not in state:
        del model.encoder  # decode only: keep the (missing) encoder off the CPU entirely
    return model.to(device=torch.device("cpu"), dtype=torch.float32).eval()


def build_frame_source(latent_format: Any, *, prefer_tiny_vae: bool = True) -> Any:
    """The best decoder available: the tiny VAE when it loads, else latent2rgb, else None.

    The tiny VAE decodes any H3 latent on its own, so it is chosen even without a latent
    format; latent2rgb needs the format's RGB factors.
    """
    if latent_preview is None:
        return None
    if prefer_tiny_vae:
        for label, path in _tiny_vae_candidates():
            try:
                return _TinyVaeSource(_build_tiny_vae(path), label)
            except Exception as exc:  # noqa: BLE001 - fall through to the next candidate
                log.debug("Character sheet preview: %s unusable (%s)", label, exc)
    factors = getattr(latent_format, "latent_rgb_factors", None) if latent_format is not None else None
    if factors is not None:
        try:
            return _Latent2RgbSource(latent_format)
        except Exception as exc:  # noqa: BLE001
            log.debug("Character sheet preview: latent2rgb unavailable (%s)", exc)
    return None


# --------------------------------------------------------------------------- #
# sending
# --------------------------------------------------------------------------- #
def default_sender(payload: dict[str, Any]) -> None:
    """Broadcast to every connected client (``sid=None``), so any tab with the panel sees it."""
    from server import PromptServer  # imported here: the module is imported by tests too

    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return
    instance.send_sync(EVENT, payload, None)


def encode_payload(image: Any, info: dict[str, Any]) -> dict[str, Any]:
    """JPEG-encode a frame and wrap it as the websocket payload."""
    frame = image.convert("RGB")
    if frame.width > MAX_WIDTH:
        frame = frame.resize((MAX_WIDTH, max(1, round(frame.height * MAX_WIDTH / frame.width))))
    buffer = io.BytesIO()
    frame.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return {
        **info,
        "image": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "width": frame.width,
        "height": frame.height,
    }


class _Worker(threading.Thread):
    """Decodes queued latents off the sampler's thread, dropping what it cannot keep up with."""

    def __init__(self, source: Any, sender: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(name="h3-sheet-preview", daemon=True)
        self.source = source
        self.sender = sender
        self.queue: queue.Queue = queue.Queue(QUEUE_SIZE)
        self.failures = 0

    def submit(self, latent: Any, info: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait((latent, info))
        except queue.Full:
            pass  # the panel has a fresher frame on the way

    def run(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            latent, info = item
            try:
                image = self.source.frame(latent)
                if image is not None:
                    self.sender(encode_payload(image, info))
            except Exception as exc:  # noqa: BLE001 - a preview never fails a render
                self.failures += 1
                if self.failures == 1:
                    log.warning("Character sheet preview: decoding failed (%s); "
                                "falling back to latent2rgb", exc)


# --------------------------------------------------------------------------- #
# the wrapper
# --------------------------------------------------------------------------- #
class _SheetPreviewWrapper:
    """OUTER_SAMPLE wrapper: mute ComfyUI's preview, stream ours, forward the callback.

    It changes exactly two things about the sampling call - the previewer classes are swapped
    for the duration (see ``preview_silence``) and the callback is wrapped so a frame can be
    taken from each step - and passes the sampler's own callback through untouched, which is
    what keeps the progress bar and ComfyUI's progress reporting working.
    """

    def __init__(
        self,
        *,
        name: str = "",
        node_id: Any = None,
        cells_total: int = 0,
        mute: bool = True,
        stream: bool = True,
        sender: Callable[[dict[str, Any]], None] | None = None,
        latent_format: Any = None,
        interval: float = MIN_INTERVAL,
        source: Any = None,
    ) -> None:
        self.name = name
        self.node_id = node_id
        self.cells_total = int(cells_total or 0)
        self.mute = bool(mute)
        self.stream = bool(stream)
        self.interval = float(interval)
        self.sender = sender or default_sender
        self.latent_format = latent_format
        self._source = source
        self._worker: _Worker | None = None
        self._broken = False
        self._first_step = True
        self._no_frame = False
        self._latent_shapes: Any = None
        self._cell = 0
        self._sent = 0
        self._last = 0.0

    # -- preview state (read by the run report and by tests) ------------------ #
    @property
    def source_name(self) -> str:
        source = self._source
        return getattr(source, "name", "none") if source is not None else "unbuilt"

    @property
    def sent(self) -> int:
        return self._sent

    # -- the OUTER_SAMPLE contract ------------------------------------------- #
    def __call__(
        self,
        executor: Any,
        noise: Any,
        latent_image: Any,
        sampler: Any,
        sigmas: Any,
        denoise_mask: Any,
        callback: Any,
        disable_pbar: Any,
        seed: Any,
        latent_shapes: Any = None,
    ) -> Any:
        # The sampler works on the flat packed latent, and this is the packing it recorded:
        # frames are read out of it with `unpack_latents` (see video_latent_from_pack).
        self._latent_shapes = latent_shapes
        patched: list[tuple[type, Any]] = []
        inner = self._wrap_callback(callback) if self.stream else callback
        try:
            if self.mute:
                for cls in previewer_classes():
                    if "decode_latent_to_preview_image" in cls.__dict__:
                        patched.append((cls, cls.__dict__["decode_latent_to_preview_image"]))
                        cls.decode_latent_to_preview_image = _no_preview
            return executor(
                noise, latent_image, sampler, sigmas, denoise_mask, inner, disable_pbar, seed,
                latent_shapes=latent_shapes,
            )
        finally:
            for cls, previous in patched:
                cls.decode_latent_to_preview_image = previous

    def _wrap_callback(self, callback: Any) -> Any:
        def stepped(step: Any, x0: Any, x: Any, total_steps: Any) -> Any:
            try:
                self._on_step(step, x0, total_steps)
            except Exception as exc:  # noqa: BLE001 - never fail the render over a preview
                self._broken = True
                log.warning("Character sheet preview: disabled for this run (%s)", exc)
            if callback is not None:
                return callback(step, x0, x, total_steps)
            return None

        return stepped

    def _on_step(self, step: Any, x0: Any, total_steps: Any) -> None:
        if self._broken:
            return
        try:
            step_index = int(step)
            total = int(total_steps)
        except (TypeError, ValueError):
            return
        if self._first_step:
            # One line per render, and the one that answers "why is the panel blank?".
            self._first_step = False
            log.info("Character sheet preview: step %s/%s, latent %s",
                     step_index + 1, total, describe_latent(x0))
        if step_index == 0:
            # One sampler call per cell, and every call starts at step 0: that is the cell
            # boundary, without the wrapper needing to know anything about the sheet's plan.
            self._cell += 1
            self._last = 0.0
        now = time.monotonic()
        last_step = step_index + 1 >= total
        if self._last and (now - self._last) < self.interval and not last_step:
            return
        self._last = now
        self._emit(step_index, x0, total)

    def _emit(self, step_index: int, x0: Any, total: int) -> None:
        latent = video_latent(x0)
        if latent is None:
            latent = video_latent_from_pack(x0, self._latent_shapes)
        if latent is None:
            if not self._no_frame:
                self._no_frame = True
                log.info("Character sheet preview: no frame in %s; streaming off", describe_latent(x0))
                self._broken = True
            return
        # One frame, on the host, detached: the worker must not touch a live sampler tensor.
        frame = latent[:, :, :1].detach().to("cpu", copy=True)
        info = {
            "node_id": self.node_id,
            "name": self.name,
            "cell": self._cell,
            "cells": self.cells_total,
            "step": step_index + 1,
            "steps": total,
        }
        source = self._source
        if source is None:
            self._source = source = build_frame_source(self.latent_format)
            if source is None:
                self._broken = True
                log.info("Character sheet preview: no decoder available; streaming off")
                return
            log.info("Character sheet preview: decoding with %s", source.name)
        if getattr(source, "name", "") == "taeh3":
            # The tiny VAE is ~130ms a frame: decode it off this thread.
            if self._worker is None:
                self._worker = _Worker(source, self._send)
                self._worker.start()
            self._worker.submit(frame, info)
            return
        image = source.frame(frame)
        if image is not None:
            self._send(encode_payload(image, info))

    def _send(self, payload: dict[str, Any]) -> None:
        self._sent += 1
        try:
            self.sender(payload)
        except Exception as exc:  # noqa: BLE001 - a dead websocket is not a render failure
            log.debug("Character sheet preview: send failed (%s)", exc)


def _already_attached(model: Any) -> bool:
    if comfy is None:
        return False
    try:
        return bool(model.get_wrappers(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, STREAM_KEY))
    except Exception:  # noqa: BLE001 - any patcher that does not answer means "no"
        return False


def attach_sheet_preview(
    model: Any,
    *,
    mute: bool = True,
    stream: bool = True,
    name: str = "",
    cells_total: int = 0,
    node_id: Any = None,
    sender: Callable[[dict[str, Any]], None] | None = None,
    source: Any = None,
) -> Any:
    """Return the model with the sheet-preview wrapper attached (or the model unchanged).

    Best effort, like the mute: a patcher that refuses to clone logs a warning and the render
    proceeds with whatever previews ComfyUI would have shown.
    """
    if comfy is None or model is None or not (mute or stream):
        return model
    if _already_attached(model):
        return model
    latent_format = getattr(getattr(model, "model", None), "latent_format", None)
    wrapper = _SheetPreviewWrapper(
        name=name, node_id=node_id, cells_total=cells_total, mute=mute, stream=stream,
        sender=sender, latent_format=latent_format, source=source,
    )
    try:
        wrapped = model.clone()
        wrapped.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, STREAM_KEY, wrapper,
        )
        return wrapped
    except Exception as exc:  # noqa: BLE001 - never fail a render over a preview
        log.warning(
            "Character sheet: could not attach the live preview (%s); "
            "ComfyUI's own preview behaviour is unchanged.",
            exc,
        )
        return model


__all__ = [
    "EVENT",
    "STREAM_KEY",
    "attach_sheet_preview",
    "build_frame_source",
    "encode_payload",
    "video_latent",
]
