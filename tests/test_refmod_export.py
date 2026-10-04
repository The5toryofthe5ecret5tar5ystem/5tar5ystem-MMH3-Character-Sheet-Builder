"""RefMod export - the sheet as a ComfyUI-MiniMaxH3Mod bundle.

No GPU, no ComfyUI-MiniMaxH3Mod install and no VAE: the fake pack below speaks their
API (``Create H3 RefMod`` returns an ``io.NodeOutput``-shaped object, the bundle save
and path helpers are the real contract), so what is pinned here is OUR side of it -
which members get built from what, in which order, with which names, and what the
user is told when the optional dependency is missing.

The one thing this cannot check is the VAE math: that belongs to their pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from h3cs import refmod_export as rx
from h3cs import sheet_store as store_mod


# --------------------------------------------------------------------------- fakes
class FakeMod:
    """Stands in for their ``H3RefMod`` dataclass."""

    def __init__(self, name, kind="video", latent_t=1, source="stack", tokens=None):
        self.name = name
        self.kind = kind
        self.latent_t = int(latent_t)
        self.source = source
        self.token_count = int(tokens if tokens is not None else latent_t * 10)
        self.description = ""
        self.concept_type = "identity"


def fake_pack(tmp_path):
    """A pack object shaped like theirs, recording every call."""
    calls: dict[str, list] = {"extract": [], "audio": [], "bundle": [], "paths": []}

    class Extract:
        @staticmethod
        def execute(**kwargs):
            calls["extract"].append(kwargs)
            name = kwargs["name"]
            refs = len(kwargs.get("refs_image") or {})
            mod = FakeMod(name=name, kind="video", latent_t=refs, source="stack",
                          tokens=refs * 100)
            return SimpleNamespace(result=([(mod, 1.0)], "details"))

    def make_audio_mod(vae, audio, name, max_seconds=30.0, max_tokens=5120,
                       budget_policy="error", description="", concept_type="voice"):
        calls["audio"].append(
            {"vae": vae, "audio": audio, "name": name, "max_seconds": max_seconds,
             "max_tokens": max_tokens, "policy": budget_policy,
             "description": description, "concept_type": concept_type}
        )
        return FakeMod(name=name, kind="audio", latent_t=int(max_seconds * 40),
                       source="audio", tokens=int(max_seconds * 80))

    def save_bundle(path, name, mods):
        # Their contract: a list of (mod, strength) pairs, exactly what their own Save
        # node forwards. Unpacking here means the suite fails on a bare mod list.
        pairs = [(mod, strength) for mod, strength in mods]
        calls["bundle"].append({"path": str(path), "name": name,
                                "mods": [mod for mod, _strength in pairs],
                                "strengths": [strength for _mod, strength in pairs]})
        return str(path) + ".safetensors"

    def mod_output_path(name, subfolder=""):
        calls["paths"].append({"name": name, "subfolder": subfolder})
        return str(Path(tmp_path) / "refmods" / subfolder / name)

    pack = SimpleNamespace(
        __name__="fake_pack",
        __file__=str(Path(tmp_path) / "fake_pack" / "__init__.py"),
        NODE_CLASS_MAPPINGS={"MiniMaxH3RefModExtract": Extract},
        audio=SimpleNamespace(make_audio_mod=make_audio_mod),
        bundle=SimpleNamespace(save_bundle=save_bundle),
        common=SimpleNamespace(mod_output_path=mod_output_path),
    )
    return pack, calls


def stills(count: int, size: int = 8) -> torch.Tensor:
    """A batch of distinct stills, like the Builder's ``cells`` output."""
    batch = torch.zeros((count, size, size, 3), dtype=torch.float32)
    for index in range(count):
        batch[index] = index / max(1, count)
    return batch


VOICE = {"waveform": torch.zeros((1, 2, 32000), dtype=torch.float32), "sample_rate": 32000}


@pytest.fixture()
def sheets_root(tmp_path, monkeypatch):
    """Point the store at a scratch output folder, like the grid tests do."""
    root = tmp_path / "minimax_sheets"
    monkeypatch.setattr(store_mod, "sheets_root", lambda: root)
    return root


def make_sheet_folder(root: Path, name: str, cells: list[str], clips: list[str]) -> Path:
    """A sheet folder with the manifest and the clips the export reads."""
    folder = root / name
    (folder / "clips").mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(
        json.dumps({"cells": {cell: {"index": 0} for cell in cells}}), encoding="utf-8"
    )
    for clip in clips:
        (folder / "clips" / clip).write_bytes(b"not really an mp4")
    return folder


