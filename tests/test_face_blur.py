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


def test_a_clip_is_blurred_like_a_picture():
    """A reference clip carries a face in its pixels exactly as a photo does."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "videos": [
                    {"videoFile": "b.mp4", "role": "clothing and body"},
                    {"videoFile": "c.mp4", "role": "clothing", "blurFace": "on"},
                    {"videoFile": "d.mp4", "role": "motion"},
                ],
            },
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("video", 0)] == "blur", "auto blurs the outfit clip of a second person"
    assert decisions[("video", 1)] == "blur", "and an explicit on needs no rule"
    assert decisions[("video", 2)] == "keep", "a role that says nothing is left alone"


def test_the_clip_that_is_the_identity_source_is_never_auto_blurred():
    """An H3 run whose motion comes from a clip usually takes its likeness from that clip."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "videos": [
                    {"videoFile": "hero.mp4", "role": "face and hair"},
                    {"videoFile": "outfit.mp4", "role": "clothing and body"},
                ],
            },
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("video", 0)] == "keep", "the likeness lives in this clip - leave it alone"
    assert decisions[("video", 1)] == "blur", "the second person's clip still goes"


def test_a_sound_reference_is_muted_rather_than_blurred():
    """A voice has no pixels, so the removal is the whole sound - and the decision says so."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "audios": [{"audioFile": "v.wav", "role": "voice", "blurFace": "on"}],
            },
            "cells": [{"id": "c"}],
        }
    )
    assert ss.blur_face_decisions(spec)[("audio", 0)] == "mute"


def test_auto_keeps_a_voice_and_only_an_explicit_on_mutes_it():
    """A sound reference is added on purpose - unlike a face in a photo, it is not a leak.

    So "auto" keeps every voice (the reference that carries the likeness included) and the
    tile's "on" is how a voice is muted. Muting a second voice automatically would break the
    run the reference was added for.
    """
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "audios": [
                    {"audioFile": "hero.wav", "role": "voice and likeness"},
                    {"audioFile": "other.wav", "role": "voice"},
                    {"audioFile": "third.wav", "role": "voice", "blurFace": "on"},
                ],
            },
            "cells": [{"id": "c"}],
        }
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("audio", 0)] == "keep", "the identity reference keeps its voice"
    assert decisions[("audio", 1)] == "keep", "and so does an ordinary second voice, by auto"
    assert decisions[("audio", 2)] == "mute", "an explicit on mutes it"
    # An explicit "off" says the same thing the default already did, which is what keeps the
    # badge a real three-state cycle rather than two states and a no-op.
    off = ss.blur_face_decisions(ss.parse_sheet_spec(
        {"refs": {"audios": [{"audioFile": "v.wav", "role": "voice", "blurFace": "off"}]},
         "cells": [{"id": "c"}]}
    ))
    assert off[("audio", 0)] == "keep"


def test_painting_a_sound_is_still_reported_rather_than_half_done():
    """There are no pixels in a voice: a painting on one has to be said out loud."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "audios": [{"audioFile": "v.wav", "role": "voice",
                            "blurPaint": [{"tool": "brush", "points": [[0.5, 0.5]], "radius": 0.05}]}],
            },
            "cells": [{"id": "c"}],
        }
    )
    assert ss.blur_face_decisions(spec)[("audio", 0)] == "unsupported"


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


# --------------------------------------------------------------------------- #
# the clip pass (fake detector, real video)
# --------------------------------------------------------------------------- #
class _BrightModel:
    """A detector that finds a bright block wherever it actually is.

    ``_FakeModel`` answers with a fixed box, which is fine for a still and useless for a
    clip: the whole point of the clip pass is that the face MOVES, so this one reads the
    picture it is handed and reports the brightest region. That makes the tracking test a
    real test - the box it returns for a frame is derived from that frame.
    """

    def __init__(self, threshold=180, largest=False):
        self.threshold = threshold
        self.largest = largest
        self.calls = 0

    def predict(self, image, **_kwargs):  # noqa: ANN003 - mirrors ultralytics
        self.calls += 1
        grey = np.asarray(image)
        grey = grey[..., 0] if grey.ndim == 3 else grey
        ys, xs = np.where(grey >= self.threshold)
        if len(xs) == 0:
            return [_FakeResult([])]
        # A round "face": the middle of the bright mass, a fixed size, so the box is a
        # function of the frame and barely of its shape.
        cx, cy = float(xs.mean()), float(ys.mean())
        half_w = max(6.0, (xs.max() - xs.min() + 1) / 2.0)
        half_h = max(6.0, (ys.max() - ys.min() + 1) / 2.0)
        if self.largest:
            half_w = min(half_w, 40.0)
            half_h = min(half_h, 40.0)
        box = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]
        return [_FakeResult([box])]


