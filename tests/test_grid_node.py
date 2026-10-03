"""Character Sheet Builder - the grid node (frames in, sheet out).

No GPU needed: fake IMAGE batches in, real files on disk out. Pinned here: slot
ordering, keeping every frame, the pick contract, missing cells, and the tensors
the node returns.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from h3cs import sheet_pass_core as spc
from h3cs import sheet_store as store_mod
from h3cs.nodes import grid as grid_node


@pytest.fixture()
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "sheets_root", lambda: tmp_path / "minimax_sheets")
    return tmp_path


def _spec(**overrides):
    payload = {
        "name": "grid sheet",
        "sheet": {"layout": "hero-left", "columns": 2, "shortEdge": 512, "aspect": "3:2",
                  "captions": False},
        "cells": [
            {"id": "hero", "view": "portrait"},
            {"id": "front", "view": "front", "pose": "t-pose"},
        ],
    }
    payload.update(overrides)
    return payload


def _batch(frames: int, value: int = 40, size: int = 16) -> torch.Tensor:
    return torch.full((frames, size, size, 3), value / 255.0, dtype=torch.float32)


def _sharp_batch(frames: int, sharp_at: int) -> torch.Tensor:
    batch = _batch(frames, 40)
    checker = torch.tensor(
        (np.indices((16, 16)).sum(axis=0) % 2).astype("float32")
    ).unsqueeze(-1).repeat(1, 1, 3) / 255.0
    batch[sharp_at] = checker
    return batch


# --------------------------------------------------------------------------- #
# ordering / flattening
# --------------------------------------------------------------------------- #
def test_slots_are_ordered_numerically_not_lexically():
    batches = {"cell_10": "TEN", "cell_2": "TWO", "cell_1": "ONE"}
    assert spc.order_cell_images(batches) == ["ONE", "TWO", "TEN"]


def test_order_accepts_lists_and_single_batches():
    two, one = _batch(2), _batch(1)
    ordered = spc.order_cell_images([two, None, one])
    assert [int(batch.shape[0]) for batch in ordered] == [2, 1]
    single = _batch(3)
    assert spc.order_cell_images(single) == [single]
    assert spc.order_cell_images(None) == []


def test_slot_index_is_safe():
    assert spc.slot_index("cell_0") == 0
    assert spc.slot_index("weird") > 1000


def test_flatten_turns_a_batch_into_frames():
    frames = spc.flatten_image_batch(_batch(4))
    assert len(frames) == 4
    assert frames[0].dtype == np.uint8
    assert len(spc.flatten_image_batch(_batch(1)[0])) == 1
    assert spc.flatten_image_batch(None) == []


# --------------------------------------------------------------------------- #
# the node
# --------------------------------------------------------------------------- #
def test_execute_writes_frames_picks_and_sheet(outputs):
    sheet, cells, report = grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()),
        name="grid sheet",
        keep_frames=True,
        cells={"cell_1": _batch(4, 90), "cell_0": _batch(3, 10)},
    ).args
    store = store_mod.SheetStore("grid_sheet")
    assert store.sheet_path.is_file()
    assert len(store.frame_files("hero")) == 3
    assert len(store.frame_files("front")) == 4
    picks = json.loads(store.picks_path.read_text(encoding="utf-8"))
    assert picks["hero"]["index"] == 2  # auto = last frame
    assert picks["front"]["index"] == 3
    assert "Sheet:" in report
    # 3:2 at a 512px short edge, aligned to the 16px grid.
    assert tuple(sheet.shape) == (1, 512, 768, 3)
    assert int(cells.shape[0]) == 2


def test_slot_order_decides_which_cell_gets_which_batch(outputs):
    grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()),
        name="grid sheet",
        cells={"cell_1": _batch(2, 200), "cell_0": _batch(2, 5)},
    )
    store = store_mod.SheetStore("grid_sheet")
    hero = np.asarray(_load(store.cell_pick_path("hero")))
    front = np.asarray(_load(store.cell_pick_path("front")))
    assert int(hero.mean()) < 50 < int(front.mean()), (hero.mean(), front.mean())


def test_sharpest_pick_mode_is_honoured(outputs):
    spec = _spec(cells=[{"id": "hero", "view": "front", "pick": "sharpest"}])
    grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(spec), name="grid sheet", cells={"cell_0": _sharp_batch(5, 2)}
    )
    store = store_mod.SheetStore("grid_sheet")
    picks = json.loads(store.picks_path.read_text(encoding="utf-8"))
    assert picks["hero"]["index"] == 2

def test_missing_cells_are_reported_not_fatal(outputs):
    _sheet, _cells, report = grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()), name="grid sheet", cells={"cell_0": _batch(2)}
    ).args
    store = store_mod.SheetStore("grid_sheet")
    assert store.sheet_path.is_file()
    assert "front" in report
    assert "no frames" in report or "Empty cells" in report


def test_keep_frames_false_drops_the_frame_folder(outputs):
    grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()),
        name="grid sheet",
        keep_frames=False,
        cells={"cell_0": _batch(2), "cell_1": _batch(2)},
    )
    store = store_mod.SheetStore("grid_sheet")
    assert store.frame_files("hero") == []
    assert store.cell_pick_path("hero").is_file()


def test_manifest_records_the_spec_that_ran(outputs):
    grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()), name="grid sheet", cells={"cell_0": _batch(2)}
    )
    manifest = store_mod.SheetStore("grid_sheet").read_manifest()
    assert manifest["spec"]["name"] == "grid_sheet"
    assert manifest["spec"]["cells"][0]["id"] == "hero"


def test_no_cells_at_all_still_produces_a_sheet(outputs):
    sheet, cells, _report = grid_node.H3SheetGrid.execute(
        sheet_data=json.dumps(_spec()), name="grid sheet", cells=None
    ).args
    assert store_mod.SheetStore("grid_sheet").sheet_path.is_file()
    assert int(cells.shape[0]) == 0
    assert int(sheet.shape[0]) == 1


def _load(path):
    from PIL import Image

    with Image.open(path) as image:
        return image.convert("RGB")
