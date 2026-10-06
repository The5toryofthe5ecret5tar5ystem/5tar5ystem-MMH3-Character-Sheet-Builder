# 5tar5ystem MMH3 Character Sheet Builder - the in-node guide, as data.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The Help tab's content, and a live check of the files the node needs.

Two things live here:

* the **guide** - what this node makes, how to drive it, and what to watch out for. It is
  data, served over the action route like the presets, so the panel never carries a stale
  copy and a test can check every claim that names a file or a node type;
* the **requirements check** - the model files, resolved against the *running* install
  (``folder_paths`` + :func:`face_blur.model_path`). A guide that says "download X" is much
  less useful than one that says "X is in the wrong folder". So the Help tab renders ✓/✗ per
  file, with the exact folder to drop it in and a link to where it comes from - and nothing
  else: which files a given install happens to hold is that install's own business, and a
  checkpoint name that exists on one machine reads as nonsense on every other one.

The file names are pinned to what the bundled example workflow actually loads, and a test
compares the two: recommending a file the example does not use would be a documentation bug
that only shows up as a validation error at queue time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("H3-Character-Sheet.help")

#: The project's name (the repo, the README, the node's display name).
PROJECT = "5tar5ystem MMH3 Character Sheet Builder"

#: Where the example workflow lives, relative to the pack, and its name in ComfyUI's list.
EXAMPLE_WORKFLOW = "example_workflows/5tar5ystem MMH3 Character Sheet Builder.json"
EXAMPLE_WORKFLOW_TITLE = "5tar5ystem MMH3 Character Sheet Builder"

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
                "Take a TURBO build: the 14GB w4a8 for speed/VRAM, the int8 20GB for the last "
                "bit of quality. The turbo delta is baked in - do NOT also load a turbo LoRA "
                "on top of a TURBO file.",
            ),
            HelpLink(
                "ComfyUI's own H3 repack (fallback)",
                "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models",
                "minimax_h3_ref2va_pruned_int8_convrot.safetensors works too, at ~20 steps.",
            ),
        ),
        note=(
            "Any H3 ref2va checkpoint renders. The presets' 8 steps are for a TURBO build - "
            "with a plain checkpoint raise the step count to 20-30. LoRAs belong here too: "
            "wire a Lora Loader between this checkpoint and the node's model input and every "
            "cell of every board renders through it (see the LoRA bullet in *Getting a good "
            "sheet*)."
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
            "While it renders, the panel plays a looping clip of the cell being denoised and "
            "**↻ new seed** re-rolls any single cell - see *While it renders*.",
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
            "neutral tan backdrop. A preset that says which cells it is for **builds them "
            "too**, so choosing one and pressing Queue is the whole job.",
            "Found a combination you like? Press **Save...** next to the preset selector: it "
            "keeps every knob, the backdrop, the blur area and the ticks as a preset of your "
            "own (marked *(custom)*, stored in ComfyUI's user folder, deleted with **Delete** "
            "- which only works on your own, not on the shipped ones).",
            "Everything else is in the **Settings** tab: every knob the node has (cell size, "
            "frames, steps, sampler, reference sizing, layout, shape, clip export), three to "
            "a row instead of one per node row. 8 steps is the default - the turbo "
            "checkpoints' own range is 6-8, so raise it only for a non-turbo model.",
            "Queue. Cells finish one at a time; the **Results** tab fills in as they land.",
            "Click any thumbnail to make it that cell's frame, then *Rebuild sheet* - that "
            "only re-composites, no GPU involved. The click is a **decision**: the row says "
            "*chosen by hand* afterwards, and that frame survives later rebuilds (and a "
            "re-render) until you pick a rule for that cell again in the *Cells* tab. Each "
            "rebuild writes the next dated file, and the status line names it - the previous "
            "sheet is kept, so a sequence of choices is never overwritten.",
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
        id="refmod",
        title="Exporting the sheet as a RefMod (appearance + voice)",
        intro=(
            "A sheet is a multi-view identity board, and that is what a RefMod wants: a "
            "latent that rides H3's own reference path for a fraction of the tokens. "
            "**H3 Sheet → RefMod** writes one bundle holding the picked cells stacked as "
            "appearance, the composited sheet as a second member, and a voice member - "
            "the sheet's **own reference audio**, so the voice in the bundle is the voice "
            "the character was built from."
        ),
        bullets=(
            "**Ready-made**: `example_workflows/5tar5ystem MMH3 Character Sheet Builder + "
            "RefMod.json` is all of this wired for you - one Queue renders the sheet, saves "
            "the PNG and writes the bundle. Open it and drop your references in.",
            "**Needs** ComfyUI-MiniMaxH3Mod (Luisa's RefMod pack) for the two VAE encoders - "
            "*Load H3 RefMods* and *Apply H3 RefMod* live there. Without it the node stops "
            "with the sentence that says where to clone it; nothing else in this pack cares.",
            "**Wire it**: the Builder's *cells* and *sheet* outputs into the node, the same "
            "video_vae the sheet node uses, *sheet_dir* (the Builder's fourth output) so the "
            "sheet's own reference audio and cell clips can supply the voice, and the "
            "audio_vae if you want a voice at all.",
            "*sheet_dir* is a text box on the node rather than a socket, because a name "
            "works there too: drag the Builder's *sheet_dir* output onto the dot on its "
            "left (or right-click it -> *Convert widget to input*) to wire it, or type the "
            "sheet's name (`character_sheet`, or the `%date%` pattern you used) into it.",
            "**Voice**: *voice_cell* is a ladder - `-1` (default) takes the voice from the "
            "sheet's **own reference audio** (the WAV in the Builder's References tab, "
            "recorded in the manifest), else the **soundtracks of its reference videos** "
            "(H3 pairs a reference video with its own soundtrack, so that is the other "
            "voice the sheet heard), else every exported cell clip joined into one "
            "waveform, else a connected *AUDIO*; `0` keeps the sheet out of it (*AUDIO* "
            "only) and `n` forces the nth cell's clip. *voice_seconds* is a ceiling on "
            "what is encoded, not a target.",
            "**Reference videos become a motion member.** *video_frames* frames of each "
            "video in the References tab go into the bundle as `<name>_videos`, taken as "
            "a window of **consecutive** frames (from *video_start*) because that is what "
            "carries movement - stills never can. It is also the most expensive member "
            "per second: rows are latent frames x (h/2) x (w/2), and H3 packs 5 latent "
            "frames per 17 pixel frames, so 13 frames is 2 latent frames (896 rows at "
            "*ref_resolution* 512) and the next real step up is 22 frames (7). 0 turns it "
            "off; the report prints the cost and flags a member that hit *max_tokens*.",
            "**A thin voice is the usual reason a bundle 'does nothing'.** A reference is "
            "worth the rows it occupies, and everything in a bundle is packed into one "
            "sequence the model attends over (the video being generated adds thousands of "
            "rows on top): a 0.95s voice is ~0.5% of that, small enough that an A/B of "
            "*voice 1.0* against *voice 0.0* looks like noise. The report prints each "
            "member's share of the bundle and, when the voice is thin, the *copies* count "
            "on *Load H3 RefMods* that would put it on the map (about 2% is where a "
            "reference starts to compete). A longer reference clip beats every other "
            "knob.",
            "**Full Reference** (default) stores the real encode at *ref_resolution*, so a "
            "face survives - that is the mode a character sheet is for. **Compressed "
            "Reference** pools it to a tiny grid: nearly free to inject, and it carries "
            "concept rather than identity.",
            "**Where it goes**: ``models/refmods/<subfolder>/<name>.safetensors``, the tree "
            "*Load H3 RefMods* lists. That dropdown is built when the page loads, so reload "
            "ComfyUI before looking for the new file.",
            "Tokens are the dial to watch: a full-reference sheet of 5+ cells injects "
            "thousands of them (*max_tokens* caps the total, 0 = uncapped), and every frame "
            "that uses the mod pays for them.",
        ),
    ),
    HelpSection(
        id="render",
        title="While it renders (live preview + new seed)",
        intro=(
            "A sheet takes minutes, so the panel shows the render as it happens instead of "
            "waiting for the first cell to land on disk."
        ),
        bullets=(
            "The **LIVE strip** above the tabs plays a looping clip of the cell being denoised, "
            "with its own counter (`cell 2/5 · step 4/8 · 22-frame loop`). It opens the moment "
            "you queue and closes when the run ends, as the finished sheet takes over in "
            "**Results**.",
            "**↻ new seed** on that strip re-rolls the cell you are looking at: it stops the run, "
            "gives that one cell a new random seed, renders *only* that cell - the others keep "
            "the frames already on disk - and puts the sheet back together from them.",
            "The same button is on every row of the **Results** tab, so a cell you only spotted "
            "later can be re-rolled without touching the rest of the sheet.",
            "Cells the cancelled run had not reached yet are named in the status line "
            "(`hero, side not rendered yet - Run again to fill them in`): a cell only reaches "
            "the folder once it has finished.",
            "The clip is decoded on the CPU, never on the GPU the sampler is using, so it cannot "
            "slow a render or run it out of memory - which is why it is short on a very large "
            "cell (at most 24 frames, and a still when even a few frames would be expensive).",
            "A tiny VAE (`taeh3` in `models/vae_approx/`, the file ComfyUI's own H3 previews "
            "use) makes the clip look like the render; without it the strip falls back to "
            "latent2rgb - blurrier, still looping, nothing to install. Either way the render "
            "itself does not care.",
            "`render.livePreview: false` in the payload turns the strip off for a run.",
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
            "**Your own presets**: *Save...* keeps the settings on the node as a preset you "
            "can re-apply to the next sheet (they live in ``user/default/h3_character_sheet/"
            "presets.json``, so a ComfyUI update or a cleared output folder does not take "
            "them with it). Press it after a good render rather than before - then you keep "
            "the numbers that actually worked.",
            "**Backdrop**: every option in the *Cells* tab is written as flat - no gradient, "
            "no vignette, no shadow - because a backdrop with a falloff makes the sheet look "
            "like N different photos. *Reference image/video* uses one reference's own "
            "setting behind the character (nobody from it is kept); it counts the references "
            "the render wires, so an unchecked tile takes no number.",
            "**10Eros' own advice**: with a TURBO file, do not also load a turbo LoRA, and "
            "skip cache/Spectrum nodes on reference (ref2va) runs - they cost accuracy.",
            "**LoRAs**: wire any LoRA loader - core's *LoraLoaderModelOnly*, rgthree's "
            "*Power Lora Loader*, or a chain of them at different strengths - between the "
            "checkpoint and the node's **model** input. Nothing to switch on: this pack "
            "never loads a model of its own, so the patches on the MODEL you hand it reach "
            "H3's sampler as-is and apply to every cell, and to every board of a suite. "
            "Keep an identity LoRA's strength low (0.4-0.6) when the sheet is also fed an "
            "identity reference - the two otherwise argue about the face.",
            "**Checkpoints**: a model page often carries several numbered builds of the "
            "same hybrid, and each one is a full checkpoint. Take the build the page itself "
            "points at - a saved workflow keeps loading whatever file it was saved with, "
            "whatever step count you set here.",
            "**Prompt side**: name each reference's job in its role box. The words are "
            "read one by one - *face*, *hair*, *eyes*, *glasses*, *clothing* (and its "
            "swimwear/underwear words), *body*, *breasts*, *intimate*, *legwear*, *shoes*, "
            "*accessories*, *voice* - and the picture that is the only claimant of one is "
            "called its **sole source**. Anything else you type rides along as your own "
            "words. The cell prompt is built from those roles, and the Prompt tab shows "
            "the exact text before you queue.",
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


def _requirement_state(requirement: Requirement) -> tuple[bool, str]:
    """``(is_it_there, where_it_belongs)`` for one requirement.

    Deliberately blind to *which* files are present: the folder is reported, the file names
    on this machine are not. A model folder can hold several generations of the same
    checkpoint (a community beta next to the official pruned build), and the Help tab is read
    by whoever installed the pack - naming one disk's contents would be a fact about that
    disk, not an answer to "am I ready to render".

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
            return True, requirement.where
        looked = ", ".join("models/" + "/".join(parts) for parts in MODEL_CANDIDATES)
        return False, looked
    try:
        names = _resolve_names(requirement.folder)
        looked = _resolve_paths(requirement.folder) or requirement.where
    except Exception as exc:  # noqa: BLE001 - a folder listing must never break the guide
        log.warning("Character sheet: could not list %s (%s)", requirement.folder, exc)
        return False, requirement.where
    present = any(
        any(token in name.lower() for token in requirement.match) for name in names
    )
    return present, looked


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
    are importable. ``file_ok`` keeps the two apart so the row can say "the file is in place,
    but the detector package is missing" instead of a bare ✗.
    """
    out: list[dict[str, Any]] = []
    for requirement in REQUIREMENTS:
        present, where_looked = _requirement_state(requirement)
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
                "ok": present and not missing_packages,
                "file_ok": present,
                "looked": where_looked,
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
