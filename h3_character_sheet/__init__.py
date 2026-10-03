# ComfyUI-H3-Character-Sheet
# Distributed under GNU GPL v3.0. See repository LICENSE and NOTICE.

"""Standalone MiniMax H3 character sheet builder for ComfyUI.

Two nodes and an in-node panel:

* ``MiniMaxH3CharacterSheet`` - renders a sheet from references with roles, across
  a matrix of views / poses / expressions (expands into ComfyUI core MiniMax H3
  nodes; no other custom pack required).
* ``H3SheetGrid`` - composites the sheet from the per-cell frames, keeps every
  frame, and picks one frame per cell.

Everything lands in ``<output>/minimax_sheets/<name>/`` and is re-composable from
disk with no re-render (the panel's Rebuild action, or POST
``/h3-character-sheet/action``).
"""

from __future__ import annotations

import logging

log = logging.getLogger("H3-Character-Sheet")

if not __package__:
    # Pytest may inspect this file as a plain file (the checkout directory has
    # hyphens), in which case relative imports cannot work. Keep that probe inert.
    NODE_CLASS_MAPPINGS: dict = {}
    NODE_DISPLAY_NAME_MAPPINGS: dict = {}
    WEB_DIRECTORY = "./web/js"
else:
    from .nodes.cellsink import H3SheetCellSink
    from .nodes.grid import H3SheetGrid
    from .nodes.ordergate import H3SheetOrderGate
    from .nodes.sheet import MiniMaxH3CharacterSheet

    NODE_CLASS_MAPPINGS = {
        "MiniMaxH3CharacterSheet": MiniMaxH3CharacterSheet,
        "H3SheetGrid": H3SheetGrid,
        # Internal: inserted by the sheet node between each cell and the grid so
        # frames land on disk (and in the panel) as each cell finishes.
        "H3SheetCellSink": H3SheetCellSink,
        # Internal: sequences the cells so they render in list order.
        "H3SheetOrderGate": H3SheetOrderGate,
    }

    NODE_DISPLAY_NAME_MAPPINGS = {
        "MiniMaxH3CharacterSheet": "MiniMax H3 Character Sheet Builder",
        "H3SheetGrid": "H3 Character Sheet Grid",
        "H3SheetCellSink": "H3 Sheet Cell Saver (internal)",
        "H3SheetOrderGate": "H3 Sheet Order Gate (internal)",
    }

    WEB_DIRECTORY = "./web/js"

    try:
        from .sheet_routes import register_routes

        if not register_routes():
            log.warning("Character sheet HTTP routes deferred: PromptServer not ready.")
    except Exception as exc:  # pragma: no cover - ComfyUI startup only
        log.warning("Character sheet HTTP routes failed to load: %s", exc)


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
