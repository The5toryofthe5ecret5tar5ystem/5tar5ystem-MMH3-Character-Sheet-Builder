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
from datetime import datetime
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


@pytest.fixture()
def input_root(tmp_path, monkeypatch):
    """ComfyUI's ``input`` folder, where a manifest's reference file name resolves.

    ``LoadAudio`` reads references from the input folder, so that is where the export
    looks first; the test pretends ``tmp_path/input`` is it instead of importing core.
    """
    folder = tmp_path / "input"
    folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rx, "_reference_roots", lambda _folder=None: [folder])
    return folder


def make_sheet_folder(
    root: Path,
    name: str,
    cells: list[str],
    clips: list[str],
    audios: list[str] | None = None,
    input_root: Path | None = None,
) -> Path:
    """A sheet folder with the manifest and the clips the export reads.

    ``audios`` writes ``spec.refs.audios`` the way the Builder's References tab does
    and puts the files in the input folder - the reference audio the sheet was rendered
    with, which is what the voice ladder offers first.
    """
    folder = root / name
    (folder / "clips").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"cells": {cell: {"index": 0} for cell in cells}}
    if audios:
        manifest["spec"] = {
            "refs": {
                "audios": [
                    {"audioFile": audio, "role": "voice", "enabled": True}
                    for audio in audios
                ]
            }
        }
        for audio in audios:
            target = (input_root if input_root is not None else folder) / audio
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF")
    (folder / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")
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
def test_the_voice_comes_from_the_sheets_own_reference_audio(
    tmp_path, sheets_root, input_root, monkeypatch
):
    """The reference audio is the point: it is the voice the sheet was built from.

    A cell clip only holds the ~1s H3 generated for that take, so the ladder takes the
    reference file the manifest recorded (the Builder's References tab), and it is read
    from the input folder the way ``LoadAudio`` would.
    """
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(
        sheets_root, "sheet_run", cells=["c1", "c2"],
        clips=["c1_00001_.mp4", "c2_00001_.mp4"],
        audios=["flaffy voice 01.wav"], input_root=input_root,
    )
    loaded: list[str] = []

    def fake_clip_audio(path):
        loaded.append(Path(path).name)
        return VOICE

    monkeypatch.setattr(rx, "clip_audio", fake_clip_audio)

    result = rx.export_bundle(cells=stills(2), video_vae="v", audio_vae="a", audio=VOICE,
                              sheet_dir=str(folder), name="run", pack=pack)
    assert loaded == ["flaffy voice 01.wav"], "the clips are not read once a reference wins"
    assert calls["audio"][0]["name"] == "run_voice"
    assert any("the sheet's reference audio (flaffy voice 01.wav)" in line
               for line in result.lines)
    assert any("not used" in line and "cell clip" in line for line in result.lines), (
        "the report says what the ladder passed over, so 'voice_cell' is discoverable"
    )


def test_every_reference_audio_file_is_joined_in_order(
    tmp_path, sheets_root, input_root, monkeypatch
):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(
        sheets_root, "sheet_run", cells=["c1"], clips=[],
        audios=["voice_a.wav", "voice_b.wav"], input_root=input_root,
    )
    monkeypatch.setattr(rx, "clip_audio", lambda path: VOICE)
    result = rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a",
                              sheet_dir=str(folder), name="run", pack=pack)
    assert calls["audio"][0]["name"] == "run_voice"
    assert any("2 files joined" in line for line in result.lines)


def test_the_joined_cell_clips_are_the_fallback(tmp_path, sheets_root, monkeypatch):
    """No reference audio in the manifest: every exported clip is joined, not just one."""
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
    assert loaded == ["c1_00001_.mp4", "c2_00001_.mp4"]
    assert calls["audio"][0]["name"] == "run_voice_cells"
    assert any("the audio of 2 exported cell clip(s)" in line for line in result.lines)


def test_a_reference_that_is_gone_falls_through_instead_of_failing(
    tmp_path, sheets_root, input_root, monkeypatch
):
    """A tidy-up must not cost the export: a missing reference file is skipped."""
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"],
                               clips=["c1_00001_.mp4"],
                               audios=["deleted.wav"], input_root=input_root)
    (input_root / "deleted.wav").unlink()
    monkeypatch.setattr(rx, "clip_audio", lambda path: VOICE)
    result = rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a",
                              sheet_dir=str(folder), name="run", pack=pack)
    assert calls["audio"][0]["name"] == "run_voice_cells"
    assert any("deleted.wav" in line and "not on disk" in line for line in result.lines), (
        "the report names the reference it could not find, so it can be put back"
    )


