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

It sends a **clip, not a still**, because a still of a video render says almost nothing: the
frames loop in the panel (the browser is told the fps), so the strip plays the cell that is being
denosed. How many frames that is depends on what the box can afford, and it is *measured*: the
first preview decodes a single latent token, and every one after that spends a CPU budget
(:data:`FRAME_BUDGET_SECONDS`) at the rate that token established - 6 latent tokens for a 288x512
cell is the whole 22-frame clip (780ms), while a 1536px cell gets one token and a still. TAEHV
chains its temporal blocks forward, so a clip is always a prefix of the render - which is the right
end of a cell to preview anyway (its start is what continuity hands to the next cell).

When the tiny VAE is not installed (or will not build), the preview falls back to ComfyUI's own
latent2rgb factors: 3ms a frame, no model, no thread - blurrier, but never absent and never
expensive, and it loops too.

Note on the wire format: the frames go as a list of JPEG data URLs and the panel cycles them. An
animated image would be one payload instead of N, but Pillow here reports ``webp: True,
webp_anim: False`` - it cannot write one - and a GIF would cost 256 colours and often more bytes
than the JPEGs. Cycling N small JPEGs is the version that works everywhere.

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
#: JPEG quality for the streamed frames.
JPEG_QUALITY = 78
#: Widest the frames are sent at (a 1536px cell decodes to 1536px wide, which is 300 KB a frame
#: and pointless in a 620px node).
MAX_WIDTH = 512
#: Most frames one clip may carry, however cheap the decode turns out to be: the payload is a
#: list of JPEGs, and the panel is 620px wide.
MAX_CLIP_FRAMES = 24
#: How much CPU time one preview may spend decoding (see the module docstring). 1.5s measured on
#: a 288x512 cell buys the whole 22-frame clip (780ms); a bigger cell buys fewer frames.
FRAME_BUDGET_SECONDS = 1.5
#: A clip should show motion even when one latent token turns out to be expensive, so this many are
#: attempted regardless - and if three of them would cost more than MAX_CLIP_MS, a still is the
#: honest answer instead of a slow loop.
MIN_CLIP_TOKENS = 3
MAX_CLIP_MS = 5000.0
#: Frames the worker may have waiting. Two: one being decoded, one ahead. Older ones are
#: dropped - a preview of a step that already passed helps nobody.
QUEUE_SIZE = 2
#: Default playback rate for a loop, in frames per second. The cell is 24fps, but a preview
#: loop of a few frames reads better a little slower.
DEFAULT_FPS = 12.0
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
def strided(frames: list[Any], limit: int) -> list[Any]:
    """At most ``limit`` frames, evenly spread over the clip (both ends kept)."""
    if limit <= 0 or len(frames) <= limit:
        return frames
    if limit == 1:
        return [frames[0]]
    return [frames[round(i * (len(frames) - 1) / (limit - 1))] for i in range(limit)]


class _Latent2RgbSource:
    """ComfyUI's own cheap preview math: the latent projected onto RGB factors.

    3ms a frame, so the budget is irrelevant here: this decodes the whole prefix it is asked for.
    """

    name = "latent2rgb"

    def __init__(self, latent_format: Any) -> None:
        self.previewer = latent_preview.Latent2RGBPreviewer(
            latent_format.latent_rgb_factors,
            getattr(latent_format, "latent_rgb_factors_bias", None),
            getattr(latent_format, "latent_rgb_factors_reshape", None),
        )

    def clip(self, latent: Any, *, tokens: int, max_frames: int, budget: float) -> tuple[list[Any], int, float]:
        frames = []
        for index in range(max(1, tokens)):
            image = self.previewer.decode_latent_to_preview(latent[:, :, index:index + 1])
            if image is not None:
                frames.append(image)
        return strided(frames, max_frames), max(1, tokens), 0.0


