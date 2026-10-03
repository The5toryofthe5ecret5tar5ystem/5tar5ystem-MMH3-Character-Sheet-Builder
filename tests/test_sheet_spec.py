"""Character Sheet Maker - spec parsing, vocabulary and prompt assembly.

Pinned here:

* the H3 frame grid (a cell length is always a valid 17k+5 chunk),
* the reference limits and the role -> ``<Picture N>`` legend,
* the unknown-value fallbacks (never a crash, always a warning),
* the prompt contract: identity text, legend, framing, pose, expression, extra.
"""

from __future__ import annotations

import json

import pytest

from h3cs import sheet_spec as ss


# --------------------------------------------------------------------------- #
# frame grid
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "requested,expected",
    [(1, 5), (5, 5), (6, 22), (21, 22), (22, 22), (23, 39), (39, 39), (40, 56), (100, 107)],
)
def test_align_h3_frames_rounds_up_to_the_17k_plus_5_grid(requested, expected):
    assert ss.align_h3_frames(requested) == expected


def test_align_h3_frames_clamps_and_survives_junk():
    assert ss.align_h3_frames(0) == 5
    assert ss.align_h3_frames(-4) == 5
    assert ss.align_h3_frames("nonsense") == ss.DEFAULT_CELL_FRAMES
    assert ss.align_h3_frames(99999) == ss.MAX_CELL_FRAMES


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def _payload(**overrides):
    data = {
        "name": "steph sheet!",
        "globalPrompt": "young woman with long dark hair",
        "refs": {
            "pictures": [
                {"imageFile": "face.png", "role": "face and hair"},
                {"imageFile": "body.png", "role": "body proportions"},
            ],
            "videos": [{"videoFile": "cloth.mp4", "role": "clothing and body movement"}],
        },
        "sheet": {"layout": "hero-left", "columns": 2, "shortEdge": 1536, "aspect": "3:2"},
        "render": {"framesPerCell": 22, "steps": 25, "seed": 7},
        "cells": [
            {"id": "hero", "view": "portrait", "pose": "neutral", "expression": "smile"},
            {"id": "a", "view": "front", "pose": "a-pose"},
        ],
    }
    data.update(overrides)
    return data


def test_parse_minimal_payload_gets_defaults_and_safe_name():
    spec = ss.parse_sheet_spec("{}")
    assert spec.name == "character_sheet"
    assert spec.layout.layout == "hero-left"
    assert spec.layout.aspect == ss.DEFAULT_ASPECT
    assert spec.cells == []
    assert any("No cells" in warning for warning in spec.warnings)


def test_parse_accepts_a_json_string_and_normalises_the_name():
    spec = ss.parse_sheet_spec(json.dumps(_payload()))
    assert spec.name == "steph_sheet"
    assert spec.global_prompt.startswith("young woman")
    assert spec.render.steps == 25
    assert spec.render.seed == 7
    assert [cell.id for cell in spec.cells] == ["hero", "a"]


def test_invalid_json_is_a_clear_error():
    with pytest.raises(ValueError, match="Invalid sheet_data JSON"):
        ss.parse_sheet_spec("{not json")


def test_reference_limits_are_enforced_with_a_warning():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": f"p{i}.png"} for i in range(12)],
                "videos": [{"videoFile": f"v{i}.mp4"} for i in range(5)],
                "audios": [{"audioFile": f"a{i}.wav"} for i in range(4)],
            },
            "cells": [{"id": "c1"}],
        }
    )
    assert len(spec.pictures) == ss.MAX_PICTURES
    assert len(spec.videos) == ss.MAX_VIDEOS
    assert len(spec.audios) == ss.MAX_AUDIOS
    assert any("first 9" in warning for warning in spec.warnings)


def test_reference_tags_follow_the_official_h3_vocabulary():
    spec = ss.parse_sheet_spec(_payload())
    assert [ref.tag for ref in spec.pictures] == ["<Picture 1>", "<Picture 2>"]
    assert spec.videos[0].tag == "<Video 1>"


