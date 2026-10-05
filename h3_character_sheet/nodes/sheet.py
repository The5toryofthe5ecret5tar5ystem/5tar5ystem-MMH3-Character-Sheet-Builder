# ComfyUI-H3-Character-Sheet - the character sheet node.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""MiniMax H3 Character Sheet Builder.

One node that renders a whole character sheet and returns it. It owns no model code: it expands
into **ComfyUI core MiniMax H3 nodes** and finishes with this pack's own nodes.

Two expansions, and the payload decides which:

* **one-pass (default)** - ONE ``MiniMaxH3ReferenceToVideo`` call whose prompt describes every
  panel, at H3's 5-frame minimum, then ``H3SheetOnePassSink`` keeps the sheet frame and slices the
  panels back out of it. Cheap, and the panels agree by construction; the panels are guidance
  rather than a promise. See ``one_pass.py``.
* **per-cell** (``single_pass`` off) - one short render per cell through this pack's own grid node,
  which picks a frame per cell and composites the sheet. Buys per-cell frames, clips, continuation
  and a sheet that can be re-composited from its parts.

Everything that makes a *character sheet* special - the cell matrix, the reference roles, the frame
picker, the layout, the prompt vocabulary - is shared by both and lives in this pack.

Per cell the per-cell expansion is exactly the official reference-to-video chain::

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
from ..one_pass import one_pass_plan
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
from ..sheet_store import SheetStore
from ..suite import board_segments, suite_boards, suite_lines, suite_manifest
from ..verbosity import apply_verbose

log = logging.getLogger("H3-Character-Sheet.sheet")

_CATEGORY = "MiniMaxH3/Character Sheet"
_MAX_WIDGET_CELLS = 24

#: Where the exported clips go, under ComfyUI's output directory - the same folder the
#: frames, the picks and the sheet composite live in, so one sheet is one folder.
CLIP_FOLDER = "minimax_sheets"

#: The cell id a one-pass render reports on its preview stream. It draws the whole sheet in ONE
#: clip (see ``one_pass``), so there is no real cell to name - ``whole_sheet`` on the stream tells
#: the panel that, and this id is only for the log and the report.
ONE_PASS_CELL_ID = "one-pass"


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
    board: str = "",
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
            board=str(board or ""),
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
        # The board folder, like the sinks: a suite renders several sheets from one queue and each
        # composes into its OWN folder. Without this every board's grid wrote into the run folder and
        # the last one won.
        board=str(board or ""),
        **cell_links,
    )
    return grid.out(0), grid.out(1), grid.out(2), grid.out(3)


