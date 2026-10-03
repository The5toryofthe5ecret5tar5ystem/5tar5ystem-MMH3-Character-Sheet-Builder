# ComfyUI-H3-Character-Sheet - turn ComfyUI's own preview off for sheet renders.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""No built-in preview for a sheet render.

ComfyUI's own preview is produced by the **sampler**, not by the pack: when a custom
sampler is given no callback, ``comfy.samplers.sample_custom`` builds one with
``latent_preview.prepare_callback``, every step decodes the latent with a small previewer
(TAESD/tiny VAE, or latent2rgb) and the frontend paints it in the node's preview area -
and then keeps replacing it with the finished images. This pack shows the sheet in its own
panel instead, so that stream buys nothing and is the reason the node has a preview area to
fight over in the first place (see the README's "Node previews" section).

The lever is the same one KJNodes' ``ModelPreviewOverrideKJ`` uses for its
``suppress_default_preview``: wrap the model with an ``OUTER_SAMPLE`` wrapper and, for the
duration of the sampling call, replace every concrete ``decode_latent_to_preview_image``
with a function that returns ``None``. The previewer classes have to be patched as CLASSES
(that is the only handle the callback holds) and are restored in a ``finally``, so a render
that raises leaves the core exactly as it was.

What this deliberately does NOT do is stream a live per-step preview of our own. Decoding
H3's packed video+audio latent into a frame is the hard part of that feature (the KJ node
carries a whole H3/LTX-specific unpack for it, ``_normalize_packed_x0``), and the panel
already shows progress per cell: the cell sink writes each cell's frames as it finishes and
the wiring polls the sheet folder while a run is live.
"""

from __future__ import annotations

import logging
from typing import Any

try:  # ComfyUI is always present at runtime; the import is soft so the module tests alone.
    import comfy.patcher_extension
    import latent_preview
except Exception:  # noqa: BLE001 - a unit test without ComfyUI on the path
    comfy = None  # type: ignore[assignment]
    latent_preview = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

#: The wrapper key. One key, not one per cell: the wrapper is on the MODEL, and every cell of
#: a sheet samples through the same model.
SILENCE_KEY = "h3_sheet_silence_preview"


def _no_preview(self_: Any, preview_format: Any, x0: Any) -> None:
    """Stand-in for ``decode_latent_to_preview_image``: decode nothing, send nothing."""
    return None


def previewer_classes() -> list[type]:
    """``LatentPreviewer`` and every subclass, recursively (VHS and friends add their own)."""
    if latent_preview is None:
        return []
    root = getattr(latent_preview, "LatentPreviewer", None)
    if root is None:
        return []
    found: list[type] = [root]
    stack = list(root.__subclasses__())
    while stack:
        cls = stack.pop()
        found.append(cls)
        stack.extend(cls.__subclasses__())
    return found


class _SilenceBuiltInPreview:
    """The OUTER_SAMPLE wrapper: sample normally, with the built-in preview muted.

    It changes exactly one thing about the call - the previewer classes are swapped while
    ``executor`` runs - and forwards everything else untouched, including the callback the
    sampler was given (which is what drives the progress bar, not only the preview).
    """

    def __init__(self, node_id: Any = None) -> None:
        self.node_id = node_id
        self.silenced: list[str] = []

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
        patched: list[tuple[type, Any]] = []
        try:
            for cls in previewer_classes():
                if "decode_latent_to_preview_image" in cls.__dict__:
                    patched.append((cls, cls.__dict__["decode_latent_to_preview_image"]))
                    cls.decode_latent_to_preview_image = _no_preview
            self.silenced = [cls.__name__ for cls, _ in patched]
            return executor(
                noise, latent_image, sampler, sigmas, denoise_mask, callback,
                disable_pbar, seed, latent_shapes=latent_shapes,
            )
        finally:
            for cls, previous in patched:
                cls.decode_latent_to_preview_image = previous


def is_silenced(model: Any) -> bool:
    """Whether this model already carries the wrapper (used by tests and the run report)."""
    if comfy is None or model is None:
        return False
    try:
        wrappers = model.get_wrappers(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, SILENCE_KEY)
    except Exception:  # noqa: BLE001 - any patcher that does not answer means "no"
        return False
    return bool(wrappers)


def silence_model_previews(model: Any, *, node_id: Any = None) -> Any:
    """Return the model with the built-in preview muted, or the model itself if it cannot be.

    Best effort on purpose: a preview is a convenience, and nothing about a sheet render
    should fail because a patcher refused to clone. The caller gets the original object back
    in that case and the render proceeds with ComfyUI's usual preview.
    """
    if comfy is None or model is None:
        return model
    if is_silenced(model):
        return model
    try:
        wrapped = model.clone()
        wrapped.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
            SILENCE_KEY,
            _SilenceBuiltInPreview(node_id),
        )
        return wrapped
    except Exception as exc:  # noqa: BLE001 - never fail a render over a preview
        log.warning(
            "Character sheet: could not mute ComfyUI's own preview (%s); "
            "the node will show its usual preview stream.",
            exc,
        )
        return model


__all__ = ["SILENCE_KEY", "is_silenced", "previewer_classes", "silence_model_previews"]
