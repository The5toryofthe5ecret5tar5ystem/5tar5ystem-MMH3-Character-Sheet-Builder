"""Character Sheet Builder - the per-cell clip export.

A sheet renders one short H3 clip per cell and, by default, keeps only the frames plus
one picked frame per cell. The clip itself - 22 frames at H3's fixed 24 fps, with the
audio the model generated alongside them - is what a finished edit cuts with, so it is
written next to those frames as ``clips/<cell>_0000N_.mp4``.

Pinned here:

* the chain is core only (``VAEDecodeAudio`` -> ``CreateVideo`` -> ``SaveVideo``) and
  lands in the sheet's own folder,
* the fps is H3's model rate, not a preference,
* the export is on an execution path (core SaveVideo is an output node; the cell saver
  carrying its result is what guarantees it runs),
* and turning it off removes every added node.
"""

from __future__ import annotations

import numpy as np
import pytest
from comfy_execution.graph_utils import GraphBuilder

from h3cs import planner as pl
from h3cs import sheet_spec as ss
from h3cs import sheet_store as store_mod
from h3cs.nodes import sheet as sheet_node

SENTINEL = {"model": "MODEL", "clip": "CLIP", "video_vae": "VVAE", "audio_vae": "AVAE"}


def _spec(cells=None, render=None):
    payload = {
        "name": "sheet run",
        "globalPrompt": "a woman in her thirties",
        "refs": {"pictures": [{"imageFile": "face.png", "role": "face and hair"}]},
        "render": dict(render or {}),
        "cells": list(cells or [{"id": "c1", "view": "front"}, {"id": "c2", "view": "front"}]),
    }
    return ss.parse_sheet_spec(payload)


def _build(spec, **kwargs):
    work_items = pl.cell_work_items(spec, cell_size=512)
    graph = GraphBuilder()
    sheet_node.build_sheet_graph(
        graph,
        model=SENTINEL["model"],
        clip=SENTINEL["clip"],
        video_vae=SENTINEL["video_vae"],
        audio_vae=SENTINEL["audio_vae"],
        work_items=work_items,
        refs=pl.reference_plan(spec),
        payload=pl.grid_payload(spec, name="sheet run"),
        name="sheet run",
        **kwargs,
    )
    return graph.finalize()


def _nodes(nodes, class_type):
    return {nid: node for nid, node in nodes.items() if node["class_type"] == class_type}


def _for_cell(nodes, class_type, cell_id):
    return next(
        node
        for nid, node in nodes.items()
        if node["class_type"] == class_type and str(nid).endswith(cell_id)
    )


# --------------------------------------------------------------------------- #
# the chain
# --------------------------------------------------------------------------- #
def test_every_cell_gets_a_clip_by_default():
    nodes = _build(_spec())
    assert len(_nodes(nodes, "CreateVideo")) == 2
    assert len(_nodes(nodes, "SaveVideo")) == 2
    assert len(_nodes(nodes, "VAEDecodeAudio")) == 2


def test_the_clip_is_built_from_the_cells_own_frames_and_audio():
    nodes = _build(_spec())
    for cell_id in ("c1", "c2"):
        video = _for_cell(nodes, "CreateVideo", cell_id)
        audio = _for_cell(nodes, "VAEDecodeAudio", cell_id)
        decoded = _for_cell(nodes, "VAEDecode", cell_id)
        # The audio is decoded from the SAME sampler output the frames came from, so the
        # clip's soundtrack is the one H3 generated with those very frames.
        assert audio["inputs"]["samples"] == decoded["inputs"]["samples"]
        assert audio["inputs"]["vae"] == SENTINEL["audio_vae"]
        assert video["inputs"]["images"][0].endswith(f"decode_{cell_id}")
        assert video["inputs"]["audio"][0].endswith(f"audio_{cell_id}")
        source = nodes[decoded["inputs"]["samples"][0]]
        assert source["class_type"] == "SamplerCustomAdvanced"


def test_the_fps_is_h3s_model_rate():
    """H3 has no fps input: the frame count is the duration, always at 24 fps."""
    assert ss.CLIP_FPS == 24.0
    nodes = _build(_spec())
    assert {node["inputs"]["fps"] for node in _nodes(nodes, "CreateVideo").values()} == {24.0}


def test_the_clip_is_written_into_the_sheets_own_folder():
    nodes = _build(_spec())
    prefixes = {node["inputs"]["filename_prefix"] for node in _nodes(nodes, "SaveVideo").values()}
    assert prefixes == {
        "minimax_sheets/sheet run/clips/c1",
        "minimax_sheets/sheet run/clips/c2",
    }
    for node in _nodes(nodes, "SaveVideo").values():
        assert node["inputs"]["format"] == "mp4"
        assert node["inputs"]["codec"] == "h264", "a plain h264 mp4 plays anywhere"


