# ComfyUI-H3-Character-Sheet - hand-painted blur areas.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Painting a blur area: the strokes, the mask, and how they meet the face blur.

Two layers are pinned here:

* the *mask* - normalized strokes rasterized the way the engine expects (brush with round
  caps at a radius measured against the image's short edge, lasso filled in), and
* the *rules* - a painted area blurs whatever the tile's mode says, because the mode
  chooses whether faces are detected while painting is the user pointing at pixels.
"""

from __future__ import annotations

import numpy as np
import pytest

from h3cs import face_blur as fb
from h3cs import sheet_spec as ss


def _stroke(**overrides):
    stroke = {"tool": "brush", "radius": 0.05, "points": [[0.2, 0.5], [0.8, 0.5]]}
    stroke.update(overrides)
    return stroke


# --------------------------------------------------------------------------- #
# the mask
# --------------------------------------------------------------------------- #
def test_an_empty_paint_is_an_empty_mask():
    mask = fb.paint_mask((64, 64), [])
    assert mask.shape == (64, 64)
    assert float(mask.max()) == 0.0


def test_a_brush_stroke_covers_the_line_it_was_drawn_on():
    mask = fb.paint_mask((100, 100), [_stroke(radius=0.05)])
    assert mask[50, 50] == pytest.approx(1.0), "the middle of the stroke is covered"
    assert mask[50, 5] == pytest.approx(0.0), "before the stroke starts is not"
    # radius is a fraction of the SHORT edge: 0.05 * 100 = 5px, i.e. 5 to each side.
    assert mask[50 - 4, 50] == pytest.approx(1.0)
    assert mask[50 - 9, 50] == pytest.approx(0.0), "and it does not spread further"


def test_the_radius_follows_the_short_edge_not_the_width():
    """A brush must be round: on a 200x100 image the radius scales with the 100."""
    mask = fb.paint_mask((100, 200), [_stroke(points=[[0.5, 0.5]], radius=0.05)])
    covered = mask > 0
    rows = np.where(covered.any(axis=1))[0]
    cols = np.where(covered.any(axis=0))[0]
    assert rows.max() - rows.min() == pytest.approx(cols.max() - cols.min(), abs=2)


def test_a_single_point_is_a_dot():
    mask = fb.paint_mask((60, 60), [_stroke(points=[[0.5, 0.5]], radius=0.1)])
    assert mask[30, 30] == pytest.approx(1.0)
    assert mask[30, 50] == pytest.approx(0.0)


def test_a_lasso_is_filled_in():
    lasso = {"tool": "lasso", "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}
    mask = fb.paint_mask((100, 100), [lasso])
    assert mask[50, 50] == pytest.approx(1.0), "the inside of the outline is covered"
    assert mask[10, 50] == pytest.approx(0.0), "outside is not"
    assert mask[95, 95] == pytest.approx(0.0)


def test_a_lasso_with_two_points_is_not_an_area():
    assert float(fb.paint_mask((50, 50), [{"tool": "lasso", "points": [[0.1, 0.1], [0.2, 0.2]]}]).max()) == 0.0


def test_the_mask_is_normalized_and_lands_where_the_points_say():
    mask = fb.paint_mask((80, 40), [_stroke(points=[[0.75, 0.25]], radius=0.02)])
    peak = np.unravel_index(int(np.argmax(mask)), mask.shape)
    assert peak[1] == pytest.approx(0.75 * 40, abs=2), "x is a fraction of the width"
    assert peak[0] == pytest.approx(0.25 * 80, abs=2), "y is a fraction of the height"


def test_feathering_softens_the_edge_without_shrinking_the_area():
    mask = fb.paint_mask((100, 100), [_stroke(radius=0.06)])
    soft = fb.feather_mask(mask, sigma=3)
    assert float(soft.max()) == pytest.approx(1.0, abs=0.15), "the middle stays covered"
    assert soft[50, 55] > 0.05, "and the edge gains a ramp"
    assert float(fb.feather_mask(mask, sigma=0).max()) == pytest.approx(1.0), "sigma 0 is a no-op"


def test_the_engine_and_the_spec_agree_on_the_default_brush():
    assert fb.PAINT_DEFAULT_RADIUS == ss.DEFAULT_BRUSH_RADIUS


# --------------------------------------------------------------------------- #
# blurring what was painted
# --------------------------------------------------------------------------- #
def test_only_the_painted_area_is_blurred():
    rng = np.random.default_rng(3)
    image = rng.integers(0, 256, size=(200, 200, 3), dtype=np.uint8)
    before = image.copy()
    out = fb.blur_painted(image, [_stroke(points=[[0.25, 0.5], [0.25, 0.5]], radius=0.08)])

    def roughness(patch):
        return float(np.abs(np.diff(patch.astype(np.float32), axis=1)).mean())

    assert roughness(out[85:115, 35:65]) < roughness(before[85:115, 35:65]) * 0.6
    assert np.array_equal(out[0:40, 0:40], before[0:40, 0:40]), "nothing else is touched"
    assert image.tolist() == before.tolist(), "the caller's image is untouched"


def test_painting_nothing_changes_nothing():
    image = np.full((60, 60, 3), 120, dtype=np.uint8)
    assert np.array_equal(fb.blur_painted(image, []), image)


# --------------------------------------------------------------------------- #
# the rules
# --------------------------------------------------------------------------- #
def _spec(roles, paint=(), **refs):
    pictures = []
    for index, role in enumerate(roles):
        item = {"imageFile": f"p{index}.jpg", "role": role}
        if index < len(paint) and paint[index]:
            item["blurPaint"] = paint[index]
        item.update(refs.get(f"p{index}", {}))
        pictures.append(item)
    return ss.parse_sheet_spec(
        {"refs": {"pictures": pictures}, "cells": [{"id": "c", "view": "portrait"}]}
    )


def test_a_painted_area_blurs_even_when_the_mode_says_off():
    """\"Instead of the face blur\": set the tile to off and paint."""
    spec = _spec(["face and hair", "body and clothes"], paint=[None, [_stroke()]])
    assert spec.pictures[1].blur_face == "auto"
    spec.pictures[1].blur_face = "off"
    assert ss.blur_face_decisions(spec)[("picture", 1)] == "blur"
    assert ss.blur_detects_faces(spec)[("picture", 1)] is False, "painting alone needs no detector"


def test_painting_the_identity_photo_blurs_it_too():
    """The identity reference is left alone by 'auto', but pointing at it is explicit."""
    spec = _spec(["face and hair", "body and clothes"], paint=[[_stroke()], None])
    decisions = ss.blur_face_decisions(spec)
    detects = ss.blur_detects_faces(spec)
    assert decisions[("picture", 0)] == "blur", "the user painted on it"
    assert detects[("picture", 0)] is False, "…and asked for no detection there"


def test_painting_adds_to_the_detected_faces():
    spec = _spec(["face and hair", "body and clothes"], paint=[None, [_stroke()]])
    assert ss.blur_face_decisions(spec)[("picture", 1)] == "blur"
    assert ss.blur_detects_faces(spec)[("picture", 1)] is True, "auto still detects here"


def test_a_painted_video_is_reported_rather_than_half_done():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [{"imageFile": "a.jpg", "role": "face and hair"}],
                "videos": [{"videoFile": "b.mp4", "role": "clothing", "blurPaint": [_stroke()]}],
            },
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    assert ss.blur_face_decisions(spec)[("video", 0)] == "unsupported"


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def test_strokes_survive_the_payload_round_trip():
    spec = _spec(["face and hair"], paint=[[_stroke()]])
    assert len(spec.pictures[0].blur_paint) == 1
    again = ss.parse_sheet_spec(spec.to_dict())
    assert again.pictures[0].blur_paint == spec.pictures[0].blur_paint


