# ComfyUI-H3-Character-Sheet - RefMod export bridge.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Export a finished sheet as a RefMod bundle (for Luisacaotica/ComfyUI-MiniMaxH3Mod).

A RefMod is that pack's no-training reference adapter: a VAE latent that rides H3's
native ref2va path for a fraction of the tokens a real reference costs. Its version 5
container holds SEVERAL members in one file, and that is what makes an
"appearance + voice" export possible:

    refmod_meta = {_format_version: 5, kind: "bundle", name, members: [...]}
    ref_0 = [1, 24, T, H, W]   appearance (one member per visual reference group)
    ref_1 = [1, 32, 2, T]      voice (the H3 audio codec, 32 kHz)

Everything the sheet already has maps onto that:

* ``cells`` - the picked still of every cell, stacked as one member: a multi-view
  identity board. This is how their own ``elf_girl`` mod was extracted
  (``mode=encode, source=stack, pool="full-res 864x1536px (short-edge cap 1024px)"``).
* ``sheet`` - the composited sheet as a second member, so the layout that was
  authored for ref2va is in the bundle too.
* the voice - either an ``AUDIO`` input, or the audio track of a cell's exported
  clip (``<sheet>/clips/<cell>_00001_.mp4``: the voice H3 generated with that take).

Both encoders are THEIR code - ``Create H3 RefMod`` for the visual members and
``audio.make_audio_mod`` for the voice - so the file is exactly what their loader
expects and this pack never duplicates VAE math. The dependency is optional: without
the pack, :func:`export_bundle` raises :class:`RefModPackMissing` naming the clone
line, and every other node in this pack keeps working.

The bundle is written with their ``bundle.save_bundle`` into
``models/refmods/<subfolder>/<name>.safetensors`` - the folder ``Load H3 RefMods``
lists - so the export appears in that dropdown after a ComfyUI reload.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .name_tokens import expand_tokens, has_tokens

log = logging.getLogger("H3-Character-Sheet.refmod")

PACK_DIRNAME = "ComfyUI-MiniMaxH3Mod"
PACK_TITLE = "ComfyUI-MiniMaxH3Mod"
PACK_URL = "https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod"
INSTALL_LINE = f"clone {PACK_URL} into ComfyUI/custom_nodes/ and restart ComfyUI"

#: Their ``Create H3 RefMod`` autogrow accepts up to 16 stills; a sheet with more
#: cells is sampled down to that many views (evenly, so the whole matrix is covered).
MAX_VISUAL_REFS = 16
#: Their bundle format refuses more than this many members.
MAX_MEMBERS = 256
#: ``voice_cell`` sentinel: walk the voice ladder - the sheet's own reference audio,
#: else every exported cell clip joined, else the connected audio.
VOICE_AUTO = -1
#: H3's audio clock: 32 kHz in, 40 latent frames per second out (2 rows per frame).
H3_AUDIO_RATE = 32000
#: Below this share of the bundle a member is a rounding error rather than a
#: reference. Measured on a real bundle: an 0.95s voice member is 76 of ~7,000 rows
#: (~0.5%) and the video being generated adds thousands more, so an A/B of "voice 1.0"
#: against "voice 0.0" came out at noise level. Their loader's ``copies`` widget is the
#: fix - it injects a member more than once - so the report says which number would put
#: the voice on the map.
VOICE_SHARE_HINT = 0.02
#: The modes this pack offers, mapped onto their internal names (their UI accepts
#: both spellings; naming ours explicitly keeps this working if they rename again).
MODES = {"Full Reference": "encode", "Compressed Reference": "training"}

#: A voice member is an H3 audio-VAE encode, so it needs that VAE. Rather than fail an
#: export whose appearance members are perfectly fine, the voice is skipped and the
#: report says why - with the exact filename to load.
NO_AUDIO_VAE = (
    "skipped - connect the MiniMax H3 audio VAE to 'audio_vae' "
    "(VAELoader -> minimax_h3_audio_vae_fp32.safetensors); the appearance members are "
    "still exported"
)

VIDEO_SUFFIXES = (".mp4", ".mkv", ".webm", ".mov")

_CLIPS_DIR = "clips"
_PICKS_NAME = "picks.json"


class RefModPackMissing(RuntimeError):
    """ComfyUI-MiniMaxH3Mod is not installed (or could not be imported)."""


class RefModExportError(ValueError):
    """The export was asked for something it cannot build."""


# --------------------------------------------------------------------- the pack


def custom_nodes_roots() -> list[Path]:
    """Candidate ``custom_nodes`` folders, nearest first."""
    roots: list[Path] = []
    # This file lives at <custom_nodes>/<pack>/h3_character_sheet/refmod_export.py,
    # so the third parent is the custom_nodes folder that holds both packs.
    here = Path(__file__).resolve()
    if len(here.parents) >= 3:
        roots.append(here.parents[2])
    try:
        import folder_paths  # noqa: PLC0415 - only available inside ComfyUI

        for entry in folder_paths.get_folder_paths("custom_nodes") or []:
            roots.append(Path(entry))
    except Exception:  # noqa: BLE001 - a bare checkout has no folder_paths
        pass
    unique: list[Path] = []
    for root in roots:
        resolved = Path(root)
        if resolved not in unique:
            unique.append(resolved)
    return unique


