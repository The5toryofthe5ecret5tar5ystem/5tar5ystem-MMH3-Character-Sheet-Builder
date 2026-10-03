# ComfyUI-H3-Character-Sheet - the sheet grid (compositor) node.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""H3 Character Sheet Grid: the cell images -> frames on disk -> one sheet.

This node is the only place a sheet is assembled. It receives one IMAGE batch per
cell (the frames the H3 render produced for that cell), keeps them all, picks one
frame per cell, composites the sheet and writes everything next to it.

Keeping every frame is what makes a sheet cheap to change your mind about: a new
layout, aspect ratio or picked frame is a re-composite, not a re-render (the panel's
Rebuild action calls the same code path through the sheet routes).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import torch

from comfy_api.latest import io

from ..planner import grid_payload
from ..sheet_pass_core import finish_sheet, flatten_image_batch, order_cell_images
from ..sheet_spec import MAX_CELLS, describe_background, parse_sheet_spec
from ..sheet_store import SheetStore

log = logging.getLogger("H3-Character-Sheet.grid")


class H3SheetGrid(io.ComfyNode):
    """Composite a character sheet from per-cell rendered frames."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3SheetGrid",
            display_name="H3 Character Sheet Grid",
            category="MiniMaxH3/Character Sheet",
            description=(
                "Composite the character sheet from the per-cell frames: keeps every "
                "frame, picks one per cell (auto = settled last frame, or sharpest), "
                "lays the cells out and writes <output>/minimax_sheets/<name>/."
            ),
            inputs=[
                io.String.Input(
                    "sheet_data",
                    default="",
                    multiline=True,
                    tooltip="Sheet payload written by the Character Sheet Maker node / panel.",
                ),
                io.String.Input("name", default="character_sheet", tooltip="Sheet folder and file name."),
                io.Boolean.Input(
                    "keep_frames",
                    default=True,
                    optional=True,
                    tooltip="Keep every frame per cell so the sheet can be re-picked or re-laid out with no re-render.",
                ),
                io.Autogrow.Input(
                    "cells",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("cell", tooltip="Frames rendered for one cell."),
                        prefix="cell_",
                        min=0,
                        max=MAX_CELLS,
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(display_name="sheet"),
                io.Image.Output(display_name="cells"),
                io.String.Output(display_name="report"),
            ],
        )

    @classmethod
    def execute(
        cls,
        sheet_data: str,
        name: str = "character_sheet",
        keep_frames: bool = True,
        cells: Any = None,
    ) -> io.NodeOutput:
        spec = parse_sheet_spec(sheet_data or {})
        spec.name = str(name or spec.name or "character_sheet")
        # fresh=True: this run writes a NEW dated sheet file, so a finished render is
        # never replaced (the manifest then points the panel at the file we wrote).
        store = SheetStore(spec.name, fresh=True).ensure()
        # Keep the recorded spec and the folder name identical: the manifest has to
        # describe the sheet that is actually on disk.
        spec.name = store.name
        chunks = order_cell_images(cells)
        lines = [
            f"H3 Character Sheet Grid: {len(chunks)} cell image(s) in, "
            f"{len(spec.enabled_cells)} cell(s) planned.",
            f"Folder: {store.dir}",
            f"Background: {describe_background(spec)}",
        ]

        missing: list[str] = []
        saved = store.read_manifest().get("progress")
        already = saved if isinstance(saved, dict) else {}
        for position, cell in enumerate(spec.enabled_cells):
            batch = chunks[position] if position < len(chunks) else None
            frames = flatten_image_batch(batch)
            if not frames:
                missing.append(cell.id)
                lines.append(f"- {cell.id}: no frames received")
                continue
            # The per-cell saver already wrote these frames during the run.
            if already.get(cell.id) == len(frames) and store.frame_files(cell.id):
                lines.append(f"- {cell.id}: {len(frames)} frame(s) already on disk")
            else:
                store.save_cell_frames(cell.id, frames)
                lines.append(f"- {cell.id}: {len(frames)} frame(s) kept")

        result = finish_sheet(store, spec, report="\n".join(lines))
        picks = result.get("cells") or {}
        for cell in spec.enabled_cells:
            pick = picks.get(cell.id) or {}
            lines.append(
                f"  picked {cell.id} -> frame {pick.get('index')} ({pick.get('mode')})"
            )
        if missing:
            lines.append("Empty cells (no frames): " + ", ".join(missing))
        for warning in spec.warnings:
            lines.append(f"Warning: {warning}")
        if result.get("size"):
            width, height = result["size"]
            lines.append(f"Sheet: {store.sheet_path} ({width}x{height})")

        report = "\n".join(lines)
        store.write_report(report)
        if not keep_frames:
            for cell in spec.enabled_cells:
                directory = store.cell_frame_dir(cell.id)
                for stale in directory.glob("f*.png"):
                    try:
                        stale.unlink()
                    except OSError:
                        pass

        sheet_tensor = tensor_from_image(result.get("sheet"))
        cells_tensor = tensor_from_arrays(
            [
                _load_cell_png(store, cell.id)
                for cell in spec.enabled_cells
            ]
        )
        return io.NodeOutput(sheet_tensor, cells_tensor, report)


def _load_cell_png(store: SheetStore, cell_id: str) -> np.ndarray | None:
    path = store.cell_pick_path(cell_id)
    if not path.is_file():
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # noqa: BLE001 - a missing cell must not break the sheet
        log.warning("sheet grid: could not read picked cell %s (%s)", cell_id, exc)
        return None


def tensor_from_image(image: Any) -> torch.Tensor:
    """PIL image -> (1, H, W, 3) float tensor (empty batch when absent)."""
    if image is None:
        return torch.zeros((0, 64, 64, 3), dtype=torch.float32)
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def tensor_from_arrays(arrays: list[np.ndarray | None]) -> torch.Tensor:
    """Picked cell images -> one (N, H, W, 3) batch at the first cell's size."""
    frames = [
        torch.from_numpy(np.asarray(array, dtype=np.float32) / 255.0)
        for array in arrays
        if array is not None
    ]
    if not frames:
        return torch.zeros((0, 64, 64, 3), dtype=torch.float32)
    height, width = int(frames[0].shape[0]), int(frames[0].shape[1])
    normalised: list[torch.Tensor] = []
    for frame in frames:
        if int(frame.shape[0]) == height and int(frame.shape[1]) == width:
            normalised.append(frame)
            continue
        resized = torch.nn.functional.interpolate(
            frame.permute(2, 0, 1).unsqueeze(0),
            size=(height, width),
            mode="bilinear",
            align_corners=False,
        )
        normalised.append(resized.squeeze(0).permute(1, 2, 0))
    return torch.stack(normalised, dim=0)


NODE_CLASS_MAPPINGS = {"H3SheetGrid": H3SheetGrid}
NODE_DISPLAY_NAME_MAPPINGS = {"H3SheetGrid": "H3 Character Sheet Grid"}

__all__ = [
    "H3SheetGrid",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "grid_payload",
    "tensor_from_arrays",
    "tensor_from_image",
    "time",
]
