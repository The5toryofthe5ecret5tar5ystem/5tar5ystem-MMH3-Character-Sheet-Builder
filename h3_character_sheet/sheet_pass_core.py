# ComfyUI-H3-Character-Sheet - frame handling shared by the grid node and routes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Frame/batch plumbing for a sheet: ComfyUI images in, sheet on disk out.

Kept free of node classes so it is unit-testable: the grid node, the HTTP routes
and the tests all use these helpers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Sequence

import numpy as np
import torch

from .sheet_spec import SheetSpec
from .sheet_store import SheetStore

log = logging.getLogger("H3-Character-Sheet.pass")

_SLOT_INDEX = re.compile(r"(\d+)\s*$")


def to_uint8_array(image: Any) -> np.ndarray | None:
    """One IMAGE (HxWx3, float 0..1 or uint8, torch or numpy) -> uint8 HxWx3."""
    if image is None:
        return None
    if torch.is_tensor(image):
        array = image.detach().to("cpu").float().clamp(0, 1).numpy() * 255.0
        return array.astype(np.uint8)
    array = np.asarray(image)
    if array.size == 0:
        return None
    if array.dtype != np.uint8:
        array = (np.clip(array.astype(np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
    if array.ndim == 4:
        array = array[0]
    return array


def flatten_image_batch(batch: Any) -> list[np.ndarray]:
    """An IMAGE batch (T,H,W,3) -> a list of HxWx3 uint8 frames."""
    if batch is None:
        return []
    frames: list[np.ndarray] = []
    if torch.is_tensor(batch):
        tensor = batch.detach().to("cpu").float().clamp(0, 1)
        array = (tensor.numpy() * 255.0).astype(np.uint8)
    else:
        array = np.asarray(batch)
        if array.size == 0:
            return []
        if array.dtype != np.uint8:
            array = (np.clip(array.astype(np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
    if array.ndim == 3:
        frames.append(array)
    elif array.ndim == 4:
        frames.extend(array[index] for index in range(array.shape[0]))
    return frames


def slot_index(slot: Any) -> int:
    """``cell_7`` -> 7; anything without a number sorts last but stays stable."""
    match = _SLOT_INDEX.search(str(slot or ""))
    return int(match.group(1)) if match else 1 << 30


def order_cell_images(cells: Any) -> list[Any]:
    """Autogrow cell inputs -> batches in cell order.

    Accepts the autogrow dict (``{"cell_1": IMAGE, "cell_0": IMAGE}``), an ordered
    mapping, or a plain list/tuple of batches.
    """
    if cells is None:
        return []
    if isinstance(cells, dict):
        items = sorted(cells.items(), key=lambda item: (slot_index(item[0]), str(item[0])))
        return [value for _slot, value in items if value is not None]
    if torch.is_tensor(cells) or isinstance(cells, np.ndarray):
        return [cells]
    if isinstance(cells, (list, tuple)):
        if cells and isinstance(cells[0], (dict, list, tuple)):
            # An INPUT_IS_LIST upstream gives a list of the autogrow dicts.
            return list(cells)
        return [batch for batch in cells if batch is not None]
    return [cells]


def finish_sheet(
    store: SheetStore,
    spec: SheetSpec,
    *,
    report: str = "",
    picks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the sheet from the frames on disk, then record what was run."""
    result = store.rebuild_sheet(spec, picks)
    store.write_manifest(
        {
            "spec": spec.to_dict(),
            "cells": result["cells"],
            "missing": result["missing"],
            "size": list(result["size"]),
            "warnings": list(spec.warnings),
        }
    )
    store.write_report(report)
    return result


def save_cell_batches(
    store: SheetStore,
    spec: SheetSpec,
    batches: Sequence[Any],
) -> dict[str, int]:
    """Persist every frame of every cell; returns ``{cellId: frames}``."""
    counts: dict[str, int] = {}
    for position, cell in enumerate(spec.enabled_cells):
        batch = batches[position] if position < len(batches) else None
        frames = flatten_image_batch(batch)
        if frames:
            store.save_cell_frames(cell.id, frames)
        counts[cell.id] = len(frames)
    return counts


def cell_report_lines(counts: dict[str, int], picks: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for cell_id, frames in counts.items():
        pick = (picks or {}).get(cell_id) or {}
        lines.append(
            f"- {cell_id}: {frames} frame(s) kept, picked frame "
            f"{pick.get('index')} ({pick.get('mode')})"
        )
    return lines


def iter_picked_paths(store: SheetStore, spec: SheetSpec) -> Iterable[Any]:
    for cell in spec.enabled_cells:
        path = store.cell_pick_path(cell.id)
        yield path if path.is_file() else None


__all__ = [
    "cell_report_lines",
    "finish_sheet",
    "flatten_image_batch",
    "iter_picked_paths",
    "order_cell_images",
    "save_cell_batches",
    "slot_index",
    "to_uint8_array",
]
