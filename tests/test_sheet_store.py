"""Character Sheet Builder - the on-disk store (frames, picks, composites).

Pinned here:

* one folder per sheet with ``frames/<cellId>``, ``cells/<cellId>.png`` and the
  composited ``<name>.png`` + manifest,
* every frame is kept, so rebuilding with another pick/layout needs no re-render,
* a cell with no frames is reported, never fatal,
* the listing payload the embedded panel polls.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from h3cs import sheet_store as store_mod
from h3cs import sheet_spec as ss


@pytest.fixture()
def store(tmp_path, monkeypatch):
    # The output root is what /view resolves ``subfolder`` against, and the sheets
    # live under it - patch the root, not sheets_root, so the URLs stay consistent.
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path)
    return store_mod.SheetStore("test sheet", node_id="42")


def _frames(count: int, *, sharp_at: int | None = None):
    """Flat frames, optionally with one high-detail frame."""
    out = []
    base = np.full((32, 32, 3), 40, dtype=np.uint8)
    for index in range(count):
        if sharp_at is not None and index == sharp_at:
            checker = (np.indices((32, 32)).sum(axis=0) % 2).astype(np.uint8)
            out.append(np.stack([checker * 255] * 3, axis=-1))
        else:
            out.append(base.copy())
    return out


def _payload(**overrides):
    data = {
        "name": "test sheet",
        "globalPrompt": "a woman",
        "refs": {"pictures": [{"imageFile": "f.png", "role": "face"}]},
        "sheet": {"layout": "grid", "columns": 1, "shortEdge": 512, "aspect": "3:2",
                  "captions": False},
        "cells": [
            {"id": "c1", "view": "front", "pose": "neutral", "pick": "auto"},
            {"id": "c2", "view": "face", "pick": "auto"},
        ],
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def test_folder_layout_and_safe_names(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path)
    sheet_store = store_mod.SheetStore("Steph Sheet!! ../etc")
    sheet_store.ensure()
    assert sheet_store.dir.parent.name == "minimax_sheets"
    assert sheet_store.dir.name == "Steph_Sheet_etc"
    assert sheet_store.sheet_path.name == sheet_store.sheet_file
    # Dated: a run writes a NEW file instead of replacing the previous sheet.
    assert sheet_store.sheet_file.startswith("Steph_Sheet_etc-")
    assert sheet_store.frames_dir.is_dir()
    assert sheet_store.cells_dir.is_dir()


# --------------------------------------------------------------------------- #
# write / rebuild
# --------------------------------------------------------------------------- #
def test_save_frames_keeps_all_of_them_and_replaces_stale_ones(store):
    store.save_cell_frames("c1", _frames(3))
    assert len(store.frame_files("c1")) == 3
    store.save_cell_frames("c1", _frames(2))
    assert len(store.frame_files("c1")) == 2


def test_rebuild_uses_the_last_frame_by_default_and_writes_everything(store):
    store.save_cell_frames("c1", _frames(4))
    store.save_cell_frames("c2", _frames(3, sharp_at=0))
    result = store.rebuild_sheet(_payload())
    assert store.sheet_path.is_file()
    assert result["size"] == (768, 512)
    assert result["cells"]["c1"]["index"] == 3  # last frame of 4
    assert result["cells"]["c2"]["index"] == 2
    assert store.cell_pick_path("c1").is_file()
    stored = json.loads(store.picks_path.read_text(encoding="utf-8"))
    assert stored["c1"]["index"] == 3


def test_rebuild_honours_an_explicit_pick_and_the_cell_file_changes(store):
    store.save_cell_frames("c1", _frames(4, sharp_at=2))
    store.save_cell_frames("c2", _frames(2))
    store.rebuild_sheet(_payload())
    last_pick = np.asarray(Image.open(store.cell_pick_path("c1")).convert("RGB"))
    store.rebuild_sheet(_payload(), {"c1": {"mode": "auto", "index": 2}})
    sharp_pick = np.asarray(Image.open(store.cell_pick_path("c1")).convert("RGB"))
    assert not np.array_equal(last_pick, sharp_pick)
    assert int(sharp_pick.mean()) > int(last_pick.mean())


def test_sharpest_mode_ranks_the_detailed_frame(store):
    store.save_cell_frames("c1", _frames(4, sharp_at=1))
    store.save_cell_frames("c2", _frames(2))
    result = store.rebuild_sheet(_payload(), {"c1": {"mode": "sharpest"}})
    assert result["cells"]["c1"]["index"] == 1


def test_rebuild_with_a_new_layout_needs_no_re_render(store):
    store.save_cell_frames("c1", _frames(2))
    store.save_cell_frames("c2", _frames(2))
    first = store.rebuild_sheet(_payload())
    hero = _payload(sheet={"layout": "hero-left", "columns": 2, "shortEdge": 1024,
                           "aspect": "16:9", "captions": True})
    second = store.rebuild_sheet(hero)
    assert first["size"] != second["size"]
    assert second["size"] == (1808, 1024)


def test_cells_without_frames_are_reported_not_fatal(store):
    store.save_cell_frames("c1", _frames(2))
    result = store.rebuild_sheet(_payload())
    assert result["missing"] == ["c2"]
    assert result["cells"]["c2"]["index"] is None
    assert store.sheet_path.is_file()


def test_disabled_cells_are_left_out_of_the_sheet(store):
    store.save_cell_frames("c1", _frames(2))
    store.save_cell_frames("c2", _frames(2))
    payload = _payload(cells=[{"id": "c1", "pick": "auto"}, {"id": "c2", "enabled": False}])
    result = store.rebuild_sheet(payload)
    assert list(result["cells"]) == ["c1"]


def test_manifest_and_report_round_trip(store):
    store.write_manifest({"spec": _payload(), "prompts": {"c1": "hello"}})
    store.write_report("Sheet: 2 cells")
    manifest = store.read_manifest()
    assert manifest["name"] == "test_sheet"
    assert manifest["pipeline"] == store_mod.PIPELINE
    assert manifest["node_id"] == "42"
    assert store._read_report() == "Sheet: 2 cells"


def test_a_hand_pick_survives_every_later_rebuild(store):
    """A click on a frame is a decision; only the cell that was clicked may be recomputed.

    The rule modes (``auto`` / ``last`` / ``sharpest``) are recomputed on every compose - that
    is deliberate, it is how a fixed rule reaches a sheet that was already on disk. A *hand*
    pick is the opposite: it has to be recorded as such and stay recorded, or the next rebuild
    of ANY cell (or a plain "Rebuild sheet") silently replaces the frame the user chose. That
    is exactly what was reported: pick frame 9, press Rebuild, pick a frame in another cell -
    and cell 1 is back on the rule.
    """
    store.save_cell_frames("c1", _frames(5))
    store.save_cell_frames("c2", _frames(5))
    store.rebuild_sheet(_payload())                                            # both on the rule
    store.rebuild_sheet(_payload(), {"c1": {"mode": "manual", "index": 1}})
    stored = json.loads(store.picks_path.read_text(encoding="utf-8"))
    assert stored["c1"]["index"] == 1
    assert stored["c1"].get("manual") is True, "the store has to remember it was a choice"

    # Picking another cell, then a plain rebuild: neither may move c1.
    store.rebuild_sheet(_payload(), {"c2": {"mode": "manual", "index": 2}})
    assert json.loads(store.picks_path.read_text(encoding="utf-8"))["c1"]["index"] == 1
    result = store.rebuild_sheet(_payload())
    assert result["cells"]["c1"]["index"] == 1, "the hand-picked frame must survive"
    assert result["cells"]["c1"]["mode"] == "manual", "and the listing has to say why"
    assert store.scan()["cells"][0]["pickIndex"] == 1


def test_a_rule_pick_is_still_recomputed_on_an_existing_sheet(store):
    """The other half of the contract: changing the mode must reach a finished sheet."""
    store.save_cell_frames("c1", _frames(5, sharp_at=0))
    store.save_cell_frames("c2", _frames(2))
    store.rebuild_sheet(_payload(), {"c1": {"mode": "manual", "index": 4}})
    assert store.scan()["cells"][0]["pickIndex"] == 4
    result = store.rebuild_sheet(_payload(), {"c1": {"mode": "sharpest"}})
    assert result["cells"]["c1"]["index"] == 0, "choosing a rule replaces the hand-pick"
    assert result["cells"]["c1"]["mode"] == "sharpest"
    assert json.loads(store.picks_path.read_text(encoding="utf-8"))["c1"].get("manual") is not True


def test_every_rebuild_writes_the_next_dated_file(store):
    """A rebuild keeps the sheet it replaces; the render keeps one file per run.

    The render's own export is stable (a workflow's SaveImage points at it). A rebuild from the
    panel is an iteration on frames already on disk, and the sheet it would otherwise overwrite is
    a finished render - so it writes the next dated file, the folder keeps the sequence, and the
    listing follows the newest one.
    """
    store.save_cell_frames("c1", _frames(3))
    store.save_cell_frames("c2", _frames(3))
    store.rebuild_sheet(_payload(), new_export=True)
    store.rebuild_sheet(_payload(), {"c1": {"mode": "manual", "index": 1}}, new_export=True)
    store.rebuild_sheet(_payload(), {"c2": {"mode": "manual", "index": 2}}, new_export=True)

    written = sorted(path.name for path in store.dir.glob("*.png"))
    assert len(written) == 3, f"three composes, three sheets: {written}"
    assert len(set(written)) == 3, "and none of them replaced another"
    assert store.sheet_path.name == written[-1] or store.sheet_path.name in written
    assert store.scan()["sheetFile"] == store.sheet_path.name, "the listing follows what was written"
    # Every sheet that was written is still on disk and readable.
    for name in written:
        with Image.open(store.dir / name) as image:
            assert image.size[0] > 0
    # A later store (the next HTTP request) reads the manifest, so it must follow the newest
    # file too - otherwise the panel would show the sheet from before the rebuild.
    fresh_read = store_mod.SheetStore("test sheet", node_id="42")
    assert fresh_read.sheet_file == store.sheet_path.name


def test_a_manual_pick_reads_only_the_frame_it_uses(store, monkeypatch):
    """The picker must not read a whole clip to use one frame of it.

    Measured on a real sheet: 2.4s of a 3.0s re-compose was decoding 110 frames (5 cells x 22)
    that the composite then used five of - which is why clicking a frame took seconds to show. The
    index is now arithmetic unless the mode ranks, and only the picked frame is read at full size.
    """
    read: list[str] = []
    small: list[str] = []
    real_load = store_mod._load_rgb
    real_small = store_mod._load_rgb_small

    def counting_load(path):
        read.append(path.name)
        return real_load(path)

    def counting_small(path, side=store_mod.RANK_SIDE):
        small.append(path.name)
        return real_small(path, side)

    monkeypatch.setattr(store_mod, "_load_rgb", counting_load)
    monkeypatch.setattr(store_mod, "_load_rgb_small", counting_small)
    store.save_cell_frames("c1", _frames(22))
    store.save_cell_frames("c2", _frames(22))

    store.rebuild_sheet(_payload(), {"c1": {"mode": "manual", "index": 7}}, new_export=True)
    assert len(read) == 2, f"one frame per cell, not 44: {len(read)} full reads"
    assert small == [], "a hand-pick ranks nothing, so nothing is even read for ranking"

    # 'sharpest' has to look at the frames - but at small copies, and only its pick in full.
    read.clear()
    small.clear()
    store.rebuild_sheet(_payload(), {"c1": {"mode": "sharpest"}}, new_export=True)
    assert len(small) >= 22, f"the ranked cell's frames are read as small copies: {len(small)}"
    assert len(read) <= 2, f"and only the picks are read at full size: {len(read)}"


def test_the_render_keeps_one_file_for_the_run(store):
    """Without ``new_export`` a compose edits the sheet that is there (the run's export)."""
    store.save_cell_frames("c1", _frames(3))
    store.save_cell_frames("c2", _frames(3))
    store.rebuild_sheet(_payload())
    name = store.sheet_path.name
    store.rebuild_sheet(_payload(), {"c1": {"mode": "manual", "index": 1}})
    assert store.sheet_path.name == name, "the run's own file name does not move"
    assert len(list(store.dir.glob("*.png"))) == 1, "and nothing else was written"


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def test_scan_reports_cells_frames_picks_and_sheet_url(store):
    store.save_cell_frames("c1", _frames(3))
    store.save_cell_frames("c2", _frames(2))
    store.write_manifest({"spec": _payload()})
    store.rebuild_sheet(_payload())
    payload = store.scan(spec=_payload())
    assert payload["counts"] == {"cells": 2, "rendered": 2, "frames": 5}
    assert payload["sheetUrl"].startswith("/view?")
    first = payload["cells"][0]
    assert first["id"] == "c1"
    assert first["frameCount"] == 3
    assert first["frames"][0]["url"].startswith("/view?")
    assert first["cellUrl"].startswith("/view?")
    assert first["view"] == "front"


def test_scan_is_empty_but_valid_for_a_folder_that_does_not_exist(store):
    payload = store.scan(spec=_payload())
    assert payload["counts"]["cells"] == 2  # spec-only cells
    assert payload["sheetUrl"] == ""


def test_view_urls_are_relative_to_the_output_directory(store):
    """``/view`` joins ``subfolder`` onto the OUTPUT root, not onto the sheets root.

    Getting this wrong 404s every thumbnail (``subfolder=character_sheet`` instead of
    ``minimax_sheets/test_sheet``) - which is exactly what the panel showed.
    """
    store.save_cell_frames("c1", _frames(2))
    store.rebuild_sheet(_payload())
    payload = store.scan(spec=_payload())
    assert payload["sheetUrl"].startswith("/view?filename=") or "/view?" in payload["sheetUrl"]
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(payload["sheetUrl"]).query)
    assert query["subfolder"][0] == "minimax_sheets/test_sheet"
    frame_query = parse_qs(urlparse(payload["cells"][0]["frames"][0]["url"]).query)
    assert frame_query["subfolder"][0] == "minimax_sheets/test_sheet/frames/c1"
    assert frame_query["type"][0] == "output"