def _clip_tree(tmp_path, monkeypatch, frames=40, size=(192, 192), with_audio=False):
    """A fake install with one reference CLIP: a bright block walking across the frame.

    The block is face-sized (56px in a 192px frame) on purpose: the blur patch is grown
    from the box, so a tiny block would get a tiny sigma and the pass would barely change
    its pixels - which would make the assertions below measure the geometry of the test
    rather than the blur.
    """
    import cv2

    root = tmp_path / "input"
    refs = root / "h3_character_sheet"
    refs.mkdir(parents=True)
    target = refs / "ref.mp4"
    writer = cv2.VideoWriter(
        str(target), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (size[0], size[1])
    )
    box = []
    for index in range(frames):
        frame = np.full((size[1], size[0], 3), 30, dtype=np.uint8)
        left = 16 + int(index * 2)
        top = 70
        frame[top:top + 56, left:left + 56] = 210  # the "face", moving right
        # ...with detail on it: stripes a few pixels apart stand in for eyes and features.
        # A blur cannot remove a flat patch's brightness, but it must remove this.
        frame[top + 8:top + 48:8, left + 6:left + 50] = 45
        frame[top + 20:top + 26, left + 12:left + 44] = 30
        box.append((left, top, left + 56, top + 56))
        writer.write(frame)
    writer.release()
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: target)
    return root, target, box


def _read_clip(path):
    import cv2

    capture = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        frames.append(frame)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    capture.release()
    return frames, fps


def _reencode(frames, path, fps=12.0):
    """The control: the same frames through the same writer, with no blur.

    A clip is written with a lossy codec, so "these pixels changed" is not evidence of
    anything on its own. Re-encoding the source without the blur pass isolates it: what is
    left is what the blur did.
    """
    import cv2

    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (width, height)
    )
    for frame in frames:
        writer.write(frame)
    writer.release()
    return _read_clip(path)[0]


def test_a_clip_is_blurred_frame_by_frame_and_keeps_its_length(tmp_path, monkeypatch):
    root, target, box = _clip_tree(tmp_path, monkeypatch, frames=40)
    source_frames, _ = _read_clip(target)
    control = _reencode(source_frames, tmp_path / "control.mp4")
    report = fb.blur_video_faces("h3_character_sheet/ref.mp4", detector=_BrightModel())

    assert report["ok"] is True, report
    assert report["file"].endswith(".mp4"), "a clip has to stay a clip"
    assert report["frames"] == 40
    written = root / report["file"]
    frames, fps = _read_clip(written)
    assert len(frames) == 40, "every frame is written back"
    assert abs(fps - 12.0) < 0.5, "at the clip's own rate"
    assert frames[0].shape == (192, 192, 3), "and its own size"
    # The face really is blurred. A bright flat patch would survive any blur, so the
    # measurement is the DETAIL inside it: the control (same codec, no pass) keeps it, the
    # blurred clip does not.
    face = (slice(72, 124), slice(62, 126))
    detail_control = float(control[20][face].std())
    detail_blurred = float(frames[20][face].std())
    assert detail_control > 40.0, f"the fixture really carries detail ({detail_control:.1f})"
    assert detail_blurred < detail_control * 0.6, (
        f"the features are gone ({detail_blurred:.1f} vs {detail_control:.1f})"
    )
    # …and the blur stayed local: the background is not smeared by it.
    assert float(frames[20][0:40, 0:40].std()) == pytest.approx(
        float(control[20][0:40, 0:40].std()), abs=6.0
    )
    assert target.is_file(), "and the original clip is untouched"


