# ComfyUI-H3-Character-Sheet - the RefMod suite: several sheets from one queue.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""A suite: the boards of one character, each rendered as its own sheet in one run.

A RefMod bundle is better the more views it carries, and the views a character needs are not one
sheet's worth: a hero sheet reads identity at a glance, an expression board says what the face can
do, and the detail crops (eyes, mouth, hands, feet - and, for an adult sheet, the explicit ones)
document what no full-body framing can show. Rendering those as four separate queues is four times
the waiting and four times the chance to forget one.

So a suite is *data*: an ordered list of layout presets (``render.suite``, written by the suite
preset in ``presets.py``). One queue renders each board into its own folder under the run's name,
and the boards stay exactly what the panel offers on their own - the suite cannot drift from them,
because it names them.

What each board is made of comes from the layout preset it names:
* its ticks become the board's cells (``cell_matrix``, the same expansion the panel's *Build cells*
  button makes),
* its ``widgets``/``sheet`` become the board's arrangement,
* the quality axis (mode, steps, reference sizing, continuation) is the RUN's, because that is what
  the user set on the node - a suite never overrides how the sheet is sampled.

Pure data: no ComfyUI, no torch, no GPU, so the whole thing is testable without a render.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from .presets import preset_by_id
from .sheet_spec import SheetSpec, cell_matrix, parse_sheet_spec

log = logging.getLogger("H3-Character-Sheet.suite")

#: Widget names a board takes from its layout preset. Deliberately a list rather than "every key
#: the preset sets": a board must not carry the quality axis (or a size) just because a preset
#: happens to mention one.
_BOARD_WIDGETS = (
    "sheet_layout",
    "sheet_columns",
    "sheet_aspect",
    "sheet_captions",
    "sheet_background",
    "sheet_fit",
    "cell_aspect",
)


@dataclass(frozen=True)
class SuiteBoard:
    """One sheet of a suite: the preset it came from, its folder name, and its spec."""

    id: str
    label: str
    folder: str
    spec: SheetSpec
    cells: int
    layout: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "folder": self.folder,
            "cells": int(self.cells),
            "layout": self.layout,
        }


def board_folder(board_id: Any) -> str:
    """The sub-folder a board renders into, under the run's sheet folder.

    Sanitised the same way sheet folders are, so a board's folder is always a plain name the
    panel can list and the routes can serve.
    """
    from .sheet_spec import safe_name  # local: keeps the module import-light

    return safe_name(str(board_id or "board"), "board")


def suite_boards(spec: SheetSpec, *, frames: int | None = None) -> tuple[list[SuiteBoard], list[str]]:
    """``([SuiteBoard, ...], [warning, ...])`` for a spec whose ``render.suite`` is set.

    Each board is the run's spec with the board's own layout, cells and layout metadata applied -
    everything else (references, background reference, blur, mode, steps, seed, resolution) stays
    the run's, because that is what the user configured. A board that names an unknown or non-layout
    preset is reported and skipped rather than silently rendered as a copy of the first sheet.
    """
    boards: list[SuiteBoard] = []
    warnings: list[str] = []
    for board_id in spec.render.suite:
        preset = preset_by_id(board_id)
        if preset is None:
            warnings.append(
                f"suite: {board_id!r} is not a preset of this pack; that board is skipped."
            )
            continue
        if preset.kind != "layout" or not preset.build:
            warnings.append(
                f"suite: {board_id!r} is a {preset.kind} preset, not a layout with cells; "
                "that board is skipped."
            )
            continue
        board_spec = _board_spec(spec, preset, frames=frames)
        if not board_spec.enabled_cells:
            warnings.append(f"suite: {board_id!r} built no cells; that board is skipped.")
            continue
        boards.append(
            SuiteBoard(
                id=preset.id,
                label=preset.label,
                folder=board_folder(preset.id),
                spec=board_spec,
                cells=len(board_spec.enabled_cells),
                layout=board_spec.layout.layout,
            )
        )
    if not boards:
        warnings.append(
            "suite: no board could be built (see the warnings above); this run has nothing to "
            "render."
        )
    return boards, warnings