def test_a_forced_cell_ignores_the_reference_audio(tmp_path, sheets_root, input_root,
                                                   monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1", "c2"], clips=["c1_00001_.mp4", "c2_00002_.mp4"],
                               audios=["voice.wav"], input_root=input_root)
    loaded: list[str] = []
    monkeypatch.setattr(rx, "clip_audio",
                        lambda path: (loaded.append(Path(path).name), VOICE)[1])
    rx.export_bundle(cells=stills(2), video_vae="v", audio_vae="a", sheet_dir=str(folder),
                     voice_cell=2, name="run", pack=pack)
    assert loaded == ["c2_00002_.mp4"]
    assert calls["audio"][0]["name"] == "run_voice_cell2"


def test_voice_cell_zero_means_no_cell_voice(tmp_path, sheets_root, monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run",
                               cells=["c1"], clips=["c1_00001_.mp4"])
    monkeypatch.setattr(rx, "clip_audio", lambda path: pytest.fail("must not read audio"))
    rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a", sheet_dir=str(folder),
                     voice_cell=0, name="run", pack=pack)
    assert calls["audio"] == []


def test_voice_cell_zero_keeps_the_sheet_out_of_the_voice(
    tmp_path, sheets_root, input_root, monkeypatch
):
    """``0`` is the escape hatch when a wired audio should win over the sheet's own."""
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"],
                               clips=["c1_00001_.mp4"], audios=["voice.wav"],
                               input_root=input_root)
    monkeypatch.setattr(rx, "clip_audio", lambda path: pytest.fail("must not read audio"))
    rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a", audio=VOICE,
                     sheet_dir=str(folder), voice_cell=0, name="run", pack=pack)
    assert calls["audio"][0]["name"] == "run_voice"
    assert calls["audio"][0]["audio"] is VOICE


def test_a_sheet_without_clips_says_so_instead_of_failing(tmp_path, sheets_root):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    result = rx.export_bundle(cells=stills(1), video_vae="v", audio_vae="a",
                              sheet_dir=str(folder), name="run", pack=pack)
    assert calls["audio"] == []
    assert any("no exported cell clip" in line for line in result.lines)
    assert result.mods, "the appearance member is still worth exporting"


def test_a_connected_audio_is_the_last_rung(tmp_path, sheets_root):
    """Nothing in the sheet: the wired clip is still a voice, and the report says why."""
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    result = rx.export_bundle(cells=stills(1), sheet=None, audio=VOICE, video_vae="v",
                              audio_vae="a", sheet_dir=str(folder), name="run", pack=pack)
    assert [mod.name for mod in result.mods] == ["run_views", "run_voice"]
    assert calls["audio"][0]["audio"] is VOICE
    assert any("the connected audio" in line for line in result.lines)


def test_sheet_audio_references_skips_disabled_and_missing_rows(
    tmp_path, sheets_root, input_root
):
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[],
                               audios=["keep.wav"], input_root=input_root)
    manifest = json.loads((folder / "sheet_run.json").read_text(encoding="utf-8"))
    manifest["spec"]["refs"]["audios"] += [
        {"audioFile": "off.wav", "role": "voice", "enabled": False},
        {"audioFile": "gone.wav", "role": "voice", "enabled": True},
    ]
    (folder / "sheet_run.json").write_text(json.dumps(manifest), encoding="utf-8")

    found = rx.sheet_audio_references(folder)
    assert [path.name for path in found] == ["keep.wav"]


def test_a_manifest_without_a_spec_has_no_reference_audio(tmp_path, sheets_root):
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    assert rx.sheet_audio_references(folder) == []
    assert rx.sheet_audio_references(None) == []


# ------------------------------------------------------------------- joining audio
def tone(seconds: float, rate: int = 32000, channels: int = 1) -> dict:
    """An AUDIO value shaped like theirs: ``[1, channels, samples]``."""
    return {
        "waveform": torch.zeros((1, channels, int(seconds * rate)), dtype=torch.float32),
        "sample_rate": rate,
    }


