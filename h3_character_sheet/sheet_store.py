# MiniMax H3 Motion Director - character sheet on-disk store.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Character Sheet Builder: where a sheet's frames, picks and composites live.

Layout (user-facing on purpose - a sheet is an asset you keep and reuse)::

    <output>/minimax_sheets/<name>/
        frames/<cellId>/f0000.png ...   every frame the cell rendered
        cells/<cellId>.png              the picked frame for that cell
        <name>.png                      the composited sheet
        <name>.json                     manifest: spec, prompts, picks, report
        report.txt                      human readable last-run report

Keeping every frame means the sheet can be rebuilt with different picks, a
different layout or a different aspect ratio without re-sampling anything - see
:func:`rebuild_sheet`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode

import folder_paths
import numpy as np
from PIL import Image

from .sheet_layout import (
    array_to_image,
    compose_from_arrays,
    pick_frame_index,
)
from .sheet_spec import (
    SheetLayoutSpec,
    SheetCell,
    continuity_plan,
    continuity_settle,
    parse_sheet_spec,
    safe_name,
)
from .name_tokens import export_stem, folder_pattern, has_tokens, is_expanded

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.sheet")

SHEETS_DIR_NAME = "minimax_sheets"
MANIFEST_SUFFIX = ".json"
PICKS_NAME = "picks.json"
REPORT_NAME = "report.txt"
FRAMES_DIR = "frames"
CELLS_DIR = "cells"
CLIPS_DIR = "clips"
PIPELINE = "character_sheet_v1"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _-]+")


def safe_sheet_name(value: Any, fallback: str = "character_sheet") -> str:
    """Sheet folder name - same normaliser the spec uses, so they cannot drift."""
    return safe_name(value, fallback)


def output_root() -> Path:
    """ComfyUI's output directory - what ``/view`` resolves ``subfolder`` against."""
    return Path(folder_paths.get_output_directory())


def sheets_root() -> Path:
    return output_root() / SHEETS_DIR_NAME


def sheet_dir(name: Any) -> Path:
    """Folder for a sheet name; a ``%date:...%`` name resolves to its newest run.

    The panel only knows the literal name the user typed, and the run expands the
    placeholders when it starts, so a tokenised name has to be looked up by pattern
    or the panel would poll a folder that never exists.
    """
    pattern = folder_pattern(name)
    if pattern:
        newest = newest_matching_sheet(pattern)
        if newest is not None:
            return newest
    return sheets_root() / safe_sheet_name(name)


def newest_matching_sheet(pattern: str) -> Path | None:
    """Newest existing sheet folder whose name matches a token pattern."""
    root = sheets_root()
    if not root.exists():
        return None
    best: Path | None = None
    best_stamp = -1.0
    for candidate in root.glob(pattern):
        if not candidate.is_dir() or not is_expanded(candidate.name):
            continue
        try:
            stamp = candidate.stat().st_mtime
        except OSError:
            continue
        if stamp > best_stamp:
            best, best_stamp = candidate, stamp
    return best


def unique_sheet_name(folder: Path, stem: str) -> str:
    """``x.png``, or ``x-2.png`` when that file is already on disk.

    A sheet export is never allowed to replace a finished render: a repeated run in
    the same second (or a name that carries no date at all) steps aside instead.
    """
    name = f"{stem}.png"
    index = 2
    while (folder / name).exists():
        name = f"{stem}-{index}.png"
        index += 1
    return name


#: Export file name for a run: tokens expanded, a plain name date-stamped instead.
def sheet_file_name(name: Any, *, now: Any = None) -> str:
    return f"{safe_sheet_name(export_stem(name, now=now), 'character_sheet')}.png"


