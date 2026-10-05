# ComfyUI-H3-Character-Sheet - recommended settings, as data.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Presets, as data: a LAYOUT axis, a QUALITY axis, and the resolution control between them.

A character sheet is three decisions, and they used to be crammed into one dropdown:

* **what to draw** - the cells, their arrangement, the cell shape. That is a *layout* preset:
  the hero-plus-four finished sheet, a 2x3 expression board, a turnaround strip.
* **how big** - the sheet canvas and the cell render size. That is the *resolution control*
  (``resolution_list`` → three chips in the panel), and it is paired: one choice sets both
  sizes, and no preset touches them.
* **how to sample it** - the mode (one render for the whole sheet, or one per cell), steps,
  reference sizing, scope, continuation, clip export. That is a *quality* preset.

Splitting them is not tidiness for its own sake: a single preset that moved the sizes could
silently undo a deliberate 4K choice, and one that moved the layout could not be combined with
a different fidelity. With the axes separate, "the expression board, at 1440p, per-cell because
the eyes matter" is three clicks, and each one says only what it changes.

So the presets live here - in Python, as data - and the panel asks for them over the action
route instead of carrying its own copy. Consequences worth stating:

* every preset is testable without a browser (``tests/test_presets.py`` parses each one through
  the real spec parser and checks each widget name against the node's schema),
* the panel can only offer what the backend actually knows,
* a saved workflow records the presets it was built from (``render.preset`` for the quality,
  ``render.layoutPreset`` for the layout), so a sheet can say where its numbers came from,
* a preset that deliberately differs from the node's own defaults has to declare it
  (``deviates``), so "recommended" can never quietly move a setting.

A preset is a starting point, not a lock: applying one writes the values, and editing a knob
afterwards just makes it yours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .sheet_spec import DEFAULT_STEPS, RESOLUTION_CHOICES

#: The quality preset a fresh node behaves like (the pack's own defaults, spelled out).
DEFAULT_PRESET_ID = "balanced"

#: The layout a fresh node behaves like: the five-cell finished sheet.
DEFAULT_LAYOUT_ID = "hero-4"


@dataclass(frozen=True)
class SheetPreset:
    """One recommended configuration of one axis of the node."""

    id: str
    label: str
    hint: str
    #: ``"layout"``, ``"quality"`` or ``"suite"``. The panel draws one selector per kind, because
    #: they are separate decisions: a layout says WHAT to draw (cells, arrangement, cell shape), a
    #: quality says HOW to sample it (mode, steps, reference sizing, continuation), and a suite
    #: says DO ALL OF THESE, each as its own sheet. Neither a layout nor a quality touches the
    #: sizes - the resolution control owns those.
    kind: str = "quality"
    #: Suite only: the layout presets it renders, in order, each into its own sheet folder. A
    #: suite is one queue producing several sheets (see ``suite.py``), which is what a RefMod
    #: bundle wants: the more views it carries, the more the reference actually steers.
    boards: tuple[str, ...] = ()
    #: payload ``render.*`` keys (continuation, clip export, frames per cell...)
    render: dict[str, Any] = field(default_factory=dict)
    #: payload ``sheet.*`` keys (layout)
    sheet: dict[str, Any] = field(default_factory=dict)
    #: node widget name -> value, applied to the node itself (frames, steps, layout, ...)
    widgets: dict[str, Any] = field(default_factory=dict)
    #: Optional tick selection: the cells this preset is FOR. Applying it does not touch an
    #: existing cell list beyond building from these ticks - the panel shows the ticks, and
    #: building is the user's call.
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
            "kind": self.kind,
            "boards": list(self.boards),
            "render": dict(self.render),
            "sheet": dict(self.sheet),
            "widgets": dict(self.widgets),
            "build": {key: list(value) for key, value in self.build.items()},
            "deviates": list(self.deviates),
            "custom": bool(self.custom),
        }


# --------------------------------------------------------------------------- #
# the two axes
# --------------------------------------------------------------------------- #
#: Render settings every quality preset starts from: the knobs that decide HOW a sheet is sampled.
#: Deliberately no sizes and no layout - the resolution control owns the two sizes (see
#: :func:`resolution_list`) and the layout presets own the cells and the arrangement, so no preset
#: can quietly move a size the user picked, or re-lay a layout they chose.
_BASE_WIDGETS: dict[str, Any] = {
    "frames_per_cell": 22,
    "steps": DEFAULT_STEPS,
    "sampler_name": "res_multistep",
    "scheduler": "simple",
    "ref_image_size": "match",
    "ref_scope": "per framing",
    "continuity": "off",
    "export_video": True,
    # The render mode, stated rather than implied: a preset that left it out would not turn the
    # per-cell pass back off, so applying a quality preset after "Per-cell renders" would keep
    # rendering every cell.
    "single_pass": True,
}