def test_junk_strokes_are_dropped_or_clamped_with_a_warning():
    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {
                        "imageFile": "a.jpg",
                        "role": "face",
                        "blurPaint": [
                            "not a stroke",
                            {"tool": "crayon", "points": [[0.5, 0.5]]},
                            {"tool": "brush", "points": []},
                            {"tool": "lasso", "points": [[0.1, 0.1], [0.2, 0.2]]},
                            {"tool": "brush", "radius": 99, "points": [["-1", "2"], [0.5, 0.5]]},
                        ],
                    }
                ]
            },
            "cells": [{"id": "c"}],
        }
    )
    strokes = spec.pictures[0].blur_paint
    assert len(strokes) == 2, "the string, the empty brush and the 2-point lasso are gone"
    assert strokes[0]["tool"] == "brush", "an unknown tool falls back, with a warning"
    assert any("unknown paint tool" in warning for warning in spec.warnings)
    assert strokes[1]["radius"] == ss.MAX_BRUSH_RADIUS, "a silly radius is clamped"
    assert strokes[1]["points"] == [[0.0, 1.0], [0.5, 0.5]], "points are clamped to the image"


def test_the_number_of_strokes_is_capped():
    many = [{"tool": "brush", "points": [[0.5, 0.5]]} for _ in range(ss.MAX_PAINT_STROKES + 5)]
    spec = ss.parse_sheet_spec(
        {"refs": {"pictures": [{"imageFile": "a.jpg", "role": "face", "blurPaint": many}]},
         "cells": [{"id": "c"}]}
    )
    assert len(spec.pictures[0].blur_paint) == ss.MAX_PAINT_STROKES
    assert any("painted strokes" in warning for warning in spec.warnings)


