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
from typing import Any, Iterable, Sequence

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
#: ``voice_cell`` sentinel: take the voice from the first cell that exported a clip.
VOICE_AUTO = -1
#: The modes this pack offers, mapped onto their internal names (their UI accepts
#: both spellings; naming ours explicitly keeps this working if they rename again).
MODES = {"Full Reference": "encode", "Compressed Reference": "training"}

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


def cell_ids(folder: Path) -> list[str]:
    """Cell ids of a sheet folder, in sheet order (manifest, then picks, then clips)."""
    for name in (f"{folder.name}.json", _PICKS_NAME):
        path = folder / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cells = data.get("cells") if isinstance(data, dict) else None
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

    ``cells`` / ``sheet`` are the Builder node's IMAGE outputs, ``audio`` an optional
    wired AUDIO (any voice clip), ``voice_cell`` picks the sheet's own generated cell
    audio (``-1`` = first cell with a clip, ``0`` = off, ``n`` = the nth cell).
    ``pack`` / ``api`` are injection points for tests.
    """
    if pack is None and api is None:
        pack = load_pack()
    if api is None:
        api = entry_points(pack)
    mod_name = sanitize_name(name)

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

    if audio is not None:
        members.append(
            build_voice_mod(
                api,
                name=f"{mod_name}_voice",
                audio=audio,
                audio_vae=audio_vae,
                max_seconds=voice_max_seconds,
                max_tokens=voice_max_tokens,
                description=voice_description,
            )
        )
        lines.append(f"voice: the connected audio as '{mod_name}_voice'")

    folder = sheet_folder(sheet_dir)
    if int(voice_cell) != 0:
        clips = cell_clips(folder)
        index = 0 if int(voice_cell) == VOICE_AUTO else int(voice_cell) - 1
        if not clips:
            lines.append(
                "voice: no exported cell clip to take audio from"
                + (f" (looked in {folder})" if folder is not None else
                   " - connect the sheet node's 'sheet_dir' output or export clips "
                   "(export_video on)")
            )
        elif not 0 <= index < len(clips):
            lines.append(
                f"voice: cell {int(voice_cell)} has no clip "
                f"(the sheet exported {len(clips)})"
            )
        else:
            clip = clips[index]
            members.append(
                build_voice_mod(
                    api,
                    name=f"{mod_name}_voice_cell{index + 1}",
                    audio=clip_audio(clip),
                    audio_vae=audio_vae,
                    max_seconds=voice_max_seconds,
                    max_tokens=voice_max_tokens,
                    description=voice_description,
                )
            )
            lines.append(f"voice: the generated audio of {clip.name} as "
                         f"'{mod_name}_voice_cell{index + 1}'")

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
    for member in result.members:
        seconds = member.get("seconds")
        detail = f"{member['tokens']} tokens"
        if seconds:
            detail = f"{seconds:.2f}s / {detail}"
        lines.append(
            f"  - {member['name']} ({member['kind']}): {detail}"
            + (f", source {member['source']}" if member["source"] else "")
        )
    total = sum(member["tokens"] for member in result.members)
    lines.append(
        f"bundle: {mod_name} - {len(members)} member(s), {total} tokens total "
        "(what Load H3 RefMods injects at strength 1)"
    )
    result.lines = lines
    for line in lines:
        log.info("RefMod export: %s", line)
    return result


def member_rows(mods: Iterable[Any]) -> list[dict[str, Any]]:
    """Public helper: describe a list of mods (used by tests and reports)."""
    return [_describe(mod) for mod in mods]


__all__ = [
    "MAX_VISUAL_REFS",
    "MODES",
    "PACK_TITLE",
    "PACK_URL",
    "VOICE_AUTO",
    "ExportResult",
    "RefModExportError",
    "RefModPackMissing",
    "build_visual_mod",
    "build_voice_mod",
    "cell_clips",
    "cell_ids",
    "clip_audio",
    "entry_points",
    "export_bundle",
    "load_pack",
    "loaded_pack",
    "member_rows",
    "pack_dir",
    "pack_status",
    "sanitize_name",
    "sheet_folder",
    "split_stills",
]