#: What every layout preset starts from, then overrides: the sheet's arrangement and cell shape.
_LAYOUT_WIDGETS: dict[str, Any] = {
    "sheet_layout": "hero-left",
    "sheet_columns": 2,
    "sheet_aspect": "3:2",
    "sheet_captions": True,
    "sheet_background": "#101014",
    "sheet_fit": "contain",
    "cell_aspect": "3:4",
}

#: The five cells a "full character sheet" is made of: a headshot, a chest-up portrait, the full
#: body from the front, the 90-degree side and from behind - neutral expression, neutral pose. Read
#: from the front to the back, so the sheet works as a turnaround.
_FULL_SHEET_VIEWS = ("face", "portrait", "front", "profile", "back")

#: The expression board's six faces. All six are already in the pack's vocabulary (see
#: ``sheet_spec.EXPRESSIONS``), and six identical framings are what makes the board comparable.
_EXPRESSION_FACES = ("neutral", "closed-eyes", "smile", "anger", "crying", "pleasure")

#: One line of guidance per resolution, for the chips' tooltips. MODELLED from the pack's own
#: numbers rather than measured on every card: the fixed cost is the int8 DiT plus the nvfp4 text
#: encoder (~15-16 GB resident), and activations scale with latent tokens ~ (w/32)(h/32) x latent
#: frames. The README carries the same table with the plan for measuring it properly.
_RESOLUTION_HINTS: dict[str, str] = {
    "1080p": "a 3:2 sheet renders 1632x1088 (~1.8 MP, ~3.5k tokens): the tier a 16 GB card wants",
    "1440p": "a 3:2 sheet renders 2160x1440 (~3.1 MP, ~6k tokens): comfortable at 24 GB",
    "4k": "a 3:2 sheet renders 3264x2176 (~7.1 MP, ~14k tokens): the 32 GB tier - and still "
          "cheaper than ONE 2048px cell rendered at 22 frames (~18k)",
}


#: The RefMod suite's boards, in the order they render. Each one is a layout preset, so the suite
#: cannot drift from the boards the panel offers on their own: adding a board here is the whole
#: change, and a test checks every id names a real layout preset.
SUITE_BOARD_IDS: tuple[str, ...] = (
    DEFAULT_LAYOUT_ID,     # hero + 4: the sheet everything else is read against
    "expressions-6",       # the expression board
    "details-sfw",         # the SFW detail crops
    "details-nsfw",        # the explicit detail crops, in their own sheet
)