def test_the_clip_tracker_follows_the_face_instead_of_a_fixed_box(tmp_path, monkeypatch):
    """The point of sampling + tracking: the blur walks with the face."""
    import cv2

    root, target, _ = _clip_tree(tmp_path, monkeypatch, frames=32)
    source_frames, _ = _read_clip(target)
    control = _reencode(source_frames, tmp_path / "control.mp4")
    report = fb.blur_video_faces("h3_character_sheet/ref.mp4", detector=_BrightModel())
    assert report["ok"] is True, report
    first, last = report["boxes"][0], report["boxes"][-1]
    assert last[0] > first[0] + 20, f"the tracked box moved right with the block: {first} -> {last}"

    frames, _ = _read_clip(root / report["file"])
    # On a late frame the block sits around x=72..128. A pass that blurred one fixed patch
    # (the one frame 0 needed) would leave that place crisp - so this is the assertion that
    # the blur followed the move rather than being applied once and repeated.
    late = 28
    moved_region = (slice(74, 122), slice(76, 124))
    detail_control = float(control[late][moved_region].std())
    assert detail_control > 40.0, "the block is really there in the control"
    assert float(frames[late][moved_region].std()) < detail_control * 0.6, (
        "the late frame is blurred where the block now is, not where it started"
    )
    # …and it did not smear the whole frame to get there: the background keeps its value.
    assert float(frames[late][0:40, 0:40].mean()) == pytest.approx(
        float(control[late][0:40, 0:40].mean()), abs=6.0
    )
    # The tracker is measured on the frames between the samples, so the derived clip is
    # still a normal clip the loader will open.
    assert cv2.VideoCapture(str(root / report["file"])).isOpened()


def test_a_second_clip_pass_is_served_from_the_cache(tmp_path, monkeypatch):
    root, _, _ = _clip_tree(tmp_path, monkeypatch, frames=20)
    detector = _BrightModel()
    first = fb.blur_video_faces("h3_character_sheet/ref.mp4", detector=detector)
    calls = detector.calls
    second = fb.blur_video_faces("h3_character_sheet/ref.mp4", detector=detector)
    assert second["ok"] is True and second["cached"] is True
    assert second["file"] == first["file"]
    assert detector.calls == calls, "a cached clip costs no detection at all"


def test_a_clip_with_no_face_is_left_alone_with_a_reason(tmp_path, monkeypatch):
    root, _, _ = _clip_tree(tmp_path, monkeypatch, frames=12)

    class _Blind:
        def predict(self, image, **_kwargs):  # noqa: ANN003
            return [_FakeResult([])]

    report = fb.blur_video_faces("h3_character_sheet/ref.mp4", detector=_Blind())
    assert report["ok"] is False
    assert "no face detected in the clip" in report["reason"]
    assert not any((root / "h3_character_sheet" / "derived").glob("*.mp4"))


def test_a_clip_can_be_painted_without_a_detector(tmp_path, monkeypatch):
    """Paint-only needs no model, and the painting is held across the whole clip."""
    root, target, _ = _clip_tree(tmp_path, monkeypatch, frames=16)
    source_frames, _ = _read_clip(target)
    control = _reencode(source_frames, tmp_path / "control.mp4")
    strokes = [{
        "tool": "brush",
        "radius": 0.08,
        "points": [[0.2, 0.5], [0.8, 0.5]],
    }]
    report = fb.blur_video_faces(
        "h3_character_sheet/ref.mp4", detect=False, paint=strokes, detector=None
    )
    assert report["ok"] is True, report
    assert report["painted"] == 1 and report["boxes"] == []
    frames, _ = _read_clip(root / report["file"])
    # The stroke runs across the middle, where the face's features are: its detail drops on
    # the FIRST and the LAST frame alike, which is what "the painting is held" means (an
    # unheld painting would only soften the frame it was drawn on).
    band = (slice(84, 108), slice(30, 150))
    for index in (0, len(frames) - 1):
        sharp = float(control[index][band].std())
        soft = float(frames[index][band].std())
        assert sharp > 40.0, f"frame {index}: the fixture really carries detail ({sharp:.1f})"
        assert soft < sharp * 0.8, (
            f"frame {index}: the painted band is softer ({soft:.1f} vs {sharp:.1f})"
        )


