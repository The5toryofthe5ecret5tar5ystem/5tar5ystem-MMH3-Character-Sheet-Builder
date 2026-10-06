# ComfyUI-H3-Character-Sheet - the LoRA stack: files, hashes, Civitai, metadata.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""LoRAs for the sheet: what is installed, what Civitai knows about it, and applying a stack.

The sheet node takes a MODEL and passes it through, so a LoRA can always be wired in front of it
with an ordinary loader node (see the README's *LoRAs* section - that stays the way to use a
loader). This module is the other half: the panel's own **LoRAs** tab, where the stack lives on
the *sheet* instead of in the graph, so one list of LoRAs covers every cell and every board.

Four jobs, and one rule for all of them - **never fail a render**:

* ``lora_files()`` / ``listing()``: the installed LoRAs, straight from ComfyUI's own loras folder.
* ``sha256_of()`` / ``file_hash()``: the digest Civitai looks files up by, cached in the store
  against the file's size and mtime, so it is computed once per file (a re-download re-hashes
  itself).
* ``civitai_lookup()`` / ``fetch_info()``: the Civitai model-version lookup by hash - the title,
  tags, base model, trigger words and link that a user otherwise reads in a browser tab. Only
  ``fetch_info`` ever touches the network, it is called when the user asks for it (a row's button
  or the tab's *Fetch info* action), and every failure is an answer, not an exception.
* ``apply_stack()``: the stack onto the model every cell samples through, with
  ``comfy.sd.load_lora_for_models`` - the same call core's own LoRA loaders make, so a stack here
  and a loader in front of the node compose instead of fighting.

The per-file metadata (display name, the strength range a slider should offer, notes, and the
Civitai answer) lives in ``<ComfyUI>/user/default/h3_character_sheet/loras.json`` - the user
directory, like the saved presets, because it is configuration rather than output.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.sheet.loras")

#: ComfyUI's own folder name for LoRAs (``models/loras``), the one ``folder_paths`` knows.
LORA_FOLDER = "loras"

#: Where the metadata goes, relative to ComfyUI's user directory (see ``user_presets``).
STORE_DIRNAME = "h3_character_sheet"
STORE_FILENAME = "loras.json"
PROFILE_DIRNAME = "default"

#: Civitai's lookup-by-hash endpoint: the same call the Civitai helper extensions make, and the
#: only address this pack ever asks for. Public, no key, no account.
CIVITAI_BY_HASH = "https://civitai.com/api/v1/model-versions/by-hash/{digest}"
CIVITAI_TIMEOUT = 20.0
CIVITAI_MODEL_PAGE = "https://civitai.com/models/{model_id}"
USER_AGENT = (
    "ComfyUI-H3-Character-Sheet/2.0 "
    "(+https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder)"
)

#: Hashing reads the file: 1MB chunks keep a 300MB LoRA cheap and the memory flat.
HASH_CHUNK = 1024 * 1024
#: ``lora_files()`` is a folder listing, but the panel asks for it on mount and on refresh.
LIST_TTL = 15.0

#: Bounds the panel can write: a name and a note are text, the strengths are numbers.
MAX_NAME_LENGTH = 120
MAX_NOTE_LENGTH = 2000
STRENGTH_RANGE = (-4.0, 4.0)
#: How much of Civitai's description is worth carrying into a panel card.
MAX_DESCRIPTION = 700
MAX_IMAGES = 3
MAX_TAGS = 24
#: Civitai's samples are often animated (a LoRA page is full of .mp4 loops). A card shows a still,
#: so the two are separated rather than left to the browser to fail on.
_VIDEO_SUFFIX = re.compile(r"\.(mp4|webm|mov|m4v|gif)(\?|$)", re.IGNORECASE)

_list_cache: tuple[float, list[str]] | None = None


# --------------------------------------------------------------------------- #
# where things live
# --------------------------------------------------------------------------- #
def store_path() -> Path:
    """Where the LoRA metadata lives (never raises; callers may create the parents)."""
    try:
        import folder_paths  # noqa: PLC0415 - ComfyUI is not importable in every context

        root = Path(folder_paths.get_user_directory()) / PROFILE_DIRNAME
    except Exception:  # noqa: BLE001 - no folder_paths (tests, standalone import)
        root = Path.home() / ".comfyui-user" / PROFILE_DIRNAME
    return root / STORE_DIRNAME / STORE_FILENAME


def lora_files(*, fresh: bool = False) -> list[str]:
    """Every installed LoRA, relative to ``models/loras`` (ComfyUI's own listing)."""
    global _list_cache
    now = time.monotonic()
    if not fresh and _list_cache is not None and now - _list_cache[0] < LIST_TTL:
        return _list_cache[1]
    names: list[str] = []
    try:
        import folder_paths  # noqa: PLC0415

        names = [str(name) for name in folder_paths.get_filename_list(LORA_FOLDER)]
    except Exception as exc:  # noqa: BLE001 - no ComfyUI, no loras folder: an empty list
        log.debug("Character sheet: cannot list loras (%s)", exc)
        names = []
    names = sorted({name.strip() for name in names if str(name).strip()}, key=str.lower)
    _list_cache = (now, names)
    return names


def lora_path(file: Any) -> Path | None:
    """The full path of one LoRA, or ``None`` when this install does not have it."""
    name = str(file or "").strip()
    if not name:
        return None
    try:
        import folder_paths  # noqa: PLC0415

        resolved = folder_paths.get_full_path(LORA_FOLDER, name)
    except Exception:  # noqa: BLE001
        resolved = None
    if not resolved:
        return None
    path = Path(resolved)
    return path if path.is_file() else None


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #
def _read_store() -> dict[str, dict[str, Any]]:
    """The stored records keyed by file, or ``{}`` when there are none / they are unreadable."""
    try:
        raw = json.loads(store_path().read_text())
    except Exception:  # noqa: BLE001 - missing, unreadable or invalid JSON = no metadata
        return {}
    records = raw.get("loras") if isinstance(raw, dict) else None
    if not isinstance(records, dict):
        return {}
    return {str(key): dict(value) for key, value in records.items() if isinstance(value, dict)}


def _write_store(records: Mapping[str, Mapping[str, Any]]) -> None:
    """Write the store atomically (a half-written file would lose every name and note)."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "loras": {key: dict(value) for key, value in records.items()}}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True))
    temporary.replace(path)


def record_for(file: Any) -> dict[str, Any]:
    """One file's stored metadata (a copy, so a caller cannot edit the store by accident)."""
    return dict(_read_store().get(str(file or "").strip(), {}))


def _clean_name(value: Any) -> str:
    return str(value if value is not None else "").strip()[:MAX_NAME_LENGTH]


def _clean_notes(value: Any) -> str:
    return str(value if value is not None else "").strip()[:MAX_NOTE_LENGTH]


def _clean_strength(value: Any) -> float | None:
    """A strength bound, or ``None`` for "not set" (the panel then uses the default range)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(min(STRENGTH_RANGE[1], max(STRENGTH_RANGE[0], number)), 3)


def save_metadata(file: Any, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Store the panel's own fields for one file (name, strength range, notes).

    Only the keys that are present are touched, so a route can save a note without clearing the
    name a user set earlier. Unknown keys are ignored rather than stored: this file is read by
    humans too.
    """
    name = str(file or "").strip()
    if not name:
        return {"ok": False, "error": "A lora file name is required."}
    records = _read_store()
    record = records.get(name, {})
    if "name" in fields:
        record["name"] = _clean_name(fields.get("name"))
    if "strengthMin" in fields:
        record["strengthMin"] = _clean_strength(fields.get("strengthMin"))
    if "strengthMax" in fields:
        record["strengthMax"] = _clean_strength(fields.get("strengthMax"))
    if "notes" in fields:
        record["notes"] = _clean_notes(fields.get("notes"))
    record["updatedAt"] = time.time()
    records[name] = record
    try:
        _write_store(records)
    except Exception as exc:  # noqa: BLE001 - a metadata write never fails a render
        log.warning("Character sheet: could not save LoRA metadata for %s (%s)", name, exc)
        return {"ok": False, "error": f"Could not write {store_path()}: {exc}"}
    return {"ok": True, "file": name, "record": _public_record(record)}


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def sha256_of(path: Path, *, chunk: int = HASH_CHUNK) -> str:
    """The SHA256 of a file - the digest Civitai's lookup is keyed by."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def file_hash(file: Any, *, force: bool = False) -> dict[str, Any]:
    """One file's sha256, computed at most once per version of the file.

    The digest is cached in the store beside the file's size and mtime, so renaming or moving a
    LoRA inside ``models/loras`` keeps its metadata and a re-downloaded file re-hashes itself.
    """
    name = str(file or "").strip()
    path = lora_path(name)
    if path is None:
        return {"ok": False, "file": name, "error": f"{name or 'that file'} is not in models/{LORA_FOLDER}."}
    try:
        stat = path.stat()
    except OSError as exc:
        return {"ok": False, "file": name, "error": f"could not read {path}: {exc}"}
    records = _read_store()
    record = records.get(name, {})
    cached = (
        not force
        and str(record.get("sha256") or "")
        and record.get("size") == stat.st_size
        and record.get("mtime") == round(stat.st_mtime, 3)
    )
    if cached:
        return {"ok": True, "file": name, "sha256": str(record["sha256"]), "cached": True}
    try:
        digest = sha256_of(path)
    except OSError as exc:
        return {"ok": False, "file": name, "error": f"could not hash {path}: {exc}"}
    record.update({
        "sha256": digest,
        "size": stat.st_size,
        "mtime": round(stat.st_mtime, 3),
        "hashAt": time.time(),
    })
    records[name] = record
    try:
        _write_store(records)
    except Exception as exc:  # noqa: BLE001 - the digest is still worth returning
        log.warning("Character sheet: could not cache the hash of %s (%s)", name, exc)
    return {"ok": True, "file": name, "sha256": digest, "cached": False, "size": stat.st_size}


# --------------------------------------------------------------------------- #
# Civitai
# --------------------------------------------------------------------------- #
def _get_json(url: str, *, timeout: float = CIVITAI_TIMEOUT) -> dict[str, Any]:
    """One GET, JSON answer, explicit user agent (Civitai refuses the default one)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310 - fixed https host
        body = answer.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _first_line(text: Any, limit: int = MAX_DESCRIPTION) -> str:
    """Civitai descriptions are HTML-ish and long: keep a readable first slice."""
    raw = str(text or "")
    for tag in ("<br />", "<br/>", "<br>", "</p>", "</div>"):
        raw = raw.replace(tag, "\n")
    while "<" in raw and ">" in raw:
        start, end = raw.find("<"), raw.find(">", raw.find("<"))
        if start == -1 or end == -1:
            break
        raw = raw[:start] + " " + raw[end + 1:]
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    joined = " ".join(lines)
    return joined[:limit]


def civitai_lookup(digest: Any) -> dict[str, Any]:
    """What Civitai knows about one file hash - or why it could not be asked.

    Shaped for the panel rather than for Civitai: the fields a card shows, with the link a user
    would otherwise go hunting for. ``found`` is the only field a caller has to check.
    """
    value = str(digest or "").strip().lower()
    if len(value) != 64:
        return {"found": False, "error": "a sha256 hash is 64 hex characters"}
    url = CIVITAI_BY_HASH.format(digest=value)
    try:
        answer = _get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"found": False, "error": "Civitai has no model version with this hash.", "url": url}
        return {"found": False, "error": f"Civitai answered {exc.code}.", "url": url}
    except Exception as exc:  # noqa: BLE001 - offline, DNS, timeout: all the same to the panel
        return {"found": False, "error": f"Could not reach Civitai ({exc}).", "url": url}

    model = answer.get("model") if isinstance(answer.get("model"), dict) else {}
    model_id = answer.get("modelId") or model.get("id")
    version_id = answer.get("id") or answer.get("modelVersionId")
    creator = answer.get("creator") if isinstance(answer.get("creator"), dict) else {}
    raw_images = [
        str(image.get("url"))
        for image in (answer.get("images") or [])
        if isinstance(image, dict) and image.get("url")
    ]
    stills = [url for url in raw_images if not _VIDEO_SUFFIX.search(url)]
    videos = [url for url in raw_images if _VIDEO_SUFFIX.search(url)]
    tags = [
        str(tag)
        for tag in (
            (answer.get("tags") or model.get("tags") or [])
            if isinstance(answer.get("tags") or model.get("tags"), list)
            else []
        )
    ][:MAX_TAGS]
    found: dict[str, Any] = {
        "found": True,
        "hash": value,
        "modelId": model_id,
        "versionId": version_id,
        "modelName": str(model.get("name") or answer.get("name") or "").strip(),
        "versionName": str(answer.get("name") or "").strip(),
        "type": str(model.get("type") or answer.get("modelType") or "").strip(),
        "baseModel": str(answer.get("baseModel") or "").strip(),
        "creator": str(creator.get("username") or "").strip(),
        "nsfw": bool(model.get("nsfw") or answer.get("nsfwLevel")),
        "tags": tags,
        "trainedWords": [str(word) for word in (answer.get("trainedWords") or []) if str(word).strip()],
        "description": _first_line(answer.get("description")),
        "images": stills[:MAX_IMAGES],
        # Samples that are animations. The card shows a still when there is one; these are here so
        # a page whose only sample is a loop still says something rather than "no sample".
        "videos": videos[:MAX_IMAGES],
        "url": (
            CIVITAI_MODEL_PAGE.format(model_id=model_id)
            + (f"?modelVersionId={version_id}" if version_id else "")
            if model_id
            else url
        ),
        "lookupUrl": url,
        "fetchedAt": time.time(),
    }
    return found