def build_one_pass_graph(
    graph: GraphBuilder,
    *,
    model: Any,
    clip: Any,
    video_vae: Any,
    audio_vae: Any,
    plan: dict[str, Any],
    refs: dict[str, list[dict[str, Any]]],
    payload: dict[str, Any],
    name: str,
    board: str = "",
    keep_frames: bool = True,
    shift_video: float = 12.0,
    shift_audio: float = 3.0,
    steps: int = DEFAULT_STEPS,
    sampler_name: str = "res_multistep",
    scheduler: str = "simple",
    seed: int = 42,
    ref_image_size: str = "match",
    node_id: Any = None,
    live_preview: bool = True,
    comfy_preview: bool = False,
    preview_frames: int = 24,
    preview_fps: float = 12.0,
) -> tuple[Any, Any, Any, Any]:
    """The one-pass expansion: ONE H3 render that has to contain the whole sheet.

    One cell's chain - reference-to-video, sigma shift, guider, sampler, decode - with two
    differences: the prompt describes every panel at once (``one_pass.one_pass_plan``) and the
    length is H3's 5-frame minimum. Everything the per-cell pass does per cell is absent because
    there is only one pass: no order gates, no per-cell saver, no clips, no continuation. Returns
    the same four outputs as the per-cell expansion, from the one-pass sink - whose second output
    is the panels sliced back out of the sheet, i.e. exactly what a per-cell run hands over as its
    ``cells`` batch.

    The references are NOT filtered per framing here (``ref_scope`` is a per-cell policy): a
    one-pass sheet shows every panel, so it is wired every reference the sheet has.

    The preview plumbing is the per-cell pass's, unchanged: the pack streams its OWN frames to the
    panel (``live_preview``) and mutes ComfyUI's per-step preview unless ``comfy_preview`` asks for
    it. A one-pass render is the case where that stream matters most - it is one render, so without
    it there is nothing on screen until the whole sheet is done - and it is marked
    ``whole_sheet`` so the panel labels it as the sheet rather than as "cell 1".
    """
    if live_preview or not comfy_preview:
        model = attach_sheet_preview(
            model,
            mute=not comfy_preview,
            stream=live_preview,
            name=str(name or ""),
            cells_total=1,
            node_id=node_id,
            max_frames=int(preview_frames),
            fps=float(preview_fps),
            cell_ids=[ONE_PASS_CELL_ID],
            whole_sheet=True,
        )

    shifted_model = graph.node(
        "MiniMaxH3SigmaShift",
        id="sigma_shift",
        model=model,
        shift_video=float(shift_video),
        shift_audio=float(shift_audio),
    ).out(0)

    inputs: dict[str, Any] = {}
    for item in refs.get("pictures", []):
        inputs[item["slot"]] = graph.node(
            "LoadImage", id=f"ref_image_{item.get('slot_id') or item['slot']}", image=item["file"]
        ).out(0)
    for item in refs.get("videos", []):
        video = graph.node(
            "LoadVideo", id=f"ref_video_src_{item.get('slot_id') or item['slot']}", file=item["file"]
        ).out(0)
        components = graph.node(
            "GetVideoComponents", id=f"ref_video_parts_{item.get('slot_id') or item['slot']}", video=video
        )
        inputs[item["slot"]] = components.out(0)
        inputs[item["audio_slot"]] = components.out(1)
    for item in refs.get("audios", []):
        inputs[item["slot"]] = graph.node(
            "LoadAudio", id=f"ref_audio_{item.get('slot_id') or item['slot']}", audio=item["file"]
        ).out(0)

    conditioning = graph.node(
        "MiniMaxH3ReferenceToVideo",
        id="onepass_ref2va",
        clip=clip,
        vae=video_vae,
        audio_vae=audio_vae,
        prompt=str(plan.get("prompt") or ""),
        width=int(plan["width"]),
        height=int(plan["height"]),
        length=int(plan["frames"]),
        ref_image_size=str(ref_image_size or "match"),
        **inputs,
    )
    sampler = graph.node(
        "KSamplerSelect", id="onepass_sampler", sampler_name=str(sampler_name)
    ).out(0)
    sigmas = graph.node(
        "BasicScheduler",
        id="onepass_sigmas",
        model=shifted_model,
        scheduler=str(scheduler),
        steps=int(steps),
        denoise=1.0,
    ).out(0)
    guider = graph.node(
        "BasicGuider", id="onepass_guider", model=shifted_model, conditioning=conditioning.out(0)
    ).out(0)
    noise = graph.node("RandomNoise", id="onepass_noise", noise_seed=int(seed)).out(0)
    sampled = graph.node(
        "SamplerCustomAdvanced",
        id="onepass_sample",
        noise=noise,
        guider=guider,
        sampler=sampler,
        sigmas=sigmas,
        latent_image=conditioning.out(1),
    )
    frames = graph.node(
        "VAEDecode", id="onepass_decode", samples=sampled.out(1), vae=video_vae
    ).out(0)
    sink = graph.node(
        "H3SheetOnePassSink",
        id="onepass_sink",
        images=frames,
        sheet_data=json.dumps(payload),
        name=str(name),
        board=str(board or ""),
        keep_frames=bool(keep_frames),
    )
    return sink.out(0), sink.out(1), sink.out(2), sink.out(3)


