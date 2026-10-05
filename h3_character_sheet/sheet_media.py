# ComfyUI-H3-Character-Sheet - media browser for the reference grid.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""List ComfyUI inputs / outputs so the panel can offer a browse picker.

Drag and drop is the fast path, but a sheet usually reuses references that are
already on disk, so the panel browses the same media the rest of ComfyUI sees.
This module answers with plain JSON and no filesystem surprises:

* only ComfyUI's own ``input`` and ``output`` folders are listed,
* the requested subfolder is resolved and re-checked against its base folder (no
  ``..``), and a recursive walk checks every DIRECTORY it enters the same way and
  never descends a symlink - so nothing outside the base can be listed,
* file kinds come from :func:`folder_paths.filter_files_content_types` when it is
  importable, unioned with an explicit extension whitelist (some containers such
  as ``.mkv`` are missing from Python's mimetypes table),
* ``/view`` URLs are built the way core builds them, so thumbnails, video posters
  and audio previews need no extra route.

**Cost.** The folders are not always local: on this box the output folder is a
network share, and walking it cold has measured **31s** against 1.3s warm, with
~4s of pure Python on top for a 25k-file input folder. So the walk

* filters by file NAME before touching the filesystem (a ``stat`` per candidate is
  the expensive part, and only the files that can match ever get one),
* uses ``os.scandir`` and the ``DirEntry`` it hands out, instead of resolving the
  path of every file,
* stops after :data:`DEFAULT_BUDGET_MS` and says so (``partial``), so a request
  never blocks on a cold share,
* and is cached by :func:`cached_media` (:data:`CACHE_TTL` seconds, stale answers
  served while a background thread refreshes them).
"""

from __future__ import annotations

import mimetypes
import os
import threading
import time
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

#: How long one listing may scan before it answers with what it has (``partial``).
#: A cold network share has measured 31s for the output folder, and a picker that
#: hangs for half a minute reads as broken; the rest of the walk finishes in a
#: background thread and the next request is instant.
DEFAULT_BUDGET_MS = 2500

#: A cached listing is used as-is for this long. After that it is still served
#: (an instant answer beats a correct one two seconds later) while a background
#: thread refreshes it.
CACHE_TTL = 20.0

#: How many listings to remember. Keyed per (folder, kind, query, recursive, limit),
#: so a session's worth of browsing fits and nothing grows without bound.
CACHE_MAX = 48

#: The budget a background refresh gets: generous, because nobody is waiting.
REFRESH_BUDGET_MS = 60_000

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


def _entry(path: Path, base: Path, source: str, stat: Any = None) -> dict[str, Any]:
    """Describe one file the way the panel needs it (paths relative to ``base``).

    ``stat`` is a ``os.stat_result`` the caller already has (a ``DirEntry`` was
    scanned either way, so using its cached stat saves one syscall per file - the
    part that costs real time on a network share).
    """
    relative = path.relative_to(base).as_posix()
    subfolder = relative.rsplit("/", 1)[0] if "/" in relative else ""
    if stat is None:
        try:
            stat = path.stat()
        except OSError:
            size, mtime = 0, 0.0
        else:
            size, mtime = int(stat.st_size), float(stat.st_mtime)
    else:
        size, mtime = int(stat.st_size), float(stat.st_mtime)
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
    budget_ms: float | None = None,
) -> dict[str, Any]:
    """List media inside one ComfyUI folder.

    ``recursive`` walks the whole folder and sorts newest first, which is what the
    panel wants right after a render; otherwise only the current level is listed,
    with subfolders included so the picker can navigate.

    ``budget_ms`` caps how long the walk may take: when it runs out the answer is
    what has been found so far, with ``partial: True``. The shallow listing is one
    ``scandir`` of one directory (sub-100ms even on a share) and ignores the
    budget - it is never the slow path.
    """
    started = time.perf_counter()
    source_key = normalize_source(source)
    kind_key = normalize_kind(kind)
    base = Path(base_dir) if base_dir is not None else _default_base(source_key)
    budget = DEFAULT_BUDGET_MS if budget_ms is None else max(0.0, float(budget_ms))
    payload: dict[str, Any] = {
        "ok": True,
        "source": source_key,
        "kind": kind_key,
        "subfolder": str(subfolder or ""),
        "parent": None,
        "folders": [],
        "items": [],
        "truncated": False,
        "partial": False,
        "recursive": bool(recursive),
        "scanMs": 0.0,
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
        found, partial = _walk_media(target, base, kind_key, needle, budget_ms=budget,
                                      started=started)
        payload["partial"] = partial
        found.sort(key=lambda item: item[1].st_mtime, reverse=True)
        entries = [_entry(path, base, source_key, stat=stat) for path, stat in found]
        payload["items"], payload["truncated"] = _limited(entries, limit)
        payload["scanMs"] = round((time.perf_counter() - started) * 1000, 1)
        return payload

    folders: list[dict[str, str]] = []
    entries = []
    try:
        children = list(os.scandir(target))
    except OSError as exc:
        payload["ok"] = False
        payload["error"] = f"{target} could not be read ({exc.strerror or exc})."
        return payload
    children.sort(key=lambda item: item.name.lower())
    files: dict[str, Any] = {}
    for child in children:
        try:
            if child.is_dir():
                if needle and needle not in child.name.lower():
                    continue
                folders.append({
                    "name": child.name,
                    "path": Path(child.path).relative_to(base).as_posix(),
                })
                continue
            if not child.is_file():  # sockets, fifos, dangling links
                continue
        except OSError:
            continue
        if needle and needle not in child.name.lower():
            continue
        files[child.name] = child
    # The whitelist is unioned with ComfyUI's own content-type filter (as it always was), so a file
    # kind only core knows about is still offered - and the stat is only paid for the survivors.
    for name in sorted(set(allowed_names(list(files), kind_key)) & set(files), key=str.lower):
        child = files[name]
        try:
            entries.append(_entry(Path(child.path), base, source_key, stat=child.stat()))
        except OSError:
            continue

    payload["folders"] = folders
    payload["items"], payload["truncated"] = _limited(entries, limit)
    payload["scanMs"] = round((time.perf_counter() - started) * 1000, 1)
    return payload


def _walk_media(
    target: Path,
    base: Path,
    kind_key: str,
    needle: str,
    *,
    budget_ms: float,
    started: float,
) -> tuple[list[tuple[Path, Any]], bool]:
    """``([(path, stat), ...], partial)`` for every media file under ``target``.

    ``os.scandir`` rather than ``os.walk`` so each file's ``DirEntry`` (and the stat
    it caches) is used instead of a fresh ``Path.stat()``, and the name filter runs
    BEFORE the stat: on the box's network share a stat costs 0.4ms, which is the
    whole cost of a 4k-file tree.

    A directory is checked against ``base`` once, before it is entered, and
    symlinked directories are never entered (that is what keeps the walk inside the
    folder it was pointed at - the old code re-resolved every single file, which
    cost seconds for the same guarantee).
    """
    found: list[tuple[Path, Any]] = []
    stack = [target]
    deadline = started + (budget_ms / 1000.0)
    checked: dict[Path, bool] = {}
    seen = 0
    while stack:
        current = stack.pop()
        inside = checked.get(current)
        if inside is None:
            inside = checked[current] = _inside(current, base)
        if not inside:
            continue
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    seen += 1
                    if needle and needle not in entry.name.lower():
                        continue
                    detected = file_kind(entry.name)
                    if detected is None or (kind_key != "all" and detected != kind_key):
                        continue
                    found.append((Path(entry.path), entry.stat(follow_symlinks=False)))
                    if seen % 256 == 0 and time.perf_counter() > deadline:
                        return found, True
        except OSError:
            continue
        if time.perf_counter() > deadline:
            return found, bool(stack)
    return found, False


# --------------------------------------------------------------------------- #
# the cache
# --------------------------------------------------------------------------- #
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_refreshing: set[tuple] = set()


def _cache_key(base: Path, kind_key: str, subfolder: str, needle: str, recursive: bool,
               limit: int) -> tuple:
    return (str(base), kind_key, subfolder, needle, bool(recursive), int(limit))


def _stored(key: tuple, payload: dict[str, Any], *, cached: bool, stale: bool) -> dict[str, Any]:
    """A copy of a cached payload, marked with how it was answered."""
    out = {**payload, "cached": bool(cached), "stale": bool(stale)}
    out["items"] = list(payload.get("items") or [])
    out["folders"] = list(payload.get("folders") or [])
    return out


def reset_cache() -> None:
    """Forget every cached listing (tests, and a "refresh" the caller wants)."""
    with _cache_lock:
        _cache.clear()
        _refreshing.clear()


def _refresh(key: tuple, kwargs: dict[str, Any]) -> None:
    """Recompute one listing in the background and store it."""
    try:
        payload = list_media(**kwargs, budget_ms=REFRESH_BUDGET_MS)
    except Exception:  # noqa: BLE001 - a background refresh may never raise into a thread
        payload = None
    with _cache_lock:
        _refreshing.discard(key)
        if payload is not None:
            _cache[key] = (time.time(), payload)


def _schedule(key: tuple, kwargs: dict[str, Any]) -> None:
    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)
    threading.Thread(target=_refresh, args=(key, kwargs), name="h3sheet-media", daemon=True).start()


def cached_media(
    source: Any = "inputs",
    kind: Any = "all",
    subfolder: str = "",
    *,
    query: str = "",
    recursive: bool = False,
    limit: int = DEFAULT_LIMIT,
    base_dir: str | os.PathLike[str] | None = None,
    budget_ms: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """``list_media`` behind a small cache, for the HTTP route.

    Three answers, in the order the picker wants them:

    * **fresh** (younger than :data:`CACHE_TTL`): served as-is, no filesystem work at
      all - which is what makes re-opening the picker, switching kind, or typing in
      the search box feel instant.
    * **stale**: served immediately (with ``stale: True``) while a background thread
      recomputes it, so a cold share never blocks a click. Repeat requests until the
      refresh lands get the same stale answer instead of stacking walks.
    * **cold**: computed inline, but only for ``budget_ms``; a walk that runs out of
      time answers with ``partial: True`` and the full result arrives in the
      background.
    """
    key = None
    kwargs: dict[str, Any] = {}
    if base_dir is not None or _default_base(normalize_source(source)) is not None:
        source_key = normalize_source(source)
        base = Path(base_dir) if base_dir is not None else _default_base(source_key)
        if base is not None:
            kwargs = {
                "source": source_key,
                "kind": normalize_kind(kind),
                "subfolder": str(subfolder or ""),
                "query": str(query or ""),
                "recursive": bool(recursive),
                "limit": limit,
                "base_dir": base,
            }
            key = _cache_key(Path(base), normalize_kind(kind), str(subfolder or ""),
                             str(query or "").strip().lower(), bool(recursive), limit)
    if key is None:  # no folder configured: nothing to cache, let list_media explain
        return list_media(source, kind, subfolder, query=query, recursive=recursive,
                          limit=limit, base_dir=base_dir, budget_ms=budget_ms)

    stamp = time.time() if now is None else float(now)
    with _cache_lock:
        entry = _cache.get(key)
    if entry is not None:
        age = stamp - entry[0]
        if age < CACHE_TTL and not entry[1].get("partial"):
            return _stored(key, entry[1], cached=True, stale=False)
        _schedule(key, kwargs)
        return _stored(key, entry[1], cached=True, stale=True)

    payload = list_media(**kwargs, budget_ms=budget_ms)
    with _cache_lock:
        _cache[key] = (stamp, payload)
        if len(_cache) > CACHE_MAX:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            if oldest != key:
                _cache.pop(oldest, None)
    if payload.get("partial") or payload.get("ok") is False:
        # A partial (or failed) answer is worth keeping for the instant reply it gives,
        # but it must never count as fresh: the real one is on its way.
        _schedule(key, kwargs)
    return _stored(key, payload, cached=False, stale=False)


__all__ = [
    "AUDIO_EXTENSIONS",
    "CACHE_MAX",
    "CACHE_TTL",
    "DEFAULT_BUDGET_MS",
    "DEFAULT_LIMIT",
    "IMAGE_EXTENSIONS",
    "KINDS",
    "MAX_LIMIT",
    "VIDEO_EXTENSIONS",
    "allowed_names",
    "cached_media",
    "file_kind",
    "list_media",
    "normalize_kind",
    "normalize_source",
    "reset_cache",
    "resolve_subfolder",
    "view_url",
]
