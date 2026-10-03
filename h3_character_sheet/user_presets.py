# ComfyUI-H3-Character-Sheet - presets the user saved, on disk.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The presets a USER saved: the settings someone actually arrived at, kept.

``presets.py`` is the pack's own opinion (tuned, reviewed, tested against the node schema).
This module is the other half of the same idea: after ten minutes of dialling in a sheet, the
combination that worked should be one click next time instead of a memory test.

Three rules keep it honest:

* **same shape, different storage.** A saved preset is an ordinary ``SheetPreset`` built from
  a JSON record, so ``preset_by_id``, ``apply_to_payload`` and the panel cannot tell it apart
  from a built-in - except that it is marked ``custom``, which is what makes it deletable.
* **never a crash.** Reading a missing, unreadable or half-written file means "no saved
  presets" (and the next save replaces it); a failed write is a message, not an exception
  into a render. A preset is a convenience, never a reason a sheet fails.
* **the store validates on the way in.** Values are flattened to JSON scalars, tick lists are
  filtered against the sheet vocabulary, and the departures from the node's defaults are
  computed here (from the live schema when it is available) rather than trusted from the
  caller - that is the field the panel prints as "Changes: ...".

Where it lives: ``<ComfyUI>/user/default/h3_character_sheet/presets.json`` - the user
directory, not the output directory, because an output folder is a place renders land and
gets cleaned, and this is configuration.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .sheet_spec import EXPRESSION_KEYS, POSE_KEYS, VIEW_KEYS, BACKGROUNDS
from .presets import SheetPreset

#: Where the file goes, relative to ComfyUI's user directory.
STORE_DIRNAME = "h3_character_sheet"
STORE_FILENAME = "presets.json"
#: Profile folder under the user directory (ComfyUI's own default profile).
PROFILE_DIRNAME = "default"

#: A store is a convenience, not a library: past this many the dropdown stops being usable.
MAX_PRESETS = 40
MAX_NAME_LENGTH = 40

#: Ids carry this prefix so a saved preset can never shadow a built-in one.
CUSTOM_PREFIX = "custom-"

#: The render keys a saved preset may carry (the ones the panel owns).
RENDER_KEYS = ("continuity", "exportVideo", "framesPerCell", "background", "backgroundRef", "blurScope")
#: The sheet keys the panel maps onto the node's layout widgets.
SHEET_KEYS = ("layout", "columns", "aspect", "shortEdge")
#: Tick lists, filtered against the sheet's own vocabulary.
BUILD_KEYS = {"views": VIEW_KEYS, "poses": POSE_KEYS, "expressions": EXPRESSION_KEYS}

_BACKGROUND_LABEL = {option.key: option.label for option in BACKGROUNDS}
_SLUG = re.compile(r"[^a-z0-9]+")


def store_path() -> Path:
    """Where saved presets live (never raises; callers may create the parents)."""
    try:
        import folder_paths  # noqa: PLC0415 - ComfyUI is not importable in every context

        root = Path(folder_paths.get_user_directory()) / PROFILE_DIRNAME
    except Exception:  # noqa: BLE001 - no folder_paths (tests, standalone import)
        root = Path.home() / ".comfyui-user" / PROFILE_DIRNAME
    return root / STORE_DIRNAME / STORE_FILENAME


# --------------------------------------------------------------------------- #
# reading and writing
# --------------------------------------------------------------------------- #
def _read_records() -> list[dict[str, Any]]:
    """The stored records, or ``[]`` when there are none / they are unreadable."""
    path = store_path()
    try:
        raw = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - missing, unreadable or invalid JSON = no presets
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("presets"), list):
        return [item for item in raw["presets"] if isinstance(item, dict)]
    return []


