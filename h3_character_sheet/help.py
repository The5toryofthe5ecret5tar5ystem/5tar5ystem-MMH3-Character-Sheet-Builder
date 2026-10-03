# 5tar5ystem MMH3 Character Sheet Maker - the in-node guide, as data.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The Help tab's content, and a live check of the files the node needs.

Two things live here:

* the **guide** - what this node makes, how to drive it, and what to watch out for. It is
  data, served over the action route like the presets, so the panel never carries a stale
  copy and a test can check every claim that names a file or a node type;
* the **requirements check** - the model files, resolved against the *running* install
  (``folder_paths`` + :func:`face_blur.model_path`). A guide that says "download X" is much
  less useful than one that says "X is in the wrong folder: I looked at
  ``models/text_encoders`` and did not find it". So the Help tab renders ✓/✗ per file, with
  the exact folder to drop it in and a link to where it comes from.

The file names are pinned to what the bundled example workflow actually loads, and a test
compares the two: recommending a file the example does not use would be a documentation bug
that only shows up as a validation error at queue time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("H3-Character-Sheet.help")

#: The project's name (the repo, the README, the node's display name).
PROJECT = "5tar5ystem MMH3 Character Sheet Maker"

#: Where the example workflow lives, relative to the pack, and its name in ComfyUI's list.
EXAMPLE_WORKFLOW = "example_workflows/H3 Character Sheet - 8 view matrix.json"
EXAMPLE_WORKFLOW_TITLE = "H3 Character Sheet - 8 view matrix"

#: ComfyUI's models folder names, as the node's own loaders see them.
DIFFUSION_FOLDER = "diffusion_models"
TEXT_ENCODER_FOLDER = "text_encoders"
VAE_FOLDER = "vae"
FACE_MODEL_FOLDER = "ultralytics/bbox"


@dataclass(frozen=True)
class HelpLink:
    """One thing to click: a download, a repo, a model card."""

    label: str
    url: str
    note: str = ""


@dataclass(frozen=True)
class Requirement:
    """A file the node needs, and how to find out whether it is there."""

    id: str
    label: str
    #: Which loader in the graph takes it (the tooltip the user will see in ComfyUI).
    node: str
    #: ComfyUI models folder, as typed into the folder list ("diffusion_models").
    folder: str
    #: The names that satisfy it (lowercase substrings - versions and quantisation suffixes
    #: change, the stem does not). Empty for the folder-agnostic face model.
    match: tuple[str, ...]
    #: Where the file has to be dropped, spelled out for a human.
    where: str
    what: str
    links: tuple[HelpLink, ...] = ()
    note: str = ""
    #: Python packages that have to be importable in the interpreter running ComfyUI for this
    #: file to be usable at all. The model file on its own is a ✓ next to a feature that
    #: cannot run - which is exactly the kind of half-truth this tab exists to avoid.
    packages: tuple[str, ...] = ()
    #: Resolved with a special branch instead of a folder listing (the face detector has
    #: two accepted layouts, and the pack already knows how to look for it).
    resolve: str = "folder"


@dataclass(frozen=True)
class HelpSection:
    """One block of the guide."""

    id: str
    title: str
    intro: str = ""
    steps: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    links: tuple[HelpLink, ...] = ()
    #: ``files`` renders the live requirements table under this section.
    kind: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "intro": self.intro,
            "steps": list(self.steps),
            "bullets": list(self.bullets),
            "links": [{"label": link.label, "url": link.url, "note": link.note} for link in self.links],
            "kind": self.kind,
        }