def test_the_clip_policy_is_part_of_the_cache_key(tmp_path, monkeypatch):
    root, target, _ = _clip_tree(tmp_path, monkeypatch, frames=10)
    base = fb.cache_key(target)
    assert fb.cache_key(target, extra={"kind": "video", "samples": 12}) != base
    assert fb.cache_key(target, extra={"kind": "video", "samples": 24}) != fb.cache_key(
        target, extra={"kind": "video", "samples": 12}
    )


def test_the_sampling_leaves_no_gap_it_cannot_bridge():
    assert fb._sample_positions(1) == [0]
    assert fb._sample_positions(2) == [0, 1]
    positions = fb._sample_positions(40)
    assert positions[0] == 0 and positions[-1] == 39
    assert positions == sorted(set(positions)), "each frame is sampled once"
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    assert max(gaps) <= fb.VIDEO_MAX_GAP, f"gaps stay bridgeable: {gaps}"
    # A long clip gets more samples rather than bigger gaps.
    long = fb._sample_positions(900)
    assert len(long) > fb.VIDEO_SAMPLES
    assert max(b - a for a, b in zip(long, long[1:])) <= fb.VIDEO_MAX_GAP


def test_a_video_reference_in_the_plan_is_rewritten_to_the_blurred_clip(tmp_path, monkeypatch):
    root, target, _ = _clip_tree(tmp_path, monkeypatch, frames=16)
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "videos": [{"videoFile": "h3_character_sheet/ref.mp4", "role": "clothing",
                            "blurFace": "on"}],
            },
            "cells": [{"id": "c"}],
        }
    )
    plan = {"videos": [{"file": "h3_character_sheet/ref.mp4", "source_slot_id": "video_0"}]}
    lines = fb.blur_reference_plan(spec, plan, detector=_BrightModel())
    assert plan["videos"][0]["file"].endswith(".mp4")
    assert plan["videos"][0]["file"] != "h3_character_sheet/ref.mp4"
    assert (root / plan["videos"][0]["file"]).is_file(), "the plan points at a real file"
    assert any("ref.mp4" in line for line in lines), lines


# --------------------------------------------------------------------------- #
# the sound pass (mute: a voice has no pixels)
# --------------------------------------------------------------------------- #
def _sound_tree(tmp_path, monkeypatch, seconds=0.5, rate=8000):
    """A fake install with one reference sound: a real tone, not silence."""
    import math
    import wave

    root = tmp_path / "input"
    refs = root / "h3_character_sheet"
    refs.mkdir(parents=True)
    target = refs / "voice.wav"
    frames = int(seconds * rate)
    samples = bytearray()
    for index in range(frames):
        value = int(12000 * math.sin(2 * math.pi * 220 * index / rate))
        samples += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(target), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(bytes(samples))
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: target)
    return root, target


def test_a_sound_reference_is_muted_at_its_own_length(tmp_path, monkeypatch):
    import wave

    root, target = _sound_tree(tmp_path, monkeypatch)
    report = fb.mute_audio("h3_character_sheet/voice.wav")

    assert report["ok"] is True, report
    assert report["muted"] is True
    written = root / report["file"]
    assert written.is_file() and written.suffix == ".wav"
    with wave.open(str(target), "rb") as original, wave.open(str(written), "rb") as muted:
        assert muted.getframerate() == original.getframerate(), "same rate"
        assert muted.getnframes() == original.getnframes(), "same length - the reference stays usable"
        assert muted.getnchannels() == original.getnchannels(), "same channels"
        frames = muted.readframes(1024)
    assert frames.count(b"\x00") == len(frames), "and it is silence"
    assert report["file"] != "h3_character_sheet/voice.wav", "the original is not the thing wired"
    assert "mute" in report["reason"] or "silence" in report["reason"], report["reason"]


def test_a_second_mute_is_served_from_the_cache(tmp_path, monkeypatch):
    root, _ = _sound_tree(tmp_path, monkeypatch)
    first = fb.mute_audio("h3_character_sheet/voice.wav")
    second = fb.mute_audio("h3_character_sheet/voice.wav")
    assert second["cached"] is True and second["file"] == first["file"]


