"""The sheet's tick vocabulary: what the panel offers and what each framing does.

The point of these is not the wording of any one prompt - it is that the three tables that
have to agree about a view DO agree: the view has a prompt, continuation knows its camera
distance, the reference filter knows what it cannot show, and "Build cells" knows which axis
to expand it along. A view added to one table and forgotten in another either breaks the
chain rule or silently ignores a tick, and neither shows up as an error at render time.
"""

from __future__ import annotations

import pytest

from h3cs import sheet_spec as ss


# --------------------------------------------------------------------------- #
# the tables agree about every view
# --------------------------------------------------------------------------- #
def test_every_view_is_described_in_every_table():
    assert len(ss.VIEW_KEYS) == len(set(ss.VIEW_KEYS)), "a view key is duplicated"
    for key in ss.VIEW_KEYS:
        option = ss._VIEW_BY_KEY[key]
        assert len(option.prompt) > 60, f"{key}: the framing text is too thin to steer a render"
        assert option.label and option.label.strip(), f"{key}: no label for the panel"
        assert key in ss.FRAMING_DISTANCES, f"{key}: continuation cannot place its camera"
        assert ss.FRAMING_DISTANCES[key] in ("close", "medium", "full")
        assert key in ss.VIEW_VARIANTS, f"{key}: Build cells does not know its axis"
        assert ss.VIEW_VARIANTS[key] in ("pose", "expression", "single")


def test_the_framing_sets_and_the_variant_axis_agree():
    """A whole-body framing takes poses, a facial one takes expressions - no crossover."""
    for key in ss.POSE_FRAMINGS:
        assert ss.VIEW_VARIANTS[key] == "pose", f"{key} is a body framing but not a pose axis"
    for key in ss.FACE_FRAMINGS:
        assert ss.VIEW_VARIANTS[key] == "expression", f"{key} shows the face but not expressions"
    for key in ss.NO_FACE_FRAMINGS:
        assert key not in ss.FACE_FRAMINGS, f"{key} has no face in it"
    assert set(ss.POSE_FRAMINGS) | set(ss.FACE_FRAMINGS) | set(ss.NO_FACE_FRAMINGS) == set(ss.VIEW_KEYS)
    assert not (set(ss.POSE_FRAMINGS) & set(ss.FACE_FRAMINGS))


def test_a_pose_framing_can_see_the_whole_figure():
    """Poses only make sense where the figure is in frame, and those are the full shots."""
    for key in ss.POSE_FRAMINGS:
        assert ss.FRAMING_DISTANCES[key] == "full", f"{key} takes poses but is not a full shot"


# --------------------------------------------------------------------------- #
# the new framings
# --------------------------------------------------------------------------- #
def test_the_turnaround_gained_the_angles_between_front_and_back():
    assert ss._VIEW_BY_KEY["three-quarter"].label.startswith("Three-quarter")
    assert ss._VIEW_BY_KEY["three-quarter-back"].label.startswith("Three-quarter back")
    # Continuation's whole point: 45s chain with the 90s, because the camera did not move.
    assert ss.framing_distance("three-quarter") == ss.framing_distance("front") == "full"
    assert ss.framing_distance("three-quarter-back") == ss.framing_distance("back") == "full"


def test_the_head_detail_framings_are_close_ups():
    for key in ("face-profile", "head-back"):
        assert ss.framing_distance(key) == "close", f"{key} is a head shot, not a full body"
    # And they must not be told about an outfit the frame cannot hold.
    for hidden in ("clothing", "body", "legwear", "shoes"):
        assert hidden in ss.attributes_hidden_by("face-profile")
        assert hidden in ss.attributes_hidden_by("head-back")


def test_the_detail_crops_get_a_single_cell():
    """A crop of the hands does not change with a pose or a smile - so it must not multiply.

    The eyes close-up is the deliberate exception: an expression IS what an eye shot is
    about (closed lids, a wink, heavy lids), so it takes the expression axis like the face.
    """
    for key in ("hands", "legs", "head-back"):
        assert ss.VIEW_VARIANTS[key] == "single", key
    assert ss.VIEW_VARIANTS["eyes"] == "expression"

    cells = ss.cell_matrix(
        views=["hands", "front"],
        poses=["neutral", "sitting"],
        expressions=["neutral", "orgasm"],
    )
    assert [cell["id"] for cell in cells] == [
        "hands-neutral-neutral",
        "front-neutral-neutral",
        "front-sitting-neutral",
    ], "the crop contributes one cell, the full body one per pose"

    eye_cells = ss.cell_matrix(views=["eyes"], poses=["neutral"], expressions=["neutral", "wink"])
    assert [cell["expression"] for cell in eye_cells] == ["neutral", "wink"]


def test_the_detail_crops_hide_what_they_cannot_show():
    assert "body" in ss.attributes_hidden_by("hands")
    assert "clothing" not in ss.attributes_hidden_by("hands"), "sleeves are in a hand shot"
    assert "glasses" not in ss.attributes_hidden_by("eyes"), "glasses are IN an eye close-up"
    assert "face" in ss.attributes_hidden_by("legs")


# --------------------------------------------------------------------------- #
# prompt assembly for the new framings
# --------------------------------------------------------------------------- #
def _cell(view: str, *, pose: str = "neutral", expression: str = "neutral"):
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg", "role": "face and hair"}]},
            "cells": [{"id": "c", "view": view, "pose": pose, "expression": expression}],
        }
    )
    return spec, spec.cells[0]