def test_a_sheet_outside_the_output_directory_gets_no_url(store, tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path / "other_root")
    assert store_mod._view_url(outside / "x.png") == ""


def test_list_sheet_names_lists_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "sheets_root", lambda: tmp_path / "minimax_sheets")
    store_mod.SheetStore("alpha").ensure()
    store_mod.SheetStore("beta").ensure()
    assert set(store_mod.list_sheet_names()) == {"alpha", "beta"}


# --------------------------------------------------------------------------- #
# delete / clear
# --------------------------------------------------------------------------- #
def test_delete_cell_removes_frames_and_pick(store):
    store.save_cell_frames("c1", _frames(2))
    store.save_cell_frames("c2", _frames(2))
    store.rebuild_sheet(_payload())
    removed = store.delete_cell("c1")
    assert removed >= 3  # two frames + the picked cell
    assert store.frame_files("c1") == []
    assert not store.cell_pick_path("c1").is_file()
    assert store.frame_files("c2")


def test_clear_removes_everything_it_wrote(store):
    store.save_cell_frames("c1", _frames(2))
    store.rebuild_sheet(_payload())
    store.write_report("x")
    assert store.clear() > 0
    assert not store.sheet_path.is_file()
    assert not store.picks_path.is_file()
    assert store.frame_files("c1") == []


