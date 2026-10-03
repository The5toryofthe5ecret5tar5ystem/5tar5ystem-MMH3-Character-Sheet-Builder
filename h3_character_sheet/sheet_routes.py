# MiniMax H3 Motion Director - character sheet HTTP routes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Character Sheet Maker backend: list a sheet, pick a frame, re-composite.

The node renders and writes everything (``director/sheet_pass.py`` +
``director/sheet_store.py``); these routes let the embedded panel work on a
finished sheet without re-rendering:

* ``GET  /``         -> ``{ok, sheets:[...]}`` or one sheet when ``name`` is given
* ``GET  /media``    -> ``{ok, source, kind, folders, items:[...]}`` (browse picker)
* ``POST /action``   -> ``{ok, action, sheet, ...}``

Actions (all take ``name``)::

    list     - refresh the listing (optionally with the panel's live spec)
    compose  - re-composite from the frames on disk, with a new spec/layout/picks
    pick     - set one cell's frame (mode + index) and re-composite
    delete   - drop one cell's frames and picked frame, then re-composite
    clear    - drop everything this sheet wrote
    names    - every sheet folder on disk
    plan     - the final prompt + references per cell (no GPU, no render)
    blur     - face blur one reference on demand, answering with the copy to look at
    presets  - the recommended whole-node settings (see ``presets.py``)
    knobs    - the node's own widgets described for the panel's compact settings grid
    help     - the in-node guide plus a live check of the model files this install has

Everything is best effort: a missing sheet folder is an empty listing, never an
error, because the panel polls this while a render is still starting.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from . import face_blur, sheet_media, sheet_spec, sheet_store
from . import planner as sheet_planner
from .help import help_payload
from .knobs import KNOB_GROUPS, knob_groups, knob_list
from .presets import DEFAULT_PRESET_ID, preset_list
from .sheet_store import SheetStore

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.sheet.routes")

BASE = "/h3-character-sheet"
_ACTIONS = ("list", "plan", "presets", "knobs", "help", "blur", "compose", "pick", "delete", "clear", "names")


def _route(routes, method: str, path: str, handler) -> None:
    if hasattr(routes, "add_route"):
        routes.add_route(method, path, handler)
    elif method == "POST" and hasattr(routes, "post"):
        routes.post(path)(handler)
    elif method == "GET" and hasattr(routes, "get"):
        routes.get(path)(handler)
    else:
        raise AttributeError("Unsupported ComfyUI route table API")


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": str(message)}, status=status)


def _store(body: dict[str, Any] | None = None, query: Any = None) -> SheetStore | None:
    source = body if isinstance(body, dict) else {}
    name = str(source.get("name") or "").strip()
    node_id = source.get("node_id")
    if not name and query is not None:
        name = str(query.get("name") or "").strip()
        node_id = node_id or query.get("node_id")
    if not name:
        return None
    return SheetStore(name, node_id=node_id)


def _listing(store: SheetStore, *, action: str = "", extra: dict | None = None) -> dict:
    payload: dict[str, Any] = {"ok": True, "sheet": store.scan()}
    payload["sheets"] = sheet_store.list_sheet_names()
    if action:
        payload["action"] = action
    if extra:
        payload.update(extra)
    return payload


async def sheet_list(request):
    store = _store(query=request.query)
    if store is None:
        return web.json_response(
            {"ok": True, "sheets": sheet_store.list_sheet_names(), "sheet": None}
        )
    return web.json_response(_listing(store))


def _flag(value: Any, default: bool) -> bool:
    if value is None or str(value) == "":
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def _int(value: Any, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


async def sheet_media_list(request):
    """Browse ComfyUI's input/output folders for the panel's reference picker."""
    params = request.rel_url.query
    payload = sheet_media.list_media(
        source=params.get("source", "inputs"),
        kind=params.get("kind", "all"),
        subfolder=params.get("subfolder", ""),
        query=params.get("q", ""),
        recursive=_flag(params.get("recursive"), True),
        limit=_int(params.get("limit"), sheet_media.DEFAULT_LIMIT),
    )
    # A bad folder is a normal answer for a picker, not a crash: 404 with the reason.
    return web.json_response(payload, status=200 if payload.get("ok") else 404)


async def sheet_action(request):
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        return _json_error(f"Invalid JSON: {exc}")
    if not isinstance(body, dict):
        return _json_error("JSON body must be an object.")

    action = str(body.get("action") or "list").strip().lower()
    if action not in _ACTIONS:
        return _json_error(f"Unknown action {action!r}; expected one of {', '.join(_ACTIONS)}.")
    if action == "names":
        return web.json_response({"ok": True, "action": action, "sheets": sheet_store.list_sheet_names()})
    if action == "plan":
        # Pure computation on the payload: no sheet folder, no GPU, no render.
        return _plan_response(body)
    if action == "presets":
        # The recommended whole-node settings. Served rather than duplicated in the panel:
        # one definition, and the panel can only offer what the backend knows.
        return web.json_response(
            {
                "ok": True,
                "action": "presets",
                "presets": preset_list(),
                "default": DEFAULT_PRESET_ID,
            }
        )
    if action == "knobs":
        # The node's own widgets, so the panel can show them as a compact grid and hide the
        # native rows. Bounds/choices come from the live schema (see knobs.py).
        knobs = knob_list()
        return web.json_response(
            {
                "ok": True,
                "action": "knobs",
                "knobs": knobs,
                "groups": knob_groups(knobs),
                "order": list(KNOB_GROUPS),
            }
        )
    if action == "help":
        # The guide plus the requirements check. Nothing here touches the GPU: the file
        # check is a folder listing, so it is safe to ask on every panel mount.
        answer = help_payload()
        answer["ok"] = True
        answer["action"] = "help"
        return web.json_response(answer)
    if action == "blur":
        # Blur one reference on demand and answer with the copy to look at. The render
        # does the same work itself (see face_blur.blur_reference_plan); this exists so
        # the panel can show the result before any GPU time is spent on it.
        return _blur_response(body)

    store = _store(body)
    if store is None:
        return _json_error("A sheet name is required.")

    spec = body.get("spec") if isinstance(body.get("spec"), dict) else None
    picks = body.get("picks") if isinstance(body.get("picks"), dict) else None

    try:
        if action == "list":
            return web.json_response(_listing(store, action=action, extra={"picks": picks or {}}))

        if action == "pick":
            cell_id = str(body.get("cell") or "").strip()
            if not cell_id:
                return _json_error("pick needs the cell id.")
            mode = str(body.get("mode") or "auto").strip().lower()
            index = body.get("index")
            try:
                index = int(index) if index is not None and str(index) != "" else None
            except (TypeError, ValueError):
                return _json_error("pick index must be a number.")
            entry = dict(picks or {})
            entry[cell_id] = {"mode": mode, "index": index}
            result = store.rebuild_sheet(spec or store.read_manifest().get("spec") or {}, entry)
            return web.json_response(
                _listing(
                    store,
                    action=action,
                    extra={"picked": {cell_id: result["cells"].get(cell_id, {})}},
                )
            )

        if action == "compose":
            result = store.rebuild_sheet(spec or store.read_manifest().get("spec") or {}, picks)
            return web.json_response(
                _listing(store, action=action, extra={"size": list(result["size"]), "missing": result["missing"]})
            )

        if action == "delete":
            cell_id = str(body.get("cell") or "").strip()
            if not cell_id:
                return _json_error("delete needs the cell id.")
            removed = store.delete_cell(cell_id)
            if spec:
                store.rebuild_sheet(spec, picks)
            return web.json_response(_listing(store, action=action, extra={"removed": removed}))

        if action == "clear":
            removed = store.clear()
            return web.json_response(_listing(store, action=action, extra={"removed": removed}))
    except ValueError as exc:
        return _json_error(str(exc), status=409)
    except Exception as exc:  # noqa: BLE001 - never break the panel on a bad sheet
        log.warning("sheet route %s failed: %s", action, exc)
        return _json_error(f"{action} failed: {exc}", status=500)

    return _json_error(f"Unhandled action {action!r}.")


def _blur_response(body: dict[str, Any]) -> web.Response:
    """Blur one reference file and describe the copy that was written.

    The panel passes its spec and the slot it is previewing, so the answer can say
    whether the *render* would blur this reference too (``applies``) and blur it the same
    way the render will: same area, same detected faces, same painted strokes. The
    preview then shows what the sheet will actually send, rather than a blur the render
    would not have used. ``paint`` and ``detect`` can be given explicitly to override
    what the spec says (a paint-only preview, for instance).
    """
    name = str(body.get("file") or "").strip()
    if not name:
        return _json_error("blur needs the reference 'file'.")
    scope = str(body.get("scope") or "").strip().lower() or None
    paint = body.get("paint") if isinstance(body.get("paint"), list) else None
    detect = body.get("detect") if isinstance(body.get("detect"), bool) else None
    applies: Any = None
    payload = body.get("spec")
    if isinstance(payload, dict):
        try:
            spec = sheet_spec.parse_sheet_spec(payload)
            slot = int(str(body.get("slot", "")) or -1)
            decisions = sheet_spec.blur_face_decisions(spec)
            detects = sheet_spec.blur_detects_faces(spec)
            if slot >= 0:
                applies = decisions.get(("picture", slot)) == "blur"
                if detect is None:
                    detect = detects.get(("picture", slot), True)
                if paint is None:
                    for ref in spec.refs:
                        origin = ref.source if ref.source >= 0 else ref.index
                        if ref.kind == "picture" and origin == slot:
                            paint = [dict(stroke) for stroke in ref.blur_paint]
                            break
            else:
                # No slot given: report the run's picture decisions by reference tag.
                applies = [
                    f"<Picture {index + 1}>"
                    for (kind, index), decision in sorted(decisions.items())
                    if kind == "picture" and decision == "blur"
                ]
            scope = scope or spec.render.blur_scope
        except Exception as exc:  # noqa: BLE001 - a preview must not fail on a bad spec
            log.warning("blur preview could not read the spec: %s", exc)
    report = face_blur.blur_image_faces(
        name, scope=scope, paint=paint, detect=detect
    )
    if not report.get("ok") and applies is False:
        # The detector was skipped on purpose (the render leaves this reference alone), so
        # "no face detected" would be a lie about what happened.
        report["reason"] = "the render sends this reference unchanged - nothing is blurred"
    if not report.get("ok"):
        # Not an error the panel should shout about: "no face detected" is a normal
        # answer, and the render keeps the original reference either way.
        return web.json_response(
            {**report, "action": "blur", "source": name, "applies": applies}, status=200
        )
    target = str(report["file"])
    folder, _, filename = target.rpartition("/")
    report.update(
        action="blur",
        source=name,
        applies=applies,
        url=sheet_media.view_url(filename, "inputs", folder),
    )
    return web.json_response(report)


def _plan_response(body: dict[str, Any]) -> web.Response:
    """What each cell will actually be sent: its final prompt and its references.

    This runs the same code the render runs (``planner.cell_work_items``), so the
    panel shows the real text rather than a guess - which is what makes a mis-wired
    or wrongly-attributed reference obvious before a sheet has finished rendering.
    """
    payload = body.get("spec") if isinstance(body.get("spec"), dict) else {}
    if not payload:
        return _json_error("plan needs the panel payload in 'spec'.")
    options: dict[str, Any] = {}
    scope = str(body.get("scope") or "").strip()
    if scope:
        options["ref_scope"] = scope
    cell_size = body.get("cell_size")
    try:
        if cell_size is not None and str(cell_size).strip() != "":
            options["cell_size"] = int(cell_size)
    except (TypeError, ValueError):
        pass
    try:
        spec = sheet_spec.parse_sheet_spec(payload)
        items = sheet_planner.cell_work_items(spec, **options)
    except Exception as exc:  # noqa: BLE001 - a bad payload is a message, not a crash
        return _json_error(f"plan failed: {exc}")
    # Which of a cell's references will be handed over blurred (see face_blur): the
    # panel shows this next to the tags so "the face is gone from picture 2" is visible
    # before a render rather than after it.
    decisions = sheet_spec.blur_face_decisions(spec)
    cells = [
        {
            "id": item["id"],
            "prompt": item["prompt"],
            "refs": sheet_planner.plan_tags(item.get("ref_plan") or {}),
            "blurred": _blurred_tags(item.get("ref_plan") or {}, decisions),
            # Frames handed over from the previous cell (0 = this cell starts from its
            # own noise). Shown so a run of chained cells is visible before the render.
            "continuity": int(item.get("continuity") or 0),
        }
        for item in items
    ]
    return web.json_response(
        {"ok": True, "action": "plan", "name": spec.name, "cells": cells}
    )


def _blurred_tags(plan: dict[str, Any], decisions: dict[tuple[str, int], str]) -> list[str]:
    """The tags in a cell's plan that will be wired as a blurred copy.

    Read from the plan rather than recomputed, so the answer matches what the render
    will do - the plan is the wiring, including the source slot each entry came from.
    """
    tags: list[str] = []
    for index, item in enumerate(plan.get("pictures") or []):
        slot = str(item.get("source_slot_id") or "")
        source = int(slot.rsplit("_", 1)[-1]) if slot.rsplit("_", 1)[-1].isdigit() else index
        if decisions.get(("picture", source)) == "blur":
            tags.append(f"<Picture {index + 1}>")
    return tags


def register_sheet_routes(routes) -> None:
    """Register the character-sheet endpoints (idempotent per process)."""
    _route(routes, "GET", BASE, sheet_list)
    _route(routes, "GET", BASE + "/media", sheet_media_list)
    _route(routes, "POST", BASE + "/action", sheet_action)


def register_routes() -> bool:
    """Register on the running ComfyUI server; False when it is not up yet."""
    try:
        from server import PromptServer
    except Exception:  # noqa: BLE001 - ComfyUI core not importable
        return False
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return False
    register_sheet_routes(server.routes)
    log.info("H3 Character Sheet routes registered at %s", BASE)
    return True


__all__ = ["BASE", "register_routes", "register_sheet_routes", "sheet_media_list"]
