# ComfyUI-H3-Character-Sheet - frame picking with latent continuation.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The pick side of continuation, on a real sheet folder.

A continuing cell's first frames ARE the previous cell's last frames (they are
re-rendered from the guide), so a picker that ranks them is ranking a duplicate: the
sheet would show the same image twice. ``sharpest`` is where that bites, so the case
is built with the sharpest frame deliberately inside the hand-over window.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from h3cs import sheet_layout as layout
from h3cs import sheet_spec as ss
from h3cs import sheet_store as store_mod


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path)
    return store_mod.SheetStore("continuity sheet", node_id="7")


def _frames(count: int, *, sharp_at: int | None = None):
    base = np.full((16, 16, 3), 40, dtype=np.uint8)
    out = []
    for index in range(count):
        if sharp_at is not None and index == sharp_at:
            checker = (np.indices((16, 16)).sum(axis=0) % 2).astype(np.uint8)
            out.append(np.stack([checker * 255] * 3, axis=-1))
        else:
            out.append(base.copy())
    return out


def _payload(continuity: str, **overrides):
    data = {
        "name": "continuity sheet",
        "refs": {"pictures": [{"imageFile": "f.png", "role": "face"}]},
        "sheet": {"layout": "grid", "columns": 1, "shortEdge": 512, "aspect": "3:2",
                  "captions": False},
        "render": {"continuity": continuity, "framesPerCell": 22},
        "cells": [
            {"id": "c1", "view": "front", "pick": "sharpest", "frames": 22},
            {"id": "c2", "view": "profile", "pick": "sharpest", "frames": 22},
        ],
    }
    data.update(overrides)
    return data


def test_settle_window_keeps_the_pose_the_cell_was_asked_for():
    """The measured shape of a real chained clip: sharpest frames are the OLD pose.

    On the shipped 5-cell sheet the 90 degree turn landed at frame 8 of 22 and the clip
    held still from there, while ``frame_sharpness`` fell monotonically from frame 0 (the
    hand-over is the sharpest part). Ranking the whole clip picked frame 5 - the frontal
    pose the previous cell already had.
    """
    frames = [old_pose_frame(index) for index in range(22)]
    assert layout.pick_frame_index(frames, mode="sharpest") == 0, (
        "the fixture reproduces the trap: the pre-turn frames score highest"
    )
    picked = layout.pick_frame_index(
        frames, mode="sharpest", skip=5, settle=ss.continuity_settle(22, 5)
    )
    assert picked >= 12, f"a chained cell must pick from its settled tail, got {picked}"


def test_continuity_settle_is_two_hand_overs_and_a_third_of_the_clip():
    assert ss.continuity_settle(22, 5) == 10
    assert ss.continuity_settle(39, 5) == 13, "a third of a longer clip"
    assert ss.continuity_settle(22, 0) == 7, "an independent clip has nothing to settle"
    assert ss.continuity_settle(0, 5) == 10


def old_pose_frame(index: int):
    """Frames 0-7 are the sharp hand-over; 8+ are the settled, smoother new pose."""
    if index < 8:
        checker = (np.indices((32, 32)).sum(axis=0) % 2).astype(np.uint8)
        return np.stack([checker * 255] * 3, axis=-1)
    ramp = np.tile(np.arange(32, dtype=np.uint8) * 4, (32, 1))
    return np.stack([ramp] * 3, axis=-1)


def test_the_hand_over_frames_are_never_picked(store):
    """The sharpest frame of c2 sits inside the hand-over, so it must be skipped."""
    store.save_cell_frames("c1", _frames(22, sharp_at=21))
    store.save_cell_frames("c2", _frames(22, sharp_at=0))
    result = store.rebuild_sheet(_payload("on"))
    assert result["cells"]["c1"]["index"] == 21  # independent: its sharp frame wins
    settled_from = 22 - ss.continuity_settle(22, 5)
    assert result["cells"]["c2"]["index"] >= settled_from, (
        "a continuing cell picks from its settled tail, not the hand-over"
    )
    assert result["cells"]["c2"]["continuity"] == 5


def test_with_continuation_off_nothing_is_skipped(store):
    store.save_cell_frames("c1", _frames(22, sharp_at=21))
    store.save_cell_frames("c2", _frames(22, sharp_at=0))
    result = store.rebuild_sheet(_payload("off"))
    assert result["cells"]["c2"]["index"] == 0
    assert "continuity" not in result["cells"]["c2"]


def test_an_explicit_pick_is_still_honoured_on_a_continuing_cell(store):
    """The panel shows the frames; a hand-picked index is the user's own call."""
    store.save_cell_frames("c1", _frames(22))
    store.save_cell_frames("c2", _frames(22, sharp_at=1))
    result = store.rebuild_sheet(_payload("on"), {"c2": {"mode": "auto", "index": 1}})
    assert result["cells"]["c2"]["index"] == 1


def test_a_re_composite_recomputes_the_automatic_pick(store):
    """A stored automatic index must not freeze an older picker's answer.

    The first compose of a chained sheet stored index 5 for c2 (before the settle window
    existed); every re-composite then replayed 5, which is how a fixed picker looks like
    it does nothing.
    """
    store.save_cell_frames("c1", _frames(22))
    store.save_cell_frames("c2", _frames(22, sharp_at=0))
    store.write_picks({"c1": {"mode": "sharpest", "index": 3}, "c2": {"mode": "sharpest", "index": 5}})
    result = store.rebuild_sheet(_payload("on"))
    assert result["cells"]["c2"]["index"] >= 22 - ss.continuity_settle(22, 5), (
        "the automatic pick is recomputed from the frames"
    )
    assert result["cells"]["c1"]["index"] == 0, "an independent cell ranks its own sharpest frame"


def test_a_hand_picked_frame_survives_a_re_composite(store):
    """Clicking a thumbnail is a decision; a later compose must not undo it."""
    store.save_cell_frames("c1", _frames(22))
    store.save_cell_frames("c2", _frames(22, sharp_at=0))
    first = store.rebuild_sheet(_payload("on"), {"c2": {"mode": "auto", "index": 2}})
    assert first["cells"]["c2"]["index"] == 2
    assert json.loads(store.picks_path.read_text(encoding="utf-8"))["c2"]["manual"] is True
    again = store.rebuild_sheet(_payload("on"))
    assert again["cells"]["c2"]["index"] == 2, "the hand-pick is still the pick"


def test_a_re_composite_makes_the_same_choice_as_the_render(store):
    """The skip comes from the spec, not from the run, so a re-composite agrees."""
    store.save_cell_frames("c1", _frames(22))
    store.save_cell_frames("c2", _frames(22, sharp_at=0))
    first = store.rebuild_sheet(_payload("on"))
    again = store.rebuild_sheet(_payload("on"))
    settled_from = 22 - ss.continuity_settle(22, 5)
    assert first["cells"]["c2"]["index"] == again["cells"]["c2"]["index"] >= settled_from
