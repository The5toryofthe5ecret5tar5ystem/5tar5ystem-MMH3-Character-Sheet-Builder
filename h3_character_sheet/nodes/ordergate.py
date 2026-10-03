# ComfyUI-H3-Character-Sheet - the render-order gate.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""H3 Sheet Order Gate: makes the cells render in list order.

ComfyUI decides which node to run next by walking the graph from its outputs and
picking the first *ready* node in discovery order. For our expansion that
discovery runs **backwards** through the grid's autogrow slots, so the executor
starts with the LAST cell: the sheet came out with the "from behind" view rendered
first and the hero last, which is the opposite of what the Cells tab shows.

There is no way to ask the executor for an order, so this node imposes one: it is a
pass-through that carries the MODEL, and each cell's gate also takes the *previous*
cell's finished frames as an input. A cell's sampler needs its gate, and its gate
needs the previous cell's frames, so cell 2 cannot start until cell 1 has finished.

Cost is nil - the node does no compute, and the model it hands on is the same
patched model object it was given (no re-patching, no extra VRAM).
"""

from __future__ import annotations

from typing import Any

from comfy_api.latest import io


class H3SheetOrderGate(io.ComfyNode):
    """Render one sheet cell at a time, in the order the cells are listed."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="H3SheetOrderGate",
            display_name="H3 Sheet Order Gate (internal)",
            category="MiniMaxH3/Character Sheet",
            description=(
                "Internal: sequences the sheet's cells so they render top to bottom. "
                "Inserted by the character sheet node, no settings."
            ),
            inputs=[
                io.Model.Input("model", tooltip="The patched H3 model, passed straight through."),
                io.Image.Input(
                    "after",
                    optional=True,
                    tooltip="The previous cell's frames: this cell waits for them before sampling.",
                ),
            ],
            outputs=[io.Model.Output(display_name="model")],
        )

    @classmethod
    def execute(cls, model: Any, after: Any = None) -> io.NodeOutput:
        # ``after`` is deliberately unused: it exists so the executor has to finish
        # the previous cell before this one may run.
        return io.NodeOutput(model)


__all__ = ["H3SheetOrderGate"]
