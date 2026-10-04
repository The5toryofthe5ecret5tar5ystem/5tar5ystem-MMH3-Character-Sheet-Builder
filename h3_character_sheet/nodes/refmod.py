# ComfyUI-H3-Character-Sheet - RefMod export node.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""H3 Sheet → RefMod: write a sheet (and its voice) as a ComfyUI-MiniMaxH3Mod bundle.

The character sheet is a multi-view identity board, which is exactly what a RefMod
wants: their own ``elf_girl`` mod is four stills of one person stacked
(``source=stack``). This node turns the Builder's picked cells and the composited
sheet into members of one version-5 bundle and adds a voice member whose source is the
sheet's own reference audio (the WAV in the Builder's References tab, recorded in the
manifest), else its exported cell clips joined, else a connected AUDIO - and saves it
to ``models/refmods/<subfolder>/<name>.safetensors``, where ``Load H3 RefMods`` lists
it.

A reference is worth the rows it occupies in the packed sequence the model attends
over, so the report prints each member's share and says which ``copies`` count would
make a thin voice matter; see ``h3_character_sheet/refmod_export.py``. Both VAE encodes
are ComfyUI-MiniMaxH3Mod's own code, and that pack is an optional dependency: without it
this node stops with the clone line instead of failing somewhere deep.
"""

from __future__ import annotations

import logging
from typing import Any

from comfy_api.latest import io

from ..refmod_export import (
    MODES,
    VOICE_AUTO,
    RefModExportError,
    RefModPackMissing,
    export_bundle,
    pack_status,
)

try:  # a preview text bubble is a nice-to-have; the report string is the contract
    from comfy_api.latest import ui as _ui
except Exception:  # noqa: BLE001 - older API surface
    _ui = None

log = logging.getLogger("H3-Character-Sheet.refmod")

_CATEGORY = "MiniMaxH3/Character Sheet"
#: Metadata only (their ``prompt_hint`` merges it with the description), and every
#: value must be one their pack knows.
CONCEPT_TYPES = ("identity", "clothing", "background", "style", "pose_motion", "generic")


class H3SheetRefMod(io.ComfyNode):
    """Export the sheet as a RefMod bundle with appearance and voice members."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3SheetRefMod",
            display_name="H3 Sheet → RefMod",
            category=_CATEGORY,
            description=(
                "Export a character sheet as a ComfyUI-MiniMaxH3Mod (RefMod) bundle: "
                "the picked cell stills as a stacked appearance member, the composited "
                "sheet as a second one, and a voice member from the sheet's own "
                "reference audio, its exported clips, or a connected audio. One file, "
                "written to models/refmods/<subfolder>/<name>.safetensors. Needs the "
                "ComfyUI-MiniMaxH3Mod pack for the encoders."
            ),
            is_output_node=True,
            inputs=[
                io.Vae.Input(
                    "video_vae",
                    tooltip="MiniMax H3 video VAE - the same one the sheet node uses. "
                            "A RefMod is a VAE encode of the references.",
                ),
                io.Vae.Input(
                    "audio_vae",
                    optional=True,
                    tooltip="MiniMax H3 audio VAE, needed for a voice member (their "
                            "encoder refuses the video VAE). Without it the voice is "
                            "skipped and the report says which file to load - the "
                            "appearance members are still exported.",
                ),
                io.Image.Input(
                    "cells",
                    optional=True,
                    tooltip="The Builder's 'cells' output - the picked still of every "
                            "cell, stacked into one appearance member. This is the "
                            "multi-view identity board (how their own elf_girl mod was "
                            "made: four stills, source=stack).",
                ),
                io.Image.Input(
                    "sheet",
                    optional=True,
                    tooltip="The Builder's 'sheet' output - the composited sheet as its "
                            "own member, so the layout authored for ref2va is in the "
                            "bundle too.",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    tooltip="Optional voice clip for a voice member: wire an AUDIO here "
                            "(core Load Audio, a video's own track via GetVideoComponents, "
                            "a TTS node...). Any audio, mono or stereo, resampled to H3's "
                            "32 kHz. It is the voice ladder's LAST choice - the sheet's "
                            "own reference audio or its cell clips win unless "
                            "'voice_cell' is 0. Needs audio_vae; without it this member "
                            "is skipped and the report says so.",
                ),
                io.String.Input(
                    "sheet_dir",
                    display_name="sheet folder or name",
                    default="",
                    optional=True,
                    tooltip="Where to read the sheet's own exported clips from - and "
                            "the manifest that records the reference audio the sheet "
                            "was rendered with (the voice ladder's first choice). This "
                            "is a text box on the node, not a socket: drag the "
                            "Character Sheet Builder's 'sheet_dir' output onto the dot "
                            "on its left to wire it (or right-click it -> 'Convert "
                            "widget to input'), or just type the sheet's name as it "
                            "was rendered here (the Builder's output_name; a %date% "
                            "name resolves to the newest matching run).",
                ),
                io.String.Input(
                    "name",
                    default="character",
                    tooltip="RefMod name and file name. Members are named after it "
                            "(<name>_views, <name>_sheet, <name>_voice...).",
                ),
                io.String.Input(
                    "subfolder",
                    default="character_sheets",
                    optional=True,
                    tooltip="Folder inside models/refmods, for example character_sheets "
                            "or people - the same tree Load H3 RefMods lists.",
                ),
                io.Combo.Input(
                    "mode",
                    options=list(MODES),
                    default="Full Reference",
                    tooltip="Full Reference stores the real VAE encode at ref_resolution "
                            "(identity, MB-sized members - this is what a character sheet "
                            "is for). Compressed Reference pools the latent to a tiny "
                            "grid: near-free to inject, but it carries concept and motion "
                            "rather than a face.",
                ),
                io.Int.Input(
                    "ref_resolution",
                    default=1024,
                    min=256,
                    max=2048,
                    step=64,
                    tooltip="Short edge in px for the appearance encodes (downscale "
                            "only). 1024 matches their identity preset; 512 halves the "
                            "encode cost and the token count.",
                ),
                io.Int.Input(
                    "max_tokens",
                    default=5120,
                    min=0,
                    max=2147483647,
                    step=512,
                    tooltip="Hard cap on the tokens the appearance members inject (0 = "
                            "off). Their recommended performance default is 5120; over "
                            "budget they drop near-duplicate frames, then resample. A "
                            "full-reference sheet of 5+ cells easily exceeds it - raise "
                            "it if you would rather keep every view.",
                ),
                io.Int.Input(
                    "refine_steps",
                    default=0,
                    min=0,
                    max=2000,
                    step=50,
                    tooltip="Compressed Reference only: refinement steps against the "
                            "real encode (0 = plain pooling). Ignored in Full Reference.",
                ),
                io.Combo.Input(
                    "concept_type",
                    options=list(CONCEPT_TYPES),
                    default="identity",
                    tooltip="Metadata: what the appearance members represent. 'identity' "
                            "for a character sheet; their loaders merge it with the "
                            "description into a prompt hint.",
                ),
                io.String.Input(
                    "description",
                    default="",
                    multiline=True,
                    optional=True,
                    tooltip="Optional description stored in the mod (e.g. 'a ginger woman "
                            "with messy hair') - documentation plus prompt hint.",
                ),
                io.Int.Input(
                    "voice_cell",
                    default=VOICE_AUTO,
                    min=-1,
                    max=64,
                    tooltip="-1 = walk the voice ladder: the sheet's own reference audio "
                            "(the file in the Builder's References tab) if the manifest "
                            "has one, else every exported cell clip joined, else the "
                            "connected audio. 0 = no sheet audio, the connected audio "
                            "only. n = force the generated audio of the nth cell "
                            "(~1s - the voice you heard in the panel, but a tiny "
                            "reference).",
                ),
                io.Float.Input(
                    "voice_seconds",
                    default=30.0,
                    min=0.5,
                    max=600.0,
                    step=0.5,
                    tooltip="Ceiling, not a target: the longest slice of audio encoded "
                            "per voice member (a longer clip is truncated, not refused). "
                            "Longer is stronger - a 1s reference is ~0.5% of the rows "
                            "the model attends over. Their recommended 30s / 5120 "
                            "tokens.",
                ),
                io.Boolean.Input(
                    "save",
                    default=True,
                    label_on="save",
                    label_off="don't save",
                    tooltip="Write the bundle into models/refmods/<subfolder>/. Off leaves "
                            "the mods on the 'mods' output for their Apply node.",
                ),
            ],
            outputs=[
                io.Custom("H3_REF_MODS").Output(
                    "mods",
                    tooltip="The bundle's members at strength 1.0 - wire straight into "
                            "their Apply H3 RefMod, or load the saved file later.",
                ),
                io.String.Output("saved_path", display_name="saved path"),
                io.String.Output("report", display_name="report"),
            ],
        )

    @classmethod
    def execute(
        cls,
        video_vae: Any,
        audio_vae: Any = None,
        cells: Any = None,
        sheet: Any = None,
        audio: Any = None,
        sheet_dir: str = "",
        name: str = "character",
        subfolder: str = "character_sheets",
        mode: str = "Full Reference",
        ref_resolution: int = 1024,
        max_tokens: int = 5120,
        refine_steps: int = 0,
        concept_type: str = "identity",
        description: str = "",
        voice_cell: int = VOICE_AUTO,
        voice_seconds: float = 30.0,
        save: bool = True,
    ) -> io.NodeOutput:
        # A first line that tells the truth about the optional dependency: this is the
        # exact sentence the user needs when their export refuses to run.
        log.info("RefMod export: %s", pack_status())
        try:
            result = export_bundle(
                cells=cells,
                sheet=sheet,
                audio=audio,
                video_vae=video_vae,
                audio_vae=audio_vae,
                sheet_dir=sheet_dir,
                name=name,
                subfolder=subfolder,
                mode=mode,
                ref_resolution=ref_resolution,
                max_tokens=max_tokens,
                identity=refine_steps,
                concept_type=concept_type,
                description=description,
                voice_cell=voice_cell,
                voice_max_seconds=voice_seconds,
                save=save,
            )
        except RefModPackMissing as exc:
            # A dependency problem is not a bug in the workflow: say so, plainly.
            raise ValueError(f"H3 Sheet → RefMod: {exc}") from exc
        except RefModExportError as exc:
            raise ValueError(f"H3 Sheet → RefMod: {exc}") from exc
        report = result.report
        lines = [f"Saved: {result.path}" if result.path else "Not saved (save is off)."]
        lines.append(report)
        lines.append("Load it with 'Load H3 RefMods' after a ComfyUI reload (the "
                     "dropdown is built when the page loads).")
        text = "\n".join(lines)
        log.info("RefMod export: %s", text)
        outputs = (result.mods, result.path, text)
        if _ui is None:  # pragma: no cover - the API always has one today
            return io.NodeOutput(*outputs)
        return io.NodeOutput(*outputs, ui=_ui.PreviewText(text))


NODE_CLASS_MAPPINGS = {"H3SheetRefMod": H3SheetRefMod}
NODE_DISPLAY_NAME_MAPPINGS = {"H3SheetRefMod": "H3 Sheet → RefMod"}

__all__ = [
    "H3SheetRefMod",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