# --------------------------------------------------------------------------- #
# the files
# --------------------------------------------------------------------------- #
#: Everything the node loads. The first three are core H3 loaders; the last is the face
#: blur's detector. Names are the real ones (checked against the Hugging Face file lists),
#: and the CLIP/VAE entries are the exact files the bundled example workflow references.
REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        id="unet",
        label="Diffusion model (the H3 checkpoint)",
        node="UNETLoader",
        folder=DIFFUSION_FOLDER,
        match=("10eros", "minimax_h3_ref2va", "minimax_h3_fl2va"),
        where=f"ComfyUI/models/{DIFFUSION_FOLDER}/ (a subfolder such as Minimax/ is fine)",
        what=(
            "The checkpoint that actually samples. This pack is set up around the 10Eros-Max "
            "TURBO hybrids: 8 steps, res_multistep/simple."
        ),
        links=(
            HelpLink(
                "10Eros-Max (TenStrip) - download page",
                "https://huggingface.co/TenStrip/10Eros-Max/tree/main",
                "Take a TURBO beta5 file: the 14GB w4a8 for speed/VRAM, the int8 20GB for "
                "the last bit of quality. The turbo delta is baked in - do NOT also load a "
                "turbo LoRA on top of a TURBO file.",
            ),
            HelpLink(
                "ComfyUI's own H3 repack (fallback)",
                "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models",
                "minimax_h3_ref2va_pruned_int8_convrot.safetensors works too, at ~20 steps.",
            ),
        ),
        note=(
            "Any H3 ref2va checkpoint renders; the presets' 8 steps assume a turbo build. "
            "Stick to 10Eros **beta5**: the author states that beta_3 and beta_4 are corrupted "
            "test versions that were never meant to ship, and model managers still offer them."
        ),
    ),
    Requirement(
        id="clip",
        label="Text encoder (Qwen3-VL)",
        node="CLIPLoader",
        folder=TEXT_ENCODER_FOLDER,
        match=("qwen3vl_32b_minimax_h3",),
        where=f"ComfyUI/models/{TEXT_ENCODER_FOLDER}/",
        what=(
            "CLIPLoader with type **minimax**. The nvfp4_awq build is the small one and is "
            "what the example workflow uses."
        ),
        links=(
            HelpLink(
                "Comfy-Org / MiniMax-H3 - text_encoders",
                "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders",
                "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors (nvfp4) - the int8_convrot and "
                "bf16 builds work the same, they are just bigger.",
            ),
        ),
    ),
    Requirement(
        id="video_vae",
        label="Video VAE",
        node="VAELoader",
        folder=VAE_FOLDER,
        match=("minimax_h3_video_vae",),
        where=f"ComfyUI/models/{VAE_FOLDER}/",
        what="Decodes the clip. The audio VAE cannot stand in for it.",
        links=(
            HelpLink(
                "Comfy-Org / MiniMax-H3 - vae",
                "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
                "minimax_h3_video_vae_fp16.safetensors",
            ),
        ),
    ),
    Requirement(
        id="audio_vae",
        label="Audio VAE",
        node="VAELoader",
        folder=VAE_FOLDER,
        match=("minimax_h3_audio_vae",),
        where=f"ComfyUI/models/{VAE_FOLDER}/",
        what=(
            "Decodes the 32kHz audio H3 generates with the clip - needed whenever a cell "
            "should have sound, and for exporting clips."
        ),
        links=(
            HelpLink(
                "Comfy-Org / MiniMax-H3 - vae",
                "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
                "minimax_h3_audio_vae_fp32.safetensors",
            ),
        ),
    ),
    Requirement(
        id="face_model",
        label="Face detector (only for the face blur)",
        node="(used inside the node)",
        folder=FACE_MODEL_FOLDER,
        match=("face_yolov8m.pt",),
        where=(
            "ComfyUI/models/ultralytics/bbox/face_yolov8m.pt - note this is the models "
            "folder next to ComfyUI itself, which may not be the same root as your "
            "extra_model_paths.yaml entries"
        ),
        what=(
            "A YOLO face model. Everything else about this pack works without it - the blur "
            "just reports \"no face model found\" and leaves your reference alone."
        ),
        packages=("ultralytics", "cv2"),
        note=(
            "Needs the ultralytics package in ComfyUI's OWN python (opencv/cv2 ships with "
            "ComfyUI already): python_embeded/python -m pip install ultralytics - or install "
            "ComfyUI-Impact-Pack, which brings both the package and this file."
        ),
        links=(
            HelpLink(
                "face_yolov8m.pt (Bingsu/adetailer)",
                "https://huggingface.co/Bingsu/adetailer/tree/main",
                "The same file ComfyUI-Impact-Pack's detectors use. Put it in "
                "models/ultralytics/bbox/ (or models/ultralytics/ - both are accepted).",
            ),
            HelpLink(
                "ComfyUI-Impact-Pack",
                "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
                "Installing this brings the file (and the ultralytics package) with it.",
            ),
        ),
        resolve="face_model",
    ),
)


