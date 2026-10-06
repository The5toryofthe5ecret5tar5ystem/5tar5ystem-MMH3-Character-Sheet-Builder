# MiniMax H3 Motion Director - character sheet specification (views/poses/expressions).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Character Sheet Builder: the sheet specification and its prompt assembly.

A *sheet* is a small matrix of single-character images ("cells") that a user can
feed back into an r2v/ref2va workflow as a reference set. Every cell is rendered
by MiniMax H3 as a very short clip (H3 has no still-image mode: the shortest
output is a 17k+5 chunk, 5 frames minimum), and the node then keeps all frames,
picks one frame per cell and composites the sheet.

This module is deliberately pure Python: it parses the payload the embedded node
panel writes, validates/clamps it, and turns each cell into a prompt. No ComfyUI,
no torch, no disk - so the whole vocabulary and prompt contract is unit-testable.

Payload shape (``sheet_data`` STRING widget, written by the node's DOM widget)::

    {
      "version": 1,
      "name": "steph_sheet",
      "globalPrompt": "young woman, ...",
      "negativePrompt": "",
      "refs": {
        "pictures": [{"imageFile": "a.png", "role": "face and hair"}],
        "videos":   [{"videoFile": "b.mp4", "role": "clothing and body"}],
        "audios":   [{"audioFile": "c.wav", "role": "voice"}]
      },
      "sheet":  {"layout": "hero-left", "columns": 2, "shortEdge": 1536,
                 "aspect": "3:2", "gap": 16, "padding": 24, "captions": true,
                 "background": "#101014", "fit": "contain"},
      "render": {"framesPerCell": 22, "steps": 25, "seed": 42},
      "cells":  [{"id": "c1", "view": "face", "pose": "neutral",
                  "expression": "smile", "extraPrompt": "", "frames": 22,
                  "pick": "auto", "place": {"row": 0, "col": 0}}]
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- #
# limits (H3 reference limits + a sane cell cap for one run)
# --------------------------------------------------------------------------- #
MAX_PICTURES = 9
MAX_VIDEOS = 3
MAX_AUDIOS = 3
MAX_CELLS = 24
MIN_CELL_FRAMES = 5
MAX_CELL_FRAMES = 425
DEFAULT_CELL_FRAMES = 22

#: Sentence used for a reference whose role box was left empty (see
#: :func:`reference_legend`). Never claims content the user did not describe.
_KIND_FALLBACK_ROLE = {
    "picture": "character reference image",
    "video": "character reference video",
    "audio": "voice reference",
}

#: MiniMax H3 only samples 17k+5 frame chunks (5, 22, 39, ...). A cell that asks
#: for anything else would be trimmed or padded by the frame aligner, so the
#: requested length is rounded UP to the next valid value instead.
H3_FRAME_STRIDE = 17
H3_FRAME_BASE = 5


def align_h3_frames(value: Any, *, fallback: int = DEFAULT_CELL_FRAMES) -> int:
    """Round ``value`` up to the next 17k+5 length H3 can sample."""
    try:
        frames = int(value)
    except (TypeError, ValueError):
        frames = int(fallback)
    frames = max(MIN_CELL_FRAMES, min(MAX_CELL_FRAMES, frames))
    if frames <= H3_FRAME_BASE:
        return H3_FRAME_BASE
    steps = -(-(frames - H3_FRAME_BASE) // H3_FRAME_STRIDE)  # ceil division
    return min(MAX_CELL_FRAMES, H3_FRAME_BASE + steps * H3_FRAME_STRIDE)


# --------------------------------------------------------------------------- #
# vocabulary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SheetOption:
    """One selectable view / pose / expression.

    ``aside`` is the same expression with its eye contact removed, used by the framings
    that cannot show any (:data:`PROFILE_FRAMINGS`). "Warm smile, eyes engaged." is right
    for a face close-up and wrong in a side view, where the composition already says
    "no eye contact with the viewer" - an instruction to look into the lens there is a
    contradiction the model resolves by turning the whole body back to the camera.
    """

    key: str
    label: str
    prompt: str
    aside: str = ""


#: What each view asks the camera for, in SHOT-SIZE words. The framing line is the
#: first thing the model reads after the reference, so it is where "the head was cut
#: off" or "the feet were cut off" is won or lost: a full-body cell that only says
#: "whole figure inside the frame" gets a medium shot half the time. Each distance
#: also says what NOT to do (no close-up, nothing cropped), because H3 is a video
#: model and will happily push in on its own.
_FULL_BODY_SHOT = (
    "Full-length wide shot, camera far back: the entire figure from the top of the "
    "head to the soles of the feet is inside the frame, with a little empty space "
    "above the head and below the feet - nothing cropped, no push-in, this is not a "
    "medium shot and not a close-up."
)

#: Framings a character sheet normally needs. ``prompt`` lines are written the way
#: H3 reference material is described: subject first, then camera/framing, because
#: the model is a video model reading a shot description.
VIEWS: tuple[SheetOption, ...] = (
    SheetOption(
        "face",
        "Face close up (straight on)",
        "Tight close-up of the face, straight on, head level and centred, shoulders "
        "just in frame, eyes to camera, even frontal light - head and shoulders "
        "only, not a full body.",
    ),
    SheetOption(
        "portrait",
        "Portrait (chest and face)",
        "Medium close-up, framed at the chest: the top of the head and the chest are "
        "both inside the frame, straight on, head level, eyes to camera, shoulders "
        "square to the lens - the camera sits back far enough to show the chest, so "
        "this is not a face-only close-up.",
    ),
    SheetOption(
        "front",
        "Full body (facing forward)",
        "Full body straight on, standing, weight even, arms clear of the body. "
        + _FULL_BODY_SHOT + " Both feet are on the ground and visible.",
    ),
    SheetOption(
        "profile",
        "Full body (90 degrees, side)",
        "Full body at exactly 90 degrees, viewed from the side, standing profile. "
        + _FULL_BODY_SHOT + " Head and body face the same direction, so only the "
        "side of the face is visible: looking straight ahead, gaze away from the "
        "camera, no eye contact with the viewer.",
    ),
    SheetOption(
        "back",
        "Full body (from behind)",
        "Full body seen from directly behind, back and the back of the head visible, "
        "standing. " + _FULL_BODY_SHOT + " Face turned away from the camera: no eye "
        "contact, the subject is not looking at the viewer.",
    ),
    # --- the angles a turnaround is missing without ------------------------------
    # Front / profile / back is a 90-degree walk; the 45s are what teach a model that the
    # head is a solid. A three-quarter view is where an identity either holds up or
    # collapses, so it earns a cell in any sheet used to lock a face down.
    SheetOption(
        "three-quarter",
        "Three-quarter (45 degrees)",
        "Full body turned 45 degrees away from the camera, three-quarter view: the near "
        "shoulder is closer to the lens, the far shoulder sits behind it, and both eyes "
        "are still visible. " + _FULL_BODY_SHOT + " Both feet are on the ground and "
        "visible.",
    ),
    SheetOption(
        "three-quarter-back",
        "Three-quarter back (135 degrees)",
        "Full body seen from 135 degrees behind and to one side: the back and the far "
        "shoulder fill the frame, and the head is turned away so only the cheek, jaw and "
        "ear are visible - no eye contact. " + _FULL_BODY_SHOT + " Both feet are on the "
        "ground and visible.",
    ),
    # --- head detail: the parts a whole-body cell renders too small to teach --------
    SheetOption(
        "face-profile",
        "Head profile (90 degrees)",
        "Tight close-up of the head in profile at exactly 90 degrees: forehead, nose, "
        "lips, chin, jaw line, ear and the hairline are all inside the frame, gaze level "
        "and away from the camera - head and neck only, not a full body.",
    ),
    SheetOption(
        "head-back",
        "Back of the head and hair",
        "Close-up of the back of the head from directly behind: the whole hairline, the "
        "nape, both ears in silhouette and the length and ends of the hair are inside the "
        "frame. No face and no eyes are visible - the subject is turned away.",
    ),
    # --- camera angles: the same person, read from above and below -----------------
    # Worth their own cells because they are what stops a LoRA learning "shot from
    # chest height, always": the model needs to see the head from above and the legs
    # from below to keep a person three-dimensional under its own camera choices.
    SheetOption(
        "high-angle",
        "Full body (from above, high angle)",
        "Full body from a high angle: the camera looks down at about 30 degrees, so the "
        "head is nearest the lens and the feet are furthest away. " + _FULL_BODY_SHOT
        + " Both feet are on the ground and visible.",
    ),
    SheetOption(
        "low-angle",
        "Full body (from below, low angle)",
        "Full body from a low angle: the camera sits low and looks up at about 30 "
        "degrees, so the legs and hips are nearest the lens and the head is furthest "
        "away - an upward view of the whole figure, not a close-up. " + _FULL_BODY_SHOT
        + " Both feet are on the ground and visible.",
    ),
    SheetOption(
        "over-shoulder",
        "Over the shoulder (looking back)",
        "Seen from behind and slightly to one side, over the near shoulder: that "
        "shoulder fills the near edge of the frame while the head is turned back over it "
        "to look straight into the lens, eye contact with the viewer. " + _FULL_BODY_SHOT,
    ),
    # --- detail crops: the things a sheet is used for and a full body hides --------
    SheetOption(
        "hands",
        "Hands (close up)",
        "Close-up of both hands raised beside the chest, palms toward the camera with "
        "the fingers spread: knuckles, nails, thumbs and the backs of the hands are all "
        "inside the frame. Only the hands and wrists are in shot - no face.",
    ),
    SheetOption(
        "eyes",
        "Eyes (close up)",
        "Extreme close-up of the eyes only: both eyes, lashes, brows and the bridge of "
        "the nose inside the frame, iris colour and shape clear, looking straight into "
        "the lens. No mouth, no chin and no body in shot.",
    ),
    SheetOption(
        "legs",
        "Legs and footwear",
        "Framed from the waist down: hips, both legs, legwear if any, and the footwear "
        "all inside the frame, standing straight with the feet together and pointing "
        "toward the camera. No head and no face in shot.",
    ),
    SheetOption(
        "mouth",
        "Mouth (close up)",
        "Close-up of the mouth and chin only: lips, teeth if they show, and the chin "
        "inside the frame, head level and facing the camera. The eyes are out of shot, so "
        "no eye contact with the viewer is visible - this is the framing an expression is "
        "read from.",
    ),
    SheetOption(
        "feet",
        "Feet (close up)",
        "Close-up of both feet from the ankle down: the footwear if any, the toes and "
        "the ankles inside the frame, feet together on the ground and pointing toward "
        "the camera. No legs above the ankle, no face.",
    ),
    # --- the documented-but-explicit crops: the same idea for what an adult sheet also
    # records. Framing only, in the same voice as every other view here - a sheet is a
    # reference, so the prompt says where the camera is, not what to feel.
    SheetOption(
        "breasts",
        "Breasts (close up)",
        "Framed on the chest: both breasts inside the frame, straight on and fully "
        "visible, nipples in shot, the collarbone above the frame. No face in shot.",
    ),
    SheetOption(
        "groin",
        "Groin (close up)",
        "Framed on the groin and the top of the thighs: the genital area inside the "
        "frame, straight on with the legs slightly apart, the waist above the frame. "
        "No face in shot.",
    ),
    SheetOption(
        "butt",
        "Butt (close up, from behind)",
        "Framed on the buttocks seen from directly behind at hip height: both cheeks "
        "inside the frame, the lower back above the frame and the thighs below it. No "
        "face in shot.",
    ),
)

#: How far the camera is from the subject for each view, in three steps. Latent
#: continuation hands the previous cell's tail to the next one, so a run of cells
#: keeps its scale - and a *framing change* across that hand-over is fought by the
#: model rather than helped: a chest-up cell continuing a face close-up stays a face
#: close-up, and a full-body cell continuing a chest-up cell lands mid-zoom ("the
#: feet are cut off"). Continuation therefore only chains cells that share a
#: distance (front -> three-quarter -> profile -> back: same scale, different angle,
#: which is exactly where it shines), unless the user forces it with
#: ``continuity="on"``. A crop is deliberately NOT the distance of the framing it was
#: cut from: a legs cell continuing a full body would hold the crop.
FRAMING_DISTANCES: dict[str, str] = {
    "face": "close",
    "face-profile": "close",
    "head-back": "close",
    "eyes": "close",
    "hands": "close",
    "legs": "close",
    # The detail crops added for the closeup boards: all close, and none of them is the
    # distance of the framing they were cut from (see the note above).
    "mouth": "close",
    "feet": "close",
    "breasts": "close",
    "groin": "close",
    "butt": "close",
    "portrait": "medium",
    "front": "full",
    "three-quarter": "full",
    "three-quarter-back": "full",
    "profile": "full",
    "back": "full",
    "high-angle": "full",
    "low-angle": "full",
    "over-shoulder": "full",
}

#: Framings that show the whole figure: a pose option belongs in the prompt.
POSE_FRAMINGS: tuple[str, ...] = (
    "front", "three-quarter", "profile", "three-quarter-back", "back",
    "high-angle", "low-angle", "over-shoulder",
)

#: Framings where the face is the subject: the expression is always stated. The mouth crop
#: counts: the expression IS the subject there, which is what a mouth board is for.
FACE_FRAMINGS: tuple[str, ...] = ("face", "portrait", "face-profile", "eyes", "mouth")

#: Framings seen from the side, where an expression only reads in profile.
PROFILE_FRAMINGS: tuple[str, ...] = ("profile", "face-profile")

#: Framings nobody can see a face in - an expression there would be a lie. The body crops
#: belong here for the same reason the hands and legs do: there is no mouth in a chest or
#: groin close-up, so an expression option must not add a line about one. The mouth crop is
#: deliberately NOT here - it is the framing an expression is READ from.
NO_FACE_FRAMINGS: tuple[str, ...] = (
    "back", "three-quarter-back", "head-back", "hands", "legs",
    "feet", "breasts", "groin", "butt",
)

#: The framings whose own frame text says the subject is NOT looking at the viewer (a
#: side view, a back view). Read from :data:`VIEWS` so the two can never drift apart: an
#: expression that asks for eye contact in one of these is a contradiction, and the model
#: resolves a contradiction by turning the body back to the camera.
NO_EYE_CONTACT_VIEWS: tuple[str, ...] = tuple(
    option.key for option in VIEWS if "no eye contact" in option.prompt.lower()
)


def expression_reads_in_view(option: SheetOption, view: Any) -> str:
    """The expression text as ``view`` can read it.

    "Warm smile, eyes engaged." belongs on a face close-up and contradicts a profile, whose
    own text already says "gaze away from the camera, no eye contact with the viewer".
    Where there is no eye contact to hold, the option's :attr:`SheetOption.aside` is used
    instead (measured: with the gaze clause in place, a profile cell came back facing the
    camera).
    """
    if str(view or "").strip().lower() in NO_EYE_CONTACT_VIEWS:
        return option.aside or option.prompt
    return option.prompt

#: Which axis "Build cells" expands a view along: ``pose`` for whole-body framings (one
#: cell per ticked pose), ``expression`` where the face is the subject (one cell per
#: ticked expression), ``single`` for the detail crops - a crop of the hands does not
#: change with a standing pose or a smile, so it gets exactly one neutral cell instead
#: of multiplying the sheet by ticks that cannot show.
VIEW_VARIANTS: dict[str, str] = {
    "front": "pose",
    "three-quarter": "pose",
    "profile": "pose",
    "three-quarter-back": "pose",
    "back": "pose",
    "high-angle": "pose",
    "low-angle": "pose",
    "over-shoulder": "pose",
    "face": "expression",
    "portrait": "expression",
    "face-profile": "expression",
    "eyes": "expression",
    "head-back": "single",
    "hands": "single",
    "legs": "single",
    # The mouth crop carries an expression (that is what a mouth board is for); the feet and
    # the body crops look the same whatever the face is doing, so multiplying them by an
    # expression would only spend renders.
    "mouth": "expression",
    "feet": "single",
    "breasts": "single",
    "groin": "single",
    "butt": "single",
}


POSES: tuple[SheetOption, ...] = (
    SheetOption("neutral", "Neutral", "Neutral relaxed pose, arms at the sides."),
    SheetOption("a-pose", "A-pose", "A-pose, arms held out from the body at about 45 degrees."),
    SheetOption("t-pose", "T-pose", "T-pose, arms held straight out horizontally, legs together."),
    # Every pose below is written to need no furniture: the backdrop is flat and has no
    # props (see _NO_SET), so "sitting on a chair" would make the model invent a chair
    # and put it in the frame.
    SheetOption(
        "sitting",
        "Sitting (on the floor)",
        "Seated on the floor, legs folded to one side, one hand resting on a thigh, "
        "back straight and shoulders open.",
    ),
    SheetOption(
        "kneeling",
        "Kneeling",
        "Kneeling upright: both knees on the floor with the shins flat, thighs "
        "vertical, back straight, arms relaxed at the sides.",
    ),
    SheetOption(
        "crouching",
        "Crouching",
        "Crouching low on the balls of the feet, knees together, elbows resting on the "
        "knees, head level.",
    ),
    SheetOption(
        "lying",
        "Lying on the back",
        "Lying on her back flat on the floor, body in one straight line, arms at the "
        "sides and toes pointed, head turned to face the camera.",
    ),
    SheetOption(
        "walking",
        "Walking",
        "Mid-stride, walking toward the camera: one foot forward with the heel landing "
        "and one back off the ground, arms swinging naturally.",
    ),
    SheetOption(
        "contrapposto",
        "Contrapposto",
        "Weight on one leg with that hip pushed out and the other knee relaxed, "
        "shoulders tilted the other way, chin level - a relaxed fashion pose.",
    ),
    SheetOption(
        "hands-on-hips",
        "Hands on hips",
        "Standing with both hands on the hips, elbows out and back straight.",
    ),
    SheetOption(
        "arms-crossed",
        "Arms crossed",
        "Standing with the arms folded across the chest, shoulders square, chin level.",
    ),
    SheetOption(
        "reach-camera",
        "Reach to camera (POV)",
        "One arm reaching straight toward the camera with the hand open and closest to "
        "the lens in the near foreground, slightly out of focus, the rest of the body "
        "further back - forced perspective, as if offering a hand to the viewer.",
    ),
    SheetOption(
        "hair-touch",
        "Hand through hair",
        "One hand lifted, fingers through the hair, sweeping it back from the face and "
        "over the ear, elbow raised and shoulder lifted.",
    ),
)

EXPRESSIONS: tuple[SheetOption, ...] = (
    SheetOption("neutral", "Neutral", "Neutral expression, mouth closed, relaxed brow."),
    SheetOption("smile", "Smile", "Warm smile, eyes engaged.", aside="Warm smile."),
    SheetOption("smirk", "Smirk", "Small one-sided smirk."),
    SheetOption("frown", "Frown", "Frowning, brows drawn down."),
    SheetOption("anger", "Anger", "Angry expression, hard stare, jaw set."),
    SheetOption("fear", "Fear", "Fearful expression, wide eyes, tense mouth."),
    SheetOption("surprised", "Surprised", "Surprised expression, eyebrows raised, mouth open."),
    SheetOption("embarrassed", "Embarrassed", "Embarrassed expression, flushed cheeks, averted eyes."),
    SheetOption("crying", "Crying", "Crying, wet eyes, distressed expression."),
    # --- the in-betweens every blink and every breath needs ------------------------
    # A sheet with only big emotions teaches big emotions: closed eyes, a parted mouth
    # and a laugh are the states a video spends most of its frames in.
    SheetOption(
        "closed-eyes",
        "Eyes closed",
        "Eyes closed and relaxed with a soft closed-mouth smile, brows smooth, calm.",
    ),
    SheetOption(
        "lips-parted",
        "Lips parted",
        "Lips slightly parted, relaxed gaze, soft brows and a calm face - the natural "
        "breath between expressions, not a smile and not a frown.",
    ),
    SheetOption("laugh", "Laugh", "Laughing openly: mouth wide, eyes crinkled shut, head tipped back a little."),
    SheetOption("pout", "Pout", "Pouting: lips pushed out, brows slightly drawn, a playfully displeased look."),
    SheetOption("wink", "Wink", "One eye closed in a wink, the other open and engaged, small one-sided smile."),
    SheetOption("disgust", "Disgust", "Disgust: nose wrinkled, upper lip raised, brows drawn down and together."),
    SheetOption("determined", "Determined", "Determined: eyes narrowed and steady, brows level and drawn in, jaw set."),
    SheetOption("pain", "Pain", "Pain: eyes squeezed shut, brows drawn up and together, mouth open in a grimace."),
    # --- arousal: written as face states, which is what a sheet cell can hold ------
    # These are deliberately clinical: the pack's job is to give the model a repeatable
    # expression, and "aroused" in a prompt without a described face just produces a
    # blank stare. Flush, lid height and mouth shape are the levers that read.
    SheetOption(
        "aroused",
        "Aroused",
        "Aroused: heavy-lidded eyes looking into the lens, pupils wide, lips parted, "
        "cheeks flushed, breathing deep, brows slightly raised.",
    ),
    SheetOption(
        "pleasure",
        "Pleasure",
        "Deep pleasure: eyes half closed and rolled slightly back, head tipped back, "
        "mouth open, brows lifted, cheeks and chest flushed, blissful.",
    ),
    SheetOption(
        "orgasm",
        "Orgasm (peak)",
        "At the peak: eyes squeezed shut or rolled back, brows drawn up and together, "
        "mouth open wide in a gasp, jaw tense, whole face flushed and strained, neck "
        "cords visible.",
    ),
    SheetOption(
        "tongue-out",
        "Tongue out",
        "Mouth open with the tongue out and the lips relaxed, chin lifted slightly, "
        "eyes open and looking at the camera.",
    ),
    SheetOption(
        "ahego",
        "Ahego (eyes rolled up, tongue out)",
        "Mouth wide open with the tongue out and the lips slack, cheeks flushed, brows "
        "raised. The eyes roll up so the pupils are almost hidden when they are in frame.",
    ),
)

#: What the model is told to put behind the figure. A flat, uniform backdrop is
#: what makes a sheet look like a sheet: the framing stays put from cell to cell,
#: nothing in the background competes with the character, and a key colour can be
#: cut out later. ``custom`` uses the user's own words instead.
#:
#: H3 is a video model: told only "neutral tan", it builds a plausible *room* in
#: that colour - walls, a floor, a door. So every backdrop has to say what is NOT
#: there, and the subject has to be lit separately from it.
_NO_SET = (
    "filling the frame behind the subject with nothing else in shot - no room, no "
    "walls, no floor, no ceiling, no doors, no windows, no furniture, no props"
)

#: Every backdrop is FLAT: no gradient, no vignette, and nothing casting a shadow onto it.
#: A backdrop that is only "evenly lit" still comes back with a falloff, a hot spot behind the
#: head and a shadow under the subject - which is what makes a sheet look like N different
#: photos instead of one. Said out loud in every clause, custom text included.
_FLAT = (
    "flat and completely uniform, evenly lit with no gradient, no vignette, no lighting "
    "falloff, no hot spot, and no shadow of the subject cast onto it"
)

#: Neutral tan, as a colour the composite and the prompt agree on.
TAN_HEX = "#c8b39b"

BACKGROUNDS: tuple[SheetOption, ...] = (
    SheetOption(
        "neutral",
        "Neutral grey",
        f"a plain neutral background, {_FLAT}, {_NO_SET}",
    ),
    SheetOption(
        "tan",
        "Neutral tan",
        f"a flat seamless neutral tan backdrop ({TAN_HEX}), {_FLAT}, {_NO_SET}",
    ),
    SheetOption(
        "white",
        "Flat white",
        f"a flat seamless pure white background, {_FLAT}, {_NO_SET}",
    ),
    SheetOption(
        "grey",
        "Mid grey",
        f"a flat seamless mid-grey studio background, {_FLAT}, {_NO_SET}",
    ),
    SheetOption(
        "black",
        "Flat black",
        f"a flat seamless black background, {_FLAT}, the subject lit separately from it, "
        f"{_NO_SET}",
    ),
    SheetOption(
        "green",
        "Green screen",
        f"a flat uniform chroma-key green screen (#00B140), {_FLAT}, unwrinkled, "
        f"no green spill or green reflections anywhere on the subject, {_NO_SET}",
    ),
    SheetOption(
        "blue",
        "Blue screen",
        f"a flat uniform chroma-key blue screen (#0000FF), {_FLAT}, no blue spill "
        f"anywhere on the subject, {_NO_SET}",
    ),
    # The one backdrop that comes from a reference instead of the presets - see
    # ``background_reference`` and ``reference_background_clause``; its prompt text is built
    # per sheet because it has to name the reference.
    SheetOption("reference", "Reference image/video", ""),
    SheetOption("custom", "Custom...", ""),
)

VIEW_KEYS = tuple(option.key for option in VIEWS)
POSE_KEYS = tuple(option.key for option in POSES)
EXPRESSION_KEYS = tuple(option.key for option in EXPRESSIONS)
BACKGROUND_KEYS = tuple(option.key for option in BACKGROUNDS)

_BACKGROUND_BY_KEY = {option.key: option for option in BACKGROUNDS}
_VIEW_BY_KEY = {option.key: option for option in VIEWS}
_POSE_BY_KEY = {option.key: option for option in POSES}
_EXPRESSION_BY_KEY = {option.key: option for option in EXPRESSIONS}

LAYOUTS = ("hero-left", "grid", "turnaround", "custom")
#: How a cell's frame is chosen. ``auto``/``last``/``sharpest`` are RULES - they are recomputed
#: on every compose, which is how a changed rule reaches a sheet that is already on disk.
#: ``manual`` is the opposite: it is what a click on a thumbnail records, it carries the frame
#: the user chose, and no later rebuild may recompute it away.
PICKS = ("auto", "last", "sharpest", "manual")

#: Cell shapes offered by the node widget. People are vertical, so the default is 3:4:
#: at the default 1024 short edge that is 768x1024 - a standing figure fits head to toe
#: with room for the arms, where a square wastes the sides and a phone-shaped 9:16
#: crops them.
CELL_ASPECTS = ("3:4", "9:16", "2:3", "1:1", "4:3", "3:2", "16:9", "21:9")
DEFAULT_CELL_ASPECT = "3:4"

#: How much of the reference set each cell receives. H3 conditions on every reference
#: it is handed at once and has no per-reference weight, so a close-up that receives
#: the outfit photo can borrow that face; the default leaves out what the framing
#: cannot show instead of arguing with the model.
REF_SCOPES = ("per framing", "every cell")
DEFAULT_REF_SCOPE = "per framing"

#: Latent continuation between cells. H3 renders one short clip per cell, so by
#: default cell N starts from its own noise and its own seed: consistent character,
#: independent pose. With continuation on, the tail of the previous cell is anchored
#: into the next cell (core ``MiniMaxH3AddGuide``), so the clip continues from it
#: instead of restarting - the same trick the Motion Director uses to hold a room,
#: a light and a framing across segments.
#:
#: ``auto`` chains only where the camera distance already matches (see
#: :func:`continuation_keeps_scale`): a run of full-body views turns the subject without the
#: model fighting a zoom, and the framing changes in a sheet stay crisp - a chained turnaround
#: IS how the turn animates inside a 22-frame cell, with the picked frame from its settled tail.
#: An angle-changing chain re-poses the body, so the report warns when the cell's own
#: references carry no outfit/body for the model to do that from. ``on`` chains everything,
#: including across a framing change - which the model resolves by keeping the framing it was
#: handed, so use it for a genuinely continuous move.
CONTINUITY_MODES = ("off", "auto", "on")
DEFAULT_CONTINUITY = "off"

#: How many frames of the previous cell are handed over. ``MiniMaxH3AddGuide`` crops
#: a guide clip down to the H3 ``17k + 5`` grid (5, 22, 39...), so 5 is the smallest
#: - and cheapest - hand-over: the first 5 frames of the next clip re-render the
#: previous tail and everything after them is the new pose. Those 5 frames are the
#: only cost: sampling is unchanged and no frames are added to the sheet.
CONTINUITY_FRAMES = 5

#: Per-cell override of the sheet switch. ``inherit`` follows the render setting, so a
#: sheet can chain its expressions while leaving a turnaround - where a shared tail
#: would fight the framing change - independent.
CONTINUITY_CELL_MODES = ("inherit", "auto", "on", "off")
DEFAULT_CELL_CONTINUITY = "inherit"

#: Face blur for a reference (see :func:`blur_face_decisions`). ``auto`` blurs a
#: picture that is not the run's identity source - the outfit photo that is a whole
#: second person - while leaving the identity photo untouched.
BLUR_MODES = ("auto", "on", "off")
#: Sampling steps for a fresh node and for every preset.
#:
#: The community TURBO H3 checkpoints bake the turbo delta into the weights, and their own
#: recipe for the sampler/scheduler these presets set (``res_multistep`` / ``simple``) is
#: **6-8 steps** - so the old 25-step default was spending ~3x the time for nothing. 8 is the
#: top of that range, which gives the most motion of it. A non-turbo checkpoint (or a
#: guidance/cfg workflow) still wants 20-30; that is one field in the Settings tab.
DEFAULT_STEPS = 8

DEFAULT_BLUR_MODE = "auto"

#: What a reference can have removed from it. A picture is blurred in one pass; a reference
#: clip is blurred frame by frame (``face_blur.blur_video_faces`` - detection is sampled and
#: tracked, and the derived clip keeps its audio track); a sound reference cannot be
#: *blurred* at all, so it is MUTED instead (``face_blur.mute_audio`` - the same length and
#: channels with no voice in them), and painting one is reported as unsupported because a
#: voice has no pixels to paint on.
BLUR_KINDS = ("picture", "video", "audio")

#: Tools the panel can paint with, and the limits of what a payload may carry.
#: ``brush`` is a freehand stroke of a given radius; ``lasso`` is a closed outline filled
#: in, so a large area is one gesture. A stroke is stored as normalized points (0-1), so
#: the same painting applies whatever size the reference happens to be.
BLUR_TOOLS = ("brush", "lasso")
MAX_PAINT_STROKES = 64
MAX_PAINT_POINTS = 512
DEFAULT_BRUSH_RADIUS = 0.03
MIN_BRUSH_RADIUS = 0.004
MAX_BRUSH_RADIUS = 0.5

#: How much of the head a blur covers. The detector only reports the face box, so hair
#: and headwear are covered by growing the patch around it - geometry, not recognition.
#: ``hair`` is the default: it takes the likeness (face plus the hair that carries
#: colour and shape) while leaving the neck, shoulders and garment alone.
BLUR_SCOPES = ("face", "hair", "head")
DEFAULT_BLUR_SCOPE = "hair"

#: H3's joint video+audio latent is a fixed 24 fps: the model has no fps input, so the
#: frame count IS the duration (22 frames = 0.92 s). A cell clip is therefore stamped 24
#: and nothing else - exporting it at a "nicer" rate would only change playback speed
#: and drift against its own soundtrack.
CLIP_FPS = 24.0

# --------------------------------------------------------------------------- #
# the one-pass sheet (the pack's primary render - see ``one_pass.py``)
# --------------------------------------------------------------------------- #
#: A one-pass render asks H3 for ONE clip that contains the whole sheet, instead of one clip
#: per cell. 5 frames is H3's shortest grid and the cheapest thing it can sample, and a sheet
#: of five cells sampled that way is ~110 frames of sampling against 5. The frames nobody
#: keeps still cost almost nothing, so they are saved.
ONE_PASS_FRAMES = 5
#: Both edges of a one-pass canvas snap UP to this grid. H3 works on a 16px VAE grid and the
#: pack composites on 16 (``sheet_layout.CANVAS_ALIGN``); a one-pass render is a single image
#: rather than a composite, so it snaps to the coarser 32 - the grid the published H3 sheet
#: workflows use - which keeps the panel count from landing on fractional tokens.
ONE_PASS_ALIGN = 32
#: Guidance ceiling for a one-pass canvas nobody chose deliberately. A one-pass render's cost IS
#: its canvas - one clip, no second context to amortise it over - and 3.6 MP is about the biggest
#: canvas the published H3 single-pass sheet workflows use (2816x1280). A canvas ABOVE this that
#: came from the resolution control is honoured as-is (that is the user's choice); one that came
#: from a hand-typed size is scaled down to fit, aspect preserved.
ONE_PASS_MAX_PIXELS = 3_600_000
#: Frame of the clip the sheet is taken from. H3 samples its 5-frame minimum as one moment, so
#: the first frame is the one to keep - and the other four stay on disk, so a change of mind
#: about the frame is a re-read, never a re-render.
ONE_PASS_SHEET_FRAME = 0

#: How many sheets one suite may render. Each is its own H3 render (or its own set of them), so
#: this is a real cost ceiling, not a taste call: four is the RefMod suite and the most a bundle
#: needs before its views start crowding the reference tokens.
MAX_SUITE_BOARDS = 8

#: How many LoRAs one sheet may stack (the panel's LoRAs tab). Every entry is a weight load on the
#: model every cell samples through, and the whole point of a sheet is one consistent look: a stack
#: past this is a mistake rather than a style, so it is refused rather than rendered.
MAX_LORAS = 16
#: The strength window a payload may ask for. Past this a LoRA stops shaping the sheet and starts
#: wrecking it, and a render is an expensive place to find that out.
LORA_STRENGTH_RANGE = (-4.0, 4.0)
DEFAULT_LORA_STRENGTH = 1.0

#: The resolution control: ``(key, label, sheet short edge, cell short edge)``.
#:
#: One choice, two paired sizes. The sheet short edge is the canvas a one-pass render draws and
#: the composite is built on; the cell short edge is what a per-cell render uses (and is unused by
#: the one-pass path). Both edges land on the 32px grid the one-pass render snaps to, so 1080p is
#: 1088 and 4K is 2176: the names are the class of display, not an exact pixel count (a 3:2 sheet
#: at a 1440 short edge is 2160x1440 whatever you call it).
RESOLUTION_CHOICES: tuple[tuple[str, str, int, int], ...] = (
    ("1080p", "1080p", 1088, 1024),
    ("1440p", "1440p", 1440, 1024),
    ("4k", "4K", 2176, 2048),
)
RESOLUTION_KEYS = tuple(choice[0] for choice in RESOLUTION_CHOICES)
RESOLUTION_LABELS = {choice[0]: choice[1] for choice in RESOLUTION_CHOICES}

_ASPECTS = {
    "1:1": 1.0,
    "4:3": 4.0 / 3.0,
    "3:2": 3.0 / 2.0,
    "16:9": 16.0 / 9.0,
    "21:9": 21.0 / 9.0,
    "9:16": 9.0 / 16.0,
    "3:4": 3.0 / 4.0,
    "2:3": 2.0 / 3.0,
}
DEFAULT_ASPECT = "3:2"
DEFAULT_SHORT_EDGE = 1536


def aspect_ratio(value: Any, fallback: str = DEFAULT_ASPECT) -> float:
    """Width/height for an aspect label such as ``"3:2"``, ``"21:9"`` or ``"1536x1024"``.

    Anything of the form ``W:H`` (or ``WxH``) is honoured, so a ratio a user invents
    works without a code change - only nonsense falls back to the default.
    """
    text = str(value or "").strip().lower()
    if text in _ASPECTS:
        return _ASPECTS[text]
    match = re.match(r"^\s*(\d+)\s*[x*:]\s*(\d+)\s*$", text)
    if match:
        w, h = int(match.group(1)), int(match.group(2))
        if w > 0 and h > 0:
            return w / h
    return _ASPECTS.get(fallback, 1.5)


# --------------------------------------------------------------------------- #
# spec dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class SheetRef:
    """One reference slot (picture / video / audio) and the role it plays."""

    kind: str  # "picture" | "video" | "audio"
    file: str
    role: str = ""
    enabled: bool = True
    index: int = 0
    #: Position in the run's FULL reference set. A cell may receive a subset of the
    #: references (see :func:`cell_references`), so ``index`` is re-numbered per cell
    #: while ``source`` still points at the image actually wired for it.
    source: int = -1
    #: Face blur for this reference: ``"auto"`` (see :func:`blur_face_decisions`),
    #: ``"on"`` or ``"off"``. The panel writes it; the node blurs the file before it
    #: is wired, so the model never sees the face of a non-identity reference.
    blur_face: str = DEFAULT_BLUR_MODE
    #: Areas painted by hand, as normalized strokes (see :func:`parse_blur_paint`). A
    #: painted area is blurred *in addition to* anything the mode blurs - with the mode
    #: at ``"off"`` the painting is the only thing that gets blurred.
    blur_paint: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tag(self) -> str:
        """Official H3 prompt tag for this reference (``<Picture 1>``, ...)."""
        label = {"picture": "Picture", "video": "Video", "audio": "Audio"}[self.kind]
        return f"<{label} {self.index + 1}>"


@dataclass
class SheetLora:
    """One LoRA in the sheet's stack: which file, how hard, and whether it is switched on.

    The stack lives on the SHEET rather than in the graph (see ``lora_library.py``): the panel's
    LoRAs tab authors it, the node applies it to the model every cell samples through, and one
    list therefore covers every cell - and every board of a suite.
    """

    file: str
    strength: float = DEFAULT_LORA_STRENGTH
    on: bool = True

    def label(self) -> str:
        """The file's own name without its extension (the panel prefers a stored name)."""
        stem = self.file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        for suffix in (".safetensors", ".ckpt", ".pt", ".sft"):
            if stem.lower().endswith(suffix):
                return stem[: -len(suffix)]
        return stem

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "strength": round(float(self.strength), 3), "on": bool(self.on)}


@dataclass
class SheetCell:
    """One image on the sheet."""

    id: str
    view: str = "front"
    pose: str = "neutral"
    expression: str = "neutral"
    extra_prompt: str = ""
    caption: str = ""
    frames: int = DEFAULT_CELL_FRAMES
    seed: int = 0
    pick: str = "auto"
    pick_index: int | None = None
    aspect: str = ""
    enabled: bool = True
    #: Which reference supplies THIS cell's likeness, as ``"<group>:<slot>"`` (``"pictures:1"``
    #: = the second picture). Empty means "whoever claims the face", which is the run-wide
    #: answer. It is the per-panel half of the sheet: the ticks build the default cross
    #: product, and a panel can then take its face from another picture.
    face_ref: str = ""
    place: dict[str, int] = field(default_factory=dict)
    #: Latent continuation for this cell: ``inherit`` (the render setting), ``on`` or
    #: ``off``. The first cell of a sheet never continues - there is nothing before it.
    continuity: str = DEFAULT_CELL_CONTINUITY

    @property
    def view_option(self) -> SheetOption:
        return _VIEW_BY_KEY.get(self.view, _VIEW_BY_KEY["front"])

    @property
    def pose_option(self) -> SheetOption:
        return _POSE_BY_KEY.get(self.pose, _POSE_BY_KEY["neutral"])

    @property
    def expression_option(self) -> SheetOption:
        return _EXPRESSION_BY_KEY.get(self.expression, _EXPRESSION_BY_KEY["neutral"])

    @property
    def label(self) -> str:
        """Default on-sheet caption when the cell has no explicit one."""
        if self.caption.strip():
            return self.caption.strip()
        parts = [self.view_option.label]
        if self.view in ("front", "profile", "back"):
            parts.append(self.pose_option.label)
        if self.view in ("face", "portrait"):
            parts.append(self.expression_option.label)
        return " · ".join(parts)


@dataclass
class SheetLayoutSpec:
    layout: str = "hero-left"
    columns: int = 2
    short_edge: int = DEFAULT_SHORT_EDGE
    aspect: str = DEFAULT_ASPECT
    cell_aspect: str = ""
    gap: int = 16
    padding: int = 24
    captions: bool = True
    background: str = "#101014"
    fit: str = "contain"


@dataclass
class SheetRenderSpec:
    frames_per_cell: int = DEFAULT_CELL_FRAMES
    steps: int = 25
    sampler: str = "res_multistep"
    scheduler: str = "simple"
    cfg: float = 1.0
    seed: int = 42
    shift_video: float = 12.0
    shift_audio: float = 3.0
    ref_max_size: int = 2048
    #: Render shape of one cell (``cell_size`` is its SHORT edge). Per-cell
    #: ``aspect`` overrides it; ``cell_size`` used to be a square edge.
    cell_aspect: str = DEFAULT_CELL_ASPECT
    background: str = "neutral"
    background_custom: str = ""
    #: Which reference supplies the backdrop when ``background`` is ``"reference"``, as
    #: ``"<group>:<slot>"`` (``"pictures:1"`` = the second picture). A backdrop can come from a
    #: picture or a video's setting; audio has no picture to take a room from.
    background_ref: str = ""
    #: How much of the head a face blur covers: ``face`` / ``hair`` / ``head`` (see
    #: :data:`BLUR_SCOPES`). One value for the sheet, because it is a look rather than a
    #: per-picture decision - *whether* a picture is blurred stays per reference.
    blur_scope: str = DEFAULT_BLUR_SCOPE
    #: Latent continuation between cells (see :func:`continuity_plan`): ``off`` renders
    #: every cell from its own noise, ``on`` anchors the previous cell's tail into the
    #: next one. Per-cell ``continuity`` overrides it in both directions.
    continuity: str = DEFAULT_CONTINUITY
    #: Write each cell's rendered clip (frames + the audio H3 generated) next to its
    #: frames, as ``clips/<cell>_0000N_.mp4`` in the sheet folder. The sheet composite is
    #: still the deliverable; the clips are the takes it was picked from, and what feeds
    #: a finished video edit.
    export_video: bool = True
    #: Keep ComfyUI's own per-step preview for this run. Off by default: the sampler's
    #: preview stream is what puts a preview area under the node at all, and the sheet is
    #: shown in the panel instead (see ``preview_silence``). Set ``render.comfyPreview``
    #: when the preview is wanted - it is the switch the live A/B test renders flip.
    comfy_preview: bool = False
    #: Stream the panel's own live preview while a render runs: one small frame per sampling
    #: step, decoded from the latent and sent over the websocket (see ``preview_stream``). On by
    #: default - it is the only thing on screen between "queued" and the finished sheet.
    live_preview: bool = True
    #: How many frames one live preview may carry, and how fast the panel plays them. The frames
    #: are a looping clip of the cell being denoised (see ``preview_stream``); the decoder spends
    #: its own CPU budget deciding how much of the cell it can afford to decode.
    preview_frames: int = 24
    preview_fps: float = 12.0
    #: Render only these cells (by id), leaving every other cell - and, crucially, the frames it
    #: already has on disk - untouched. This is what the panel's "new seed" button writes: the
    #: cell you are looking at is re-rolled on its own, and the sheet is then recomposed from disk
    #: (see the compose route). Empty means the whole sheet, which is what a normal render is.
    only_cells: list[str] = field(default_factory=list)
    #: One-pass sheet (the DEFAULT): ONE H3 render for the whole sheet instead of one per cell -
    #: the panels are asked for in a single prompt over the sheet's own canvas, the frame the model
    #: settles on becomes the sheet, and the panels are sliced back out of it so per-view consumers
    #: (RefMod above all) still work. Roughly a twentieth of the sampling and consistent by
    #: construction (one sampling context, so the panels cannot drift apart), at the price of
    #: per-cell frames, clips, motion and the frame picker. Off = the classic per-cell pass
    #: (see ``one_pass.py`` vs ``nodes/sheet.py``).
    single_pass: bool = True
    #: The resolution control's choice - ``""``, ``"1080p"``, ``"1440p"`` or ``"4k"`` (see
    #: :data:`RESOLUTION_CHOICES`). It records that a size was CHOSEN, which is what lets a
    #: one-pass render be bigger than :data:`ONE_PASS_MAX_PIXELS` without being scaled: the two
    #: paired widget values travel with the payload, and this is the flag that says they are a
    #: decision rather than a leftover.
    resolution: str = ""
    #: Which recommended preset these settings came from (see ``presets.py``). A record, not
    #: a lock: applied presets write their values, and editing a knob afterwards leaves the
    #: id in place so a sheet can still say how it started.
    preset: str = ""
    #: The LAYOUT preset this sheet's cells came from, recorded on its own axis: a layout and a
    #: quality preset are separate decisions, so applying one must not erase where the other
    #: started from. Empty means the cells were hand-authored (or the layout was cleared).
    layout_preset: str = ""
    #: SUITE: the layout presets to render, in order, each into its own sheet folder under this
    #: run's name. Non-empty means this run is a suite (see ``suite.py``) and the single sheet's
    #: own cells/layout are ignored - every board carries its own. This is what makes "a full
    #: suite of sheets for RefMod" one queue instead of four.
    suite: list[str] = field(default_factory=list)


@dataclass
class SheetSpec:
    name: str = "character_sheet"
    global_prompt: str = ""
    negative_prompt: str = ""
    task_type: str = ""
    refs: list[SheetRef] = field(default_factory=list)
    #: The sheet's LoRA stack (the panel's LoRAs tab), applied to the model every cell samples
    #: through - so one list covers every cell and every board of a suite.
    loras: list[SheetLora] = field(default_factory=list)
    cells: list[SheetCell] = field(default_factory=list)
    #: The panel's view/pose/expression ticks. Kept even when the cell list is
    #: edited by hand, so an empty cell list is not a lost intention: the ticks
    #: say what to render.
    build: dict[str, list[str]] = field(default_factory=dict)
    layout: SheetLayoutSpec = field(default_factory=SheetLayoutSpec)
    render: SheetRenderSpec = field(default_factory=SheetRenderSpec)
    warnings: list[str] = field(default_factory=list)
    #: Lines the builder node knows and the compositor cannot compute - which references
    #: were blurred, whether the panel's live preview is on, that the run was a draft.
    #: They travel in the payload so every writer of ``report.txt`` appends the same text,
    #: instead of the node composing a second report of its own.
    notes: list[str] = field(default_factory=list)

    @property
    def pictures(self) -> list[SheetRef]:
        return [ref for ref in self.refs if ref.kind == "picture"]

    @property
    def videos(self) -> list[SheetRef]:
        return [ref for ref in self.refs if ref.kind == "video"]

    @property
    def audios(self) -> list[SheetRef]:
        return [ref for ref in self.refs if ref.kind == "audio"]

    @property
    def enabled_cells(self) -> list[SheetCell]:
        return [cell for cell in self.cells if cell.enabled]

    @property
    def uses_references(self) -> bool:
        return bool(self.pictures or self.videos)

    def to_dict(self) -> dict[str, Any]:
        """Round-trip payload (the manifest keeps the exact spec that was run)."""
        return {
            "version": 1,
            "name": self.name,
            "globalPrompt": self.global_prompt,
            "negativePrompt": self.negative_prompt,
            "taskType": self.task_type,
            "build": {
                "views": list(self.build.get("views") or []),
                "poses": list(self.build.get("poses") or []),
                "expressions": list(self.build.get("expressions") or []),
            },
            "warnings": list(self.warnings),
            "notes": [str(note) for note in self.notes],
            "loras": [entry.to_dict() for entry in self.loras],
            "refs": {
                "pictures": [
                    {
                        "imageFile": r.file,
                        "role": r.role,
                        "enabled": r.enabled,
                        "blurFace": r.blur_face,
                        **({"blurPaint": [dict(stroke) for stroke in r.blur_paint]} if r.blur_paint else {}),
                    }
                    for r in self.pictures
                ],
                "videos": [
                    {"videoFile": r.file, "role": r.role, "enabled": r.enabled, "blurFace": r.blur_face}
                    for r in self.videos
                ],
                "audios": [
                    {"audioFile": r.file, "role": r.role, "enabled": r.enabled}
                    for r in self.audios
                ],
            },
            "sheet": {
                "layout": self.layout.layout,
                "columns": self.layout.columns,
                "shortEdge": self.layout.short_edge,
                "aspect": self.layout.aspect,
                "cellAspect": self.layout.cell_aspect,
                "gap": self.layout.gap,
                "padding": self.layout.padding,
                "captions": self.layout.captions,
                "background": self.layout.background,
                "fit": self.layout.fit,
            },
            "render": {
                "framesPerCell": self.render.frames_per_cell,
                "steps": self.render.steps,
                "sampler": self.render.sampler,
                "scheduler": self.render.scheduler,
                "cfg": self.render.cfg,
                "seed": self.render.seed,
                "shiftVideo": self.render.shift_video,
                "shiftAudio": self.render.shift_audio,
                "refMaxSize": self.render.ref_max_size,
                "cellAspect": self.render.cell_aspect,
                "background": self.render.background,
                "backgroundCustom": self.render.background_custom,
                "backgroundRef": self.render.background_ref,
                "blurScope": self.render.blur_scope,
                # Written even at the default: a saved workflow should say whether its
                # cells were chained or independent.
                "continuity": self.render.continuity,
                "exportVideo": bool(self.render.export_video),
                # The mode, not a preference: a one-pass run produces a different graph, so a
                # saved workflow has to say which of the two it was. Written even at the default
                # so a workflow that turned it off says so.
                "singlePass": bool(self.render.single_pass),
                "resolution": str(self.render.resolution),
                # Round-trips so a run's own preview choice comes back with its settings.
                "comfyPreview": bool(self.render.comfy_preview),
                "livePreview": bool(self.render.live_preview),
                "previewFrames": int(self.render.preview_frames),
                "previewFps": float(self.render.preview_fps),
                "onlyCells": list(self.render.only_cells),
                "preset": self.render.preset,
                "layoutPreset": self.render.layout_preset,
                "suite": list(self.render.suite),
            },
            "cells": [
                {
                    "id": c.id,
                    "enabled": c.enabled,
                    "view": c.view,
                    "pose": c.pose,
                    "expression": c.expression,
                    "extraPrompt": c.extra_prompt,
                    "caption": c.caption,
                    "frames": c.frames,
                    "seed": c.seed,
                    "pick": c.pick,
                    "pickIndex": c.pick_index,
                    "aspect": c.aspect,
                    "place": dict(c.place),
                    "continuity": c.continuity,
                    # The panel's own face source rides the manifest too: a saved spec has to
                    # round-trip as the sheet that was run, panel choices included.
                    **({"faceRef": c.face_ref} if c.face_ref else {}),
                }
                for c in self.cells
            ],
        }


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
_SAFE_ID = re.compile(r"[^A-Za-z0-9 _-]+")
_SAFE_RUNS = re.compile(r"[\s_]+")


def safe_name(value: Any, fallback: str = "character_sheet") -> str:
    """Folder-safe name shared by the spec, the store and the cell ids.

    One implementation on purpose: the spec name becomes the sheet folder name and
    each cell id becomes a file name, so they must normalise identically (only
    ``A-Za-z0-9``, ``_`` and ``-``; runs of separators collapse; 60 chars max).
    """
    text = _SAFE_ID.sub("", str(value or "")).strip()
    text = _SAFE_RUNS.sub("_", text).strip("_- ")
    return text[:60] or fallback


def _clean_id(value: Any, fallback: str) -> str:
    return safe_name(value, fallback)


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    return fallback


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _file_of(item: dict, kind: str) -> str:
    keys = {
        "picture": ("imageFile", "image_file", "file", "imageB64"),
        "video": ("videoFile", "video_file", "file"),
        "audio": ("audioFile", "audio_file", "file"),
    }[kind]
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_blur_mode(item: dict, label: str, warnings: list[str]) -> str:
    """``auto``/``on``/``off``; a checkbox value (true/false) still means something."""
    raw = item.get("blurFace", item.get("blur_face", DEFAULT_BLUR_MODE))
    if isinstance(raw, bool):
        return "on" if raw else "off"
    text = str(DEFAULT_BLUR_MODE if raw is None else raw).strip().lower()
    if not text:
        return DEFAULT_BLUR_MODE
    if text in BLUR_MODES:
        return text
    warnings.append(f"{label}: unknown face blur {text!r}; using {DEFAULT_BLUR_MODE}.")
    return DEFAULT_BLUR_MODE


def parse_blur_paint(raw: Any, label: str, warnings: list[str]) -> list[dict[str, Any]]:
    """Hand-painted blur areas from a payload, validated and clamped.

    A stroke is ``{"tool": "brush"|"lasso", "radius": r, "points": [[x, y], ...]}`` with
    every coordinate normalized to 0-1 (``radius`` against the image's SHORT edge, so a
    brush is round whatever the aspect). Storing the strokes rather than a raster keeps
    the payload small, makes the painting resolution-independent and lets the user edit
    it again later; a broken stroke is dropped with a warning, never a render failure.
    """
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        warnings.append(f"{label}: face blur paint must be a list of strokes.")
        return []
    strokes: list[dict[str, Any]] = []
    for index, item in enumerate(list(raw)[:MAX_PAINT_STROKES]):
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "brush").strip().lower()
        if tool not in BLUR_TOOLS:
            warnings.append(f"{label}: unknown paint tool {tool!r}; using 'brush'.")
            tool = "brush"
        points: list[list[float]] = []
        for point in list(item.get("points") or [])[:MAX_PAINT_POINTS]:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            x = min(1.0, max(0.0, _as_float(point[0], 0.0)))
            y = min(1.0, max(0.0, _as_float(point[1], 0.0)))
            points.append([round(x, 4), round(y, 4)])
        # A lasso needs an area, a brush only a starting point.
        if len(points) < (3 if tool == "lasso" else 1):
            continue
        radius = min(
            MAX_BRUSH_RADIUS,
            max(MIN_BRUSH_RADIUS, _as_float(item.get("radius"), DEFAULT_BRUSH_RADIUS)),
        )
        strokes.append({"tool": tool, "radius": round(radius, 4), "points": points})
    if isinstance(raw, (list, tuple)) and len(raw) > MAX_PAINT_STROKES:
        warnings.append(f"{label}: kept the first {MAX_PAINT_STROKES} painted strokes.")
    return strokes


def has_blur_paint(ref: SheetRef) -> bool:
    """Whether this reference has anything painted on it."""
    return bool(ref.blur_paint)


def _parse_refs(raw: Any, warnings: list[str]) -> list[SheetRef]:
    block = raw if isinstance(raw, dict) else {}
    refs: list[SheetRef] = []
    for kind, limit, list_key in (
        ("picture", MAX_PICTURES, "pictures"),
        ("video", MAX_VIDEOS, "videos"),
        ("audio", MAX_AUDIOS, "audios"),
    ):
        items = block.get(list_key)
        if not isinstance(items, list):
            continue
        kept = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            file = _file_of(item, kind)
            if not file:
                continue
            if kept >= limit:
                warnings.append(
                    f"{list_key}: kept the first {limit} references; extra slots ignored."
                )
                break
            role = str(item.get("role") or item.get("label") or "").strip()[:160]
            label = f"{list_key} {kept + 1}"
            refs.append(
                SheetRef(
                    kind=kind,
                    file=file,
                    role=role,
                    enabled=_as_bool(item.get("enabled"), True),
                    index=kept,
                    blur_face=_parse_blur_mode(item, label, warnings),
                    blur_paint=parse_blur_paint(
                        item.get("blurPaint", item.get("blur_paint")), label, warnings
                    ),
                )
            )
            kept += 1
    # A tag number has to be the number the run actually wires: H3 receives ONLY the
    # enabled references, in this order, and numbers them itself. Letting a disabled
    # slot consume a number shifts every tag after it, so "<Picture 2>" in the prompt
    # points at another photo (or at a picture the model never saw) - the identity
    # clause then names the wrong reference and the model blends the faces.
    counters: dict[str, int] = {}
    for ref in refs:
        if ref.enabled:
            ref.index = counters.get(ref.kind, 0)
            ref.source = ref.index
            counters[ref.kind] = ref.index + 1
    for ref in refs:
        if not ref.enabled:
            # Unchecked slots sit past the wired range: unique, but not a tag the
            # prompt ever uses (the legend and the attribution lines skip them).
            ref.index = counters.get(ref.kind, 0)
            counters[ref.kind] = ref.index + 1
    return refs


def _parse_loras(raw: Any, warnings: list[str]) -> list[SheetLora]:
    """The sheet's LoRA stack: which files, how hard, switched on or not.

    Accepts what the panel writes (``[{"file": ..., "strength": ..., "on": true}]``) and the
    shorthand a hand-written payload may use (``"Minimax/x.safetensors@0.8"``, or a bare file name
    at full strength). A repeated file is one entry - the last mention wins, because a stack with
    the same LoRA twice is a strength typo, not an intention.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [part for part in re.split(r"[,\n;]+", raw) if part.strip()]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        warnings.append("loras: expected a list of LoRA entries; ignoring it.")
        return []

    stack: list[SheetLora] = []
    seen: dict[str, int] = {}
    for item in raw:
        name = ""
        strength = DEFAULT_LORA_STRENGTH
        on = True
        if isinstance(item, str):
            text = item.strip()
            if "@" in text:
                text, _, raw_strength = text.rpartition("@")
                strength = _as_float(raw_strength, DEFAULT_LORA_STRENGTH)
            name = text.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("file")
                or item.get("lora")
                or item.get("name")
                or item.get("lora_name")
                or ""
            ).strip()
            strength = _as_float(
                item.get("strength", item.get("strengthModel", item.get("strength_model"))),
                DEFAULT_LORA_STRENGTH,
            )
            on = _as_bool(item.get("on", item.get("enabled")), True)
        if not name:
            continue
        # A loader widget writes the file name as-is; a hand-typed one may carry the folder
        # separator the other way round, and a leading "./" is never part of the name.
        name = name.replace("\\", "/").lstrip("./").strip()
        if not name:
            continue
        low, high = LORA_STRENGTH_RANGE
        clamped = round(min(high, max(low, strength)), 3)
        entry = SheetLora(file=name, strength=clamped, on=on)
        if name in seen:
            stack[seen[name]] = entry
            continue
        if len(stack) >= MAX_LORAS:
            warnings.append(
                f"loras: more than {MAX_LORAS} entries; the rest are ignored (one sheet is one "
                "look - a stack this long is a mistake, not a style)."
            )
            break
        seen[name] = len(stack)
        stack.append(entry)
    return stack


def _parse_cell_aspect(render_raw: dict[str, Any], warnings: list[str]) -> str:
    """Render shape of one cell (``"3:4"``/``"768x1024"``); the default if unreadable."""
    value = str(
        render_raw.get("cellAspect", render_raw.get("cell_aspect")) or DEFAULT_CELL_ASPECT
    ).strip()
    try:
        ratio = aspect_ratio(value, DEFAULT_CELL_ASPECT)
    except ValueError:
        warnings.append(f"unknown cell aspect {value!r}; using {DEFAULT_CELL_ASPECT}.")
        return DEFAULT_CELL_ASPECT
    if ratio <= 0:
        warnings.append(f"unknown cell aspect {value!r}; using {DEFAULT_CELL_ASPECT}.")
        return DEFAULT_CELL_ASPECT
    return value


#: What people call the same three sizes: the display short edge, the display width, or the key
#: the control uses. Anything else leaves the flag off, and the canvas then follows the widgets
#: (or the guidance ceiling).
_RESOLUTION_ALIASES: dict[str, str] = {
    "1080p": "1080p", "1080": "1080p", "1920": "1080p", "fhd": "1080p",
    "1440p": "1440p", "1440": "1440p", "2560": "1440p", "qhd": "1440p", "2k": "1440p",
    "4k": "4k", "2160": "4k", "2160p": "4k", "3840": "4k", "uhd": "4k",
}


def _parse_resolution(render_raw: dict[str, Any]) -> str:
    """The resolution control's choice - ``""`` means the size was set by hand.

    The flag matters beyond bookkeeping: a chosen size is honoured as-is even when it is bigger
    than :data:`ONE_PASS_MAX_PIXELS`, because it is a decision rather than a leftover (see
    ``one_pass.one_pass_budget``).
    """
    key = str(render_raw.get("resolution") or "").strip().lower()
    return _RESOLUTION_ALIASES.get(key, "")


def _parse_suite(render_raw: dict[str, Any]) -> list[str]:
    """The suite's board ids, in order (``render.suite``: a list, or a comma-separated run).

    A board that is not a layout preset is dropped here rather than failing the run: the suite is
    a convenience, and ``suite.py`` reports what it could not resolve instead of rendering a board
    that would have been identical to this sheet.
    """
    raw = render_raw.get("suite")
    if isinstance(raw, str):
        items: list[Any] = [part for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    ordered: list[str] = []
    for item in items:
        key = str(item or "").strip().lower()
        if key and key not in ordered:
            ordered.append(key)
    return ordered[:MAX_SUITE_BOARDS]


def _parse_blur_scope(render_raw: dict[str, Any], warnings: list[str]) -> str:
    """How much of the head a blur covers, falling back to the default."""
    value = str(
        render_raw.get("blurScope", render_raw.get("blur_scope")) or DEFAULT_BLUR_SCOPE
    ).strip().lower()
    if value in BLUR_SCOPES:
        return value
    warnings.append(f"unknown blur area {value!r}; using {DEFAULT_BLUR_SCOPE}.")
    return DEFAULT_BLUR_SCOPE


def _parse_continuity(render_raw: dict[str, Any], warnings: list[str]) -> str:
    """Sheet-wide latent continuation between cells, defaulting to off."""
    value = str(
        render_raw.get("continuity") or DEFAULT_CONTINUITY
    ).strip().lower()
    if value in CONTINUITY_MODES:
        return value
    # A frame count is a reasonable thing to write by hand ("5"); it still means on,
    # because the hand-over length is fixed by the H3 guide grid.
    if value.isdigit() and int(value) > 0:
        warnings.append(
            f"continuity {value!r} is a frame count, not a mode; using 'on' "
            f"({CONTINUITY_FRAMES} frames)."
        )
        return "on"
    warnings.append(f"unknown continuity {value!r}; using {DEFAULT_CONTINUITY}.")
    return DEFAULT_CONTINUITY


def _parse_cell_continuity(item: dict[str, Any], cell_id: str, warnings: list[str]) -> str:
    """Per-cell override of the sheet's continuation switch."""
    value = str(
        item.get("continuity") or DEFAULT_CELL_CONTINUITY
    ).strip().lower()
    if value in CONTINUITY_CELL_MODES:
        return value
    truthy = {"true": "on", "yes": "on", "1": "on", "false": "off", "no": "off", "0": "off"}
    if value in truthy:
        return truthy[value]
    warnings.append(
        f"cell {cell_id}: unknown continuity {value!r}; using {DEFAULT_CELL_CONTINUITY}."
    )
    return DEFAULT_CELL_CONTINUITY


def _parse_background(render_raw: dict[str, Any], warnings: list[str]) -> str:
    """Background preset key, falling back to the neutral backdrop."""
    value = str(render_raw.get("background") or "neutral").strip().lower()
    if value not in BACKGROUND_KEYS:
        warnings.append(f"unknown background {value!r}; using 'neutral'.")
        return "neutral"
    if value == "custom":
        custom = str(
            render_raw.get("backgroundCustom", render_raw.get("background_custom")) or ""
        ).strip()
        if not custom:
            warnings.append("background 'custom' has no text; using 'neutral'.")
            return "neutral"
    return value


_BUILD_KEYS = ("views", "poses", "expressions")


def _parse_build(raw: Any, warnings: list[str]) -> dict[str, list[str]]:
    """The panel's tick selection: which views/poses/expressions it offered to build."""
    if not isinstance(raw, dict):
        return {}
    known = {
        "views": set(VIEW_KEYS),
        "poses": set(POSE_KEYS),
        "expressions": set(EXPRESSION_KEYS),
    }
    build: dict[str, list[str]] = {}
    for key in _BUILD_KEYS:
        values = raw.get(key)
        if not isinstance(values, (list, tuple)):
            continue
        kept: list[str] = []
        for value in values:
            text = str(value).strip().lower()
            if text in known[key] and text not in kept:
                kept.append(text)
            else:
                warnings.append(f"build.{key}: ignoring unknown value {text!r}.")
        if kept:
            build[key] = kept
    return build


def _parse_cells(raw: Any, render: SheetRenderSpec, warnings: list[str]) -> list[SheetCell]:
    if not isinstance(raw, list):
        return []
    cells: list[SheetCell] = []
    used_ids: set[str] = set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        if len(cells) >= MAX_CELLS:
            warnings.append(f"cells: kept the first {MAX_CELLS} cells; extra cells ignored.")
            break
        cell_id = _clean_id(item.get("id"), f"c{position + 1}")
        if cell_id in used_ids:
            cell_id = f"{cell_id}-{position + 1}"
        used_ids.add(cell_id)

        view = str(item.get("view") or "front").strip().lower()
        if view not in VIEW_KEYS:
            warnings.append(f"cell {cell_id}: unknown view {view!r}; using 'front'.")
            view = "front"
        pose = str(item.get("pose") or "neutral").strip().lower()
        if pose not in POSE_KEYS:
            warnings.append(f"cell {cell_id}: unknown pose {pose!r}; using 'neutral'.")
            pose = "neutral"
        expression = str(item.get("expression") or "neutral").strip().lower()
        if expression not in EXPRESSION_KEYS:
            warnings.append(
                f"cell {cell_id}: unknown expression {expression!r}; using 'neutral'."
            )
            expression = "neutral"

        # "<group>:<slot>", the way the payload writes it. Validated against the refs when the
        # cell prompt is built (see cell_face_reference): a cell can outlive a deleted reference,
        # and that must not break the run.
        face_ref = str(item.get("faceRef", item.get("face_ref")) or "").strip()
        if face_ref and ":" not in face_ref:
            warnings.append(
                f"cell {cell_id}: face reference {face_ref!r} is not '<group>:<slot>'; ignored."
            )
            face_ref = ""

        pick = str(item.get("pick") or "auto").strip().lower()
        pick_index = item.get("pickIndex", item.get("pick_index"))
        if pick not in PICKS:
            # A raw number is accepted as a direct frame index.
            numeric = _as_int(pick, -1)
            if numeric >= 0:
                pick_index = numeric
                pick = "last"
            else:
                warnings.append(f"cell {cell_id}: unknown pick {pick!r}; using 'auto'.")
                pick = "auto"

        place_raw = item.get("place") if isinstance(item.get("place"), dict) else {}
        place = {
            key: _clamp(_as_int(place_raw.get(key), 0), 0, 63)
            for key in ("row", "col", "rowSpan", "colSpan")
            if place_raw.get(key) is not None
        }

        # H3 samples 5, 22, 39, 56... frames and nothing between, so a requested length is
        # rounded UP and the clip is longer than asked. Worth saying out loud: it is the
        # difference between "8 frames" and a 22-frame render (and, with continuation, the
        # reason a chained cell has room for its hand-over at all).
        requested_frames = _as_int(
            item.get("frames") or item.get("frameCount") or render.frames_per_cell,
            render.frames_per_cell,
        )
        cell_frames = align_h3_frames(requested_frames)
        if cell_frames != requested_frames:
            warnings.append(
                f"cell {cell_id}: {requested_frames} frame(s) snapped up to {cell_frames} "
                "(H3 samples 5, 22, 39... frames)."
            )

        cells.append(
            SheetCell(
                id=cell_id,
                view=view,
                pose=pose,
                expression=expression,
                extra_prompt=str(item.get("extraPrompt") or item.get("extra_prompt") or "").strip(),
                caption=str(item.get("caption") or "").strip()[:120],
                frames=cell_frames,
                seed=_as_int(item.get("seed"), 0),
                pick=pick,
                pick_index=(
                    _clamp(_as_int(pick_index, 0), 0, MAX_CELL_FRAMES - 1)
                    if pick_index is not None
                    else None
                ),
                aspect=str(item.get("aspect") or "").strip(),
                enabled=_as_bool(item.get("enabled"), True),
                face_ref=face_ref,
                place=place,
                continuity=_parse_cell_continuity(item, cell_id, warnings),
            )
        )
    return cells


def _parse_only_cells(render_raw: dict[str, Any]) -> list[str]:
    """The render scope: ``render.onlyCells`` - the cells this run renders, by id.

    The panel writes this when one cell is re-rolled with a new seed. Everything that reads
    ``spec.enabled_cells`` (the render, the per-cell saver, the grid) then agrees that this run
    is about those cells; the cells it leaves out keep the frames they already have on disk,
    which is what the compose route rebuilds the sheet from afterwards.
    """
    raw = render_raw.get("onlyCells", render_raw.get("only_cells"))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _apply_only_cells(spec: SheetSpec) -> None:
    """Narrow a spec to ``render.onlyCells``, in place, saying so in the warnings.

    Disabling a cell here (rather than filtering the list) keeps every position in the sheet
    meaningful: the layout, the manifest and the report still describe the whole sheet, with one
    cell marked as the only one this run renders.
    """
    wanted = [cell_id for cell_id in spec.render.only_cells]
    if not wanted:
        return
    known = {cell.id for cell in spec.cells}
    missing = [cell_id for cell_id in wanted if cell_id not in known]
    for cell in spec.cells:
        cell.enabled = cell.id in wanted
    chosen = [cell.id for cell in spec.cells if cell.enabled]
    if not chosen:
        # Nothing matched: rather than render an empty sheet, fall back to the whole thing.
        for cell in spec.cells:
            cell.enabled = True
        spec.warnings.append(
            f"render.onlyCells named {', '.join(wanted)} - no such cell; rendering the whole sheet."
        )
        return
    spec.warnings.append(
        f"Re-render scope: only {', '.join(chosen)} - the other cell(s) keep the frames "
        "already on disk."
        + (f" ({', '.join(missing)} not found.)" if missing else "")
    )


def parse_sheet_spec(raw: Any) -> SheetSpec:
    """Parse the panel payload (dict or JSON string) into a validated spec."""
    warnings: list[str] = []
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            data = {}
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid sheet_data JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("sheet_data must be a JSON object.")

    render_raw = data.get("render") if isinstance(data.get("render"), dict) else {}
    render = SheetRenderSpec(
        frames_per_cell=align_h3_frames(
            render_raw.get("framesPerCell", render_raw.get("frames_per_cell", DEFAULT_CELL_FRAMES))
        ),
        steps=_clamp(_as_int(render_raw.get("steps"), 25), 1, 200),
        sampler=str(render_raw.get("sampler") or "res_multistep").strip() or "res_multistep",
        scheduler=str(render_raw.get("scheduler") or "simple").strip() or "simple",
        cfg=_as_float(render_raw.get("cfg"), 1.0),
        seed=_as_int(render_raw.get("seed"), 42),
        shift_video=_as_float(render_raw.get("shiftVideo", render_raw.get("shift_video")), 12.0),
        shift_audio=_as_float(render_raw.get("shiftAudio", render_raw.get("shift_audio")), 3.0),
        ref_max_size=_clamp(_as_int(render_raw.get("refMaxSize", render_raw.get("ref_max_size")), 2048), 512, 4096),
        cell_aspect=_parse_cell_aspect(render_raw, warnings),
        background=_parse_background(render_raw, warnings),
        background_custom=str(
            render_raw.get("backgroundCustom", render_raw.get("background_custom")) or ""
        ).strip(),
        background_ref=str(
            render_raw.get("backgroundRef", render_raw.get("background_ref")) or ""
        ).strip().lower(),
        blur_scope=_parse_blur_scope(render_raw, warnings),
        continuity=_parse_continuity(render_raw, warnings),
        export_video=_as_bool(
            render_raw.get("exportVideo", render_raw.get("export_video")), True
        ),
        single_pass=_as_bool(
            render_raw.get(
                "singlePass",
                render_raw.get(
                    "single_pass",
                    # The mode's first name, kept as an alias: payloads and notes written while
                    # it was called the draft pass still say what they mean.
                    render_raw.get("draft", render_raw.get("draftSheet", render_raw.get("draft_sheet"))),
                ),
            ),
            True,
        ),
        resolution=_parse_resolution(render_raw),
        comfy_preview=_as_bool(
            render_raw.get("comfyPreview", render_raw.get("comfy_preview")), False
        ),
        live_preview=_as_bool(
            render_raw.get("livePreview", render_raw.get("live_preview")), True
        ),
        preview_frames=_clamp(
            _as_int(render_raw.get("previewFrames", render_raw.get("preview_frames")), 24), 1, 48
        ),
        preview_fps=min(30.0, max(1.0, _as_float(
            render_raw.get("previewFps", render_raw.get("preview_fps")), 12.0
        ))),
        only_cells=_parse_only_cells(render_raw),
        preset=str(render_raw.get("preset") or "").strip(),
        layout_preset=str(
            render_raw.get("layoutPreset", render_raw.get("layout_preset")) or ""
        ).strip(),
        suite=_parse_suite(render_raw),
    )
    sheet_raw = data.get("sheet") if isinstance(data.get("sheet"), dict) else {}
    layout_name = str(sheet_raw.get("layout") or "hero-left").strip().lower()
    if layout_name not in LAYOUTS:
        warnings.append(f"unknown layout {layout_name!r}; using 'hero-left'.")
        layout_name = "hero-left"
    fit = str(sheet_raw.get("fit") or "contain").strip().lower()
    if fit not in ("contain", "cover", "stretch"):
        warnings.append(f"unknown fit {fit!r}; using 'contain'.")
        fit = "contain"
    aspect_label = str(sheet_raw.get("aspect") or DEFAULT_ASPECT).strip() or DEFAULT_ASPECT
    if aspect_label.lower() not in _ASPECTS:
        aspect_ratio(aspect_label, DEFAULT_ASPECT)  # validates the "WxH" form
    layout = SheetLayoutSpec(
        layout=layout_name,
        columns=_clamp(_as_int(sheet_raw.get("columns"), 2), 1, 6),
        short_edge=_clamp(_as_int(sheet_raw.get("shortEdge", sheet_raw.get("short_edge")), DEFAULT_SHORT_EDGE), 256, 4096),
        aspect=aspect_label,
        cell_aspect=str(sheet_raw.get("cellAspect", sheet_raw.get("cell_aspect")) or "").strip(),
        gap=_clamp(_as_int(sheet_raw.get("gap"), 16), 0, 200),
        padding=_clamp(_as_int(sheet_raw.get("padding"), 24), 0, 400),
        captions=_as_bool(sheet_raw.get("captions"), True),
        background=str(sheet_raw.get("background") or "#101014").strip() or "#101014",
        fit=fit,
    )

    refs = _parse_refs(data.get("refs"), warnings)
    cells = _parse_cells(data.get("cells"), render, warnings)
    if not cells:
        warnings.append("No cells in the payload; the node cannot render an empty sheet.")

    # A reference backdrop can only be checked once the references are parsed: say so here
    # rather than let a cell prompt promise a setting that is not wired in. The backdrop
    # then falls back to neutral (see background_clause) instead of rendering something
    # nobody chose.
    if render.background == "reference" and resolve_background_ref(refs, render.background_ref) is None:
        warnings.append(
            f"background 'reference' names {render.background_ref or 'nothing'!r}, which is "
            "not an enabled picture or video; using the neutral backdrop."
        )

    # Warnings raised by whoever resolved this payload (the sheet node's fallback
    # notices, for example) come first: they explain the cells that follow.
    inherited = [str(item).strip() for item in (data.get("warnings") or []) if str(item).strip()]
    notes = [str(item).strip() for item in (data.get("notes") or []) if str(item).strip()]

    name = _clean_id(data.get("name"), "character_sheet")
    spec = SheetSpec(
        name=name,
        global_prompt=str(data.get("globalPrompt") or data.get("global_prompt") or "").strip(),
        negative_prompt=str(data.get("negativePrompt") or data.get("negative_prompt") or "").strip(),
        task_type=str(data.get("taskType") or data.get("task_type") or "").strip(),
        refs=refs,
        loras=_parse_loras(data.get("loras"), warnings),
        cells=cells,
        build=_parse_build(data.get("build"), warnings),
        layout=layout,
        render=render,
        warnings=inherited[:20] + warnings,
        notes=notes[:40],
    )
    # The render scope decides which cells this run touches; it has to be applied before anyone
    # asks for `enabled_cells` (the work items, the saver, the grid), so it happens here.
    _apply_only_cells(spec)
    return spec


# --------------------------------------------------------------------------- #
# prompt assembly
# --------------------------------------------------------------------------- #
def attributes_hidden_by(view: Any) -> tuple[str, ...]:
    """The attributes a framing cannot show (see ``ATTRIBUTES_HIDDEN_BY_VIEW``)."""
    return ATTRIBUTES_HIDDEN_BY_VIEW.get(str(view or "").strip().lower(), ())


def reference_legend(
    spec: SheetSpec,
    *,
    enabled_only: bool = True,
    refs: list[SheetRef] | None = None,
    hidden: Iterable[str] = (),
) -> str:
    """The "which reference carries what" block shared by every cell prompt.

    H3 reads the official ``<Picture N>`` / ``<Video K>`` / ``<Audio J>`` tags, so
    the legend states each tag AND the user's role text for it - that pairing is
    what makes "Picture 2 is the body" actually steer the render.

    The roles are read as attributes (see :func:`reference_attributes`), so the
    ownership claim is stated the way the ref2va prompts that behave state it: a
    reference that is the ONLY claimant of what it describes is called the *sole
    source* of those attributes ("``<Picture 1>`` is the sole source of the face and
    the hair."). It is a claim about this run, so it needs the whole picture/video
    set to compute: a tag that shares an attribute is never called sole.

    ``hidden`` is the framing's own out-of-frame list (:func:`attributes_hidden_by`).
    A chest-up portrait must not be told that a reference owns the groin - naming an
    attribute the shot cannot contain is an invitation to include it - so a partly
    hidden role falls back to the user's own words plus the claim it CAN show
    ("``<Picture 2>`` is the breasts, butt, vagina reference and the only source of
    the breasts."). The exclusivity count still uses every claimant: hiding an
    attribute must not promote a shared one to "sole".

    A slot the user left without a role gets a neutral sentence for its kind rather
    than the word "reference" twice: the panel shows the role as a placeholder, so
    an empty box must not invent a claim about the reference's content.
    """
    source = refs if refs is not None else spec.refs
    selected = [ref for ref in source if not enabled_only or ref.enabled]
    hidden_set = frozenset(hidden)

    supplied: dict[str, list[SheetRef]] = {}
    for ref in selected:
        if ref.kind not in ("picture", "video"):
            continue
        for attribute in reference_attributes(ref.role):
            supplied.setdefault(attribute, []).append(ref)

    lines: list[str] = []
    for ref in selected:
        role = (ref.role or "").strip()
        has_role = bool(role) and role.lower() != "reference"
        claimed = (
            reference_attributes(ref.role) if ref.kind in ("picture", "video") else set()
        )
        visible = claimed - hidden_set
        sole = [
            attribute
            for attribute in ATTRIBUTE_LABELS
            if attribute in visible and len(supplied.get(attribute) or ()) == 1
        ]
        sole_labels = [ATTRIBUTE_LABELS[attribute] for attribute in sole]
        if sole_labels and len(sole) == len(claimed):
            # The proven ref2va shape: the tag, the user's own phrase in brackets, then
            # the exclusivity claim. The brackets only appear when the vocabulary does
            # NOT already say everything the role said ("head", "elf ears").
            extra = unmatched_role_words(role)
            descriptor = f" ({role})" if extra else ""
            lines.append(f"{ref.tag}{descriptor} is the sole source of {_join(sole_labels)}.")
        elif sole_labels and has_role:
            lines.append(
                f"{ref.tag} is the {role} reference and the only source of "
                f"{_join(sole_labels)}."
            )
        elif has_role:
            lines.append(f"{ref.tag} is the {role} reference.")
        else:
            lines.append(f"{ref.tag} is a {_KIND_FALLBACK_ROLE.get(ref.kind, 'reference')}.")
    return "\n".join(lines)


def describe_background(spec: SheetSpec) -> str:
    """Readable name of the chosen backdrop (plan lines, report.txt, status)."""
    key = spec.render.background
    for option in BACKGROUNDS:
        if option.key != key:
            continue
        if key == "custom":
            return f"{spec.render.background_custom.strip()} (custom)"
        if key == "reference":
            reference = background_reference(spec)
            if reference is not None:
                label = "setting" if reference.kind == "video" else "background"
                return f"the {label} of {reference.tag} ({key})"
            return f"{option.label} - no reference chosen ({key})"
        return f"{option.label} ({key})"
    return key


#: Attribute vocabulary, most specific first. Reading the role the user typed
#: ("face, hair, glasses" vs "body and clothes") is what lets the prompt say which
#: picture may supply what - and, just as important, which pictures may NOT.
#:
#: Clothes and bodies are split finer than the rest because that is where an adult
#: sheet's references are usually divided: "body and bikini" against "breasts, butt,
#: vagina". ``body`` is the silhouette every framing sees (proportions, waist, hips,
#: skin), ``breasts`` is the chest - visible in a portrait - and ``intimate`` is what
#: only a full-body cell shows. Keeping them apart is what lets the framing filter drop
#: a chest-up reference's groin claim without dropping its chest claim too.
ATTRIBUTE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hair", ("hair", "bangs", "ponytail", "locks", "fringe")),
    ("glasses", ("glass", "spectacles", "eyewear")),
    ("eyes", ("eye", "iris")),
    ("face", ("face", "facial", "features", "makeup", "lipstick", "complexion")),
    (
        "clothing",
        (
            "cloth", "outfit", "dress", "skirt", "shirt", "top", "uniform", "apron",
            "cosplay", "costume", "wardrobe", "lingerie", "trousers", "pants", "jacket",
            "bikini", "swimsuit", "swimwear", "underwear", "bra", "panties", "thong",
            "leotard", "bodysuit", "corset", "camisole", "garter", "nightgown", "robe",
        ),
    ),
    ("legwear", ("sock", "stocking", "tights", "legwear")),
    ("shoes", ("shoe", "boot", "heel", "sandal", "slipper")),
    (
        "body",
        (
            "body", "figure", "proportion", "shape", "build", "skin", "tattoo", "height",
            "chest", "waist", "hip", "thigh", "torso", "silhouette", "navel", "abdomen",
            "midriff", "muscle", "curve",
        ),
    ),
    ("breasts", ("breast", "boob", "tit", "bust", "nipple", "areola")),
    (
        "intimate",
        (
            "butt", "ass", "glute", "crotch", "pubic", "vulva", "vagina", "labia",
            "mons", "pussy", "penis", "cock", "dick", "scrotum", "testicle", "anus",
        ),
    ),
    (
        "accessories",
        ("accessor", "bow", "jewel", "necklace", "earring", "hat", "glove", "choker", "belt"),
    ),
    ("voice", ("voice", "speech", "accent")),
)

