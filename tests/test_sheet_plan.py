# ComfyUI-H3-Character-Sheet - the panel's "what will this cell send?" preview
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The ``plan`` action behind the Prompt tab.

The panel cannot build the prompt itself (the planner owns that), so it asks. These
tests pin the answer: per cell, the final prompt text and the references that cell is
really wired with - which is what makes a mis-attributed reference visible before a
sheet has finished rendering.
"""

from __future__ import annotations

import asyncio
import json

from h3cs import planner as pl
from h3cs import sheet_routes

PAYLOAD = {
    "name": "preview",
    "globalPrompt": "young woman with long silver hair",
    "refs": {
        "pictures": [
            {"imageFile": "face.jpg", "role": "head, face, hair"},
            {"imageFile": "body.jpg", "role": "body and clothes"},
        ]
    },
    "cells": [
        {"id": "close", "view": "face"},
        {"id": "whole", "view": "front"},
    ],
}


class _Request:
    """Just enough of an ``aiohttp`` request for the action handler."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


def _call(body: dict) -> dict:
    response = asyncio.run(sheet_routes.sheet_action(_Request(body)))
    return json.loads(response.text)


def test_plan_tags_are_per_kind_and_in_wiring_order():
    plan = {
        "pictures": [{"slot": "a"}, {"slot": "b"}],
        "videos": [{"slot": "v"}],
        "audios": [{"slot": "s"}],
    }
    assert pl.plan_tags(plan) == ["<Picture 1>", "<Picture 2>", "<Video 1>", "<Audio 1>"]
    assert pl.plan_tags({}) == []


def test_plan_action_returns_each_cells_prompt_and_its_references():
    answer = _call({"action": "plan", "spec": PAYLOAD})
    assert answer["ok"] is True
    assert answer["action"] == "plan"
    assert [cell["id"] for cell in answer["cells"]] == ["close", "whole"]

    close, whole = answer["cells"]
    assert close["refs"] == ["<Picture 1>"], "a close-up is wired with the face picture only"
    assert "<Picture 1>" in close["prompt"]
    assert "<Picture 2>" not in close["prompt"], "never name a reference the cell was not given"
    assert "head, face, hair" in close["prompt"]

    assert whole["refs"] == ["<Picture 1>", "<Picture 2>"]
    # The user's own word "head" survives in the brackets; the claim is exclusive.
    assert "<Picture 1> (head, face, hair) is the sole source of the face and the hair." in whole["prompt"]
    assert "<Picture 2> is the sole source of the clothing and the body proportions." in whole["prompt"]
    assert "must not supply a face, a hairstyle, hair colour, hair length, skin tone or facial features" in whole["prompt"]


def test_plan_reports_which_references_will_be_blurred():
    """The preview says which tags arrive with the face already blurred out.

    Same rule the prompt uses: whatever it demotes to "must not supply a face" is the
    picture the node replaces with a blurred copy, so the panel can show it before a
    render rather than after one.
    """
    answer = _call({"action": "plan", "spec": PAYLOAD})
    close, whole = answer["cells"]
    assert close["blurred"] == [], "the close-up only receives the identity picture"
    assert whole["blurred"] == ["<Picture 2>"], "the outfit picture is the one blurred"


def test_the_blur_action_writes_a_copy_and_answers_with_it(tmp_path, monkeypatch):
    """The panel's preview: blur one reference now, look at it, then decide."""
    import cv2
    import numpy as np

    from h3cs import face_blur

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    image = np.zeros((240, 240, 3), dtype=np.uint8)
    image[90:150, 90:150] = 200
    cv2.imwrite(str(root / "h3_character_sheet" / "body.jpg"), image)
    monkeypatch.setattr(face_blur, "input_root", lambda: root)
    monkeypatch.setattr(face_blur, "detect_faces", lambda image, **_kw: [(100, 90, 140, 140)])

    answer = _call({"action": "blur", "file": "h3_character_sheet/body.jpg"})
    assert answer["ok"] is True, answer
    assert answer["action"] == "blur"
    assert answer["file"].startswith("h3_character_sheet/derived/")
    assert answer["url"].startswith("/view?filename=")
    assert "subfolder=h3_character_sheet%2Fderived" in answer["url"], "the folder is escaped"
    assert len(answer["boxes"]) == 1


def test_the_blur_preview_says_whether_the_render_would_blur_it(tmp_path, monkeypatch):
    """The eyeball preview shows the copy the render wires - or says it wires none.

    The panel sends its spec and the slot it is previewing, and the route answers with
    the same decision the render makes, so a picture that is left alone cannot be shown
    as if it had been edited.
    """
    import cv2
    import numpy as np

    from h3cs import face_blur

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    image = np.zeros((240, 240, 3), dtype=np.uint8)
    image[90:150, 90:150] = 200
    cv2.imwrite(str(root / "h3_character_sheet" / "body.jpg"), image)
    monkeypatch.setattr(face_blur, "input_root", lambda: root)
    monkeypatch.setattr(face_blur, "detect_faces", lambda image, **_kw: [(100, 90, 140, 140)])

    file = "h3_character_sheet/body.jpg"
    outfit = _call({"action": "blur", "file": file, "slot": 1, "spec": PAYLOAD})
    assert outfit["ok"] is True
    assert outfit["applies"] is True, "the outfit picture is the one the render blurs"
    assert outfit["scope"] == "hair", "the area travels with the request"

    head = _call({"action": "blur", "file": file, "slot": 1, "spec": PAYLOAD, "scope": "head"})
    assert head["scope"] == "head"
    assert head["file"] != outfit["file"], "a different area is a different copy"

    identity = _call({"action": "blur", "file": file, "slot": 0, "spec": PAYLOAD})
    assert identity["applies"] is False, "picture 1 is the identity: the render leaves it as it is"


def test_the_blur_action_answers_a_problem_as_a_message_not_a_crash(tmp_path, monkeypatch):
    import cv2
    import numpy as np

    from h3cs import face_blur

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    cv2.imwrite(str(root / "h3_character_sheet" / "noface.jpg"), np.zeros((80, 80, 3), np.uint8))
    monkeypatch.setattr(face_blur, "input_root", lambda: root)
    monkeypatch.setattr(face_blur, "detect_faces", lambda image, **_kw: [])

    answer = _call({"action": "blur", "file": "h3_character_sheet/noface.jpg"})
    assert answer["ok"] is False
    assert "no face detected" in answer["reason"]
    assert _call({"action": "blur"})["ok"] is False, "the file is required"


def test_plan_action_honours_the_scope_widget():
    every = _call({"action": "plan", "spec": PAYLOAD, "scope": "every cell"})
    close = every["cells"][0]
    assert close["refs"] == ["<Picture 1>", "<Picture 2>"]
    assert "<Picture 2>" in close["prompt"]


def test_plan_action_answers_a_bad_payload_with_a_message():
    empty = _call({"action": "plan"})
    assert empty["ok"] is False and "spec" in empty["error"]
    junk = _call({"action": "plan", "spec": {"cells": [{"id": "c"}], "refs": {"pictures": 7}}})
    assert junk["ok"] is True, "junk it can survive is a warning, not an error"