def test_a_disabled_reference_does_not_consume_a_tag_number():
    """``<Picture N>`` must be the number the graph wires - H3 gets enabled refs only.

    A disabled slot used to eat an index, so the prompt could say "identity from
    <Picture 1>" while slot 0 held another photo - or name a tag the model never
    received. That is how a face cell ends up rendering somebody else's face.
    """
    from h3cs import planner as pl

    spec = ss.parse_sheet_spec(
        {
            "name": "shift",
            "refs": {
                "pictures": [
                    {"imageFile": "one.jpg", "role": "face and hair"},
                    {"imageFile": "two.jpg", "role": "body", "enabled": False},
                    {"imageFile": "three.jpg", "role": "clothes"},
                ]
            },
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    tags = {ref.file: ref.tag for ref in spec.pictures}
    assert tags["one.jpg"] == "<Picture 1>"
    assert tags["three.jpg"] == "<Picture 2>", "the third tile is the second image the run sends"
    wired = [
        (item["slot"].split(".")[-1], item["file"]) for item in pl.reference_plan(spec)["pictures"]
    ]
    assert wired == [("ref_image_0", "one.jpg"), ("ref_image_1", "three.jpg")]
    legend = ss.reference_legend(spec)
    assert "<Picture 3>" not in legend, "nothing is wired at slot 3"
    prompt = ss.build_cell_prompt(spec, spec.enabled_cells[0])
    assert "<Picture 2>" in prompt, "the second wired reference must be named in the prompt"


def test_ultrawide_and_invented_aspects_are_honoured():
    """21:9 is offered for the sheet and the cells; any ``W:H`` label works too."""
    assert "21:9" in ss.CELL_ASPECTS
    assert ss.aspect_ratio("21:9") == pytest.approx(21 / 9)
    assert ss.aspect_ratio("16:9") == pytest.approx(16 / 9)
    # A ratio the user types themselves is not silently replaced by the 3:2 default.
    assert ss.aspect_ratio("7:4") == pytest.approx(7 / 4)
    assert ss.aspect_ratio("banana") == pytest.approx(1.5), "nonsense still falls back"

    spec = ss.parse_sheet_spec(
        {
            "name": "wide",
            "sheet": {"layout": "grid", "columns": 3, "shortEdge": 1536, "aspect": "21:9"},
            "cells": [{"id": "c0", "view": "front"}],
        }
    )
    assert spec.layout.aspect == "21:9"
    assert spec.warnings == [], "a known ratio is not a warning"
    assert spec.to_dict()["sheet"]["aspect"] == "21:9", "and it survives the round trip"


def test_unknown_values_fall_back_and_are_reported():
    spec = ss.parse_sheet_spec(
        {
            "sheet": {"layout": "spiral", "fit": "squish", "aspect": "banana"},
            "cells": [
                {"id": "c1", "view": "upskirt", "pose": "splits", "expression": "manic",
                 "pick": "vibes"},
            ],
        }
    )
    cell = spec.cells[0]
    assert (cell.view, cell.pose, cell.expression) == ("front", "neutral", "neutral")
    assert cell.pick == "auto"
    assert spec.layout.layout == "hero-left"
    assert spec.layout.fit == "contain"
    messages = " | ".join(spec.warnings)
    for expected in ("view", "pose", "expression", "pick", "layout", "fit"):
        assert expected in messages


def test_cell_ids_are_sanitised_deduplicated_and_capped():
    spec = ss.parse_sheet_spec(
        {"cells": [{"id": "a b!"}, {"id": "a b!"}, *[{"id": f"c{i}"} for i in range(40)]]}
    )
    assert spec.cells[0].id == "a_b"
    assert spec.cells[1].id != spec.cells[0].id
    assert len(spec.cells) == ss.MAX_CELLS
    assert any("first 24" in warning for warning in spec.warnings)


def test_numeric_pick_is_treated_as_a_frame_index():
    spec = ss.parse_sheet_spec({"cells": [{"id": "c1", "pick": "7"}]})
    assert spec.cells[0].pick == "last"
    assert spec.cells[0].pick_index == 7


def test_placement_is_clamped_for_custom_layouts():
    spec = ss.parse_sheet_spec(
        {
            "sheet": {"layout": "custom"},
            "cells": [{"id": "c1", "place": {"row": 2, "col": 3, "colSpan": 99}}],
        }
    )
    place = spec.cells[0].place
    assert place["row"] == 2
    assert place["col"] == 3
    assert place["colSpan"] == 63


def test_spec_round_trips_through_to_dict():
    spec = ss.parse_sheet_spec(_payload())
    again = ss.parse_sheet_spec(json.dumps(spec.to_dict()))
    assert [cell.id for cell in again.cells] == [cell.id for cell in spec.cells]
    assert [(ref.kind, ref.file, ref.role) for ref in again.refs] == [
        (ref.kind, ref.file, ref.role) for ref in spec.refs
    ]
    assert again.layout.short_edge == spec.layout.short_edge
    assert again.render.frames_per_cell == spec.render.frames_per_cell


# --------------------------------------------------------------------------- #
# cell matrix builder
# --------------------------------------------------------------------------- #
def test_cell_matrix_expands_poses_for_body_views_and_expressions_for_face_views():
    cells = ss.cell_matrix(
        views=["face", "front"],
        poses=["neutral", "t-pose"],
        expressions=["neutral", "smile", "crying"],
    )
    keys = [(cell["view"], cell["pose"], cell["expression"]) for cell in cells]
    assert ("face", "neutral", "neutral") in keys
    assert ("face", "neutral", "crying") in keys
    assert ("front", "t-pose", "neutral") in keys
    # A face cell never picks up a pose from the pose list.
    assert all(pose == "neutral" for view, pose, _ in keys if view == "face")


def test_cell_matrix_falls_back_to_one_neutral_cell():
    cells = ss.cell_matrix(views=["portrait"])
    assert len(cells) == 1
    assert cells[0]["view"] == "portrait"


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #
def test_reference_legend_pairs_each_tag_with_its_role():
    spec = ss.parse_sheet_spec(_payload())
    legend = ss.reference_legend(spec)
    # The roles are read as attributes, so the ownership is stated the way the working
    # ref2va prompts state it: "sole source" when nothing else claims it.
    assert "<Picture 1> is the sole source of the face and the hair." in legend
    assert (
        "<Picture 2> is the body proportions reference." in legend
    ), "the video also claims the body, so picture 2 is not its sole source"
    assert (
        "<Video 1> is the clothing and body movement reference and the only source of "
        "the clothing." in legend
    ), "a role that is half shared keeps its own words and claims what is left"


def test_the_legend_keeps_role_words_the_vocabulary_cannot_read():
    """A word like "head" is the only description of the reference - it must survive."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg", "role": "head, face, hair"}]},
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    assert ss.unmatched_role_words("head, face, hair") == ["head"]
    assert ss.unmatched_role_words("face and hair") == [], "filler is not a description"
    assert (
        "<Picture 1> (head, face, hair) is the sole source of the face and the hair."
        in ss.reference_legend(spec)
    )


def test_a_shared_attribute_is_never_called_a_sole_source():
    """"Sole source" is a claim about this run, so it needs the whole set to compute."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {"imageFile": "a.jpg", "role": "face and hair"},
                    {"imageFile": "b.jpg", "role": "face and hair"},
                ]
            },
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    legend = ss.reference_legend(spec)
    assert "sole source" not in legend, "two claimants is a match, not an ownership"
    assert "<Picture 1> is the face and hair reference." in legend
    assert "<Picture 2> is the face and hair reference." in legend