ATTRIBUTE_LABELS: dict[str, str] = {
    "face": "the face",
    "eyes": "the eyes",
    "glasses": "the glasses",
    "hair": "the hair",
    "clothing": "the clothing",
    "body": "the body proportions",
    "breasts": "the breasts",
    "intimate": "the intimate anatomy",
    "legwear": "the legwear",
    "shoes": "the shoes",
    "accessories": "the accessories",
    "voice": "the voice",
}

#: What a tight head shot can show: nothing below the neck, and no body under the collar.
_HEAD_ONLY: tuple[str, ...] = (
    "clothing", "body", "breasts", "intimate", "legwear", "shoes",
)

#: Attributes a framing cannot show: a from-behind cell must not be asked to match
#: eyes or glasses nobody can see, a close-up must not be told about an outfit, shoes or
#: a body it cannot fit in frame, and a chest-up portrait stops above the groin.
ATTRIBUTES_HIDDEN_BY_VIEW: dict[str, tuple[str, ...]] = {
    "back": ("face", "eyes", "glasses"),
    # 135 degrees: the face is nearly gone but the jaw, ear and hair are not.
    "three-quarter-back": ("eyes", "glasses"),
    # Seen from behind: the hair and the back are the whole shot.
    "head-back": ("face", "eyes", "glasses") + _HEAD_ONLY,
    "face": _HEAD_ONLY,
    # The same head, from the side: same ceiling on what the cell can contain.
    "face-profile": _HEAD_ONLY,
    "eyes": _HEAD_ONLY,
    # The mouth crop is a head-only framing too (nothing below the collar is in frame), and
    # it is the one head crop where the eyes are out of shot.
    "mouth": _HEAD_ONLY + ("eyes",),
    # A feet crop shows shoes, legwear and - at most - the hem of the clothing.
    "feet": ("face", "eyes", "glasses", "hair", "body", "breasts", "intimate"),
    # The body crops: no face in any of them, and what the framing cannot contain is
    # dropped so a reference's claim about it does not get argued with.
    "breasts": ("face", "eyes", "glasses", "body", "legwear", "shoes"),
    "groin": ("face", "eyes", "glasses", "hair", "shoes"),
    "butt": ("face", "eyes", "glasses", "shoes"),
    "portrait": ("intimate", "legwear", "shoes"),
    # A crop of the hands shows no body, but the sleeves are in frame - so clothing stays.
    "hands": ("body", "breasts", "intimate"),
    # Waist down: no face in the shot, and the guard in cell_references keeps the
    # identity reference wired even when its only claim is the face.
    "legs": ("face", "eyes", "glasses"),
}

