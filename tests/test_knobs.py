# ComfyUI-H3-Character-Sheet - compact settings (the node's knobs, as data).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The panel draws the node's knobs itself, so this table has to match the node.

The frontend lays a native widget out one per row, full width, with no column-span API, so
23 knobs cost ~500px of node height that the panel can spend in three columns. What makes
that safe is that the panel does not invent the knobs: ``knobs.py`` reads them from the node
schema (``INPUT_TYPES``, the same source the server serves as ``object_info``), so a knob can
never be shown with bounds the node would reject - or be missing entirely.

These tests are the two directions of that promise:

* every widget the node has is described (a new knob must reach the panel, or it disappears
  from the node the moment the pack hides the native rows);
* every description still points at a widget (a renamed knob must not leave a dead field).
"""

from __future__ import annotations

from h3cs import knobs
from h3cs.nodes.sheet import MiniMaxH3CharacterSheet

LINK_SECTIONS = ("required", "optional")


def _schema() -> dict:
    return MiniMaxH3CharacterSheet.INPUT_TYPES()


def _schema_knobs() -> dict:
    """Every non-link, non-internal widget, as ``name -> (type, meta)``."""
    out = {}
    for section in LINK_SECTIONS:
        for name, entry in (_schema().get(section) or {}).items():
            if name in knobs.SKIPPED_WIDGETS:
                continue
            if str(entry[0]).upper() in knobs.LINK_TYPES:
                continue
            out[name] = (str(entry[0]), dict(entry[1]) if len(entry) > 1 else {})
    return out


def test_every_knob_the_node_has_is_described():
    described = [knob["name"] for knob in knobs.knob_list() if not knob.get("frontend")]
    assert described == list(_schema_knobs()), "the described knobs must be exactly the node's, in order"


def test_the_browser_s_own_widgets_are_described_too():
    """`control_after_generate` is added by the frontend, not the schema.

    The panel can write it, and the node hides every row, so leaving it out would take the
    seed's mode (fixed / randomize / ...) away from the user.
    """
    by_name = {knob["name"]: knob for knob in knobs.knob_list()}
    entry = by_name["control_after_generate"]
    assert entry["frontend"] is True
    assert entry["kind"] == "select"
    assert entry["options"] == ["fixed", "increment", "decrement", "randomize"]
    assert "control_after_generate" not in _schema_knobs(), "it really is not in the schema"
    names = [knob["name"] for knob in knobs.knob_list()]
    assert names[names.index("seed") + 1] == "control_after_generate", "it belongs next to the seed"


def test_the_links_and_the_panel_storage_are_not_knobs():
    described = {knob["name"] for knob in knobs.knob_list()}
    assert not described & {"model", "video_vae", "audio_vae", "clip"}, "sockets are not knobs"
    assert not described & knobs.SKIPPED_WIDGETS, "sheet_data and the panel widget are not knobs"


def test_no_description_points_at_a_widget_that_is_gone():
    live = {knob["name"] for knob in knobs.knob_list()}
    known = {entry["name"] for entry in (*knobs.KNOB_LAYOUT, *knobs.FRONTEND_KNOBS)}
    assert known <= live, f"these have no field any more: {sorted(known - live)}"
    stale = [entry["name"] for entry in knobs.KNOB_LAYOUT if entry["name"] not in live]
    assert stale == [], f"label layout mentions widgets the node no longer has: {stale}"


def test_every_knob_is_labelled_and_grouped():
    for knob in knobs.knob_list():
        assert knob["label"] and knob["label"] != knob["name"], f"{knob['name']} has no short label"
        assert knob["group"] in knobs.KNOB_GROUPS, f"{knob['name']} has no declared group"
        assert knob["span"] >= 1


def test_bounds_and_choices_come_from_the_schema():
    """A panel field must not be able to offer what the node would reject."""
    by_name = {knob["name"]: knob for knob in knobs.knob_list()}
    meta = _schema_knobs()

    cell = by_name["cell_size"]
    assert (cell["kind"], cell["min"], cell["max"], cell["step"]) == ("number", 256, 2048, 32)
    assert cell["min"] == meta["cell_size"][1]["min"]
    assert cell["max"] == meta["cell_size"][1]["max"]

    sampler = by_name["sampler_name"]
    assert sampler["kind"] == "select"
    assert sampler["options"] == list(meta["sampler_name"][1]["options"]), "the choices are the node's own"
    assert "res_multistep" in sampler["options"]

    assert by_name["continuity"]["options"] == ["off", "auto", "on"]
    assert by_name["export_video"]["kind"] == "toggle"
    assert by_name["sheet_background"]["kind"] == "text"
    assert by_name["output_name"]["kind"] == "text"
    assert by_name["output_name"]["default"] == "character_sheet"


def test_groups_keep_the_declared_order_and_hold_every_knob_once():
    listing = knobs.knob_list()
    groups = knobs.knob_groups(listing)
    assert [group["group"] for group in groups] == list(knobs.KNOB_GROUPS)
    named = [knob["name"] for group in groups for knob in group["knobs"]]
    assert sorted(named) == sorted(knob["name"] for knob in listing)
    assert len(named) == len(set(named)), "a knob appears in exactly one group"


def test_an_undeclared_group_still_reaches_the_panel():
    """A new knob without a group must be reachable, not silently invisible."""
    listing = knobs.knob_list() + [
        {"name": "brand_new", "label": "New", "group": "Other", "kind": "number", "span": 1}
    ]
    groups = knobs.knob_groups(listing)
    assert "Other" in [group["group"] for group in groups]
    assert [group["group"] for group in groups][-1] == "Other", "declared groups come first"


def test_the_column_count_is_the_panel_s_own_choice():
    """The panel packs the grid; the backend only describes the knobs."""
    assert "span" in knobs.knob_list()[0]
    assert knobs.knob_list()[0]["span"] in (1, 2)


def test_each_knob_says_whether_the_node_owns_it():
    """The flag the tests above rely on has to be on every entry, not implied by absence."""
    for entry in knobs.knob_list():
        assert isinstance(entry["frontend"], bool)
    assert sum(1 for entry in knobs.knob_list() if entry["frontend"]) == len(knobs.FRONTEND_KNOBS)