def test_disabled_references_are_dropped_from_the_legend():
    payload = _payload()
    payload["refs"]["pictures"][1]["enabled"] = False
    spec = ss.parse_sheet_spec(payload)
    legend = ss.reference_legend(spec)
    assert "<Picture 2>" not in legend


def test_a_reference_without_a_role_gets_a_neutral_sentence():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.png"}],
                "videos": [{"videoFile": "b.mp4", "role": "reference"}],
                "audios": [{"audioFile": "c.wav"}],
            },
            "cells": [{"id": "c1"}],
        }
    )
    legend = ss.reference_legend(spec)
    assert "<Picture 1> is a character reference image." in legend
    assert "<Video 1> is a character reference video." in legend
    assert "<Audio 1> is a voice reference." in legend
    assert "reference reference" not in legend


def test_negative_prompt_is_applied_and_optional():
    payload = _payload()
    spec = ss.parse_sheet_spec(payload)
    assert "Do not include" not in ss.build_cell_prompt(spec, spec.cells[0])

    payload["negativePrompt"] = "text, watermark, logo"
    spec = ss.parse_sheet_spec(payload)
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Do not include: text, watermark, logo." in prompt
    # it belongs to the framing block, before the fixed trailer
    assert prompt.index("Do not include") < prompt.index("Single person against a plain neutral background")