#: The angles a front-facing reference picture CANNOT show, and how to name them. A side or
#: back view is the one place the model has to invent part of the head - and the second
#: reference (usually a full-body outfit photo of somebody with their own hair) is right
#: there with a plausible answer. Measured: a profile panel came back wearing the OTHER
#: reference's dark hair while every view the reference covers kept the braids.
_HAIR_HOLDS_BY_VIEW: dict[str, str] = {
    "profile": "seen from the side",
    "face-profile": "seen from the side",
    "three-quarter-back": "seen from behind and to one side",
    "back": "seen from behind",
    "head-back": "seen from behind, the back of the head",
}


#: Attributes that decide *who* the person is. A reference that claims none of them
#: is not an identity source no matter how much of a person is visible in it, which is
#: the distinction the outfit-photo case turns on.
LIKENESS_ATTRIBUTES: tuple[str, ...] = ("face", "eyes", "hair")

#: The sentence that does the work, taken from the ref2va renders that behave - the
#: reference docs in this pack use the same list ("must not supply a face, hair, body
#: shape, skin tone, background or framing"). Asking a picture to "supply clothing
#: only" is too abstract for the model; naming the parts of a face it must not lend
#: is what it can act on.
_LIKENESS_BAN = (
    "must not supply a face, a hairstyle, hair colour, hair length, skin tone or facial "
    "features - the person visible in it is not the identity, do not copy their face or "
    "their hair"
)