# --------------------------------------------------------------------------- #
# end to end through the file pass and the plan
# --------------------------------------------------------------------------- #
class _NoModel:
    """A complete stand-in for "this install has no face detector"."""


def test_a_painted_file_is_written_without_any_face_model(tmp_path, monkeypatch):
    import cv2

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    rng = np.random.default_rng(5)
    image = rng.integers(0, 256, size=(200, 200, 3), dtype=np.uint8)
    target = root / "h3_character_sheet" / "ref.jpg"
    cv2.imwrite(str(target), image)
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: None)

    strokes = [_stroke(points=[[0.3, 0.3]], radius=0.08)]
    report = fb.blur_image_faces("h3_character_sheet/ref.jpg", paint=strokes, detect=False)
    assert report["ok"] is True, report
    assert report["painted"] == 1 and report["boxes"] == []
    assert "painted area" in report["reason"]
    # Compare against the DECODED source: a .jpg is already lossy, so the question is what
    # this module changed, not how the encoder rounded.
    decoded = cv2.imread(str(target)).astype(float)
    written = cv2.imread(str(root / report["file"])).astype(float)
    assert np.abs(written - decoded).max() > 10, "the painted dot was blurred"
    assert (written[150:, 150:] == decoded[150:, 150:]).all(), "and the rest is untouched"

    again = fb.blur_image_faces("h3_character_sheet/ref.jpg", paint=strokes, detect=False)
    assert again["cached"] is True and again["file"] == report["file"]


def test_painting_and_detection_are_both_reported(tmp_path, monkeypatch):
    import cv2

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    image = np.full((240, 240, 3), 60, dtype=np.uint8)
    cv2.imwrite(str(root / "h3_character_sheet" / "ref.jpg"), image)
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: root / "h3_character_sheet" / "ref.jpg")

    class _Box:
        xyxy = [[100, 90, 140, 140]]
        conf = [0.9]

    class _Result:
        boxes = [_Box()]

    class _Model:
        def predict(self, image, **_kwargs):
            return [_Result()]

    report = fb.blur_image_faces(
        "h3_character_sheet/ref.jpg",
        paint=[_stroke(points=[[0.2, 0.2]], radius=0.05)],
        detect=True,
        detector=_Model(),
    )
    assert report["ok"] is True
    assert "1 face(s)" in report["reason"] and "1 painted area(s)" in report["reason"]


def test_the_cache_key_follows_the_painting(tmp_path):
    source = tmp_path / "a.jpg"
    source.write_bytes(b"pixels")
    plain = fb.cache_key(source)
    assert fb.cache_key(source, paint=[_stroke()]) != plain, "repainting is a new copy"
    assert fb.cache_key(source, paint=[_stroke()]) == fb.cache_key(source, paint=[_stroke()])


def test_the_plan_rewrites_a_paint_only_reference(tmp_path, monkeypatch):
    import cv2

    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    cv2.imwrite(str(root / "h3_character_sheet" / "ref.jpg"), np.full((160, 160, 3), 90, np.uint8))
    monkeypatch.setattr(fb, "input_root", lambda: root)
    monkeypatch.setattr(fb, "model_path", lambda: None)

    spec = ss.parse_sheet_spec(
        {
            "refs": {
                "pictures": [
                    {
                        "imageFile": "h3_character_sheet/ref.jpg",
                        "role": "face and hair",
                        "blurFace": "off",
                        "blurPaint": [_stroke(points=[[0.5, 0.5]], radius=0.08)],
                    }
                ]
            },
            "cells": [{"id": "c", "view": "portrait"}],
        }
    )
    plan = {"pictures": [{"source_slot_id": "ref_image_0", "file": "h3_character_sheet/ref.jpg"},
                         ], "videos": [], "audios": []}
    lines = fb.blur_reference_plan(spec, plan)

    assert "-blurface-" in plan["pictures"][0]["file"], "off + painted still gets a copy"
    assert any("painted area" in line for line in lines)
