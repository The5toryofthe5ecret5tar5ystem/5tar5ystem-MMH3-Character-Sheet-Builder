# ComfyUI-H3-Character-Sheet - run planning for a sheet.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Turn a sheet spec into the per-cell work ComfyUI has to run.

Pure Python on purpose (no ComfyUI imports): this is where a sheet's cells become
concrete work items - prompt, frame count, seed, render size - and where the
reference files become the autogrow input keys the core MiniMax H3 ReferenceToVideo
node expects. It is unit-tested without a GPU, which is what keeps the graph wiring
in ``nodes/sheet.py`` thin.

Autogrow key shape (verified against core ``comfy_extras/nodes_minimax_h3.py`` and a
real api prompt): the group id and the template id are joined with a dot, so a
reference image is ``ref_images.ref_image_0``. The node's ``execute`` receives those
as dicts (``ref_images`` maps ``ref_image_0`` -> image); a flat ``ref_image_0`` key
fails with "unexpected keyword argument".
"""

from __future__ import annotations

from typing import Any, Sequence

from .sheet_spec import (
    CLIP_FPS,
    CONTINUITY_FRAMES,
    DEFAULT_CELL_ASPECT,
    DEFAULT_REF_SCOPE,
    MAX_AUDIOS,
    MAX_CELLS,
    MAX_PICTURES,
    MAX_VIDEOS,
    SheetCell,
    SheetRef,
    SheetSpec,
    align_h3_frames,
    aspect_ratio,
    build_cell_prompt,
    cell_matrix,
    cell_references,
    continuity_plan,
    describe_background,
    framing_distance,
)

#: H3 latents are 16px per token in each axis and the canvas is aligned to 32.
CELL_SIZE_STEP = 32
MIN_CELL_SIZE = 256
MAX_CELL_SIZE = 2048
DEFAULT_CELL_SIZE = 1024

#: Distinct seeds per cell: one seed across a whole sheet makes the cells agree on
#: their noise and fight each other on pose.
SEED_STRIDE = 7919


def align_cell_size(value: Any, *, fallback: int = DEFAULT_CELL_SIZE) -> int:
    """Cell short edge: rounded to the 32px grid H3 expects."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = int(fallback)
    size = max(MIN_CELL_SIZE, min(MAX_CELL_SIZE, size))
    return max(CELL_SIZE_STEP, (size // CELL_SIZE_STEP) * CELL_SIZE_STEP)


def cell_render_size(short_edge: int, aspect: str) -> tuple[int, int]:
    """Pixel size of one cell from its short edge and shape.

    ``9:16`` with a 1024 short edge gives 576x1024: the whole figure fits and the
    sides are not wasted, which is why 9:16 is the default rather than a square.
    """
    ratio = aspect_ratio(aspect, DEFAULT_CELL_ASPECT)
    if ratio <= 0:
        ratio = aspect_ratio(DEFAULT_CELL_ASPECT, DEFAULT_CELL_ASPECT)
    if ratio >= 1.0:
        width, height = short_edge, int(round(short_edge / ratio))
    else:
        width, height = int(round(short_edge * ratio)), short_edge
    return (
        max(CELL_SIZE_STEP, (width // CELL_SIZE_STEP) * CELL_SIZE_STEP),
        max(CELL_SIZE_STEP, (height // CELL_SIZE_STEP) * CELL_SIZE_STEP),
    )


def cell_seed(spec: SheetSpec, cell: SheetCell, index: int) -> int:
    """Explicit per-cell seed, else the sheet seed plus a per-cell offset."""
    if int(cell.seed or 0) > 0:
        return int(cell.seed)
    return (int(spec.render.seed) + index * SEED_STRIDE) & 0xFFFFFFFFFFFFFFFF


def cell_work_items(
    spec: SheetSpec,
    *,
    cell_size: int = DEFAULT_CELL_SIZE,
    ref_image_size: str = "match",
    ref_scope: str = DEFAULT_REF_SCOPE,
) -> list[dict[str, Any]]:
    """One work item per enabled cell, in sheet order (cell 0 is the hero).

    ``cell_size`` is the cell's SHORT edge; each cell's own ``aspect`` (else the
    sheet's ``render.cell_aspect``) decides the long edge. Each item carries the
    references that cell will actually receive (see ``sheet_spec.cell_references``),
    so the prompt and the wiring always describe the same pictures.

    ``continuity`` is how many frames of the previous cell this one continues from
    (``0`` = independent; see ``sheet_spec.continuity_plan``). It is computed here, once
    for the whole sheet, because the graph wiring, the frame picker and the report all
    have to agree on it.
    """
    short_edge = align_cell_size(cell_size)
    default_aspect = str(spec.render.cell_aspect or DEFAULT_CELL_ASPECT)
    guide_frames = continuity_plan(spec)
    items: list[dict[str, Any]] = []
    for index, cell in enumerate(spec.enabled_cells):
        width, height = cell_render_size(short_edge, str(cell.aspect or default_aspect))
        refs = cell_references(spec, cell, scope=ref_scope)
        items.append(
            {
                "index": index,
                "id": cell.id,
                "prompt": build_cell_prompt(spec, cell, refs=refs),
                "frames": align_h3_frames(cell.frames),
                "seed": cell_seed(spec, cell, index),
                "width": width,
                "height": height,
                "ref_image_size": ref_image_size,
                "view": cell.view,
                "pose": cell.pose,
                "expression": cell.expression,
                "continuity": int(guide_frames.get(cell.id, 0) or 0),
                "ref_plan": reference_plan(spec, refs),
            }
        )
    return items


#: The core node's autogrow groups: ``<group>.<template><index>`` in a prompt.
PICTURE_GROUP = "ref_images"
VIDEO_GROUP = "ref_videos"
VIDEO_AUDIO_GROUP = "ref_video_audios"
AUDIO_GROUP = "ref_audios"

#: This pack's grid node collects per-cell frames through the same mechanism.
CELL_GROUP = "cells"


def reference_plan(
    spec: SheetSpec,
    refs: Sequence[SheetRef] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Reference files as the core node's autogrow input keys.

    ``MiniMaxH3ReferenceToVideo`` declares four autogrow groups, each with a template
    prefix (9 images, 3 videos, 3 video soundtracks, 3 audios); a reference video's
    soundtrack is the same index, exactly how the official node pairs them.

    ``refs`` is the subset one cell receives (``sheet_spec.cell_references``): the
    slots are numbered from that subset, because H3 numbers the references it is
    handed. ``source_slot_id`` names the loader node built for the run's FULL set, so
    the graph builder can wire the same image under the cell's own numbering.
    """
    source = list(refs) if refs is not None else [r for r in spec.refs if r.enabled]
    plan: dict[str, list[dict[str, Any]]] = {"pictures": [], "videos": [], "audios": []}
    for position, ref in enumerate([r for r in source if r.kind == "picture"][:MAX_PICTURES]):
        plan["pictures"].append(
            {
                "slot": f"{PICTURE_GROUP}.ref_image_{position}",
                "slot_id": f"ref_image_{position}",
                "source_slot_id": f"ref_image_{ref.source if ref.source >= 0 else position}",
                "file": ref.file,
                "role": ref.role,
            }
        )
    for position, ref in enumerate([r for r in source if r.kind == "video"][:MAX_VIDEOS]):
        origin = ref.source if ref.source >= 0 else position
        plan["videos"].append(
            {
                "slot": f"{VIDEO_GROUP}.ref_video_{position}",
                "slot_id": f"ref_video_{position}",
                "audio_slot": f"{VIDEO_AUDIO_GROUP}.ref_video_audio_{position}",
                "audio_slot_id": f"ref_video_audio_{position}",
                "source_slot_id": f"ref_video_{origin}",
                "source_audio_slot_id": f"ref_video_audio_{origin}",
                "file": ref.file,
                "role": ref.role,
            }
        )
    for position, ref in enumerate([r for r in source if r.kind == "audio"][:MAX_AUDIOS]):
        plan["audios"].append(
            {
                "slot": f"{AUDIO_GROUP}.ref_audio_{position}",
                "slot_id": f"ref_audio_{position}",
                "source_slot_id": f"ref_audio_{ref.source if ref.source >= 0 else position}",
                "file": ref.file,
                "role": ref.role,
            }
        )
    return plan


def uses_audio_references(spec: SheetSpec) -> bool:
    return bool([ref for ref in spec.audios if ref.enabled])


def grid_payload(spec: SheetSpec, *, name: str | None = None) -> dict[str, Any]:
    """What the grid (compositor) node receives: the spec as it was run."""
    payload = spec.to_dict()
    payload["name"] = str(name or spec.name)
    payload["cells"] = [cell for cell in payload["cells"] if cell.get("enabled", True)]
    return payload


def plan_tags(plan: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Prompt tags a reference plan wires, e.g. ``['<Picture 1>', '<Video 1>']``."""
    labels = {"pictures": "Picture", "videos": "Video", "audios": "Audio"}
    tags: list[str] = []
    for group, label in labels.items():
        for position, _entry in enumerate(plan.get(group) or []):
            tags.append(f"<{label} {position + 1}>")
    return tags


def work_summary(spec: SheetSpec, items: list[dict[str, Any]]) -> list[str]:
    """Human readable plan lines (report + panel status)."""
    lines = [
        f"Character sheet '{spec.name}': {len(items)} cell(s), "
        f"{sum(int(item['frames']) for item in items)} frame(s) to sample.",
        f"Layout: {spec.layout.layout} · {spec.layout.columns} column(s) · "
        f"{spec.layout.aspect} @ {spec.layout.short_edge}px short edge.",
        f"Background: {describe_background(spec)} · cells render in list order "
        "(cell 1 first).",
    ]
    refs = reference_plan(spec)
    full = plan_tags(refs)
    lines.append(
        f"References: {len(refs['pictures'])} picture(s), "
        f"{len(refs['videos'])} video(s), {len(refs['audios'])} audio(s)."
    )
    # A framing can leave out a reference it cannot show (an outfit photo on a
    # close-up); say so, because that is what keeps the other face out of the shot.
    for item in items:
        tags = plan_tags(item.get("ref_plan") or {})
        if tags and len(tags) != len(full):
            lines.append(
                f"{item['id']} is conditioned on {', '.join(tags)} only "
                f"(the framing cannot show the rest)."
            )
    chained = [item for item in items if int(item.get("continuity") or 0) > 0]
    if chained:
        lines.append(
            f"Continuation: {len(chained)} cell(s) continue from the previous cell "
            f"({CONTINUITY_FRAMES} frame(s) handed over, frames 1-{CONTINUITY_FRAMES} "
            "of those cells re-render the previous tail; their picked frame comes from "
            "the settled tail of the clip)."
        )
    # With the switch on 'auto' a framing change breaks the chain on purpose; saying so
    # keeps "why is this cell not continuing?" from being a mystery in the report.
    breaks: list[str] = []
    for position, item in enumerate(items):
        if position == 0 or int(item.get("continuity") or 0) > 0:
            continue
        mine = framing_distance(item.get("view"))
        theirs = framing_distance(items[position - 1].get("view"))
        if mine and theirs and mine != theirs:
            breaks.append(f"{item['id']} ({theirs} -> {mine})")
    if breaks:
        lines.append(
            "Continuation: kept independent at a framing change: "
            + ", ".join(breaks)
            + " - the hand-over would carry the previous camera distance."
        )
    if spec.render.export_video:
        lines.append(
            f"Cell clips: every cell is also written as a video next to its frames "
            f"(minimax_sheets/{spec.name}/clips/<cell>_0000N_.mp4, {CLIP_FPS:g} fps with the "
            "audio H3 generated)."
        )
    for item in items:
        guide = int(item.get("continuity") or 0)
        lines.append(
            f"- [{item['index']}] {item['id']}: {item['view']}/{item['pose']}/"
            f"{item['expression']} · {item['frames']}f · {item['width']}x{item['height']} · "
            f"seed {item['seed']}"
            + (f" · continues {guide}f" if guide else "")
        )
    for warning in spec.warnings:
        lines.append(f"Warning: {warning}")
    return lines


#: The standard 8-view sheet: the curated matrix the shipped workflow builds and
#: what a payload without cells falls back to (face + smile, portrait, front in
#: three poses, profile, back - the set a character sheet is normally asked for).
DEFAULT_MATRIX: tuple[tuple[str, str, str], ...] = (
    ("face", "neutral", "neutral"),
    ("face", "neutral", "smile"),
    ("portrait", "neutral", "neutral"),
    ("front", "neutral", "neutral"),
    ("front", "a-pose", "neutral"),
    ("front", "t-pose", "neutral"),
    ("profile", "neutral", "neutral"),
    ("back", "neutral", "neutral"),
)


def default_cells() -> list[dict[str, str]]:
    """Cell payloads for :data:`DEFAULT_MATRIX`, ready to parse into ``SheetCell``."""
    return [
        {
            "id": f"{view}-{pose}-{expression}",
            "view": view,
            "pose": pose,
            "expression": expression,
        }
        for view, pose, expression in DEFAULT_MATRIX
    ]


def cells_from_build(build: Any) -> list[dict[str, Any]]:
    """Cells implied by the panel's view/pose/expression ticks.

    A payload with ticks but no explicit cell list is not empty - the user picked a
    set of views. Building from the ticks keeps "what I ticked is what renders"
    true, and it is the same expansion the panel's *Build cells* button makes; the
    cells deliberately carry no frame count so they follow the node's
    ``frames_per_cell`` widget.
    """
    if not isinstance(build, dict):
        return []

    def values(key: str) -> list[str]:
        raw = build.get(key)
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(item).strip().lower() for item in raw if str(item).strip()]

    views = values("views")
    if not views:
        return []
    built = cell_matrix(views=views, poses=values("poses"), expressions=values("expressions"))
    return [{key: value for key, value in cell.items() if key != "frames"} for cell in built]


def cell_slots(count: int) -> list[str]:
    """Autogrow slot keys for the grid node, capped and ordered.

    Same ``<group>.<template><index>`` shape as the reference slots: the grid's
    autogrow group is ``cells`` with the ``cell_`` template prefix.
    """
    return [
        f"{CELL_GROUP}.cell_{index}"
        for index in range(max(0, min(MAX_CELLS, int(count))))
    ]


__all__ = [
    "CELL_GROUP",
    "CELL_SIZE_STEP",
    "DEFAULT_CELL_SIZE",
    "DEFAULT_MATRIX",
    "MAX_CELL_SIZE",
    "MIN_CELL_SIZE",
    "SEED_STRIDE",
    "align_cell_size",
    "cell_seed",
    "cell_slots",
    "cell_work_items",
    "default_cells",
    "grid_payload",
    "plan_tags",
    "reference_plan",
    "uses_audio_references",
    "work_summary",
]
