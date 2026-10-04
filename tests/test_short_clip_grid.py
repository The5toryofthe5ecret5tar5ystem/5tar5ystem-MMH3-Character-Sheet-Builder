"""Character Sheet Builder - short clips, the frame grid, and continuation.

H3 samples 5, 22, 39, 56... frames and nothing in between, so a requested length is rounded
UP: asking for 8 or 12 frames renders 22. That matters twice over, and both halves are
pinned here because they are easy to get wrong in opposite directions:

* a 22-frame render is not "a little longer than 8" - it is 2.75x the sampling work, and
  the user should be told rather than silently charged for it;
* continuation needs a cell LONGER than its 5-frame hand-over. On this grid only 5 and 22
  are reachable through the widget, so a 5-frame cell cannot continue (and is skipped),
  while anything from 6 to 21 becomes a 22-frame cell with 17 frames of its own. There is
  no reachable length where the hand-over eats the whole clip.

Measured on real renders (2026-10-03): in a chained 22-frame cell the move to the cell's own
pose landed at frame 8 for a 90 degree turn and at frame 12 for a pose change, with the clip
settled from there - which is what ``continuity_settle`` covers.
"""

from __future__ import annotations

from h3cs import planner as pl
from h3cs import sheet_spec as ss


def _spec(frames, mode="auto", count=3, views=("front", "front", "front")):
    cells = [{"id": f"c{i + 1}", "view": views[i % len(views)], "frames": frame}
             for i, frame in enumerate([frames] * count)]
    return ss.parse_sheet_spec({
        "name": "snap probe",
        "refs": {"pictures": [{"imageFile": "a.png", "role": "face and hair"}]},
        "render": {"continuity": mode},
        "cells": cells,
    })


def test_the_grid_is_five_then_steps_of_seventeen():
    assert [ss.align_h3_frames(n) for n in (1, 5, 6, 12, 22, 23, 39, 40)] == [5, 5, 22, 22, 22, 39, 39, 56]


def test_a_requested_length_is_reported_when_it_is_rounded_up():
    for requested, resolved in ((5, 5), (8, 22), (12, 22), (23, 39)):
        spec = _spec(requested)
        assert spec.cells[0].frames == resolved
        snapped = [line for line in spec.warnings if "snapped up" in line]
        if requested == resolved:
            assert snapped == [], "no note when the request already fits the grid"
        else:
            assert len(snapped) == 3, "one note per cell, so the report matches the plan"
            assert f"{requested} frame(s) snapped up to {resolved}" in snapped[0]


def test_short_cells_cannot_continue_because_the_hand_over_would_fill_them():
    """5 is the only short length the widget can reach, and it is skipped - not broken."""
    spec = _spec(5, mode="on")
    warnings: list[str] = []
    plan = ss.continuity_plan(spec, warnings=warnings)
    assert set(plan.values()) == {0}
    assert any("skipped" in line for line in warnings)


def test_a_six_frame_request_becomes_a_twenty_two_frame_cell_with_room_to_move():
    spec = _spec(6, mode="on")
    plan = ss.continuity_plan(spec)
    assert spec.cells[1].frames == 22
    assert plan["c2"] == ss.CONTINUITY_FRAMES
    # 22 - 5 = 17 frames of the cell's own, and the picker only ranks the settled tail.
    assert 22 - ss.CONTINUITY_FRAMES == 17
    assert 22 - ss.continuity_settle(22, ss.CONTINUITY_FRAMES) == 12


def test_the_snap_note_reaches_the_run_report():
    spec = _spec(8)
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    assert any("snapped up to 22" in line for line in lines)
    assert any("[0] c1: front/neutral/neutral · 22f" in line for line in lines)


def test_a_fully_snapped_sheet_is_still_a_valid_plan():
    """The user's actual scenario: 4-6 cells at 5-12 frames each."""
    spec = ss.parse_sheet_spec({
        "name": "short sheet",
        "refs": {"pictures": [{"imageFile": "a.png", "role": "face and hair"}]},
        "render": {"continuity": "auto"},
        "cells": [{"id": "face", "view": "face", "frames": 5},
                  {"id": "portrait", "view": "portrait", "frames": 8},
                  {"id": "front", "view": "front", "frames": 12},
                  {"id": "profile", "view": "profile", "frames": 12},
                  {"id": "back", "view": "back", "frames": 12}],
    })
    assert [cell.frames for cell in spec.cells] == [5, 22, 22, 22, 22]
    plan = ss.continuity_plan(spec)
    # face -> portrait and portrait -> front are framing changes under 'auto'; the
    # full-body run (front -> profile -> back) chains, which is how a turnaround turns.
    assert plan == {"face": 0, "portrait": 0, "front": 0, "profile": 5, "back": 5}
    items = pl.cell_work_items(spec)
    assert [item["frames"] for item in items] == [5, 22, 22, 22, 22]