def _view_url(path: Path, root: Path | None = None) -> str:
    """ComfyUI ``/view`` URL for a file below the output directory.

    ``subfolder`` is relative to the OUTPUT root (``minimax_sheets/<sheet>/...``), and
    only then to the sheets root: ``/view`` joins it onto ``get_output_directory()``,
    so a shorter subfolder 404s and every thumbnail in the panel shows a broken image.
    """
    candidates = [output_root()] if root is None else [output_root(), Path(root)]
    relative: Path | None = None
    for base in candidates:
        try:
            relative = path.relative_to(base)
            break
        except ValueError:
            continue
    if relative is None:
        return ""
    subfolder = "/".join(relative.parts[:-1])
    try:
        stamp = int(path.stat().st_mtime)
    except OSError:
        stamp = 0
    params = {"filename": relative.name, "type": "output", "c": str(stamp)}
    if subfolder:
        params["subfolder"] = subfolder
    return f"/view?{urlencode(params)}"


class SheetStore:
    """Read/write helper for one sheet folder."""

    def __init__(
        self,
        name: Any,
        *,
        node_id: Any = None,
        export_name: Any = None,
        fresh: bool = False,
    ) -> None:
        # Resolve first: a tokenised name has to reach sheet_dir() intact (it looks
        # up the newest run by pattern), and only then is it sanitised.
        resolved = sheet_dir(name)
        self.requested = str(name or "")
        self.name = resolved.name
        self.node_id = "" if node_id is None else str(node_id)
        self.root = sheets_root()
        self.dir = resolved
        self.frames_dir = self.dir / FRAMES_DIR
        self.cells_dir = self.dir / CELLS_DIR
        self.clips_dir = self.dir / CLIPS_DIR
        #: ``fresh`` marks the store that is about to WRITE the sheet (the render and
        #: the grid node): it mints a new dated file. Everyone else (the panel, the
        #: routes, a re-compose) follows the file the manifest recorded, so they edit
        #: the sheet that is on disk instead of guessing a name.
        self.fresh = bool(fresh)
        self._export_name = str(export_name) if export_name else ""
        self._sheet_file: str | None = None

    # ---------------------------------------------------------------- paths
    @property
    def manifest_path(self) -> Path:
        return self.dir / f"{self.name}{MANIFEST_SUFFIX}"

    @property
    def picks_path(self) -> Path:
        return self.dir / PICKS_NAME

    @property
    def report_path(self) -> Path:
        return self.dir / REPORT_NAME

    @property
    def sheet_file(self) -> str:
        """File name of this run's sheet - dated, and never an existing file."""
        if self._sheet_file is None:
            self._sheet_file = self._resolve_sheet_file()
        return self._sheet_file

    def _latest_export(self) -> Path | None:
        """Newest sheet png written straight into this folder (not frames/cells)."""
        try:
            files = [path for path in self.dir.glob("*.png") if path.is_file()]
            if not files:
                return None
            return max(files, key=lambda path: path.stat().st_mtime)
        except OSError:
            return None

    def _mint_stem(self) -> str:
        """Stem for a NEW export file (the date is added by :func:`export_stem`)."""
        if self._export_name:
            return self._export_name
        if has_tokens(self.requested) and is_expanded(self.name):
            # The folder IS the expanded name (``character_sheet-180705``): follow it instead
            # of stamping a second date onto it.
            return self.name
        return export_stem(self.requested)

    def new_export_name(self) -> str:
        """A fresh dated file name, for a compose that must not replace the previous sheet.

        The render keeps ONE file per run, so a workflow's own output (and its SaveImage) stays
        stable. A rebuild from the panel is a different act: it iterates on the frames already on
        disk, and the sheet before it is a finished render rather than a draft - so every rebuild
        writes the next dated file, and the folder keeps the sequence of choices.
        """
        self.ensure()
        return unique_sheet_name(self.dir, safe_sheet_name(self._mint_stem(), "character_sheet"))

    def _resolve_sheet_file(self) -> str:
        # The manifest is authoritative; a folder without one (a hand-made sheet, or a
        # run that died before the manifest) still resolves to the newest export, so a
        # re-compose edits the sheet that is there instead of creating another copy.
        if not self.fresh:
            recorded = str(self.read_manifest().get("sheetFile") or "")
            if recorded and (self.dir / recorded).is_file():
                return recorded
            latest = self._latest_export()
            if latest is not None:
                return latest.name
        return unique_sheet_name(self.dir, safe_sheet_name(self._mint_stem(), "character_sheet"))

    @property
    def sheet_path(self) -> Path:
        return self.dir / self.sheet_file

    def ensure(self) -> "SheetStore":
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.cells_dir.mkdir(parents=True, exist_ok=True)
        return self

    def cell_frame_dir(self, cell_id: str) -> Path:
        return self.frames_dir / safe_sheet_name(cell_id, "cell")

    def cell_pick_path(self, cell_id: str) -> Path:
        return self.cells_dir / f"{safe_sheet_name(cell_id, 'cell')}.png"

    def cell_clip_path(self, cell_id: str) -> Path | None:
        """Newest exported clip of one cell, or ``None`` when the sheet kept no clips.

        The clips are written by core ``SaveVideo`` under ``clips/`` with its own counter
        (``<cell>_00001_.mp4``), so a re-render of the same cell adds a file instead of
        replacing one - the newest is the one this sheet belongs to.
        """
        stem = safe_sheet_name(cell_id, "cell")
        try:
            files = [
                path
                for path in self.clips_dir.glob(f"{stem}_*")
                if path.is_file() and path.suffix.lower() in (".mp4", ".mkv", ".webm")
            ]
        except OSError:
            return None
        if not files:
            return None
        return max(files, key=lambda path: path.stat().st_mtime)

    def prune_cell_clips(self, cell_id: str, keep: int = 1) -> list[str]:
        """Drop older exported clips of one cell, newest ``keep`` kept.

        Core ``SaveVideo`` counts (``<cell>_00002_.mp4``), which is what makes a render
        non-destructive - but a sheet folder that collects three takes of every cell stops
        being a sheet folder. This runs once the new clip is on disk, so the newest is the
        one kept.
        """
        directory = self.clips_dir
        stem = safe_sheet_name(cell_id, "cell")
        try:
            files = sorted(
                (path for path in directory.glob(f"{stem}_*")
                 if path.is_file() and path.suffix.lower() in (".mp4", ".mkv", ".webm")),
                key=lambda path: path.stat().st_mtime,
            )
        except OSError:
            return []
        removed: list[str] = []
        for path in files[: max(0, len(files) - max(1, int(keep)))]:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:  # a share may refuse; never fail a render over it
                log.warning("sheet: could not remove stale clip %s: %s", path.name, exc)
        return removed

    def frame_files(self, cell_id: str) -> list[Path]:
        directory = self.cell_frame_dir(cell_id)
        try:
            return sorted(directory.glob("f*.png"))
        except OSError:
            return []

    # ---------------------------------------------------------------- writes
    def save_cell_frames(self, cell_id: str, arrays: Sequence[np.ndarray]) -> list[Path]:
        """Persist every rendered frame of one cell (old frames are replaced)."""
        directory = self.cell_frame_dir(cell_id)
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("f*.png"):
            try:
                stale.unlink()
            except OSError:
                pass
        paths: list[Path] = []
        for position, array in enumerate(arrays):
            path = directory / f"f{position:04d}.png"
            try:
                array_to_image(array).save(path)
                paths.append(path)
            except Exception as exc:  # noqa: BLE001 - a bad frame must not kill the run
                log.warning("sheet: could not save frame %s of %s (%s)", position, cell_id, exc)
        return paths

    def save_cell_pick(self, cell_id: str, array: np.ndarray | None) -> Path | None:
        if array is None:
            return None
        path = self.cell_pick_path(cell_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            array_to_image(array).save(path)
            return path
        except Exception as exc:  # noqa: BLE001
            log.warning("sheet: could not save picked frame for %s (%s)", cell_id, exc)
            return None

    def write_manifest(self, payload: dict[str, Any]) -> Path:
        self.ensure()
        data = dict(payload)
        data["name"] = self.name
        # Which file this run actually wrote: the panel and the routes read this
        # instead of recomputing a name that is only valid for one second.
        data["sheetFile"] = self.sheet_file
        data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["pipeline"] = PIPELINE
        if self.node_id:
            data["node_id"] = self.node_id
        self.manifest_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return self.manifest_path

    def read_manifest(self) -> dict[str, Any]:
        try:
            if self.manifest_path.is_file():
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
        return {}

    def write_picks(self, picks: dict[str, Any]) -> Path:
        self.ensure()
        self.picks_path.write_text(json.dumps(picks, indent=1), encoding="utf-8")
        return self.picks_path

    def read_picks(self) -> dict[str, Any]:
        try:
            if self.picks_path.is_file():
                data = json.loads(self.picks_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
        return {}

    def write_report(self, text: str) -> None:
        try:
            self.ensure()
            self.report_path.write_text(str(text or ""), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.debug("sheet: report write failed (%s)", exc)

    def delete_cell(self, cell_id: str) -> int:
        removed = 0
        for pattern_dir in (self.cell_frame_dir(cell_id), None):
            if pattern_dir is None:
                path = self.cell_pick_path(cell_id)
                if path.is_file():
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
                continue
            try:
                for path in list(pattern_dir.glob("f*.png")):
                    path.unlink()
                    removed += 1
                pattern_dir.rmdir()
            except OSError:
                pass
        return removed

    def clear(self) -> int:
        removed = 0
        for directory in (self.frames_dir, self.cells_dir):
            try:
                for path in list(directory.rglob("*.png")):
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        # Every export this folder holds, not just the one this store resolved to:
        # runs accumulate dated sheets, and 'clear' means clear.
        try:
            sheet_files = [path for path in self.dir.glob("*.png") if path.is_file()]
        except OSError:
            sheet_files = []
        for path in sheet_files + [self.manifest_path, self.picks_path, self.report_path]:
            try:
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        return removed

    # ---------------------------------------------------------------- reads
    def scan(self, *, spec: dict[str, Any] | None = None) -> dict[str, Any]:
        """Listing payload for the panel: cells, frames, picks and the sheet."""
        manifest = self.read_manifest()
        picks = self.read_picks()
        spec_data = spec if isinstance(spec, dict) else manifest.get("spec") or {}
        cell_specs = spec_data.get("cells") if isinstance(spec_data, dict) else None
        cell_ids: list[str] = []
        if isinstance(cell_specs, list):
            for item in cell_specs:
                if isinstance(item, dict) and item.get("id"):
                    cell_ids.append(str(item["id"]))
        for directory in sorted(self.frames_dir.glob("*")) if self.frames_dir.is_dir() else []:
            if directory.is_dir() and directory.name not in cell_ids:
                cell_ids.append(directory.name)

        cells: list[dict[str, Any]] = []
        for cell_id in cell_ids:
            frames = self.frame_files(cell_id)
            pick = picks.get(cell_id) if isinstance(picks.get(cell_id), dict) else {}
            pick_path = self.cell_pick_path(cell_id)
            clip_path = self.cell_clip_path(cell_id)
            entry = {
                "id": cell_id,
                "frames": [
                    {"file": path.name, "url": _view_url(path, self.root)}
                    for path in frames
                ],
                "frameCount": len(frames),
                "pickMode": str(pick.get("mode") or "auto"),
                "pickIndex": pick.get("index"),
                "cellUrl": _view_url(pick_path, self.root) if pick_path.is_file() else "",
                # The generated clip of this cell, when the sheet exported one, so the
                # panel can play the take instead of only its picked frame.
                "clipUrl": _view_url(clip_path, self.root) if clip_path is not None else "",
                "clipFile": clip_path.name if clip_path is not None else "",
                "rendered": bool(frames),
            }
            cells.append(entry)

        spec_cells = {
            str(item.get("id")): item
            for item in (cell_specs or [])
            if isinstance(item, dict) and item.get("id")
        }
        for entry in cells:
            meta = spec_cells.get(entry["id"]) or {}
            entry["view"] = str(meta.get("view") or "")
            entry["pose"] = str(meta.get("pose") or "")
            entry["expression"] = str(meta.get("expression") or "")
            entry["caption"] = str(meta.get("caption") or "")

        sheet_exists = self.sheet_path.is_file()
        return {
            "name": self.name,
            "dir": str(self.dir),
            "sheetUrl": _view_url(self.sheet_path, self.root) if sheet_exists else "",
            "sheetFile": self.sheet_path.name if sheet_exists else "",
            "cells": cells,
            "counts": {
                "cells": len(cells),
                "rendered": sum(1 for cell in cells if cell["rendered"]),
                "frames": sum(int(cell["frameCount"]) for cell in cells),
            },
            "manifest": manifest,
            "spec": spec_data,
            "report": self._read_report(),
        }

    def _read_report(self) -> str:
        try:
            if self.report_path.is_file():
                return self.report_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return ""
        return ""

    # ---------------------------------------------------------------- rebuild
    def rebuild_sheet(
        self,
        spec: dict[str, Any] | Any,
        picks: dict[str, Any] | None = None,
        *,
        save_cells: bool = True,
        new_export: bool = False,
    ) -> dict[str, Any]:
        """Compose the sheet from the frames already on disk (no re-render).

        ``spec`` is the current panel payload, so a new layout / aspect / caption
        setting can be applied to a finished render. Picks may be overridden per
        call (``{cellId: {"mode": "sharpest", "index": 3}}``).

        ``new_export`` writes the result as the NEXT dated file instead of replacing the sheet
        that is already there. The render leaves it off (one file per run, so a workflow's own
        output is stable); a rebuild from the panel - a pick, a re-compose - turns it on, because
        the sheet it would otherwise overwrite is a finished render, not a draft.

        An index that arrives WITH a request is a hand-pick (the panel's click on a
        thumbnail) and always wins; the index stored by a previous compose is only a
        record of what the automatic rule chose, so it is recomputed here. Otherwise a
        re-composite would keep replaying an older rule's answer - which is how a fixed
        picker appears to do nothing on an existing sheet.
        """
        parsed = spec if hasattr(spec, "cells") else parse_sheet_spec(spec)
        requested_picks = picks if isinstance(picks, dict) else {}
        stored_picks = self.read_picks()
        # With latent continuation a cell's first frames are a re-render of the previous
        # cell's tail - they are a duplicate, so the picker starts after them. Computed
        # from the spec, so a re-composite makes the same choice the render did.
        guides = continuity_plan(parsed)
        arrays: list[np.ndarray | None] = []
        resolved: dict[str, Any] = {}
        captions: list[str] = []
        cells: list[SheetCell] = []
        missing: list[str] = []

        for cell in parsed.enabled_cells:
            cells.append(cell)
            captions.append(cell.label)
            hand = requested_picks.get(cell.id)
            hand = hand if isinstance(hand, dict) else {}
            stored = stored_picks.get(cell.id)
            stored = stored if isinstance(stored, dict) else {}
            # Two kinds of pick, and they must not be confused:
            #  * a RULE (auto / last / sharpest) is recomputed on every compose, which is how a
            #    changed rule reaches a sheet that is already on disk;
            #  * a HAND pick (a click on a thumbnail) is a decision. It is stored with
            #    ``manual: True`` and stays until the user changes that cell's mode. Dropping the
            #    flag on the next rebuild - of another cell, or a plain "Rebuild sheet" - is what
            #    made a chosen frame snap back to the rule.
            hand_index = hand.get("index") if "index" in hand else None
            hand_mode = str(hand.get("mode") or "").strip().lower()
            if hand_index is not None:
                pick = {"mode": hand_mode or "manual", "index": hand_index}
                manual = True
            elif hand_mode and hand_mode != "manual":
                pick = {"mode": hand_mode}
                manual = False
            elif stored.get("manual") and stored.get("index") is not None:
                pick = {"mode": "manual", "index": stored.get("index")}
                manual = True
            else:
                pick = stored
                manual = False
            frames = self.frame_files(cell.id)
            if not frames:
                arrays.append(None)
                missing.append(cell.id)
                resolved[cell.id] = {"mode": str(pick.get("mode") or cell.pick), "index": None}
                continue
            mode = str(pick.get("mode") or cell.pick or "auto")
            if manual:
                explicit = pick.get("index")
            elif hand_mode and hand_mode != "manual":
                # A rule was chosen for this cell: it decides, and the old hand-pick is gone.
                explicit = cell.pick_index
            elif stored.get("manual"):
                explicit = stored.get("index")
            else:
                explicit = cell.pick_index
            buffers = [_load_rgb(path) for path in frames]
            buffers = [buffer for buffer in buffers if buffer is not None]
            if not buffers:
                arrays.append(None)
                missing.append(cell.id)
                resolved[cell.id] = {"mode": mode, "index": None}
                continue
            index = pick_frame_index(
                buffers,
                mode=mode,
                explicit=explicit,
                skip=int(guides.get(cell.id, 0) or 0),
                # A continuing clip settles after its hand-over: rank only its tail, or
                # 'sharpest' picks the previous cell's pose (measured: the turn lands at
                # frame 8 of 22 while the sharpest frames are 0-7).
                settle=(
                    continuity_settle(len(buffers), guides[cell.id])
                    if guides.get(cell.id)
                    else 0
                ),
            )
            picked = buffers[index]
            arrays.append(picked)
            resolved[cell.id] = {
                "mode": mode,
                "index": int(index),
                "frames": len(frames),
                # Records a hand-pick so the NEXT re-composite keeps it (see above): the frame
                # is the user's, not the rule's, until they choose a rule for this cell again.
                **({"manual": True} if manual else {}),
                **({"continuity": int(guides[cell.id])} if guides.get(cell.id) else {}),
            }
            if save_cells:
                self.save_cell_pick(cell.id, picked)

        sheet = compose_from_arrays(arrays, parsed.layout, cells=cells, captions=captions)
        self.ensure()
        target = self.dir / (self.new_export_name() if new_export else self.sheet_file)
        sheet.save(target)
        if new_export:
            # Remember the file this compose wrote: the panel's listing, the next compose and
            # any other store read the manifest's ``sheetFile``, so without this they would keep
            # pointing at the sheet from before the rebuild.
            self._export_name = target.name
            self._sheet_file = target.name
        self.write_picks(resolved)
        if new_export:
            self.write_manifest(self.read_manifest())
        if missing and isinstance(parsed.warnings, list):
            parsed.warnings.append(
                "Cells without frames were left empty: " + ", ".join(missing)
            )
        return {
            "sheet": sheet,
            "path": self.sheet_path,
            "cells": resolved,
            "missing": missing,
            "size": (sheet.width, sheet.height),
        }


def _load_rgb(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # noqa: BLE001
        log.warning("sheet: could not read %s (%s)", path, exc)
        return None


def list_sheet_names() -> list[str]:
    """Sheet folder names present on disk (newest first)."""
    root = sheets_root()
    if not root.is_dir():
        return []
    try:
        entries = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return []
    entries.sort(key=lambda entry: entry.stat().st_mtime if entry.exists() else 0, reverse=True)
    return [entry.name for entry in entries]


def layout_from_spec(spec: Any) -> SheetLayoutSpec:
    parsed = spec if hasattr(spec, "layout") else parse_sheet_spec(spec)
    return parsed.layout


__all__ = [
    "CELLS_DIR",
    "FRAMES_DIR",
    "PIPELINE",
    "SHEETS_DIR_NAME",
    "SheetStore",
    "layout_from_spec",
    "list_sheet_names",
    "output_root",
    "safe_sheet_name",
    "sheet_dir",
    "sheet_file_name",
    "sheets_root",
    "unique_sheet_name",
]