# --------------------------------------------------------------------------- #
# card art (phase 2 of the redesign): the newest sheet per layout preset
# --------------------------------------------------------------------------- #
def _sheet_with(tmp_path, monkeypatch, name, layout, *, image="page.png", suite=None):
    """A sheet folder on disk with a manifest that remembers its layout.

    Written through the store's own writer, not by hand: the manifest file is named after the
    folder (`<name>.json`), and a fixture that guesses the name tests nothing.
    """
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path)
    store = store_mod.SheetStore(name)
    store.ensure()
    if image:
        (store.dir / image).write_bytes(b"png")
    store.write_manifest({"spec": {"render": {"layoutPreset": layout, "suite": suite or []}}})
    return store.dir


def test_gallery_art_maps_each_layout_to_its_newest_render(tmp_path, monkeypatch):
    _sheet_with(tmp_path, monkeypatch, "first hero", "hero-4")
    newer = _sheet_with(tmp_path, monkeypatch, "second hero", "hero-4")
    # Newest wins: the folder mtime is what orders them, like the Results tab.
    import os

    os.utime(newer, (newer.stat().st_atime + 10, newer.stat().st_mtime + 10))
    art = store_mod.gallery_art()
    # The folder name is sanitised ("second_hero"), which is what the panel draws from.
    assert art["layouts"]["hero-4"]["name"] == "second_hero"
    assert art["layouts"]["hero-4"]["url"].startswith("/view?filename=page.png")
    assert "subfolder=" in art["layouts"]["hero-4"]["url"], "and /view loads it from its folder"
    assert [entry["name"] for entry in art["sheets"]] == ["second_hero", "first_hero"], "newest first"


def test_gallery_art_a_suite_informs_every_board_it_drew(tmp_path, monkeypatch):
    _sheet_with(tmp_path, monkeypatch, "suite run", "refmod-suite",
                suite=["hero-4", "expressions-6", "details-sfw", "details-nsfw"])
    art = store_mod.gallery_art()
    for board in ("hero-4", "expressions-6", "details-sfw", "details-nsfw"):
        assert art["layouts"][board]["name"] == "suite_run", (
            "the page a suite drew IS what each board looks like, so it is that board's art too"
        )


def test_gallery_art_ignores_folders_with_no_sheet_yet(tmp_path, monkeypatch):
    _sheet_with(tmp_path, monkeypatch, "half rendered", "hero-4", image="")
    art = store_mod.gallery_art()
    assert art["layouts"] == {}, "no picture, no art - the card keeps the drawn arrangement"
    assert art["sheets"] == []


def test_gallery_art_is_empty_but_valid_with_no_sheets_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path / "nothing here")
    assert store_mod.gallery_art() == {"layouts": {}, "sheets": []}
