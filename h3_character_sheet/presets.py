# ComfyUI-H3-Character-Sheet - recommended settings, as data.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Whole-node presets: the settings that make a sheet work, in one click.

A character sheet has a lot of knobs (cell size, frames, steps, reference sizing, scope,
continuation, clip export, layout, shape) and most of them interact: reference sizing and
step count are a speed/fidelity trade, `per framing` scope is what keeps a close-up from
borrowing another picture's face, 5-frame cells cannot continue, and continuation only pays
off where the camera distance matches. Leaving a user to find that combination by rendering
is how they end up with a sheet of duplicates at 5 frames or a 40-minute turnaround.

So the presets live here - in Python, as data - and the panel asks for them over the action
route instead of carrying its own copy. Three consequences worth stating:

* every preset is testable without a browser (`tests/test_presets.py` parses each one through
  the real spec parser and checks each widget name against the node's schema),
* the panel can only offer what the backend actually knows,
* a saved workflow records the preset it was built from (``render.preset``), so a sheet can
  say where its numbers came from.

A preset is a starting point, not a lock: applying one writes the values, and editing a knob
afterwards just makes it yours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .sheet_spec import DEFAULT_STEPS

#: The preset a fresh node behaves like (the pack's own defaults, spelled out).
DEFAULT_PRESET_ID = "balanced"


@dataclass(frozen=True)
class SheetPreset:
    """One recommended configuration of the whole node."""

    id: str
    label: str
    hint: str
    #: payload ``render.*`` keys (continuation, clip export, frames per cell...)
    render: dict[str, Any] = field(default_factory=dict)
    #: payload ``sheet.*`` keys (layout)
    sheet: dict[str, Any] = field(default_factory=dict)
    #: node widget name -> value, applied to the node itself (cell_size, steps, ...)
    widgets: dict[str, Any] = field(default_factory=dict)
    #: Optional tick selection: the cells this preset is FOR. Applying it does not touch an
    #: existing cell list - the panel shows the ticks, and building is the user's call.
    build: dict[str, list[str]] = field(default_factory=dict)
    #: Widgets where this preset DELIBERATELY differs from the node's own default. Declared
    #: rather than implied: "recommended" that quietly changes a default is how a user ends
    #: up with settings they never chose, and a test compares this set against the schema, so
    #: an undeclared deviation fails the suite instead of shipping.
    deviates: tuple[str, ...] = ()
    #: True for a preset the USER saved (see ``user_presets.py``): the pack cannot vouch for
    #: the settings, only for the shape, and the panel offers to delete those and only those.
    custom: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hint": self.hint,
            "render": dict(self.render),
            "sheet": dict(self.sheet),
            "widgets": dict(self.widgets),
            "build": {key: list(value) for key, value in self.build.items()},
            "deviates": list(self.deviates),
            "custom": bool(self.custom),
        }


#: The sheet the pack is tuned for. Everything else here is a deliberate trade of this one.
_BALANCED_WIDGETS: dict[str, Any] = {
    "cell_size": 1024,
    "frames_per_cell": 22,
    "steps": DEFAULT_STEPS,
    "sampler_name": "res_multistep",
    "scheduler": "simple",
    "ref_image_size": "match",
    "cell_aspect": "3:4",
    "ref_scope": "per framing",
    "continuity": "auto",
    "export_video": True,
    "sheet_layout": "hero-left",
    "sheet_columns": 2,
    "sheet_aspect": "3:2",
    "sheet_short_edge": 1536,
    "sheet_captions": True,
    "sheet_background": "#101014",
    "sheet_fit": "contain",
}

#: The five cells a "full character sheet" is made of: a headshot, a chest-up portrait, the
#: full body from the front, the 90-degree side and from behind - neutral expression, neutral
#: pose. Read from the front to the back, so the sheet works as a turnaround.
_FULL_SHEET_VIEWS = ("face", "portrait", "front", "profile", "back")

#: The sheet these two presets are: 5 cells, hero on the left, 3:2 canvas.
_FULL_SHEET_SHEET = {"layout": "hero-left", "columns": 2, "aspect": "3:2"}


def _full_sheet_widgets(*, cell_size: int, short_edge: int) -> dict[str, Any]:
    """The shared body of the two full-sheet presets, differing only in resolution."""
    return {
        **_BALANCED_WIDGETS,
        "cell_size": cell_size,
        "sheet_short_edge": short_edge,
    }


