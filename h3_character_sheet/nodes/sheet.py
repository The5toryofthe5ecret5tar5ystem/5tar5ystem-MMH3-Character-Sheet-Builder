# ComfyUI-H3-Character-Sheet - the character sheet node.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""MiniMax H3 Character Sheet Builder.

One node that renders a whole character sheet and returns it. It owns no model
code: it expands into **ComfyUI core MiniMax H3 nodes** (one short render per cell)
and finishes with this pack's own grid node, which picks a frame per cell and
composites the sheet. Everything that makes a *character sheet* special - the cell
matrix, the reference roles, the frame picker, the layout - lives in this pack.

Per cell the expansion is exactly the official reference-to-video chain::

    MiniMaxH3ReferenceToVideo(clip, vae, audio_vae, prompt, ref_image_N...)
        -> conditioning + AV latent
    MiniMaxH3SigmaShift(model)                 -> shifted model
    KSamplerSelect + BasicScheduler(shifted)   -> sampler + sigmas
    BasicGuider(shifted, conditioning)
    RandomNoise(seed) -> SamplerCustomAdvanced -> VAEDecode(video vae) -> frames

then every cell's frames go to ``H3SheetGrid``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import comfy.samplers
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder

from ..face_blur import blur_reference_plan
from ..planner import (
    CELL_GROUP,
    DEFAULT_CELL_SIZE,
    align_cell_size,
    cell_work_items,
    grid_payload,
    reference_plan,
    uses_audio_references,
    work_summary,
)
from ..name_tokens import expand_tokens, has_tokens
from ..preview_stream import EVENT as PREVIEW_EVENT
from ..preview_stream import attach_sheet_preview
from ..sheet_plan import drop_empty_payload_warning, plan_payload
from ..sheet_spec import (
    CELL_ASPECTS,
    CLIP_FPS,
    CONTINUITY_FRAMES,
    CONTINUITY_MODES,
    DEFAULT_CELL_ASPECT,
    DEFAULT_CONTINUITY,
    DEFAULT_REF_SCOPE,
    DEFAULT_STEPS,
    continuity_plan,
    parse_sheet_spec,
)
from ..verbosity import apply_verbose

log = logging.getLogger("H3-Character-Sheet.sheet")

_CATEGORY = "MiniMaxH3/Character Sheet"
_MAX_WIDGET_CELLS = 24

#: Where the exported clips go, under ComfyUI's output directory - the same folder the
#: frames, the picks and the sheet composite live in, so one sheet is one folder.
CLIP_FOLDER = "minimax_sheets"