def fetch_info(file: Any, *, force: bool = False) -> dict[str, Any]:
    """Hash one LoRA, ask Civitai about it, and keep the answer.

    THE only function here that uses the network, and it is reached from a button - the pack never
    calls Civitai on its own, and a panel mount never costs a request.
    """
    name = str(file or "").strip()
    hashed = file_hash(name, force=force)
    if not hashed.get("ok"):
        return {**hashed, "found": False}
    digest = str(hashed["sha256"])
    record = record_for(name)
    cached = record.get("civitai") if isinstance(record.get("civitai"), dict) else None
    if cached and not force and cached.get("hash") == digest:
        return {"ok": True, "file": name, "sha256": digest, "civitai": cached, "cached": True}

    info = civitai_lookup(digest)
    records = _read_store()
    entry = records.get(name, {})
    entry["sha256"] = digest
    entry["civitaiAt"] = time.time()
    if info.get("found"):
        entry["civitai"] = info
        entry.pop("civitaiError", None)
    else:
        # A miss is remembered too: a file Civitai does not have should not be looked up again
        # on every panel mount, but the next force=True retries it.
        entry["civitaiError"] = str(info.get("error") or "not found")
        entry.setdefault("civitai", None)
    records[name] = entry
    try:
        _write_store(records)
    except Exception as exc:  # noqa: BLE001
        log.warning("Character sheet: could not cache Civitai info for %s (%s)", name, exc)
    return {"ok": True, "file": name, "sha256": digest, "civitai": info, "cached": False}