def _board_spec(spec: SheetSpec, preset: Any, *, frames: int | None) -> SheetSpec:
    """The run's spec with one layout preset's cells and arrangement applied."""
    ticks = preset.build or {}
    matrix = cell_matrix(
        views=ticks.get("views") or [],
        poses=ticks.get("poses") or [],
        expressions=ticks.get("expressions") or [],
        frames=int(frames or spec.render.frames_per_cell or 22),
    )
    cells = parse_sheet_spec({"cells": matrix}).cells
    if not ticks.get("views"):
        # A layout with no ticks would render nothing; fall back to this run's own cells rather
        # than an empty board, and leave the arrangement to the preset.
        cells = list(spec.cells)

    widgets = {key: preset.widgets[key] for key in _BOARD_WIDGETS if key in preset.widgets}
    layout = replace(
        spec.layout,
        layout=str(widgets.get("sheet_layout") or spec.layout.layout),
        columns=int(widgets.get("sheet_columns") or spec.layout.columns),
        aspect=str(widgets.get("sheet_aspect") or spec.layout.aspect),
        captions=bool(widgets.get("sheet_captions", spec.layout.captions)),
        background=str(widgets.get("sheet_background") or spec.layout.background),
        fit=str(widgets.get("sheet_fit") or spec.layout.fit),
    )
    # The board's own backdrop, when the layout preset names one (the hero sheet's neutral tan).
    render = replace(
        spec.render,
        background=str(preset.render.get("background") or spec.render.background),
        background_custom=str(preset.render.get("backgroundCustom") or spec.render.background_custom),
        background_ref=str(preset.render.get("backgroundRef") or spec.render.background_ref),
        cell_aspect=str(widgets.get("cell_aspect") or spec.render.cell_aspect),
        # A board is not itself a suite, or every board would try to render every board.
        suite=[],
        layout_preset=preset.id,
    )
    return replace(spec, cells=cells, layout=layout, render=render, warnings=[], notes=[])


def board_segments(boards: list[SuiteBoard]) -> list[dict[str, Any]]:
    """The live stream's map of a suite: which board each sampler call belongs to.

    The preview wrapper is attached to the model every board samples through, so it sees ONE
    stream of sampler calls for the whole suite and cannot know where one board ends and the next
    begins. This is that missing piece - one entry per board, in render order:

    * ``id`` / ``label`` / ``folder``: what the panel (and the routes) name the board by.
    * ``calls``: how many sampler calls the board makes - one in one-pass mode (the whole sheet is
      a single render), one per cell otherwise.
    * ``whole_sheet``: whether each of those calls IS the board (one-pass) rather than one cell of
      it, so the panel can label what it is showing honestly.

    Without it a suite stream reads as "cell 3/19" of a run whose boards the panel cannot tell
    apart, and it cannot follow the board that is actually rendering.
    """
    out: list[dict[str, Any]] = []
    for board in boards:
        single = bool(board.spec.render.single_pass)
        out.append({
            "id": str(board.id),
            "label": str(board.label),
            "folder": str(board.folder),
            "calls": 1 if single else max(1, len(board.spec.enabled_cells)),
            "whole_sheet": single,
        })
    return out


def suite_lines(boards: list[SuiteBoard], *, name: str = "") -> list[str]:
    """The suite's report block: what will render, in order, and where each board lands."""
    if not boards:
        return ["Suite: nothing to render."]
    lines = [
        f"Suite: {len(boards)} sheet(s) from one queue - "
        + ", ".join(board.label for board in boards),
        f"Folder: {name or 'the sheet folder'}/<board> - one folder per board, each a full sheet "
        "with its own cells, picks and report.",
    ]
    for position, board in enumerate(boards, start=1):
        lines.append(
            f"  {position}. {board.label} -> {board.folder}/ "
            f"({board.cells} cell(s), {board.layout} layout)"
        )
    return lines


def suite_manifest(boards: list[SuiteBoard], *, name: str = "", exported: str = "") -> dict[str, Any]:
    """The suite's own record, written next to the run's sheets."""
    return {
        "name": str(name or ""),
        "boards": [board.to_dict() for board in boards],
        "exported": str(exported or ""),
    }


__all__ = [
    "SuiteBoard",
    "board_folder",
    "board_segments",
    "suite_boards",
    "suite_lines",
    "suite_manifest",
]
