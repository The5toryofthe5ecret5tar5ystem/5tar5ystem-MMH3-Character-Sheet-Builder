# ComfyUI-H3-Character-Sheet - media browser for the reference grid.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""List ComfyUI inputs / outputs so the panel can offer a browse picker.

Drag and drop is the fast path, but a sheet usually reuses references that are
already on disk, so the panel browses the same media the rest of ComfyUI sees.
This module answers with plain JSON and no filesystem surprises:

* only ComfyUI's own ``input`` and ``output`` folders are listed,
* every request is resolved and re-checked against its base folder (no ``..``),
* file kinds come from :func:`folder_paths.filter_files_content_types` when it is
  importable, unioned with an explicit extension whitelist (some containers such
  as ``.mkv`` are missing from Python's mimetypes table),
* ``/view`` URLs are built the way core builds them, so thumbnails, video posters
  and audio previews need no extra route.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".jpe", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".wmv", ".flv", ".ts",
}
AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif",
}

KINDS = ("image", "video", "audio", "all")
MAX_LIMIT = 1000
DEFAULT_LIMIT = 300

_EXTENSIONS_BY_KIND = {
    "image": IMAGE_EXTENSIONS,
    "video": VIDEO_EXTENSIONS,
    "audio": AUDIO_EXTENSIONS,
}

_SOURCE_TO_TYPE = {"inputs": "input", "outputs": "output"}
_SOURCE_TO_GETTER = {"inputs": "get_input_directory", "outputs": "get_output_directory"}

#: Characters left unescaped in ``/view`` query values (same set core uses).
_URL_SAFE = "-_.!~*'()"


def normalize_kind(kind: Any) -> str:
    text = str(kind or "all").strip().lower()
    return text if text in KINDS else "all"


def normalize_source(source: Any) -> str:
    text = str(source or "inputs").strip().lower()
    return text if text in _SOURCE_TO_TYPE else "inputs"


def _mime_kind(filename: str) -> str | None:
    """Best-effort content kind from Python's mimetypes table."""
    mime_type, _ = mimetypes.guess_type(filename, strict=False)
    if not mime_type:
        return None
    content = mime_type.split("/")[0]
    return content if content in ("image", "video", "audio") else None


def file_kind(filename: str) -> str | None:
    """``"image"`` / ``"video"`` / ``"audio"`` for a file name, else ``None``.

    The explicit whitelist wins (it knows about containers mimetypes misses);
    mimetypes fills in the long tail (``.apng``, ``.3gp``, ...).
    """
    suffix = Path(str(filename)).suffix.lower()
    for kind, extensions in _EXTENSIONS_BY_KIND.items():
        if suffix in extensions:
            return kind
    return _mime_kind(filename)


def allowed_names(names: Iterable[str], kind: str) -> list[str]:
    """Filter file names down to ``kind`` (``"all"`` keeps every known media type).

    Uses ComfyUI's own content-type filter when it is importable so the browser
    agrees with the rest of ComfyUI, then unions in the whitelist decision.
    """
    text = [str(name) for name in names]
    wanted = [] if kind == "all" else [kind]
    keep: set[str] = set()
    try:  # pragma: no cover - depends on the ComfyUI install
        import folder_paths

        filterer = getattr(folder_paths, "filter_files_content_types", None)
        if callable(filterer):
            keep.update(filterer(text, wanted or ["image", "video", "audio"]))
    except Exception:  # noqa: BLE001 - standalone use / test stub
        pass
    for name in text:
        detected = file_kind(name)
        if detected is None:
            continue
        if kind == "all" or detected == kind:
            keep.add(name)
    return [name for name in text if name in keep]


def view_url(name: str, source: str, subfolder: str = "") -> str:
    """ComfyUI ``/view`` URL for a file inside the input/output folder."""
    type_param = _SOURCE_TO_TYPE.get(normalize_source(source), "input")
    filename = quote(os.path.basename(name), safe=_URL_SAFE)
    sub = quote(subfolder or "", safe=_URL_SAFE)
    return f"/view?filename={filename}&type={type_param}&subfolder={sub}"