# --------------------------------------------------------------------------- #
# the panel's listing
# --------------------------------------------------------------------------- #
def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The stored fields the panel may see (no sizes, no mtimes, no half-written entries)."""
    civitai = record.get("civitai") if isinstance(record.get("civitai"), dict) else None
    return {
        "name": str(record.get("name") or ""),
        "strengthMin": record.get("strengthMin"),
        "strengthMax": record.get("strengthMax"),
        "notes": str(record.get("notes") or ""),
        "sha256": str(record.get("sha256") or ""),
        "civitai": civitai,
        "civitaiError": str(record.get("civitaiError") or "") if not civitai else "",
        "civitaiAt": record.get("civitaiAt"),
    }


def label_for(file: str, record: Mapping[str, Any] | None = None) -> str:
    """What the panel calls one LoRA: the name a user gave it, else the file's stem."""
    record = record or {}
    named = _clean_name(record.get("name"))
    if named:
        return named
    stem = Path(str(file)).name
    for suffix in (".safetensors", ".ckpt", ".pt", ".sft"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def listing(*, fresh: bool = False) -> dict[str, Any]:
    """The installed LoRAs plus whatever metadata is already stored (no hashing, no network)."""
    records = _read_store()
    items: list[dict[str, Any]] = []
    for file in lora_files(fresh=fresh):
        record = records.get(file) or {}
        public = _public_record(record)
        items.append({
            "file": file,
            "folder": str(Path(file).parent).replace("\\", "/").replace(".", ""),
            "label": label_for(file, record),
            **public,
        })
    for file, record in records.items():
        if any(item["file"] == file for item in items):
            continue
        # A file that is gone from disk is still worth listing while its metadata matters
        # (a workflow may be about to be fixed), but it is marked so the panel can say so.
        public = _public_record(record)
        items.append({
            "file": file,
            "folder": str(Path(file).parent).replace("\\", "/").replace(".", ""),
            "label": label_for(file, record),
            "missing": True,
            **public,
        })
    items.sort(key=lambda item: str(item["file"]).lower())
    return {
        "ok": True,
        "items": items,
        "count": len(items),
        "missing": sum(1 for item in items if item.get("missing")),
        "store": str(store_path()),
    }


# --------------------------------------------------------------------------- #
# applying a stack
# --------------------------------------------------------------------------- #
def apply_stack(model: Any, stack: Iterable[Any], *, clip: Any = None) -> tuple[Any, list[str], list[str]]:
    """Load every enabled LoRA of ``stack`` onto ``model``.

    ``stack`` holds the spec's own ``SheetLora`` entries (anything with ``file``/``strength``/
    ``on`` will do). Returns ``(model, lines, warnings)``: the lines are the report's record of
    what was applied, the warnings name what was skipped and why. The model a caller passed in is
    never mutated - ``load_lora_for_models`` clones it, exactly as a loader node does.
    """
    entries = [entry for entry in stack or [] if str(getattr(entry, "file", "") or "").strip()]
    if model is None or not entries:
        return model, [], []
    try:
        import comfy.sd  # noqa: PLC0415 - only the executing process has ComfyUI
        import comfy.utils  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - importing the pack must not require lora support
        return model, [], [f"LoRAs could not be applied ({exc}); rendering without them."]

    lines: list[str] = []
    warnings: list[str] = []
    applied: list[str] = []
    for entry in entries:
        name = str(getattr(entry, "file", "") or "").strip()
        if not getattr(entry, "on", True):
            continue
        try:
            strength = float(getattr(entry, "strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        if strength == 0:
            continue
        path = lora_path(name)
        if path is None:
            warnings.append(
                f"LoRA {name!r} is not in models/{LORA_FOLDER}; it was skipped."
            )
            continue
        try:
            lora = comfy.utils.load_torch_file(str(path), safe_load=True)
            loaded, _ = comfy.sd.load_lora_for_models(model, None, lora, strength, 0)
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the sheet
            warnings.append(f"LoRA {name!r} could not be loaded ({exc}); it was skipped.")
            continue
        if loaded is None:
            warnings.append(f"LoRA {name!r} did not attach to this model; it was skipped.")
            continue
        model = loaded
        applied.append(f"{name}@{strength:g}")
    if applied:
        lines.append("LoRA stack: " + ", ".join(applied))
    if warnings:
        lines.extend(warnings)
    return model, lines, warnings


__all__ = [
    "CIVITAI_BY_HASH",
    "LORA_FOLDER",
    "MAX_DESCRIPTION",
    "MAX_NAME_LENGTH",
    "MAX_NOTE_LENGTH",
    "STORE_FILENAME",
    "STRENGTH_RANGE",
    "apply_stack",
    "civitai_lookup",
    "fetch_info",
    "file_hash",
    "label_for",
    "listing",
    "lora_files",
    "lora_path",
    "record_for",
    "save_metadata",
    "sha256_of",
    "store_path",
]