def test_background_is_a_preset_the_user_picks():
    spec = ss.parse_sheet_spec(_payload())
    assert spec.render.background == "neutral"
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Single person against a plain neutral background" in prompt
    assert "no text, no watermark, no extra people." in prompt
    # H3 invents a room around a subject unless it is told not to.
    assert "no room, no walls, no floor" in prompt
    assert "no doors" in prompt and "no furniture" in prompt

    for key, expected in (
        ("white", "a flat seamless pure white background"),
        ("grey", "a flat seamless mid-grey studio background"),
        ("black", "a flat seamless black background"),
        ("green", "a flat uniform chroma-key green screen (#00B140)"),
        ("blue", "a flat uniform chroma-key blue screen (#0000FF)"),
    ):
        payload = _payload()
        payload["render"] = {"background": key}
        spec = ss.parse_sheet_spec(payload)
        assert spec.render.background == key
        for cell in spec.cells:
            cell_prompt = ss.build_cell_prompt(spec, cell)
            assert expected in cell_prompt, f"{key}: {cell_prompt}"
            assert "no watermark" in cell_prompt, "the trailer survives every background"
            assert "no room" in cell_prompt, f"{key} forgot the no-set guard"

    # Green screen carries the spill guard: green fringes are what make a key
    # unusable, and H3 will happily paint them.
    payload = _payload()
    payload["render"] = {"background": "green"}
    spec = ss.parse_sheet_spec(payload)
    assert "no green spill" in ss.build_cell_prompt(spec, spec.cells[0])


def test_background_custom_uses_the_users_own_words():
    payload = _payload()
    payload["render"] = {"background": "custom", "backgroundCustom": "Deep red velvet curtain. "}
    spec = ss.parse_sheet_spec(payload)
    assert spec.render.background == "custom"
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "a flat uniform backdrop of deep red velvet curtain" in prompt
    # The complaint that started this: "neutral tan" alone made H3 build a tan ROOM.
    assert "no room, no walls, no floor" in prompt
    assert not spec.warnings, spec.warnings


def test_custom_background_is_still_a_flat_backdrop():
    payload = _payload()
    payload["render"] = {"background": "custom", "backgroundCustom": "Neutral tan"}
    spec = ss.parse_sheet_spec(payload)
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "a flat uniform backdrop of neutral tan" in prompt
    assert "filling the frame behind the subject with nothing else in shot" in prompt


def test_junk_backgrounds_fall_back_with_a_warning():
    payload = _payload()
    payload["render"] = {"background": "plaid"}
    spec = ss.parse_sheet_spec(payload)
    assert spec.render.background == "neutral"
    assert any("plaid" in warning for warning in spec.warnings)

    # "custom" with nothing typed is the same mistake, not an empty backdrop.
    payload["render"] = {"background": "custom", "backgroundCustom": "   "}
    spec = ss.parse_sheet_spec(payload)
    assert spec.render.background == "neutral"
    assert any("custom" in warning for warning in spec.warnings)


def test_background_survives_the_payload_round_trip():
    payload = _payload()
    payload["render"] = {"background": "green", "backgroundCustom": "unused"}
    spec = ss.parse_sheet_spec(payload)
    again = ss.parse_sheet_spec(json.dumps(spec.to_dict()))
    assert again.render.background == "green"
    assert again.render.background_custom == "unused"


def test_neutral_tan_is_a_backdrop_of_its_own():
    """The sheet's own backdrop: the tan the composite and the prompt name together."""
    assert "tan" in ss.BACKGROUND_KEYS
    option = next(item for item in ss.BACKGROUNDS if item.key == "tan")
    assert option.label == "Neutral tan"
    assert ss.TAN_HEX in option.prompt

    payload = _payload()
    payload["render"] = {"background": "tan"}
    spec = ss.parse_sheet_spec(payload)
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert f"a flat seamless neutral tan backdrop ({ss.TAN_HEX})" in prompt
    assert ss.describe_background(spec) == "Neutral tan (tan)"
    assert not spec.warnings, spec.warnings


