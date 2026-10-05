# ComfyUI-H3-Character-Sheet - the suite join.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""H3 Sheet Suite Join: the one point a suite's workflow waits for.

ComfyUI runs a node as soon as ITS OWN inputs are ready - there is no "after that
one" in a graph, only dependencies. A suite renders several boards, and the builder
returns them merged with the FIRST board's result as its own outputs; wiring the
RefMod export to the builder therefore let it run while boards 2..4 were still
rendering: the bundle was written from the hero board alone and the other sheets
landed after it.

This node is the dependency that fixes it. It takes the hero board's four values
(what the node's outputs are - sheet, cells, report, sheet_dir) plus every OTHER
board's report as an input it never reads. Strings, deliberately: a report is a few
kilobytes, where carrying each board's sheet image would hold four 7 MP tensors in
memory for the whole run. Nothing else changes - the node does no compute, it hands
on exactly what it was given, and the boards themselves are untouched.

The same trick as ``ordergate.py``, for the same reason: the executor has no notion
of order, so the order has to be expressed as a dependency.
"""

from __future__ import annotations

from typing import Any

from comfy_api.latest import io

_CATEGORY = "MiniMaxH3/Character Sheet"


class H3SheetJoin(io.ComfyNode):
    """Wait for every board of a suite, then hand the first board's result on."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3SheetJoin",
            display_name="H3 Sheet Suite Join (internal)",
            category=_CATEGORY,
            description=(
                "Internal: waits for every board of a RefMod suite before the rest of the "
                "workflow (the RefMod export above all) may run. Inserted by the character "
                "sheet node, no settings."
            ),
            inputs=[
                io.Image.Input("sheet", tooltip="The first board's sheet, passed straight through."),
                io.Image.Input("cells", tooltip="The first board's panels, passed straight through."),
                io.String.Input("report", tooltip="The first board's report."),
                io.String.Input("sheet_dir", tooltip="The first board's folder."),
                io.Autogrow.Input(
                    "boards",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.String.Input(
                            "report",
                            tooltip=(
                                "Another board's report. Unused on purpose: it is the dependency "
                                "that makes this node wait for that board to finish."
                            ),
                        ),
                        prefix="report_",
                        min=0,
                        max=16,
                    ),
                ),
            ],
            outputs=[
                io.Image.Output(display_name="sheet"),
                io.Image.Output(display_name="cells"),
                io.String.Output(display_name="report"),
                io.String.Output(display_name="sheet_dir"),
            ],
        )

    @classmethod
    def execute(
        cls,
        sheet: Any,
        cells: Any,
        report: str = "",
        sheet_dir: str = "",
        boards: Any = None,
    ) -> io.NodeOutput:
        # ``boards`` is deliberately unused: it exists so the executor has to finish every other
        # board before anything wired to this node may run.
        return io.NodeOutput(sheet, cells, report, sheet_dir)


__all__ = ["H3SheetJoin"]