def _write_records(records: Iterable[Mapping[str, Any]]) -> None:
    """Write the store atomically (a half-written file would lose every preset)."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "presets": [dict(record) for record in records]}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2))
    temporary.replace(path)


def saved_presets() -> list[SheetPreset]:
    """The saved presets as ``SheetPreset`` objects (broken records skipped, not raised)."""
    presets: list[SheetPreset] = []
    for record in _read_records():
        preset = _preset_from_record(record)
        if preset is not None:
            presets.append(preset)
    return presets


def _preset_from_record(record: Mapping[str, Any]) -> SheetPreset | None:
    preset_id = str(record.get("id") or "").strip().lower()
    if not preset_id:
        return None
    name = str(record.get("name") or record.get("label") or "").strip()
    render = _scalars(record.get("render"), RENDER_KEYS)
    widgets = _scalars(record.get("widgets"))
    deviates = record.get("deviates")
    return SheetPreset(
        id=preset_id,
        label=name or preset_id,
        hint=str(record.get("hint") or "").strip() or "Saved from this node.",
        render=render,
        sheet=_scalars(record.get("sheet"), SHEET_KEYS),
        widgets=widgets,
        build=_ticks(record.get("build")),
        deviates=tuple(str(item) for item in deviates) if isinstance(deviates, list) else (),
        custom=True,
    )


def _scalars(raw: Any, allowed: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Keep the JSON scalars of a mapping (drop lists, dicts, ``None`` and NaN).

    A hand-written request must not be able to put a structure into the store that the
    panel would then render as ``[object Object]``, and an absent value must not be turned
    into a zero by a "helpful" cast.
    """
    if not isinstance(raw, Mapping):
        return {}
    keep: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        if allowed is not None and name not in allowed:
            continue
        if isinstance(value, bool) or isinstance(value, (int, str)):
            keep[name] = value
        elif isinstance(value, float):
            if value == value and value not in (float("inf"), float("-inf")):  # NaN/inf guard
                keep[name] = value
    return keep


def _ticks(raw: Any) -> dict[str, list[str]]:
    """The tick lists, filtered against the sheet's own views / poses / expressions."""
    if not isinstance(raw, Mapping):
        return {}
    ticks: dict[str, list[str]] = {}
    for key, vocabulary in BUILD_KEYS.items():
        values = raw.get(key)
        if not isinstance(values, (list, tuple)):
            continue
        kept: list[str] = []
        for value in values:
            text = str(value).strip().lower()
            if text in vocabulary and text not in kept:
                kept.append(text)
        if kept:
            ticks[key] = kept
    return ticks


# --------------------------------------------------------------------------- #
# the defaults a saved preset departs from
# --------------------------------------------------------------------------- #
def schema_defaults() -> dict[str, Any]:
    """The node's own widget defaults, or ``{}`` when the schema is not readable.

    Read live (``knobs.knob_list`` reads the node's schema) so a saved preset's "Changes:"
    line cannot drift from the node it will be applied to. Every failure - not inside
    ComfyUI, a renamed widget, a schema that moved - means "unknown", not a wrong answer.
    """
    try:
        from . import knobs  # noqa: PLC0415 - imports the node, which needs ComfyUI

        return {
            str(entry["name"]): entry.get("default")
            for entry in knobs.knob_list()
            if entry.get("name")
        }
    except Exception:  # noqa: BLE001 - a missing schema is not an error here
        return {}


