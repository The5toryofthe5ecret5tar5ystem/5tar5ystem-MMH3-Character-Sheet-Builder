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

from h3cs import sheet_routes


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
        assert isinstance(entry["widgets"], dict) and entry["widgets"], entry["id"]


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


def test_the_actions_the_panel_uses_are_all_registered():
    """The panel calls these by name; each one has to exist."""
    for action in ("list", "plan", "presets", "compose", "pick", "delete", "clear", "names"):
        assert action in sheet_routes._ACTIONS, action