PRESETS: tuple[SheetPreset, ...] = (
    # ---------------------------------------------------------------- quality
    SheetPreset(
        id=DEFAULT_PRESET_ID,
        kind="quality",
        label="One-pass sheet (default)",
        hint=(
            "The recommendation IS the node's own default: one H3 render for the whole sheet, "
            "8 steps (the turbo checkpoints' 6-8 range for res_multistep/simple), references "
            "restricted to what each framing can show, and the panels sliced back out so per-view "
            "consumers work. The sizes come from the resolution buttons and the cells from a "
            "layout."
        ),
        render={"continuity": "off", "exportVideo": True, "framesPerCell": 22,
                "singlePass": True},
        widgets=dict(_BASE_WIDGETS),
        deviates=(),
    ),
    SheetPreset(
        id="per-cell",
        kind="quality",
        label="Per-cell renders (classic)",
        hint=(
            "ONE RENDER PER CELL - the path to take when a panel has to be exactly right. Every "
            "cell is its own H3 render, so its framing is the framing you asked for, and each one "
            "keeps its frames (the picker), its clip and its audio. Pair it with a turnaround "
            "layout to get the chained turn: latent continuation then carries the light and the "
            "head position while only the expression or the angle changes."
        ),
        render={"continuity": "auto", "exportVideo": True, "framesPerCell": 22,
                "singlePass": False},
        widgets={**_BASE_WIDGETS, "single_pass": False, "continuity": "auto"},
        deviates=("single_pass", "continuity"),
    ),
    SheetPreset(
        id="identity",
        kind="quality",
        label="Max identity fidelity",
        hint=(
            "The 2048px reference pipeline (several times slower) with independent cells: for "
            "when the likeness is the whole point. Same 8 steps - the likeness comes from the "
            "reference, not from more sampling - and per-cell, because that pipeline only pays "
            "off on a render that is about one panel."
        ),
        render={"continuity": "off", "exportVideo": True, "framesPerCell": 22,
                "singlePass": False},
        widgets={**_BASE_WIDGETS, "single_pass": False, "ref_image_size": "max"},
        deviates=("single_pass", "ref_image_size"),
    ),
    # ----------------------------------------------------------------- layout
    SheetPreset(
        id=DEFAULT_LAYOUT_ID,
        kind="layout",
        label="Hero + 4 panels (5 cells)",
        hint=(
            "The finished article: a headshot, a chest-up portrait, the full body from the front, "
            "the 90-degree side and from behind - neutral expression and pose - with the headshot "
            "as a tall hero panel on the left and the other four in a 2x2 block beside it, on the "
            "pack's flat neutral tan backdrop."
        ),
        # The backdrop is part of the look this layout is known for; the cells are the layout.
        render={"background": "tan"},
        # Both languages, on purpose: ``widgets`` is what the node's canvas reads, ``sheet`` is
        # what the payload says - and a headless run only ever sees the second one.
        sheet={"layout": "hero-left", "columns": 2, "aspect": "3:2"},
        widgets=dict(_LAYOUT_WIDGETS),
        build={"views": list(_FULL_SHEET_VIEWS), "poses": ["neutral"], "expressions": ["neutral"]},
        deviates=(),
    ),
    SheetPreset(
        id="expressions-6",
        kind="layout",
        label="Expressions 2x3 (6 cells)",
        hint=(
            "Six face close-ups in a 2x3 grid: neutral, eyes closed, smile, anger, crying and "
            "pleasure - the same framing every time, so the sheet compares expressions rather "
            "than angles. Square cells on a 3:2 sheet."
        ),
        sheet={"layout": "grid", "columns": 3, "aspect": "3:2"},
        widgets={
            **_LAYOUT_WIDGETS, "sheet_layout": "grid", "sheet_columns": 3, "cell_aspect": "1:1",
        },
        build={"views": ["face"], "poses": ["neutral"], "expressions": list(_EXPRESSION_FACES)},
        deviates=("sheet_layout", "sheet_columns", "cell_aspect"),
    ),
    SheetPreset(
        id="turnaround-3",
        kind="layout",
        label="Turnaround (3 in a row)",
        hint=(
            "Front, 90-degree side and back in one row on an ultrawide canvas: the classic "
            "turnaround strip. Pair it with the per-cell quality preset to chain the turn, or "
            "leave the one-pass default for the cheapest read of the same strip."
        ),
        sheet={"layout": "turnaround", "columns": 3, "aspect": "21:9"},
        widgets={
            **_LAYOUT_WIDGETS,
            "sheet_layout": "turnaround",
            "sheet_columns": 3,
            "sheet_aspect": "21:9",
        },
        build={"views": ["front", "profile", "back"], "poses": ["neutral"], "expressions": []},
        deviates=("sheet_layout", "sheet_columns", "sheet_aspect"),
    ),
    # The detail boards: what a full-body sheet cannot show, in the 2x2 grid a RefMod bundle
    # wants. SFW and NSFW are separate presets on purpose - the bundle is built from the cells,
    # so mixing them would put explicit crops in the same bundle as the eyes and the hands.
    SheetPreset(
        id="details-sfw",
        kind="layout",
        label="Closeups 2x2 (SFW)",
        hint=(
            "Four detail crops in a 2x2 grid: the eyes, the mouth, the hands and the feet - "
            "the cells a sheet is usually missing, because a full-body view cannot show a nail "
            "or a shoe."
        ),
        sheet={"layout": "grid", "columns": 2, "aspect": "3:2"},
        widgets={
            **_LAYOUT_WIDGETS, "sheet_layout": "grid", "sheet_columns": 2, "cell_aspect": "1:1",
        },
        build={"views": ["eyes", "mouth", "hands", "feet"], "poses": [], "expressions": ["neutral"]},
        deviates=("sheet_layout", "cell_aspect"),
    ),
    SheetPreset(
        id="details-nsfw",
        kind="layout",
        label="Closeups 2x2 (NSFW)",
        hint=(
            "The same board for the explicit detail a character sheet also documents: the "
            "breasts, the groin, the butt from behind, and the mouth with the ahego expression "
            "(eyes rolled up, tongue out). The ahego cell is the mouth view plus that "
            "expression, so it is one cell rather than a view of its own."
        ),
        sheet={"layout": "grid", "columns": 2, "aspect": "3:2"},
        widgets={
            **_LAYOUT_WIDGETS, "sheet_layout": "grid", "sheet_columns": 2, "cell_aspect": "1:1",
        },
        build={
            "views": ["breasts", "groin", "butt", "mouth"],
            "poses": [],
            "expressions": ["ahego"],
        },
        deviates=("sheet_layout", "cell_aspect"),
    ),
    # ------------------------------------------------------------------ suite
    SheetPreset(
        id="refmod-suite",
        kind="suite",
        label="RefMod suite (4 sheets)",
        hint=(
            "Four sheets from one queue - a hero + 4 panel sheet, the 2x3 expression board, the "
            "SFW detail crops and the NSFW ones - each rendered into its own folder and, with "
            "the H3 Sheet -> RefMod node wired to the suite, exported as ONE bundle whose "
            "members are named per board. This is the configuration a character wants to "
            "condition a render: the more views a bundle carries, the more the reference "
            "actually steers, and the explicit board stays identifiable in the list rather than "
            "folded into an anonymous stack."
        ),
        boards=SUITE_BOARD_IDS,
        # A suite never moves the sampling or the sizes; those stay on their own axes. What it does
        # state is the mode: four sheets as four one-pass renders. Inheriting the node's current
        # mode would mean a user who had turned one-pass off gets 19 per-cell renders from a preset
        # that promises four sheets.
        render={"singlePass": True},
        deviates=(),
    ),
)

