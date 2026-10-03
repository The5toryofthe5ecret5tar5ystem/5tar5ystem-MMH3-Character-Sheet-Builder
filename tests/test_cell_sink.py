# ComfyUI-H3-Character-Sheet - the per-cell saver.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Tests for ``H3SheetCellSink``: the node that makes progress visible.

The grid cannot run until every cell has rendered, so without a sink the sheet
folder stays empty for the whole job and the panel shows "nothing rendered yet"
while the log is already on cell 3. The sink writes one cell the moment it lands,
records the plan in the manifest, and hands the frames on unchanged.
"""

from __future__ import annotations

import json

import numpy as np

from h3cs import sheet_store
from h3cs.nodes import cellsink, grid

from tests.test_grid_node import _batch, _spec  # noqa: E402  (shared fixtures)


def _payload() -> str:
    return json.dumps(_spec())


def _run_sink(tmp_path, monkeypatch, *, cell_id="hero", frames=3, keep=True, payload=None):
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)
    out = cellsink.H3SheetCellSink.execute(
        images=_batch(frames),
        sheet_data=payload if payload is not None else _payload(),
        cell_id=cell_id,
        name="sink test",
        keep_frames=keep,
    )
    return out


def test_sink_writes_frames_and_passes_images_through(tmp_path, monkeypatch):
    out = _run_sink(tmp_path, monkeypatch, frames=4)
    # pass-through: the grid still receives the whole batch
    assert hasattr(out, "args") and out.args, "the sink must return the images"
    images = out.args[0]
    assert images.shape[0] == 4, f"expected 4 frames through, got {images.shape}"

    store = sheet_store.SheetStore("sink test", node_id=None)
    frames = store.frame_files("hero")
    assert len(frames) == 4, f"frames must be on disk immediately: {frames}"
    assert frames[0].name == "f0000.png"
    # the panel can already see this cell through the sheet listing
    listing = store.scan()
    rendered = [cell for cell in listing["cells"] if cell["rendered"]]
    assert [cell["id"] for cell in rendered] == ["hero"]
    assert listing["counts"]["frames"] == 4


def test_sink_records_the_plan_so_every_cell_is_listed_before_it_renders(tmp_path, monkeypatch):
    _run_sink(tmp_path, monkeypatch)
    store = sheet_store.SheetStore("sink test", node_id=None)
    manifest = store.read_manifest()
    assert manifest["spec"]["cells"], "the sink must write the planned cells"
    assert manifest["progress"]["planned"] == len(manifest["spec"]["cells"])
    assert manifest["progress"]["hero"] == 3
    listed = {cell["id"]: cell for cell in store.scan()["cells"]}
    assert len(listed) == len(manifest["spec"]["cells"]), "all planned cells are listed"
    assert listed["front"]["rendered"] is False, "a cell with no frames yet is not rendered"


def test_keep_frames_off_writes_no_frames(tmp_path, monkeypatch):
    _run_sink(tmp_path, monkeypatch, keep=False)
    store = sheet_store.SheetStore("sink test", node_id=None)
    assert store.frame_files("hero") == []
    assert store.read_manifest()["progress"]["hero"] == 0


def test_bad_payload_never_kills_the_render(tmp_path, monkeypatch):
    out = _run_sink(tmp_path, monkeypatch, payload="{not json")
    assert out.args[0].shape[0] == 3, "images still pass through"
    store = sheet_store.SheetStore("sink test", node_id=None)
    assert store.frame_files("hero") == []


def test_grid_does_not_rewrite_frames_the_sink_already_saved(tmp_path, monkeypatch):
    _run_sink(tmp_path, monkeypatch, frames=3)
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)
    result = grid.H3SheetGrid.execute(
        sheet_data=_payload(),
        name="sink test",
        keep_frames=True,
        cells={"cells.cell_0": _batch(3, 5)},
    )
    report = (tmp_path / "sink_test" / "report.txt").read_text()
    assert "hero: 3 frame(s) already on disk" in report, report
    assert result.args[2] is not None
    store = sheet_store.SheetStore("sink test", node_id=None)
    assert len(store.frame_files("hero")) == 3


def test_manifest_progress_is_readable_by_the_report(tmp_path, monkeypatch):
    _run_sink(tmp_path, monkeypatch, frames=2)
    store = sheet_store.SheetStore("sink test", node_id=None)
    progress = store.read_manifest()["progress"]
    assert progress["last"] == "hero"
    assert progress["frames"] == 2