def test_muting_accepts_the_arguments_the_other_passes_take(tmp_path, monkeypatch):
    """The caller treats every kind the same way, so the mute pass must not choke on them."""
    _sound_tree(tmp_path, monkeypatch)
    report = fb.mute_audio(
        "h3_character_sheet/voice.wav",
        scope="hair",
        paint=[{"tool": "brush", "points": [[0.5, 0.5]], "radius": 0.05}],
        detect=True,
        detector=object(),
        conf=0.25,
    )
    assert report["ok"] is True, report


def test_a_file_outside_the_input_folder_is_refused_for_a_sound_too(tmp_path, monkeypatch):
    _sound_tree(tmp_path, monkeypatch)
    report = fb.mute_audio("../voice.wav")
    assert report["ok"] is False
    assert "input folder" in report["reason"]

# --------------------------------------------------------------------------- #
# a panel's own face reference (the panel's drag-and-drop)
# --------------------------------------------------------------------------- #
def test_a_panel_can_take_its_face_from_a_reference_the_rule_would_blur():
    """The panelled choice protects the picture it points at, the way the identity source is.

    "This panel's likeness comes from Picture 2" is a promise the prompt makes; a blurred copy
    of Picture 2 cannot keep it. Same protection the run-wide identity source gets, for the same
    reason - just for one panel instead of the whole sheet.
    """
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [
                {"imageFile": "identity.jpg", "role": "face, hair"},
                {"imageFile": "outfit.jpg", "role": "body and clothes"},
            ]},
            "cells": [
                {"id": "c0", "view": "portrait"},
                {"id": "c1", "view": "portrait", "faceRef": "pictures:1"},
            ],
        }
    )
    decisions = ss.blur_face_decisions(spec)
    assert decisions[("picture", 0)] == "keep", "the identity photo is still protected"
    assert decisions[("picture", 1)] == "keep", "and so is the picture a panel points at"
    assert ss.cell_face_slots(spec) == {("picture", 1)}


def test_the_panel_that_names_a_face_reference_leads_with_it():
    """The cell's prompt hands it to H3 as <Picture 1> and gives it the face attribute."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [
                {"imageFile": "identity.jpg", "role": "face, hair"},
                {"imageFile": "outfit.jpg", "role": "body and clothes"},
            ]},
            "cells": [
                {"id": "c0", "view": "portrait"},
                {"id": "c1", "view": "portrait", "faceRef": "pictures:1"},
            ],
        }
    )
    by_id = {cell.id: cell for cell in spec.cells}
    plain = ss.cell_references(spec, by_id["c0"])
    assert [ref.file for ref in plain] == ["identity.jpg", "outfit.jpg"], "the default order"
    own = ss.cell_references(spec, by_id["c1"])
    assert [ref.file for ref in own] == ["outfit.jpg", "identity.jpg"], (
        "the panel's own face reference leads, so it is the one <Picture 1> names"
    )
    assert "face" in own[0].role, "and it claims the face the prompt will point at"
    assert ss.identity_reference(own) is own[0], "so the identity lines name that picture"


def test_a_panel_face_reference_that_no_longer_exists_falls_back():
    """A cell outlives a deleted tile: the name is a lookup, never a crash."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [{"imageFile": "identity.jpg", "role": "face"}]},
            "cells": [{"id": "c0", "view": "portrait", "faceRef": "pictures:7"}],
        }
    )
    cell = spec.cells[0]
    assert ss.cell_face_reference(cell, spec.refs) is None, "no such slot"
    assert [ref.file for ref in ss.cell_references(spec, cell)] == ["identity.jpg"]
    assert ss.cell_face_slots(spec) == set(), "and nothing is protected on its behalf"


def test_an_explicit_on_still_blurs_the_pictures_a_panel_points_at():
    """The tile's own "always" is the more explicit instruction about those pixels."""
    spec = ss.parse_sheet_spec(
        {
            "refs": {"pictures": [
                {"imageFile": "identity.jpg", "role": "face, hair"},
                {"imageFile": "outfit.jpg", "role": "body and clothes", "blurFace": "on"},
            ]},
            "cells": [{"id": "c0", "view": "portrait", "faceRef": "pictures:1"}],
        }
    )
    assert ss.blur_face_decisions(spec)[("picture", 1)] == "blur"