#: Suffixes a keyword may carry and still mean the same attribute (plural / gerund).
_KEYWORD_SUFFIXES = ("", "s", "es", "ing", "ed")

#: Filler in a role box ("face and hair", "her face, plus hair"). Never a role word by
#: itself, so it must not count as "the user typed something we cannot read".
_ROLE_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "both", "for", "her", "his", "in", "is",
        "main", "of", "on", "only", "or", "plus", "reference", "the", "their", "to",
        "with",
    }
)


def _matches_keyword(word: str, keyword: str) -> bool:
    """``tops``/``clothes`` match ``top``/``cloth``; ``topic`` must not match ``top``."""
    if not word.startswith(keyword):
        return False
    return word[len(keyword):] in _KEYWORD_SUFFIXES


def role_words(role: str) -> list[str]:
    """The words of a role box, lowercased and stripped of punctuation and filler."""
    words: list[str] = []
    for raw in str(role or "").split():
        word = raw.strip(".,;:/()[]-_+").lower()
        if word and word not in _ROLE_STOPWORDS:
            words.append(word)
    return words


def unmatched_role_words(role: str) -> list[str]:
    """Role words the attribute vocabulary does not read (``head``, ``elf ears``).

    Those words are the only description of what the reference actually shows, so the
    legend keeps the user's own phrase whenever one is present - a role the vocabulary
    fully understands does not need to be repeated next to the labels it produced.
    """
    return [
        word
        for word in role_words(role)
        if not any(
            _matches_keyword(word, keyword)
            for _attribute, keywords in ATTRIBUTE_KEYWORDS
            for keyword in keywords
        )
    ]