def test_every_backdrop_is_flat_and_casts_no_shadow():
    """A sheet is one look; a backdrop with a falloff or a shadow makes it N photos.

    Every preset (and the user's own words) has to say so - "evenly lit" on its own still
    comes back with a gradient behind the head and a shadow under the subject.
    """
    for option in ss.BACKGROUNDS:
        if option.key in ("reference", "custom"):
            continue
        assert "flat and completely uniform" in option.prompt, option.key
        assert "no gradient" in option.prompt and "no vignette" in option.prompt, option.key
        assert "no shadow of the subject cast onto it" in option.prompt, option.key
        assert "no room, no walls" in option.prompt, f"{option.key} forgot the no-set guard"

    payload = _payload()
    payload["render"] = {"background": "custom", "backgroundCustom": "Brushed steel"}
    spec = ss.parse_sheet_spec(payload)
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "no shadow of the subject cast onto it" in prompt, "custom wording is flat too"


def test_reference_backdrop_borrows_the_setting_of_the_reference_it_names():
    """'Reference' keeps the place and replaces the people - and says which is which.

    H3's tags number the references the run actually wires, so the backdrop has to be named
    with the same tag the legend uses, or the setting is taken from the wrong picture.
    """
    payload = _payload()
    payload["render"] = {"background": "reference", "backgroundRef": "pictures:1"}
    spec = ss.parse_sheet_spec(payload)
    assert not spec.warnings, spec.warnings
    reference = ss.background_reference(spec)
    assert reference is not None and reference.tag == "<Picture 2>", "the second picture"
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "the same setting and backdrop as <Picture 2>" in prompt
    assert "use <Picture 2> for the BACKGROUND ONLY" in prompt
    assert "no extra people, no props added" in prompt
    # The place IS wanted here, so the no-set guard must not be part of this clause.
    assert "no room, no walls, no floor" not in prompt
    # Flat still applies: the backdrop should not gain a shadow the reference did not have.
    assert "no shadow of the subject cast onto it" in prompt

    # A video supplies a place rather than a backdrop, and says so.
    payload["render"] = {"background": "reference", "backgroundRef": "videos:0"}
    spec = ss.parse_sheet_spec(payload)
    assert "the same place, room and lighting as <Video 1>" in ss.background_clause(spec)
    assert ss.describe_background(spec) == "the setting of <Video 1> (reference)"


def test_reference_backdrop_falls_back_when_its_reference_is_gone():
    """A stale key (or none at all) renders neutral, and says why rather than silently."""
    for key, expected in (("", "nothing"), ("pictures:9", "'pictures:9'"), ("audios:0", "'audios:0'")):
        payload = _payload()
        payload["render"] = {"background": "reference", "backgroundRef": key}
        spec = ss.parse_sheet_spec(payload)
        assert ss.background_reference(spec) is None
        assert any(expected in warning for warning in spec.warnings), spec.warnings
        prompt = ss.build_cell_prompt(spec, spec.cells[0])
        assert "a plain neutral background" in prompt, "the fallback is the neutral preset"
        assert "no room, no walls, no floor" in prompt
        assert "reference" in ss.describe_background(spec)

    # A disabled slot is not wired, so it cannot supply a backdrop either.
    payload = _payload()
    payload["refs"]["pictures"][1]["enabled"] = False
    payload["render"] = {"background": "reference", "backgroundRef": "pictures:1"}
    spec = ss.parse_sheet_spec(payload)
    assert ss.background_reference(spec) is None
    assert any("pictures:1" in warning for warning in spec.warnings), spec.warnings


def test_reference_backdrop_survives_the_payload_round_trip():
    payload = _payload()
    payload["render"] = {"background": "reference", "backgroundRef": "Videos:0"}
    spec = ss.parse_sheet_spec(payload)
    assert spec.render.background_ref == "videos:0", "keys are normalised"
    assert spec.to_dict()["render"]["backgroundRef"] == "videos:0"
    again = ss.parse_sheet_spec(json.dumps(spec.to_dict()))
    assert ss.describe_background(again) == "the setting of <Video 1> (reference)"
    assert not again.warnings, again.warnings


