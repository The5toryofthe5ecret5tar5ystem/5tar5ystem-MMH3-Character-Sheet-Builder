# ComfyUI-H3-Character-Sheet - the RefMod suite.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Tests for the suite: several sheets for one character, rendered by one queue.

A suite is data (``render.suite`` = an ordered list of layout presets) expanded into one graph per
board, each board a complete sheet folder of its own. What these tests pin:

* the preset's boards ARE the layout presets it names - the four the panel shows on their own, so
  the suite cannot drift from them;
* the boards do not collapse into one render: separate ``GraphBuilder``s, distinct node ids, one
  H3 render (or one cell set) per board;
* two invariants that make it usable: the quality axis stays the RUN's, and a suite preset never
  sets a size (that is the resolution control's, and it is what makes the chips stick);
* the folder contract: ``<run>/<board>/``, and the manifest that says the boards belong together.
"""

from __future__ import annotations

import json

import pytest

from comfy_execution.graph_utils import GraphBuilder

from h3cs import presets as preset_mod
from h3cs import sheet_spec as ss
from h3cs import sheet_store as store_mod
from h3cs import suite as suite_mod
from h3cs.nodes import sheet as sheet_node
from h3cs.planner import grid_payload, reference_plan

from tests.test_sheet_one_pass import ALLOWED_ONE_PASS_TYPES, _spec


@pytest.fixture()
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "sheets_root", lambda: tmp_path / "minimax_sheets")
    return tmp_path


def _suite_spec(**overrides) -> ss.SheetSpec:
    return _spec(render={"suite": list(preset_mod.SUITE_BOARD_IDS)}, **overrides)


# --------------------------------------------------------------------------- #
# the preset: four boards that are the panel's own layouts
# --------------------------------------------------------------------------- #
def test_the_suite_preset_names_the_four_boards_it_promises():
    preset = preset_mod.suite_preset()
    assert preset is not None and preset.kind == "suite"
    assert list(preset.boards) == list(preset_mod.SUITE_BOARD_IDS)
    # Every board is a LAYOUT preset with cells, in the order the suite renders them: the hero
    # sheet, the expression board, then the two closeup boards.
    assert list(preset_mod.SUITE_BOARD_IDS) == [
        "hero-4", "expressions-6", "details-sfw", "details-nsfw",
    ]
    for board_id in preset.boards:
        board = preset_mod.preset_by_id(board_id)
        assert board is not None and board.kind == "layout", board_id
        assert board.build.get("views"), f"{board_id} would render nothing"


def test_a_suite_preset_arranges_boards_rather_than_the_sheet():
    """No widgets of its own: the arrangement comes from each board's layout preset."""
    preset = preset_mod.suite_preset()
    assert preset.boards and not preset.widgets, (
        "a suite's widgets would be dead data - each board brings its own arrangement"
    )
    assert not preset.build, "the suite itself builds no cells; its boards do"


def test_the_suite_preset_sets_no_size_and_no_layout_of_its_own():
    preset = preset_mod.suite_preset()
    for key in ("cell_size", "sheet_short_edge", "sheet_layout", "sheet_aspect"):
        assert key not in preset.widgets, key
    # It does state the mode: a suite is four one-pass renders by default, not 19 per-cell ones.
    assert preset.render.get("singlePass") is True


def test_a_suite_board_is_never_another_suite():
    for board_id in preset_mod.SUITE_BOARD_IDS:
        assert preset_mod.preset_by_id(board_id).kind == "layout", board_id


def test_applying_the_suite_preset_writes_its_boards_into_the_payload():
    payload = preset_mod.apply_to_payload({}, "refmod-suite")
    assert payload["render"]["suite"] == list(preset_mod.SUITE_BOARD_IDS)
    # A suite rides the LAYOUT axis: it decides which sheets render, so it records itself where a
    # layout would and leaves the quality preset you had alone.
    assert payload["render"]["layoutPreset"] == "refmod-suite"
    assert "preset" not in payload["render"]
    # The quality axis does not touch it (that is the whole point of two axes) ...
    quality = preset_mod.apply_to_payload(
        {"render": {"suite": list(preset_mod.SUITE_BOARD_IDS)}}, "per-cell"
    )
    assert quality["render"]["suite"] == list(preset_mod.SUITE_BOARD_IDS)
    assert quality["render"]["singlePass"] is False
    # ... but picking ONE layout after a suite means one sheet again: leaving the boards set would
    # silently ignore the layout the user just chose.
    layout = preset_mod.apply_to_payload(payload, "expressions-6")
    assert layout["render"]["suite"] == []
    assert layout["render"]["layoutPreset"] == "expressions-6"


# --------------------------------------------------------------------------- #
# the payload: the board list, however it was written
# --------------------------------------------------------------------------- #
def test_the_board_list_round_trips_and_accepts_a_comma_string():
    for written in (
        list(preset_mod.SUITE_BOARD_IDS),
        ",".join(preset_mod.SUITE_BOARD_IDS),
        "; ".join(preset_mod.SUITE_BOARD_IDS),
    ):
        spec = ss.parse_sheet_spec({"render": {"suite": written}})
        assert spec.render.suite == list(preset_mod.SUITE_BOARD_IDS), written
    # A repeat of the same board is one board, not two renders of it.
    spec = ss.parse_sheet_spec({"render": {"suite": "hero-4, hero-4 , expressions-6"}})
    assert spec.render.suite == ["hero-4", "expressions-6"], spec.render.suite
    # And it survives a save/load as a payload (the panel keeps it in the workflow).
    spec = ss.parse_sheet_spec({"render": {"suite": list(preset_mod.SUITE_BOARD_IDS)}})
    assert ss.parse_sheet_spec(json.loads(json.dumps(spec.to_dict()))).render.suite == list(
        preset_mod.SUITE_BOARD_IDS
    )
    # A non-suite run carries an empty list rather than nothing at all.
    assert ss.parse_sheet_spec({}).render.suite == []


def test_the_board_list_is_capped_at_the_cost_ceiling():
    spec = ss.parse_sheet_spec({"render": {"suite": ["hero-4"] * 40}})
    assert spec.render.suite == ["hero-4"]
    spec = ss.parse_sheet_spec({"render": {"suite": [f"board-{n}" for n in range(12)]}})
    assert len(spec.render.suite) == ss.MAX_SUITE_BOARDS


# --------------------------------------------------------------------------- #
# the boards: the layout preset's cells, the run's quality axis
# --------------------------------------------------------------------------- #
def test_the_boards_resolve_to_the_cells_their_layouts_promise():
    boards, warnings = suite_mod.suite_boards(_suite_spec())
    assert warnings == []
    assert [board.id for board in boards] == list(preset_mod.SUITE_BOARD_IDS)
    assert sum(board.cells for board in boards) == 19, "5 + 6 + 4 + 4"
    assert [board.cells for board in boards] == [5, 6, 4, 4]
    # The arrangements are the layout presets' own.
    hero, expressions, sfw, nsfw = boards
    assert hero.layout == "hero-left"
    assert (expressions.layout, expressions.spec.layout.columns) == ("grid", 3)
    assert [cell.view for cell in sfw.spec.enabled_cells] == ["eyes", "mouth", "hands", "feet"]
    assert [cell.view for cell in nsfw.spec.enabled_cells] == [
        "breasts", "groin", "butt", "mouth",
    ]
    assert [cell.expression for cell in expressions.spec.enabled_cells] == [
        "neutral", "closed-eyes", "smile", "anger", "crying", "pleasure",
    ]


def test_each_board_is_the_run_s_quality_axis_with_its_own_layout():
    run = _suite_spec()
    boards, _warnings = suite_mod.suite_boards(
        ss.parse_sheet_spec(
            {**run.to_dict(), "render": {
                **run.to_dict()["render"], "singlePass": True, "steps": 14, "seed": 7,
            }}
        )
    )
    for board in boards:
        assert board.spec.render.single_pass is True, board.id
        assert boards[0].spec.render.steps == 14
        assert board.spec.render.seed == 7, "the seed stays the run's"
        # ... and no board is itself a suite, or every board would render every board.
        assert board.spec.render.suite == []
        assert board.spec.render.layout_preset == board.id


def test_a_board_keeps_the_run_s_references():
    boards, _warnings = suite_mod.suite_boards(_suite_spec())
    for board in boards:
        assert [ref.file for ref in board.spec.refs] == ["face.png"], board.id


def test_boards_that_cannot_be_rendered_are_reported_not_rendered():
    spec = ss.parse_sheet_spec(
        {"render": {"suite": ["hero-4", "no-such-preset", "balanced", "turnaround-3"]}}
    )
    boards, warnings = suite_mod.suite_boards(spec)
    assert [board.id for board in boards] == ["hero-4", "turnaround-3"]
    assert len(warnings) == 2, warnings
    assert any("no-such-preset" in line for line in warnings)
    assert any("balanced" in line and "quality" in line for line in warnings)


def test_a_suite_with_nothing_renderable_says_so():
    boards, warnings = suite_mod.suite_boards(
        ss.parse_sheet_spec({"render": {"suite": ["nope"]}})
    )
    assert boards == []
    assert any("nothing to render" in line for line in warnings), warnings


def test_every_board_gets_a_folder_of_its_own():
    boards, _warnings = suite_mod.suite_boards(_suite_spec())
    folders = [board.folder for board in boards]
    assert folders == ["hero-4", "expressions-6", "details-sfw", "details-nsfw"]
    assert len(set(folders)) == len(folders)


# --------------------------------------------------------------------------- #
# the graph: one queue, one graph per board
# --------------------------------------------------------------------------- #
def _suite_graph(spec: ss.SheetSpec):
    boards, warnings = suite_mod.suite_boards(spec)
    assert not warnings, warnings
    return sheet_node.build_suite_graph(
        boards=boards,
        model="MODEL",
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        name=str(spec.name),
    )


def test_the_suite_is_four_h3_renders_in_one_graph():
    spec = _suite_spec()
    expand, (sheet, cells, report, sheet_dir), lines = _suite_graph(spec)
    assert sheet and cells and report and sheet_dir, "the same four outputs as a single sheet"
    built = expand
    types = [node["class_type"] for node in built.values()]
    assert set(types) <= ALLOWED_ONE_PASS_TYPES, sorted(set(types) - ALLOWED_ONE_PASS_TYPES)
    assert types.count("MiniMaxH3ReferenceToVideo") == 4, "one render per board"
    assert types.count("H3SheetOnePassSink") == 4, "and a folder per board"
    # Four boards, four line(s) each: the summary names every board and where it lands.
    assert len([line for line in lines if line.startswith("Suite board")]) == 4
    assert all(f"{spec.name}/{board}" in " ".join(lines) for board in preset_mod.SUITE_BOARD_IDS)


def test_every_board_renders_its_own_cells_rather_than_anybody_elses():
    spec = _suite_spec()
    expand, _outputs, _lines = _suite_graph(spec)
    sinks = [node for node in expand.values() if node["class_type"] == "H3SheetOnePassSink"]
    assert len(sinks) == 4
    boards = {node["inputs"]["board"] for node in sinks}
    assert boards == set(preset_mod.SUITE_BOARD_IDS), boards
    # Each sink carries ITS board's payload: its own cells, its own layout, and no suite.
    for node in sinks:
        payload = json.loads(node["inputs"]["sheet_data"])
        assert payload["render"]["suite"] == [], node["inputs"]["board"]
        assert len(payload["cells"]) == 5 if node["inputs"]["board"] == "hero-4" else True
        assert payload["render"]["layoutPreset"] == node["inputs"]["board"]
    hero = next(node for node in sinks if node["inputs"]["board"] == "hero-4")
    assert len(json.loads(hero["inputs"]["sheet_data"])["cells"]) == 5
    assert json.loads(hero["inputs"]["sheet_data"])["sheet"]["layout"] == "hero-left"


def test_the_boards_do_not_share_a_single_node():
    """Two boards wired to one sampler would be one render wearing four folder names."""
    spec = _suite_spec()
    expand, _outputs, _lines = _suite_graph(spec)
    samplers = [key for key, node in expand.items() if node["class_type"] == "SamplerCustomAdvanced"]
    assert len(samplers) == 4, samplers
    # Every node id is unique (they are, by construction, but a shared builder would collide).
    assert len(expand) == len(set(expand))
    # And each board's decode is fed by its own sampler, not by the first board's.
    decodes = {node["inputs"]["samples"][0] for node in expand.values()
               if node["class_type"] == "VAEDecode"}
    assert len(decodes) == 4, "each board decodes its own samples"


def test_the_suite_wraps_the_preview_once_for_all_boards():
    """One model, one preview wrapper: four wrappers would stack four step clocks on it."""
    spec = _suite_spec()
    expand, _outputs, _lines = _suite_graph(spec)
    types = [node["class_type"] for node in expand.values()]
    # The sigma shifts all sit on the same model input (the wrapper), so the graph has one entry
    # point per board into the same wrapper - asserted by the shifts sharing a link.
    models = [node["inputs"]["model"] for node in expand.values()
              if node["class_type"] == "MiniMaxH3SigmaShift"]
    assert len(models) == 4
    assert len({json.dumps(model) for model in models}) == 1, models


def test_the_suite_tells_the_preview_which_board_is_rendering():
    """One wrapper for four boards, so it can only name them if it is handed the map.

    The preview wrapper goes on the model every board samples through: the stream is ONE run of
    sampler calls across all of them, and the panel follows the board it is told about (see
    suite.board_segments and preview_stream._SheetPreviewWrapper.board_of).
    """
    spec = _suite_spec()
    boards, _warnings = suite_mod.suite_boards(spec)
    segments = suite_mod.board_segments(boards)
    assert [entry["id"] for entry in segments] == [board.id for board in boards]
    assert [entry["folder"] for entry in segments] == [board.folder for board in boards]
    assert all(entry["label"] for entry in segments)
    # One-pass is the suite's own mode: every board is ONE sampler call, and that call IS the
    # sheet, so each clip is labelled as the board rather than as "cell 1 of 19".
    assert [entry["calls"] for entry in segments] == [1, 1, 1, 1]
    assert all(entry["whole_sheet"] is True for entry in segments)

    spec.render.single_pass = False
    per_cell, _warnings = suite_mod.suite_boards(spec)
    segments = suite_mod.board_segments(per_cell)
    assert [entry["calls"] for entry in segments] == [
        len(board.spec.enabled_cells) for board in per_cell
    ]
    assert sum(entry["calls"] for entry in segments) == 19, "the suite's cells, board by board"
    assert all(entry["whole_sheet"] is False for entry in segments)


def test_a_suite_in_per_cell_mode_renders_every_board_s_cells():
    spec = _suite_spec()
    spec.render.single_pass = False
    boards, warnings = suite_mod.suite_boards(spec)
    assert not warnings
    expand, _outputs, _lines = sheet_node.build_suite_graph(
        boards=boards,
        model="MODEL",
        clip="CLIP",
        video_vae="VVAE",
        audio_vae="AVAE",
        name=str(spec.name),
    )
    types = [node["class_type"] for node in expand.values()]
    assert types.count("MiniMaxH3ReferenceToVideo") == 19, "one render per cell of every board"
    assert types.count("H3SheetCellSink") == 19
    # Each board's cells live in that board's folder.
    boards_seen = {node["inputs"]["board"] for node in expand.values()
                   if node["class_type"] == "H3SheetCellSink"}
    assert boards_seen == set(preset_mod.SUITE_BOARD_IDS), boards_seen


def test_the_suite_ignores_the_run_s_own_cells():
    """A board carries its own cells; rendering "the sheet you had" as well would be a fifth."""
    spec = _suite_spec(cells=[{"id": "whatever", "view": "front"}])
    expand, _outputs, _lines = _suite_graph(spec)
    payloads = [json.loads(node["inputs"]["sheet_data"]) for node in expand.values()
                if node["class_type"] == "H3SheetOnePassSink"]
    for payload in payloads:
        assert "whatever" not in json.dumps(payload["cells"]), payload["cells"]


def test_each_board_gets_the_references_the_run_configured():
    spec = _suite_spec()
    expand, _outputs, _lines = _suite_graph(spec)
    ref2va = [node for node in expand.values() if node["class_type"] == "MiniMaxH3ReferenceToVideo"]
    prompts = {node["inputs"]["prompt"] for node in ref2va}
    assert len(prompts) == 4, "each board describes its own panels"
    for prompt in prompts:
        assert "the face and the hair" in prompt, "the run's reference role reaches every board"


def test_the_board_folder_is_sanitised_like_a_sheet_folder():
    assert suite_mod.board_folder("hero-4") == "hero-4"
    assert "/" not in suite_mod.board_folder("../evil")
    assert suite_mod.board_folder("") == "board"


def test_a_board_folder_sits_inside_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "sheets_root", lambda: tmp_path / "minimax_sheets")
    store = store_mod.SheetStore("character sheet-20261005_120000", board="hero-4").ensure()
    assert store.dir.name == "hero-4"
    # A run name with spaces resolves to the run's own (sanitised) folder, and the board is
    # INSIDE it - one run, four complete sheets.
    assert store.dir.parent.name == "character_sheet-20261005_120000"
    assert store.dir.is_dir(), "the board folder is created on demand, like a sheet's"


