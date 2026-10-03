# ComfyUI-H3-Character-Sheet - face blur for references.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Automatic face blur: the decision, the image maths and the plan rewrite.

The detector is injected everywhere (a fake that returns fixed boxes), so these tests
never load a model: what is pinned here is the policy (who gets blurred) and the pixel
handling (what a blur does to a patch), not YOLO's opinion of a test image.
"""

from __future__ import annotations

import numpy as np
import pytest

from h3cs import face_blur as fb
from h3cs import sheet_spec as ss


# --------------------------------------------------------------------------- #
# who gets blurred
# --------------------------------------------------------------------------- #
def _spec(roles, **refs):
    pictures = [
        {"imageFile": f"p{index}.jpg", "role": role, **refs.get(f"p{index}", {})}
        for index, role in enumerate(roles)
    ]
    return ss.parse_sheet_spec(
        {"refs": {"pictures": pictures}, "cells": [{"id": "c", "view": "portrait"}]}
    )


def test_auto_blurs_the_reference_that_is_not_the_identity():
    """The reported bug in one assertion: picture 2 is a face source, picture 1 is not."""
    spec = _spec(["head, face, hair", "body and clothes"])
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("picture", 0)] == "keep", "the identity photo is never blurred"
    assert decisions[("picture", 1)] == "blur"


def test_auto_keeps_a_reference_whose_role_says_nothing():
    """Blurring the only face in the run is not recoverable, so an empty role is left alone."""
    spec = _spec(["face and hair", ""])
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("picture", 1)] == "keep"


def test_auto_keeps_everything_when_no_reference_claims_the_likeness():
    spec = _spec(["body and clothes", "clothing"])
    assert set(ss.blur_face_decisions(spec).values()) == {"keep"}


def test_an_explicit_on_and_off_beat_the_automatic_rule():
    spec = _spec(
        ["face and hair", "body and clothes", "clothing"],
        p0={"blurFace": "on"},
        p2={"blurFace": "off"},
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("picture", 0)] == "blur", "on wins even for the identity photo"
    assert decisions[("picture", 1)] == "blur"
    assert decisions[("picture", 2)] == "keep"


def test_a_video_is_never_blurred_but_an_explicit_on_is_reported():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "videos": [
                    {"videoFile": "b.mp4", "role": "clothing and body"},
                    {"videoFile": "c.mp4", "role": "clothing", "blurFace": "on"},
                ],
            },
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("video", 0)] == "keep", "auto says nothing about a video"
    assert decisions[("video", 1)] == "unsupported"


def test_the_mode_survives_the_payload_round_trip():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {"imageFile": "a.jpg", "role": "face and hair", "blurFace": "off"},
                    {"imageFile": "b.jpg", "role": "clothing"},
                ]
            },
            "cells": [{"id": "c"}],
        }
    )
    assert [ref.blur_face for ref in spec.pictures] == ["off", "auto"]
    again = ss.parse_sheet_spec(spec.to_dict())
    assert [ref.blur_face for ref in again.pictures] == ["off", "auto"]


# --------------------------------------------------------------------------- #
# how much of the head is covered
# --------------------------------------------------------------------------- #
def test_the_blur_area_survives_the_payload_round_trip():
    spec = ss.parse_sheet_spec({"render": {"blurScope": "head"}, "cells": [{"id": "c"}]})
    assert spec.render.blur_scope == "head"
    assert spec.to_dict()["render"]["blurScope"] == "head"
    assert ss.parse_sheet_spec(spec.to_dict()).render.blur_scope == "head"
    assert ss.parse_sheet_spec({"cells": []}).render.blur_scope == ss.DEFAULT_BLUR_SCOPE


def test_an_unknown_blur_area_warns_and_falls_back():
    spec = ss.parse_sheet_spec({"render": {"blurScope": "eyebrows"}, "cells": [{"id": "c"}]})
    assert spec.render.blur_scope == ss.DEFAULT_BLUR_SCOPE
    assert any("unknown blur area" in warning for warning in spec.warnings)


def test_the_two_vocabularies_agree():
    """The panel offers these names and the engine implements them - nothing else."""
    assert set(ss.BLUR_SCOPES) == set(fb.SCOPE_SETTINGS)
    assert ss.DEFAULT_BLUR_SCOPE == fb.DEFAULT_SCOPE


def test_each_area_grows_the_patch_further():
    face = fb.settings_for_scope("face")
    hair = fb.settings_for_scope("hair")
    head = fb.settings_for_scope("head")
    assert face["pad_x"] < hair["pad_x"] < head["pad_x"]
    assert face["pad_y"] < hair["pad_y"] < head["pad_y"]
    assert face["pad_up"] <= hair["pad_up"] <= head["pad_up"]
    # An unknown or missing area is the default, never an exception during a render.
    assert fb.settings_for_scope("banana") == hair
    assert fb.settings_for_scope(None) == hair


def test_blur_boxes_never_receives_the_detection_setting():
    """`conf` is detection, not pixels: passing it through would be a TypeError."""
    kwargs = fb._box_kwargs(None, "head")
    assert "conf" not in kwargs
    assert set(kwargs) == {"pad_x", "pad_y", "pad_up", "sigma", "feather"}
    image = np.zeros((60, 60, 3), dtype=np.uint8)
    assert fb.blur_boxes(image, [(20, 20, 40, 40)], **kwargs).shape == image.shape


def test_the_head_area_covers_what_is_worn_above_the_face():
    """A bow, hat or headband sits outside the face box: the head area has to reach it."""
    image = np.zeros((400, 400, 3), dtype=np.uint8)
    image[60:100, 150:250] = 255  # a bow above the head
    image[120:200, 160:240] = 200  # the face
    head = fb.blur_boxes(image, [(160, 120, 240, 200)], **fb._box_kwargs(None, "head"))
    face = fb.blur_boxes(image, [(160, 120, 240, 200)], **fb._box_kwargs(None, "face"))

    # The face-only patch starts just above the box, so the bow keeps its hard edge …
    assert face[60:85, 150:250].max() == 255, "the face area does not reach the bow"
    # … while the head patch is over it and has smoothed it out.
    assert head[60:85, 150:250].max() < 255, "the head area covers what is worn above the face"
    assert np.array_equal(head[380:, :], image[380:, :]), "and stops well above the garment"


def test_a_patch_running_off_the_frame_is_not_feathered_at_the_border():
    """Hair that reaches the top of the photo must be blurred all the way to the edge."""
    rng = np.random.default_rng(11)
    image = rng.integers(0, 256, size=(300, 300, 3), dtype=np.uint8)
    before = image.copy()
    # A face near the top: the grown patch has nowhere to go but off the frame.
    blurred = fb.blur_boxes(image, [(120, 20, 180, 90)], **fb._box_kwargs(None, "head"))

    def roughness(patch):
        return float(np.abs(np.diff(patch.astype(np.float32), axis=1)).mean())

    assert roughness(blurred[0:12, 90:210]) < roughness(before[0:12, 90:210]) * 0.9
    assert blurred[0:12, 90:210].std() < before[0:12, 90:210].std()
    assert np.array_equal(blurred[280:, :], before[280:, :]), "far away is untouched"


def test_an_unknown_blur_value_warns_and_falls_back():
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "a.jpg", "blurFace": "maybe"}]},
            "cells": [{"id": "c"}],
        }
    )
    assert spec.pictures[0].blur_face == "auto"
    assert any("unknown face blur" in warning for warning in spec.warnings)


def test_a_checkbox_value_still_means_something():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {"imageFile": "a.jpg", "blurFace": True},
                    {"imageFile": "b.jpg", "blurFace": False},
                ]
            },
            "cells": [{"id": "c"}],
        }
    )
    assert [ref.blur_face for ref in spec.pictures] == ["on", "off"]


# --------------------------------------------------------------------------- #
# the image maths (no model, no disk)
# --------------------------------------------------------------------------- #
def test_blur_boxes_blurs_inside_the_patch_and_leaves_the_rest_alone():
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(240, 240, 3), dtype=np.uint8)
    before = image.copy()
    blurred = fb.blur_boxes(image, [(100, 90, 140, 140)])

    def roughness(patch):
        return float(np.abs(np.diff(patch.astype(np.float32), axis=1)).mean())

    face = blurred[95:150, 90:150]
    far = blurred[0:40, 0:40]
    assert roughness(face) < roughness(before[95:150, 90:150]) * 0.6, "the patch is smoothed"
    assert np.array_equal(far, before[0:40, 0:40]), "nothing outside the patch is touched"
    assert image.tolist() == before.tolist(), "the caller's image is not modified in place"


def test_the_blur_patch_covers_the_hair_above_the_face_box():
    """The detector box stops at the forehead; the patch has to reach past it."""
    image = np.zeros((300, 300, 3), dtype=np.uint8)
    image[120:180, 130:170] = 255  # a bright "face" block
    blurred = fb.blur_boxes(image, [(130, 120, 170, 180)])
    assert blurred[:60, :].max() == 0, "the top of the image is untouched"
    assert blurred[80:120, 130:170].max() > 0, "the patch reaches above the box, into the hair"


def test_a_patch_is_soft_edged_not_a_pasted_rectangle():
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    image[60:140, 60:140] = 255
    blurred = fb.blur_boxes(image, [(70, 70, 130, 130)])
    row = blurred[100, :, 0].astype(np.float32)
    inside = row[85:115].mean()
    edge = row[45:60].mean()
    outside = row[0:20].mean()
    assert outside == 0
    assert edge < inside, "the edge fades in rather than switching on"


def test_the_ellipse_mask_is_one_in_the_middle_and_zero_at_the_rim():
    mask = fb._ellipse_mask(41, 41)
    assert mask[20, 20] == pytest.approx(1.0, abs=0.02)
    assert mask[0, 0] == pytest.approx(0.0, abs=0.02)
    assert mask[20, 40] < mask[20, 20]


def test_a_degenerate_box_is_skipped_without_crashing():
    image = np.full((40, 40, 3), 90, dtype=np.uint8)
    assert np.array_equal(fb.blur_boxes(image, [(20, 20, 20, 20)]), image)


def test_cache_key_changes_with_the_file_and_the_settings(tmp_path):
    source = tmp_path / "a.jpg"
    source.write_bytes(b"first")
    key = fb.cache_key(source)
    assert fb.cache_key(source) == key, "a stable key is what makes the cache a cache"
    source.write_bytes(b"second and longer")
    assert fb.cache_key(source) != key, "a replaced file must not serve the old blur"
    assert fb.cache_key(source, settings={"pad_x": 2.0}) != fb.cache_key(source)


# --------------------------------------------------------------------------- #
# the file pass (fake detector, real image)
# --------------------------------------------------------------------------- #
class _FakeBox:
    def __init__(self, box):
        self.xyxy = [box]
        self.conf = [0.9]


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = [_FakeBox(box) for box in boxes]


class _FakeModel:
    """A detector that always finds one face at a fixed place."""

    def __init__(self, boxes=((100, 90, 140, 140),)):
        self.boxes = list(boxes)
        self.calls = 0

    def predict(self, image, **_kwargs):  # noqa: ANN003 - mirrors ultralytics
        self.calls += 1
        return [_FakeResult(self.boxes)]


def _input_tree(tmp_path, monkeypatch, image=None):
    """A fake ComfyUI install: an input folder with one reference picture."""
    import cv2

    root = tmp_path / "input"
    refs = root / "h3_character_sheet"
    refs.mkdir(parents=True)
    target = refs / "ref.jpg"
    if image is None:
        image = np.full((240, 240, 3), 40, dtype=np.uint8)
    cv2.imwrite(str(target), image)
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: target)  # any existing file
    return root, target


def test_the_derived_file_is_written_next_to_the_references(tmp_path, monkeypatch):
    import cv2

    image = np.zeros((240, 240, 3), dtype=np.uint8)
    image[90:150, 90:150] = 220
    root, target = _input_tree(tmp_path, monkeypatch, image)
    # Compare bytes, not pixels: writing a .jpg already costs a little fidelity, so the
    # question is whether this module rewrote the reference - it must not.
    original = target.read_bytes()
    report = fb.blur_image_faces("h3_character_sheet/ref.jpg", detector=_FakeModel())

    assert report["ok"] is True, report
    assert report["file"].startswith("h3_character_sheet/derived/")
    assert report["scope"] == fb.DEFAULT_SCOPE
    written = root / report["file"]
    assert written.is_file()
    assert written.stat().st_size > 0
    assert np.abs(cv2.imread(str(written)).astype(float) - image.astype(float)).max() > 10
    assert target.read_bytes() == original, "the original is untouched"


def test_each_area_is_cached_separately(tmp_path, monkeypatch):
    """Switching area has to re-render the copy, not serve the previous area's blur."""
    _input_tree(tmp_path, monkeypatch)
    detector = _FakeModel()
    hair = fb.blur_image_faces("h3_character_sheet/ref.jpg", scope="hair", detector=detector)
    head = fb.blur_image_faces("h3_character_sheet/ref.jpg", scope="head", detector=detector)
    again = fb.blur_image_faces("h3_character_sheet/ref.jpg", scope="hair", detector=detector)
    assert hair["ok"] and head["ok"]
    assert hair["file"] != head["file"], "a different area is a different copy"
    assert hair["file"] == again["file"] and again["cached"] is True
    assert detector.calls == 2, "one detection per area, not per call"