def test_a_body_framing_still_carries_an_expression():
    spec, cell = _cell("three-quarter", expression="pleasure")
    prompt = ss.build_cell_prompt(spec, cell)
    assert ss.EXPRESSIONS[ss.EXPRESSION_KEYS.index("pleasure")].prompt in prompt
    spec, high = _cell("high-angle", expression="orgasm")
    assert ss.EXPRESSIONS[ss.EXPRESSION_KEYS.index("orgasm")].prompt in ss.build_cell_prompt(spec, high)


def test_a_framing_with_no_face_in_it_never_gets_an_expression():
    """"Smiling" in a hands crop only invents a face at the edge of the frame."""
    for view in ("hands", "legs", "head-back"):
        spec, cell = _cell(view, expression="orgasm")
        prompt = ss.build_cell_prompt(spec, cell)
        assert "gasp" not in prompt, f"{view} should not carry an expression"
        assert "flushed" not in prompt


def test_a_side_framing_says_the_expression_reads_in_profile():
    spec, cell = _cell("profile", expression="smile")
    prompt = ss.build_cell_prompt(spec, cell)
    assert "Visible in profile only." in prompt
    assert "Warm smile." in prompt
    assert "eyes engaged" not in prompt, (
        "a side view already says 'no eye contact with the viewer': an expression that "
        "asks for eye contact there is a contradiction the model resolves by turning the "
        "subject back to the lens (measured: the profile cell rendered frontal)"
    )
    spec2, cell2 = _cell("face-profile", expression="smile")
    prompt2 = ss.build_cell_prompt(spec2, cell2)
    assert "Warm smile, eyes engaged." in prompt2, (
        "a head profile shows the whole face side, and does not say 'no eye contact'"
    )
    assert "Visible in profile only." not in prompt2, "a head profile shows the whole face side"


def test_the_aside_is_only_used_where_the_view_text_forbids_eye_contact():
    """Data-driven: the rule reads the view's own text, so the two cannot drift apart."""
    assert "profile" in ss.NO_EYE_CONTACT_VIEWS
    assert "back" in ss.NO_EYE_CONTACT_VIEWS
    assert "face" not in ss.NO_EYE_CONTACT_VIEWS
    assert "front" not in ss.NO_EYE_CONTACT_VIEWS
    smile = ss.EXPRESSIONS[ss.EXPRESSION_KEYS.index("smile")]
    assert smile.aside and "eyes engaged" not in smile.aside
    assert ss.expression_reads_in_view(smile, "profile") == smile.aside
    assert ss.expression_reads_in_view(smile, "face") == smile.prompt


def test_a_face_framing_keeps_the_eye_contact_the_expression_asks_for():
    """The aside is for the framings that cannot hold eye contact, not a general softening."""
    spec, cell = _cell("face", expression="smile")
    assert "Warm smile, eyes engaged." in ss.build_cell_prompt(spec, cell)
    spec3, cell3 = _cell("front", expression="smile")
    assert "Warm smile, eyes engaged." in ss.build_cell_prompt(spec3, cell3)


def test_a_body_framing_with_a_non_neutral_pose_says_so():
    spec, cell = _cell("three-quarter", pose="reach-camera")
    prompt = ss.build_cell_prompt(spec, cell)
    assert "reaching straight toward the camera" in prompt
    assert "forced perspective" in prompt


# --------------------------------------------------------------------------- #
# the expressions themselves
# --------------------------------------------------------------------------- #
def test_the_arousal_expressions_describe_a_face_not_a_feeling():
    """A sheet cell can only hold what shows: flush, lid height, mouth shape, brows."""
    by_key = {option.key: option for option in ss.EXPRESSIONS}
    for key in ("aroused", "pleasure", "orgasm"):
        prompt = by_key[key].prompt.lower()
        assert any(word in prompt for word in ("lid", "eyes")), key
        assert any(word in prompt for word in ("mouth", "lips", "jaw")), key
        assert "flush" in prompt or "flushed" in prompt, key
    assert "peak" in by_key["orgasm"].prompt.lower()
    assert by_key["orgasm"].label.endswith("(peak)")


def test_the_in_between_expressions_are_offered():
    by_key = {option.key: option for option in ss.EXPRESSIONS}
    for key in ("closed-eyes", "lips-parted", "laugh", "pout", "wink", "disgust",
                "determined", "pain"):
        assert key in by_key, f"{key} is missing from the expression list"
    # Eyes closed is the one a video spends most frames in, and it must not read as a smile.
    assert "eyes closed" in by_key["closed-eyes"].prompt.lower()


def test_the_pose_list_stays_prop_free():
    """The backdrop has no furniture (see _NO_SET), so no pose may need a chair."""
    for option in ss.POSES:
        prompt = option.prompt.lower()
        assert "chair" not in prompt, f"{option.key}: the model would build the chair"
        assert "bed" not in prompt, f"{option.key}: there is no bed in the backdrop"


def test_the_new_poses_are_offered_and_distinct():
    keys = [option.key for option in ss.POSES]
    assert len(keys) == len(set(keys))
    for key in ("sitting", "kneeling", "crouching", "lying", "walking", "contrapposto",
                "hands-on-hips", "arms-crossed", "reach-camera", "hair-touch"):
        assert key in keys, f"{key} is missing from the pose list"


def test_unknown_yet_plausible_view_keys_are_still_refused():
    """The vocabulary grew, but it is still a closed list: a typo must not guess."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg", "role": "face"}]},
            "cells": [{"id": "c", "view": "three-quarters"}],
        }
    )
    assert spec.cells[0].view == "front"
    assert any("unknown view" in warning for warning in spec.warnings)


if __name__ == "__main__":  # pragma: no cover - manual run
    pytest.main([__file__, "-q"])