def test_the_suite_manifest_says_which_boards_belong_together():
    boards, _warnings = suite_mod.suite_boards(_suite_spec())
    manifest = suite_mod.suite_manifest(boards, name="character sheet")
    assert manifest["name"] == "character sheet"
    assert [board["id"] for board in manifest["boards"]] == list(preset_mod.SUITE_BOARD_IDS)
    assert [board["folder"] for board in manifest["boards"]] == [
        "hero-4", "expressions-6", "details-sfw", "details-nsfw",
    ]
    json.dumps(manifest)


def test_the_suite_report_lists_the_boards_in_render_order():
    boards, _warnings = suite_mod.suite_boards(_suite_spec())
    lines = suite_mod.suite_lines(boards, name="character sheet")
    assert "4 sheet(s) from one queue" in lines[0]
    assert "character sheet/<board>" in lines[1]
    for position, board in enumerate(boards, start=1):
        assert lines[position + 1].startswith(f"  {position}. {board.label}"), lines


def test_a_suite_needs_a_preset_that_names_layouts():
    """The board list is validated in Python, not only in the panel."""
    assert preset_mod.preset_by_id("balanced").kind == "quality"
    assert preset_mod.preset_by_id("hero-4").kind == "layout"
    spec = ss.parse_sheet_spec({"render": {"suite": ["balanced"]}})
    boards, warnings = suite_mod.suite_boards(spec)
    assert boards == []
    assert any("quality" in line for line in warnings), warnings
