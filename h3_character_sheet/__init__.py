# ComfyUI-H3-Character-Sheet
# Distributed under GNU GPL v3.0. See repository LICENSE and NOTICE.

"""Standalone MiniMax H3 character sheet builder for ComfyUI.

Two nodes and an in-node panel:

* ``MiniMaxH3CharacterSheet`` - renders a sheet from references with roles, across
  a matrix of views / poses / expressions (expands into ComfyUI core MiniMax H3
  nodes; no other custom pack required).
* ``H3SheetGrid`` - composites the sheet from the per-cell frames, keeps every
  frame, and picks one frame per cell.
* ``H3SheetRefMod`` - exports the sheet as a ComfyUI-MiniMaxH3Mod "RefMod" bundle
  (appearance members plus a voice member). Needs that pack for the VAE encoders;
  without it the node stops with the clone line. See ``refmod_export.py``.

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
    from .nodes.join import H3SheetJoin
    from .nodes.onepass import H3SheetOnePassSink
    from .nodes.ordergate import H3SheetOrderGate
    from .nodes.refmod import H3SheetRefMod
    from .nodes.sheet import MiniMaxH3CharacterSheet

    NODE_CLASS_MAPPINGS = {
        "MiniMaxH3CharacterSheet": MiniMaxH3CharacterSheet,
        "H3SheetGrid": H3SheetGrid,
        # Internal: inserted by the sheet node between each cell and the grid so
        # frames land on disk (and in the panel) as each cell finishes.
        "H3SheetCellSink": H3SheetCellSink,
        # Internal: the one-pass sheet's sink - one H3 render for the whole sheet, whose panels
        # are sliced back out of it (see one_pass / nodes.onepass). This is the default path.
        "H3SheetOnePassSink": H3SheetOnePassSink,
        # The type this node had while the mode was called the draft pass. A prompt queued before
        # the rename still names it, so the alias stays - it is the same class.
        "H3SheetDraftSink": H3SheetOnePassSink,
        # Internal: sequences the cells so they render in list order.
        "H3SheetOrderGate": H3SheetOrderGate,
        # Internal: a SUITE's exit point. Every board's sheet/report/cells feed it, so nothing
        # downstream (the RefMod export) can run before the last board has finished - graphs have
        # no ordering of their own. NOTE: this list is what ComfyUI executes from, and it is a
        # SECOND list next to ``nodes/__init__.__all__`` - forgetting an entry here means the
        # executor dies with KeyError after the expansion has already run (that happened to
        # H3SheetJoin). ``tests/test_node_registry.py`` now keeps the two lists in step.
        "H3SheetJoin": H3SheetJoin,
        # Optional: needs ComfyUI-MiniMaxH3Mod installed to actually run.
        "H3SheetRefMod": H3SheetRefMod,
    }

    NODE_DISPLAY_NAME_MAPPINGS = {
        "MiniMaxH3CharacterSheet": "MiniMax H3 Character Sheet Builder",
        "H3SheetGrid": "H3 Character Sheet Grid",
        "H3SheetCellSink": "H3 Sheet Cell Saver (internal)",
        "H3SheetOnePassSink": "H3 Sheet One-Pass Sink (internal)",
        "H3SheetOrderGate": "H3 Sheet Order Gate (internal)",
        "H3SheetJoin": "H3 Sheet Join (internal)",
        "H3SheetRefMod": "H3 Sheet → RefMod",
    }

    WEB_DIRECTORY = "./web/js"

    try:
        from .sheet_routes import register_routes

        if not register_routes():
            log.warning("Character sheet HTTP routes deferred: PromptServer not ready.")
    except Exception as exc:  # pragma: no cover - ComfyUI startup only
        log.warning("Character sheet HTTP routes failed to load: %s", exc)


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
