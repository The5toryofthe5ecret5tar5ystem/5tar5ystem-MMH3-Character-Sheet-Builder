# ComfyUI-H3-Character-Sheet - save one cell as soon as it finishes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Per-cell sink: the reason the panel can show progress during a run.

``H3SheetGrid`` only runs once every cell has rendered, because it needs all of them
to composite the sheet. Without a sink nothing touches the disk until the whole job
ends, so the panel's Results tab stays empty for the entire render (a 12-cell sheet
is many minutes of "Nothing rendered yet").

This node sits between a cell's ``VAEDecode`` and the grid: it writes that cell's
frames immediately, records the plan and the progress in the manifest, and passes the
images through untouched. The grid then only has to pick frames and composite - and
the panel's poll of the sheet folder fills in cell by cell, live.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

from comfy_api.latest import io

from ..planner import grid_payload
from ..sheet_pass_core import flatten_image_batch
from ..sheet_spec import parse_sheet_spec
from ..sheet_store import SheetStore

log = logging.getLogger("H3-Character-Sheet.cellsink")

_CATEGORY = "MiniMaxH3/Character Sheet"


class H3SheetCellSink(io.ComfyNode):
    """Keep one sheet cell's frames on disk while the rest of the sheet renders."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3SheetCellSink",
            display_name="H3 Sheet Cell Saver",
            description=(
                "Internal to the Character Sheet Maker: saves one cell's frames as soon "
                "as that cell is rendered so the panel can show progress. Passes the "
                "frames through to the sheet grid."
            ),
            category=_CATEGORY,
            inputs=[
                io.Image.Input("images", tooltip="Frames of one sheet cell."),
                io.Video.Input(
                    "clip",
                    optional=True,
                    tooltip=(
                        "The cell's exported clip, when the sheet writes one. Taken purely so "
                        "the export is part of the graph this node needs: core SaveVideo is an "
                        "output node, and a node nothing consumes may not be executed. "
                        "Passed through untouched."
                    ),
                ),
                io.String.Input(
                    "sheet_data", multiline=True, default="",
                    tooltip="The character sheet payload (cells + references), as authored by the panel.",
                ),
                io.String.Input("cell_id", default="cell", tooltip="Which cell of the matrix these frames are."),
                io.String.Input("name", default="character_sheet", tooltip="Sheet folder name."),
                io.Boolean.Input("keep_frames", default=True, tooltip="Write the frames (off = only the final sheet is kept)."),
            ],
            outputs=[io.Image.Output(display_name="images")],
        )

    @classmethod
    def execute(
        cls,
        images: Any,
        sheet_data: str = "",
        cell_id: str = "cell",
        name: str = "character_sheet",
        keep_frames: bool = True,
        clip: Any = None,
    ) -> io.NodeOutput:
        try:
            spec = parse_sheet_spec(sheet_data or {})
        except ValueError as exc:
            log.warning("H3 sheet cell saver: %s", exc)
            return io.NodeOutput(images)

        spec.name = str(name or spec.name or "character_sheet")
        store = SheetStore(spec.name).ensure()
        cell_key = str(cell_id or "cell")
        cells = {cell.id for cell in spec.enabled_cells}
        frames = flatten_image_batch(images)
        saved = 0
        if keep_frames and frames:
            saved = len(store.save_cell_frames(cell_key, frames))

        # Record the plan + progress so the panel (which polls this folder through
        # /h3-character-sheet) can list every cell and show it filling in.
        manifest = store.read_manifest()
        manifest["spec"] = grid_payload(spec, name=store.name)
        progress = manifest.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        progress["planned"] = len(spec.enabled_cells)
        progress[cell_key] = saved
        progress["last"] = cell_key
        progress["frames"] = int(progress.get("frames") or 0) + saved
        manifest["progress"] = progress
        store.write_manifest(manifest)

        log.info(
            "H3 sheet cell saver: %s wrote %s frame(s) (%s/%s cells so far)",
            cell_key, saved, sum(1 for key, value in progress.items() if key not in ("planned", "last", "frames") and value),
            progress["planned"],
        )
        if keep_frames and cells:
            _prune_unplanned(store, cells, cell_key)
        if clip is not None:
            # The clip was written by core SaveVideo just before this node ran: keep the
            # newest take of this cell, drop the ones an earlier attempt left behind.
            removed = store.prune_cell_clips(cell_key)
            if removed:
                log.info("H3 sheet cell saver: dropped older clip(s): %s", ", ".join(removed))
        return io.NodeOutput(images)


def _prune_unplanned(store: SheetStore, planned_ids: set[str], current: str) -> None:
    """Drop frames of cells this run is not rendering.

    The sheet folder is reused between runs, so yesterday's "profile" cell would
    otherwise sit in the results list - and in the folder listing - as a ghost the
    current plan does not contain.
    """
    removed: list[str] = []
    frames_dir = store.frames_dir
    for directory in frames_dir.iterdir() if frames_dir.exists() else []:
        if not directory.is_dir() or directory.name in planned_ids or directory.name == current:
            continue
        try:
            shutil.rmtree(directory)
            removed.append(directory.name)
        except OSError as exc:  # a file share may refuse; never fail a render over it
            log.warning("H3 sheet cell saver: could not remove stale cell %s: %s", directory.name, exc)
    if removed:
        log.info("H3 sheet cell saver: removed stale cell folder(s): %s", ", ".join(sorted(removed)))


__all__ = ["H3SheetCellSink"]