def reference_attributes(role: str) -> set[str]:
    """Which attributes a reference's role text claims (empty when it says nothing).

    Word-level matching with a plural suffix tolerance ("tops", "clothes"): a bare
    prefix match is too greedy - "topic" must not register as clothing because the
    keyword is "top". First bucket wins, so "glasses" is not also an accessory.
    """
    words = [word.strip(".,;:/()[]-_").lower() for word in str(role or "").split()]
    found: set[str] = set()
    for word in words:
        if not word:
            continue
        for attribute, keywords in ATTRIBUTE_KEYWORDS:
            if any(_matches_keyword(word, keyword) for keyword in keywords):
                found.add(attribute)
                break
    return found


def _join(items: list[str]) -> str:
    """"a, b and c" - prompts read better than a bare comma list."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


#: The payload's group names -> the reference kinds they hold (see REF_GROUPS in the panel).
FACE_REF_KINDS = {"pictures": "picture", "videos": "video", "audios": "audio"}


def cell_face_reference(cell: SheetCell, refs: Iterable[SheetRef]) -> SheetRef | None:
    """The reference a CELL names as its likeness source (``cell.face_ref``), or ``None``.

    ``"pictures:1"`` = the picture the prompt calls ``<Picture 2>`` - the number is the TAG
    number, i.e. the position among the ENABLED references of that kind, which is the number
    the user sees on the tile badge. It therefore shifts when a reference is unchecked, in
    exactly the way ``<Picture N>`` in a prompt shifts; the panel's own badge tells the user
    which number is which.

    A cell can outlive the reference it points at (the tile was removed, or the slot was
    cleared), which is why this is a lookup and not a promise: a name that matches nothing
    leaves the cell on the run-wide identity source.
    """
    wanted = str(getattr(cell, "face_ref", "") or "").strip()
    if ":" not in wanted:
        return None
    group, _, raw = wanted.partition(":")
    kind = FACE_REF_KINDS.get(group)
    if kind is None or not raw.lstrip("-").isdigit():
        return None
    slot = int(raw)
    if slot < 0:
        return None
    for ref in refs:
        if not ref.enabled or ref.kind != kind:
            continue
        if ref.index == slot or ref.source == slot:
            return ref
    return None


def identity_reference(refs: Iterable[SheetRef]) -> SheetRef | None:
    """The reference the prompt names as the identity source (``None`` when unclear).

    The face decides, then the hair. One function on purpose: the wording ("the
    identity comes from <Picture 1>") and the face-blur decision have to agree, or the
    blur would take the face out of the very reference the prompt points at.
    """
    candidates = [ref for ref in refs if ref.kind in ("picture", "video")]
    for attribute in ("face", "hair"):
        for ref in candidates:
            if attribute in reference_attributes(ref.role):
                return ref
    return None


def attribution_lines(
    spec: SheetSpec,
    cell: SheetCell,
    *,
    refs: list[SheetRef] | None = None,
    hidden: Iterable[str] | None = None,
) -> list[str]:
    """Per-picture ownership, spelled out for THIS cell.

    H3 conditions on every reference at once, so a prompt that only says "keep the
    person as shown in <Picture 1>, <Picture 2>" invites a blend: the outfit of the
    face picture leaks into a body cell, the hair bow of the clothing picture into a
    face cell. Naming the owner of each attribute AND forbidding the other pictures
    from supplying it is the cheap, deterministic lever against that.

    Wording follows the ref2va prompts that behave (see the pack's character-replace
    docs): ownership is exclusive ("Take the face and the hair only from
    ``<Picture 1>``."), and a reference demoted to carrying something other than
    likeness is told outright that the person visible in it is not the identity and
    its face must not be copied. That last sentence is the one that stopped an outfit
    photo lending its model's face to a full-body cell - telling the model which
    picture owns the face is not enough, because a complete second person is a
    complete second identity.

    ``refs`` is the set this cell will actually be sent (see :func:`cell_references`);
    only those are named, so the prompt can never talk about a picture the run did not
    wire.

    ``hidden`` defaults to what THIS cell's framing cannot show. A prompt that covers
    several framings at once (the draft pass) passes what NONE of them can show, so an
    attribute one panel does display is not quietly dropped from the whole prompt.
    """
    source = refs if refs is not None else spec.refs
    refs = [ref for ref in source if ref.enabled and ref.kind in ("picture", "video")]
    if not refs:
        return []

    supplied: dict[str, list[SheetRef]] = {}
    for ref in refs:
        for attribute in reference_attributes(ref.role):
            supplied.setdefault(attribute, []).append(ref)

    hidden = set(attributes_hidden_by(cell.view)) if hidden is None else set(hidden)

    # Group by owner: one picture per attribute reads as an instruction, a list of
    # "X from P1, Y from P1, Z from P1" reads as noise.
    owner_of: dict[str, list[str]] = {}
    shared: list[str] = []
    for attribute, label in ATTRIBUTE_LABELS.items():
        owners = supplied.get(attribute)
        if not owners or attribute in hidden:
            continue
        if len(owners) == 1:
            owner_of.setdefault(owners[0].tag, []).append(label)
        else:
            shared.append(f"{label} to {_join([ref.tag for ref in owners])}")

    many = len(refs) > 1
    lines: list[str] = []
    identity = identity_reference(refs) or refs[0]
    if many:
        lines.append(
            f"The same person in every image - the identity comes from {identity.tag} "
            "and from no other reference."
        )

    for tag, labels in owner_of.items():
        # "only from" is the exclusive form; with a single reference there is nothing
        # to be exclusive against, so it stays the plain assignment.
        if many:
            lines.append(f"Take {_join(labels)} only from {tag}.")
        else:
            lines.append(f"Use {tag} for {_join(labels)}.")
    if shared:
        lines.append(f"Match {_join(shared)}.")

    # An attribute exactly one picture owns is a prohibition for every other picture:
    # that is what stops the outfit arriving from the face picture.
    likeness_owners = {
        ref.tag for ref in refs if reference_attributes(ref.role) & set(LIKENESS_ATTRIBUTES)
    }
    if many:
        for ref in refs:
            forbidden = sorted(
                {
                    label
                    for tag, labels in owner_of.items()
                    if tag != ref.tag
                    for label in labels
                }
            )
            claimed = reference_attributes(ref.role)
            parts: list[str] = []
            if forbidden:
                parts.append(f"must not change {_join(forbidden)}")
            # Only for a reference the prompt itself demoted to a non-likeness job,
            # and only when some other reference does own the likeness: a role nobody
            # can read must never be told it is "not the identity", and a pair where
            # no picture claims the face keeps the plain prohibitions.
            if claimed and likeness_owners and ref.tag not in likeness_owners:
                parts.append(_LIKENESS_BAN)
            if parts:
                lines.append(f"{ref.tag} " + ", and ".join(parts) + ".")

    clothing_owners = supplied.get("clothing")
    if clothing_owners and "clothing" not in hidden:
        lines.append(
            "Wear the clothing exactly as in the reference: the same garment, fully "
            "dressed - nothing removed, opened, shortened or swapped for another top."
        )
        # The outfit leak in the other direction: the identity picture is usually a whole
        # person wearing something, and a reference has no per-picture weight - so the
        # sheet kept coming out in the CLOTHES OF THE FACE PICTURE even with "the clothing
        # comes only from <Picture 2>" in the prompt. Naming the picture that must be
        # REPLACED is the missing half of that instruction.
        if len(refs) > 1 and len(clothing_owners) == 1 and clothing_owners[0] is not identity:
            lines.append(
                f"The person in {identity.tag} is wearing something else: that outfit is "
                f"replaced. The clothing of this image is the garment worn by the person in "
                f"{clothing_owners[0].tag}, worn exactly as it is there - do not carry over the "
                f"neckline, the cut, the length, the fabric or the colours of what the person "
                f"in {identity.tag} is wearing, and do not mix the two garments."
            )
    if "hair" in supplied and "hair" not in hidden:
        lines.append("Keep the hair exactly as in the reference: no added headwear or extra accessories.")
    if many:
        lines.append(
            "Reference rule: the references are static and only supply what is listed "
            "above. Never copy their pose, framing, camera angle, lighting or "
            "background - the pose, expression and framing of this image come from its "
            "own instructions."
        )
    return lines


def identity_reminder(
    spec: SheetSpec,
    cell: SheetCell,
    *,
    refs: list[SheetRef] | None = None,
) -> str:
    """The identity sentence repeated at the END of a cell prompt (``""`` if none).

    Where a line sits in a prompt changes how much it steers, so the last sentence
    before the sampler gets the identity restated: which reference owns the likeness
    attributes and that they are not to be blended. Only raised for a cell that
    receives more than one reference - with a single reference there is nothing to
    blend and the closing line would just be noise.
    """
    source = refs if refs is not None else spec.refs
    refs = [ref for ref in source if ref.enabled and ref.kind in ("picture", "video")]
    if len(refs) < 2:
        return ""
    identity = identity_reference(refs)
    if identity is None:
        return ""
    owned = reference_attributes(identity.role)
    labels = [
        ATTRIBUTE_LABELS[attribute]
        for attribute in LIKENESS_ATTRIBUTES
        if attribute in owned
    ]
    if not labels:
        return ""
    return (
        f"Identity: {_join(labels)} in this image come from {identity.tag} and from no "
        "other reference - do not blend them with the face of another reference."
    )


def cell_references(
    spec: SheetSpec,
    cell: SheetCell,
    *,
    scope: str = DEFAULT_REF_SCOPE,
) -> list[SheetRef]:
    """The references THIS cell should receive, renumbered 1..n per kind.

    H3 conditions on every reference it is handed at once, and it has no per-reference
    weight: a prompt can *ask* for the face to come from ``<Picture 1>``, but it cannot
    stop the model taking it from the outfit photo. So a reference whose whole role is
    hidden by this framing - an outfit for a face close-up - is left out of the wiring
    instead of being argued with, and the prompt names only what is wired.

    A reference that claims nothing stays: its purpose is unknown, so dropping it would
    be a silent change. If the filter would drop everything, the first enabled
    reference is kept so the person is still conditioned. ``scope="every cell"``
    turns the filter off and hands every enabled reference to every cell.

    A cell that names its own face reference (``cell.face_ref``, the panel's drag-and-drop)
    puts that reference first and gives it the face attribute, so the panel's prompt points
    at it. See :func:`cell_face_reference`.
    """
    enabled = [ref for ref in spec.refs if ref.enabled]
    if str(scope or "").strip().lower() == "every cell":
        return enabled
    hidden = set(attributes_hidden_by(cell.view))
    kept: list[SheetRef] = []
    for ref in enabled:
        claimed = reference_attributes(ref.role)
        if claimed and claimed <= hidden:
            continue
        kept.append(ref)
    if not kept:
        kept = enabled[:1]
    # The cell's OWN face reference - a tile dropped on this panel - leads the list and is given
    # the face attribute if its role did not already claim it. H3 has no per-reference weight, so
    # "the likeness in THIS panel comes from that picture" is said by making it <Picture 1> and by
    # letting the lines that name the identity owner (attribution, the closing reminder, the blur
    # decision) find it. An explicit drop also outranks the framing filter: asking for that picture
    # in this panel is a decision, not something to be quietly dropped because a face view cannot
    # show a garment.
    face = cell_face_reference(cell, enabled)
    if face is not None:
        role = str(face.role or "").strip()
        if "face" not in reference_attributes(role):
            role = f"{role}, face".strip(" ,") if role else "face"
        face = replace(face, role=role)
        kept = [face] + [ref for ref in kept if ref.file != face.file]

    counters: dict[str, int] = {}
    out: list[SheetRef] = []
    for ref in kept:
        index = counters.get(ref.kind, 0)
        counters[ref.kind] = index + 1
        # A copy: the run's own numbering (and the tile badges) stay untouched.
        out.append(ref if ref.index == index else replace(ref, index=index))
    return out


def continuity_settle(frames: int, guide: int) -> int:
    """How many trailing frames of a CONTINUING clip are the settled pose.

    A continuing clip has three parts: the hand-over (the previous cell's tail), the
    move to this cell's own pose, and the settled hold at the end. Measured on a real
    sheet (22 frames, 5-frame hand-over, a 90 degree turn): frames 0-7 are still the old
    pose, the turn lands at frame 8, and everything after holds. ``frame_sharpness``
    meanwhile ranks the *early* frames highest, because the hand-over is the sharpest
    part of the clip - so ranking the whole clip picks the pose the previous cell already
    had. Restricting the ranking to this window is what makes a chained cell show its own
    view.

    Two hand-overs wide, and never less than a third of the clip: the move needs room to
    land, and a very short clip has no settled part to speak of anyway.
    """
    total = max(0, int(frames or 0))
    return max(2 * max(0, int(guide or 0)), total // 3)


def framing_distance(view: Any) -> str:
    """How far the camera is for a view: ``close`` / ``medium`` / ``full``.

    Unknown views answer ``""``, which never matches another cell, so continuation's
    auto mode treats them as independent rather than guessing.
    """
    return FRAMING_DISTANCES.get(str(view or "").strip().lower(), "")


def continuation_keeps_scale(previous_view: Any, view: Any) -> bool:
    """May ``auto`` hand a cell over from a cell with ``previous_view``?

    The hand-over carries the previous cell's SCALE, so chaining a full body after a chest-up
    cell lands mid-zoom with the feet cut off. That is the whole rule: the camera DISTANCE has
    to match.

    A different ANGLE at the same distance is allowed on purpose - it is how the turnarounds
    animate: the clip spends its first frames turning and settles by roughly frame 8 of 22,
    which is why the frame picker only ranks the settled tail. Three chained turnarounds
    rendered exactly that way (one with two face references plus an outfit reference).

    What an angle-changing chain does need is a reference the model can re-pose the BODY from;
    every chained turnaround that worked had a clothing/body reference, and the one that came
    back frontal had a single face/hair/skin bust. :func:`continuity_plan` WARNS about that
    combination (see :func:`reference_supplies_outfit`) instead of changing the plan quietly:
    the behaviour is the user's to keep. ``on`` bypasses this rule in any case.
    """
    previous = framing_distance(previous_view)
    mine = framing_distance(view)
    return bool(previous) and previous == mine


def reference_supplies_outfit(refs: Sequence[SheetRef]) -> bool:
    """Does one of these references carry the body an angle change has to re-pose?

    Deliberately about CLOTHING, not the ``body`` bucket: "face, hair, skin" maps to ``body``
    through *skin* (skin tone), and that is exactly the reference set that failed. An outfit
    picture - "body and clothes", "body and bikini", "Dress, clothing" - is what the working
    chained turnarounds had.
    """
    return any("clothing" in reference_attributes(ref.role) for ref in refs)


def continuity_plan(
    spec: SheetSpec,
    *,
    warnings: list[str] | None = None,
) -> dict[str, int]:
    """``{cell id: guide frames}`` for one sheet - ``0`` means the cell is independent.

    This is the single source of truth for continuation, because three places have to
    agree: the graph builder (does it wire a guide?), the frame picker (must it skip the
    hand-over frames?) and the report. Rules, all of them cheap to state and cheap to
    test:

    * The **first** cell never continues - there is no previous cell to continue from.
    * A cell continues when its own ``continuity`` says ``on``, or when it says
      ``inherit`` and the sheet's render setting is ``on``. ``off`` beats the sheet.
    * ``auto`` - from the cell or the sheet - continues only when the previous enabled
      cell has the SAME camera distance (:func:`framing_distance`) **and the same view**.
      The hand-over carries the previous cell's scale, so chaining a chest-up cell after a
      face close-up just keeps the close-up, and chaining a full body after a chest-up cell
      lands mid-zoom with the feet cut off - that is the distance half. The other half is
      the ANGLE, and it was measured the hard way: chaining a profile cell after a frontal
      one renders frontal again. H3 resolves a hand-over by keeping what it was handed, so
      the five frames of the previous cell win over a prompt that asks the subject to turn,
      and a 90-degree walk of views comes back as five frontal cells. Same view, different
      pose or expression (front -> a-pose, front -> front-smile) is what ``auto`` is for.
      Use ``on`` when a genuine continuous turn is wanted, which still chains everything and
      says so in the report.
    * ``on`` continues regardless, and says so when it crosses a framing change.
    * The hand-over is :data:`CONTINUITY_FRAMES` frames of the previous cell's render.
    * A cell whose *own* length is not larger than the hand-over cannot continue: the
      guide would fill the whole clip and the cell would be a copy of its predecessor.
      That is reported instead of rendered.
    """
    plan: dict[str, int] = {}
    cells = spec.enabled_cells
    sheet_mode = str(spec.render.continuity or DEFAULT_CONTINUITY).strip().lower()
    if sheet_mode not in CONTINUITY_MODES:
        sheet_mode = DEFAULT_CONTINUITY
    previous_frames = 0
    previous_cell: SheetCell | None = None
    for position, cell in enumerate(cells):
        guide = 0
        mode = str(cell.continuity or DEFAULT_CELL_CONTINUITY).strip().lower()
        if mode not in CONTINUITY_CELL_MODES:
            mode = DEFAULT_CELL_CONTINUITY
        if mode == "inherit":
            mode = sheet_mode
        wants = mode in ("on", "auto")
        if wants and position == 0:
            note = f"cell {cell.id}: continuation has no effect on the first cell."
            if warnings is not None:
                warnings.append(note)
        if wants and mode == "auto" and position > 0:
            if previous_cell is None or not continuation_keeps_scale(
                previous_cell.view, cell.view
            ):
                wants = False
            elif (warnings is not None
                  and str(previous_cell.view or "").strip().lower()
                  != str(cell.view or "").strip().lower()):
                # The chain crosses an angle, so this cell is re-posing the body: say so when
                # the references it receives cannot help with that. The plan is left alone.
                # (`ref_scope` is a node widget, not part of the payload: the default is what
                # every other reader of a plan assumes, and a full-body view hides nothing.)
                wired = cell_references(spec, cell, scope=DEFAULT_REF_SCOPE)
                if not reference_supplies_outfit(wired):
                    warnings.append(
                        f"cell {cell.id}: continues from a different angle "
                        f"({previous_cell.view} -> {cell.view}) and no reference of its own "
                        "supplies the outfit or the body - the hand-over keeps the angle it "
                        "was handed, so this cell can come back facing the previous one's way "
                        "(a turnaround with one face/hair/skin reference did). Add a picture "
                        "whose role names the body or the outfit, or set this cell's "
                        "continuation to off."
                    )
        if wants and mode == "on" and position > 0 and previous_cell is not None:
            mine = framing_distance(cell.view)
            theirs = framing_distance(previous_cell.view)
            if mine != theirs:
                note = (
                    f"cell {cell.id}: continuation is forced across a framing change "
                    f"({previous_cell.view} -> {cell.view}) - the hand-over carries the "
                    "previous camera distance, so the new framing may not arrive. Use "
                    "'cont: auto' or 'cont: no' for this cell, or render it on its own."
                )
                if warnings is not None:
                    warnings.append(note)
        if wants and position > 0:
            guide = min(CONTINUITY_FRAMES, int(previous_frames or 0))
            if guide <= 0:
                guide = 0
            elif int(cell.frames) <= guide:
                note = (
                    f"cell {cell.id}: continuation skipped - the {guide}-frame hand-over "
                    f"would fill its whole {int(cell.frames)}-frame clip."
                )
                if warnings is not None:
                    warnings.append(note)
                guide = 0
        plan[cell.id] = guide
        previous_frames = int(cell.frames)
        previous_cell = cell
    return plan


def cell_face_slots(spec: SheetSpec) -> set[tuple[str, int]]:
    """``{(kind, slot)}`` for every reference a CELL names as its face source.

    A panel can take its likeness from a picture the run-wide rule would have blurred (the
    outfit photo, for one panel). The prompt can say "the face comes from <Picture 2>" but the
    pixels decide: a blurred copy of that picture cannot supply a face, so the panelled choice
    protects it from ``auto`` - the same protection the run-wide identity source gets, and for
    the same reason (see :func:`blur_face_decisions`).
    """
    slots: set[tuple[str, int]] = set()
    enabled = [ref for ref in spec.refs if ref.enabled]
    for cell in getattr(spec, "enabled_cells", []) or []:
        ref = cell_face_reference(cell, enabled)
        if ref is None:
            continue
        slots.add((ref.kind, ref.source if ref.source >= 0 else ref.index))
    return slots


def blur_face_decisions(spec: SheetSpec) -> dict[tuple[str, int], str]:
    """``{(kind, source slot): "blur" | "mute" | "keep" | "unsupported"}`` for the whole run.

    Run-wide on purpose. A reference is loaded once - one loader node per source slot,
    shared by every cell - so the clean copy is one file for the sheet, not a decision
    per framing.

    ``auto`` (the default) blurs a picture or a clip that is NOT the run's identity source, and
    only when some other reference does claim the likeness. That is exactly the failure
    this exists for: an outfit photo that is a whole second person, whose face the model
    copies into every full-body cell - the prompt can forbid it, but a face that is in
    the pixels is a face the model can use. A reference whose role says nothing is left
    alone, because blurring the only face in the run is not recoverable. A clip that IS the
    identity source is protected by the same rule, and it matters more there: an H3 run
    whose motion comes from a clip usually takes its likeness from that clip.

    **A hand-painted area blurs whatever the mode says**: the mode chooses whether faces
    are *detected*, the painting is the user pointing at pixels. So
    ``off`` + painting means "only what I painted", and ``auto``/``on`` + painting means
    the painting in addition to the detected faces.
    """
    enabled = [ref for ref in spec.refs if ref.enabled]
    identity = identity_reference(enabled)
    identity_slot = (
        (identity.kind, identity.source if identity.source >= 0 else identity.index)
        if identity is not None
        else None
    )
    # A panel's own face source is protected exactly like the run-wide one: the two are the same
    # promise ("this reference IS the likeness here"), and a blurred copy cannot keep it.
    protected = cell_face_slots(spec)
    if identity_slot is not None:
        protected.add(identity_slot)
    decisions: dict[tuple[str, int], str] = {}
    for ref in enabled:
        slot = (ref.kind, ref.source if ref.source >= 0 else ref.index)
        painted = has_blur_paint(ref)
        if ref.kind == "audio":
            # A voice has no pixels, so the removal is the whole sound: the decision is
            # "mute", there is nothing to detect, and painting one is unsupported rather than
            # silently ignored.
            #
            # "auto" KEEPS a sound, unlike a picture. A face in a photo leaks an identity that
            # nobody asked for, which is why the rule is on by default there; a voice
            # reference is put in the panel deliberately, and it is usually the performance
            # itself. Muting one because another reference owns the face would break the run
            # it was added for - so a voice is muted when the tile says "on", and not before.
            if painted:
                decisions[slot] = "unsupported"
            elif ref.blur_face == "on":
                decisions[slot] = "mute"
            else:
                decisions[slot] = "keep"
        elif painted:
            decisions[slot] = "blur"
        elif ref.blur_face == "off":
            decisions[slot] = "keep"
        elif ref.blur_face == "on":
            decisions[slot] = "blur"
        elif not protected or slot in protected:
            decisions[slot] = "keep"
        elif reference_attributes(ref.role):
            decisions[slot] = "blur"
        else:
            decisions[slot] = "keep"
    return decisions


def blur_detects_faces(spec: SheetSpec) -> dict[tuple[str, int], bool]:
    """``{(kind, source slot): bool}`` - whether faces are *detected* for this reference.

    Separate from :func:`blur_face_decisions` because the two questions are different:
    that one answers "does this reference get a blurred copy at all", this one answers
    "does the face detector run on it". They come apart as soon as a user paints: with
    ``off`` plus a painted area the copy is blurred from the painting alone and the
    detector is not needed (or wanted - it would take out a face the user left alone).
    """
    enabled = [ref for ref in spec.refs if ref.enabled]
    identity = identity_reference(enabled)
    identity_slot = (
        (identity.kind, identity.source if identity.source >= 0 else identity.index)
        if identity is not None
        else None
    )
    detects: dict[tuple[str, int], bool] = {}
    for ref in enabled:
        if ref.kind not in BLUR_KINDS:
            continue
        slot = (ref.kind, ref.source if ref.source >= 0 else ref.index)
        if ref.blur_face == "on":
            detects[slot] = True
        elif ref.blur_face == "off":
            detects[slot] = False
        else:
            detects[slot] = bool(
                identity is not None
                and slot != identity_slot
                and reference_attributes(ref.role)
            )
    return detects


def resolve_background_ref(refs: list[SheetRef], background_ref: Any) -> SheetRef | None:
    """Find the reference a ``"<group>:<slot>"`` backdrop key names, or ``None``.

    ``background_ref`` is written the way the payload stores references (``"pictures:1"``
    = the second picture), and only a picture or a video can supply a backdrop: audio has
    no picture to take a room from. The reference also has to be enabled - pointing the
    backdrop at a muted slot would quietly render a setting the user cannot see.
    """
    key = str(background_ref or "").strip().lower()
    group, _, slot = key.partition(":")
    kind = group.rstrip("s") if group else ""
    if kind not in ("picture", "video") or not slot.strip().isdigit():
        return None
    wanted = int(slot)
    for ref in refs:
        if ref.kind == kind and ref.index == wanted and ref.enabled:
            return ref
    return None


def background_reference(spec: SheetSpec) -> SheetRef | None:
    """The reference a ``reference`` backdrop names, or ``None`` when it is not usable."""
    if spec.render.background != "reference":
        return None
    return resolve_background_ref(spec.refs, spec.render.background_ref)


def reference_background_clause(spec: SheetSpec, reference: SheetRef) -> str:
    """The backdrop clause when a reference supplies the setting.

    ``_NO_SET`` must NOT be part of this one: here the place is exactly what is wanted. What
    is not wanted is the rest of the reference - the people and props around whoever stood
    there - so the subject replaces them, and the backdrop stays as flat as the presets.
    """
    tag = reference.tag
    place = (
        "the same place, room and lighting"
        if reference.kind == "video"
        else "the same setting and backdrop"
    )
    return (
        f"{place} as {tag}: the subject stands where {tag} is, with {tag}'s backdrop and "
        f"lighting unchanged - use {tag} for the BACKGROUND ONLY, nobody and nothing else "
        f"from {tag} appears in shot, no extra people, no props added, {_FLAT}"
    )


def background_clause(spec: SheetSpec) -> str:
    """What the model is told to put behind the figure, as a noun phrase.

    Presets are fixed wording so the sheet stays consistent from cell to cell;
    ``custom`` drops the user's own words into the same frame ("a flat uniform
    backdrop of neutral tan, filling the frame behind the subject with nothing
    else in shot...") - saying only "neutral tan" makes H3 build a tan room.
    ``reference`` builds its wording from the reference it names, and falls back to
    the neutral backdrop when that reference is not there any more.
    """
    choice = spec.render.background
    if choice == "custom":
        text = spec.render.background_custom.strip().rstrip(".")
        if text:
            lower = text if text[0].islower() else text[0].lower() + text[1:]
            return f"a flat uniform backdrop of {lower}, {_FLAT}, {_NO_SET}"
    if choice == "reference":
        reference = background_reference(spec)
        if reference is not None:
            return reference_background_clause(spec, reference)
    option = _BACKGROUND_BY_KEY.get(choice) or _BACKGROUND_BY_KEY["neutral"]
    return option.prompt or _BACKGROUND_BY_KEY["neutral"].prompt


def attributes_hidden_by_all(cells: Iterable[SheetCell]) -> tuple[str, ...]:
    """Attributes NO framing in this run can show - the intersection.

    :func:`attributes_hidden_by` answers for one framing. A prompt that covers several
    framings at once (the draft pass, see :func:`build_sheet_prompt`) may only drop an
    attribute when every panel hides it: naming the outfit because the close-up cannot
    show it would take the outfit away from the full-body panels too.
    """
    panels = [cell for cell in cells]
    if not panels:
        return ()
    hidden = set(attributes_hidden_by(panels[0].view))
    for cell in panels[1:]:
        hidden &= set(attributes_hidden_by(cell.view))
    return tuple(attribute for attribute in ATTRIBUTE_LABELS if attribute in hidden)


#: What to call each column when there are three or fewer of them. The words matter more
#: than the index: "the middle column, upper half" is a place H3 can act on, "column 2 of 3"
#: is arithmetic it has to do.
_COLUMN_WORDS = {1: ("the",), 2: ("the left", "the right"), 3: ("the left", "the middle", "the right")}


def sheet_columns(rects: Sequence[tuple[int, int, int, int]] | None) -> list[list[int]]:
    """Panel indexes grouped into columns, left to right and top to bottom within each.

    Reading the geometry back out of the boxes is what lets the prompt SAY the arrangement
    ("the middle column holds two panels stacked") instead of describing it in pixels and
    hoping: a sheet the model lays out as one row of columns when four of its five panels
    were meant to be stacked is the failure this is here to prevent.
    """
    if not rects:
        return []
    columns: list[list[int]] = []
    for index, rect in enumerate(rects):
        x = int(rect[0])
        for column in columns:
            if abs(int(rects[column[0]][0]) - x) <= 2:
                column.append(index)
                break
        else:
            columns.append([index])
    for column in columns:
        column.sort(key=lambda i: int(rects[i][1]))
    columns.sort(key=lambda column: int(rects[column[0]][0]))
    return columns


def panel_place(columns: Sequence[Sequence[int]], index: int) -> str:
    """Where panel ``index`` sits, in words (``"the middle column, upper half"``).

    ``""`` when the boxes are unknown. "full height" is a claim about the sheet, not about
    the box: a column that holds one panel is that panel's whole height.
    """
    total = len(columns)
    for position, column in enumerate(columns):
        if index not in column:
            continue
        rows = len(column)
        if total == 1 and rows == 1:
            # One panel on the sheet is not a column: it IS the frame.
            return "the whole frame"
        words = _COLUMN_WORDS.get(total)
        where = f"{words[position]} column" if words else f"column {position + 1} of {total}"
        if rows == 1:
            return f"{where}, full height"
        row = column.index(index)
        if rows == 2:
            return f"{where}, {'upper' if row == 0 else 'lower'} half"
        if rows == 3:
            return f"{where}, {('upper', 'middle', 'lower')[row]} third"
        return f"{where}, row {row + 1} of {rows}"


def sheet_arrangement(
    spec: SheetSpec,
    panels: Sequence[SheetCell],
    rects: Sequence[tuple[int, int, int, int]] | None = None,
) -> str:
    """How the panels sit on the canvas, as one clause (``"4 panels in a row..."``)."""
    count = len(panels)
    many = f"{count} panel" + ("" if count == 1 else "s")
    layout = str(spec.layout.layout or "").strip().lower()
    if count == 1 or layout == "turnaround":
        return f"{many} side by side in a single row, left to right"
    if layout == "hero-left":
        columns = sheet_columns(rects)
        if columns:
            shapes: list[str] = []
            for column in columns:
                if len(column) == 1:
                    shapes.append("one tall panel that fills the full height")
                elif len(column) == 2:
                    shapes.append("two panels stacked one above the other")
                else:
                    shapes.append(f"{len(column)} panels stacked one above the other")
            words = _COLUMN_WORDS.get(len(columns))
            named = words is not None
            described = "; ".join(
                (f"{words[i]} column holds {shape}" if named else f"column {i + 1} holds {shape}")
                for i, shape in enumerate(shapes)
            )
            plural = "columns" if len(columns) > 1 else "column"
            return (
                f"{many} in {len(columns)} {plural} of equal width - {described} - "
                "with even gaps between the panels and a clear margin around the sheet"
            )
        return (
            f"{many}: the first is larger and alone on the left, the rest fill a grid "
            "to its right"
        )
    if layout == "grid":
        columns = max(1, int(spec.layout.columns or 1))
        rows = max(1, -(-count // columns))
        if rows > 1:
            return (
                f"{many} in a {columns}-column, {rows}-row grid, filled left to right then "
                "top to bottom"
            )
        return f"{many} in a {columns}-column grid, filled left to right then top to bottom"
    return f"{many} laid out left to right"


def panel_box(rects: Sequence[tuple[int, int, int, int]] | None, position: int) -> str:
    """``" (x=24, y=24, 436x1488)"`` for the panel at ``position`` (1-based), else ""."""
    if not rects or position < 1 or position > len(rects):
        return ""
    x, y, width, height = (int(value) for value in rects[position - 1])
    return f" (x={x}, y={y}, {width}x{height})"


def hair_holds_in_view(view: Any, refs: Iterable[SheetRef] | None = None) -> str:
    """The "the camera does not restyle the hair" sentence, or ``""``.

    Raised for the angles a front-facing picture cannot show (see ``_HAIR_HOLDS_BY_VIEW``) and
    only when a picture or video reference is wired - without one there is no hairstyle being
    held and the sentence would invent a claim about a reference that does not exist.
    """
    angle = _HAIR_HOLDS_BY_VIEW.get(str(view or "").strip().lower())
    if not angle:
        return ""
    wired = [ref for ref in (refs if refs is not None else ()) if ref.enabled
             and ref.kind in ("picture", "video")]
    if not wired:
        return ""
    return (
        "The hairstyle does not change with the camera: the same parting, the same length, the "
        f"same colour and the same style as the reference picture, {angle} - do not give the "
        "subject a different hairstyle because this view is a new angle."
    )


def cell_shot_lines(
    spec: SheetSpec,
    cell: SheetCell,
    *,
    refs: list[SheetRef] | None = None,
) -> list[str]:
    """The framing / pose / expression sentences for ONE cell.

    Split out of :func:`build_cell_prompt` because a draft render asks for every panel at
    once and has to describe each of them in the same words (see
    :func:`build_sheet_prompt`): the view vocabulary keeps one definition, so a draft and
    a cell can never disagree about what "left profile" means.
    """
    lines = [f"{cell.view_option.label}: {cell.view_option.prompt}"]
    holds = hair_holds_in_view(cell.view, refs if refs is not None else spec.refs)
    if holds:
        lines.append(holds)
    # A pose line always belongs on a full-body framing; on a face/portrait cell
    # it is still honoured when the user picked something other than neutral, so
    # unusual combinations (an angry full body, an A-pose close-up) survive.
    if cell.view in POSE_FRAMINGS or cell.pose != "neutral":
        lines.append(cell.pose_option.prompt)
    if cell.view in FACE_FRAMINGS:
        lines.append(cell.expression_option.prompt)
    elif cell.view not in NO_FACE_FRAMINGS and cell.expression != "neutral":
        # A whole-body framing still takes an expression - it steers the face - and a
        # profile only reads one from the side. A framing with no face in it gets
        # nothing: "smiling" in a hands crop just invents a face at the edge of frame.
        # A framing whose own text says there is no eye contact gets the expression
        # without its gaze clause (see expression_reads_in_view).
        scope = " Visible in profile only." if cell.view in PROFILE_FRAMINGS else ""
        lines.append(f"{expression_reads_in_view(cell.expression_option, cell.view)}{scope}")
    return lines


def cell_closing_lines(
    spec: SheetSpec,
    cell: SheetCell,
    *,
    refs: list[SheetRef] | None = None,
) -> list[str]:
    """The lines every prompt ends with: attribution, backdrop, identity restated."""
    source = refs if refs is not None else spec.refs
    wired = [ref for ref in source if ref.enabled and ref.kind in ("picture", "video")]
    lines = list(attribution_lines(spec, cell, refs=refs))
    if not wired:
        # No picture/video reference, so nothing to attribute: say who the person is
        # outright instead of naming references that are not wired in.
        lines.append(
            "Keep the same person across every image: identity, hair, body proportions "
            "and clothing."
        )
    if spec.negative_prompt.strip():
        lines.append(f"Do not include: {spec.negative_prompt.strip()}.")
    lines.append(
        f"Single person against {background_clause(spec)}, no text, no watermark, no extra people."
    )
    # Last line before the sampler: restate which reference owns the likeness. Cheap
    # to add and the position that carries the most weight.
    reminder = identity_reminder(spec, cell, refs=refs)
    if reminder:
        lines.append(reminder)
    return lines


def build_cell_prompt(spec: SheetSpec, cell: SheetCell, *, refs: list[SheetRef] | None = None) -> str:
    """Full prompt for one sheet cell.

    Order matters for H3: the user's global description first (identity), then the
    reference legend, then the framing/pose/expression instructions for THIS cell,
    then any extra text the user typed on the cell. Reference tags are always
    spelled out so the official tag parser matches them. ``refs`` is the subset this
    cell receives (see :func:`cell_references`).
    """
    lines: list[str] = []
    if spec.global_prompt.strip():
        lines.append(spec.global_prompt.strip())

    legend = reference_legend(spec, refs=refs, hidden=attributes_hidden_by(cell.view))
    if legend:
        lines.append(legend)

    body = cell_shot_lines(spec, cell, refs=refs) + cell_closing_lines(spec, cell, refs=refs)
    lines.append(" ".join(body))

    if cell.extra_prompt.strip():
        lines.append(cell.extra_prompt.strip())
    return "\n\n".join(lines)


def build_sheet_prompt(
    spec: SheetSpec,
    cells: Sequence[SheetCell],
    *,
    size: tuple[int, int] | None = None,
    rects: Sequence[tuple[int, int, int, int]] | None = None,
    refs: list[SheetRef] | None = None,
) -> str:
    """The whole sheet as ONE prompt - what the draft pass samples (``draft_sheet.py``).

    A draft render is a single H3 clip that has to contain every panel, so this is the
    cell prompt turned inside out: the blocks that are the same for every cell - the
    global description, the reference legend, the per-reference ownership rules, the
    identity reminder and the negative - stay once, and each cell contributes only the
    sentences that describe its own panel, prefixed with its place on the sheet.

    ``size`` and ``rects`` are the canvas and the per-panel boxes from
    ``sheet_layout.layout_rects``, i.e. the geometry the composite would use: a draft
    describes the same layout the finished sheet will have, so the two can be compared.
    Position and size are stated in pixels and H3 reads them as guidance rather than as a
    hard constraint - which is exactly how they are meant (see the pack README).
    """
    panels = [cell for cell in cells if cell.enabled] or list(cells)
    if not panels:
        return ""
    source = refs if refs is not None else spec.refs
    wired = [ref for ref in source if ref.enabled and ref.kind in ("picture", "video")]
    hidden = attributes_hidden_by_all(panels)

    # H3's own prompt shape (subject_definitions / summary / retention_analysis /
    # detailed_description / overall_soundscape / non_diegetic_music). The model is trained on
    # this structure - the pack's own chains and every MiniMax caption are written in it - so the
    # one sheet render that has to hold five panels at once is asked for in the same language
    # a caption uses, and each block has the job its name says.
    columns = sheet_columns(rects)
    lines: list[str] = []
    if spec.global_prompt.strip():
        lines.append(spec.global_prompt.strip())

    legend = reference_legend(spec, refs=wired or None, hidden=hidden)
    if legend:
        lines.append("subject_definitions:\n" + legend)

    views = []
    for cell in panels:
        label = str(cell.view_option.label or cell.view)
        if label not in views:
            views.append(label)
    lines.append(
        "summary:\n"
        f"[reference generation] Create ONE completed, static character sheet of one person "
        f"showing only these {len(panels)} views at the same time: {', '.join(views)}. "
        "Every panel is the same person, drawn once, in one image."
    )

    retain: list[str] = []
    retain.extend(attribution_lines(spec, panels[0], refs=wired or None, hidden=hidden))
    if not wired:
        retain.append(
            "Keep the same person across every panel: identity, hair, body proportions "
            "and clothing."
        )
    retain.append(
        "Across every panel the same person is shown, in the same light against the "
        "same backdrop; only the view - and the pose or expression named for that panel "
        "- changes."
    )
    reminder = identity_reminder(spec, panels[0], refs=wired or None)
    if reminder:
        retain.append(reminder)
    lines.append("retention_analysis:\n" + " ".join(retain))

    layout = [
        f"A single character reference sheet of one person: "
        f"{sheet_arrangement(spec, panels, rects)}, all on {background_clause(spec)}."
    ]
    if size:
        layout.append(f"The whole image is {int(size[0])}x{int(size[1])} pixels.")
    # H3 renders a clip: without this line the frames can drift into a turn or a pan, which is
    # how a sheet loses panels between frame 0 and frame 4.
    layout.append(
        "The finished sheet is already complete in the first frame and stays completely "
        "unchanged to the last frame - one still image, no motion, no camera movement, no "
        "morphing or transition between the panels."
    )
    for position, cell in enumerate(panels, start=1):
        shot = cell_shot_lines(spec, cell, refs=wired or None)
        if cell.extra_prompt.strip():
            shot.append(cell.extra_prompt.strip())
        # The place in words first ("the middle column, upper half"), then the box in pixels:
        # words are what H3 can act on, the numbers are the check.
        box = panel_box(rects, position).strip()
        where = "; ".join(part for part in (panel_place(columns, position - 1), box[1:-1] if box else "") if part)
        head = f"- Panel {position} of {len(panels)} ({where})" if where else f"- Panel {position} of {len(panels)}"
        layout.append(f"{head}: {' '.join(shot)}")
    drawn = (f"All {len(panels)} panels are drawn" if len(panels) > 1 else "The panel is drawn")
    layout.append(
        f"{drawn}: none is merged with another, dropped, reordered, repeated or scaled up to fill "
        "the sheet, and each panel keeps its own area and framing."
    )
    feet = [panel for panel in panels if panel.view in POSE_FRAMINGS]
    if len(feet) > 1:
        layout.append(
            "Across the full-body panels keep one common figure scale, one common camera "
            "height and one common ground line, so every figure stands on the same baseline "
            "in the same order left to right."
        )
    if spec.negative_prompt.strip():
        layout.append(f"Do not include: {spec.negative_prompt.strip()}.")
    layout.append("No text, no letters, no caption, no panel border, no watermark, no extra people.")
    lines.append("detailed_description:\n" + "\n".join(layout))

    # A sheet is a still image: H3 decodes audio in the same pass, and naming the audio branch
    # keeps it from spending the render on speech or music nobody asked for.
    lines.append(
        "overall_soundscape:\nNone. The sheet is a still image - no speech, no vocalisation, "
        "no ambience, no sound effects."
    )
    lines.append("non_diegetic_music:\nNone.")
    return "\n\n".join(lines)


def cell_matrix(
    *,
    views: Iterable[str],
    poses: Iterable[str] = (),
    expressions: Iterable[str] = (),
    frames: int = DEFAULT_CELL_FRAMES,
) -> list[dict[str, Any]]:
    """Build the cell list for "generate the matrix" (panel convenience + tests).

    Which axis a view expands along comes from :data:`VIEW_VARIANTS`: a whole-body framing
    gets one cell per ticked pose, a framing where the face is the subject gets one per
    ticked expression, and a pure detail crop (the hands, the legs, the back of the head)
    gets a single neutral cell - it looks the same whatever the standing pose or the mouth
    is doing, so multiplying it would only spend renders. The eyes close-up is the
    exception: an expression is exactly what an eye shot is about.
    """
    cells: list[dict[str, Any]] = []
    for view in views:
        view_key = str(view).strip().lower()
        if view_key not in VIEW_KEYS:
            continue
        variants: list[tuple[str, str]] = []
        axis = VIEW_VARIANTS.get(view_key, "single")
        if axis == "pose":
            pose_keys = [str(p).strip().lower() for p in poses] or ["neutral"]
            variants = [(p, "neutral") for p in pose_keys if p in POSE_KEYS]
        elif axis == "expression":
            expression_keys = [str(e).strip().lower() for e in expressions] or ["neutral"]
            variants = [("neutral", e) for e in expression_keys if e in EXPRESSION_KEYS]
        if not variants:
            variants = [("neutral", "neutral")]
        for pose, expression in variants:
            cells.append(
                {
                    "id": f"{view_key}-{pose}-{expression}",
                    "view": view_key,
                    "pose": pose,
                    "expression": expression,
                    "frames": align_h3_frames(frames),
                }
            )
    return cells


__all__ = [
    "BACKGROUNDS",
    "BACKGROUND_KEYS",
    "ATTRIBUTE_LABELS",
    "ATTRIBUTES_HIDDEN_BY_VIEW",
    "attributes_hidden_by",
    "attributes_hidden_by_all",
    "build_cell_prompt",
    "build_sheet_prompt",
    "cell_closing_lines",
    "cell_shot_lines",
    "ONE_PASS_ALIGN",
    "ONE_PASS_FRAMES",
    "ONE_PASS_MAX_PIXELS",
    "ONE_PASS_SHEET_FRAME",
    "RESOLUTION_CHOICES",
    "RESOLUTION_KEYS",
    "RESOLUTION_LABELS",
    "panel_box",
    "sheet_arrangement",
    "POSE_FRAMINGS",
    "FACE_FRAMINGS",
    "PROFILE_FRAMINGS",
    "NO_FACE_FRAMINGS",
    "VIEW_VARIANTS",
    "BLUR_KINDS",
    "BLUR_MODES",
    "BLUR_SCOPES",
    "CELL_ASPECTS",
    "CLIP_FPS",
    "CONTINUITY_CELL_MODES",
    "CONTINUITY_FRAMES",
    "CONTINUITY_MODES",
    "FRAMING_DISTANCES",
    "DEFAULT_ASPECT",
    "DEFAULT_BLUR_MODE",
    "DEFAULT_BLUR_SCOPE",
    "DEFAULT_CELL_ASPECT",
    "DEFAULT_CELL_CONTINUITY",
    "DEFAULT_CONTINUITY",
    "DEFAULT_REF_SCOPE",
    "REF_SCOPES",
    "DEFAULT_CELL_FRAMES",
    "DEFAULT_SHORT_EDGE",
    "EXPRESSIONS",
    "EXPRESSION_KEYS",
    "NO_EYE_CONTACT_VIEWS",
    "expression_reads_in_view",
    "H3_FRAME_BASE",
    "H3_FRAME_STRIDE",
    "LAYOUTS",
    "MAX_AUDIOS",
    "MAX_CELLS",
    "MAX_CELL_FRAMES",
    "MAX_PICTURES",
    "MAX_VIDEOS",
    "MIN_CELL_FRAMES",
    "PICKS",
    "POSES",
    "POSE_KEYS",
    "SheetCell",
    "SheetLayoutSpec",
    "SheetOption",
    "SheetRef",
    "SheetRenderSpec",
    "SheetSpec",
    "VIEWS",
    "VIEW_KEYS",
    "align_h3_frames",
    "aspect_ratio",
    "attribution_lines",
    "background_clause",
    "blur_detects_faces",
    "blur_face_decisions",
    "BLUR_TOOLS",
    "build_cell_prompt",
    "cell_matrix",
    "cell_references",
    "continuation_keeps_scale",
    "reference_supplies_outfit",
    "continuity_plan",
    "continuity_settle",
    "describe_background",
    "framing_distance",
    "has_blur_paint",
    "identity_reference",
    "identity_reminder",
    "MAX_PAINT_POINTS",
    "MAX_PAINT_STROKES",
    "parse_blur_paint",
    "parse_sheet_spec",
    "reference_legend",
    "role_words",
    "safe_name",
    "unmatched_role_words",
]
