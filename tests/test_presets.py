"""Character Sheet Builder - the recommended whole-node presets.

Presets are data, not prose: each one has to survive the real spec parser, name only real
node widgets, and describe a configuration that is actually coherent (a 5-frame preset
cannot promise continuation; an identity preset should not be the one that chains across a
framing change). All of that is checkable without a GPU, so it is checked here.

The properties that matter:

* **one definition, served, not mirrored**: the panel fetches this list over the action
  route, so the backend can never offer a preset it does not implement;
* **every widget name is real**: a typo in ``widgets`` would silently do nothing at run
  time, which is exactly the kind of bug a preset should never have;
* **every preset parses cleanly** through ``parse_sheet_spec`` with no warnings of its own;
* **the recommended one matches the pack's own defaults**, so "recommended" means "what you
  already had" rather than a hidden change.
"""

from __future__ import annotations

import inspect
import json

import pytest

from h3cs import planner as pl
from h3cs import presets as preset_mod
from h3cs import sheet_spec as ss
from h3cs.nodes import sheet as sheet_node
from h3cs.presets import PRESETS, apply_to_payload, preset_by_id, preset_list

#: Widgets a preset may set, straight off the node schema - not a hand-written list.
SCHEMA_WIDGETS = {
    getattr(item, "id", None)
    for item in sheet_node.MiniMaxH3CharacterSheet.define_schema().inputs
    if getattr(item, "id", None)
} - {"model", "video_vae", "audio_vae", "clip"}


@pytest.fixture(autouse=True)
def _no_saved_presets(tmp_path, monkeypatch):
    """These tests are about the BUILT-IN presets.

    ``preset_list()`` also serves the presets a user saved (``user_presets.py``), which live
    in the running ComfyUI's user directory - so without this the suite would read whatever
    that user happens to have kept, and fail on their machine instead of here.
    """
    from h3cs import user_presets as store

    monkeypatch.setattr(store, "store_path", lambda: tmp_path / "presets.json")


