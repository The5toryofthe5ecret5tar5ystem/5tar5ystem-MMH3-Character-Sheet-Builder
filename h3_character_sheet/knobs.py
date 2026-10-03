# ComfyUI-H3-Character-Sheet - the node's knobs, as data for the panel.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The node's own widgets, described for the panel's compact settings grid.

The node has 23 knobs and the frontend lays a native widget out one per row, full width:
there is no column-span API (`computeLayoutSize` only lets a widget claim its own space), so
a 1000px-wide node spends ~500px of height on rows that the panel could show in three
columns. The supported way to change that is to draw the knobs in our own DOM widget - which
is what this module feeds.

Two rules keep it honest:

* **the schema is the source of truth.** ``knob_list()`` reads the node's live schema, so
  min/max/step/options/default can never drift from what the node actually accepts; only the
  short *label*, the *group* and the optional column *span* are written here, because the
  schema has tooltips but no short names;
* **every knob is covered.** A test compares this table against the schema in both
  directions: a new widget without a label fails, and a stale label for a removed widget
  fails too. ``sheet_data`` is excluded on purpose - the panel owns it and it stays hidden.

The panel writes these values back through the node's own widgets (see ``applyWidgets`` in
``web/js/h3sheet_ui.js``), so hiding the native rows changes nothing about the render: the
values, their order in ``widgets_values`` and the prompt inputs are the same.
"""

from __future__ import annotations

from typing import Any

#: Columns the panel's knob grid uses. A row may fill fewer - see ``row`` below.
KNOB_COLUMNS = 3

#: Knobs the panel draws itself. ``label`` is what a person calls it, ``group`` is the
#: section it belongs to, ``row`` is which line of that section it sits on, and ``span`` is
#: how many of the grid's columns it takes (1 by default, 2 for a long text field).
#:
#: The row is declared rather than left to the grid: a flowing grid puts a knob wherever the
#: previous ones happen to end, which is how *Seed* and its *Seed mode* ended up diagonally
#: apart. Knobs that are one decision (size / shape / frames, sampler / scheduler / steps,
#: the seed and its mode, the two shifts) share a row, and a row's spans have to fit the
#: grid - both are enforced by ``tests/test_knobs.py``.
#:
#: Order here is the order in the panel: rows top to bottom, left to right within a row.
KNOB_LAYOUT: tuple[dict[str, Any], ...] = (
    # What comes out, and whether the takes are kept.
    {"name": "output_name", "label": "Sheet name", "group": "Output", "span": 2, "row": 0},
    {"name": "keep_frames", "label": "Keep frames", "group": "Output", "row": 0},
    # One cell: how big, what shape, how long.
    {"name": "cell_size", "label": "Cell size", "group": "Render", "row": 0,
     "hint": "short edge of one cell"},
    {"name": "cell_aspect", "label": "Cell shape", "group": "Render", "row": 0},
    {"name": "frames_per_cell", "label": "Frames", "group": "Render", "row": 0,
     "hint": "H3 samples 5, 22, 39..."},
    # How it is sampled.
    {"name": "steps", "label": "Steps", "group": "Render", "row": 1},
    {"name": "sampler_name", "label": "Sampler", "group": "Render", "row": 1},
    {"name": "scheduler", "label": "Scheduler", "group": "Render", "row": 1},
    # Which noise, and what the seed does after each render: one decision, one row.
    {"name": "seed", "label": "Seed", "group": "Render", "row": 2},
    # Flow shift, one per stream.
    {"name": "shift_video", "label": "Shift video", "group": "Render", "row": 3},
    {"name": "shift_audio", "label": "Shift audio", "group": "Render", "row": 3},
    # How the references are fed in.
    {"name": "ref_image_size", "label": "Reference size", "group": "References", "row": 0,
     "hint": "'max' = the 2048px pipeline, several times slower"},
    {"name": "ref_scope", "label": "Reference scope", "group": "References", "row": 0},
    # The sheet itself: arrangement, then resolution, then its backdrop.
    {"name": "sheet_layout", "label": "Layout", "group": "Sheet", "row": 0},
    {"name": "sheet_columns", "label": "Columns", "group": "Sheet", "row": 0},
    {"name": "sheet_aspect", "label": "Sheet aspect", "group": "Sheet", "row": 0},
    {"name": "sheet_short_edge", "label": "Sheet size", "group": "Sheet", "row": 1},
    {"name": "sheet_fit", "label": "Fit", "group": "Sheet", "row": 1},
    {"name": "sheet_captions", "label": "Captions", "group": "Sheet", "row": 1},
    {"name": "sheet_background", "label": "Background", "group": "Sheet", "span": 2, "row": 2},
    # Per-cell extras.
    {"name": "continuity", "label": "Continuation", "group": "Cells", "row": 0},
    {"name": "export_video", "label": "Export clips", "group": "Cells", "row": 0},
    {"name": "verbose_logging", "label": "Verbose log", "group": "Debug", "row": 0},
)

#: Section order in the panel.
KNOB_GROUPS: tuple[str, ...] = ("Output", "Render", "References", "Sheet", "Cells", "Debug")

#: Widgets the BROWSER adds to a node - not in ``INPUT_TYPES``, so not in the schema.
#:
#: ``control_after_generate`` is the seed row's mode: the frontend creates it next to a
#: seed widget and uses it after queueing (it is ``serialize: false``, so it never reaches
#: the prompt or ``widgets_values``). The panel draws it too, which is what lets the node
#: hide every row and still leave the user able to say "randomize the seed each render".
#: ``after`` puts it where it belongs in the reading order (right after the seed).
FRONTEND_KNOBS: tuple[dict[str, Any], ...] = (
    {
        "name": "control_after_generate",
        "label": "Seed mode",
        "group": "Render",
        "row": 2,
        "kind": "select",
        "options": ("fixed", "increment", "decrement", "randomize"),
        "default": "randomize",
        "span": 1,
        "after": "seed",
        "hint": "what the seed does after each render",
    },
)

#: Widgets that are NOT knobs: links, the payload the panel owns, and the panel itself.
SKIPPED_WIDGETS = frozenset({"sheet_data", "h3_character_sheet_ui"})

#: Types that are a socket, not a knob.
LINK_TYPES = frozenset({"MODEL", "CLIP", "VAE", "IMAGE", "VIDEO", "AUDIO", "LATENT", "MASK"})


def _schema_knobs() -> list[tuple[str, str, dict[str, Any]]]:
    """``[(name, type, meta)]`` for every non-link widget, straight from the node schema."""
    from .nodes.sheet import MiniMaxH3CharacterSheet

    # INPUT_TYPES is what the server itself serves as object_info, so the panel can never
    # offer a bound or a choice the node would reject.
    spec = MiniMaxH3CharacterSheet.INPUT_TYPES()
    out: list[tuple[str, str, dict[str, Any]]] = []
    for section in ("required", "optional"):
        for name, entry in (spec.get(section) or {}).items():
            if name in SKIPPED_WIDGETS:
                continue
            kind = entry[0]
            type_name = str(kind) if isinstance(kind, str) else "COMBO"
            if type_name.upper() in LINK_TYPES:
                continue
            meta = dict(entry[1]) if len(entry) > 1 and isinstance(entry[1], dict) else {}
            out.append((name, type_name, meta))
    return out


def knob_list() -> list[dict[str, Any]]:
    """The knobs the panel draws, with the node's own bounds and choices.

    "Schema order, minus the non-knobs, plus the panel metadata and the browser's own
    widgets (see ``FRONTEND_KNOBS``). Each entry is
    ``{name, label, group, kind, span, row, hint, default, min, max, step, options, frontend}``.
    """
    layout = {entry["name"]: entry for entry in KNOB_LAYOUT}
    knobs: list[dict[str, Any]] = []
    for name, type_name, meta in _schema_knobs():
        described = layout.get(name, {})
        knobs.append(_knob(name, type_name, meta, described, frontend=False))
    for described in FRONTEND_KNOBS:
        entry = _knob(
            str(described["name"]),
            "COMBO" if described.get("options") else "STRING",
            {key: described[key] for key in ("default", "options") if described.get(key) is not None},
            described,
            frontend=True,
        )
        anchor = str(described.get("after") or "")
        position = next((index + 1 for index, knob in enumerate(knobs) if knob["name"] == anchor), len(knobs))
        knobs.insert(position, entry)
    return knobs


def _knob(
    name: str,
    type_name: str,
    meta: dict[str, Any],
    described: dict[str, Any],
    *,
    frontend: bool,
) -> dict[str, Any]:
    """One panel entry: what the node says about the value, plus what a person calls it."""
    return {
        "name": name,
        "label": str(described.get("label") or name.replace("_", " ")),
        "group": str(described.get("group") or "Other"),
        "hint": str(described.get("hint") or ""),
        "span": int(described.get("span") or 1),
        "row": int(described.get("row") or 0),
        "kind": _kind_of(type_name),
        "default": meta.get("default"),
        "min": meta.get("min"),
        "max": meta.get("max"),
        "step": meta.get("step"),
        "options": [str(option) for option in (meta.get("options") or [])],
        "frontend": bool(frontend),
    }


def _kind_of(type_name: str) -> str:
    """What the panel should draw: ``number`` / ``select`` / ``toggle`` / ``text``."""
    text = str(type_name).upper()
    if "BOOLEAN" in text:
        return "toggle"
    if "INT" in text or "FLOAT" in text:
        return "number"
    if "COMBO" in text or text.startswith("["):
        return "select"
    return "text"


def knob_groups(knobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sections the panel shows, in order, each with the knobs it contains.

    The knobs of a group arrive in **row order**, which is the order ``KNOB_LAYOUT`` declares
    (falling back to the schema's own order for a knob nobody described). The panel draws them
    left to right, top to bottom, so the layout table - not the ``INPUT_TYPES`` order - is the
    one that decides what sits next to what.
    """
    declared = {
        entry["name"]: index
        for index, entry in enumerate((*KNOB_LAYOUT, *FRONTEND_KNOBS))
    }
    by_group: dict[str, list[dict[str, Any]]] = {}
    for knob in knobs:
        by_group.setdefault(knob["group"], []).append(knob)
    groups: list[dict[str, Any]] = []
    # Declared groups first (that is the reading order), then anything unexpected so a new
    # knob without a group is still reachable in the panel instead of silently invisible.
    for name in [*KNOB_GROUPS, *sorted(set(by_group) - set(KNOB_GROUPS))]:
        if name in by_group:
            entries = by_group.pop(name)
            # Undescribed knobs keep their schema position at the end of their row rather than
            # jumping to the front of the group.
            entries.sort(key=lambda knob: (int(knob.get("row") or 0), declared.get(knob["name"], len(declared))))
            groups.append({"group": name, "knobs": entries})
    return groups


__all__ = [
    "FRONTEND_KNOBS",
    "KNOB_COLUMNS",
    "KNOB_GROUPS",
    "KNOB_LAYOUT",
    "SKIPPED_WIDGETS",
    "knob_groups",
    "knob_list",
]