def test_a_second_pass_is_served_from_the_cache(tmp_path, monkeypatch):
    _input_tree(tmp_path, monkeypatch)
    detector = _FakeModel()
    first = fb.blur_image_faces("h3_character_sheet/ref.jpg", detector=detector)
    second = fb.blur_image_faces("h3_character_sheet/ref.jpg", detector=detector)
    assert first["cached"] is False and second["cached"] is True
    assert first["file"] == second["file"]
    assert detector.calls == 1, "detection is the expensive part; it runs once per file"


def test_no_face_means_no_derived_file_and_a_reason(tmp_path, monkeypatch):
    _input_tree(tmp_path, monkeypatch)
    report = fb.blur_image_faces("h3_character_sheet/ref.jpg", detector=_FakeModel(boxes=()))
    assert report["ok"] is False
    assert "no face detected" in report["reason"]
    assert report["file"] == ""


def test_a_missing_model_is_a_reason_not_a_crash(tmp_path, monkeypatch):
    _input_tree(tmp_path, monkeypatch)
    monkeypatch.setattr(fb, "model_path", lambda: None)
    report = fb.blur_image_faces("h3_character_sheet/ref.jpg")
    assert report["ok"] is False
    assert "no face model" in report["reason"]


def test_a_path_outside_the_input_folder_is_refused(tmp_path, monkeypatch):
    root, _ = _input_tree(tmp_path, monkeypatch)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"nope")
    assert fb.resolve_input_file(str(outside)) is None
    report = fb.blur_image_faces("../outside.jpg", detector=_FakeModel())
    assert report["ok"] is False and "input folder" in report["reason"]
    assert fb.resolve_input_file("h3_character_sheet/ref.jpg") is not None