def test_clips_are_joined_as_samples_at_h3s_rate():
    joined = rx.concat_audio([tone(1.0), tone(0.5, rate=16000)])
    assert joined["sample_rate"] == rx.H3_AUDIO_RATE
    assert joined["waveform"].shape == (1, 1, 48000), "1s + 0.5s, all at 32 kHz"


def test_a_stereo_clip_makes_the_join_stereo():
    joined = rx.concat_audio([tone(0.25, channels=1), tone(0.25, channels=2)])
    assert joined["waveform"].shape == (1, 2, 16000), "mono is duplicated, like theirs"


def test_the_join_is_capped_not_extended():
    joined = rx.concat_audio([tone(3.0), tone(3.0)], max_seconds=2.0)
    assert joined["waveform"].shape == (1, 1, 64000), "voice_seconds is a ceiling"
    assert rx.concat_audio([]) is None


def test_audio_parts_refuses_something_that_is_not_an_audio_value():
    with pytest.raises(rx.RefModExportError, match="AUDIO value"):
        rx.audio_parts({"waveform": torch.zeros(1)})
    with pytest.raises(rx.RefModExportError, match="one batch"):
        rx.audio_parts({"waveform": torch.zeros((2, 1, 100)), "sample_rate": 32000})


# ---------------------------------------------------------------------- row share
def test_the_report_gives_every_member_its_share_of_the_rows(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    result = rx.export_bundle(cells=stills(8), sheet=None, audio=VOICE, video_vae="v",
                              audio_vae="a", name="hero", pack=pack)
    # The fake pack counts 100 tokens per still and 80 per second of voice (30s).
    assert any("800 tokens" in line and "of the bundle" in line for line in result.lines)
    assert any("2400 tokens" in line and "of the bundle" in line for line in result.lines)


def test_a_thin_voice_member_gets_the_copies_hint(tmp_path):
    """Rows are the whole story: 76 of 8,956 is why an A/B can look like noise.

    (Measured on a real bundle: an 0.95s cell clip next to a 640x384/124f target - and
    the target itself adds thousands of rows the bundle report cannot see.)
    """
    members = [
        {"name": "views", "kind": "video", "tokens": 8880},
        {"name": "voice", "kind": "audio", "tokens": 76},
    ]
    hint = rx.share_hint(members, 8956)
    assert len(hint) == 1
    assert "76 of the bundle's 8956 rows (0.8%)" in hint[0]
    assert "copies 3" in hint[0]


def test_a_hint_says_so_when_copies_cannot_fix_it():
    members = [
        {"name": "views", "kind": "video", "tokens": 100000},
        {"name": "voice", "kind": "audio", "tokens": 40},
    ]
    hint = rx.share_hint(members, 100040)
    assert "even 10 copies" in hint[0] and "voice_seconds" in hint[0]


def test_a_voice_with_a_real_share_gets_no_hint():
    members = [
        {"name": "views", "kind": "video", "tokens": 8000},
        {"name": "voice", "kind": "audio", "tokens": 2000},
    ]
    assert rx.share_hint(members, 10000) == []
    assert rx.share_hint([], 0) == []
    assert rx.share_hint([members[0]], 8880) == [], "an appearance-only bundle is fine"


def test_a_voice_member_needs_the_audio_vae(tmp_path):
    """The encoder refuses a missing/wrong VAE - that is their guard, kept as a unit."""
    pack, _calls = fake_pack(tmp_path)
    api = rx.entry_points(pack)
    with pytest.raises(rx.RefModExportError, match="audio VAE"):
        rx.build_voice_mod(api, name="v", audio=VOICE, audio_vae=None)


def test_a_connected_audio_without_the_audio_vae_is_skipped_not_fatal(tmp_path):
    """Forgetting the audio VAE must not cost the appearance members.

    The export is still worth having, so the voice is dropped and the report says which
    file to connect (the node leads with it in the status line).
    """
    pack, calls = fake_pack(tmp_path)
    result = rx.export_bundle(cells=stills(2), sheet=None, audio=VOICE, video_vae="v",
                              audio_vae=None, name="hero", pack=pack)
    assert [mod.name for mod in result.mods] == ["hero_views"]
    assert calls["audio"] == []
    assert any("skipped" in line and "minimax_h3_audio_vae_fp32" in line
               for line in result.lines)
    assert result.path, "the bundle is still written"


def test_a_cell_voice_without_the_audio_vae_is_skipped_too(tmp_path, sheets_root,
                                                           monkeypatch):
    pack, calls = fake_pack(tmp_path)
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"],
                               clips=["c1_00001_.mp4"])
    monkeypatch.setattr(rx, "clip_audio", lambda path: pytest.fail("must not decode"))
    result = rx.export_bundle(cells=stills(1), video_vae="v", audio_vae=None,
                              sheet_dir=str(folder), name="run", pack=pack)
    assert calls["audio"] == []
    assert any("skipped" in line for line in result.lines)
    assert [mod.name for mod in result.mods] == ["run_views"]