def build_suite_graph(
    *,
    boards: list[Any],
    model: Any,
    clip: Any,
    video_vae: Any,
    audio_vae: Any,
    name: str,
    keep_frames: bool = True,
    shift_video: float = 12.0,
    shift_audio: float = 3.0,
    steps: int = DEFAULT_STEPS,
    sampler_name: str = "res_multistep",
    scheduler: str = "simple",
    cell_size: int | None = None,
    ref_image_size: str = "1024",
    ref_scope: str = "sheet",
    node_id: Any = None,
) -> tuple[dict[str, Any], tuple[Any, Any, Any, Any], list[str]]:
    """Build one graph that renders every board of a suite, each into its own folder.

    Returns ``(expand, hero_outputs, lines)``. Each board is built by the SAME builders a single
    sheet uses - ``build_one_pass_graph`` or ``build_sheet_graph``, whichever the run's mode says -
    in its OWN ``GraphBuilder``, and the finished graphs are merged. Separate builders are what
    keeps the boards from sharing nodes: the ids they mint are prefixed per builder, so four boards
    produce four independent renders rather than four wirings of one.

    The run's quality axis (mode, steps, sampler, seed, resolution, references) is every board's:
    a suite changes which cells render, never how. What does change per board is the cells, the
    arrangement and the folder - so a RefMod export can point at any one of them.
    """
    lines: list[str] = []
    merged: dict[str, Any] = {}
    hero: tuple[Any, Any, Any, Any] | None = None

    # ONE preview wrapper for the whole suite: the wrapper goes on the model every board samples
    # through, so attaching it per board would stack four step clocks on one model. Built here,
    # and the boards are then told not to attach their own (live preview off, ComfyUI's stream
    # kept rather than muted a second time).
    preview_on = bool(boards and boards[0].spec.render.live_preview)
    comfy_preview = bool(boards and boards[0].spec.render.comfy_preview)
    # The boards in render order, with how many sampler calls each makes: the wrapper is what
    # turns that into "board 3 of 4, cell 2/6" on the wire, and the panel follows it.
    segments = board_segments(boards)
    if preview_on or not comfy_preview:
        model = attach_sheet_preview(
            model,
            mute=not comfy_preview,
            stream=preview_on,
            name=str(name or ""),
            cells_total=sum(int(entry.get("calls") or 0) for entry in segments),
            segments=segments,
            node_id=node_id,
            whole_sheet=bool(segments[0]["whole_sheet"]) if segments else True,
        )

    for board in boards:
        spec = board.spec
        refs = reference_plan(spec)
        spec.notes.extend(blur_reference_plan(spec, refs))
        spec.notes.append(
            f"Suite board '{board.id}': {board.label} - {board.cells} cell(s) in the "
            f"{board.layout} layout, rendered into {name}/{board.folder}/."
        )
        payload = grid_payload(spec, name=str(name or spec.name))
        sub = GraphBuilder()
        if spec.render.single_pass:
            outs = build_one_pass_graph(
                sub,
                model=model,
                clip=clip,
                video_vae=video_vae,
                audio_vae=audio_vae,
                plan=one_pass_plan(spec),
                refs=refs,
                payload=payload,
                name=str(name or spec.name),
                board=board.folder,
                keep_frames=bool(keep_frames),
                shift_video=float(shift_video),
                shift_audio=float(shift_audio),
                steps=int(steps),
                sampler_name=str(sampler_name),
                scheduler=str(scheduler),
                seed=int(spec.render.seed),
                ref_image_size=str(ref_image_size),
                live_preview=False,
                comfy_preview=True,
            )
        else:
            work_items = cell_work_items(
                spec, cell_size=cell_size, ref_image_size=ref_image_size, ref_scope=ref_scope
            )
            if not work_items:
                raise ValueError(
                    f"suite board '{board.id}' has no cells; clear it from the suite or give it "
                    "a layout with views."
                )
            outs = build_sheet_graph(
                sub,
                model=model,
                clip=clip,
                video_vae=video_vae,
                audio_vae=audio_vae,
                work_items=work_items,
                refs=refs,
                payload=payload,
                name=str(name or spec.name),
                board=board.folder,
                keep_frames=bool(keep_frames),
                shift_video=float(shift_video),
                shift_audio=float(shift_audio),
                steps=int(steps),
                sampler_name=str(sampler_name),
                scheduler=str(scheduler),
                export_video=bool(spec.render.export_video),
                live_preview=False,
                comfy_preview=True,
            )
        merged.update(sub.finalize())
        if hero is None:
            hero = outs
        lines.append(
            f"Suite board '{board.id}': {board.cells} cell(s), "
            f"{'one render' if spec.render.single_pass else 'per-cell renders'} -> "
            f"{name}/{board.folder}/"
        )
        for line in spec.warnings:
            lines.append(f"  {board.id}: {line}")
        log.info(
            "Character sheet: suite board '%s' - %s cell(s) -> %s/%s/",
            board.id, board.cells, name, board.folder,
        )

    if hero is None:  # pragma: no cover - suite_boards() never returns an empty list
        raise ValueError("suite has no boards to render")
    return merged, hero, lines


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
                        "Shape of one cell - cell_size is its SHORT edge. 3:4 (default, "
                        "768x1024 at a 1024 short edge) fits a standing figure with room "
                        "for the arms; 9:16 is phone-shaped and crops them; 1:1 for square "
                        "cells."
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
                # Appended last as well (positional widgets_values): the mode is a different
                # expansion, not a tweak to the per-cell one.
                io.Boolean.Input(
                    "single_pass",
                    default=True,
                    tooltip=(
                        "ONE-PASS SHEET (default): render the whole sheet from ONE H3 clip - "
                        "one prompt describing every panel, H3's 5-frame minimum, the frame the "
                        "model settles on as the sheet - then slice the panels back out of it at "
                        "the boxes the prompt asked for, so per-view consumers (the RefMod "
                        "export above all) work without a second render. About a twentieth of "
                        "the sampling, and the panels agree by construction: one sampling "
                        "context means identity, light and palette cannot drift between views. "
                        "The price: one shared canvas per panel instead of a full render each, "
                        "no per-cell frame picker, no clips, no continuation, and H3 treats the "
                        "panel positions as guidance - it can reorder, merge or drop panels. "
                        "Turn it OFF for the classic per-cell pass, which is what you want when "
                        "a panel has to be exactly right, when you want each cell's clip, or "
                        "when the sheet is going to be enlarged."
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
        single_pass: bool = True,
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
                "single_pass": single_pass,
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
        if spec.render.single_pass:
            # One pass: there is no previous cell to hand over from and no per-cell clip to
            # encode. Say so, rather than leave two knobs looking like they did something.
            if str(spec.render.continuity or DEFAULT_CONTINUITY).strip().lower() != "off":
                spec.warnings.append(
                    "one-pass sheet ignores continuation: it renders the whole sheet in ONE clip, "
                    "so there is no previous cell to continue from (the knob applies to the "
                    "per-cell pass)."
                )
            if spec.render.export_video:
                spec.notes.append(
                    "one-pass sheet writes no clips - each cell's clip comes from the per-cell "
                    "pass (export clips)."
                )

        if spec.render.suite:
            # A SUITE (see suite.py): several sheets for one character - a hero sheet, an
            # expression board, the detail crops - rendered by one queue, each into its own folder
            # under the run name. This run's own cells and arrangement are ignored on purpose:
            # every board carries its own, and a suite that also rendered "the sheet you had"
            # would be a fifth render nobody asked for.
            boards, suite_warnings = suite_boards(spec)
            spec.warnings.extend(suite_warnings)
            for line in suite_warnings:
                log.warning("Character sheet: %s", line)
            if not boards:
                raise ValueError(
                    "Suite has no renderable board. Pick the boards in the preset "
                    "(render.suite) - each names one of the panel's layout presets."
                )
            expand, (sheet, cells, report, sheet_dir), board_lines = build_suite_graph(
                boards=boards,
                model=model,
                clip=clip,
                video_vae=video_vae,
                audio_vae=audio_vae,
                name=str(sheet_name or spec.name),
                keep_frames=bool(keep_frames),
                shift_video=float(shift_video),
                shift_audio=float(shift_audio),
                steps=int(steps),
                sampler_name=str(sampler_name),
                scheduler=str(scheduler),
                cell_size=int(cell_size) if cell_size else None,
                ref_image_size=str(ref_image_size),
                ref_scope=str(ref_scope),
            )
            # The suite's own record, in the run folder beside the boards: what rendered, where each
            # board landed and how many cells it built. The panel lists the boards as ordinary
            # sheets (each folder is a complete sheet), and this is what says they belong together.
            # It REPLACES the run's manifest and report rather than merging into whatever ran in
            # this folder before: the run folder holds no sheet and no cells of its own (the boards
            # own those), and a manifest that inherited the previous single-sheet run's sheetFile
            # and onePass block described a run that never happened.
            store = SheetStore(str(sheet_name or spec.name)).ensure()
            store.write_report("\n".join(
                [f"H3 Sheet suite: {len(boards)} board(s) from ONE queue - "
                 f"{sum(board.cells for board in boards)} cell(s) in total."]
                + suite_lines(boards, name=store.name)
                + board_lines
            ))
            store.write_manifest(
                {
                    "spec": spec.to_dict(),
                    # The boards own the cells, the sheets and the frames; the run folder is the
                    # record that ties them together. No size either: each board lays its own canvas
                    # out, and its own manifest is where that number belongs.
                    "cells": {},
                    "missing": [],
                    "warnings": list(spec.warnings),
                    "notes": list(spec.notes),
                    "suite": suite_manifest(boards, name=store.name),
                },
                sheet_file="",
            )
            for line in suite_lines(boards, name=store.name) + board_lines:
                log.info("Character sheet: %s", line)
            log.info(
                "Character sheet: suite - %s board(s), %s cell(s) in total; each board is a "
                "complete sheet folder under %s.",
                len(boards), sum(board.cells for board in boards), store.dir,
            )
            return io.NodeOutput(sheet, cells, report, sheet_dir, expand=expand)

        refs = reference_plan(spec)
        # Reference hygiene before anything is wired: a picture the prompt demoted to
        # "must not supply a face" is handed over with that face blurred out, so the
        # instruction and the pixels agree. Best effort - a failure keeps the original.
        blur_lines = blur_reference_plan(spec, refs)

        # What the node knows and the compositor cannot: which references were blurred, and
        # whether the streams are on. Collected BEFORE the payload is serialised, because the
        # grid and the one-pass sink both write report.txt from this payload - assembling a
        # second report here is what used to leave the node's `report` output holding a
        # Python list repr instead of the report.
        preview_lines: list[str] = []
        note_lines: list[str] = list(blur_lines)
        if spec.render.single_pass:
            note_lines.append(
                "One-pass sheet: one H3 render for the whole sheet - one clip, so the panel's live "
                "stream shows the whole sheet being denoised instead of one cell of it."
            )
        # The preview switches mean the same thing in both passes, so they are reported the same
        # way and only the subject differs: one pass streams the sheet, a render streams each cell.
        subject = "the sheet" if spec.render.single_pass else "each cell"
        if spec.render.live_preview:
            preview_lines.append(
                f"Live preview: on - clips of up to {int(spec.render.preview_frames)} frame(s) "
                f"at {float(spec.render.preview_fps):g}fps to the panel ('{PREVIEW_EVENT}' events), "
                f"as much of {subject} as the decoder's CPU budget affords."
            )
        else:
            preview_lines.append("Live preview: off (render.livePreview).")
        preview_lines.append(
            "ComfyUI's own preview: kept (render.comfyPreview)." if spec.render.comfy_preview
            else "ComfyUI's own preview: muted - the panel shows the sheet and this stream."
        )
        note_lines.extend(preview_lines)
        spec.notes.extend(note_lines)
        for line in note_lines:
            log.info("Character sheet: %s", line)

        payload = grid_payload(spec, name=sheet_name)
        graph = GraphBuilder()
        if spec.render.single_pass:
            # The one-pass sheet - the default: the whole sheet from one H3 clip (see one_pass).
            # Built instead of the per-cell expansion, not on top of it - there is nothing
            # per-cell here, which is exactly what makes it cheap. The sink slices the panels back
            # out, so the `cells` output still carries one image per panel.
            plan = one_pass_plan(spec)
            sheet, cells, report, sheet_dir = build_one_pass_graph(
                graph,
                model=model,
                clip=clip,
                video_vae=video_vae,
                audio_vae=audio_vae,
                plan=plan,
                refs=refs,
                payload=payload,
                name=str(sheet_name or spec.name),
                keep_frames=bool(keep_frames),
                shift_video=float(shift_video),
                shift_audio=float(shift_audio),
                steps=int(steps),
                sampler_name=str(sampler_name),
                scheduler=str(scheduler),
                seed=int(spec.render.seed),
                ref_image_size=str(ref_image_size),
                live_preview=bool(spec.render.live_preview),
                comfy_preview=bool(spec.render.comfy_preview),
                preview_frames=int(spec.render.preview_frames),
                preview_fps=float(spec.render.preview_fps),
            )
            log.info(
                "Character sheet: one-pass sheet - %s panel(s) in one %sx%s render, %s frame(s).",
                len(plan.get("panels") or []), plan.get("width"), plan.get("height"),
                plan.get("frames"),
            )
            return io.NodeOutput(sheet, cells, report, sheet_dir, expand=graph.finalize())

        work_items = cell_work_items(
            spec, cell_size=cell_size, ref_image_size=ref_image_size, ref_scope=ref_scope
        )
        if not work_items:
            raise ValueError(
                "Character sheet has no cells. Add cells in the Character Sheet panel "
                "(Views / Poses / Expressions) or pass them in sheet_data."
            )
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
    # Which expansion runs is a render policy as well, so the widget wins here too: the panel
    # writes the knob, and a headless run can say it in sheet_data.
    if widgets.get("single_pass") is not None:
        spec.render.single_pass = bool(widgets["single_pass"])
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
    "build_one_pass_graph",
    "build_sheet_graph",
]