# --------------------------------------------------------------------------- #
# the plan rewrite (what the render actually wires)
# --------------------------------------------------------------------------- #
def test_the_plan_is_rewritten_to_the_derived_file(tmp_path, monkeypatch):
    _input_tree(tmp_path, monkeypatch)
    spec = _spec(["head, face, hair", "body and clothes"])
    plan = {
        "pictures": [
            {"slot": "ref_images.ref_image_0", "slot_id": "ref_image_0",
             "source_slot_id": "ref_image_0", "file": "h3_character_sheet/ref.jpg"},
            {"slot": "ref_images.ref_image_1", "slot_id": "ref_image_1",
             "source_slot_id": "ref_image_1", "file": "h3_character_sheet/ref.jpg"},
        ],
        "videos": [],
        "audios": [],
    }
    lines = fb.blur_reference_plan(spec, plan, detector=_FakeModel())

    assert plan["pictures"][0]["file"] == "h3_character_sheet/ref.jpg", "picture 1 is the identity"
    assert "derived" in plan["pictures"][1]["file"]
    assert any("face blur:" in line for line in lines)
    assert any(f"({spec.render.blur_scope})" in line for line in lines), "the report names the area"


def test_a_changed_area_reaches_the_plan_rewrite(tmp_path, monkeypatch):
    """The sheet's blur area is what the render uses, not a module default."""
    _input_tree(tmp_path, monkeypatch)
    spec = ss.parse_sheet_spec(
        {
            "render": {"blurScope": "head"},
            "refs": {"pictures": [
                {"imageFile": "a.jpg", "role": "head, face, hair"},
                {"imageFile": "b.jpg", "role": "body and clothes"},
            ]},
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    plan = {"pictures": [
        {"source_slot_id": "ref_image_0", "file": "h3_character_sheet/ref.jpg"},
        {"source_slot_id": "ref_image_1", "file": "h3_character_sheet/ref.jpg"},
    ], "videos": [], "audios": []}
    fb.blur_reference_plan(spec, plan, detector=_FakeModel())
    assert "-blurface-" in plan["pictures"][1]["file"]
    assert fb.settings_for_scope("head")["pad_y"] > fb.settings_for_scope("hair")["pad_y"]


def test_nothing_is_touched_when_nothing_is_flagged(tmp_path, monkeypatch):
    _input_tree(tmp_path, monkeypatch)
    spec = _spec(["face and hair"])
    plan = {"pictures": [{"source_slot_id": "ref_image_0", "file": "h3_character_sheet/ref.jpg"}],
            "videos": [], "audios": []}
    assert fb.blur_reference_plan(spec, plan, detector=_FakeModel()) == []
    assert plan["pictures"][0]["file"] == "h3_character_sheet/ref.jpg"