def test_an_appearance_member_needs_the_video_vae(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    with pytest.raises(rx.RefModExportError, match="video VAE"):
        rx.export_bundle(cells=stills(2), video_vae=None, name="c", pack=pack)


def test_nothing_connected_names_what_to_connect(tmp_path):
    pack, _calls = fake_pack(tmp_path)
    with pytest.raises(rx.RefModExportError, match="nothing to export"):
        rx.export_bundle(video_vae="v", name="c", pack=pack)


# -------------------------------------------------------------------- the name
def test_a_date_token_in_the_name_is_expanded():
    """The Builder expands ``output_name`` per run; the export has to expand its own ``name``.

    Otherwise ``hero-%date:hhmmss%`` is written to disk with the placeholder still in it,
    which is what a user reads as "the export ignores my date code".
    """
    when = datetime(2026, 10, 4, 15, 30, 12)
    assert rx.export_name("elf_girl-%date:hhmmss%", None, now=when) == "elf_girl-153012"
    assert rx.export_name("%date%", None, now=when) == "20261004_153012"
    assert rx.export_name("take-%date:yyyy-MM-dd%", None, now=when) == "take-2026-10-04"


def test_a_plain_name_is_left_exactly_as_typed():
    # No auto stamp here (unlike the sheet folder): a bundle is a file you name on purpose,
    # and re-export over on purpose.
    assert rx.export_name("character") == "character"
    assert rx.export_name("elf girl v2") == "elf girl v2"
    assert rx.export_name("") == "" and rx.export_name(None) == ""


def test_a_name_gets_no_characters_a_file_name_cannot_carry():
    when = datetime(2026, 10, 4, 15, 30, 12)
    assert rx.export_name("take-%date:HH:mm%", None, now=when) == "take-15-30"


def test_a_seed_token_uses_the_seed_the_sheet_was_rendered_with(tmp_path, sheets_root):
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    manifest = json.loads((folder / "sheet_run.json").read_text(encoding="utf-8"))
    manifest["spec"] = {"render": {"seed": 12345}}
    (folder / "sheet_run.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert rx.sheet_seed(folder) == 12345
    assert rx.export_name("hero-%seed%", folder) == "hero-12345"


def test_a_seed_token_without_a_manifest_stays_literal(tmp_path, sheets_root):
    """An invented seed would be worse than a placeholder: the sheet's manifest is the only
    place the run's seed is written down."""
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    assert rx.sheet_seed(folder) is None
    assert rx.sheet_seed(None) is None
    assert rx.export_name("hero-%seed%", folder) == "hero-%seed%"


def test_a_negative_seed_is_a_sentinel_not_a_seed(tmp_path, sheets_root):
    folder = make_sheet_folder(sheets_root, "sheet_run", cells=["c1"], clips=[])
    manifest = json.loads((folder / "sheet_run.json").read_text(encoding="utf-8"))
    manifest["spec"] = {"render": {"seed": -1}}
    (folder / "sheet_run.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert rx.sheet_seed(folder) is None
    assert rx.export_name("hero-%seed%", folder) == "hero-%seed%"


def test_the_export_writes_the_expanded_name(tmp_path):
    pack, calls = fake_pack(tmp_path)
    result = rx.export_bundle(cells=stills(1), video_vae="v",
                              name="hero-%date:hhmmss%", pack=pack)
    name = calls["paths"][0]["name"]
    assert name.startswith("hero-") and "%" not in name
    assert calls["bundle"][0]["name"] == name, "the bundle carries the expanded name"
    assert [mod.name for mod in calls["bundle"][0]["mods"]] == [f"{name}_views"]
    assert name in result.path


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