def pack_dir() -> Path | None:
    """Where ComfyUI-MiniMaxH3Mod is installed, or ``None`` when it is not."""
    for root in custom_nodes_roots():
        candidate = root / PACK_DIRNAME
        if (candidate / "__init__.py").is_file():
            return candidate
    return None


def loaded_pack() -> Any | None:
    """The pack as ComfyUI itself already imported it.

    Preferred over a fresh import: two copies of their module would mean two
    ``H3RefMod`` classes, and a mod built here should be the same kind of object
    their loaders and Apply node hand around. (They duck-type mods today, so this is
    hygiene rather than a hard requirement - but it costs nothing to prefer.)
    """
    for module in list(sys.modules.values()):
        file = getattr(module, "__file__", None)
        if not file:
            continue
        path = Path(str(file))
        if path.name != "__init__.py" or path.parent.name != PACK_DIRNAME:
            continue
        if hasattr(module, "NODE_CLASS_MAPPINGS"):
            return module
    return None


def import_pack(directory: Path) -> Any:
    """Import the installed pack as a package (their modules use relative imports)."""
    alias = f"_h3sheet_{PACK_DIRNAME.replace('-', '_')}"
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        alias, directory / "__init__.py", submodule_search_locations=[str(directory)]
    )
    if spec is None or spec.loader is None:
        raise RefModPackMissing(f"{PACK_TITLE} at {directory} is not importable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - reported as a missing dependency
        sys.modules.pop(alias, None)
        raise RefModPackMissing(
            f"{PACK_TITLE} is installed at {directory} but failed to import: {exc}"
        ) from exc
    log.debug("RefMod export: imported %s from %s", PACK_TITLE, directory)
    return module


def load_pack(*, reload: bool = False) -> Any:
    """The pack module, or :class:`RefModPackMissing`."""
    global _PACK
    if _PACK is not None and not reload:
        return _PACK
    pack = loaded_pack()
    if pack is None:
        directory = pack_dir()
        if directory is None:
            raise RefModPackMissing(f"{PACK_TITLE} is not installed - {INSTALL_LINE}.")
        pack = import_pack(directory)
    _PACK = pack
    return pack


_PACK: Any = None


def pack_status() -> str:
    """One line for a report or a tooltip: installed where, or what to clone."""
    pack = loaded_pack()
    if pack is not None:
        return f"{PACK_TITLE}: loaded ({Path(str(pack.__file__)).parent.name})"
    directory = pack_dir()
    if directory is not None:
        return f"{PACK_TITLE}: installed at {directory}"
    return f"{PACK_TITLE}: not installed - {INSTALL_LINE}"


@dataclass(frozen=True)
class _Api:
    """The handful of their entry points this module calls."""

    extract: Any
    make_audio_mod: Any
    save_bundle: Any
    mod_output_path: Any


def _submodule(pack: Any, name: str) -> Any:
    """Their submodule by attribute or import; ``None`` when it is not there."""
    module = getattr(pack, name, None)
    if module is not None:
        return module
    try:
        return importlib.import_module(f"{pack.__name__}.{name}")
    except Exception:  # noqa: BLE001 - entry_points() reports it, with context
        return None


def entry_points(pack: Any) -> _Api:
    """Resolve their API, complaining clearly if their layout changed."""
    classes = getattr(pack, "NODE_CLASS_MAPPINGS", None) or {}
    audio = _submodule(pack, "audio")
    bundle = _submodule(pack, "bundle")
    common = _submodule(pack, "common")
    extract = classes.get("MiniMaxH3RefModExtract")
    make_audio_mod = getattr(audio, "make_audio_mod", None)
    save_bundle = getattr(bundle, "save_bundle", None)
    mod_output_path = getattr(common, "mod_output_path", None)
    missing = [
        label
        for label, value in (
            ("Create H3 RefMod (MiniMaxH3RefModExtract)", extract),
            ("audio.make_audio_mod", make_audio_mod),
            ("bundle.save_bundle", save_bundle),
            ("common.mod_output_path", mod_output_path),
        )
        if value is None
    ]
    if missing:
        raise RefModPackMissing(
            f"{PACK_TITLE} does not expose {', '.join(missing)}; "
            f"update it (this pack is built against 0.2.x)."
        )
    return _Api(
        extract=extract,
        make_audio_mod=make_audio_mod,
        save_bundle=save_bundle,
        mod_output_path=mod_output_path,
    )


# ------------------------------------------------------------------ the sheet


def sanitize_name(name: Any, fallback: str = "character") -> str:
    """Their ``_sanitize_name`` rule: no path separators in a mod name."""
    text = str(name or "").strip().replace("/", "_").replace("\\", "_")
    return text or fallback


#: Characters a file name may not carry on every filesystem, and what to write instead.
#: Only reachable through an expanded placeholder (``%date:HH:mm%`` asks for a colon), so it
#: is applied to the expanded name and never to the member names, which keep their spaces.
_UNSAFE_FILE_CHARS = str.maketrans({":": "-", "*": "_", "?": "_", '"': "'",
                                    "<": "(", ">": ")", "|": "-"})


def sheet_seed(folder: Path | str | None) -> int | None:
    """The seed the sheet was rendered with, when its manifest recorded one.

    The sheet node expands ``%seed%`` with the seed of its run, so a bundle can only honour
    that placeholder if the run wrote it down - which the manifest does
    (``spec.render.seed``). A negative value is a "not pinned" sentinel, and then there is
    nothing honest to print.
    """
    if folder is None:
        return None
    spec = sheet_manifest(folder).get("spec")
    render = spec.get("render") if isinstance(spec, dict) else None
    seed = render.get("seed") if isinstance(render, dict) else None
    if isinstance(seed, bool):  # a bool is an int in Python, and never a seed
        return None
    try:
        value = int(seed)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def export_name(name: Any, folder: Path | str | None = None, *, now: Any = None) -> str:
    """The bundle's name with its placeholders expanded, exactly like the Builder's.

    ``%date%`` / ``%date:hhmmss%`` / ``%seed%`` are the vocabulary this pack implements
    (core savers write the tokens literally), and the Builder expands them once per run in
    ``output_name``. The export has to do the same or a name typed as
    ``hero-%date:hhmmss%`` lands on disk with the placeholder still in it, which reads as
    "the export ignores my date code". ``%seed%`` needs the sheet's seed, which the
    manifest of the folder being read supplies; without it the token stays literal rather
    than being invented.

    A name with no placeholder is returned unchanged - deliberately no auto stamp: this is
    a file you name on purpose, and re-exporting over it on purpose.
    """
    text = str(name or "").strip()
    if not has_tokens(text):
        return text
    expanded = expand_tokens(text, seed=sheet_seed(folder), now=now)
    return expanded.translate(_UNSAFE_FILE_CHARS)


def sheet_folder(value: Any, *, newest: bool = True) -> Path | None:
    """Resolve a sheet folder from an absolute path, a name, or a token pattern.

    The Builder node's ``sheet_dir`` output is an absolute folder; the widget fallback
    is whatever was typed into ``output_name``, which may be ``%date:hhmmss%`` - the
    store already knows how to find the newest run that matches.
    """
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    direct = Path(text)
    if direct.is_dir():
        return direct
    from .sheet_store import sheet_dir  # noqa: PLC0415 - avoid a heavy import at module load

    resolved = sheet_dir(text) if newest else None
    if resolved is not None and Path(resolved).is_dir():
        return Path(resolved)
    return None


def _json_dict(path: Path) -> dict[str, Any]:
    """A JSON object from disk, or ``{}`` (a half-written file is not an error here)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def sheet_manifest(folder: Path | str) -> dict[str, Any]:
    """The sheet's manifest (``<folder>/<name>.json``), which keeps the spec it ran."""
    folder = Path(folder)
    return _json_dict(folder / f"{folder.name}.json")


def _reference_roots(folder: Path | None) -> list[Path]:
    """Where a manifest's reference file name may live, nearest first.

    ComfyUI's ``LoadImage`` / ``LoadAudio`` resolve against the input folder, so that
    is the real home of a reference; the sheet folder and the output folder are tried
    too, because a homemade spec (or a moved sheet) can carry either.
    """
    roots: list[Path] = []
    if folder is not None:
        roots.append(Path(folder))
    try:
        import folder_paths  # noqa: PLC0415 - only available inside ComfyUI

        for getter in ("get_input_directory", "get_output_directory"):
            func = getattr(folder_paths, getter, None)
            directory = func() if callable(func) else None
            if directory:
                roots.append(Path(directory))
    except Exception:  # noqa: BLE001 - a bare checkout has no folder_paths
        pass
    unique: list[Path] = []
    for root in roots:
        resolved = Path(root)
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_reference_file(name: Any, folder: Path | str | None = None) -> Path | None:
    """A file name from a manifest -> the file on disk, or ``None``.

    Never guesses: a reference that has been moved or deleted is reported by the
    caller (which then falls through to the next voice source) instead of loading
    whatever happens to share the name.
    """
    text = str(name or "").strip().strip('"')
    if not text:
        return None
    direct = Path(text)
    if direct.is_absolute():
        return direct if direct.is_file() else None
    roots = _reference_roots(Path(folder) if folder is not None else None)
    candidate = direct if direct.is_file() else None
    if candidate is not None:
        return candidate
    for root in roots:
        found = root / text
        if found.is_file():
            return found
    return None


def sheet_audio_reference_rows(folder: Path | str | None) -> tuple[list[Path], list[str]]:
    """``(reference audio files on disk, names the manifest lists but that are gone)``.

    The manifest keeps the spec of the run, and ``spec.refs.audios[]`` is the file the
    sheet itself was conditioned on - the WAV dropped into the Builder's References
    tab. That one is much better voice material than the ~1s H3 generates per cell (it
    is the actual voice the character was built from, usually several seconds of clean
    speech), so the export offers it first.

    Rows that are switched off are skipped. A row whose file is missing is returned in
    the second list instead of failing the export - the caller reports it and carries
    on, because a tidied-away reference should cost a line of the report, not the run.
    """
    if folder is None:
        return [], []
    spec = sheet_manifest(folder).get("spec")
    refs = spec.get("refs") if isinstance(spec, dict) else None
    entries = refs.get("audios") if isinstance(refs, dict) else None
    found: list[Path] = []
    missing: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        name = str(entry.get("audioFile") or "").strip()
        if not name:
            continue
        path = resolve_reference_file(name, folder)
        if path is None:
            missing.append(Path(name).name)
        elif path not in found:
            found.append(path)
    return found, missing


def sheet_audio_references(folder: Path | str | None) -> list[Path]:
    """The reference audio of a sheet that is on disk (see the rows helper)."""
    return sheet_audio_reference_rows(folder)[0]


def cell_ids(folder: Path) -> list[str]:
    """Cell ids of a sheet folder, in sheet order (manifest, then picks, then clips)."""
    folder = Path(folder)
    for data in (sheet_manifest(folder), _json_dict(folder / _PICKS_NAME)):
        cells = data.get("cells")
        if isinstance(cells, dict) and cells:
            return [str(key) for key in cells]
    return []


def cell_clips(folder: Path | str | None, cell: int | None = None) -> list[Path]:
    """Exported clips of a sheet, in cell order.

    ``CellSink`` prunes older clips, and core ``SaveVideo`` counts up
    (``<cell>_00001_.mp4``), so the highest counter is the newest take.
    ``cell`` selects one cell (0-based) instead of all of them.
    """
    if folder is None:
        return []
    clips_dir = Path(folder) / _CLIPS_DIR
    if not clips_dir.is_dir():
        return []
    ordered: list[Path] = []
    for cell_id in cell_ids(Path(folder)):
        found = [
            path
            for path in clips_dir.glob(f"{cell_id}_*")
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        ]
        if found:
            ordered.append(max(found, key=lambda path: path.name))
    if not ordered:
        ordered = sorted(
            path
            for path in clips_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        )
    if cell is None:
        return ordered
    return ordered[cell : cell + 1] if 0 <= cell < len(ordered) else []


def clip_audio(path: Path | str) -> dict[str, Any]:
    """ComfyUI's own audio decode (PyAV, so an mp4/mkv audio track is fine)."""
    from comfy_extras.nodes_audio import load as load_audio  # noqa: PLC0415 - ComfyUI only

    waveform, sample_rate = load_audio(str(path))
    if getattr(waveform, "ndim", 0) == 2:
        waveform = waveform.unsqueeze(0)  # [C, L] -> [1, C, L]
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def audio_parts(clip: Any, *, what: str = "audio") -> tuple[Any, int]:
    """``(waveform [1, C, L], sample rate)`` from an AUDIO dict (their input shape)."""
    waveform = clip.get("waveform") if isinstance(clip, dict) else None
    rate = clip.get("sample_rate") if isinstance(clip, dict) else None
    if waveform is None or not rate:
        raise RefModExportError(f"{what} is not an AUDIO value (waveform + sample_rate).")
    if getattr(waveform, "ndim", 0) == 2:
        waveform = waveform.unsqueeze(0)
    if getattr(waveform, "ndim", 0) != 3 or int(waveform.shape[0]) != 1:
        raise RefModExportError(
            f"{what} must be one batch of samples [1, channels, length]."
        )
    return waveform, int(rate)


def _resample(waveform: Any, source_rate: int, target_rate: int) -> Any:
    """Their own resample when torchaudio is there, linear interpolation otherwise."""
    if source_rate == target_rate:
        return waveform
    try:
        import torchaudio  # noqa: PLC0415 - the same call their encoder makes

        return torchaudio.functional.resample(waveform, source_rate, target_rate)
    except Exception:  # noqa: BLE001 - torchaudio is present in ComfyUI, not everywhere
        import torch.nn.functional as functional  # noqa: PLC0415

        length = max(1, int(round(waveform.shape[-1] * target_rate / source_rate)))
        return functional.interpolate(waveform, size=length, mode="linear",
                                      align_corners=False)


def concat_audio(
    clips: Sequence[Any],
    *,
    sample_rate: int = H3_AUDIO_RATE,
    max_seconds: float | None = None,
) -> dict[str, Any] | None:
    """Join audio clips into the single waveform their encoder takes.

    Clips are joined as samples, in order, not as latents: H3's audio latent clock is a
    fixed 40 frames per second, so concatenating the latents of separate encodes would
    put an arbitrary cut in the middle of a frame. Every clip is resampled to H3's
    32 kHz first (their encoder would otherwise do it one clip at a time, at different
    ratios) and the whole join is truncated to ``max_seconds`` when a cap is given -
    the cap is a ceiling, not a target.
    """
    if not clips:
        return None
    waveforms: list[Any] = []
    for index, clip in enumerate(clips, start=1):
        waveform, rate = audio_parts(clip, what=f"audio clip {index}")
        waveforms.append(_resample(waveform, rate, int(sample_rate)))
    channels = 2 if any(int(waveform.shape[1]) > 1 for waveform in waveforms) else 1
    padded: list[Any] = []
    for waveform in waveforms:
        if int(waveform.shape[1]) == channels:
            padded.append(waveform)
        elif channels == 2 and int(waveform.shape[1]) == 1:
            padded.append(waveform.repeat(1, 2, 1))  # their own mono -> stereo rule
        else:
            padded.append(waveform.mean(dim=1, keepdim=True))
    import torch  # noqa: PLC0415 - heavy, and only a voice member needs it

    joined = torch.cat(padded, dim=-1)
    limit = int(max(1.0, float(max_seconds)) * int(sample_rate)) if max_seconds else 0
    if limit and joined.shape[-1] > limit:
        joined = joined[..., :limit].contiguous()
    return {"waveform": joined, "sample_rate": int(sample_rate)}


def split_stills(batch: Any, limit: int = MAX_VISUAL_REFS) -> list[Any]:
    """An IMAGE batch -> single-still slices, evenly sampled down to ``limit``."""
    if batch is None:
        return []
    try:
        count = int(batch.shape[0])
    except (AttributeError, IndexError, TypeError, ValueError):
        return []
    if count <= 0:
        return []
    indexes = list(range(count))
    if limit and count > limit:
        if limit <= 1:
            indexes = [0]
        else:
            # Keep both outer cells: the first and the last view of a sheet are the
            # ones a user notices missing, so the sample is spread end to end.
            step = (count - 1) / float(limit - 1)
            indexes = sorted({int(round(index * step)) for index in range(limit)})
        log.info(
            "RefMod export: %s stills sampled down to %s views (their autogrow limit).",
            count, len(indexes),
        )
    return [batch[index : index + 1] for index in indexes]


def _first_mod(output: Any, name: str) -> Any:
    """``io.NodeOutput(([(mod, strength)], details))`` -> the mod."""
    result = getattr(output, "result", output)
    mods = result[0] if isinstance(result, (tuple, list)) and result else None
    if not mods:
        raise RefModExportError(
            f"{PACK_TITLE} returned no reference for '{name}' - check its console output."
        )
    item = mods[0]
    return item[0] if isinstance(item, (tuple, list)) else item


def build_visual_mod(
    api: _Api,
    *,
    name: str,
    stills: Sequence[Any],
    vae: Any,
    mode: str = "Full Reference",
    ref_resolution: int = 1024,
    max_tokens: int = 5120,
    identity: int = 0,
    concept_type: str = "identity",
    description: str = "",
) -> Any:
    """One visual member, encoded by their ``Create H3 RefMod`` (``save`` off)."""
    if not stills:
        raise RefModExportError("a visual RefMod needs at least one still.")
    if vae is None:
        raise RefModExportError(
            "connect the MiniMax H3 video VAE - a visual RefMod is a VAE encode."
        )
    refs = {f"ref_image_{index + 1}": still for index, still in enumerate(stills)}
    internal = MODES.get(str(mode), str(mode))
    output = api.extract.execute(
        name=name,
        mode=internal,
        refs_image=refs,
        vae=vae,
        ref_resolution=int(ref_resolution),
        identity=int(identity),
        max_tokens=int(max_tokens),
        budget_policy="truncate",
        concept_type=str(concept_type),
        description=str(description or ""),
        save=False,
        extraction_preset="manual",
    )
    return _first_mod(output, name)


def build_voice_mod(
    api: _Api,
    *,
    name: str,
    audio: Any,
    audio_vae: Any,
    max_seconds: float = 30.0,
    max_tokens: int = 5120,
    description: str = "",
) -> Any:
    """One voice member, encoded by their ``audio.make_audio_mod``."""
    if audio is None:
        raise RefModExportError("a voice RefMod needs an audio waveform.")
    if audio_vae is None:
        raise RefModExportError(
            "a voice member needs the MiniMax H3 audio VAE (their encoder checks the "
            "checkpoint is the audio one, not the video VAE)."
        )
    return api.make_audio_mod(
        audio_vae,
        audio,
        name,
        float(max_seconds),
        int(max_tokens),
        "truncate",
        str(description or ""),
        "voice",
    )


def _describe(mod: Any) -> dict[str, Any]:
    """Member summary for the report (works for their H3RefMod, and for fakes)."""
    seconds = None
    if getattr(mod, "kind", "") == "audio":
        latent_t = getattr(mod, "latent_t", None)
        if latent_t is None:
            shape = getattr(getattr(mod, "latent", None), "shape", ())
            latent_t = int(shape[-1]) if len(shape) >= 1 else None
        if latent_t:
            seconds = float(latent_t) / 40.0
    return {
        "name": str(getattr(mod, "name", "ref")),
        "kind": str(getattr(mod, "kind", "video")),
        "tokens": int(getattr(mod, "token_count", 0) or 0),
        "seconds": seconds,
        "source": str(getattr(mod, "source", "")),
    }


@dataclass
class ExportResult:
    """What the node returns: the mods, the written file, and the report lines."""

    mods: list[Any] = field(default_factory=list)
    members: list[dict[str, Any]] = field(default_factory=list)
    path: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def report(self) -> str:
        return "\n".join(self.lines)


# ------------------------------------------------------------------ the voice


def _no_clips_note(folder: Path | None) -> str:
    """The one sentence that says why there is no cell clip to read."""
    if folder is None:
        return ("no exported cell clip to take audio from - connect the sheet node's "
                "'sheet_dir' output or export clips (export_video on)")
    return f"no exported cell clip to take audio from (looked in {folder})"


def _reference_label(refs: Sequence[Path]) -> str:
    if len(refs) == 1:
        return f"the sheet's reference audio ({refs[0].name})"
    return f"the sheet's reference audio ({len(refs)} files joined)"


def _clip_label(clips: Sequence[Path]) -> str:
    return f"the audio of {len(clips)} exported cell clip(s), joined"


def voice_member(
    api: _Api,
    *,
    name: str,
    voice_cell: int = VOICE_AUTO,
    folder: Path | None = None,
    audio: Any = None,
    audio_vae: Any = None,
    max_seconds: float = 30.0,
    max_tokens: int = 5120,
    description: str = "",
) -> tuple[Any | None, list[str]]:
    """The bundle's voice member plus the report lines that explain which source it used.

    ``voice_cell`` is the whole ladder switch:

    * ``-1`` (auto) - the sheet's own reference audio, else every exported cell clip
      joined into one waveform, else the connected ``audio``;
    * ``0`` - no sheet audio: the connected ``audio`` only;
    * ``n`` - the generated audio of the nth exported cell clip, forced.

    Auto starts with the reference audio because that is the voice the sheet itself was
    built from - the file dropped into the Builder's References tab: clean, and usually
    seconds long - whereas a cell clip only holds the ~1s H3 generated for that one
    take. Length is what matters: a reference is worth the rows it occupies in the
    packed sequence (see :func:`share_hint`), and 0.95s is 0.5% of it.
    """
    wanted = int(voice_cell)
    refs, missing = sheet_audio_reference_rows(folder)
    clips = cell_clips(folder)
    ladder: list[tuple[str, str, str, Callable[[], Any]]] = []  # (name, label, key, read)

    def joined(paths: Sequence[Path]) -> Any:
        return concat_audio([clip_audio(path) for path in paths], max_seconds=max_seconds)

    # A reference row that no longer resolves is worth saying out loud: the ladder is
    # about to use something shorter, and the user's own file is the thing they wanted.
    notes: list[str] = []
    if missing and not refs:
        notes.append(
            "voice: the sheet's reference audio "
            f"'{', '.join(sorted(set(missing)))}' is not on disk (ComfyUI's input "
            "folder) - the ladder cannot use it"
        )

    if wanted > 0:
        if 0 <= wanted - 1 < len(clips):
            clip = clips[wanted - 1]
            ladder.append((f"{name}_voice_cell{wanted}",
                           f"the generated audio of {clip.name}", "cell",
                           (lambda path=clip: clip_audio(path))))
    elif wanted == 0:
        if audio is not None:
            ladder.append((f"{name}_voice", "the connected audio", "audio",
                           lambda: audio))
    else:
        if refs:
            ladder.append((f"{name}_voice", _reference_label(refs), "refs",
                           (lambda paths=list(refs): joined(paths))))
        if clips:
            ladder.append((f"{name}_voice_cells", _clip_label(clips), "clips",
                           (lambda paths=list(clips): joined(paths))))
        if audio is not None:
            ladder.append((f"{name}_voice", "the connected audio", "audio",
                           lambda: audio))

    if not ladder:
        lines: list[str] = []
        if wanted > 0:
            lines.append(f"voice: cell {wanted} has no clip "
                         f"(the sheet exported {len(clips)})" if clips
                         else "voice: " + _no_clips_note(folder))
        elif wanted == 0:
            lines.append("voice: no voice member - 'voice_cell' is 0 and nothing is "
                         "connected to 'audio'")
        else:
            if not refs and not missing:
                lines.append(
                    "voice: no reference audio in the sheet's manifest"
                    + (f" ({folder.name}.json)" if folder is not None else
                       " - point 'sheet_dir' at the sheet folder")
                )
            if not clips:
                lines.append("voice: " + _no_clips_note(folder))
            if audio is None:
                lines.append("voice: no AUDIO connected")
        return None, notes + lines

    if audio_vae is None:
        return None, notes + ["voice: " + NO_AUDIO_VAE]

    lines = list(notes)
    for member_name, label, key, read in ladder:
        skipped: str | None = None
        try:
            clip = read()
        except RefModExportError as exc:
            skipped = str(exc)
            clip = None
        except Exception as exc:  # noqa: BLE001 - a broken file falls through, not fails
            skipped = f"{type(exc).__name__}: {exc}"
            clip = None
        if clip is None:
            lines.append(f"voice: {label} could not be read ({skipped})" if skipped
                         else f"voice: {label} had no audio")
            continue
        mod = build_voice_mod(
            api,
            name=member_name,
            audio=clip,
            audio_vae=audio_vae,
            max_seconds=max_seconds,
            max_tokens=max_tokens,
            description=description,
        )
        lines.append(f"voice: {label} as '{member_name}'")
        if wanted == VOICE_AUTO:
            spare = []
            if key != "refs" and refs:
                spare.append("the sheet's reference audio")
            if key != "clips" and clips:
                spare.append(f"its {len(clips)} exported cell clip(s)")
            if key != "audio" and audio is not None:
                spare.append("the connected audio")
            if spare:
                lines.append(
                    f"voice: not used - {', '.join(spare)} ('auto' walks reference audio "
                    "-> cell clips -> connected audio; 'voice_cell' forces one: 0 = the "
                    "connected audio, n = the nth cell)"
                )
        return mod, lines
    return None, lines


def share_hint(members: Sequence[dict[str, Any]], total: int) -> list[str]:
    """How much of the bundle's rows the thinnest voice member gets.

    Everything in a bundle is packed into ONE sequence that the model attends over
    jointly, so a reference only counts for the rows it occupies - and the video being
    generated adds its own rows on top of these, so the share printed here is an
    optimistic ceiling. A measured case: a 0.95s voice member is 76 rows, ~0.5% of the
    rows once a 5s 640x384 target is packed too, which is why an A/B of "voice 1.0"
    against "voice 0.0" came out at noise level. Their loader's ``copies`` widget
    repeats a member, so the hint names the number that would put the voice on the map
    (2% of the bundle is the point where a reference starts to compete, and the real
    share with the target included is lower still).
    """
    voices = [m for m in members if m.get("kind") == "audio" and int(m.get("tokens") or 0)]
    if not voices or total <= 0:
        return []
    thinnest = min(voices, key=lambda member: int(member["tokens"]))
    rows = int(thinnest["tokens"])
    share = rows / total
    # The decision is made on the number the report prints (one decimal): a member that
    # reads "2.0%" must not be called thin in the next line.
    if round(share, 3) >= VOICE_SHARE_HINT:
        return []
    needed = (int(VOICE_SHARE_HINT * total) + rows - 1) // rows
    if needed <= 10:
        copies = max(2, needed)
        return [
            f"voice: {rows} of the bundle's {total} rows ({share:.1%}) - thin, and the "
            f"video you generate adds thousands more on top. Their loader's 'copies' on "
            f"the voice member repeats it: copies {copies} = {share * copies:.1%}."
        ]
    return [
        f"voice: {rows} of the bundle's {total} rows ({share:.1%}) - even 10 copies "
        f"({share * 10:.1%}) stays thin. Raise 'voice_seconds' or connect a longer "
        "clip."
    ]


def export_bundle(
    *,
    cells: Any = None,
    sheet: Any = None,
    audio: Any = None,
    video_vae: Any = None,
    audio_vae: Any = None,
    sheet_dir: str | Path | None = None,
    name: str = "character",
    subfolder: str = "character_sheets",
    mode: str = "Full Reference",
    ref_resolution: int = 1024,
    max_tokens: int = 5120,
    identity: int = 0,
    concept_type: str = "identity",
    description: str = "",
    voice_cell: int = VOICE_AUTO,
    voice_max_seconds: float = 30.0,
    voice_max_tokens: int = 5120,
    voice_description: str = "",
    save: bool = True,
    pack: Any = None,
    api: _Api | None = None,
) -> ExportResult:
    """Build one bundle with the sheet's appearance and voice members.

    ``cells`` / ``sheet`` are the Builder node's IMAGE outputs and ``audio`` an optional
    wired AUDIO. ``voice_cell`` picks the voice source: ``-1`` walks the ladder (the
    sheet's own reference audio, else its exported cell clips joined, else ``audio``),
    ``0`` keeps the sheet out of it (``audio`` only) and ``n`` forces the nth cell's
    clip. ``pack`` / ``api`` are injection points for tests; see :func:`voice_member`.
    """
    if pack is None and api is None:
        pack = load_pack()
    if api is None:
        api = entry_points(pack)
    # The folder is resolved first: a tokenised name is expanded against the sheet this
    # export reads (its manifest carries the seed), not against "now" alone.
    folder = sheet_folder(sheet_dir)
    mod_name = sanitize_name(export_name(name, folder))
    if mod_name != str(name or "").strip():
        log.info("RefMod export: name %r -> %r", str(name), mod_name)

    result = ExportResult()
    lines: list[str] = []
    members: list[Any] = []

    stills = split_stills(cells)
    if stills:
        member = build_visual_mod(
            api,
            name=f"{mod_name}_views",
            stills=stills,
            vae=video_vae,
            mode=mode,
            ref_resolution=ref_resolution,
            max_tokens=max_tokens,
            identity=identity,
            concept_type=concept_type,
            description=description,
        )
        members.append(member)
        lines.append(
            f"appearance: {len(stills)} picked cell still(s) stacked as '{mod_name}_views' "
            f"({MODES.get(str(mode), mode)}, short edge {int(ref_resolution)}px)"
        )

    sheet_still = split_stills(sheet, limit=1)
    if sheet_still:
        member = build_visual_mod(
            api,
            name=f"{mod_name}_sheet",
            stills=sheet_still,
            vae=video_vae,
            mode=mode,
            ref_resolution=ref_resolution,
            max_tokens=max_tokens,
            identity=identity,
            concept_type=concept_type,
            description=description,
        )
        members.append(member)
        lines.append(f"appearance: the composited sheet as '{mod_name}_sheet'")

    voice, voice_lines = voice_member(
        api,
        name=mod_name,
        voice_cell=voice_cell,
        folder=folder,
        audio=audio,
        audio_vae=audio_vae,
        max_seconds=voice_max_seconds,
        max_tokens=voice_max_tokens,
        description=voice_description,
    )
    if voice is not None:
        members.append(voice)
    lines.extend(voice_lines)

    if not members:
        raise RefModExportError(
            "nothing to export: connect the Character Sheet Builder's 'cells' and/or "
            "'sheet' output (appearance), a voice clip, or point 'sheet_dir' at a sheet "
            "with exported clips."
        )
    if len(members) > MAX_MEMBERS:
        raise RefModExportError(
            f"{len(members)} members exceeds the bundle limit ({MAX_MEMBERS})."
        )

    if save:
        path_no_ext = api.mod_output_path(mod_name, str(subfolder or ""))
        # Their save_bundle takes (mod, strength) pairs - the same shape their own
        # Save node forwards - and deduplicates by object identity.
        result.path = str(api.save_bundle(path_no_ext, mod_name,
                                          [(member, 1.0) for member in members]))
        lines.append(f"saved: {result.path}")
    else:
        lines.append("saved: no (save is off - the mods are on the 'mods' output)")

    result.mods = members
    result.members = [_describe(member) for member in members]
    total = sum(member["tokens"] for member in result.members)
    for member in result.members:
        seconds = member.get("seconds")
        detail = f"{member['tokens']} tokens"
        if seconds:
            detail = f"{seconds:.2f}s / {detail}"
        # The share is the number that decides whether a member does anything: rows are
        # what a reference is in the packed sequence, and a 1% member is a rounding
        # error next to the target's thousands.
        share = f", {member['tokens'] / total:.1%} of the bundle" if total else ""
        lines.append(
            f"  - {member['name']} ({member['kind']}): {detail}{share}"
            + (f", source {member['source']}" if member["source"] else "")
        )
    lines.append(
        f"bundle: {mod_name} - {len(members)} member(s), {total} tokens total "
        "(what Load H3 RefMods injects at strength 1)"
    )
    lines.extend(share_hint(result.members, total))
    result.lines = lines
    for line in lines:
        log.info("RefMod export: %s", line)
    return result


def member_rows(mods: Iterable[Any]) -> list[dict[str, Any]]:
    """Public helper: describe a list of mods (used by tests and reports)."""
    return [_describe(mod) for mod in mods]


__all__ = [
    "H3_AUDIO_RATE",
    "MAX_VISUAL_REFS",
    "MODES",
    "PACK_TITLE",
    "PACK_URL",
    "VOICE_AUTO",
    "VOICE_SHARE_HINT",
    "ExportResult",
    "RefModExportError",
    "RefModPackMissing",
    "audio_parts",
    "build_visual_mod",
    "build_voice_mod",
    "cell_clips",
    "cell_ids",
    "clip_audio",
    "concat_audio",
    "entry_points",
    "export_bundle",
    "export_name",
    "load_pack",
    "loaded_pack",
    "member_rows",
    "pack_dir",
    "pack_status",
    "resolve_reference_file",
    "sanitize_name",
    "share_hint",
    "sheet_audio_reference_rows",
    "sheet_audio_references",
    "sheet_folder",
    "sheet_manifest",
    "sheet_seed",
    "split_stills",
    "voice_member",
]