# --------------------------------------------------------------------------- #
# the guide
# --------------------------------------------------------------------------- #
SECTIONS: tuple[HelpSection, ...] = (
    HelpSection(
        id="what",
        title="What this node makes",
        intro=(
            "One node turns reference pictures into a model sheet: it renders a grid of "
            "framed cells (face close-up, portrait, full body front / side / back, poses, "
            "expressions), keeps every frame of each cell, and stitches them into one image "
            "with captions. Each cell can continue the previous one, so a row reads as one "
            "take instead of a set of unrelated frames."
        ),
        bullets=(
            "Every cell is a short H3 clip (5, 22, 39... frames - H3's 17k+5 grid at 24fps), "
            "and the sheet uses the frame you pick from it.",
            "References are named in the prompt by role (@image1 = \"face and hair\"), so one "
            "picture can supply identity while another supplies clothing.",
            "Nothing is rendered until you queue, and re-compositing the sheet after picking "
            "different frames costs no GPU time.",
        ),
    ),
    HelpSection(
        id="quickstart",
        title="Quick start",
        intro="Five minutes from nothing to a sheet.",
        steps=(
            "Put the files from *Files you need* in place - the tab checks them for you and "
            "shows a ✓ or ✗ next to each one.",
            f"Workflow → Browse → **{EXAMPLE_WORKFLOW_TITLE}**: it already wires the H3 "
            "checkpoint, text encoder and both VAEs, and pre-builds an 8-cell matrix. "
            "(Building it by hand: UNETLoader → CLIPLoader (type minimax) → two VAELoaders, "
            "then this node.)",
            "**References** tab: drop 1-9 pictures, then type a role under each one that "
            "says what it supplies (\"face and hair\", \"body and clothes\"). Fill in "
            "*Character* with who this is, and *Suppress* with what must not appear "
            "(text, watermark, logo, extra people).",
            "**Cells** tab: tick the views / poses / expressions you want and press *Build "
            "cells* - or tick nothing and the node renders its default 8-cell matrix. Use "
            "the *Latent continuation* switch here (Auto is usually right).",
            "Want the whole thing in one click? The **Preset** bar at the top has two full "
            "character sheets - *Full Character Sheet - Balanced* (1024px cells, 1536px "
            "sheet) and *... - Fidelity* (2048 / 3840) - each one headshot, portrait, full "
            "body front, 90-degree side and back, neutral pose and expression, on a flat "
            "neutral tan backdrop.",
            "Everything else is in the **Settings** tab: every knob the node has (cell size, "
            "frames, steps, sampler, reference sizing, layout, shape, clip export), three to "
            "a row instead of one per node row. 8 steps is the default - the turbo "
            "checkpoints' own range is 6-8, so raise it only for a non-turbo model.",
            "Queue. Cells finish one at a time; the **Results** tab fills in as they land.",
            "Click any thumbnail to make it that cell's frame, then *Rebuild sheet* - that "
            "only re-composites, no GPU involved.",
        ),
    ),
    HelpSection(
        id="files",
        title="Files you need",
        kind="files",
        intro=(
            "All five are ComfyUI models. The check below reads the running install, so a ✗ "
            "means the file is missing or in a folder ComfyUI does not scan."
        ),
    ),
    HelpSection(
        id="faceblur",
        title="Face blur (the face swap trick)",
        intro=(
            "H3 reads every reference picture at once and has no per-reference weight. A "
            "prompt can ask for \"clothing from picture 2\", but it cannot stop the model "
            "seeing that picture 2 is a different person - and a full-body outfit photo is "
            "a full second identity. Blurring that face out of the pixels is the only fix "
            "that cannot be argued with."
        ),
        bullets=(
            "**Per tile**: the *Blur* button in the bottom-left corner of a picture cycles "
            "auto → on → off. *Auto* blurs a reference whose role does not mention the face.",
            "**How much**: the *Blur area* selector in the References header - face only, "
            "face + hair (default), or the whole head (hair, hats, glasses).",
            "**By hand**: click the tile's preview (the eye), then paint over whatever else "
            "should go - a tattoo, a logo on a shirt, a second person.",
            "**Before you queue**: the preview's *Blurred* button shows the exact copy the "
            "render will wire.",
            "The original file is never modified: blurred copies are written to "
            "``input/h3_character_sheet/derived/`` and cached (by source + settings), so a "
            "re-render does not re-run detection.",
        ),
        links=(
            HelpLink(
                "face_yolov8m.pt",
                "https://huggingface.co/Bingsu/adetailer/tree/main",
                "Download and drop into ComfyUI/models/ultralytics/bbox/ - that file alone is "
                "not enough: the blur also needs the ultralytics package in ComfyUI's python "
                "(python_embeded/python -m pip install ultralytics).",
            ),
        ),
    ),
    HelpSection(
        id="output",
        title="What you get on disk",
        intro="Output → minimax_sheets → <the node's output name>/",
        bullets=(
            "``<name>.png`` - the assembled sheet, with captions and the picked frames.",
            "``cells/<cell>.png`` - one file per chosen frame.",
            "``frames/<cell>/`` - **every** frame of that cell's clip, so you can re-pick "
            "later without rendering again.",
            "``clips/<cell>_0000N_.mp4`` - the cell's clip with the audio H3 made (when "
            "*Export clips* is on), 24fps.",
            "``manifest.json`` / ``picks.json`` / ``report.txt`` - what was rendered, the "
            "seeds, and the warnings (snapped frame counts, missing references...).",
        ),
    ),
    HelpSection(
        id="tips",
        title="Getting a good sheet",
        bullets=(
            "**Continuation**: *Auto* only chains cells that already share a camera "
            "distance. Chaining a full body onto a chest-up keeps the close framing - if a "
            "full body comes back zoomed in, that is what happened.",
            "**One identity picture is enough**; extra pictures are for clothing, angles and "
            "objects. More identity references from different people is the most common way "
            "a sheet goes wrong.",
            "**Frames**: 22 is the sweet spot for a usable still. Below 22 (5 frames is "
            "H3's minimum) the clip is too short to continue from, and the presets turn "
            "continuation off for it.",
            "**Steps**: 8 with a TURBO checkpoint (the presets and the node default), 20-30 "
            "with a plain one. More steps on a turbo model buys nothing.",
            "**Backdrop**: every option in the *Cells* tab is written as flat - no gradient, "
            "no vignette, no shadow - because a backdrop with a falloff makes the sheet look "
            "like N different photos. *Reference image/video* uses one reference's own "
            "setting behind the character (nobody from it is kept); it counts the references "
            "the render wires, so an unchecked tile takes no number.",
            "**10Eros' own advice**: with a TURBO file, do not also load a turbo LoRA, and "
            "skip cache/Spectrum nodes on reference (ref2va) runs - they cost accuracy.",
            "**Check WHICH beta you downloaded**: 10Eros beta_3 and beta_4 are the author's own "
            "\"corrupted test versions\" - beta5 is the first functional one, and old betas are "
            "still sitting in model folders (and in old workflows). The Files section above "
            "lists every matching checkpoint it can see, not just the first.",
            "**Prompt side**: name each reference's job in its role box. The cell prompt is "
            "built from those roles, and the Prompt tab shows the exact text before you "
            "queue.",
            "**Text in frames**: watermarks and logos in the source pictures get learned. "
            "Put them in *Suppress* (\"text, watermark, logo\"), and blur or crop them if "
            "they are burned in.",
            "**The full manual** is this pack's README.md: every knob, the HTTP routes and "
            "the development notes, in long form.",
        ),
    ),
)