def test_global_prompt_leads_every_cell_prompt():
    payload = _payload()
    payload["globalPrompt"] = "young woman with long silver hair"
    spec = ss.parse_sheet_spec(payload)
    for cell in spec.cells:
        prompt = ss.build_cell_prompt(spec, cell)
        assert prompt.startswith("young woman with long silver hair")


# --------------------------------------------------------------------------- #
# reference attribution: which picture may supply what
# --------------------------------------------------------------------------- #
def _two_ref_spec(**cell):
    """The pair that started this: a face picture and a body/clothes picture."""
    return ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {"imageFile": "face.jpg", "role": "face, hair, glasses"},
                    {"imageFile": "body.jpg", "role": "body and clothes"},
                ]
            },
            "cells": [{"id": "c", **cell}],
        }
    )


def test_roles_are_read_into_attributes():
    assert ss.reference_attributes("face, hair, glasses") == {"face", "hair", "glasses"}
    assert ss.reference_attributes("body and clothes") == {"body", "clothing"}
    assert ss.reference_attributes("voice") == {"voice"}
    assert ss.reference_attributes("") == set()


def test_a_cell_only_gets_the_references_its_framing_can_show():
    """The reported bug: a face close-up rendered the OTHER picture's face.

    H3 conditions on every reference it is handed and has no per-reference weight, so
    asking is not enough - the outfit photo has to be left out of the wiring.
    """
    spec = _two_ref_spec(view="face")
    cell = spec.enabled_cells[0]
    refs = ss.cell_references(spec, cell)
    assert [(ref.tag, ref.file) for ref in refs] == [("<Picture 1>", "face.jpg")]
    prompt = ss.build_cell_prompt(spec, cell, refs=refs)
    assert "<Picture 1>" in prompt
    assert "<Picture 2>" not in prompt, "a picture the run did not wire must never be named"
    assert "Use <Picture 1> for the face, the glasses and the hair." in prompt

    # A portrait still shows the outfit, so both references stay.
    portrait = _two_ref_spec(view="portrait").enabled_cells[0]
    kept = ss.cell_references(_two_ref_spec(view="portrait"), portrait)
    assert [ref.file for ref in kept] == ["face.jpg", "body.jpg"]

    # Behind the subject the face is hidden but the hair is not: keep the face picture.
    back = _two_ref_spec(view="back")
    assert [ref.file for ref in ss.cell_references(back, back.enabled_cells[0])] == [
        "face.jpg",
        "body.jpg",
    ]


def test_the_framing_filter_can_be_turned_off_and_never_leaves_a_cell_bare():
    spec = _two_ref_spec(view="face")
    cell = spec.enabled_cells[0]
    every = ss.cell_references(spec, cell, scope="every cell")
    assert [ref.file for ref in every] == ["face.jpg", "body.jpg"]

    # Only an outfit reference and a face cell: keep it rather than conditioning on
    # nothing at all.
    only_outfit = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "outfit.jpg", "role": "clothing and body"}]},
            "cells": [{"id": "c", "view": "face"}],
        }
    )
    kept = ss.cell_references(only_outfit, only_outfit.enabled_cells[0])
    assert [(ref.tag, ref.file) for ref in kept] == [("<Picture 1>", "outfit.jpg")]


