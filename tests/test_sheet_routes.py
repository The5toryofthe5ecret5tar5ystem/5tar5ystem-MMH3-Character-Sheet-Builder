# ComfyUI-H3-Character-Sheet - route surface tests.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The action route's own contract, without a live ComfyUI.

A route is the one part of this pack the panel cannot test for itself: a typo in the action
name, a handler that never runs because the action is not registered, or a served shape that
does not match what the panel reads all pass every unit test and only show up in the browser.
So the dispatcher is driven directly here, with `web.json_response` stubbed out - the answer
is what is being checked, not aiohttp.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from h3cs import sheet_routes, sheet_store as store_mod


class _Request:
    """Bare minimum of an aiohttp request: the dispatcher only reads the JSON body."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    @property
    def text(self) -> str:
        return json.dumps(self.payload)


@pytest.fixture(autouse=True)
def _stub_responses(monkeypatch):
    monkeypatch.setattr(
        sheet_routes.web, "json_response", lambda payload, status=200: _Response(payload, status)
    )


def _call(body):
    response = asyncio.run(sheet_routes.sheet_action(_Request(body)))
    return response.payload


def test_the_presets_action_is_registered_and_served():
    """`presets` must be in the action list, or the panel gets a 400 for asking."""
    assert "presets" in sheet_routes._ACTIONS
    answer = _call({"action": "presets"})
    assert answer["ok"] is True
    assert answer["action"] == "presets"
    assert answer["default"] == "balanced"
    assert [entry["id"] for entry in answer["presets"]][0] == "balanced"
    json.dumps(answer), "the panel parses this"  # a non-serialisable preset breaks the UI


def test_the_knobs_action_is_registered_and_served():
    """The Settings tab cannot draw anything until this answers."""
    assert "knobs" in sheet_routes._ACTIONS
    answer = _call({"action": "knobs"})
    assert answer["ok"] is True
    assert answer["action"] == "knobs"
    names = [knob["name"] for knob in answer["knobs"]]
    assert "cell_size" in names and "continuity" in names
    assert "sheet_data" not in names, "the panel's own storage is not a knob"
    # The panel builds its grid from these groups, so they have to be ready to render:
    # every knob carries the label, the control kind and the value it currently has.
    grouped = [knob for group in answer["groups"] for knob in group["knobs"]]
    assert sorted(knob["name"] for knob in grouped) == sorted(names)
    assert all(knob["label"] and knob["kind"] for knob in grouped)
    assert answer["order"] == list(sheet_routes.KNOB_GROUPS)
    json.dumps(answer), "the panel parses this"


def test_every_served_preset_has_the_fields_the_panel_reads():
    for entry in _call({"action": "presets"})["presets"]:
        for key in ("id", "label", "hint", "render", "sheet", "widgets", "build", "deviates"):
            assert key in entry, f"{entry['id']} is missing {key}"
        assert isinstance(entry["widgets"], dict) and isinstance(entry["boards"], list)
        if entry["kind"] == "suite":
            # A suite arranges BOARDS, not the sheet: the arrangement comes from the layout preset
            # each board names, so widgets of its own would be dead data (test_presets says so).
            assert entry["boards"] and not entry["widgets"], entry["id"]
        else:
            assert entry["widgets"], entry["id"]
            assert not entry["boards"], entry["id"]


def test_the_help_action_is_registered_and_served():
    """The Help tab is one request: the guide plus the live file check."""
    assert "help" in sheet_routes._ACTIONS
    answer = _call({"action": "help"})
    assert answer["ok"] is True and answer["action"] == "help"
    assert answer["project"]
    assert [section["id"] for section in answer["sections"]][:2] == ["what", "quickstart"]
    assert len(answer["requirements"]) >= 4
    for item in answer["requirements"]:
        assert "ok" in item and "where" in item and item["links"], item["id"]
    assert answer["ready"] is (not answer["missing"])
    json.dumps(answer), "the panel parses this"


def test_an_unknown_action_names_the_ones_that_exist():
    answer = _call({"action": "presets!"})
    assert answer["ok"] is False
    assert "presets" in answer["error"], "the error has to name the real actions"


def test_the_save_preset_action_stores_what_the_panel_sends(tmp_path, monkeypatch):
    """Saving is one request, and the answer carries the WHOLE list back.

    That matters: the panel refills its dropdown from this answer rather than guessing what
    the store now holds, so a save and a delete are the same code path on the panel side.
    """
    monkeypatch.setattr(sheet_routes.user_presets, "store_path",
                        lambda: tmp_path / "h3_character_sheet" / "presets.json")
    assert "save-preset" in sheet_routes._ACTIONS
    answer = _call({
        "action": "save-preset",
        "name": "Route preset",
        "render": {"background": "tan"},
        "widgets": {"cell_size": 1024},
        "build": {"views": ["face"]},
    })
    assert answer["ok"] is True, answer
    assert answer["action"] == "save-preset"
    assert answer["preset"]["custom"] is True
    assert [entry["id"] for entry in answer["presets"]][-1] == answer["preset"]["id"]
    assert answer["store"].endswith("presets.json"), "the panel shows the user where it went"
    json.dumps(answer)

    # A request with no name is a refusal with a reason, not a 500.
    refused = _call({"action": "save-preset", "widgets": {"cell_size": 1024}})
    assert refused["ok"] is False
    assert "name" in refused["reason"]


# ---------------------------------------------------------------- suite boards
# A suite renders several sheets under ONE run name, one folder per board. The run folder itself
# holds no cells, so before the routes resolved a board the panel could only name the run and the
# four sheets that ARE the run were invisible: the Results tab showed nothing and Re-compose had
# nothing to re-compose. These tests drive the dispatcher, so they check the ANSWER the panel gets.

BOARDS = [
    {"id": "hero-4", "label": "Hero + 4 panels", "folder": "hero-4", "cells": 5, "layout": "hero-left"},
    {"id": "expressions-6", "label": "Expressions 2x3", "folder": "expressions-6", "cells": 6,
     "layout": "grid"},
    {"id": "details-sfw", "label": "Closeups 2x2 (SFW)", "folder": "details-sfw", "cells": 4,
     "layout": "grid"},
]


@pytest.fixture
def suite_run(tmp_path, monkeypatch):
    """A run folder with a suite record and two boards that have something on disk."""
    root = tmp_path / "minimax_sheets"
    run = root / "character_sheet-20261005_120000"
    (run / "hero-4" / "cells").mkdir(parents=True)
    (run / "hero-4" / "cells" / "face-neutral.png").write_bytes(b"png")
    (run / "hero-4" / "hero-4-20261005-120100.png").write_bytes(b"png")
    (run / "expressions-6").mkdir(parents=True)
    # Patch the roots FIRST: SheetStore(name) resolves and writes through them, so a store built
    # before the patch would put the manifest in the real output folder.
    monkeypatch.setattr(store_mod, "sheets_root", lambda: root)
    monkeypatch.setattr(sheet_routes.sheet_store, "sheets_root", lambda: root)
    store = store_mod.SheetStore(run.name)
    store.write_manifest({"spec": {"render": {"suite": [entry["id"] for entry in BOARDS]}},
                          "suite": {"name": run.name, "boards": list(BOARDS), "exported": ""}})
    return run


class _GetRequest:
    """The GET route reads only the query string."""

    def __init__(self, query):
        self.query = query


def _get(query):
    response = asyncio.run(sheet_routes.sheet_list(_GetRequest(query)))
    return response.payload, response.status


def test_a_suite_run_answers_with_its_first_board_and_lists_them_all(suite_run):
    answer, status = _get({"name": suite_run.name})
    assert status == 200 and answer["ok"] is True
    # No board named: the run resolves to the hero sheet, not to a folder with no cells in it.
    assert answer["board"] == "hero-4"
    assert answer["sheet"]["board"] == "hero-4"
    assert answer["sheet"]["sheetFile"].startswith("hero-4-"), answer["sheet"]["sheetFile"]
    # Every board is offered, in render order, with what it will draw and whether it landed.
    assert [entry["folder"] for entry in answer["boards"]] == ["hero-4", "expressions-6", "details-sfw"]
    assert [entry["cells"] for entry in answer["boards"]] == [5, 6, 4]
    assert [entry["rendered"] for entry in answer["boards"]] == [True, False, False]
    assert answer["boards"][1]["label"] == "Expressions 2x3"
    json.dumps(answer)


def test_a_named_board_is_honoured_and_a_bogus_one_is_refused(suite_run):
    answer, _status = _get({"name": suite_run.name, "board": "expressions-6"})
    assert answer["board"] == "expressions-6"
    assert answer["sheet"]["dir"].endswith("expressions-6"), answer["sheet"]["dir"]
    assert answer["sheet"]["cells"] == [], "that board has not rendered"

    # A board the run does not have is a refusal that names the ones it does - answered from the
    # run folder instead, the panel would silently show nothing and look broken.
    refused, status = _get({"name": suite_run.name, "board": "nope"})
    assert refused["ok"] is False and status == 400
    assert "nope" in refused["error"] and "hero-4" in refused["error"], refused["error"]


def test_actions_are_scoped_to_the_board_they_name(suite_run):
    """Clear one board and the others are untouched: the board IS the folder."""
    cleared = _call({"action": "clear", "name": suite_run.name, "board": "hero-4"})
    assert cleared["ok"] is True, cleared
    assert cleared["board"] == "hero-4"
    assert not (suite_run / "hero-4" / "cells" / "face-neutral.png").exists()
    # An action with no board named takes the run's first board, so an older caller still works.
    assert (suite_run / "expressions-6").is_dir()
    listed = _call({"action": "list", "name": suite_run.name})
    assert listed["board"] == "hero-4" and [entry["folder"] for entry in listed["boards"]][0] == "hero-4"


def test_a_normal_sheet_run_has_no_boards(tmp_path, monkeypatch):
    """The board plumbing must be invisible to a single-sheet run."""
    root = tmp_path / "minimax_sheets"
    (root / "plain_sheet").mkdir(parents=True)
    monkeypatch.setattr(store_mod, "sheets_root", lambda: root)
    monkeypatch.setattr(sheet_routes.sheet_store, "sheets_root", lambda: root)
    answer, status = _get({"name": "plain_sheet"})
    assert status == 200 and answer["ok"] is True
    assert answer["board"] == ""
    assert "boards" not in answer
    # And a board named for it is refused rather than quietly ignored.
    refused, status = _get({"name": "plain_sheet", "board": "hero-4"})
    assert refused["ok"] is False and status == 400
    assert "not a suite run" in refused["error"]


def test_the_delete_preset_action_refuses_built_ins(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet_routes.user_presets, "store_path",
                        lambda: tmp_path / "h3_character_sheet" / "presets.json")
    assert "delete-preset" in sheet_routes._ACTIONS
    saved = _call({"action": "save-preset", "name": "Route preset", "widgets": {"steps": 8}})
    preset_id = saved["preset"]["id"]

    answer = _call({"action": "delete-preset", "id": preset_id})
    assert answer["ok"] is True
    assert answer["removed"] == preset_id
    assert preset_id not in [entry["id"] for entry in answer["presets"]]

    built_in = _call({"action": "delete-preset", "id": "balanced"})
    assert built_in["ok"] is False
    assert "built-in" in built_in["reason"]


def test_the_actions_the_panel_uses_are_all_registered():
    """The panel calls these by name; each one has to exist."""
    for action in ("list", "plan", "presets", "save-preset", "delete-preset",
                   "compose", "pick", "delete", "clear", "names"):
        assert action in sheet_routes._ACTIONS, action


def test_the_blur_action_runs_the_clip_pass_for_a_reference_clip(monkeypatch):
    """A clip is previewed with the clip pass - sampled detection, tracked box, re-encode.

    The panel sends `kind`; a bare request is sniffed from the suffix, so a curl or an older
    panel still asks for the right work instead of blurring a clip as if it were one still.
    """
    calls = []

    def _clip(name, **kwargs):
        calls.append(("clip", name, kwargs))
        return {"ok": False, "reason": "no face detected in the clip"}

    def _still(name, **kwargs):
        calls.append(("still", name, kwargs))
        return {"ok": False, "reason": "no face detected"}

    monkeypatch.setattr(sheet_routes.face_blur, "blur_video_faces", _clip)
    monkeypatch.setattr(sheet_routes.face_blur, "blur_image_faces", _still)

    answer = _call({"action": "blur", "file": "h3_character_sheet/clip.mp4", "kind": "video"})
    assert answer["ok"] is False and "clip" in answer["reason"]
    assert calls[-1][0] == "clip", "the clip pass ran"

    # No kind given: the suffix decides.
    _call({"action": "blur", "file": "h3_character_sheet/clip.MP4"})
    assert calls[-1][0] == "clip", "an upper-case suffix still reads as a clip"
    _call({"action": "blur", "file": "h3_character_sheet/still.png"})
    assert calls[-1][0] == "still", "a picture still goes through the picture pass"


def test_the_blur_action_says_which_KIND_of_reference_applies():
    """`applies` is read from the plan by kind, so a clip is reported by its own slot."""
    payload = {
        "refs": {
            "pictures": [{"imageFile": "a.png", "role": "face and hair"}],
            "videos": [{"videoFile": "b.mp4", "role": "clothing and body"}],
        },
        "cells": [{"id": "c", "view": "portrait"}],
    }
    answer = _call({"action": "blur", "file": "h3_character_sheet/b.mp4", "kind": "video",
                    "slot": 0, "spec": payload})
    assert answer["applies"] is True, "auto blurs the outfit clip of a second person"
    # The same slot number on a picture is a different reference entirely.
    answer = _call({"action": "blur", "file": "h3_character_sheet/a.png", "slot": 0, "spec": payload})
    assert answer["applies"] is False, "the identity picture is left alone by auto"


def test_the_plan_report_names_blurred_clips_too():
    """A cell that gets a blurred clip must say so, or the panel cannot show it before a render."""
    payload = {
        "refs": {
            "pictures": [{"imageFile": "a.png", "role": "face and hair"}],
            "videos": [{"videoFile": "b.mp4", "role": "clothing and body"}],
        },
        "cells": [{"id": "c", "view": "portrait", "frames": 124}],
    }
    answer = _call({"action": "plan", "spec": payload})
    assert answer["ok"] is True
    blurred = [tag for cell in answer["cells"] for tag in cell["blurred"]]
    assert "<Video 1>" in blurred, blurred
