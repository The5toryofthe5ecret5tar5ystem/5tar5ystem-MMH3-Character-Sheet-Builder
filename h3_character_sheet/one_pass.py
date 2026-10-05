# ComfyUI-H3-Character-Sheet - the one-pass sheet: every panel from one H3 render.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""One-pass sheet: the whole sheet from ONE H3 render, with the panels sliced back out.

This is the pack's primary render. One prompt describes every panel, one clip at H3's 5-frame
minimum draws them all, and the frame the model settles on becomes the sheet.

What that buys: about a twentieth of the sampling of a per-cell run (5 frames against 110 for a
five-cell sheet at 22 frames), and panels that agree by construction - identity, lighting, palette
and style cannot drift between views when a single sampling context draws them all.

What it costs, stated plainly: the panels share one canvas rather than getting a render each, H3
reads the panel positions as guidance (it can merge, reorder or drop panels), and there are no
per-cell frames to pick from, no clips, no continuation.

The panels are also SLICED back out of the still, at the rectangles the prompt asked for
(:func:`slice_panels`, from the same ``layout_rects`` the composite uses). That is what lets a
one-pass sheet feed everything that wants per-view images - the RefMod export above all - without a
second render, and it is why this mode can be the default instead of a preview.

The per-cell pass (``single_pass`` off) is the classic path: one short render per cell, which buys
per-cell frames, the frame picker, clips with audio, latent continuation, a full render per panel
and a sheet that can be re-composited from its parts.

The geometry and the prompt vocabulary are shared, never duplicated: a one-pass sheet asks for the
same cells in the same words (``sheet_spec.cell_shot_lines``) over the same layout
(``sheet_layout.layout_rects``), so the two modes describe the same sheet and can be compared.

Pure data: no ComfyUI, no torch, no GPU.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Sequence

import numpy as np

from .sheet_layout import layout_rects, sheet_canvas_size
from .sheet_spec import (
    ONE_PASS_ALIGN,
    ONE_PASS_FRAMES,
    ONE_PASS_MAX_PIXELS,
    ONE_PASS_SHEET_FRAME,
    SheetCell,
    SheetSpec,
    align_h3_frames,
    build_sheet_prompt,
    describe_background,
)

log = logging.getLogger("H3-Character-Sheet.onepass")

#: Smallest canvas edge a one-pass render will use. Below this H3 has no room for a figure and the
#: panels are not panels any more; ``sheet_canvas_size`` already floors the composite at 32, and
#: this is the render's own, higher floor.
MIN_ONE_PASS_EDGE = 256

#: Above this many panels the panels stop being readable: each one gets canvas/panels of the width,
#: and one sampling context only has so much attention to spread. A warning rather than a cap - the
#: panel count is the user's call.
ONE_PASS_PANEL_COMFORT = 8

#: Backdrop a sliced panel is padded onto when it lands in a common IMAGE batch (see
#: ``slice_panels``). Panels have different shapes - a hero box is tall, a grid cell is not - and an
#: IMAGE batch is one tensor, so the batch letterboxes rather than stretches. The files on disk keep
#: each panel's true size.
PANEL_PAD_COLOR = (16, 16, 20)