PRESETS: tuple[SheetPreset, ...] = (
    SheetPreset(
        id=DEFAULT_PRESET_ID,
        label="Balanced (recommended)",
        hint=(
            "What this pack is tuned for: 1024px cells, 22 frames, 8 steps (the turbo H3 "
            "checkpoints' 6-8 range for res_multistep/simple), references restricted to what "
            "each framing can show, cells chained only where the camera distance already "
            "matches, and each cell's clip exported."
        ),
        render={"continuity": "auto", "exportVideo": True, "framesPerCell": 22},
        sheet={"layout": "hero-left", "columns": 2, "aspect": "3:2", "shortEdge": 1536},
        widgets=dict(_BALANCED_WIDGETS),
        # The one deliberate departure: a fresh node renders cells independently (the safe
        # default), while the recommendation is to chain where the framing already matches.
        deviates=("continuity",),
    ),
    SheetPreset(
        id="full-balanced",
        label="Full Character Sheet - Balanced",
        hint=(
            "The finished article: headshot, chest-up portrait, full body front, full body "
            "90-degree side and from behind - neutral expression, neutral pose, on a flat "
            "neutral tan backdrop. 1024px cells on a 1536px sheet."
        ),
        render={
            "continuity": "auto",
            "exportVideo": True,
            "framesPerCell": 22,
            "background": "tan",
        },
        sheet={**_FULL_SHEET_SHEET, "shortEdge": 1536},
        widgets=_full_sheet_widgets(cell_size=1024, short_edge=1536),
        build={"views": list(_FULL_SHEET_VIEWS), "poses": ["neutral"], "expressions": ["neutral"]},
        deviates=("continuity",),
    ),
    SheetPreset(
        id="full-fidelity",
        label="Full Character Sheet - Fidelity",
        hint=(
            "The same five cells and the same neutral tan backdrop at print resolution: "
            "2048px cells on a 3840px sheet. Several times the render time of Balanced, and "
            "a very large PNG - worth it for a sheet that will be enlarged or cut out."
        ),
        render={
            "continuity": "auto",
            "exportVideo": True,
            "framesPerCell": 22,
            "background": "tan",
        },
        sheet={**_FULL_SHEET_SHEET, "shortEdge": 3840},
        widgets=_full_sheet_widgets(cell_size=2048, short_edge=3840),
        build={"views": list(_FULL_SHEET_VIEWS), "poses": ["neutral"], "expressions": ["neutral"]},
        deviates=("cell_size", "continuity", "sheet_short_edge"),
    ),
    SheetPreset(
        id="fast",
        label="Fast look (no chains, no clips)",
        hint=(
            "Planning pass: 768px cells at H3's 5-frame minimum, every cell independent, "
            "nothing encoded. 5 frames is too short to continue from, so continuation is "
            "off - use this to find the framing, not to keep the result."
        ),
        render={"continuity": "off", "exportVideo": False, "framesPerCell": 5},
        sheet={"layout": "grid", "columns": 4, "aspect": "16:9", "shortEdge": 1280},
        widgets={
            **_BALANCED_WIDGETS,
            "cell_size": 768,
            "frames_per_cell": 5,
            "cell_aspect": "1:1",
            "continuity": "off",
            "export_video": False,
            "sheet_layout": "grid",
            "sheet_columns": 4,
            "sheet_aspect": "16:9",
            "sheet_short_edge": 1280,
        },
        deviates=("cell_size", "frames_per_cell", "cell_aspect", "export_video",
                  "sheet_layout", "sheet_columns", "sheet_aspect", "sheet_short_edge"),
    ),
    SheetPreset(
        id="identity",
        label="Max identity fidelity",
        hint=(
            "The 2048px reference pipeline (several times slower per cell), 2048px cells on a "
            "3840px sheet, and independent cells: for when the likeness is the whole point. "
            "Same 8 steps - the likeness comes from the reference, not from more sampling."
        ),
        render={"continuity": "off", "exportVideo": True, "framesPerCell": 22},
        sheet={"layout": "hero-left", "columns": 2, "aspect": "3:2", "shortEdge": 3840},
        widgets={
            **_BALANCED_WIDGETS,
            "cell_size": 2048,
            "sheet_short_edge": 3840,
            "ref_image_size": "max",
            "continuity": "off",
        },
        deviates=("ref_image_size", "cell_size", "sheet_short_edge"),
    ),
    SheetPreset(
        id="turnaround",
        label="Turnaround (chained full body)",
        hint=(
            "Front -> profile -> back in one row. All three share a camera distance, so "
            "continuation holds the room, the light and the scale while the subject turns - "
            "watch the clips rather than the picked frames to judge it."
        ),
        render={"continuity": "auto", "exportVideo": True, "framesPerCell": 22},
        sheet={"layout": "turnaround", "columns": 3, "aspect": "21:9", "shortEdge": 2048},
        widgets={
            **_BALANCED_WIDGETS,
            "sheet_layout": "turnaround",
            "sheet_columns": 3,
            "sheet_aspect": "21:9",
            "sheet_short_edge": 2048,
        },
        build={"views": ["front", "profile", "back"], "poses": ["neutral"], "expressions": []},
        deviates=("continuity", "sheet_layout", "sheet_columns", "sheet_aspect",
                  "sheet_short_edge"),
    ),
    SheetPreset(
        id="expressions",
        label="Expression sheet (chained face)",
        hint=(
            "Five face close-ups in one row: identical framing, so the chain carries the "
            "light and the head position while only the expression changes - the case "
            "continuation is actually good at."
        ),
        render={"continuity": "auto", "exportVideo": True, "framesPerCell": 22},
        sheet={"layout": "turnaround", "columns": 5, "aspect": "21:9", "shortEdge": 2048},
        widgets={
            **_BALANCED_WIDGETS,
            "sheet_layout": "turnaround",
            "sheet_columns": 5,
            "sheet_aspect": "21:9",
            "sheet_short_edge": 2048,
        },
        build={
            "views": ["face"],
            "poses": ["neutral"],
            "expressions": ["neutral", "smile", "smirk", "frown", "surprised"],
        },
        deviates=("continuity", "sheet_layout", "sheet_columns",
                  "sheet_aspect", "sheet_short_edge"),
    ),
)