def build_sheet_graph(
    graph: GraphBuilder,
    *,
    model: Any,
    clip: Any,
    video_vae: Any,
    audio_vae: Any,
    work_items: list[dict[str, Any]],
    refs: dict[str, list[dict[str, Any]]],
    payload: dict[str, Any],
    name: str,
    keep_frames: bool = True,
    shift_video: float = 12.0,
    shift_audio: float = 3.0,
    steps: int = DEFAULT_STEPS,
    sampler_name: str = "res_multistep",
    scheduler: str = "simple",
    export_video: bool = True,
    clip_fps: float = CLIP_FPS,
    comfy_preview: bool = False,
    live_preview: bool = True,
    preview_frames: int = 24,
    preview_fps: float = 12.0,
    node_id: Any = None,
) -> tuple[Any, Any, Any]:
    """Build the expansion; returns the (sheet, cells, report) output links.

    Split out of ``execute`` so the wiring can be asserted in tests without a GPU:
    it only builds graph nodes.
    """
    # Previews, one decision on the model every cell samples through and therefore before the
    # sigma shift: the pack streams its OWN per-step frame to the panel (live_preview, on by
    # default) and mutes ComfyUI's own stream (see preview_stream / preview_silence).
    # `render.comfyPreview: true` keeps ComfyUI's stream as well.
    if live_preview or not comfy_preview:
        model = attach_sheet_preview(
            model,
            mute=not comfy_preview,
            stream=live_preview,
            name=str(name or ""),
            cells_total=len(work_items),
            node_id=node_id,
            max_frames=int(preview_frames),
            fps=float(preview_fps),
            cell_ids=[str(item.get("id") or "") for item in work_items],
        )

    shifted_model = graph.node(
        "MiniMaxH3SigmaShift",
        id="sigma_shift",
        model=model,
        shift_video=float(shift_video),
        shift_audio=float(shift_audio),
    ).out(0)

    # The run's loaders, built once. `all_inputs` is every reference under the run's
    # own numbering; `by_source` maps a slot id of that full set to its node output, so
    # a cell can wire the subset it receives (see sheet_spec.cell_references) under its
    # own 1..n numbering - which is what H3 numbers in the prompt.
    all_inputs: dict[str, Any] = {}
    by_source: dict[str, Any] = {}
    for item in refs.get("pictures", []):
        output = graph.node(
            "LoadImage", id=f"ref_image_{item.get('slot_id') or item['slot']}", image=item["file"]
        ).out(0)
        all_inputs[item["slot"]] = output
        by_source[item["slot_id"]] = output
    for item in refs.get("videos", []):
        video = graph.node(
            "LoadVideo", id=f"ref_video_src_{item.get('slot_id') or item['slot']}", file=item["file"]
        ).out(0)
        components = graph.node(
            "GetVideoComponents", id=f"ref_video_parts_{item.get('slot_id') or item['slot']}", video=video
        )
        all_inputs[item["slot"]] = components.out(0)
        all_inputs[item["audio_slot"]] = components.out(1)
        by_source[item["slot_id"]] = components.out(0)
        by_source[item.get("audio_slot_id") or item["audio_slot"]] = components.out(1)
    for item in refs.get("audios", []):
        output = graph.node(
            "LoadAudio", id=f"ref_audio_{item.get('slot_id') or item['slot']}", audio=item["file"]
        ).out(0)
        all_inputs[item["slot"]] = output
        by_source[item["slot_id"]] = output

    def cell_ref_inputs(cell_plan: dict[str, Any] | None) -> dict[str, Any]:
        """The reference inputs for one cell, taken from its own plan."""
        if not cell_plan:
            return dict(all_inputs)
        wired: dict[str, Any] = {}
        for group in ("pictures", "videos", "audios"):
            for entry in cell_plan.get(group) or []:
                source = entry.get("source_slot_id") or entry.get("slot_id")
                output = by_source.get(source)
                if output is not None:
                    wired[entry["slot"]] = output
                audio_source = entry.get("source_audio_slot_id")
                audio_output = by_source.get(audio_source) if audio_source else None
                if audio_output is not None:
                    wired[entry["audio_slot"]] = audio_output
        return wired

    cell_links: dict[str, Any] = {}
    previous_frames: Any = None
    #: The previous cell's DECODED frames (for the continuation guide) - kept apart
    #: from `previous_frames`, which is the sink link that orders the cells.
    previous_cell_frames: Any = None
    guided_cells: list[str] = []
    for position, item in enumerate(work_items):
        node_id = item["id"] or f"cell{position}"
        # Order gate: cell N's gate cannot run before cell N-1's frames exist, so the
        # executor samples the cells in list order (top to bottom in the Cells tab)
        # instead of its own backwards discovery order.
        gate = graph.node(
            "H3SheetOrderGate",
            id=f"order_gate_{node_id}",
            model=shifted_model,
            **({} if previous_frames is None else {"after": previous_frames}),
        ).out(0)
        conditioning = graph.node(
            "MiniMaxH3ReferenceToVideo",
            id=f"ref2va_{node_id}",
            clip=clip,
            vae=video_vae,
            audio_vae=audio_vae,
            prompt=item["prompt"],
            width=int(item["width"]),
            height=int(item["height"]),
            length=int(item["frames"]),
            ref_image_size=str(item.get("ref_image_size") or "match"),
            **cell_ref_inputs(item.get("ref_plan")),
        )
        # Latent continuation (opt in, off by default): anchor the tail of the previous
        # cell at frame 0 of this one, so this cell continues from it instead of
        # restarting from its own noise - the H3 guide API, the same mechanism the
        # Motion Director uses to hold a room and a light across segments. It is a soft
        # anchor (conditioning, not a splice), and it costs the first `guide` frames of
        # the clip, which re-render the previous tail.
        # `previous_cell_frames` is the PREVIOUS cell's VAEDecode, not a sink: the frames
        # have to be the real pixels the previous cell produced.
        guide = int(item.get("continuity") or 0)
        positive = conditioning.out(0)
        if guide > 0 and previous_cell_frames is not None:
            # ImageFromBatch with a negative index takes the last N frames, and clamps
            # itself if the previous cell rendered fewer frames than planned.
            tail = graph.node(
                "ImageFromBatch",
                id=f"continuity_tail_{node_id}",
                image=previous_cell_frames,
                batch_index=-guide,
                length=guide,
            ).out(0)
            positive = graph.node(
                "MiniMaxH3AddGuide",
                id=f"continuity_guide_{node_id}",
                positive=positive,
                latent=conditioning.out(1),
                vae=video_vae,
                image=tail,
                frame_idx=0,
            ).out(0)
            guided_cells.append(node_id)
        sampler = graph.node(
            "KSamplerSelect", id=f"sampler_{node_id}", sampler_name=str(sampler_name)
        ).out(0)
        sigmas = graph.node(
            "BasicScheduler",
            id=f"sigmas_{node_id}",
            model=gate,
            scheduler=str(scheduler),
            steps=int(steps),
            denoise=1.0,
        ).out(0)
        guider = graph.node(
            "BasicGuider",
            id=f"guider_{node_id}",
            model=gate,
            conditioning=positive,
        ).out(0)
        noise = graph.node(
            "RandomNoise", id=f"noise_{node_id}", noise_seed=int(item["seed"])
        ).out(0)
        sampled = graph.node(
            "SamplerCustomAdvanced",
            id=f"sample_{node_id}",
            noise=noise,
            guider=guider,
            sampler=sampler,
            sigmas=sigmas,
            latent_image=conditioning.out(1),
        )
        frames = graph.node(
            "VAEDecode", id=f"decode_{node_id}", samples=sampled.out(1), vae=video_vae
        ).out(0)
        previous_cell_frames = frames
        # The clip this cell actually generated: its frames plus the audio H3 made with
        # them, muxed into the sheet folder. The sheet composite still comes from the
        # picked frames - this is the take they were picked from, and what a finished
        # edit cuts with. SaveVideo is a core OUTPUT node, so its result is handed to the
        # cell saver: a node nothing consumes would not be worth executing.
        # NB: never name this `clip` - that is the CLIP model parameter, and rebinding it
        # hands the next cell's reference node a video instead of the text encoder.
        cell_clip: Any = None
        if export_video:
            audio = graph.node(
                "VAEDecodeAudio", id=f"audio_{node_id}", samples=sampled.out(1), vae=audio_vae
            ).out(0)
            cell_clip = graph.node(
                "CreateVideo",
                id=f"clip_{node_id}",
                images=frames,
                fps=float(clip_fps),
                audio=audio,
            ).out(0)
            cell_clip = graph.node(
                "SaveVideo",
                id=f"clipfile_{node_id}",
                video=cell_clip,
                filename_prefix=f"{CLIP_FOLDER}/{name}/clips/{node_id}",
                format="mp4",
                codec="h264",
            ).out(0)
        # Save this cell's frames as soon as it finishes, so the panel shows progress
        # during the run instead of staying empty until the whole sheet is done.
        sink = graph.node(
            "H3SheetCellSink",
            id=f"cellsink_{node_id}",
            images=frames,
            sheet_data=json.dumps(payload),
            cell_id=node_id,
            name=str(name),
            keep_frames=bool(keep_frames),
            **({} if cell_clip is None else {"clip": cell_clip}),
        ).out(0)
        cell_links[f"{CELL_GROUP}.cell_{position}"] = sink
        previous_frames = sink

    if guided_cells:
        log.info(
            "Character sheet: latent continuation on %s cell(s): %s "
            "(each continues from the previous cell's last frames)",
            len(guided_cells), ", ".join(guided_cells),
        )

    grid = graph.node(
        "H3SheetGrid",
        id="sheet_grid",
        sheet_data=json.dumps(payload),
        name=str(name),
        keep_frames=bool(keep_frames),
        **cell_links,
    )
    return grid.out(0), grid.out(1), grid.out(2), grid.out(3)