def _resolve_names(folder: str) -> list[str]:
    """The file names ComfyUI knows in ``folder`` (never raises, may be empty)."""
    try:
        import folder_paths

        return [str(name) for name in folder_paths.get_filename_list(folder)]
    except Exception:  # noqa: BLE001 - no ComfyUI (tests, standalone import)
        return []


def _resolve_paths(folder: str) -> str:
    """Where ``folder`` actually points, for a message that can be acted on."""
    try:
        import folder_paths

        paths = folder_paths.get_folder_paths(folder)
        return str(paths[0]) if paths else ""
    except Exception:  # noqa: BLE001
        return ""


def _requirement_state(requirement: Requirement) -> tuple[bool, str, str, list[str]]:
    """``(found, what_was_found, where_we_looked, every_match)`` for one requirement.

    Every matching file is reported, not just the first: a model folder can hold several
    generations of the same checkpoint (10Eros beta4 next to beta5, a pruned official build
    next to a community merge), and "found: the beta4 file" is a very different answer from
    "found: the beta5 file".

    Every lookup is guarded: a folder that a custom node registered badly, a broken
    extra_model_paths entry or a ComfyUI that simply is not there must not take the guide
    down with it - a Help tab that raises is worse than one that says "not found".
    """
    if requirement.resolve == "face_model":
        from .face_blur import MODEL_CANDIDATES, model_path

        try:
            found = model_path()
        except Exception as exc:  # noqa: BLE001
            log.warning("Character sheet: face model lookup failed (%s)", exc)
            found = None
        if found is not None:
            return True, str(found), str(Path(found).parent), [str(found)]
        looked = ", ".join("models/" + "/".join(parts) for parts in MODEL_CANDIDATES)
        return False, "", looked, []
    try:
        names = _resolve_names(requirement.folder)
        looked = _resolve_paths(requirement.folder) or requirement.where
    except Exception as exc:  # noqa: BLE001 - a folder listing must never break the guide
        log.warning("Character sheet: could not list %s (%s)", requirement.folder, exc)
        return False, "", requirement.where, []
    matches = [
        name for name in names
        if any(token in name.lower() for token in requirement.match)
    ]
    if matches:
        return True, matches[0], looked, matches
    return False, "", looked, []