def resolve_subfolder(base: Path, subfolder: str) -> Path | None:
    """``base/subfolder`` when it stays inside ``base`` (else ``None``)."""
    base_resolved = base.resolve()
    relative = str(subfolder or "").strip("/\\")
    candidate = (base_resolved / relative) if relative else base_resolved
    try:
        candidate = candidate.resolve()
        candidate.relative_to(base_resolved)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_dir() else None


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _entry(path: Path, base: Path, source: str) -> dict[str, Any]:
    """Describe one file the way the panel needs it (paths relative to ``base``)."""
    relative = path.relative_to(base).as_posix()
    subfolder = relative.rsplit("/", 1)[0] if "/" in relative else ""
    try:
        stat = path.stat()
        size, mtime = int(stat.st_size), float(stat.st_mtime)
    except OSError:
        size, mtime = 0, 0.0
    return {
        "name": path.name,
        "path": relative,
        "subfolder": subfolder,
        "kind": file_kind(path.name) or "other",
        "url": view_url(path.name, source, subfolder),
        "size": size,
        "mtime": mtime,
    }


def _limited(entries: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    limit = DEFAULT_LIMIT if limit <= 0 else min(int(limit), MAX_LIMIT)
    return entries[:limit], len(entries) > limit


def _default_base(source_key: str) -> Path | None:
    try:
        import folder_paths

        getter = getattr(folder_paths, _SOURCE_TO_GETTER[source_key], None)
        directory = getter() if callable(getter) else None
    except Exception:  # noqa: BLE001 - ComfyUI core not importable
        directory = None
    return Path(directory) if directory else None


def list_media(
    source: Any = "inputs",
    kind: Any = "all",
    subfolder: str = "",
    *,
    query: str = "",
    recursive: bool = False,
    limit: int = DEFAULT_LIMIT,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """List media inside one ComfyUI folder.

    ``recursive`` walks the whole folder and sorts newest first, which is what the
    panel wants right after a render; otherwise only the current level is listed,
    with subfolders included so the picker can navigate.
    """
    source_key = normalize_source(source)
    kind_key = normalize_kind(kind)
    base = Path(base_dir) if base_dir is not None else _default_base(source_key)
    payload: dict[str, Any] = {
        "ok": True,
        "source": source_key,
        "kind": kind_key,
        "subfolder": str(subfolder or ""),
        "parent": None,
        "folders": [],
        "items": [],
        "truncated": False,
    }
    if base is None:
        payload["ok"] = False
        payload["error"] = f"ComfyUI has no {source_key} folder configured."
        return payload

    target = resolve_subfolder(base, subfolder)
    if target is None:
        payload["ok"] = False
        payload["error"] = f"{subfolder!r} is not a folder inside {base}."
        return payload

    current = str(subfolder or "").strip("/\\")
    payload["subfolder"] = current
    payload["base"] = str(base)
    if current:
        payload["parent"] = current.rsplit("/", 1)[0] if "/" in current else ""

    needle = str(query or "").strip().lower()

    if recursive:
        found: list[Path] = []
        for root, _dirs, files in os.walk(target):
            for name in files:
                if needle and needle not in name.lower():
                    continue
                detected = file_kind(name)
                if detected is None or (kind_key != "all" and detected != kind_key):
                    continue
                path = Path(root) / name
                if _inside(path, base):
                    found.append(path)
        entries = [_entry(path, base, source_key) for path in found]
        entries.sort(key=lambda item: item["mtime"], reverse=True)
        payload["items"], payload["truncated"] = _limited(entries, limit)
        return payload

    folders: list[dict[str, str]] = []
    names: list[str] = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
        try:
            if child.is_dir():
                if needle and needle not in child.name.lower():
                    continue
                folders.append({
                    "name": child.name,
                    "path": child.relative_to(base).as_posix(),
                })
            elif child.is_file():
                names.append(child.name)
        except OSError:
            continue

    keep = set(allowed_names(names, kind_key))
    entries = []
    for name in sorted(names, key=str.lower):
        if name not in keep:
            continue
        if needle and needle not in name.lower():
            continue
        entries.append(_entry(target / name, base, source_key))

    payload["folders"] = folders
    payload["items"], payload["truncated"] = _limited(entries, limit)
    return payload


__all__ = [
    "AUDIO_EXTENSIONS",
    "DEFAULT_LIMIT",
    "IMAGE_EXTENSIONS",
    "KINDS",
    "MAX_LIMIT",
    "VIDEO_EXTENSIONS",
    "allowed_names",
    "file_kind",
    "list_media",
    "normalize_kind",
    "normalize_source",
    "resolve_subfolder",
    "view_url",
]