def align_one_pass_edge(value: Any) -> int:
    """Snap one canvas edge UP to the one-pass grid (``ONE_PASS_ALIGN``)."""
    try:
        edge = int(value)
    except (TypeError, ValueError):
        edge = MIN_ONE_PASS_EDGE
    edge = max(MIN_ONE_PASS_EDGE, edge)
    return -(-edge // ONE_PASS_ALIGN) * ONE_PASS_ALIGN  # ceil to the grid


def one_pass_size(spec: SheetSpec) -> tuple[int, int]:
    """``(width, height)`` of the one-pass canvas: the sheet's own layout at the chosen size.

    The starting point is the composite's canvas (``sheet_layout.sheet_canvas_size``), so the panel
    boxes the prompt states describe the sheet's real layout. A render above
    ``ONE_PASS_MAX_PIXELS`` is scaled down, aspect preserved - one pass has no second render to
    amortise a bigger canvas over - unless the sheet's own size was chosen explicitly, which the
    resolution control does (see ``presets.resolution_choice``).
    """
    width, height = sheet_canvas_size(spec.layout)
    width, height = align_one_pass_edge(width), align_one_pass_edge(height)
    budget = one_pass_budget(spec)
    if budget <= 0 or width * height <= budget:
        return width, height
    factor = math.sqrt(budget / float(width * height))
    return align_one_pass_edge(round(width * factor)), align_one_pass_edge(round(height * factor))


def one_pass_budget(spec: SheetSpec) -> int:
    """The pixel budget for one pass: ``0`` = whatever the layout asks for.

    The sheet's own resolution is a deliberate choice (the resolution control writes it, and the
    chips pair it with the cell size), so a chosen size is honoured as-is and only a size nobody
    picked - a hand-typed 8K canvas, or a layout the control does not cover - is scaled to
    ``ONE_PASS_MAX_PIXELS``.
    """
    chosen = bool(getattr(spec.render, "resolution", ""))
    return 0 if chosen else ONE_PASS_MAX_PIXELS


def one_pass_panels(spec: SheetSpec) -> list[SheetCell]:
    """The cells a one-pass render draws, in sheet order (enabled first, else every cell)."""
    return list(spec.enabled_cells) or [cell for cell in spec.cells]


def one_pass_plan(spec: SheetSpec) -> dict[str, Any]:
    """Everything a one-pass run needs: size, frame count, prompt, geometry, notes, warnings.

    Plain data, so the graph builder, the sink and the tests all describe the same render and it
    can be unit-tested with no GPU and no ComfyUI:
    ``{width, height, frames, sheetFrame, prompt, panels, rects, pixels, notes, warnings}``.
    """
    panels = one_pass_panels(spec)
    width, height = one_pass_size(spec)
    sheet_width, sheet_height = sheet_canvas_size(spec.layout)
    # The rects come from the render's OWN canvas (see layout_rects): the prompt states the panel
    # boxes of the image H3 is about to draw, and the same rects slice it back up afterwards.
    _, rects = layout_rects(panels, spec.layout, canvas=(width, height))
    frames = align_h3_frames(ONE_PASS_FRAMES, fallback=ONE_PASS_FRAMES)
    sheet_frame = min(ONE_PASS_SHEET_FRAME, max(0, frames - 1))
    prompt = build_sheet_prompt(spec, panels, size=(width, height), rects=rects)

    pixels = width * height
    notes: list[str] = []
    warnings: list[str] = []
    if not panels:
        warnings.append(
            "One-pass render has no cells to describe - the sheet would be a picture of nothing."
        )
    if width * height != sheet_width * sheet_height:
        notes.append(
            f"the sheet's own canvas is {sheet_width}x{sheet_height} "
            f"({(sheet_width * sheet_height) / 1_000_000:.1f} MP); this pass renders "
            f"{width}x{height} because one pass draws the whole sheet at once and "
            f"{ONE_PASS_MAX_PIXELS / 1_000_000:.1f} MP is the budget for a canvas nobody chose. "
            "The layout is the same, only smaller - pick a resolution to render it as-is."
        )
    if pixels > ONE_PASS_MAX_PIXELS:
        notes.append(
            f"rendering {width}x{height} = {pixels / 1_000_000:.1f} MP in one pass "
            f"(above the {ONE_PASS_MAX_PIXELS / 1_000_000:.1f} MP guidance): the chosen "
            "resolution is honoured as-is, and this is the whole cost of the render."
        )
    if len(panels) > ONE_PASS_PANEL_COMFORT:
        warnings.append(
            f"{len(panels)} panels in one render - each gets about "
            f"{width // max(1, len(panels))}x{height} px of one canvas, and one sampling context "
            "only spreads so far, so panels this small tend to merge or drop. The per-cell pass is "
            "the reliable sheet."
        )
    for note in notes:
        log.info("Character sheet one-pass: %s", note)
    for warning in warnings:
        log.info("Character sheet one-pass: %s", warning)

    return {
        "width": width,
        "height": height,
        "frames": frames,
        "sheetFrame": sheet_frame,
        "prompt": prompt,
        "panels": list(panels),
        "rects": [tuple(int(value) for value in rect) for rect in rects],
        "pixels": pixels,
        "notes": notes,
        "warnings": warnings,
    }


def slice_panels(
    arrays: Sequence[np.ndarray],
    plan: dict[str, Any],
    *,
    background: tuple[int, int, int] = PANEL_PAD_COLOR,
) -> list[tuple[str, np.ndarray]]:
    """Cut the still into one image per panel: ``[(cell_id, array), ...]`` in sheet order.

    Each panel is cut at the rectangle the prompt asked for (``plan['rects']``, from
    ``layout_rects`` on this render's canvas), clamped to the image, so a sliced panel is what H3
    was told to draw in that spot. This is what makes the mode the default rather than a preview:
    per-view images exist without a second render, which is exactly what the RefMod export needs.

    The canvas H3 returns is the canvas it was asked for, so the boxes land 1:1; the clamp is there
    for the case where a backend returns something else (a different frame size never silently
    becomes a wrong crop - the panel keeps its aspect and is cut no larger than the image).
    """
    if isinstance(arrays, np.ndarray):
        # A single frame is a reasonable thing to hand over; a bare array is not a sequence of
        # frames and ``not arrays`` on one is ambiguous, so make it the one-frame list it means.
        arrays = [arrays]
    if not arrays:
        return []
    still = arrays[min(int(plan.get("sheetFrame") or 0), len(arrays) - 1)]
    height, width = int(still.shape[0]), int(still.shape[1])
    panels = list(plan.get("panels") or [])
    rects = list(plan.get("rects") or [])
    sliced: list[tuple[str, np.ndarray]] = []
    for position, cell in enumerate(panels):
        if position >= len(rects):
            break
        x, y, box_w, box_h = (int(value) for value in rects[position])
        left = max(0, min(x, width - 1))
        top = max(0, min(y, height - 1))
        right = max(left + 1, min(x + box_w, width))
        bottom = max(top + 1, min(y + box_h, height))
        crop = np.ascontiguousarray(still[top:bottom, left:right])
        if crop.size == 0:
            continue
        sliced.append((str(cell.id), crop))
    return sliced


def pad_panels(
    panels: Sequence[tuple[str, np.ndarray]],
    *,
    background: tuple[int, int, int] = PANEL_PAD_COLOR,
) -> list[np.ndarray]:
    """Panels -> one size, letterboxed (not stretched) so an IMAGE batch can carry them.

    A sliced panel keeps the shape of its own box: a hero panel is tall, a grid cell is not. An
    IMAGE batch is a single tensor, so the batch pads each panel onto the largest panel's canvas,
    centred, on the sheet's own background colour. The files written for each panel keep their true
    size - only the hand-off batch is uniform.
    """
    if not panels:
        return []
    height = max(int(array.shape[0]) for _cell, array in panels)
    width = max(int(array.shape[1]) for _cell, array in panels)
    padded: list[np.ndarray] = []
    for _cell, array in panels:
        top = (height - int(array.shape[0])) // 2
        left = (width - int(array.shape[1])) // 2
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        canvas[:, :] = np.array(background, dtype=np.uint8)
        canvas[top : top + array.shape[0], left : left + array.shape[1]] = array
        padded.append(canvas)
    return padded


def one_pass_prompt_summary(plan: dict[str, Any]) -> str:
    """``"5 panel(s), 4782 characters"`` - one line for the report and the log."""
    prompt = str(plan.get("prompt") or "")
    return f"{len(plan.get('panels') or [])} panel(s), {len(prompt)} characters"


def one_pass_report_lines(
    plan: dict[str, Any],
    *,
    spec: SheetSpec,
    still_path: Any = None,
    frame_count: int | None = None,
    panel_count: int | None = None,
) -> list[str]:
    """The one-pass report block (kept in the same voice as the per-cell pass)."""
    panels = plan.get("panels") or []
    width, height = int(plan.get("width") or 0), int(plan.get("height") or 0)
    lines = [
        "One-pass sheet: the whole sheet from ONE H3 render "
        f"({int(plan.get('frames') or ONE_PASS_FRAMES)} frames, sheet = frame "
        f"{int(plan.get('sheetFrame') or 0)}).",
        f"Canvas: {width}x{height} "
        f"({(width * height) / 1_000_000:.1f} MP, snapped up to a {ONE_PASS_ALIGN}px grid).",
        f"Panels: {len(panels)} ({', '.join(cell.id for cell in panels) or 'none'}) "
        f"on a {spec.layout.layout} layout; background: {describe_background(spec)}.",
        f"Prompt: {one_pass_prompt_summary(plan)} - global description, reference legend, "
        "one line per panel, then the shared identity and negative rules.",
        "Panel positions are stated to H3 in pixels. They are guidance, not a constraint: panels "
        "can be reordered, merged or dropped - check the sheet before trusting a layout.",
    ]
    if panel_count:
        lines.append(
            f"Sliced {int(panel_count)} panel image(s) out of the sheet at the requested boxes, so "
            "per-view images (RefMod members above all) exist without a per-cell render."
        )
    if frame_count is not None:
        lines.append(
            f"Kept {int(frame_count)} frame(s) of the render"
            + (f"; the sheet is {still_path}." if still_path is not None else ".")
        )
    for note in plan.get("notes") or []:
        lines.append(f"Note: {note}")
    for warning in plan.get("warnings") or []:
        lines.append(f"Warning: {warning}")
    return lines


def one_pass_manifest(
    plan: dict[str, Any],
    *,
    spec: SheetSpec,
    still_file: str = "",
    frame_files: Iterable[str] = (),
    panel_files: Iterable[str] = (),
) -> dict[str, Any]:
    """The manifest a one-pass render writes - the grid's shape, plus the ``onePass`` block.

    ``cells`` stays empty on purpose: the per-cell pass owns that map, and a manifest that claimed
    per-cell frames it never rendered is how a later re-compose would quietly replace the sheet with
    a composite of slices. The panels are recorded in their own block.
    """
    return {
        "spec": spec.to_dict(),
        "cells": {},
        "missing": [],
        "size": [int(plan.get("width") or 0), int(plan.get("height") or 0)],
        "warnings": list(plan.get("warnings") or []),
        "notes": list(plan.get("notes") or []),
        "sheetFile": str(still_file or ""),
        "onePass": {
            "width": int(plan.get("width") or 0),
            "height": int(plan.get("height") or 0),
            "frames": int(plan.get("frames") or ONE_PASS_FRAMES),
            "sheetFrame": int(plan.get("sheetFrame") or 0),
            "panels": [cell.id for cell in plan.get("panels") or []],
            "prompt": str(plan.get("prompt") or ""),
            "framesKept": [str(name) for name in frame_files],
            "panelFiles": [str(name) for name in panel_files],
        },
    }


__all__ = [
    "MIN_ONE_PASS_EDGE",
    "ONE_PASS_PANEL_COMFORT",
    "PANEL_PAD_COLOR",
    "align_one_pass_edge",
    "one_pass_budget",
    "one_pass_manifest",
    "one_pass_panels",
    "one_pass_plan",
    "one_pass_prompt_summary",
    "one_pass_report_lines",
    "one_pass_size",
    "pad_panels",
    "slice_panels",
]