class _TinyVaeSource:
    """The ``taeh3`` tiny VAE, on the CPU in float32 (see the module docstring).

    One ``clip`` call decodes a **prefix** of the latent's tokens: TAEHV's temporal blocks chain
    forward, so a later token cannot be decoded without the ones before it (KJNodes' decoder
    documents the same). The prefix is also the useful end of a cell to look at.
    """

    name = "taeh3"

    def __init__(self, model: Any, label: str) -> None:
        self.model = model
        self.label = label

    def clip(self, latent: Any, *, tokens: int, max_frames: int, budget: float) -> tuple[list[Any], int, float]:
        import time

        import torch

        total = int(latent.shape[2])
        used = max(1, min(total, int(tokens)))
        started = time.perf_counter()
        with torch.no_grad():
            decoded = self.model.decode(latent[:, :, :used].to(dtype=torch.float32))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        frames = [latent_preview.preview_to_image(decoded[0, :, i].movedim(0, -1), do_scale=False)
                  for i in range(int(decoded.shape[2]))]
        # Measured, not guessed: how long one latent token takes on this box, for this cell size.
        return strided(frames, max_frames), used, elapsed_ms / used

    def tokens_for(self, rate_ms: float, total: int, *, budget_ms: float = FRAME_BUDGET_SECONDS * 1000,
                   min_tokens: int = MIN_CLIP_TOKENS, cap_ms: float = MAX_CLIP_MS) -> int:
        """How long a clip to decode at the measured rate.

        Three answers, in order of preference: everything the budget affords; at least
        ``min_tokens`` so the panel gets a loop rather than a still; or one token when even that
        would be too expensive on this cell.
        """
        if rate_ms <= 0:
            return 1
        tokens = max(int(min_tokens), int(budget_ms / rate_ms))
        if tokens * rate_ms > cap_ms:
            return 1
        return max(1, min(int(total), tokens))


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


def encode_frame(image: Any) -> tuple[str, int, int]:
    """One frame as a JPEG data URL the panel can put straight on an ``<img>``."""
    frame = image.convert("RGB")
    if frame.width > MAX_WIDTH:
        frame = frame.resize((MAX_WIDTH, max(1, round(frame.height * MAX_WIDTH / frame.width))))
    buffer = io.BytesIO()
    frame.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return ("data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
            frame.width, frame.height)


def encode_payload(frames: Any, info: dict[str, Any], *, fps: float = DEFAULT_FPS,
                   tokens: int = 0, decode_ms: float = 0.0) -> dict[str, Any]:
    """Encode a clip and wrap it as the websocket payload.

    ``frames`` is a list (or a single image, for callers that have one). The panel cycles the
    list at ``fps``; a list of one is simply a still.
    """
    if not isinstance(frames, (list, tuple)):
        frames = [frames]
    encoded: list[str] = []
    width = height = 0
    for image in frames:
        if image is None:
            continue
        data_url, width, height = encode_frame(image)
        encoded.append(data_url)
    if not encoded:
        raise ValueError("nothing to send")
    return {
        **info,
        "image": encoded[0],          # the first frame: what a panel that ignores `frames` shows
        "frames": encoded,
        "frame_count": len(encoded),
        "fps": float(fps),
        "tokens": int(tokens),
        "decode_ms": round(float(decode_ms), 1),
        "width": width,
        "height": height,
    }


