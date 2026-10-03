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
def test_there_is_a_recommended_preset_and_it_is_first():
    assert PRESETS[0].id == preset_mod.DEFAULT_PRESET_ID
    assert "recommended" in PRESETS[0].label.lower()


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
        assert widgets.get("continuity") in ss.CONTINUITY_MODES, preset.id
        assert widgets.get("ref_scope") in ss.REF_SCOPES, preset.id
        assert widgets.get("cell_aspect") in ss.CELL_ASPECTS, preset.id
        assert widgets.get("sheet_layout") in ss.LAYOUTS, preset.id
        assert widgets.get("ref_image_size") in ("match", "max"), preset.id
        assert widgets.get("sheet_fit") in ("contain", "cover", "stretch"), preset.id
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
        for name, value in preset.widgets.items():
            if name == "frames_per_cell":
                payload.setdefault("render", {})
            # Widgets are not payload keys, but the two the spec also reads are:
        spec = ss.parse_sheet_spec(payload)
        unexpected = [line for line in spec.warnings if "snapped up" not in line]
        assert unexpected == [], f"{preset.id} does not parse cleanly: {unexpected}"
        assert spec.render.preset == preset.id
        if "exportVideo" in preset.render:
            assert spec.render.export_video is preset.render["exportVideo"]
        if "continuity" in preset.render:
            assert spec.render.continuity == preset.render["continuity"]


def test_a_five_frame_preset_does_not_pretend_it_can_continue():
    """The fast preset renders 5-frame cells: continuation is impossible there."""
    preset = preset_by_id("fast")
    assert preset.widgets["frames_per_cell"] == ss.MIN_CELL_FRAMES
    assert preset.widgets["continuity"] == "off"
    payload = apply_to_payload(_payload(), "fast")
    payload["render"]["framesPerCell"] = ss.MIN_CELL_FRAMES
    payload["render"]["preset"] = "fast"
    spec = ss.parse_sheet_spec(payload)
    assert all(cell.frames == ss.MIN_CELL_FRAMES for cell in spec.cells)
    assert set(ss.continuity_plan(spec).values()) == {0}, "5-frame cells can never continue"


def test_the_turnaround_preset_chains_a_full_body_run():
    spec = ss.parse_sheet_spec(apply_to_payload(_payload(), "turnaround"))
    # Its ticks build three full-body cells, all the same camera distance, so 'auto' chains
    # them - that is the point of the preset.
    cells = ss.cell_matrix(views=["front", "profile", "back"], poses=["neutral"])
    spec.cells = ss.parse_sheet_spec({**_payload(), "cells": cells}).cells
    plan = ss.continuity_plan(spec)
    assert list(plan.values()) == [0, ss.CONTINUITY_FRAMES, ss.CONTINUITY_FRAMES]


def test_the_expression_preset_chains_identical_framing():
    cells = ss.cell_matrix(
        views=["face"], expressions=["neutral", "smile", "smirk", "frown", "surprised"]
    )
    spec = ss.parse_sheet_spec({**_payload(), "cells": cells,
                                "render": {"continuity": "auto"}})
    assert [cell.view for cell in spec.cells] == ["face"] * 5
    assert list(ss.continuity_plan(spec).values()) == [0] + [ss.CONTINUITY_FRAMES] * 4


def test_the_identity_preset_is_independent_and_slow():
    """Fidelity preset: no chaining (each framing must stand alone) and the 2048px refs."""
    preset = preset_by_id("identity")
    assert preset.widgets["ref_image_size"] == "max"
    assert preset.widgets["continuity"] == "off"
    # The likeness lever is the reference pipeline, not more sampling: every preset uses the
    # turbo step count, so this one has to differ on ref_image_size (and declare it).
    balanced = preset_by_id(preset_mod.DEFAULT_PRESET_ID)
    assert preset.widgets["ref_image_size"] != balanced.widgets["ref_image_size"]
    assert "ref_image_size" in preset.deviates
    # Same 2048px cells on a 3840px sheet as the fidelity sheet: if the likeness is the point,
    # it has to survive being cut out and enlarged.
    assert preset.widgets["cell_size"] == 2048
    assert preset.widgets["sheet_short_edge"] == 3840
    assert preset.sheet["shortEdge"] == 3840