def deviates_for(widgets: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Which of ``widgets`` differ from a fresh node (the order the panel lists them in)."""
    table = schema_defaults() if defaults is None else defaults
    names: list[str] = []
    for name, value in widgets.items():
        if name not in table:
            continue
        default = table[name]
        if default is None or value == default:
            continue
        names.append(str(name))
    return tuple(names)


# --------------------------------------------------------------------------- #
# saving and deleting
# --------------------------------------------------------------------------- #
def _slug(name: str) -> str:
    slug = _SLUG.sub("-", name.strip().lower()).strip("-")
    return slug[:32] or "preset"


def _unique_id(name: str, taken: set[str]) -> str:
    base = f"{CUSTOM_PREFIX}{_slug(name)}"
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base}-{int(time.time())}"


def _hint_for(widgets: Mapping[str, Any], render: Mapping[str, Any]) -> str:
    """A one-line description of what was saved, written by the code that knows the fields."""
    bits: list[str] = []
    size = widgets.get("cell_size")
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        bits.append(f"{int(size)}px cells")
    frames = widgets.get("frames_per_cell", render.get("framesPerCell"))
    if isinstance(frames, (int, float)) and not isinstance(frames, bool):
        bits.append(f"{int(frames)} frames")
    steps = widgets.get("steps")
    if isinstance(steps, (int, float)) and not isinstance(steps, bool):
        bits.append(f"{int(steps)} steps")
    backdrop = str(render.get("background") or "").strip()
    if backdrop:
        bits.append(f"{_BACKGROUND_LABEL.get(backdrop, backdrop).lower()} backdrop")
    if not bits:
        return "Saved from this node."
    return "Saved from this node: " + ", ".join(bits) + "."


def save_preset(body: Any) -> dict[str, Any]:
    """Store the settings in ``body`` as a new preset; returns a small result dict.

    ``body`` is what the panel sends: a name plus the ``render`` / ``sheet`` / ``widgets`` /
    ``build`` groups. Anything unrecognised is dropped rather than refused - the panel is
    allowed to send a newer shape than this file knows about.
    """
    if not isinstance(body, Mapping):
        return {"ok": False, "reason": "a preset has to be a JSON object."}
    name = " ".join(str(body.get("name") or "").split())[:MAX_NAME_LENGTH]
    if not name:
        return {"ok": False, "reason": "give the preset a name."}

    records = _read_records()
    if len(records) >= MAX_PRESETS:
        return {
            "ok": False,
            "reason": f"you already have {MAX_PRESETS} saved presets - delete one first.",
        }

    widgets = _scalars(body.get("widgets"))
    render = _scalars(body.get("render"), RENDER_KEYS)
    sheet = _scalars(body.get("sheet"), SHEET_KEYS)
    build = _ticks(body.get("build"))
    record = {
        "id": _unique_id(name, {str(item.get("id") or "").lower() for item in records}),
        "name": name,
        "label": name,
        "hint": str(body.get("hint") or "").strip() or _hint_for(widgets, render),
        "render": render,
        "sheet": sheet,
        "widgets": widgets,
        "build": build,
        "deviates": list(deviates_for(widgets)),
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        _write_records([*records, record])
    except Exception as exc:  # noqa: BLE001 - a failed write is a message, not a crash
        return {"ok": False, "reason": f"could not write {store_path()}: {exc}"}
    preset = _preset_from_record(record)
    return {
        "ok": True,
        "preset": preset.to_dict() if preset is not None else {},
        "count": len(records) + 1,
    }


def delete_preset(preset_id: Any) -> dict[str, Any]:
    """Remove one saved preset; built-ins are refused with a reason."""
    key = str(preset_id or "").strip().lower()
    if not key:
        return {"ok": False, "reason": "no preset id given."}
    from .presets import PRESETS  # noqa: PLC0415 - presets imports this module lazily

    builtin = next((preset for preset in PRESETS if preset.id == key), None)
    if builtin is not None:
        return {"ok": False, "reason": f"{builtin.label!r} is a built-in preset and cannot be deleted."}

    records = _read_records()
    kept = [record for record in records if str(record.get("id") or "").strip().lower() != key]
    if len(kept) == len(records):
        return {"ok": False, "reason": f"no saved preset with the id {key!r}."}
    try:
        _write_records(kept)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"could not write {store_path()}: {exc}"}
    return {"ok": True, "removed": key, "count": len(kept)}


__all__ = [
    "CUSTOM_PREFIX",
    "MAX_NAME_LENGTH",
    "MAX_PRESETS",
    "delete_preset",
    "deviates_for",
    "save_preset",
    "saved_presets",
    "schema_defaults",
    "store_path",
]
