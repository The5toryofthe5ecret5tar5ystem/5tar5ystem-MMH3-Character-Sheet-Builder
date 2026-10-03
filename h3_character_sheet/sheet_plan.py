# ComfyUI-H3-Character-Sheet - what the node will actually render.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Deciding the cells for a run, without touching ComfyUI.

A sheet payload arrives from the panel (or from an old workflow, or from someone's
script) and has to answer one question before anything is sampled: **which cells
am I rendering?** That decision lives here, in pure Python, because getting it wrong
is expensive - a two-view request once turned into eight renders and 176 frames
because an empty cell list quietly meant the curated matrix.

Resolution order:

1. an explicit ``cells`` list wins, always;
2. otherwise the panel's ticks (``build``) say what was wanted, so render exactly
   those - it is the same expansion the panel's *Build cells* button makes;
3. only with neither does the curated 8-view matrix run, and the run says so.
"""

from __future__ import annotations

from typing import Any

from .planner import cells_from_build, default_cells
from .sheet_spec import SheetCell

#: Notice keys so the node, the report and the panel all phrase this the same way.
NO_CELLS_TICKS = "sheet_data had no cell list"
NO_CELLS_MATRIX = "no cells and no view ticks"


def payload_cells(payload: dict[str, Any]) -> list[Any]:
    """The explicit cell list in a payload (junk entries dropped)."""
    cells = payload.get("cells")
    return [cell for cell in cells if isinstance(cell, dict)] if isinstance(cells, list) else []


def plan_payload(
    payload: dict[str, Any],
    *,
    frames_per_cell: int | None = None,
) -> dict[str, Any]:
    """Resolve a panel payload into the payload the node will run.

    Mutates and returns ``payload``: cells are filled in from the ticks when the
    panel had none, and every substitution is announced through ``warnings`` so the
    report explains a run that did not match anyone's memory of the node.
    """
    if frames_per_cell is not None:
        render = payload.get("render") if isinstance(payload.get("render"), dict) else {}
        render.setdefault("framesPerCell", int(frames_per_cell))
        payload["render"] = render

    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        payload["warnings"] = warnings

    if payload_cells(payload):
        return payload

    built = cells_from_build(payload.get("build"))
    if built:
        payload["cells"] = built
        warnings.append(f"{NO_CELLS_TICKS} - built the {len(built)} cell(s) the panel ticks asked for{_describe(payload.get('build'))}")
        return payload

    payload["cells"] = default_cells()
    warnings.append(
        f"{NO_CELLS_MATRIX} - using the default 8-view matrix "
        "(face, face+smile, portrait, front, A-pose, T-pose, profile, back)"
    )
    return payload


def _describe(build: Any) -> str:
    """``(views: face, front · poses: neutral)`` - the ticks that made the cells."""
    if not isinstance(build, dict):
        return ""
    parts: list[str] = []
    for key in ("views", "poses", "expressions"):
        values = build.get(key)
        if isinstance(values, (list, tuple)) and values:
            parts.append(f"{key}: " + ", ".join(str(value) for value in values))
    return " (" + " · ".join(parts) + ")" if parts else ""


def drop_empty_payload_warning(warnings: list[str]) -> list[str]:
    """The parser's "no cells" warning is noise once cells have been built."""
    return [warning for warning in warnings if not warning.startswith("No cells in the payload")]


def matrix_cells() -> list[SheetCell]:
    """The curated matrix as parsed cells (last resort, and what the panel offers)."""
    return [SheetCell(**cell) for cell in default_cells()]


__all__ = [
    "NO_CELLS_MATRIX",
    "NO_CELLS_TICKS",
    "drop_empty_payload_warning",
    "matrix_cells",
    "payload_cells",
    "plan_payload",
]
