# ComfyUI-H3-Character-Sheet - the one-pass sink.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""H3 Sheet One-Pass Sink: the whole sheet from ONE H3 render, written to the sheet folder.

Internal node, inserted by the Character Sheet Builder unless the run asks for the per-cell pass.
The builder expands into a single H3 chain (one ``MiniMaxH3ReferenceToVideo`` at the sheet's
canvas, ``length=5``) instead of one chain per cell, and this node turns the frames it produced
into the sheet:

* the frame the model settled on becomes the sheet's own image file, so the panel, the routes and
  any preview show a one-pass sheet exactly where they show a per-cell one;
* **the panels are sliced back out** of that frame at the boxes the prompt asked for, and each one
  is written as a cell-like record (``cells/<id>.png`` + ``frames/<id>/f0000.png``). That is what
  lets a one-pass sheet feed everything that wants per-view images - the RefMod export above all -
  and it makes the Results tab show the panels without a second render;
* every frame of the clip is kept under ``one_pass/``, so a different sheet frame is a re-read;
* the manifest records the ``onePass`` block (canvas, panels, prompt, slices) and claims NO cells:
  a manifest that claimed per-cell frames it never rendered is how a later re-compose would quietly
  replace the sheet with a composite of slices.

The per-cell pass is still the opt-in path (``single_pass`` off). See ``one_pass.py`` for the trade.
"""

from __future__ import annotations

import logging
from typing import Any

from comfy_api.latest import io

from ..one_pass import (
    one_pass_manifest,
    one_pass_plan,
    one_pass_report_lines,
    pad_panels,
    slice_panels,
)
from ..sheet_pass_core import flatten_image_batch
from ..sheet_spec import parse_sheet_spec
from ..sheet_store import SheetStore
from .grid import tensor_from_arrays

log = logging.getLogger("H3-Character-Sheet.onepass")


class H3SheetOnePassSink(io.ComfyNode):
    """Write a one-pass render: the sheet frame, the sliced panels and what they describe."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3SheetOnePassSink",
            # AN OUTPUT NODE, and it has to be. This is the node that WRITES the sheet folder
            # (one_pass/ frames, the sheet still, the slices, the report, the manifest), so a copy
            # of it that nothing consumes must still run - ComfyUI executes the nodes reachable
            # from the prompt's output nodes and prunes the rest. A SUITE renders several boards in
            # one expansion and only the FIRST board's sink is returned as this node's own output,
            # so without this flag every other board was pruned and the suite quietly rendered one
            # sheet (see build_suite_graph). Being an output node is also what a writer is: core's
            # SaveImage/SaveVideo declare the same.
            is_output_node=True,
            display_name="H3 Sheet One-Pass Sink (internal)",
            category="MiniMaxH3/Character Sheet",
            description=(
                "Records a one-pass sheet - the whole sheet from one H3 clip: keeps the clip's "
                "frames, writes one of them as the sheet's image, slices the panels back out of it "
                "and records the run in the sheet folder's manifest."
            ),
            inputs=[
                io.Image.Input(
                    "images",
                    tooltip="Every frame of the render (H3's 5-frame minimum).",
                ),
                io.String.Input(
                    "sheet_data",
                    default="",
                    multiline=True,
                    tooltip="Sheet payload written by the Character Sheet Builder node / panel.",
                ),
                io.String.Input("name", default="character_sheet", tooltip="Sheet folder name."),
                io.String.Input(
                    "board",
                    default="",
                    optional=True,
                    tooltip=(
                        "Which sheet of a suite this is (see suite.py): the render lands in "
                        "name/<board>/ so every board is a complete sheet folder of its own. "
                        "Empty for a normal run."
                    ),
                ),
                io.Boolean.Input(
                    "keep_frames",
                    default=True,
                    optional=True,
                    tooltip=(
                        "Keep every frame of the render under one_pass/ so a different sheet frame "
                        "can be chosen later without re-rendering. The sliced panels are always "
                        "kept - they are what a per-view consumer reads."
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(
                    display_name="sheet",
                    tooltip="The sheet - the whole reference sheet as one image.",
                ),
                io.Image.Output(
                    display_name="panels",
                    tooltip=(
                        "The panels sliced out of the sheet, in sheet order (letterboxed onto one "
                        "batch). The builder hands these on as its `cells` output, so per-view "
                        "consumers - RefMod above all - work the same way they do after a per-cell "
                        "render."
                    ),
                ),
                io.String.Output(display_name="report"),
                io.String.Output(
                    display_name="sheet_dir",
                    tooltip="Absolute folder the sheet was written to.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        images: Any,
        sheet_data: str = "",
        name: str = "character_sheet",
        board: str = "",
        keep_frames: bool = True,
    ) -> io.NodeOutput:
        spec = parse_sheet_spec(sheet_data or {})
        spec.name = str(name or spec.name or "character_sheet")
        plan = one_pass_plan(spec)
        frames = flatten_image_batch(images)
        # fresh=True: the render writes a NEW dated sheet file, exactly like the per-cell pass - the
        # sheet of the previous run is a finished image, not something to overwrite.
        store = SheetStore(spec.name, fresh=True, board=board or None).ensure()
        spec.name = store.name

        still_file = ""
        sheet_array = None
        panels: list[tuple[str, Any]] = []
        if frames:
            store.save_pass_frames(frames)
            index = min(int(plan.get("sheetFrame") or 0), len(frames) - 1)
            sheet_array = frames[index]
            saved = store.save_sheet_still(sheet_array)
            still_file = saved.name if saved is not None else ""
            panels = slice_panels(frames, plan)
            for cell_id, array in panels:
                # One frame per panel, written the way a per-cell render writes its cell: the panel
                # listing, the results thumbnails, a picked still and the RefMod export all read
                # these without knowing which mode produced them.
                store.save_cell_frames(cell_id, [array])
                store.save_cell_pick(cell_id, array)
        else:
            log.warning("Character sheet one-pass: the render produced no frames.")

        lines = [
            f"H3 Sheet one-pass: {len(frames)} frame(s) from ONE H3 render "
            f"({plan['width']}x{plan['height']}), sliced into {len(panels)} panel(s).",
            f"Folder: {store.dir}",
        ]
        lines.extend(
            one_pass_report_lines(
                plan,
                spec=spec,
                still_path=still_file or None,
                frame_count=len(frames),
                panel_count=len(panels),
            )
        )
        report = "\n".join(lines)
        store.write_report(report)
        store.write_manifest(
            one_pass_manifest(
                plan,
                spec=spec,
                still_file=still_file,
                frame_files=[path.name for path in store.pass_frame_files()],
                panel_files=[cell_id for cell_id, _array in panels],
            )
        )
        if not keep_frames:
            for stale in store.pass_dir.glob("f*.png"):
                try:
                    stale.unlink()
                except OSError:
                    pass

        sheet_tensor = tensor_from_arrays([sheet_array])
        panels_tensor = tensor_from_arrays(pad_panels(panels))
        return io.NodeOutput(sheet_tensor, panels_tensor, report, str(store.dir))


NODE_CLASS_MAPPINGS = {"H3SheetOnePassSink": H3SheetOnePassSink}
NODE_DISPLAY_NAME_MAPPINGS = {"H3SheetOnePassSink": "H3 Sheet One-Pass Sink (internal)"}

__all__ = [
    "H3SheetOnePassSink",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