def test_a_cell_renumbers_the_references_it_receives():
    """Dropping a reference renumbers the rest, and the prompt follows the wiring."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {"imageFile": "outfit.jpg", "role": "clothing and body"},
                    {"imageFile": "face.jpg", "role": "face and hair"},
                ]
            },
            "cells": [{"id": "c", "view": "face"}],
        }
    )
    cell = spec.enabled_cells[0]
    refs = ss.cell_references(spec, cell)
    assert [(ref.tag, ref.file, ref.source) for ref in refs] == [
        ("<Picture 1>", "face.jpg", 1)
    ], "the second picture is now the first one H3 sees"
    assert "<Picture 2>" not in ss.build_cell_prompt(spec, cell, refs=refs)
    # "glasses" must not also register as a generic accessory, and a word that only
    # looks like a keyword ("topic") must not register as clothing.
    assert "accessories" not in ss.reference_attributes("glasses")
    assert ss.reference_attributes("topic") == set(), "a bare prefix match is too greedy"
    assert ss.reference_attributes("tops, boots") == {"clothing", "shoes"}, "plurals still land"


def test_each_picture_is_told_what_it_supplies_and_what_it_must_not():
    spec = _two_ref_spec(view="front")
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Take the face, the glasses and the hair only from <Picture 1>." in prompt
    assert "Take the clothing and the body proportions only from <Picture 2>." in prompt
    # The prohibitions are the hardening: the portrait wore picture 1's top because
    # nothing said picture 1 may not supply clothing.
    assert "<Picture 1> must not change the body proportions and the clothing." in prompt
    assert "<Picture 2> must not change the face, the glasses and the hair" in prompt
    assert "the identity comes from <Picture 1> and from no other reference" in prompt


def test_a_non_identity_reference_is_told_not_to_supply_a_face():
    """The outfit photo is a whole second person, so say its face is not the identity.

    Naming the owner of the face is not enough on its own: a complete second person in
    the reference set is a complete second identity, which is how the full-body cells
    ended up wearing picture 2's face. This is the sentence that names the failure.
    """
    spec = _two_ref_spec(view="portrait")
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert (
        "must not supply a face, a hairstyle, skin tone or facial features" in prompt
    )
    assert "the person visible in it is not the identity, do not copy their face" in prompt
    assert "<Picture 2> must not change the face, the glasses and the hair, and must not supply" in prompt
    # The identity picture supplies the face, so it is never told not to.
    assert "<Picture 1> must not supply a face" not in prompt
    # And the last thing the sampler reads is the identity restatement.
    assert prompt.rstrip().endswith(
        "Identity: the face and the hair in this image come from <Picture 1> and from "
        "no other reference - do not blend them with the face of another reference."
    )


def test_a_reference_with_an_unreadable_role_is_not_called_a_non_identity():
    """An empty role must not be accused of not being the identity - it may well be it."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg"}, {"imageFile": "b.jpg", "role": "clothes"}]},
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "must not supply a face" not in prompt
    assert "not the identity" not in prompt
    assert "Reference rule:" in prompt, "the static-reference rule still applies"