# ------------------------------------------------------------------ member building
def test_the_bundle_holds_appearance_and_voice_members(tmp_path):
    pack, calls = fake_pack(tmp_path)
    result = rx.export_bundle(
        cells=stills(5),
        sheet=stills(1),
        audio=VOICE,
        video_vae="video-vae",
        audio_vae="audio-vae",
        name="elf girl",
        subfolder="character_sheets",
        pack=pack,
    )

    # Two visual members: the picked cells stacked, then the composite.
    first, second = calls["extract"]
    assert list(first["refs_image"]) == ["ref_image_1", "ref_image_2", "ref_image_3",
                                         "ref_image_4", "ref_image_5"]
    assert first["name"] == "elf girl_views"
    assert first["mode"] == "encode"  # "Full Reference" is theirs to name, ours to map
    assert first["save"] is False, "the bundle owns the file, not the extract"
    assert first["vae"] == "video-vae"
    assert list(second["refs_image"]) == ["ref_image_1"]
    assert second["name"] == "elf girl_sheet"

    voice = calls["audio"][0]
    assert voice["name"] == "elf girl_voice"
    assert voice["concept_type"] == "voice"
    assert voice["vae"] == "audio-vae"
    assert voice["audio"] is VOICE

    bundle = calls["bundle"][0]
    assert bundle["name"] == "elf girl"
    assert [mod.name for mod in bundle["mods"]] == [
        "elf girl_views", "elf girl_sheet", "elf girl_voice"
    ]
    assert bundle["strengths"] == [1.0, 1.0, 1.0], "their pairs carry a strength"
    assert result.path.endswith(".safetensors")
    assert bundle["path"] == str(tmp_path / "refmods" / "character_sheets" / "elf girl")
    assert len(result.members) == 3
    assert result.members[2]["kind"] == "audio"
    assert result.members[2]["seconds"] == 30.0
    assert "elf girl_views" in result.report and "elf girl_voice" in result.report


def test_names_are_sanitized_for_the_file_system(tmp_path):
    pack, calls = fake_pack(tmp_path)
    rx.export_bundle(cells=stills(2), video_vae="v", name="people/elf\\girl", pack=pack)
    assert calls["paths"][0]["name"] == "people_elf_girl"
    assert calls["bundle"][0]["mods"][0].name == "people_elf_girl_views"


def test_more_cells_than_their_autogrow_holds_are_sampled_evenly(tmp_path):
    pack, calls = fake_pack(tmp_path)
    rx.export_bundle(cells=stills(20), video_vae="v", name="wide", pack=pack)
    refs = calls["extract"][0]["refs_image"]
    assert len(refs) == rx.MAX_VISUAL_REFS
    # Evenly spread: the first and the last cell are in, so the whole matrix is covered.
    assert torch.equal(refs["ref_image_1"], stills(20)[0:1])
    assert torch.equal(refs[f"ref_image_{rx.MAX_VISUAL_REFS}"], stills(20)[-1:])


def test_compressed_mode_and_its_refinement_steps_reach_their_node(tmp_path):
    pack, calls = fake_pack(tmp_path)
    rx.export_bundle(cells=stills(3), video_vae="v", mode="Compressed Reference",
                     identity=250, ref_resolution=512, max_tokens=0, name="c", pack=pack)
    call = calls["extract"][0]
    assert call["mode"] == "training"
    assert call["identity"] == 250
    assert call["ref_resolution"] == 512
    assert call["max_tokens"] == 0


def test_saving_can_be_switched_off(tmp_path):
    pack, calls = fake_pack(tmp_path)
    result = rx.export_bundle(cells=stills(2), video_vae="v", name="c", save=False, pack=pack)
    assert calls["bundle"] == []
    assert result.path == ""
    assert len(result.mods) == 1
    assert "save is off" in result.report


