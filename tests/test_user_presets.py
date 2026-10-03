# ComfyUI-H3-Character-Sheet - the presets a user saved.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Saved presets: the settings someone actually arrived at, kept across sessions.

The interesting properties are all about trust and survival, not features:

* a saved preset and a built-in one are the SAME object type and shape, so everything
  downstream treats them alike - and the one difference (`custom`) is what makes a preset
  deletable;
* the store validates on the way in (JSON scalars only, tick lists filtered against the
  sheet's own vocabulary), because it is fed by an HTTP body;
* every failure mode is a sentence, not an exception: a missing file, a corrupt file, a
  read-only folder, a request with no name - a preset is never a reason a render fails;
* where it lives is the user directory, so it survives a ComfyUI update and is not confused
  with render output.

Every test points the store at a temporary path: the real one is the running ComfyUI's user
folder, and a test suite must not leave presets in it.
"""

from __future__ import annotations

import json

import pytest

from h3cs import presets as preset_mod
from h3cs import sheet_spec as ss
from h3cs import user_presets as up


@pytest.fixture(autouse=True)
def _temporary_store(tmp_path, monkeypatch):
    """Point the store at a tmp path - never at the real ComfyUI user folder."""
    path = tmp_path / up.STORE_DIRNAME / up.STORE_FILENAME
    monkeypatch.setattr(up, "store_path", lambda: path)
    return path


def _body(name="My house style", **overrides):
    body = {
        "name": name,
        "render": {"background": "tan", "continuity": "auto", "exportVideo": True, "framesPerCell": 22},
        "sheet": {"layout": "hero-left", "columns": 2, "aspect": "3:2", "shortEdge": 1536},
        "widgets": {"cell_size": 1024, "steps": 8, "sheet_layout": "hero-left", "export_video": True},
        "build": {"views": ["face", "front"], "poses": ["neutral"], "expressions": ["neutral"]},
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# saving
# --------------------------------------------------------------------------- #
def test_a_saved_preset_comes_back_as_a_normal_preset():
    result = up.save_preset(_body())
    assert result["ok"] is True, result
    saved = result["preset"]
    assert saved["custom"] is True
    assert saved["label"] == "My house style"
    assert saved["id"].startswith(up.CUSTOM_PREFIX)

    stored = up.saved_presets()
    assert len(stored) == 1
    assert stored[0].custom is True
    # The lookup the rest of the pack uses has to find it too, or applying it 404s.
    assert preset_mod.preset_by_id(saved["id"]) is not None
    assert [entry["id"] for entry in preset_mod.preset_list()][-1] == saved["id"]


def test_a_saved_preset_has_the_same_shape_as_a_built_in_one():
    """One shape, two origins: the panel reads them with the same code."""
    saved = up.save_preset(_body())["preset"]
    built_in = preset_mod.PRESETS[0].to_dict()
    assert set(saved) == set(built_in)
    assert saved["custom"] is True
    assert built_in["custom"] is False, "only what the user saved is deletable"
    assert [entry["custom"] for entry in preset_mod.preset_list()] == [
        False, False, False, False, False, False, False, True,
    ], "built-ins first, the user's own last"


def test_the_name_is_required_and_trimmed():
    assert up.save_preset({"render": {"background": "tan"}})["ok"] is False
    assert up.save_preset({"name": "   "})["ok"] is False
    assert up.save_preset(None)["ok"] is False
    assert up.saved_presets() == [], "a refused save writes nothing"
    saved = up.save_preset({"name": f"  {'x' * 60}  "})["preset"]
    assert len(saved["label"]) == up.MAX_NAME_LENGTH
    assert saved["label"] == saved["label"].strip()


def test_junk_values_never_reach_the_store():
    """The store is fed by an HTTP body: one shape, or the panel renders [object Object]."""
    saved = up.save_preset(_body(
        render={"background": "tan", "nested": {"a": 1}, "list": [1], "none": None, "nan": float("nan")},
        widgets={"cell_size": 1024, "bogus": {"deep": True}, "flag": False, "ratio": 1.5},
        sheet={"layout": "grid", "columns": "3"},
    ))["preset"]
    assert saved["render"] == {"background": "tan"}
    assert saved["widgets"] == {"cell_size": 1024, "flag": False, "ratio": 1.5}
    assert saved["sheet"] == {"layout": "grid", "columns": "3"}, "strings are values too"
    # And the stored file round-trips as JSON, which is the whole point of flattening.
    json.dumps(saved)


def test_unknown_render_and_sheet_keys_are_dropped():
    saved = up.save_preset(_body(render={"background": "tan", "settings": 3},
                                 sheet={"layout": "grid", "somethingElse": 1}))["preset"]
    assert saved["render"] == {"background": "tan"}
    assert saved["sheet"] == {"layout": "grid"}


def test_tick_lists_are_filtered_against_the_sheet_vocabulary():
    """A view the node cannot render must not reach the payload as a tick."""
    saved = up.save_preset(_body(build={
        "views": ["face", "nonsense", "FACE", "front"],
        "poses": ["neutral", "hovering"],
        "expressions": [],
    }))["preset"]
    assert saved["build"] == {"views": ["face", "front"], "poses": ["neutral"]}


def test_a_duplicate_name_gets_its_own_id():
    first = up.save_preset(_body(name="House style"))["preset"]
    second = up.save_preset(_body(name="house STYLE"))["preset"]
    assert first["id"] != second["id"]
    assert second["id"].startswith(first["id"]), "the same slug, disambiguated"
    assert len(up.saved_presets()) == 2, "both stay usable"


def test_the_hint_says_what_was_saved():
    saved = up.save_preset(_body())["preset"]
    assert saved["hint"].startswith("Saved from this node:")
    assert "1024px cells" in saved["hint"]
    assert "8 steps" in saved["hint"]
    assert "neutral tan backdrop" in saved["hint"], "the backdrop is named, not spelled as a key"

    # A hint from the caller wins: it may know something the fields do not say.
    assert up.save_preset(_body(hint="My Tuesday look"))["preset"]["hint"] == "My Tuesday look"


def test_the_departures_from_the_node_defaults_are_computed_not_trusted(monkeypatch):
    """`deviates` is what the panel prints as "Changes: ..." - so it is derived here."""
    monkeypatch.setattr(up, "schema_defaults", lambda: {"cell_size": 1024, "steps": 8, "sheet_columns": 2})
    saved = up.save_preset(_body(widgets={"cell_size": 2048, "steps": 8, "unknown": 5}))["preset"]
    assert saved["deviates"] == ["cell_size"], "one departure, and only for a known widget"


def test_without_a_readable_schema_nothing_is_claimed(monkeypatch):
    monkeypatch.setattr(up, "schema_defaults", lambda: {})
    saved = up.save_preset(_body())["preset"]
    assert saved["deviates"] == [], "'unknown' must not read as 'changed'"


# --------------------------------------------------------------------------- #
# the store file itself
# --------------------------------------------------------------------------- #
def test_the_store_directory_is_created_on_demand(_temporary_store):
    assert not _temporary_store.parent.exists()
    up.save_preset(_body())
    assert _temporary_store.exists()


def test_a_corrupt_store_reads_as_empty_and_the_next_save_replaces_it(_temporary_store):
    _temporary_store.parent.mkdir(parents=True)
    _temporary_store.write_text("{not json at all")
    assert up.saved_presets() == []
    assert up.save_preset(_body())["ok"] is True, "a broken file must not block the next save"
    assert len(up.saved_presets()) == 1


def test_a_store_full_of_nonsense_skips_the_broken_records(_temporary_store):
    _temporary_store.parent.mkdir(parents=True)
    _temporary_store.write_text(json.dumps([
        {"id": "custom-good", "name": "Good", "widgets": {"cell_size": 1024}},
        {"name": "no id at all"},
        "not even an object",
    ]))
    assert [preset.id for preset in up.saved_presets()] == ["custom-good"]


def test_the_store_accepts_the_older_flat_list_shape(_temporary_store):
    """A file written by an earlier version (a bare list) still loads."""
    _temporary_store.parent.mkdir(parents=True)
    _temporary_store.write_text(json.dumps([{"id": "custom-old", "name": "Old"}]))
    assert [preset.id for preset in up.saved_presets()] == ["custom-old"]


def test_the_store_is_capped(monkeypatch):
    monkeypatch.setattr(up, "MAX_PRESETS", 2)
    assert up.save_preset(_body(name="one"))["ok"] is True
    assert up.save_preset(_body(name="two"))["ok"] is True
    refused = up.save_preset(_body(name="three"))
    assert refused["ok"] is False
    assert "delete one first" in refused["reason"]
    assert len(up.saved_presets()) == 2


def test_a_failed_write_is_a_reason_not_a_crash(monkeypatch, tmp_path):
    """A read-only user folder must not take a render down with it."""
    monkeypatch.setattr(up, "store_path", lambda: tmp_path / "nowhere" / "presets.json")

    def _explode(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(up, "_write_records", _explode)
    result = up.save_preset(_body())
    assert result["ok"] is False
    assert "read-only" in result["reason"]


# --------------------------------------------------------------------------- #
# deleting
# --------------------------------------------------------------------------- #
def test_deleting_a_saved_preset_removes_it():
    saved = up.save_preset(_body())["preset"]
    result = up.delete_preset(saved["id"])
    assert result["ok"] is True
    assert result["removed"] == saved["id"]
    assert up.saved_presets() == []
    assert preset_mod.preset_by_id(saved["id"]) is None


def test_deleting_is_case_insensitive_like_every_other_lookup():
    saved = up.save_preset(_body())["preset"]
    assert up.delete_preset(saved["id"].upper())["ok"] is True


def test_a_built_in_preset_cannot_be_deleted():
    """The pack's own recommendations are not the user's to remove."""
    for built_in in preset_mod.PRESETS:
        result = up.delete_preset(built_in.id)
        assert result["ok"] is False, built_in.id
        assert "built-in" in result["reason"]
    assert len(preset_mod.PRESETS) == 7, "and nothing was removed on the way"


def test_deleting_something_that_is_not_there_says_so():
    result = up.delete_preset("custom-imaginary")
    assert result["ok"] is False
    assert "no saved preset" in result["reason"]
    assert up.delete_preset("")["ok"] is False


# --------------------------------------------------------------------------- #
# a saved preset has to be usable, not just stored
# --------------------------------------------------------------------------- #
def test_a_saved_preset_merges_into_a_payload_and_parses():
    """The panel applies it through `apply_to_payload`; the node then parses that."""
    saved = up.save_preset(_body())["preset"]
    payload = {
        "version": 1,
        "name": "from a preset",
        "refs": {"pictures": [{"imageFile": "face.png", "role": "face and hair"}]},
        "cells": [{"id": "c1", "view": "front"}],
    }
    merged = preset_mod.apply_to_payload(payload, saved["id"])
    spec = ss.parse_sheet_spec(merged)
    assert spec.render.preset == saved["id"]
    assert spec.render.background == "tan"
    assert spec.render.continuity == "auto"
    assert spec.layout.layout == "hero-left"
    assert spec.layout.columns == 2
    assert spec.layout.short_edge == 1536
    unexpected = [line for line in spec.warnings if "snapped up" not in line]
    assert unexpected == [], f"a saved preset must parse cleanly: {unexpected}"


def test_the_saved_ticks_build_the_cells_a_preset_promises():
    """The panel builds cells from these ticks - so they have to make cells."""
    saved = up.save_preset(_body(build={"views": ["face", "front"], "poses": ["neutral"],
                                       "expressions": ["neutral"]}))["preset"]
    cells = ss.cell_matrix(views=saved["build"]["views"], poses=saved["build"]["poses"],
                           expressions=saved["build"]["expressions"])
    assert [cell["id"] for cell in cells] == ["face-neutral-neutral", "front-neutral-neutral"]


def test_the_defaults_never_come_from_a_saved_file():
    """A widget absent from the schema has no default: claiming one would invent a change."""
    assert up.deviates_for({"anything": 1}, {}) == ()
    assert up.deviates_for({"steps": 8}, {"steps": 8}) == ()
    assert up.deviates_for({"steps": 20}, {"steps": 8}) == ("steps",)