_PRESET_BY_ID = {preset.id: preset for preset in PRESETS}

#: Selector order, and the labels the panel puts above the two dropdowns.
PRESET_KINDS: tuple[tuple[str, str], ...] = (
    ("layout", "Layout"),
    ("quality", "Quality"),
    ("suite", "Suite"),
)


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


def presets_by_kind(kind: Any) -> tuple[SheetPreset, ...]:
    """The built-ins of one axis, in the order the panel offers them."""
    wanted = str(kind or "").strip().lower()
    return tuple(preset for preset in all_presets() if preset.kind == wanted)


def suite_preset() -> SheetPreset | None:
    """The suite preset, when the pack ships one (``None`` is a valid answer)."""
    suites = presets_by_kind("suite")
    return suites[0] if suites else None


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
    """The presets as plain data, for the panel (each carries its ``kind``)."""
    return [preset.to_dict() for preset in all_presets()]


def resolution_list() -> list[dict[str, Any]]:
    """The resolution control's choices, for the panel's chips.

    One entry per choice, with BOTH sizes it writes and the guidance for its tooltip. The table
    itself is ``sheet_spec.RESOLUTION_CHOICES`` - the same one the payload's ``resolution`` flag is
    validated against and the one the one-pass render reads - so the chips, the node and the
    report can never disagree about what "1440p" means.
    """
    return [
        {
            "key": key,
            "label": label,
            "sheetShortEdge": short_edge,
            "cellShortEdge": cell_size,
            "hint": _RESOLUTION_HINTS.get(key, ""),
        }
        for key, label, short_edge, cell_size in RESOLUTION_CHOICES
    ]


def apply_to_payload(payload: dict[str, Any], preset_id: Any) -> dict[str, Any]:
    """Merge a preset into a panel payload: ``render``/``sheet`` keys plus its ticks.

    The payload is the panel's own contract, so applying a preset here and applying it in
    the panel have to agree - this is the copy the tests exercise, and the panel applies the
    same three groups (``render``, ``sheet``, ``widgets``). The record of WHICH preset was
    applied lands on the axis it belongs to (``render.preset`` / ``render.layoutPreset``).
    """
    preset = preset_by_id(preset_id)
    if preset is None:
        return dict(payload)
    merged = dict(payload)
    render = dict(merged.get("render") or {})
    render.update(preset.render)
    if preset.boards:
        # A suite is written as the board list it renders, in order: the node expands those into
        # separate sheets, so the payload carries the same data the preset does.
        render["suite"] = list(preset.boards)
    elif preset.kind == "layout":
        # The suite rides the layout axis (it decides WHICH sheets render), so picking one layout
        # after a suite means one sheet again - leaving the boards set would silently ignore the
        # layout the user just chose. A quality preset says how, not what, and leaves it alone.
        render["suite"] = []
    render["layoutPreset" if preset.kind in ("layout", "suite") else "preset"] = preset.id
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
    "DEFAULT_LAYOUT_ID",
    "DEFAULT_PRESET_ID",
    "PRESETS",
    "PRESET_KINDS",
    "SUITE_BOARD_IDS",
    "SheetPreset",
    "all_presets",
    "apply_to_payload",
    "preset_by_id",
    "preset_list",
    "presets_by_kind",
    "resolution_list",
    "user_presets",
]