class _Worker(threading.Thread):
    """Decodes queued latents off the sampler's thread, dropping what it cannot keep up with."""

    def __init__(self, source: Any, sender: Callable[[dict[str, Any]], None],
                 plan: Callable[[], tuple[int, int, float]]) -> None:
        super().__init__(name="h3-sheet-preview", daemon=True)
        self.source = source
        self.sender = sender
        #: Asks the wrapper how many latent tokens to decode right now, and how many frames may
        #: be sent, and at what fps - it owns the measured rate and the payload switches.
        self.plan = plan
        self.queue: queue.Queue = queue.Queue(QUEUE_SIZE)
        self.failures = 0
        self.learned_ms = 0.0
        self.reported = False

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
                tokens, max_frames, fps = self.plan()
                if self.learned_ms > 0 and hasattr(self.source, "tokens_for"):
                    tokens = self.source.tokens_for(self.learned_ms, int(latent.shape[2]))
                frames, used, per_token_ms = self.source.clip(
                    latent, tokens=tokens, max_frames=max_frames, budget=FRAME_BUDGET_SECONDS,
                )
                if per_token_ms:
                    # Keep the FASTEST rate seen, not an average: a sample that ran while the CPU
                    # was busy with the render must not make the next preview smaller, and the
                    # queue drops anything the worker cannot keep up with anyway.
                    self.learned_ms = (per_token_ms if self.learned_ms <= 0
                                       else min(self.learned_ms, per_token_ms))
                if frames:
                    if not self.reported:
                        # One line per render, and the answer to "why is the loop so short?".
                        self.reported = True
                        log.info(
                            "Character sheet preview: %s ms per latent frame -> %s frames "
                            "from %s of %s latent frame(s) (%s fps)",
                            round(per_token_ms or 0), len(frames), used, int(latent.shape[2]), fps,
                        )
                    self.sender(encode_payload(frames, info, fps=fps, tokens=used,
                                               decode_ms=per_token_ms * max(1, used)))
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
        max_frames: int = MAX_CLIP_FRAMES,
        fps: float = DEFAULT_FPS,
        budget: float = FRAME_BUDGET_SECONDS,
        cell_ids: list[str] | None = None,
        whole_sheet: bool = False,
    ) -> None:
        self.name = name
        self.node_id = node_id
        self.cells_total = int(cells_total or 0)
        self.whole_sheet = bool(whole_sheet)
        self.mute = bool(mute)
        self.stream = bool(stream)
        self.interval = float(interval)
        self.sender = sender or default_sender
        self.latent_format = latent_format
        #: A clip is at most this many frames, played at ``fps``; the decode budget buys as many
        #: as this box can pay for (see the module docstring).
        self.max_frames = max(1, int(max_frames))
        self.fps = float(fps) or DEFAULT_FPS
        self.budget = float(budget)
        #: The sheet's cells in render order, so every clip can say WHICH cell it is - the
        #: panel's retry button needs the id, not a guess from an index.
        self.cell_ids = [str(value) for value in (cell_ids or [])]
        self._source = source
        self._worker: _Worker | None = None
        self._broken = False
        self._first_step = True
        self._no_frame = False
        self._latent_shapes: Any = None
        self._cell = 0
        self._sent = 0
        self._frames_sent = 0
        self._last = 0.0

    # -- preview state (read by the run report and by tests) ------------------ #
    @property
    def source_name(self) -> str:
        source = self._source
        return getattr(source, "name", "none") if source is not None else "unbuilt"

    @property
    def sent(self) -> int:
        return self._sent

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    @property
    def decode_ms(self) -> float:
        """The measured cost of one latent token on this box, for this cell size (0 = unmeasured)."""
        return self._worker.learned_ms if self._worker else 0.0

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
        # The whole latent prefix goes to the worker (a few hundred KB): how much of it becomes
        # frames is decided there, from the budget and the rate this box measured.
        clip = latent.detach().to("cpu", copy=True)
        info = {
            "node_id": self.node_id,
            "name": self.name,
            "cell": self._cell,
            "cells": self.cells_total,
            # True when this one clip is the whole sheet (the draft pass): the panel says so
            # instead of "cell 1", and there is no per-cell re-roll to offer.
            "whole_sheet": self.whole_sheet,
            "cell_id": self.cell_id_of(self._cell),
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
        if source.name == "taeh3":
            # ~130ms per latent token at 288x512: decode it off this thread.
            if self._worker is None:
                self._worker = _Worker(source, self._send, self._plan)
                self._worker.start()
            self._worker.submit(clip, info)
            return
        frames, used, _ = source.clip(clip, tokens=int(clip.shape[2]),
                                      max_frames=self.max_frames, budget=self.budget)
        if frames:
            self._send(encode_payload(frames, info, fps=self.fps, tokens=used))

    def _plan(self) -> tuple[int, int, float]:
        """What the worker should aim for right now: tokens, frames, fps."""
        return 1, self.max_frames, self.fps

    def cell_id_of(self, cell: int) -> str:
        """The id of cell ``cell`` (1-based), when the render told us the order."""
        index = int(cell) - 1
        if 0 <= index < len(self.cell_ids):
            return self.cell_ids[index]
        return ""

    def _send(self, payload: dict[str, Any]) -> None:
        self._sent += 1
        self._frames_sent += int(payload.get("frame_count") or 1)
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
    max_frames: int = MAX_CLIP_FRAMES,
    fps: float = DEFAULT_FPS,
    budget: float = FRAME_BUDGET_SECONDS,
    cell_ids: list[str] | None = None,
    whole_sheet: bool = False,
) -> Any:
    """Return the model with the sheet-preview wrapper attached (or the model unchanged).

    Best effort, like the mute: a patcher that refuses to clone logs a warning and the render
    proceeds with whatever previews ComfyUI would have shown.

    ``whole_sheet`` marks a render whose single clip IS the sheet (the one-pass sheet, see
    ``one_pass``): one sampler call, nothing to re-roll per cell, so the panel labels the stream
    as the sheet rather than as "cell 1".
    """
    if comfy is None or model is None or not (mute or stream):
        return model
    if _already_attached(model):
        return model
    latent_format = getattr(getattr(model, "model", None), "latent_format", None)
    wrapper = _SheetPreviewWrapper(
        name=name, node_id=node_id, cells_total=cells_total, mute=mute, stream=stream,
        sender=sender, latent_format=latent_format, source=source, max_frames=max_frames,
        fps=fps, budget=budget, cell_ids=cell_ids, whole_sheet=whole_sheet,
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
    "encode_frame",
    "encode_payload",
    "strided",
    "video_latent",
    "video_latent_from_pack",
]
