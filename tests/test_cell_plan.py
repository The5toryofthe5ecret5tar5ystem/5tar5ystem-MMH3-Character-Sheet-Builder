# ComfyUI-H3-Character-Sheet - what runs when the cell list is empty.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""An empty cell list must not mean "render a sheet I never asked for".

A payload without cells used to jump straight to the curated 8-view matrix, which
is how a two-view request turned into eight renders (and 176 frames) the user never
asked for. The panel's ticks now travel with the payload, so:

* ticks + no cells  -> exactly the cells the ticks imply,
* no ticks, no cells -> the curated matrix, announced in the report.
"""

from __future__ import annotations

import json

from h3cs import planner as pl
from h3cs import sheet_plan, sheet_spec


def _resolve(payload: dict, *, frames_per_cell: int = 22) -> sheet_spec.SheetSpec:
    """Plan a payload exactly like the node does, then parse it."""
    planned = sheet_plan.plan_payload(json.loads(json.dumps(payload)), frames_per_cell=frames_per_cell)
    return sheet_spec.parse_sheet_spec(planned)


# --------------------------------------------------------------------------- #
# the ticks
# --------------------------------------------------------------------------- #
def test_ticks_build_exactly_those_cells():
    spec = _resolve(
        {
            "name": "tick test",
            "build": {"views": ["face", "front"], "poses": ["neutral"], "expressions": ["neutral"]},
            "cells": [],
        }
    )
    assert [cell.id for cell in spec.cells] == ["face-neutral-neutral", "front-neutral-neutral"], (
        "two ticked views must be two cells, not the eight-view matrix"
    )
    assert any("built the 2 cell(s) the panel ticks asked for" in w for w in spec.warnings), spec.warnings
    assert any("face, front" in w for w in spec.warnings), "the notice names the ticks"


def test_the_notice_reaches_the_compositor_and_the_manifest():
    spec = _resolve({"build": {"views": ["face"], "poses": [], "expressions": []}, "cells": []})
    forwarded = pl.grid_payload(spec, name=spec.name)
    assert any(sheet_plan.NO_CELLS_TICKS in w for w in forwarded["warnings"]), forwarded["warnings"]
    assert forwarded["build"]["views"] == ["face"], "ticks round-trip into the manifest"


def test_ticks_expand_poses_and_expressions_like_the_build_button():
    spec = _resolve(
        {
            "build": {
                "views": ["front"],
                "poses": ["neutral", "a-pose", "t-pose"],
                "expressions": ["neutral"],
            },
            "cells": [],
        }
    )
    assert [cell.id for cell in spec.cells] == [
        "front-neutral-neutral",
        "front-a-pose-neutral",
        "front-t-pose-neutral",
    ]
    assert all(cell.frames == 22 for cell in spec.cells), "ticks follow the frames_per_cell widget"
    assert all(cell.view == "front" for cell in spec.cells)


def test_a_body_view_with_no_pose_ticked_still_renders_the_neutral_one():
    spec = _resolve({"build": {"views": ["front", "back"], "poses": [], "expressions": []}, "cells": []})
    assert [cell.id for cell in spec.cells] == ["front-neutral-neutral", "back-neutral-neutral"]


def test_ticked_frames_follow_the_frame_widget():
    spec = _resolve(
        {"build": {"views": ["portrait"], "expressions": ["smile"]}, "cells": []},
        frames_per_cell=56,
    )
    assert [cell.id for cell in spec.cells] == ["portrait-neutral-smile"]
    assert spec.cells[0].frames == 56, "a tick-built cell must not pin its own length"


# --------------------------------------------------------------------------- #
# the last resort
# --------------------------------------------------------------------------- #
def test_no_ticks_and_no_cells_is_the_curated_matrix_and_says_so():
    spec = _resolve({"cells": [], "build": {}})
    assert [cell.id for cell in spec.cells] == [cell["id"] for cell in pl.default_cells()]
    assert any(sheet_plan.NO_CELLS_MATRIX in w for w in spec.warnings), spec.warnings
    dropped = sheet_plan.drop_empty_payload_warning(spec.warnings)
    assert not any(w.startswith("No cells in the payload") for w in dropped)
    assert any(sheet_plan.NO_CELLS_MATRIX in w for w in dropped), "the real reason survives"


def test_an_explicit_cell_list_always_wins_over_the_ticks():
    spec = _resolve(
        {
            "build": {"views": ["face", "profile", "back"], "poses": ["neutral"], "expressions": ["neutral"]},
            "cells": [{"id": "hero", "view": "portrait"}],
        }
    )
    assert [cell.id for cell in spec.cells] == ["hero"]
    assert not any(sheet_plan.NO_CELLS_TICKS in w for w in spec.warnings)


def test_junk_ticks_are_ignored_with_a_warning():
    spec = _resolve({"build": {"views": ["face", "unicorn"], "poses": ["neutral"]}, "cells": []})
    assert [cell.id for cell in spec.cells] == ["face-neutral-neutral"]
    assert any("unicorn" in w for w in spec.warnings), spec.warnings


def test_ticks_survive_the_payload_round_trip():
    spec = _resolve({"build": {"views": ["face"], "poses": ["neutral"], "expressions": ["neutral"]}, "cells": []})
    again = sheet_spec.parse_sheet_spec(json.dumps(spec.to_dict()))
    assert again.build["views"] == ["face"]


def test_planning_leaves_the_callers_payload_alone():
    original = {"build": {"views": ["face"]}, "cells": []}
    planned = sheet_plan.plan_payload(dict(original), frames_per_cell=22)
    assert [cell["id"] for cell in planned["cells"]] == ["face-neutral-neutral"]
    assert original["cells"] == [], "the caller's payload is not rewritten in place"


def test_cells_from_build_is_pure_and_survives_junk():
    assert pl.cells_from_build(None) == []
    assert pl.cells_from_build({}) == []
    assert pl.cells_from_build({"views": "face"}) == []
    cells = pl.cells_from_build({"views": ["FACE"], "poses": ["neutral"]})
    assert cells == [{"id": "face-neutral-neutral", "view": "face", "pose": "neutral", "expression": "neutral"}]
    assert "frames" not in cells[0], "ticks must not pin a frame count"