def test_the_export_rides_on_the_cell_savers_input():
    """Core SaveVideo is an output node: a node nothing consumes may not execute.

    The cell saver takes the clip as an optional input and ignores it, which is what puts
    the export on the path to the sheet's own outputs.
    """
    nodes = _build(_spec())
    for cell_id in ("c1", "c2"):
        sink = _for_cell(nodes, "H3SheetCellSink", cell_id)
        saver = _for_cell(nodes, "SaveVideo", cell_id)
        assert sink["inputs"]["clip"][0] == next(
            nid for nid, node in nodes.items() if node is saver
        )


def test_the_export_never_shadows_the_text_encoder():
    """Regression: a local named ``clip`` rebinding the CLIP parameter.

    The export's video used to be bound to ``clip``, so every cell AFTER the first got a
    video in the reference node's ``clip`` input: the run rendered cell 1, then died with
    "'VideoFromComponents' object has no attribute 'tokenize'" (in the reference node's
    own text encoding, i.e. a long way from the mistake).
    """
    nodes = _build(_spec())
    for cell_id in ("c1", "c2"):
        ref2va = _for_cell(nodes, "MiniMaxH3ReferenceToVideo", cell_id)
        assert ref2va["inputs"]["clip"] == SENTINEL["clip"]
        assert ref2va["inputs"]["vae"] == SENTINEL["video_vae"]
        assert ref2va["inputs"]["audio_vae"] == SENTINEL["audio_vae"]


def test_switching_the_export_off_removes_the_whole_chain():
    spec = _spec(render={"exportVideo": False})
    assert spec.render.export_video is False
    nodes = _build(spec, export_video=False)
    assert _nodes(nodes, "CreateVideo") == {}
    assert _nodes(nodes, "SaveVideo") == {}
    assert _nodes(nodes, "VAEDecodeAudio") == {}
    for cell_id in ("c1", "c2"):
        assert "clip" not in _for_cell(nodes, "H3SheetCellSink", cell_id)["inputs"]


def test_the_flag_round_trips_and_defaults_on():
    assert _spec().render.export_video is True
    assert _spec(render={"exportVideo": False}).render.export_video is False
    spec = _spec(render={"exportVideo": False})
    assert ss.parse_sheet_spec(spec.to_dict()).render.export_video is False


def test_the_summary_says_where_the_clips_go():
    spec = _spec()
    lines = pl.work_summary(spec, pl.cell_work_items(spec))
    joined = "\n".join(lines)
    assert f"minimax_sheets/{spec.name}/clips/" in joined
    assert "24 fps" in joined
    off = _spec(render={"exportVideo": False})
    assert "Cell clips" not in "\n".join(pl.work_summary(off, pl.cell_work_items(off)))


# --------------------------------------------------------------------------- #
# the panel side of it
# --------------------------------------------------------------------------- #
@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "output_root", lambda: tmp_path)
    return store_mod.SheetStore("clip sheet", node_id="9").ensure()


def test_the_listing_points_at_the_newest_clip_of_a_cell(store):
    store.save_cell_frames("c1", [np.zeros((8, 8, 3), dtype=np.uint8)])
    clips = store.dir / store_mod.CLIPS_DIR
    clips.mkdir(parents=True, exist_ok=True)
    (clips / "c1_00001_.mp4").write_bytes(b"old")
    (clips / "c1_00002_.mp4").write_bytes(b"new")
    (clips / "other_00001_.mp4").write_bytes(b"other")
    listing = store.scan(spec={"cells": [{"id": "c1"}]})
    cell = next(item for item in listing["cells"] if item["id"] == "c1")
    assert cell["clipFile"] == "c1_00002_.mp4"
    assert "c1_00002_.mp4" in cell["clipUrl"]
    assert "type=output" in cell["clipUrl"]


def test_a_cell_without_a_clip_reports_none(store):
    store.save_cell_frames("c1", [np.zeros((8, 8, 3), dtype=np.uint8)])
    listing = store.scan(spec={"cells": [{"id": "c1"}]})
    cell = next(item for item in listing["cells"] if item["id"] == "c1")
    assert cell["clipUrl"] == "" and cell["clipFile"] == ""
    assert store.cell_clip_path("c1") is None


def test_only_the_newest_clip_of_a_cell_is_kept(store):
    """A re-render adds a clip (SaveVideo counts); the folder should not pile up."""
    clips = store.dir / store_mod.CLIPS_DIR
    clips.mkdir(parents=True, exist_ok=True)
    older = clips / "c1_00001_.mp4"
    newer = clips / "c1_00002_.mp4"
    other = clips / "c2_00001_.mp4"
    for path in (older, newer, other):
        path.write_bytes(b"x")
    import os
    import time

    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    removed = store.prune_cell_clips("c1")
    assert removed == ["c1_00001_.mp4"]
    assert newer.is_file(), "the newest take is the one that stays"
    assert other.is_file(), "another cell's clip is not touched"
    assert store.cell_clip_path("c1").name == "c1_00002_.mp4"