_PRESET_BY_ID = {preset.id: preset for preset in PRESETS}


def preset_by_id(preset_id: Any) -> SheetPreset | None:
    """Look a preset up by id (``None`` when it is unknown - never a guess).

    Built-ins first, then the user's own saved presets. A saved preset cannot shadow a
    built-in: the store hands out ``custom-...`` ids only.
    """
    key = str(preset_id or "").strip().lower()
    found = _PRESET_BY_ID.get(key)
    if found is not None:
        return found
    return next((preset for preset in user_presets() if preset.id == key), None)


def user_presets() -> tuple[SheetPreset, ...]:
    """The presets the user saved, as ``SheetPreset`` objects (never raises).

    Imported lazily: ``user_presets`` builds the same ``SheetPreset`` type this module
    defines, so a module-level import would be a cycle.
    """
    from . import user_presets as store  # noqa: PLC0415 - deliberate, see the docstring

    return tuple(store.saved_presets())


def all_presets() -> tuple[SheetPreset, ...]:
    """Built-ins, then the user's own - the order the panel offers them in."""
    return PRESETS + user_presets()


def preset_list() -> list[dict[str, Any]]:
    """The presets as plain data, for the panel."""
    return [preset.to_dict() for preset in all_presets()]


def apply_to_payload(payload: dict[str, Any], preset_id: Any) -> dict[str, Any]:
    """Merge a preset into a panel payload: ``render``/``sheet`` keys plus its ticks.

    The payload is the panel's own contract, so applying a preset here and applying it in
    the panel have to agree - this is the copy the tests exercise, and the panel applies the
    same three groups (``render``, ``sheet``, ``widgets``).
    """
    preset = preset_by_id(preset_id)
    if preset is None:
        return dict(payload)
    merged = dict(payload)
    render = dict(merged.get("render") or {})
    render.update(preset.render)
    render["preset"] = preset.id
    merged["render"] = render
    if preset.sheet:
        sheet = dict(merged.get("sheet") or {})
        sheet.update(preset.sheet)
        merged["sheet"] = sheet
    if preset.build:
        build = dict(merged.get("build") or {})
        for key, values in preset.build.items():
            if values:
                build[key] = list(values)
        merged["build"] = build
    return merged


__all__ = [
    "DEFAULT_PRESET_ID",
    "PRESETS",
    "SheetPreset",
    "all_presets",
    "apply_to_payload",
    "preset_by_id",
    "preset_list",
    "user_presets",
]