def test_a_single_reference_gets_no_exclusivity_or_reminder():
    """With one reference there is nothing to blend, so the closing lines stay out."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "all.jpg", "role": "face, hair, clothing"}]},
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "only from" not in prompt
    assert "Reference rule:" not in prompt
    assert "Identity:" not in prompt


def test_the_outfit_is_pinned_to_its_reference():
    spec = _two_ref_spec(view="back")
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    framing = prompt.split("\n\n")[-1]
    assert "Take the clothing and the body proportions only from <Picture 2>." in framing
    assert "fully dressed - nothing removed, opened, shortened or swapped" in framing
    # a from-behind cell cannot match glasses nobody can see
    assert "glasses" not in framing
    assert "<Picture 2> must not change the hair," in framing


def test_the_face_close_up_is_not_told_about_the_outfit():
    """A framing that cannot show the outfit gets no outfit instruction at all.

    Checked on the framing block: the legend is the tag -> role block and still names
    what every reference is for, but the cell itself must not be handed clothes it
    cannot see - and the wiring drops that reference entirely (see
    :func:`test_a_cell_only_gets_the_references_its_framing_can_show`).
    """
    spec = _two_ref_spec(view="face")
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    framing = prompt.split("\n\n")[-1]
    assert "Take the face, the glasses and the hair only from <Picture 1>." in framing
    assert "clothing" not in framing
    # no headwear from the other picture is exactly the bow-in-the-hair report
    assert "no added headwear" in framing


def test_side_and_back_views_keep_the_side_face_and_the_outfit_instructions():
    spec = _two_ref_spec(view="profile")
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "only the side of the face is visible" in prompt
    assert "Take the clothing and the body proportions only from <Picture 2>." in prompt


def test_a_reference_without_a_role_claims_nothing():
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg"}, {"imageFile": "b.jpg", "role": "clothes"}]},
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Take the clothing only from <Picture 2>." in prompt
    assert "Use <Picture 1> for" not in prompt, "an empty role must not invent a claim"
    # the picture that claims the clothing is the only source for it, so the
    # role-less one must not change it either
    assert "<Picture 1> must not change the clothing." in prompt


def test_one_picture_that_supplies_everything_needs_no_prohibitions():
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "all.jpg", "role": "face, hair, body, clothes"}]},
            "cells": [{"id": "c", "view": "front"}],
        }
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Use <Picture 1> for the face, the hair, the clothing and the body proportions." in prompt
    assert "must not change" not in prompt
    assert "identity from" not in prompt, "one reference is not a contradiction to resolve"


def test_no_reference_falls_back_to_a_plain_identity_line():
    spec = ss.parse_sheet_spec({"cells": [{"id": "c", "view": "front"}]})
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "Keep the same person across every image" in prompt
    assert "<Picture" not in prompt


def test_cell_prompt_order_and_content():
    spec = ss.parse_sheet_spec(_payload())
    cell = spec.cells[1]  # front + a-pose
    prompt = ss.build_cell_prompt(spec, cell)
    identity, legend, framing = prompt.split("\n\n")[0], prompt.split("\n\n")[1], prompt.split("\n\n")[2]
    assert identity == "young woman with long dark hair"
    assert "<Picture 1> is the sole source of the face and the hair." in legend
    assert "Full body straight on" in framing
    assert "A-pose" in framing
    assert "Take the face and the hair only from <Picture 1>." in framing
    assert "Take the clothing only from <Video 1>." in framing
    # two references claim the body, so it is a "match", not an owner
    assert "Match the body proportions to <Picture 2> and <Video 1>." in framing
    assert "<Picture 1> must not change the clothing." in framing
    assert "Reference rule: the references are static" in framing
    assert "no watermark" in framing


def test_expression_is_honoured_even_on_a_body_view():
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "face.png", "role": "face"}]},
            "cells": [{"id": "c1", "view": "front", "pose": "t-pose", "expression": "anger"}],
        }
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert "T-pose" in prompt
    assert "Angry expression" in prompt


def test_side_and_back_views_do_not_look_at_the_camera():
    spec = ss.parse_sheet_spec(
        {
            "cells": [
                {"id": "side", "view": "profile"},
                {"id": "rear", "view": "back"},
            ]
        }
    )
    side = ss.build_cell_prompt(spec, spec.cells[0])
    assert "90 degrees" in side
    assert "only the side of the face is visible" in side
    assert "no eye contact" in side

    rear = ss.build_cell_prompt(spec, spec.cells[1])
    assert "from directly behind" in rear
    assert "not looking at the viewer" in rear

    # An expression is a face instruction: it must not leak onto a from-behind shot,
    # where every expression prompt describes the eyes.
    spec_back = ss.parse_sheet_spec(
        {"cells": [{"id": "rear", "view": "back", "expression": "smile"}]}
    )
    prompt = ss.build_cell_prompt(spec_back, spec_back.cells[0])
    assert "Warm smile" not in prompt
    assert "not looking at the viewer" in prompt

    # On a profile it survives, scoped to what can be seen from the side.
    spec_side = ss.parse_sheet_spec(
        {"cells": [{"id": "side", "view": "profile", "expression": "smile"}]}
    )
    side_prompt = ss.build_cell_prompt(spec_side, spec_side.cells[0])
    assert "Warm smile" in side_prompt and "Visible in profile only" in side_prompt


def test_extra_prompt_comes_last():
    spec = ss.parse_sheet_spec(
        {"cells": [{"id": "c1", "view": "front", "extraPrompt": "holding a sword"}]}
    )
    prompt = ss.build_cell_prompt(spec, spec.cells[0])
    assert prompt.rstrip().endswith("holding a sword")


def test_cell_label_defaults_to_view_pose_and_expression():
    spec = ss.parse_sheet_spec(
        {"cells": [{"id": "c1", "view": "front", "pose": "t-pose"},
                   {"id": "c2", "view": "face", "expression": "smirk"}]}
    )
    assert "T-pose" in spec.cells[0].label
    assert "Smirk" in spec.cells[1].label