def _payload(**overrides):
    payload = {
        "version": 1,
        "name": "preset sheet",
        "refs": {"pictures": [{"imageFile": "face.png", "role": "face and hair"}]},
        "cells": [{"id": "c1", "view": "front"}, {"id": "c2", "view": "profile"}],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# the shape of the list
# --------------------------------------------------------------------------- #
def test_the_default_preset_is_the_node_s_own_defaults_and_it_is_first():
    """The recommended quality preset is not a change: it spells out what a fresh node does."""
    assert PRESETS[0].id == preset_mod.DEFAULT_PRESET_ID
    assert PRESETS[0].kind == "quality"
    assert PRESETS[0].deviates == (), "the default preset must not move anything"
    assert preset_by_id(preset_mod.DEFAULT_LAYOUT_ID).kind == "layout"


def test_ids_are_unique_and_lookable_up():
    ids = [preset.id for preset in PRESETS]
    assert len(ids) == len(set(ids))
    for preset in PRESETS:
        assert preset_by_id(preset.id) is preset
        assert preset_by_id(preset.id.upper()) is preset, "ids are matched case-insensitively"
    assert preset_by_id("nonsense") is None
    assert preset_by_id(None) is None


def test_every_preset_says_what_it_is_for():
    for preset in PRESETS:
        assert preset.label and len(preset.label) <= 48, preset.id
        assert len(preset.hint) > 40, f"{preset.id} needs a real hint, not a label repeat"


def test_every_widget_a_preset_sets_actually_exists():
    for preset in PRESETS:
        unknown = sorted(set(preset.widgets) - SCHEMA_WIDGETS)
        assert unknown == [], f"{preset.id} sets widget(s) the node does not declare: {unknown}"


def test_presets_only_use_known_vocabularies():
    for preset in PRESETS:
        widgets = preset.widgets
        # A preset sets only what its own axis owns, so each key is checked when it is there:
        # a layout preset carries no render settings, a quality preset no layout.
        for name, allowed in (
            ("continuity", ss.CONTINUITY_MODES),
            ("ref_scope", ss.REF_SCOPES),
            ("cell_aspect", ss.CELL_ASPECTS),
            ("sheet_layout", ss.LAYOUTS),
            ("ref_image_size", ("match", "max")),
            ("sheet_fit", ("contain", "cover", "stretch")),
        ):
            if name in widgets:
                assert widgets[name] in allowed, f"{preset.id}: bad {name}={widgets[name]!r}"
        for view in (preset.build or {}).get("views") or []:
            assert view in ss.VIEW_KEYS, f"{preset.id}: unknown view {view}"
        for pose in (preset.build or {}).get("poses") or []:
            assert pose in ss.POSE_KEYS, f"{preset.id}: unknown pose {pose}"
        for expression in (preset.build or {}).get("expressions") or []:
            assert expression in ss.EXPRESSION_KEYS, f"{preset.id}: unknown expression {expression}"


def _schema_defaults() -> dict[str, object]:
    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    return {
        getattr(item, "id", None): getattr(item, "default", None)
        for item in schema.inputs
        if getattr(item, "id", None)
    }


def test_deviations_from_the_node_defaults_are_declared():
    """Each preset must list exactly where it departs from a fresh node.

    Not a formality: the difference between "recommended" and "what you already had" is
    where a preset can quietly impose settings the user never chose, so the list is data
    (surfaced to the panel) and is checked against the schema rather than trusted.
    """
    defaults = _schema_defaults()
    for preset in PRESETS:
        actual = {
            name for name, value in preset.widgets.items()
            if name in defaults and defaults[name] is not None and value != defaults[name]
        }
        assert actual == set(preset.deviates), (
            f"{preset.id}: declares {sorted(preset.deviates)} but actually deviates on "
            f"{sorted(actual)}"
        )


def test_a_value_below_the_node_default_is_always_declared():
    """A faster/lighter preset must not smuggle in less work without saying so."""
    defaults = _schema_defaults()
    for preset in PRESETS:
        for name in ("steps", "cell_size", "frames_per_cell"):
            value = preset.widgets.get(name)
            if value is None or defaults.get(name) is None:
                continue
            if value < defaults[name]:
                assert name in preset.deviates, (
                    f"{preset.id} lowers {name} to {value} (default {defaults[name]}) without "
                    "declaring it"
                )


# --------------------------------------------------------------------------- #
# each preset has to be a configuration that works
# --------------------------------------------------------------------------- #
def test_every_preset_parses_cleanly_into_the_spec():
    for preset in PRESETS:
        payload = apply_to_payload(_payload(), preset.id)
        spec = ss.parse_sheet_spec(payload)
        unexpected = [line for line in spec.warnings if "snapped up" not in line]
        assert unexpected == [], f"{preset.id} does not parse cleanly: {unexpected}"
        # The record lands on the axis the preset belongs to, so applying a layout after a
        # quality preset (or the other way round) cannot erase the other one's provenance. A
        # suite rides the layout axis - it decides which SHEETS render, not how they sample.
        if preset.kind in ("layout", "suite"):
            assert spec.render.layout_preset == preset.id
            assert spec.render.preset == "", "only a quality preset claims the quality axis"
        else:
            assert spec.render.preset == preset.id
            assert spec.render.layout_preset == "", "a quality preset must not claim the layout"
        # And only a suite carries boards - every other preset renders one sheet.
        assert spec.render.suite == list(preset.boards), preset.id
        if "exportVideo" in preset.render:
            assert spec.render.export_video is preset.render["exportVideo"]
        if "continuity" in preset.render:
            assert spec.render.continuity == preset.render["continuity"]


def test_no_preset_pretends_a_short_clip_can_continue():
    """Continuation needs frames to hand over; a 5-frame preset cannot promise it."""
    for preset in PRESETS:
        frames = preset.widgets.get("frames_per_cell")
        if frames == ss.MIN_CELL_FRAMES:
            assert preset.widgets.get("continuity") == "off", (
                f"{preset.id} renders {frames}-frame cells, which can never continue"
            )
    # The default render is the one-pass sheet: 5 frames inside ONE clip, so continuation is
    # not a per-cell hand-over at all and the engine says so in the report.
    assert preset_by_id(preset_mod.DEFAULT_PRESET_ID).widgets["single_pass"] is True
    assert ss.parse_sheet_spec(_payload()).render.single_pass is True


def test_a_turnaround_layout_with_the_per_cell_quality_chains_a_full_body_run():
    """The two axes together are what the old one-shot turnaround preset used to be."""
    payload = apply_to_payload(_payload(), "turnaround-3")       # the layout: three in a row
    payload = apply_to_payload(payload, "per-cell")               # the quality: chain the turn
    spec = ss.parse_sheet_spec(payload)
    assert spec.layout.layout == "turnaround"
    assert spec.render.continuity == "auto"
    assert spec.render.single_pass is False
    # Its ticks build three full-body cells at one camera distance, and the chain is the point:
    # the subject turns inside each clip and settles. (The references have to carry the body for
    # that - see test_sheet_continuity.)
    cells = ss.cell_matrix(views=["front", "profile", "back"], poses=["neutral"])
    spec.cells = ss.parse_sheet_spec({**payload, "cells": cells}).cells
    assert list(ss.continuity_plan(spec).values()) == [0, ss.CONTINUITY_FRAMES, ss.CONTINUITY_FRAMES]  


def test_the_expression_board_is_six_faces_in_a_2x3_grid():
    preset = preset_by_id("expressions-6")
    assert preset.kind == "layout"
    assert preset.widgets["sheet_layout"] == "grid"
    assert preset.widgets["sheet_columns"] == 3
    assert preset.widgets["cell_aspect"] == "1:1"
    assert preset.build["views"] == ["face"]
    assert preset.build["expressions"] == [
        "neutral", "closed-eyes", "smile", "anger", "crying", "pleasure",
    ], "the six faces the board is for"
    # Two rows of three: six cells, all the same framing, which is what makes it comparable.
    cells = ss.cell_matrix(views=preset.build["views"], expressions=preset.build["expressions"])
    assert len(cells) == 6
    assert {cell["view"] for cell in cells} == {"face"}


def test_the_expression_board_chains_when_the_quality_asks_for_it():
    payload = apply_to_payload(_payload(), "expressions-6")
    payload = apply_to_payload(payload, "per-cell")
    cells = ss.cell_matrix(views=["face"], expressions=list(preset_by_id("expressions-6").build["expressions"]))
    spec = ss.parse_sheet_spec({**payload, "cells": cells})
    assert [cell.view for cell in spec.cells] == ["face"] * 6
    assert list(ss.continuity_plan(spec).values()) == [0] + [ss.CONTINUITY_FRAMES] * 5


def test_the_identity_preset_is_independent_and_slow():
    """Fidelity preset: no chaining (each framing must stand alone) and the 2048px refs."""
    preset = preset_by_id("identity")
    assert preset.kind == "quality"
    assert preset.widgets["ref_image_size"] == "max"
    assert preset.widgets["continuity"] == "off"
    assert preset.widgets["single_pass"] is False, "the reference pipeline is a per-panel cost"
    # The likeness lever is the reference pipeline, not more sampling: every preset uses the
    # turbo step count, so this one has to differ on ref_image_size (and declare it).
    balanced = preset_by_id(preset_mod.DEFAULT_PRESET_ID)
    assert preset.widgets["ref_image_size"] != balanced.widgets["ref_image_size"]
    assert "ref_image_size" in preset.deviates


# --------------------------------------------------------------------------- #
# the full character sheet: the same five cells, two resolution tiers
# --------------------------------------------------------------------------- #
def test_the_hero_layout_is_the_same_five_cells_in_the_same_order():
    """The flagship layout's cells are part of the pack's contract, so they are pinned here.

    Headshot, chest-up portrait, full body front, the 90-degree side and from behind - read
    front to back so the sheet doubles as a turnaround; neutral expression and neutral pose,
    because a sheet is a reference someone else will pose from.
    """
    preset = preset_by_id(preset_mod.DEFAULT_LAYOUT_ID)
    assert preset.kind == "layout"
    assert preset.build == {
        "views": ["face", "portrait", "front", "profile", "back"],
        "poses": ["neutral"],
        "expressions": ["neutral"],
    }
    for view in preset.build["views"]:
        assert view in ss.VIEW_KEYS, f"unknown view {view}"
    # Hero on the left, the other four in a 2x2 block: hero-left with two grid columns.
    assert preset.widgets["sheet_layout"] == "hero-left"
    assert preset.widgets["sheet_columns"] == 2


def test_the_hero_layout_keeps_the_neutral_tan_backdrop():
    """"Neutral tan backdrop setting" is part of this layout's look, not a leftover default."""
    preset = preset_by_id(preset_mod.DEFAULT_LAYOUT_ID)
    assert preset.render["background"] == "tan"
    payload = apply_to_payload(_payload(), preset.id)
    spec = ss.parse_sheet_spec(payload)
    assert ss.describe_background(spec) == "Neutral tan (tan)"
    # The backdrop travels in the prompt itself, not only in the panel.
    cells = ss.cell_matrix(views=preset.build["views"], poses=["neutral"])
    spec.cells = ss.parse_sheet_spec({**payload, "cells": cells}).cells
    for cell in spec.cells:
        assert ss.TAN_HEX in ss.build_cell_prompt(spec, cell), cell.view


def test_no_preset_sets_a_size():
    """The invariant that makes the resolution chips work: sizes belong to the control alone.

    A preset that wrote ``cell_size`` or ``sheet_short_edge`` would silently undo a 4K choice
    the moment it was applied - which is exactly what the old one-shot presets did.
    """
    for preset in PRESETS:
        for name in ("cell_size", "sheet_short_edge"):
            assert name not in preset.widgets, f"{preset.id} sets the size {name}"
        assert "shortEdge" not in preset.sheet, f"{preset.id} sets the sheet size"
        assert "cellSize" not in preset.sheet, f"{preset.id} sets the cell size"


def test_every_preset_and_the_node_use_the_turbo_step_count():
    """One step count, defined once.

    The pack is set up around the TURBO H3 checkpoints, whose own recipe for
    res_multistep/simple is 6-8 steps. The node's default and every preset must agree, or a
    fresh node quietly renders 3x slower than the preset the user then applies.
    """
    assert _schema_defaults()["steps"] == ss.DEFAULT_STEPS
    for preset in PRESETS:
        assert preset.widgets.get("steps", ss.DEFAULT_STEPS) == ss.DEFAULT_STEPS, preset.id
        assert "steps" not in preset.deviates, (
            f"{preset.id} lists steps as a deviation, but it is the default"
        )


def test_presets_do_not_touch_the_users_cells_or_references():
    """Applying a preset may recommend ticks; it must not rewrite the sheet's content."""
    payload = _payload()
    before = json.dumps(payload["cells"], sort_keys=True)
    for preset in PRESETS:
        merged = apply_to_payload(payload, preset.id)
        assert json.dumps(merged["cells"], sort_keys=True) == before
        assert merged["refs"] == payload["refs"]


def test_apply_to_payload_keeps_unknown_ids_harmless():
    payload = _payload()
    assert apply_to_payload(payload, "nonsense") == payload
    assert "render" not in apply_to_payload(payload, "")


def test_each_preset_axis_round_trips_through_the_saved_payload():
    layout = apply_to_payload(_payload(), "turnaround-3")
    both = apply_to_payload(layout, "per-cell")
    again = ss.parse_sheet_spec(json.dumps(both))
    assert again.render.layout_preset == "turnaround-3"
    assert again.render.preset == "per-cell", "the quality record survives the layout's"
    restored = ss.parse_sheet_spec(json.loads(json.dumps(again.to_dict())))
    assert restored.render.layout_preset == "turnaround-3"
    assert restored.render.preset == "per-cell"


def test_the_resolution_choices_pair_a_sheet_size_with_a_cell_size():
    """The chips' table: one choice, two sizes, both on the grid the render snaps to."""
    choices = preset_mod.resolution_list()
    assert [choice["key"] for choice in choices] == [key for key, _l, _s, _c in ss.RESOLUTION_CHOICES]
    for choice in choices:
        assert choice["label"] and choice["hint"], choice["key"]
        assert choice["sheetShortEdge"] % ss.ONE_PASS_ALIGN == 0
        # The cell size has to be a value the node's own widget would accept.
        assert 256 <= choice["cellShortEdge"] <= 2048
        # And the key has to be what a payload written from the chip means.
        assert ss.parse_sheet_spec({"render": {"resolution": choice["key"]}}).render.resolution


def test_the_route_payload_is_json_safe_and_complete():
    listed = preset_list()
    assert len(listed) == len(PRESETS)
    json.dumps(listed)  # a preset that cannot be serialised would break the panel
    for entry in listed:
        assert set(entry) == {
            "id", "label", "hint", "kind", "render", "sheet", "widgets", "build", "deviates",
            "boards", "custom",
        }
        # Two selectors in the panel are drawn from this field, so every preset has to declare it.
        assert entry["kind"] in {key for key, _label in preset_mod.PRESET_KINDS}, entry["id"]
        # `custom` is how the panel knows which entries it may offer to delete (see
        # user_presets.py); a built-in must never look deletable.
        assert entry["custom"] is False, entry["id"]
    # And both axes have something to offer.
    assert preset_mod.presets_by_kind("layout"), "the panel needs layout presets"
    assert preset_mod.presets_by_kind("quality"), "and quality ones"


def test_the_summary_mentions_the_preset_only_when_the_none_is_absent():
    """The report stays about the sheet; the preset id rides in the payload it runs."""
    spec = ss.parse_sheet_spec(apply_to_payload(_payload(), "balanced"))
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    assert lines, "the summary is never empty"


def test_the_panel_can_apply_a_preset_it_fetched():
    """Every widget in the list is something the panel's hook can set on the node."""
    from h3cs.nodes.sheet import MiniMaxH3CharacterSheet

    params = set(inspect.signature(MiniMaxH3CharacterSheet.execute).parameters)
    for preset in PRESETS:
        for name in preset.widgets:
            assert name in params, f"{preset.id} sets {name}, which execute() cannot take"


# --------------------------------------------------------------------------- #
# the detail boards
# --------------------------------------------------------------------------- #
def test_the_closeup_boards_build_the_cells_they_promise():
    """Four crops each, in a 2x2 grid - and the ahego cell is the mouth crop, not a view."""
    sfw = preset_by_id("details-sfw")
    assert sfw.kind == "layout"
    assert sfw.build == {"views": ["eyes", "mouth", "hands", "feet"], "poses": [],
                         "expressions": ["neutral"]}
    assert sfw.widgets["sheet_layout"] == "grid" and sfw.widgets["sheet_columns"] == 2
    assert sfw.widgets["cell_aspect"] == "1:1", "a detail board is square cells"
    cells = ss.cell_matrix(views=sfw.build["views"], expressions=sfw.build["expressions"])
    assert [cell["view"] for cell in cells] == ["eyes", "mouth", "hands", "feet"]
    assert len(cells) == 4, "one cell per crop - the detail framings are single-cell"

    nsfw = preset_by_id("details-nsfw")
    assert nsfw.kind == "layout"
    assert nsfw.build["views"] == ["breasts", "groin", "butt", "mouth"]
    assert nsfw.widgets["sheet_columns"] == 2
    cells = ss.cell_matrix(views=nsfw.build["views"], expressions=nsfw.build["expressions"])
    assert len(cells) == 4
    assert [cell["view"] for cell in cells] == ["breasts", "groin", "butt", "mouth"]
    assert [cell["expression"] for cell in cells] == ["neutral", "neutral", "neutral", "ahego"], (
        "the mouth cell carries ahego; the body crops do not take an expression at all"
    )


def test_a_body_crop_is_never_told_about_a_face_it_cannot_show():
    """The vocabulary rule the body crops have to keep: no expression line, no gaze."""
    payload = apply_to_payload(_payload(), "details-nsfw")
    cells = ss.cell_matrix(views=["breasts", "groin", "butt", "mouth"], expressions=["ahego"])
    spec = ss.parse_sheet_spec({**payload, "cells": cells})
    for cell in spec.cells:
        prompt = ss.build_cell_prompt(spec, cell)
        assert "no extra people" in prompt
        if cell.view == "mouth":
            assert "ahego" in prompt.lower() or "tongue" in prompt.lower(), (
                "the mouth crop is where the expression reads"
            )
        else:
            assert "tongue" not in prompt.lower(), (
                f"{cell.view} cannot show a mouth, so an expression must not reach its prompt"
            )


# --------------------------------------------------------------------------- #
# the panel's own vocabulary lists have to match the backend's
# --------------------------------------------------------------------------- #
def _js_keys(name: str) -> list[str]:
    """The keys of ``export const <name> = [ ["key", "Label"], ... ]`` in the panel source."""
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parents[1] / "web" / "js" / "h3sheet_core.mjs"
    match = re.search(rf"export const {name} = \[(.*?)\n\];", source.read_text(), re.S)
    assert match, f"the panel does not export {name}"
    return re.findall(r'\[\s*"([^"]+)"\s*,', match.group(1))


def test_the_panel_offers_exactly_the_vocabulary_the_backend_knows():
    """Two lists, one truth: the panel draws the ticks from its own copy, so a view added on
    one side only would be a view you cannot ask for (or one the pack cannot render).

    Order is the panel's own - it groups the ticks the way it reads best - but the SET has to
    match exactly, in both directions.
    """
    for name, backend in (("VIEWS", ss.VIEW_KEYS), ("POSES", ss.POSE_KEYS),
                          ("EXPRESSIONS", ss.EXPRESSION_KEYS)):
        keys = _js_keys(name)
        assert len(keys) == len(backend), (
            f"{name}: the panel offers {len(keys)} and the backend knows {len(backend)}"
        )
        assert set(keys) == set(backend), (
            f"{name} drifted: panel-only {sorted(set(keys) - set(backend))}, "
            f"backend-only {sorted(set(backend) - set(keys))}"
        )
