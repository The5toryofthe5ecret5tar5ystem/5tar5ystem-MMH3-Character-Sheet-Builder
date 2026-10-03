# ComfyUI-H3-Character-Sheet - output name placeholders.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""``%date:...%`` in a sheet name, and finding the run it produced.

Core ``SaveImage`` writes these placeholders literally (verified against this build:
``character_sheet-%date:hhmmss%`` produced a file with that exact name), so the syntax
belongs to the packs that implement it themselves. Ours now does - with the same
vocabulary - and the panel still finds a timestamped sheet by pattern.
"""

from __future__ import annotations

import datetime as dt

from h3cs import name_tokens as nt
from h3cs import sheet_store

FIXED = dt.datetime(2026, 10, 2, 18, 7, 5)


# --------------------------------------------------------------------------- #
# expansion
# --------------------------------------------------------------------------- #
def test_date_tokens_use_the_same_vocabulary_as_the_other_packs():
    assert nt.expand_tokens("character_sheet-%date:hhmmss%", now=FIXED) == "character_sheet-180705"
    assert nt.expand_tokens("s-%date%", now=FIXED) == "s-20261002_180705"
    assert nt.expand_tokens("s-%date:yyyy-MM-dd%", now=FIXED) == "s-2026-10-02"
    assert nt.expand_tokens("s-%date:yyyyMMdd_HHmmss%", now=FIXED) == "s-20261002_180705"
    # DD is day, as in the packs this mirrors
    assert nt.expand_tokens("s-%date:DD%", now=FIXED) == "s-02"


def test_seed_token_and_plain_names():
    assert nt.expand_tokens("sheet-%seed%", seed=42, now=FIXED) == "sheet-42"
    assert nt.expand_tokens("sheet-%date:hhmmss%_%seed%", seed=7, now=FIXED) == "sheet-180705_7"
    assert nt.expand_tokens("plain_name", seed=7, now=FIXED) == "plain_name"
    # no seed supplied: leave the token alone rather than writing "None"
    assert nt.expand_tokens("sheet-%seed%", now=FIXED) == "sheet-%seed%"


def test_unknown_placeholders_are_left_exactly_as_typed():
    assert nt.expand_tokens("sheet-%model%", now=FIXED) == "sheet-%model%"
    assert nt.expand_tokens("100%_done", now=FIXED) == "100%_done"


def test_has_tokens_and_is_expanded():
    assert nt.has_tokens("a-%date%") and nt.has_tokens("a-%date:hh%") and nt.has_tokens("a-%seed%")
    assert not nt.has_tokens("a-b")
    assert nt.is_expanded("character_sheet-180705")
    assert not nt.is_expanded("character_sheet-%date:hhmmss%")


def test_folder_pattern_matches_only_the_tokenised_tail():
    assert nt.folder_pattern("character_sheet-%date:hhmmss%") == "character_sheet-*"
    assert nt.folder_pattern("sheet-%seed%") == "sheet-*"
    assert nt.folder_pattern("sheet-%date%_x") == "sheet-*"
    assert nt.folder_pattern("plain") is None


# --------------------------------------------------------------------------- #
# finding the run
# --------------------------------------------------------------------------- #
def test_a_timestamped_name_resolves_to_the_newest_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)
    import os

    def stamp(path, when):
        path.mkdir(exist_ok=True)
        os.utime(path, (when, when))

    stamp(tmp_path / "character_sheet-170000", 1_600_000_000)
    stamp(tmp_path / "character_sheet-180705", 1_600_000_200)
    stamp(tmp_path / "character_sheet-180000", 1_600_000_300)

    resolved = sheet_store.sheet_dir("character_sheet-%date:hhmmss%")
    assert resolved.name == "character_sheet-180000", "the newest by mtime wins, not the name"

    # a folder that is not an expansion is never matched
    (tmp_path / "character_sheet-%date:hhmmss%").mkdir()
    assert sheet_store.sheet_dir("character_sheet-%date:hhmmss%").name == "character_sheet-180000"


def test_a_literal_name_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)
    assert sheet_store.sheet_dir("my sheet!").name == "my_sheet"


def test_export_stem_expands_tokens_and_stamps_plain_names():
    # The user asked for the date, so the expanded name IS the file name.
    assert nt.export_stem("character_sheet-%date:hhmmss%", now=FIXED) == "character_sheet-180705"
    # No placeholder: the run stamps one, so two runs never share a file.
    assert nt.export_stem("character_sheet", now=FIXED) == "character_sheet-20261002-180705"
    assert nt.export_stem("", now=FIXED) == "character_sheet-20261002-180705"


def test_the_store_keeps_the_resolved_name_for_its_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet_store, "sheets_root", lambda: tmp_path)
    (tmp_path / "character_sheet-180705").mkdir()
    store = sheet_store.SheetStore("character_sheet-%date:hhmmss%")
    assert store.name == "character_sheet-180705"
    assert store.dir == tmp_path / "character_sheet-180705"
    assert store.manifest_path.name == "character_sheet-180705.json"
    assert sheet_store.sheet_file_name("character_sheet-%date:hhmmss%", now=FIXED) == "character_sheet-180705.png"