# ------------------------------------------------------------------------- voices
def test_the_voice_can_come_from_a_cell_clip(tmp_path, sheets_root, monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1", "c2"], clips=["c1_00001_.mp4", "c2_00001_.mp4"])
    loaded: list[str] = []

    def fake_clip_audio(path):
        loaded.append(Path(path).name)
        return VOICE

    monkeypatch.setattr(rx, "clip_audio", fake_clip_audio)

    result = rx.export_bundle(
        cells=stills(2), video_vae="v", audio_vae="a", sheet_dir=str(folder),
        name="run", pack=pack,
    )
    assert loaded == ["c1_00001_.mp4"], "auto takes the first cell that exported a clip"
    assert calls["audio"][0]["name"] == "run_voice_cell1"
    assert any("generated audio of c1_00001_.mp4" in line for line in result.lines)


def test_a_specific_cell_can_supply_the_voice(tmp_path, sheets_root, monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1", "c2"], clips=["c1_00001_.mp4", "c2_00002_.mp4"])
    monkeypatch.setattr(rx, "clip_audio", lambda path: VOICE)
    rx.export_bundle(cells=stills(2), video_vae="v", audio_vae="a", sheet_dir=str(folder),
                     voice_cell=2, name="run", pack=pack)
    assert calls["audio"][0]["name"] == "run_voice_cell2"


def test_voice_cell_zero_means_no_cell_voice(tmp_path, sheets_root, monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1"], clips=["c1_00001_.mp4"])
    monkeypatch.setattr(rx, "clip_audio", lambda path: pytest.fail("must not read audio"))
    rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a", sheet_dir=str(folder),
                     voice_cell=0, name="run", pack=pack)
    assert calls["audio"] == []


def test_a_sheet_without_clips_says_so_instead_of_failing(tmp_path, sheets_root):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    result = rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a",
                              sheet_dir=str(folder), name="run", pack=pack)
    assert calls["audio"] == []
    assert any("no exported cell clip" in line for line in result.lines)
    assert result.mods, "the appearance member is still worth exporting"


def test_both_voice_sources_can_be_members_at_once(tmp_path, sheets_root, monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1"], clips=["c1_00001_.mp4"])
    monkeypatch.setattr(rx, "clip_audio", lambda path: VOICE)
    result = rx.export_bundle(cells=stills(1), sheet=None, audio=VOICE, video_vae="v",
                              audio_vae="a", sheet_dir=str(folder), name="run", pack=pack)
    assert [mod.name for mod in result.mods] == ["run_views", "run_voice", "run_voice_cell1"]


def test_a_voice_member_needs_the_audio_vae(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    with pytest.raises(rx.RefModExportError, match="audio VAE"):
        rx.export_bundle(audio=VOICE, audio_vae=None, name="c", pack=pack)


def test_an_appearance_member_needs_the_video_vae(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    with pytest.raises(rx.RefModExportError, match="video VAE"):
        rx.export_bundle(cells=stills(2), video_vae=None, name="c", pack=pack)


def test_nothing_connected_names_what_to_connect(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    with pytest.raises(rx.RefModExportError, match="nothing to export"):
        rx.export_bundle(video_vae="v", name="c", pack=pack)


# ------------------------------------------------------------------- the folder
def test_a_sheet_folder_resolves_from_a_path_or_a_name(sheets_root):
    folder = make_sheet_folder(sheets_root, "my_sheet", cells=["c1"], clips=[])
    assert rx.sheet_folder(str(folder)) == folder
    assert rx.sheet_folder("my_sheet") == folder
    assert rx.sheet_folder("") is None
    assert rx.sheet_folder(str(sheets_root / "nope")) is None


def test_cell_clips_follow_the_sheet_order_not_the_alphabet(sheets_root):
    # Lexically c10 < c2, the manifest is not.
    folder = make_sheet_folder(sheets_root, "many",
                               cells=[f"c{index}" for index in range(1, 11)],
                               clips=[f"c{index}_00001_.mp4" for index in range(1, 11)])
    assert [path.name for path in rx.cell_clips(folder)][:3] == [
        "c1_00001_.mp4", "c2_00001_.mp4", "c3_00001_.mp4"
    ]
    assert [path.name for path in rx.cell_clips(folder, cell=9)] == ["c10_00001_.mp4"]


def test_clip_selection_has_no_clips_to_offer(sheets_root):
    folder = make_sheet_folder(sheets_root, "empty", cells=["c1"], clips=[])
    assert rx.cell_clips(folder) == []
    assert rx.cell_clips(None) == []


def test_a_re_render_keeps_the_newest_clip(sheets_root):
    folder = make_sheet_folder(sheets_root, "again", cells=["c1"],
                               clips=["c1_00001_.mp4", "c1_00002_.mp4"])
    assert [path.name for path in rx.cell_clips(folder)] == ["c1_00002_.mp4"]


# ---------------------------------------------------------------- the dependency
def test_a_missing_pack_is_reported_with_the_clone_line(tmp_path, monkeypatch):
    monkeypatch.setattr(rx, "loaded_pack", lambda: None)
    monkeypatch.setattr(rx, "pack_dir", lambda: None)
    monkeypatch.setattr(rx, "_PACK", None)
    with pytest.raises(rx.RefModPackMissing) as excinfo:
        rx.load_pack(reload=True)
    assert rx.PACK_URL in str(excinfo.value)
    assert "custom_nodes" in str(excinfo.value)
    assert rx.PACK_TITLE in rx.pack_status()
    assert "not installed" in rx.pack_status()


def test_the_installed_pack_is_found_in_custom_nodes(tmp_path, monkeypatch):
    root = tmp_path / "custom_nodes"
    (root / rx.PACK_DIRNAME).mkdir(parents=True)
    (root / rx.PACK_DIRNAME / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(rx, "custom_nodes_roots", lambda: [root])
    assert rx.pack_dir() == root / rx.PACK_DIRNAME


def test_a_pack_without_the_entry_points_is_reported_as_broken():
    half_pack = SimpleNamespace(__name__="half", NODE_CLASS_MAPPINGS={})
    with pytest.raises(rx.RefModPackMissing, match="does not expose"):
        rx.entry_points(half_pack)


def test_the_loaded_pack_is_reused_when_comfyui_already_has_it(monkeypatch):
    fake = SimpleNamespace(__file__="/x/custom_nodes/ComfyUI-MiniMaxH3Mod/__init__.py",
                           NODE_CLASS_MAPPINGS={})
    monkeypatch.setitem(__import__("sys").modules, "ComfyUI-MiniMaxH3Mod", fake)
    assert rx.loaded_pack() is fake


# ---------------------------------------------------------------------- the node
def test_the_node_maps_its_widgets_onto_the_export(tmp_path, monkeypatch):
    from h3cs.nodes import refmod as node_mod

    seen: dict = {}

    def fake_export(**kwargs):
        seen.update(kwargs)
        return rx.ExportResult(mods=["m"], members=[], path=str(tmp_path / "x.safetensors"),
                               lines=["saved: x"])

    monkeypatch.setattr(node_mod, "export_bundle", fake_export)
    out = node_mod.H3SheetRefMod.execute(
        video_vae="v", audio_vae="a", cells=stills(2), sheet=stills(1), audio=VOICE,
        sheet_dir="/tmp/sheet", name="hero", subfolder="people", mode="Full Reference",
        ref_resolution=768, max_tokens=2048, refine_steps=111, concept_type="identity",
        description="a hero", voice_cell=2, voice_seconds=12.5,
    ).result

    mods, path, report = out
    assert mods == ["m"]
    assert path.endswith("x.safetensors")
    assert "Saved:" in report and "Load H3 RefMods" in report
    assert seen["video_vae"] == "v" and seen["sheet_dir"] == "/tmp/sheet"
    assert seen["identity"] == 111, "refine_steps is their 'identity' widget"
    assert seen["voice_max_seconds"] == 12.5
    assert seen["ref_resolution"] == 768 and seen["max_tokens"] == 2048
    assert seen["voice_cell"] == 2 and seen["subfolder"] == "people"


def test_the_node_turns_a_missing_pack_into_a_readable_error(monkeypatch):
    from h3cs.nodes import refmod as node_mod

    def boom(**_kwargs):
        raise rx.RefModPackMissing(f"{rx.PACK_TITLE} is not installed - {rx.INSTALL_LINE}.")

    monkeypatch.setattr(node_mod, "export_bundle", boom)
    with pytest.raises(ValueError, match="H3 Sheet"):
        node_mod.H3SheetRefMod.execute(video_vae="v", cells=stills(1))


def test_the_node_schema_and_execute_agree(tmp_path):
    """A widget the schema offers but execute rejects fails only at run time."""
    import inspect

    from h3cs.nodes import refmod as node_mod

    schema = node_mod.H3SheetRefMod.define_schema()
    params = set(inspect.signature(node_mod.H3SheetRefMod.execute).parameters)
    link_inputs = {"video_vae", "audio_vae", "cells", "sheet", "audio"}
    missing = [
        item.id for item in schema.inputs
        if item.id and item.id not in link_inputs and item.id not in params
    ]
    assert not missing, f"execute() would reject {missing}"
    assert node_mod.NODE_CLASS_MAPPINGS["H3SheetRefMod"] is node_mod.H3SheetRefMod