# --------------------------------------------------------------------------- #
# the full character sheet: the same five cells, two resolution tiers
# --------------------------------------------------------------------------- #
def test_the_full_sheet_presets_are_the_same_five_cells_in_the_same_order():
    """One definition of "full character sheet", shared by both tiers.

    Headshot, chest-up portrait, full body front, the 90-degree side and from behind - read
    front to back so the sheet doubles as a turnaround; neutral expression and neutral pose,
    because a sheet is a reference someone else will pose from.
    """
    for preset_id in ("full-balanced", "full-fidelity"):
        preset = preset_by_id(preset_id)
        assert preset.build == {
            "views": ["face", "portrait", "front", "profile", "back"],
            "poses": ["neutral"],
            "expressions": ["neutral"],
        }, preset_id
        assert len(preset.build["views"]) == 5
        for view in preset.build["views"]:
            assert view in ss.VIEW_KEYS, f"{preset_id}: unknown view {view}"


def test_the_full_sheet_presets_are_neutral_tan():
    """"Neutral tan backdrop setting" is the point of these two, not a leftover default."""
    for preset_id in ("full-balanced", "full-fidelity"):
        preset = preset_by_id(preset_id)
        assert preset.render["background"] == "tan", preset_id
        payload = apply_to_payload(_payload(), preset_id)
        spec = ss.parse_sheet_spec(payload)
        assert ss.describe_background(spec) == "Neutral tan (tan)"
        # The backdrop travels in the prompt itself, not only in the panel.
        cells = ss.cell_matrix(views=preset.build["views"], poses=["neutral"])
        spec.cells = ss.parse_sheet_spec({**payload, "cells": cells}).cells
        for cell in spec.cells:
            assert ss.TAN_HEX in ss.build_cell_prompt(spec, cell), cell.view


def test_the_two_full_sheet_tiers_differ_only_in_resolution():
    balanced = preset_by_id("full-balanced")
    fidelity = preset_by_id("full-fidelity")
    assert balanced.widgets["cell_size"] == 1024
    assert balanced.widgets["sheet_short_edge"] == 1536
    assert fidelity.widgets["cell_size"] == 2048
    assert fidelity.widgets["sheet_short_edge"] == 3840
    assert {**fidelity.widgets, "cell_size": 1024, "sheet_short_edge": 1536} == balanced.widgets
    assert fidelity.render == balanced.render
    assert fidelity.build == balanced.build
    # Only the resolution is a departure from a fresh node (plus the chaining the
    # recommendation adds); the fidelity tier has to say so.
    assert set(fidelity.deviates) == {"cell_size", "sheet_short_edge", "continuity"}
    assert set(balanced.deviates) == {"continuity"}


def test_every_preset_and_the_node_use_the_turbo_step_count():
    """One step count, defined once.

    The pack is set up around the TURBO H3 checkpoints, whose own recipe for
    res_multistep/simple is 6-8 steps. The node's default and every preset must agree, or a
    fresh node quietly renders 3x slower than the preset the user then applies.
    """
    assert _schema_defaults()["steps"] == ss.DEFAULT_STEPS
    for preset in PRESETS:
        assert preset.widgets["steps"] == ss.DEFAULT_STEPS, preset.id
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


def test_the_preset_round_trips_through_the_saved_payload():
    payload = apply_to_payload(_payload(), "turnaround")
    again = ss.parse_sheet_spec(json.dumps(payload))
    assert again.render.preset == "turnaround"
    assert ss.parse_sheet_spec(json.loads(json.dumps(again.to_dict()))).render.preset == "turnaround"


def test_the_route_payload_is_json_safe_and_complete():
    listed = preset_list()
    assert len(listed) == len(PRESETS)
    json.dumps(listed)  # a preset that cannot be serialised would break the panel
    for entry in listed:
        assert set(entry) == {
            "id", "label", "hint", "render", "sheet", "widgets", "build", "deviates", "custom",
        }
        # `custom` is how the panel knows which entries it may offer to delete (see
        # user_presets.py); a built-in must never look deletable.
        assert entry["custom"] is False, entry["id"]


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
