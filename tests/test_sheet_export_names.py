# ComfyUI-H3-Character-Sheet - the sheet export name
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""What a run writes, and what a re-compose edits.

The rule the user asked for: a render keeps its sheet in the SAME folder but adds a
new dated file, so an earlier sheet is never replaced. The manifest records the file
each run wrote, and everything that is not a render (the panel, the routes, a
re-pick) follows that record instead of minting another name.
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np

from h3cs import name_tokens as nt
from h3cs import sheet_store

FIXED = dt.datetime(2026, 10, 2, 18, 7, 5)


def _store(name: str, **kwargs):
    return sheet_store.SheetStore(name, **kwargs)


def _patch_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)


# --------------------------------------------------------------------------- #
# a plain name: same folder, dated files, nothing replaced
# --------------------------------------------------------------------------- #
def test_a_plain_name_gets_a_dated_file_in_the_same_folder(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    store = _store("character_sheet", export_name=nt.export_stem("character_sheet", now=FIXED), fresh=True)
    assert store.dir == tmp_path / "character_sheet"
    assert store.sheet_file == "character_sheet-20261002-180705.png"


def test_a_second_run_in_the_same_second_steps_aside_instead_of_overwriting(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    folder = tmp_path / "character_sheet"
    folder.mkdir()
    (folder / "character_sheet-20261002-180705.png").write_bytes(b"png")
    store = _store(
        "character_sheet",
        export_name="character_sheet-20261002-180705",
        fresh=True,
    )
    assert store.sheet_file == "character_sheet-20261002-180705-2.png"


def test_a_tokenised_name_expands_without_a_second_stamp(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    (tmp_path / "character_sheet-180705").mkdir()
    store = _store("character_sheet-%date:hhmmss%", fresh=True)
    assert store.dir.name == "character_sheet-180705"
    assert store.sheet_file == "character_sheet-180705.png"


# --------------------------------------------------------------------------- #
# readers follow the manifest, so the panel edits the sheet that exists
# --------------------------------------------------------------------------- #
def test_the_manifest_records_the_file_and_readers_follow_it(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    writer = _store("character_sheet", export_name="character_sheet-20261002-180705", fresh=True)
    writer.ensure()
    writer.sheet_path.write_bytes(b"png")
    writer.write_manifest({"spec": {"name": "character_sheet"}})

    assert writer.read_manifest()["sheetFile"] == "character_sheet-20261002-180705.png"
    reader = _store("character_sheet")  # the panel / the routes
    assert reader.fresh is False
    assert reader.sheet_file == "character_sheet-20261002-180705.png"
    assert reader.sheet_path.is_file()


def test_a_folder_without_a_manifest_resolves_to_the_newest_export(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    folder = tmp_path / "character_sheet"
    folder.mkdir()
    old = folder / "character_sheet-20261002-170000.png"
    old.write_bytes(b"png")
    new = folder / "character_sheet-20261002-180705.png"
    new.write_bytes(b"png")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    os.utime(new, (1_600_000_200, 1_600_000_200))

    assert _store("character_sheet").sheet_file == new.name


def test_cells_and_frames_are_never_mistaken_for_the_sheet(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    store = _store("character_sheet", export_name="character_sheet-20261002-180705", fresh=True)
    store.ensure()
    store.save_cell_pick("c1", np.zeros((4, 4, 3), dtype="uint8"))
    # only a png written straight into the folder counts as the sheet
    assert store.sheet_file == "character_sheet-20261002-180705.png"


def test_clear_removes_every_export_the_folder_holds(tmp_path, monkeypatch):
    _patch_root(monkeypatch, tmp_path)
    folder = tmp_path / "character_sheet"
    folder.mkdir()
    for name in ("character_sheet-20261002-170000.png", "character_sheet-20261002-180705.png"):
        (folder / name).write_bytes(b"png")
    store = _store("character_sheet")
    store.write_manifest({"spec": {}})
    assert store.clear() >= 3
    assert not list(folder.glob("*.png"))