def _package_state(package: str) -> bool:
    """Is ``package`` importable in THIS interpreter - the one running ComfyUI?

    ``find_spec`` and not ``import``: the answer is needed while the panel is drawing, and
    importing torch-class dependency trees (ultralytics pulls torch) inside a route handler
    is not worth a ✓. A package that cannot be inspected counts as missing.
    """
    try:
        import importlib.util

        return importlib.util.find_spec(package) is not None
    except Exception as exc:  # noqa: BLE001 - a broken install must not break the guide
        log.warning("Character sheet: could not look up the %s package (%s)", package, exc)
        return False


def check_requirements() -> list[dict[str, Any]]:
    """Every required file, checked against the running install.

    Deliberately forgiving: a ComfyUI that cannot answer (or a test without one) reports
    "not found" rather than raising - the guide has to render either way.

    ``ok`` means **usable**: the file is there AND, where the entry declares packages, they
    are importable. ``file_ok`` keeps the two apart so the row can say "found it, but the
    detector package is missing" instead of a bare ✗.
    """
    out: list[dict[str, Any]] = []
    for requirement in REQUIREMENTS:
        found, name, looked, matches = _requirement_state(requirement)
        packages = [
            {"name": package, "ok": _package_state(package)}
            for package in requirement.packages
        ]
        missing_packages = [item["name"] for item in packages if not item["ok"]]
        out.append(
            {
                "id": requirement.id,
                "label": requirement.label,
                "node": requirement.node,
                "folder": requirement.folder,
                "where": requirement.where,
                "what": requirement.what,
                "note": requirement.note,
                "expect": list(requirement.match),
                "ok": bool(found) and not missing_packages,
                "file_ok": bool(found),
                "found": name,
                "matches": matches[:8],
                "match_count": len(matches),
                "looked": looked,
                "packages": packages,
                "missing_packages": missing_packages,
                "links": [
                    {"label": link.label, "url": link.url, "note": link.note}
                    for link in requirement.links
                ],
            }
        )
    return out


def help_payload() -> dict[str, Any]:
    """The whole Help tab in one answer: the guide plus the live file check."""
    requirements = check_requirements()
    missing = [item["label"] for item in requirements if not item["ok"]]
    missing_packages = sorted(
        {
            name
            for item in requirements
            for name in item.get("missing_packages", [])
        }
    )
    return {
        "project": PROJECT,
        "example": {"file": EXAMPLE_WORKFLOW, "title": EXAMPLE_WORKFLOW_TITLE},
        "sections": [section.to_dict() for section in SECTIONS],
        "requirements": requirements,
        "missing": missing,
        "missing_packages": missing_packages,
        "ready": not missing,
    }


__all__ = [
    "EXAMPLE_WORKFLOW",
    "EXAMPLE_WORKFLOW_TITLE",
    "PROJECT",
    "REQUIREMENTS",
    "SECTIONS",
    "check_requirements",
    "help_payload",
]
