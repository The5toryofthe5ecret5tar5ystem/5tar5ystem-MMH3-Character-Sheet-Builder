# ComfyUI-H3-Character-Sheet - automatic face blur for reference pictures.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Blur the face out of a reference picture before the model ever sees it.

Why this exists
---------------
MiniMax H3 conditions on every reference at once and has **no per-reference weight**.
A prompt can therefore *ask* for "identity from ``<Picture 1>``, clothing from
``<Picture 2>``", but it cannot stop the model reading a face that is present in the
pixels - and a full-body outfit photo is a whole second person, so it is a whole second
identity. The prompt side (see :mod:`sheet_spec`) names the failure outright; this
module removes it, which is the only version that cannot be argued with.

What it does
------------
* Detects faces with the YOLO face model that already ships with this ComfyUI install
  (``models/ultralytics/bbox/face_yolov8m.pt`` - no download, and it is the same model
  Impact Pack's detectors use).
* Blurs a region anchored on each face, expanded to cover the hair and jaw, with a soft
  elliptical edge so it reads as a blur and not as a pasted rectangle.
* Writes the result next to the originals (``input/h3_character_sheet/derived/``) and
  returns the path, caching by source mtime + settings so a re-render never re-runs
  detection. The original file is never modified.

The node rewrites the reference plan with the derived path (see
``nodes/sheet.py``), and the panel can preview it with the ``blur`` route action.

Failure policy: this is hygiene, not a requirement. A missing model, an unreadable
image or a detector error leaves the original reference in place and returns a warning -
a sheet must never fail to render because a convenience step did not work. Nothing here
raises into the render.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger("ComfyUI-H3-Character-Sheet.face-blur")

#: Where the derived copies live, relative to the ComfyUI input folder. Reference files
#: are stored the same way (``h3_character_sheet/<file>``), so a derived path is valid
#: as a ``LoadImage`` value too.
DERIVED_SUBDIR = ("h3_character_sheet", "derived")

#: The face model, tried in order. The first two are this install's own copies (the
#: nested one first, which is where the Impact Pack example puts it); the rest are the
#: layout model-manager uses for a fresh install.
MODEL_CANDIDATES = (
    ("ultralytics", "bbox", "face_yolov8m.pt"),
    ("ultralytics", "face_yolov8m.pt"),
)

#: Detection confidence. 0.25 is ultralytics' default; every real reference photo in
#: testing scored above 0.87, so this is not a tuning knob worth exposing.
CONF = 0.25

#: How far past the detected box the blur reaches. The detector box is tight on the
#: face, and hair, ears and jaw carry identity too, so the patch is grown sideways and
#: mostly upwards (a face box sits low in the head).
PAD_X = 1.6
PAD_Y = 1.9
PAD_UP = 0.62  # share of the grown height placed above the face centre

#: Gaussian sigma, scaled with the patch width so a small face is not under-blurred and
#: a large one is not turned into a smear: ``sigma = SIGMA * width / SIGMA_REF_WIDTH``.
SIGMA = 24.0
SIGMA_REF_WIDTH = 240.0

#: Share of the patch radius used for the soft edge (0.35 = the outer 35% ramps).
FEATHER = 0.35

#: Soft edge for a hand-painted area, as a fraction of the image's short edge (so the
#: stroke does not read as a cut-out patch at any resolution).
PAINT_FEATHER = 0.005

#: Brush radius used when a stroke carries none, as a fraction of the short edge.
#: Mirrors ``sheet_spec.DEFAULT_BRUSH_RADIUS`` (a test pins the two together).
PAINT_DEFAULT_RADIUS = 0.03

#: Every knob above that changes pixels, and therefore has to be part of the cache key.
SETTINGS: dict[str, float] = {
    "pad_x": PAD_X,
    "pad_y": PAD_Y,
    "pad_up": PAD_UP,
    "sigma": SIGMA,
    "feather": FEATHER,
    "conf": CONF,
}

#: The knobs ``blur_boxes`` accepts (``conf`` is detection, not pixels).
_BOX_KEYS = ("pad_x", "pad_y", "pad_up", "sigma", "feather")

#: Blur area presets, keyed by ``sheet_spec.BLUR_SCOPES``.
#:
#: The detector reports the face box and nothing else - there is no hair or headwear
#: model in this install - so "hair" and "head" are that same box grown by geometry:
#: sideways for the hair mass, and upwards past the crown so a bow, a hat, a hood or a
#: headband is covered too. Growing it is also what keeps the garment safe: the patch
#: stops at the neck instead of at the top of the dress.
SCOPE_SETTINGS: dict[str, dict[str, float]] = {
    "face": {"pad_x": 1.35, "pad_y": 1.50, "pad_up": 0.60},
    "hair": {"pad_x": PAD_X, "pad_y": PAD_Y, "pad_up": PAD_UP},
    "head": {"pad_x": 2.20, "pad_y": 2.80, "pad_up": 0.70},
}

#: The area used when nothing is said. Mirrors ``sheet_spec.DEFAULT_BLUR_SCOPE``.
DEFAULT_SCOPE = "hair"


def settings_for_scope(scope: Any = DEFAULT_SCOPE) -> dict[str, float]:
    """The pixel knobs for a blur area (unknown names get the default preset)."""
    name = str(scope or "").strip().lower()
    preset = SCOPE_SETTINGS.get(name, SCOPE_SETTINGS[DEFAULT_SCOPE])
    return {**SETTINGS, **preset}


def _box_kwargs(settings: dict[str, float] | None, scope: Any) -> dict[str, float]:
    """Only the knobs ``blur_boxes`` takes, from the given settings or the scope."""
    source = settings if settings else settings_for_scope(scope)
    return {key: float(value) for key, value in source.items() if key in _BOX_KEYS}

_detector_lock = threading.Lock()
_detector: Any = None
_detector_key: str | None = None


def input_root() -> Path | None:
    """ComfyUI's input folder, or ``None`` when core is not importable."""
    try:
        import folder_paths

        directory = folder_paths.get_input_directory()
    except Exception:  # noqa: BLE001 - standalone use / test stub
        return None
    return Path(directory) if directory else None


def model_path() -> Path | None:
    """The face detector on disk, or ``None`` when this install has none."""
    try:
        import folder_paths

        models = Path(folder_paths.models_dir)
    except Exception:  # noqa: BLE001 - standalone use / test stub
        return None
    for parts in MODEL_CANDIDATES:
        candidate = models.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def resolve_input_file(name: Any) -> Path | None:
    """A reference value (``h3_character_sheet/a.jpg``) as a file inside the input folder.

    ``LoadImage`` resolves its value the same way, so anything rejected here would not
    have loaded either. Traversal is refused: a reference may not point outside input.
    """
    root = input_root()
    if root is None:
        return None
    text = str(name or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        path = candidate
    else:
        path = root / candidate
    try:
        path = path.resolve()
        path.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def derived_path(source: Path, *, key: str, root: Path | None = None) -> Path:
    """Where the blurred copy of ``source`` lives for a given cache ``key``."""
    base = root if root is not None else input_root()
    if base is None:
        raise RuntimeError("ComfyUI's input folder is not available.")
    stem = source.stem[:80]
    return base.joinpath(*DERIVED_SUBDIR) / f"{stem}-blurface-{key}.png"


def cache_key(
    source: Path,
    *,
    settings: dict[str, float] | None = None,
    model: Path | None = None,
    paint: Sequence[dict[str, Any]] | None = None,
) -> str:
    """Short stable key: the source as it is *now* plus everything that changes pixels.

    mtime and size are in the key, so replacing a reference photo with a different file
    of the same name produces a new copy instead of serving the old blur - and so are the
    painted strokes, so repainting produces a new copy too.
    """
    try:
        stat = source.stat()
        stamp = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        stamp = "missing"
    payload = json.dumps(
        {
            "source": str(source),
            "stamp": stamp,
            "settings": dict(settings or SETTINGS),
            "model": str(model or ""),
            "paint": list(paint or []),
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def load_detector(path: Path | None = None) -> Any:
    """The YOLO model, loaded once per model file (imports ultralytics lazily)."""
    global _detector, _detector_key
    resolved = path or model_path()
    if resolved is None:
        return None
    key = str(resolved)
    with _detector_lock:
        if _detector is not None and _detector_key == key:
            return _detector
        from ultralytics import YOLO  # imported here: it pulls torch in

        _detector = YOLO(key)
        _detector_key = key
        log.info("Character sheet: face blur loaded %s", key)
        return _detector


def detect_faces(image: Any, *, conf: float = CONF, detector: Any = None) -> list[tuple[int, int, int, int]]:
    """Face boxes (``x1, y1, x2, y2``) in an OpenCV image, best first."""
    model = detector if detector is not None else load_detector()
    if model is None:
        return []
    result = model.predict(image, conf=float(conf), device="cpu", verbose=False)[0]
    boxes = []
    for box in result.boxes:
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0])
        boxes.append((int(x1), int(y1), int(x2), int(y2)))
    return boxes


def _ellipse_mask(height: int, width: int, *, feather: float = FEATHER) -> Any:
    """Soft elliptical mask: 1 in the middle, 0 at the edge, linear ramp in between."""
    import numpy as np

    ys = np.arange(height, dtype=np.float32)[:, None]
    xs = np.arange(width, dtype=np.float32)[None, :]
    nx = (xs - (width - 1) / 2.0) / max(1.0, (width - 1) / 2.0)
    ny = (ys - (height - 1) / 2.0) / max(1.0, (height - 1) / 2.0)
    radius = np.sqrt(nx * nx + ny * ny)
    inner = max(0.0, 1.0 - float(feather))
    ramp = np.clip((1.0 - radius) / max(1e-6, 1.0 - inner), 0.0, 1.0)
    return (ramp * ramp * (3.0 - 2.0 * ramp)).astype(np.float32)  # smoothstep


def _composite(image: Any, mask: Any, *, sigma: float) -> Any:
    """Blur ``image`` and blend it back through a per-pixel ``mask`` (0-1, HxW or HxWx1)."""
    import cv2
    import numpy as np

    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.ndim == 3:
        alpha = alpha[..., 0]
    blurred = cv2.GaussianBlur(np.asarray(image), (0, 0), max(1.0, float(sigma)))
    weight = alpha[..., None]
    return np.clip(
        blurred.astype(np.float32) * weight
        + np.asarray(image).astype(np.float32) * (1.0 - weight),
        0,
        255,
    ).astype(np.asarray(image).dtype)


def paint_mask(shape: Sequence[int], strokes: Sequence[dict[str, Any]]) -> Any:
    """Rasterize hand-painted strokes into a 0-1 mask (pure - no model, no disk).

    ``shape`` is ``(height, width)``. A stroke's points come in normalized 0-1 and its
    ``radius`` is a fraction of the image's SHORT edge, so a brush is round whatever the
    aspect ratio and the same painting works at any resolution - which is why strokes are
    stored as vectors rather than as a baked image.

    ``brush`` is a freehand line of that radius with round caps (a single point is a dot);
    ``lasso`` is a closed outline filled in, for covering a large area in one gesture.
    """
    import cv2
    import numpy as np

    height, width = int(shape[0]), int(shape[1])
    mask = np.zeros((height, width), dtype=np.uint8)
    if height < 1 or width < 1:
        return mask.astype(np.float32)
    scale = min(width, height)
    for stroke in strokes or []:
        points = [
            (int(round(float(x) * width)), int(round(float(y) * height)))
            for x, y in (list(point)[:2] for point in (stroke.get("points") or []))
        ]
        if not points:
            continue
        radius = max(1, int(round(float(stroke.get("radius") or PAINT_DEFAULT_RADIUS) * scale)))
        if str(stroke.get("tool") or "brush").lower() == "lasso":
            # A lasso needs an outline to fill: two points are a slip, not an area.
            # (The payload parser drops these too - one rule, no surprises.)
            if len(points) < 3:
                continue
            cv2.fillPoly(mask, [np.asarray(points, dtype=np.int32)], 255, lineType=cv2.LINE_8)
            continue
        thickness = max(2, radius * 2)
        if len(points) == 1:
            cv2.circle(mask, points[0], radius, 255, thickness=-1, lineType=cv2.LINE_8)
            continue
        cv2.polylines(mask, [np.asarray(points, dtype=np.int32)], False, 255,
                      thickness=thickness, lineType=cv2.LINE_8)
        # Round caps: polylines stop square at the ends, which leaves corners on a stroke.
        for point in (points[0], points[-1]):
            cv2.circle(mask, point, radius, 255, thickness=-1, lineType=cv2.LINE_8)
    return (mask.astype(np.float32) / 255.0)


def feather_mask(mask: Any, *, sigma: float = 0.0) -> Any:
    """Soften a hard mask edge, so a painted blur does not read as a cut-out patch.

    ``sigma`` is in pixels; 0 leaves the mask hard.
    """
    import cv2
    import numpy as np

    alpha = np.asarray(mask, dtype=np.float32)
    strength = max(0.0, float(sigma))
    if strength <= 0:
        return alpha
    return np.clip(cv2.GaussianBlur(alpha, (0, 0), strength), 0.0, 1.0)


def blur_painted(
    image: Any,
    strokes: Sequence[dict[str, Any]],
    *,
    sigma: float = SIGMA,
    feather: float = PAINT_FEATHER,
) -> Any:
    """Blur exactly the painted areas of an image (the "instead of" path)."""
    import numpy as np

    out = np.asarray(image).copy()
    if out.ndim != 3:
        return out
    short_edge = min(out.shape[0], out.shape[1])
    mask = feather_mask(
        paint_mask(out.shape[:2], strokes), sigma=max(2.0, float(feather) * short_edge)
    )
    if float(mask.max() or 0.0) <= 0.0:
        return out
    strength = max(6.0, float(sigma) * short_edge / SIGMA_REF_WIDTH)
    return _composite(out, mask, sigma=strength)


def blur_boxes(
    image: Any,
    boxes: Sequence[Sequence[float]],
    *,
    pad_x: float = PAD_X,
    pad_y: float = PAD_Y,
    pad_up: float = PAD_UP,
    sigma: float = SIGMA,
    feather: float = FEATHER,
) -> Any:
    """Blur every box in ``boxes`` (pure image maths - no model, no disk, testable).

    Each box is grown sideways and mostly upwards (hair above a face box is outside it),
    clipped to the image, blurred with a sigma proportional to the patch width, and
    composited through the soft ellipse so the edge does not read as a rectangle.
    """
    import numpy as np

    out = np.asarray(image).copy()
    if out.ndim != 3:
        return out
    height, width = out.shape[:2]
    for raw in boxes:
        x1, y1, x2, y2 = (float(value) for value in list(raw)[:4])
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        patch_w = max(4.0, (x2 - x1) * float(pad_x))
        patch_h = max(4.0, (y2 - y1) * float(pad_y))
        # The patch is placed first, then clipped: the difference between the two is
        # what tells the mask which of its edges are the image border.
        want_left = int(round(cx - patch_w / 2.0))
        want_right = int(round(cx + patch_w / 2.0))
        want_top = int(round(cy - patch_h * float(pad_up)))
        want_bottom = int(round(cy + patch_h * (1.0 - float(pad_up))))
        left, right = max(0, want_left), min(width, want_right)
        top, bottom = max(0, want_top), min(height, want_bottom)
        if right - left < 4 or bottom - top < 4:
            continue
        # The mask is built for the WHOLE patch and only then cropped, so a patch that
        # runs off the frame is not feathered against the image border: hair that
        # reaches the top of the photo is blurred all the way to the edge.
        mask = _ellipse_mask(
            want_bottom - want_top, want_right - want_left, feather=float(feather)
        )[
            top - want_top:bottom - want_top, left - want_left:right - want_left
        ]
        strength = max(3.0, float(sigma) * (want_right - want_left) / SIGMA_REF_WIDTH)
        patch = _composite(out[top:bottom, left:right], mask, sigma=strength)
        out[top:bottom, left:right] = patch
    return out


def blur_image_faces(
    name: Any,
    *,
    destination: Path | str | None = None,
    conf: float = CONF,
    scope: Any = DEFAULT_SCOPE,
    settings: dict[str, float] | None = None,
    paint: Sequence[dict[str, Any]] | None = None,
    detect: bool | None = None,
    detector: Any = None,
) -> dict[str, Any]:
    """Blur the faces in one input file and write the copy; never raises.

    ``scope`` picks how much of the head a *detected* face blur covers (``face`` /
    ``hair`` / ``head``). ``paint`` adds hand-painted areas (normalized strokes, see
    ``sheet_spec.parse_blur_paint``) and ``detect`` says whether the face detector runs
    at all - ``None`` means "if a model is there", ``False`` means the painted areas are
    the whole job, so no model is needed.

    Returns a report - ``{ok, reason, file, url, boxes, painted, cached, seconds}`` -
    where ``file`` is the value a ``LoadImage`` accepts (relative to the input folder).
    On any failure the report has ``ok: False`` and a ``reason``; the caller then keeps
    the original reference.
    """
    import time

    strokes = list(paint or [])
    report: dict[str, Any] = {
        "ok": False,
        "reason": "",
        "file": "",
        "boxes": [],
        "painted": len(strokes),
        "cached": False,
        "scope": str(scope or DEFAULT_SCOPE),
    }
    source = resolve_input_file(name)
    root = input_root()
    if source is None or root is None:
        report["reason"] = f"{name!r} is not a file inside ComfyUI's input folder"
        return report

    model = model_path()
    wants_detect = detect is not False
    if wants_detect and detector is None and model is None:
        if not strokes:
            report["reason"] = (
                "no face model found (models/ultralytics/bbox/face_yolov8m.pt) - "
                "reference left unblurred"
            )
            return report
        # Painted areas do not need the model: carry on with the painting alone.
        wants_detect = False

    patch = settings if settings is not None else settings_for_scope(scope)
    key = cache_key(
        source, settings=patch, model=model if wants_detect else None, paint=strokes
    )
    target = derived_path(source, key=key, root=root)
    relative = target.relative_to(root).as_posix()
    try:
        if target.is_file() and target.stat().st_size > 0:
            report.update(ok=True, file=relative, cached=True, reason="already blurred")
            return report
    except OSError:
        pass

    started = time.time()
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001 - no opencv, no blur
        report["reason"] = f"opencv unavailable: {exc}"
        return report

    image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if image is None:
        report["reason"] = f"{name!r} could not be read as an image"
        return report

    boxes: list[tuple[int, int, int, int]] = []
    if wants_detect:
        try:
            boxes = detect_faces(image, conf=conf, detector=detector)
        except Exception as exc:  # noqa: BLE001 - a detector error is a warning
            if not strokes:
                report["reason"] = f"face detection failed: {exc}"
                return report
            log.warning("Character sheet: face detection failed, painting only: %s", exc)
    if not boxes and not strokes:
        report["reason"] = "no face detected - reference left unblurred"
        return report

    try:
        blurred = image
        if boxes:
            blurred = blur_boxes(blurred, boxes, **_box_kwargs(settings, scope))
        if strokes:
            # Painted areas go on last: the user pointed at those pixels, so they must not
            # be diluted by whatever the detector decided around them.
            blurred = blur_painted(blurred, strokes)
        target.parent.mkdir(parents=True, exist_ok=True)
        # cv2.imwrite is silently unhappy with some unicode paths; encode + write.
        ok, buffer = cv2.imencode(".png", blurred)
        if not ok:
            report["reason"] = "the blurred image could not be encoded"
            return report
        buffer.tofile(str(target))
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"face blur failed: {exc}"
        return report

    parts = []
    if boxes:
        parts.append(f"{len(boxes)} face(s)")
    if strokes:
        parts.append(f"{len(strokes)} painted area(s)")
    report.update(
        ok=True,
        file=relative,
        boxes=[list(box) for box in boxes],
        reason=f"{' + '.join(parts)} blurred" if parts else "nothing to blur",
        seconds=round(time.time() - started, 2),
    )
    log.info(
        "Character sheet: face blur %s -> %s (%s, %.2fs)",
        source.name,
        relative,
        report["reason"],
        report.get("seconds", 0.0),
    )
    return report


def blur_reference_plan(
    spec: Any,
    plan: dict[str, list[dict[str, Any]]],
    *,
    detector: Any = None,
) -> list[str]:
    """Rewrite a reference plan so flagged pictures are wired as blurred copies.

    Mutates ``plan`` in place (that is what ``build_sheet_graph`` reads) and returns the
    human-readable lines for the log and the run report. Entries are matched by their
    source slot - the loader node is built per source, so every cell that reuses the
    same reference gets the same blurred file without a second detection run.
    """
    from . import sheet_spec

    decisions = sheet_spec.blur_face_decisions(spec)
    detects = sheet_spec.blur_detects_faces(spec)
    painted = {
        (ref.kind, ref.source if ref.source >= 0 else ref.index): list(ref.blur_paint)
        for ref in spec.refs
        if ref.enabled and ref.blur_paint
    }
    scope = getattr(getattr(spec, "render", None), "blur_scope", DEFAULT_SCOPE)
    wanted = [key for key, decision in decisions.items() if decision == "blur"]
    lines: list[str] = []
    if wanted:
        lines.append(
            f"face blur ({scope}): "
            + ", ".join(f"picture {slot + 1}" for kind, slot in wanted if kind == "picture")
        )
    if not wanted:
        return lines

    for group, kind in (("pictures", "picture"), ("videos", "video"), ("audios", "audio")):
        for item in plan.get(group) or []:
            slot_id = str(item.get("source_slot_id") or "")
            index = int(slot_id.rsplit("_", 1)[-1]) if slot_id.rsplit("_", 1)[-1].isdigit() else -1
            if (kind, index) not in decisions:
                continue
            decision = decisions[(kind, index)]
            if decision == "unsupported":
                lines.append(
                    f"face blur: {item.get('file')!r} is a {kind} reference and is not "
                    "blurred (only pictures are); its role still forbids the likeness in the prompt."
                )
                continue
            if decision != "blur":
                continue
            original = str(item.get("file") or "")
            strokes = painted.get((kind, index)) or []
            report = blur_image_faces(
                original,
                scope=scope,
                paint=strokes,
                detect=detects.get((kind, index), True),
                detector=detector,
            )
            if report.get("ok"):
                item["file"] = report["file"]
                lines.append(
                    f"face blur: {Path(original).name} -> {report['file']} "
                    f"({report.get('reason', '')}{', cached' if report.get('cached') else ''})"
                )
            else:
                lines.append(f"face blur skipped for {original!r}: {report.get('reason', '')}")
    return lines


__all__ = [
    "CONF",
    "DEFAULT_SCOPE",
    "DERIVED_SUBDIR",
    "FEATHER",
    "MODEL_CANDIDATES",
    "PAD_UP",
    "PAD_X",
    "PAD_Y",
    "PAINT_FEATHER",
    "SCOPE_SETTINGS",
    "SETTINGS",
    "SIGMA",
    "blur_boxes",
    "blur_image_faces",
    "blur_painted",
    "blur_reference_plan",
    "cache_key",
    "derived_path",
    "detect_faces",
    "feather_mask",
    "input_root",
    "load_detector",
    "model_path",
    "PAINT_DEFAULT_RADIUS",
    "paint_mask",
    "resolve_input_file",
    "settings_for_scope",
]