class MiniMaxH3CharacterSheet(io.ComfyNode):
    """Render a character sheet from references plus a cell list."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3CharacterSheet",
            display_name="MiniMax H3 Character Sheet Builder",
            category=_CATEGORY,
            description=(
                "Render a character sheet from up to 9 picture / 3 video / 3 audio "
                "references with roles, across a matrix of views, poses and "
                "expressions, then composite it into one sheet for ref2va workflows."
            ),
            enable_expand=True,
            inputs=[
                io.Model.Input("model", tooltip="MiniMax H3 UNET (UNETLoader)."),
                io.Vae.Input("video_vae", tooltip="MiniMax H3 video VAE."),
                io.Vae.Input("audio_vae", tooltip="MiniMax H3 audio VAE (needed for audio references)."),
                io.Clip.Input("clip", tooltip="CLIPLoader type=minimax (qwen3vl)."),
                io.String.Input(
                    "sheet_data",
                    default="",
                    multiline=True,
                    tooltip=(
                        "Sheet payload authored by the in-node panel: references with "
                        "their roles and the cell list. The panel is the authoring "
                        "surface; leave it empty for a headless run."
                    ),
                ),
                io.String.Input("output_name", default="character_sheet", tooltip=(
                    "Sheet folder and file name under <output>/minimax_sheets. Supports "
                    "%date% (yyyyMMdd_HHmmss), %date:hhmmss% (any yyyy yy MM dd HH hh mm ss "
                    "mix) and %seed%, e.g. character_sheet-%date:hhmmss%. A name without "
                    "placeholders is date-stamped for you, and a run never overwrites an "
                    "earlier sheet - the exports accumulate in the same folder."
                )),
                io.Int.Input(
                    "cell_size",
                    default=DEFAULT_CELL_SIZE,
                    min=256,
                    max=2048,
                    step=32,
                    tooltip=(
                        "Render size (square, snapped to 32px) of one cell. The sheet "
                        "scales it into its slot, so 1024 is plenty for a reference sheet."
                    ),
                ),
                io.Int.Input(
                    "frames_per_cell",
                    default=22,
                    min=5,
                    max=425,
                    step=1,
                    tooltip=(
                        "Frames sampled per cell, snapped up to the H3 17k+5 grid. More "
                        "frames = more choices for the frame picker; 5 is the fastest."
                    ),
                ),
                io.Int.Input(
                    "steps",
                    default=DEFAULT_STEPS,
                    min=1,
                    max=200,
                    tooltip=(
                        "Sampling steps per cell. 8 is what the community TURBO H3 checkpoints "
                        "want for res_multistep/simple (their range is 6-8); a non-turbo "
                        "checkpoint wants 20-30."
                    ),
                ),
                io.Combo.Input(
                    "sampler_name",
                    options=list(comfy.samplers.KSampler.SAMPLERS),
                    default="res_multistep",
                    tooltip="Sampler used for every cell.",
                ),
                io.Combo.Input(
                    "scheduler",
                    options=list(comfy.samplers.KSampler.SCHEDULERS),
                    default="simple",
                    tooltip="Scheduler used for every cell.",
                ),
                io.Int.Input(
                    "seed",
                    default=42,
                    min=0,
                    max=0xFFFFFFFFFFFFFFFF,
                    tooltip="Base seed; each cell gets its own derived seed unless the cell sets one.",
                ),
                io.Float.Input("shift_video", default=12.0, min=0.01, max=100.0, step=0.01, tooltip="MiniMaxH3SigmaShift shift_video."),
                io.Float.Input("shift_audio", default=3.0, min=0.01, max=100.0, step=0.01, tooltip="MiniMaxH3SigmaShift shift_audio."),
                io.Combo.Input(
                    "ref_image_size",
                    options=["match", "max"],
                    default="match",
                    tooltip=(
                        "Reference sizing passed to H3. 'max' uses the 2048px reference "
                        "pipeline (best identity fidelity, several times slower)."
                    ),
                ),
                io.Combo.Input(
                    "sheet_layout",
                    options=["hero-left", "grid", "turnaround", "custom"],
                    default="hero-left",
                    tooltip="hero-left: cell 1 is the hero and the rest fill the grid beside it. custom: use each cell's row/col/span.",
                ),
                io.Int.Input("sheet_columns", default=2, min=1, max=6, step=1, tooltip="Grid columns (on the right of the hero for hero-left)."),
                io.Combo.Input(
                    "sheet_aspect",
                    options=["3:2", "1:1", "4:3", "16:9", "21:9", "2:3", "3:4", "9:16"],
                    default="3:2",
                    tooltip="Sheet aspect ratio (21:9 is ultrawide for a wide strip of cells).",
                ),
                io.Int.Input("sheet_short_edge", default=1536, min=256, max=4096, step=16, tooltip="Sheet short edge in pixels."),
                io.Boolean.Input("sheet_captions", default=True, tooltip="Draw the view/pose/expression caption under each cell."),
                io.String.Input("sheet_background", default="#101014", tooltip="Sheet background colour."),
                io.Combo.Input("sheet_fit", options=["contain", "cover", "stretch"], default="contain", tooltip="How a cell image fills its slot."),
                io.Boolean.Input(
                    "keep_frames",
                    default=True,
                    tooltip="Keep every rendered frame per cell so the sheet can be re-picked or re-laid out with no re-render.",
                ),
                io.Boolean.Input("verbose_logging", default=False, tooltip="Run this pack's loggers at DEBUG for this run."),
                # Added LAST on purpose: widgets_values in a saved workflow are
                # positional, so inserting a widget mid-list silently shifts every
                # value after it (sheet_layout would land in cell_aspect).
                io.Combo.Input(
                    "cell_aspect",
                    options=list(CELL_ASPECTS),
                    default=DEFAULT_CELL_ASPECT,
                    tooltip=(
                        "Shape of one cell - cell_size is its SHORT edge. 9:16 (default) "
                        "fits a standing person, 1:1 for square cells."
                    ),
                ),
                # Also appended last: the reference scope is a render policy, and
                # inserting it mid-list would shift every saved widget value after it.
                io.Combo.Input(
                    "ref_scope",
                    options=["per framing", "every cell"],
                    default=DEFAULT_REF_SCOPE,
                    tooltip=(
                        "Which references each cell is given. H3 conditions on every "
                        "reference at once and has no per-reference weight, so 'per "
                        "framing' leaves out a reference whose whole role is hidden by "
                        "the shot (an outfit photo on a face close-up) - which is what "
                        "stops a close-up borrowing the other picture's face. 'every "
                        "cell' sends them all to every cell."
                    ),
                ),
                # Appended last as well: another render policy, so inserting it mid-list
                # would shift every saved widget value after it.
                io.Combo.Input(
                    "continuity",
                    options=list(CONTINUITY_MODES),
                    default=DEFAULT_CONTINUITY,
                    tooltip=(
                        "Latent continuation between cells. 'off' (default) renders every "
                        "cell from its own noise - consistent character, independent pose. "
                        "'auto' anchors the last "
                        f"{CONTINUITY_FRAMES} frames of the previous cell at the start of "
                        "the next one (H3's guide API) wherever the camera distance already "
                        "matches, so a run of full-body views turns the subject while the "
                        "sheet's framing changes stay crisp. 'on' chains every cell, "
                        "including across a framing change - the hand-over carries the "
                        "previous camera distance, so a full body after a chest-up shot "
                        "lands mid-zoom. Those frames of each cell re-render the previous "
                        "tail. Per-cell continuity overrides this in both directions."
                    ),
                ),
                # Appended last as well (positional widgets_values).
                io.Boolean.Input(
                    "export_video",
                    default=True,
                    tooltip=(
                        "Write each cell's rendered CLIP next to its frames, as "
                        "clips/<cell>_0000N_.mp4 in the sheet folder - the frames plus the "
                        "audio H3 generated with them, at H3's fixed 24 fps. The sheet "
                        "composite is still the deliverable; the clips are the takes it "
                        "was picked from, and what a finished video edit cuts with."
                    ),
                ),
            ],
            hidden=[io.Hidden.unique_id],
            outputs=[
                io.Image.Output(display_name="sheet"),
                io.Image.Output(display_name="cells"),
                io.String.Output(display_name="report"),
                io.String.Output(
                    display_name="sheet_dir",
                    tooltip="Absolute folder the sheet was written to (frames, picks, "
                            "clips, manifest). Wire it into H3 Sheet → RefMod to export "
                            "the sheet as a RefMod bundle, including the generated "
                            "voice of a cell.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        model: Any,
        video_vae: Any,
        audio_vae: Any,
        clip: Any,
        sheet_data: str = "",
        output_name: str = "character_sheet",
        cell_size: int = DEFAULT_CELL_SIZE,
        frames_per_cell: int = 22,
        steps: int = DEFAULT_STEPS,
        sampler_name: str = "res_multistep",
        scheduler: str = "simple",
        seed: int = 42,
        shift_video: float = 12.0,
        shift_audio: float = 3.0,
        ref_image_size: str = "match",
        sheet_layout: str = "hero-left",
        sheet_columns: int = 2,
        sheet_aspect: str = "3:2",
        sheet_short_edge: int = 1536,
        sheet_captions: bool = True,
        sheet_background: str = "#101014",
        sheet_fit: str = "contain",
        keep_frames: bool = True,
        verbose_logging: bool = False,
        cell_aspect: str = DEFAULT_CELL_ASPECT,
        ref_scope: str = DEFAULT_REF_SCOPE,
        continuity: str = DEFAULT_CONTINUITY,
        export_video: bool = True,
    ) -> io.NodeOutput:
        apply_verbose(verbose_logging)
        # A tokenised output name ("%date:hhmmss%") is expanded here, once, so the
        # folder, the sheet file and the report all use the same name for this run.
        sheet_name = expand_tokens(output_name, seed=int(seed)) or "character_sheet"
        if has_tokens(output_name):
            log.info("Character sheet: output name %r -> %r", str(output_name), sheet_name)
        spec = _spec_from_widgets(
            sheet_data,
            {
                "output_name": sheet_name,
                "frames_per_cell": frames_per_cell,
                "seed": seed,
                "sheet_layout": sheet_layout,
                "sheet_columns": sheet_columns,
                "sheet_aspect": sheet_aspect,
                "sheet_short_edge": sheet_short_edge,
                "sheet_captions": sheet_captions,
                "sheet_background": sheet_background,
                "sheet_fit": sheet_fit,
                "cell_aspect": cell_aspect,
                "continuity": continuity,
                "export_video": export_video,
            },
        )
        if uses_audio_references(spec) and audio_vae is None:
            log.warning(
                "Character sheet: audio references are set but no audio VAE is "
                "connected; they will only condition the text encoder."
            )
        # Continuation is resolved once here, so its notes ("cell c4 has only 5 frames,
        # the hand-over would fill it") land in the same warning list the panel shows.
        continuity_plan(spec, warnings=spec.warnings)

        work_items = cell_work_items(
            spec, cell_size=cell_size, ref_image_size=ref_image_size, ref_scope=ref_scope
        )
        if not work_items:
            raise ValueError(
                "Character sheet has no cells. Add cells in the Character Sheet panel "
                "(Views / Poses / Expressions) or pass them in sheet_data."
            )
        refs = reference_plan(spec)
        # Reference hygiene before anything is wired: a picture the prompt demoted to
        # "must not supply a face" is handed over with that face blurred out, so the
        # instruction and the pixels agree. Best effort - a failure keeps the original.
        blur_lines = blur_reference_plan(spec, refs)
        payload = grid_payload(spec, name=sheet_name)
        graph = GraphBuilder()
        sheet, cells, report, sheet_dir = build_sheet_graph(
            graph,
            model=model,
            clip=clip,
            video_vae=video_vae,
            audio_vae=audio_vae,
            work_items=work_items,
            refs=refs,
            payload=payload,
            name=str(sheet_name or spec.name),
            keep_frames=bool(keep_frames),
            shift_video=float(shift_video),
            shift_audio=float(shift_audio),
            steps=int(steps),
            sampler_name=str(sampler_name),
            scheduler=str(scheduler),
            export_video=bool(spec.render.export_video),
            comfy_preview=bool(spec.render.comfy_preview),
            live_preview=bool(spec.render.live_preview),
            preview_frames=int(spec.render.preview_frames),
            preview_fps=float(spec.render.preview_fps),
        )
        for line in work_summary(spec, work_items):
            log.info("Character sheet: %s", line)
        for line in blur_lines:
            log.info("Character sheet: %s", line)
        if blur_lines:
            report = f"{report}\n\n" + "\n".join(blur_lines)
        # Say where to look while it runs: the panel's own preview is the only place a sheet
        # render is visible before it finishes, and both halves are switches.
        preview_lines = []
        if spec.render.live_preview:
            preview_lines.append(
                f"Live preview: on - clips of up to {int(spec.render.preview_frames)} frame(s) "
                f"at {float(spec.render.preview_fps):g}fps to the panel ('{PREVIEW_EVENT}' events), "
                "as much of each cell as the decoder's CPU budget affords."
            )
        else:
            preview_lines.append("Live preview: off (render.livePreview).")
        preview_lines.append(
            "ComfyUI's own preview: kept (render.comfyPreview)." if spec.render.comfy_preview
            else "ComfyUI's own preview: muted - the panel shows the sheet and this stream."
        )
        report = f"{report}\n\n" + "\n".join(preview_lines)
        for line in preview_lines:
            log.info("Character sheet: %s", line)
        return io.NodeOutput(sheet, cells, report, sheet_dir, expand=graph.finalize())


def _spec_from_widgets(sheet_data: Any, widgets: dict[str, Any]):
    """Payload first (references + cells), then the node widgets for the knobs.

    The widgets are the single source of truth for the sheet presentation and the
    render settings, so what is on the node is what runs; the panel authors the
    references, the cells and the output name.
    """
    payload = _payload(sheet_data)
    payload["name"] = str(widgets["output_name"] or payload.get("name") or "character_sheet")
    # frames_per_cell is a FALLBACK for cells without their own length, so it has to
    # be in the payload before parsing; the ticks (panel views/poses/expressions) are
    # what an empty cell list resolves to, and only then does the curated matrix run.
    payload = plan_payload(payload, frames_per_cell=int(widgets["frames_per_cell"]))
    for warning in payload.get("warnings") or []:
        log.info("Character sheet: %s", warning)

    spec = parse_sheet_spec(payload)
    spec.warnings = drop_empty_payload_warning(spec.warnings)
    spec.render.seed = int(widgets["seed"])
    spec.layout.layout = str(widgets["sheet_layout"])
    spec.layout.columns = int(widgets["sheet_columns"])
    spec.layout.aspect = str(widgets["sheet_aspect"])
    spec.layout.short_edge = int(widgets["sheet_short_edge"])
    spec.layout.captions = bool(widgets["sheet_captions"])
    spec.layout.background = str(widgets["sheet_background"])
    spec.layout.fit = str(widgets["sheet_fit"])
    spec.render.cell_aspect = str(widgets.get("cell_aspect") or spec.render.cell_aspect)
    # The widget wins over the payload, exactly like the other render knobs: which
    # cells chain is a render setting, and the node is where it is switched.
    mode = str(widgets.get("continuity") or "").strip().lower()
    if mode in CONTINUITY_MODES:
        spec.render.continuity = mode
    # Clip export is a render policy too: the widget wins over the payload.
    if widgets.get("export_video") is not None:
        spec.render.export_video = bool(widgets["export_video"])
    if len(spec.cells) > _MAX_WIDGET_CELLS:
        spec.cells = spec.cells[:_MAX_WIDGET_CELLS]
    return spec


def _payload(sheet_data: Any) -> dict[str, Any]:
    if isinstance(sheet_data, dict):
        return dict(sheet_data)
    text = str(sheet_data or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid sheet_data JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("sheet_data must be a JSON object.")
    return data


NODE_CLASS_MAPPINGS = {"MiniMaxH3CharacterSheet": MiniMaxH3CharacterSheet}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3CharacterSheet": "MiniMax H3 Character Sheet Builder"
}

__all__ = [
    "MiniMaxH3CharacterSheet",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "align_cell_size",
    "build_sheet_graph",
]
