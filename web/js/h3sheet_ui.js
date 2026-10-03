// MiniMax H3 Character Sheet Maker — panel wiring.
//
// The panel itself lives in `h3sheet_core.mjs` (no ComfyUI imports, so its DOM is
// testable in jsdom). This file does the four things that need ComfyUI:
//
//   1. mounts the panel as a DOM widget INSIDE the node and moves it to the top of
//      the node, so the node reads as an interface (references, cells, results)
//      with the layout/render knobs below it - no popup,
//   2. persists the panel state into the node's `sheet_data` widget,
//   3. uploads dropped / picked reference files into ComfyUI's input folder,
//   4. talks to the /h3-character-sheet routes (media browse / list / pick /
//      compose / clear).

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
    buildSheetInterface,
    applyPreviewMode,
    enforcePreviewCaps,
    nodePreviews,
    previewHeight,
    previewParts,
    readState,
    toPayload,
    LIVE_PREVIEW_EVENT,
    REF_GROUPS,
    PANEL_FIT,
    panelFitHeight,
} from "./h3sheet_core.mjs?boot=h3sheet_v53";

const CLASS = "MiniMaxH3CharacterSheet";
const DOM_WIDGET = "h3_character_sheet_ui";
const DATA_WIDGET = "sheet_data";
const BASE = "/h3-character-sheet";
const POLL_MS = 4000;
//: A height difference smaller than this is layout jitter, not the runaway node.
const FIT_TOLERANCE = 24;
//: Re-measure after the browser has settled: fonts and thumbnails land late.
const FIT_DELAYS = [120, 400, 1200];
//: How often the preview caps are re-checked while a node is on the canvas (see
//: startPreviewKeeper). It writes only when something is actually wrong, so in practice this is
//: a check that does nothing.
const PREVIEW_KEEPER_MS = 400;
function apiUrl(path = "") {
    const url = `${BASE}${path}`;
    return typeof api?.apiURL === "function" ? api.apiURL(url) : url;
}

/**
 * Snap the node back to the height its panel actually needs.
 *
 * A node never shrinks on its own (the frontend's layout only grows), and a saved
 * workflow restores whatever size it had - so a sheet that was tall while it was
 * rendering kept a huge empty area under the panel after a refresh. Re-measuring on
 * every panel change is what keeps the node hugging its content.
 */
function fitNodeToPanel(node) {
    const part = node?._mmxSheet;
    const widget = part?.widget;
    const element = widget?.element;
    if (!widget || !element) return;
    if (app.canvas?.resizing_node === node) return;   // never fight a user's drag
    const knobs = (node.widgets || []).filter((item) => item !== widget && item.hidden !== true);
    // ComfyUI's own output previews are DOM widgets too, and in `compact` mode the pack caps
    // their height - so the fit has to size the node for THAT, not for the height the
    // frontend would have given them (which is what made a finished sheet a 1000px-wide,
    // very tall node).
    const compactPreview = previewHeight(part.previewMode || nodePreviews(part.state));
    const rowsHeight = knobs.reduce(
        (total, item) => total + (isPreviewWidget(item, widget)
            ? (compactPreview || Number(item.computedHeight) || PANEL_FIT.rowHeight)
            : (Number(item.computedHeight) || PANEL_FIT.rowHeight)),
        0,
    );
    // Measure the panel's CONTENT, not the height the node handed it: the element is sized by
    // the node (`height: 100%`), so its clientHeight only ever looks back at the node and the
    // content never gets to ask for room - which is how the compact settings grid ended up
    // scrolling inside a node with space to spare. `scrollHeight` is the root's own content
    // (it scrolls), and a pane that is capped on purpose (a run's 110 thumbnails) reports its
    // capped height, so the node still cannot explode.
    const client = Number(element.clientHeight) || 0;
    const content = Math.max(client, Number(element.scrollHeight) || 0);
    // Whatever the panel says it cannot fit is room the model above got wrong (a different
    // zoom, another ComfyUI build, a font that landed late). Add it instead of hoping the fit
    // tolerance swallows it - the difference is a few px, and over those few px sits a
    // permanent scrollbar. It goes away as soon as the panel fits, so this cannot run away.
    const overflow = Math.max(0, content - client);
    const target = panelFitHeight({
        top: Number(widget.y),
        panelHeight: content + overflow,
        rowsHeight,
        ceiling: fitCeiling(),
    });
    const current = Math.round(Number(node.size?.[1]) || 0);
    if (!Number.isFinite(target) || target < 240) return;
    // Ignore small differences: a few pixels of jitter is not worth a re-layout, and
    // it leaves a deliberate resize alone unless it is far off its content.
    if (Math.abs(current - target) < FIT_TOLERANCE) return;
    node.setSize?.([node.size[0], target]);
}

/** Fit now, then again as fonts/images/layout settle after a change. */
function scheduleFit(node) {
    fitNodeToPanel(node);
    const timers = node._mmxSheetFitTimers || (node._mmxSheetFitTimers = []);
    while (timers.length) clearTimeout(timers.pop());
    for (const delay of FIT_DELAYS) {
        timers.push(setTimeout(() => fitNodeToPanel(node), delay));
    }
}

function widgetOf(node, name) {
    return (node.widgets || []).find((item) => item.name === name) || null;
}

function sheetName(node) {
    return String(widgetOf(node, "output_name")?.value || "character_sheet");
}

function viewUrl(url) {
    if (!url) return "";
    return typeof api?.apiURL === "function" ? api.apiURL(url) : url;
}

async function sheetAction(node, body) {
    const response = await api.fetchApi(apiUrl("/action"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, node_id: node.id, name: sheetName(node) }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
        throw new Error(data?.error || `HTTP ${response.status}`);
    }
    return data;
}

async function listSheet(node) {
    const url = apiUrl(`?name=${encodeURIComponent(sheetName(node))}&node_id=${encodeURIComponent(node.id ?? "")}`);
    const response = await api.fetchApi(url, { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    return data?.sheet || null;
}

/**
 * A preset-store action (save / delete one of the user's own presets).
 *
 * Posted directly instead of through ``sheetAction`` because a refusal here is an ANSWER:
 * "give the preset a name" or "delete one first" has to reach the panel as a sentence, and
 * ``sheetAction`` turns a 400 into a thrown error that would surface as "HTTP 400".
 */
async function presetStore(node, action, body = {}) {
    const response = await api.fetchApi(apiUrl("/action"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, action, node_id: node.id, name: sheetName(node) }),
    });
    return response.json().catch(() => ({ ok: false, reason: `HTTP ${response.status}` }));
}

//: Seeds are written as H3's own kind of integer (a uint32 fits every sampler path).
const CELL_SEED_MAX = 0xFFFFFFFF;

/** Write a payload onto the node's `sheet_data` and keep the panel in step with it. */
function writePayload(node, payload) {
    const dataWidget = widgetOf(node, DATA_WIDGET);
    if (dataWidget) dataWidget.value = JSON.stringify(payload);
    const part = node._mmxSheet;
    if (part) {
        // The panel reads its cells (and their seeds) from its own state, so adopting the payload
        // is what keeps a later hand-edit or a preset application from undoing the new seed.
        part.state = readState(JSON.stringify(payload));
        part.panel?.setState?.(part.state);
    }
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
    return payload;
}

/** Queue the graph the node belongs to (the panel's own Queue button, in effect). */
async function queueRun(node) {
    if (typeof app.queuePrompt === "function") return app.queuePrompt(0, 1);
    // Older/newer frontends differ on where queueing lives; the graph->prompt pair is the
    // documented fallback and is exactly what the Queue button does.
    if (typeof app.graphToPrompt !== "function") throw new Error("this frontend cannot queue a prompt");
    const { workflow, output } = await app.graphToPrompt();
    return api.queuePrompt(0, { workflow, output });
}

/** Wait for ComfyUI's queue to drain, so a re-roll is not appended behind the run it cancelled. */
async function waitForIdleQueue(attempts = 40, delayMs = 150) {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
        const empty = await api.fetchApi("/queue", { cache: "no-store" })
            .then((response) => response.json())
            .then((queue) => !(queue?.queue_running?.length || queue?.queue_pending?.length))
            .catch(() => true);
        if (empty) return true;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    return false;
}

/**
 * Re-render ONE cell with a new seed - the panel's "new seed" button.
 *
 * The flow, in order, and each step is why the next one is safe:
 *
 * 1. cancel the running prompt (only if this node's render is the one running), and wait for the
 *    queue to drain - otherwise the re-roll would queue behind the run it just interrupted;
 * 2. write a random seed onto that cell and scope the run to it (`render.onlyCells`), which the
 *    node narrows the sheet to, leaving every other cell's frames on disk untouched;
 * 3. queue, and remember what was re-rolled;
 * 4. when the run succeeds, drop the scope and recompose the sheet from the folder — the other
 *    cells come back from the frames they already had.
 */
async function retryCellRender(node, cellId) {
    const part = node._mmxSheet;
    if (!part) return { queued: false };
    if (part.running) {
        try {
            await api.interrupt?.(part.promptId || undefined);
        } catch (error) {
            /* an interrupt that fails is not fatal: the queue wait below still applies */
        }
        await waitForIdleQueue();
    }
    const payload = currentPayload(node, part.state);
    const cells = Array.isArray(payload.cells) ? payload.cells : [];
    const index = cells.findIndex((cell) => String(cell?.id || "") === String(cellId));
    if (index < 0) throw new Error(`${cellId} is not a cell of this sheet`);
    const seed = Math.floor(Math.random() * CELL_SEED_MAX);
    cells[index] = { ...cells[index], seed };
    payload.cells = cells;
    payload.render = { ...(payload.render || {}), onlyCells: [String(cellId)] };
    writePayload(node, payload);
    part.retry = { cellId: String(cellId), seed };
    await queueRun(node);
    return { queued: true, seed };
}

async function uploadReference(file, groupKey) {
    const group = REF_GROUPS.find((item) => item.key === groupKey);
    const body = new FormData();
    body.append("image", file);
    body.append("type", "input");
    body.append("subfolder", "h3_character_sheet");
    const response = await api.fetchApi("/upload/image", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const hint = group?.kind === "video" || group?.kind === "audio"
            ? " (very large media: bump --max-upload-size, or drop it in ComfyUI/input/h3_character_sheet by hand)"
            : "";
        throw new Error(`${data?.error || `HTTP ${response.status}`}${hint}`);
    }
    const name = String(data?.name || "");
    if (!name) throw new Error("upload returned no file name");
    const subfolder = String(data?.subfolder || "");
    return subfolder ? `${subfolder}/${name}` : name;
}

/** Media already in ComfyUI's input / output folders, for the Browse overlay. */
async function listMedia({ source = "inputs", kind = "all", query = "" } = {}) {
    const params = new URLSearchParams({
        source: source === "outputs" ? "outputs" : "inputs",
        kind,
        q: query,
        recursive: "1",
    });
    const response = await api.fetchApi(apiUrl(`/media?${params.toString()}`), { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok && data?.ok !== false) {
        throw new Error(data?.error || `HTTP ${response.status}`);
    }
    return data;
}

function currentPayload(node, state) {
    const live = widgetOf(node, DATA_WIDGET)?.value;
    if (!live) return toPayload(state);
    try {
        return JSON.parse(live);
    } catch {
        return toPayload(state);
    }
}

/** Widgets that never count as a knob: the panel itself and its storage. */
const INTERNAL_WIDGETS = new Set([DOM_WIDGET, DATA_WIDGET]);

/**
 * The node's own knobs, cached once.
 *
 * The panel hides these rows so the node is as tall as the interface instead of the
 * interface plus 23 rows. The list has to be captured before hiding, because a hidden
 * widget is exactly what the filter is looking for.
 */
function knobWidgets(node) {
    if (!node._mmxKnobWidgets) {
        node._mmxKnobWidgets = (node.widgets || []).filter(
            (widget) => widget && widget.name && !INTERNAL_WIDGETS.has(widget.name),
        );
    }
    return node._mmxKnobWidgets;
}

/**
 * Show or hide the node's own knob rows.
 *
 * Hiding is presentational only: `widgets_values` keeps the slot (the frontend skips
 * just `serialize === false`, and the loader walks the same list), the prompt keeps the
 * input, and the panel writes the same widget objects. This is the idiom the pack
 * already uses for `sheet_data`, which is hidden and still reaches the node.
 */
function setKnobsVisible(node, visible) {
    const widgets = knobWidgets(node);
    for (const widget of widgets) {
        if (visible) {
            widget.hidden = false;
            if (widget.options) widget.options.hidden = false;
            if (widget._mmxComputeSize) {
                widget.computeSize = widget._mmxComputeSize;
            } else {
                delete widget.computeSize;
            }
            widget._mmxComputeSize = undefined;
        } else {
            if (!widget._mmxComputeSize) widget._mmxComputeSize = widget.computeSize || null;
            widget.hidden = true;
            if (widget.options) widget.options.hidden = true;
            widget.computeSize = () => [0, 0];
        }
    }
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
    scheduleFit(node);
    return widgets.length;
}

/** Read the node's own widget values, so the panel can show what will render. */
function readWidgets(node, names = null) {
    const list = Array.isArray(names) && names.length
        ? names
        : knobWidgets(node).map((widget) => widget.name);
    const values = {};
    for (const name of list) {
        const widget = widgetOf(node, name);
        if (widget) values[name] = widget.value;
    }
    return values;
}

function mountPanel(node) {
    const dataWidget = widgetOf(node, DATA_WIDGET);
    const state = readState(dataWidget?.value || "");
    let panel = null;

    const hooks = {
        stateChanged(payload) {
            if (dataWidget) {
                // Never let a panel that lost its cell list wipe a workflow's matrix:
                // keep what sheet_data already holds when this payload has none.
                if (!Array.isArray(payload.cells) || !payload.cells.length) {
                    try {
                        const current = JSON.parse(dataWidget.value || "{}");
                        if (Array.isArray(current?.cells) && current.cells.length) {
                            payload.cells = current.cells;
                        }
                    } catch {
                        /* unreadable payload: write what the panel has */
                    }
                }
                dataWidget.value = JSON.stringify(payload);
            }
            node.setDirtyCanvas?.(true, true);
            node.graph?.setDirtyCanvas?.(true, true);
        },
        status(text) {
            if (panel?.status) panel.status.textContent = String(text || "");
        },
        assetUrl: viewUrl,
        upload: uploadReference,
        listMedia,
        listResults: () => listSheet(node),
        pickFrame: (cellId, index) => sheetAction(node, {
            action: "pick", cell: cellId, mode: "last", index,
            spec: currentPayload(node, state),
        }),
        compose: () => sheetAction(node, { action: "compose", spec: currentPayload(node, state) }),
        // "This cell is no good": cancel the run and render that one cell again with a new seed.
        retryCell: ({ cellId }) => retryCellRender(node, cellId),
        clearSheet: () => sheetAction(node, { action: "clear" }),
        layoutChanged: () => scheduleFit(node),
        // The recommended whole-node settings come from the pack's backend
        // (h3_character_sheet/presets.py): one definition, and the panel can only offer
        // what the node implements.
        listPresets: () => sheetAction(node, { action: "presets" }),
        /** Keep the settings on this node as a preset of the user's own (user_presets.py). */
        savePreset: (body) => presetStore(node, "save-preset", body),
        /** Remove one of those; the backend refuses a built-in with a reason. */
        deletePreset: (id) => presetStore(node, "delete-preset", { id }),
        // The node's knobs, described by the pack's backend from the node schema: the
        // panel draws them in columns and hides the native rows (see knobs.py).
        listKnobs: () => sheetAction(node, { action: "knobs" }),
        // The guide + which model files this install actually has (help.py). One request,
        // no GPU: the check is a folder listing.
        listHelp: () => sheetAction(node, { action: "help" }),
        /** The values on the node right now, so the settings fields never guess. */
        readWidgets: (names) => readWidgets(node, names),
        /** Take the node's own knob rows away (or give them back), leaving the values. */
        setKnobsVisible: (visible) => setKnobsVisible(node, visible),
        /** ComfyUI's own output previews: smaller, side by side, or gone. */
        setPreviewMode: (mode) => {
            const result = applyNodePreviews(node, mode);
            // The node can be a lot shorter once the previews are capped.
            scheduleFit(node);
            return result;
        },
        /** Write a preset's values onto the node's own knobs (cell size, steps, layout...). */
        applyWidgets: async (values) => {
            const applied = [];
            for (const [name, value] of Object.entries(values || {})) {
                const widget = widgetOf(node, name);
                if (!widget) continue;
                widget.value = value;
                applied.push(name);
            }
            node.setDirtyCanvas?.(true, true);
            node.graph?.setDirtyCanvas?.(true, true);
            // The panel's own height can change with the layout it just asked for.
            scheduleFit(node);
            return applied;
        },
        // The final prompt per cell comes from the pack's planner (no GPU, no render),
        // so the Prompt tab shows the real text instead of a guess.
        planCells: () => sheetAction(node, {
            action: "plan",
            spec: toPayload(state),
            scope: String(widgetOf(node, "ref_scope")?.value || ""),
            cell_size: widgetOf(node, "cell_size")?.value,
        }),
        // "Show me the blur": the same work the render does, on demand, so the preview
        // can show the copy that will be wired - including whether this reference is
        // one the render would blur at all (the route answers with `applies`). A blur
        // report is an ANSWER, not an action error: "no face detected" must reach the
        // panel as a reason to show, not as a thrown HTTP failure.
        blurReference: async ({ file, scope, slot }) => {
            const response = await api.fetchApi(apiUrl("/action"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: "blur",
                    file,
                    scope: scope || state.blurScope,
                    slot,
                    spec: toPayload(state),
                    node_id: node.id,
                    name: sheetName(node),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!data.ok && !data.reason) {
                return { ok: false, reason: data?.error || `HTTP ${response.status}` };
            }
            return data;
        },
    };

    panel = buildSheetInterface({ state, hooks });
    const widget = node.addDOMWidget(DOM_WIDGET, "character_sheet", panel.container, {
        getValue: () => "",
        setValue: () => {},
        getMinHeight: () => 470,
        hideOnZoom: false,
    });
    widget.element = panel.container;

    // Interface first: addDOMWidget appends the panel after every knob, which buries
    // it. Moving it to the front makes the node read as the sheet interface, with
    // the layout/render settings below it.
    if (Array.isArray(node.widgets)) {
        node.widgets = [widget, ...node.widgets.filter((item) => item !== widget)];
    }
    // `sheet_data` is the panel's storage, not something to hand-edit: collapse it
    // the way this pack hides its other internal widgets (the value still
    // serialises with the workflow, only the row disappears).
    if (dataWidget) {
        dataWidget.hidden = true;
        if (dataWidget.options) dataWidget.options.hidden = true;
        dataWidget.computeSize = () => [0, 0];
    }

    node._mmxSheet = { state, panel, widget, hooks, refresh: () => panel.refresh() };
    // Follow the run: while a prompt is executing the panel polls faster (every few
    // seconds) so the Results tab fills in cell by cell - the per-cell saver writes
    // each cell to disk the moment it finishes.
    if (!node._mmxSheetEvents) {
        const onStart = (event) => {
            const part = node._mmxSheet;
            if (part) {
                part.running = true;
                part.promptId = event?.detail?.prompt_id || "";
            }
            panel.setRunning(true);
        };
        const onStop = () => {
            const part = node._mmxSheet;
            if (part) {
                part.running = false;
                part.promptId = "";
            }
            panel.setRunning(false);
            // The previews are created/updated by the frontend as the images arrive, so the
            // node's preview size is re-applied once the run is over (and once more as the
            // DOM settles).
            schedulePreviewMode(node);
        };
        // A re-roll finishes by putting the sheet back together: this run rendered one cell, the
        // others were never touched, and the composite has to be rebuilt from the folder.
        const onSuccess = async () => {
            const part = node._mmxSheet;
            const retry = part?.retry;
            if (!part || !retry) return;
            part.retry = null;
            try {
                const payload = currentPayload(node, part.state);
                if (payload.render && "onlyCells" in payload.render) {
                    delete payload.render.onlyCells;
                    writePayload(node, payload);
                }
                const result = await sheetAction(node, {
                    action: "compose", spec: currentPayload(node, part.state),
                });
                await part.panel?.refreshResults?.();
                // Cells that never finished - the run this replaced was cancelled mid-cell, and a
                // cell only reaches the folder once it is done - are named rather than left as an
                // unexplained gap in the sheet.
                const missing = Array.isArray(result?.missing) ? result.missing : [];
                part.hooks?.status?.(
                    `${retry.cellId} re-rendered with seed ${retry.seed} · sheet recomposed`
                    + (missing.length
                        ? ` (${missing.join(", ")} not rendered yet - Run again to fill ${missing.length === 1 ? "it" : "them"} in)`
                        : "")
                );
            } catch (error) {
                part.panel?.status?.(`${retry.cellId} re-rendered, but the sheet could not be recomposed: ${error.message}`);
            }
        };
        // The render streams a clip per step for this panel (`preview_stream.py`). Every node
        // listens; the sheet name is what tells two nodes' streams apart, and a payload without
        // one (an older node, or a hand-written graph) is shown by whoever is listening.
        const onLive = (event) => {
            const data = event?.detail || {};
            const mine = sheetName(node);
            if (data.name && mine && data.name !== mine) return;
            if (data.node_id != null && node.id != null && String(data.node_id) !== String(node.id)) return;
            panel.setLivePreview?.(data);
        };
        node._mmxSheetEvents = { onStart, onStop, onLive, onSuccess };
        api.addEventListener("execution_start", onStart);
        api.addEventListener("executing", (event) => { if (!event?.detail) onStop(); });
        api.addEventListener("execution_error", onStop);
        api.addEventListener("execution_interrupted", onStop);
        api.addEventListener("execution_success", onSuccess);
        api.addEventListener(LIVE_PREVIEW_EVENT, onLive);
    }

    clearInterval(node._mmxSheetPoll);
    node._mmxSheetPoll = setInterval(() => {
        if (document.hidden || !node.graph || !panel.autoRefresh?.checked) return;
        panel.refreshResults();
    }, POLL_MS);
    panel.refreshResults();
    scheduleFit(node);
    // ComfyUI's own previews are already on the node when a saved workflow is opened (and
    // arrive after each render), so the node's preview size is applied from the start - and
    // kept that way as the frontend creates and re-creates them (see startPreviewKeeper).
    applyNodePreviews(node, nodePreviews(state));
    startPreviewKeeper(node);
    return panel;
}

/**
 * The tallest the node may get before a pane is allowed to scroll again.
 *
 * Panes grow with their content now, so a Results list with a few hundred thumbnails would
 * otherwise ask for a 3000px node. The ceiling is the viewport, so the node fills the screen
 * and scrolls after that; without a viewport (a test, an odd embed) it is PANEL_FIT.maxHeight.
 */
function fitCeiling() {
    const viewport = Number(globalThis.innerHeight) || 0;
    if (viewport <= 0) return PANEL_FIT.maxHeight;
    return Math.max(600, Math.round(viewport - 140));
}

/** Is this widget one of ComfyUI's own output previews (image host or the animation one)? */
function isPreviewWidget(widget, panelWidget = null) {
    if (!widget || widget === panelWidget) return false;
    return previewParts({ widgets: [widget] }).widgets.length > 0;
}

/**
 * Size the node's own output previews (ComfyUI's, under the panel).
 *
 * The frontend computes each preview image from the node width, so a wide node means a
 * giant preview and two of them make the node enormous. This caps them (and puts them side
 * by side) or hides them, per the panel's preference; `fitNodeToPanel` then sizes the node to
 * match. Re-applied after each render because the frontend creates/updates the preview
 * widgets when images arrive.
 */
function applyNodePreviews(node, mode) {
    const part = node?._mmxSheet;
    const skip = [DOM_WIDGET, DATA_WIDGET];
    const result = applyPreviewMode(node, mode, { skip });
    if (part) part.previewMode = result.mode;
    return result;
}

/** Apply now, then again as the frontend's own preview widgets settle after a run. */
function schedulePreviewMode(node) {
    const part = node?._mmxSheet;
    if (!part) return;
    applyNodePreviews(node, part.previewMode || nodePreviews(part.state));
    for (const delay of FIT_DELAYS) {
        setTimeout(() => { if (node._mmxSheet) applyNodePreviews(node, node._mmxSheet.previewMode); }, delay);
    }
}

/**
 * Keep the preview caps on, whatever the frontend does afterwards.
 *
 * The frontend adds the canvas image-preview widget when the image finishes loading - seconds
 * after a run on a big sheet PNG - and re-arranges the node's widgets whenever it wants, so a
 * one-shot cap at mount / on stop / on selector change can be applied to a node that has no
 * preview yet, and then never again. An uncapped preview is both huge and unstable: its minimum
 * joins the node's layout minimums while its unbounded maximum swallows the free height, so the
 * frontend's layout grows the node and this pack's fit shrinks it back, every frame (the preview
 * "jittering up and down"). This is a light timer that puts the caps back and, when it had to
 * change something, re-fits the node once so it can settle.
 */
function startPreviewKeeper(node) {
    if (node._mmxPreviewKeeper) return;
    node._mmxPreviewKeeper = setInterval(() => {
        const part = node._mmxSheet;
        if (!part || document.hidden || !node.graph) return;
        const result = enforcePreviewCaps(node, part.previewMode || nodePreviews(part.state), { skip: [DOM_WIDGET, DATA_WIDGET] });
        // Something was late or got inflated: settle the node around the corrected previews.
        if (result.changed) scheduleFit(node);
    }, PREVIEW_KEEPER_MS);
}

function stopPreviewKeeper(node) {
    clearInterval(node._mmxPreviewKeeper);
    node._mmxPreviewKeeper = null;
}

function wrapNode(nodeType) {
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
        const result = onNodeCreated?.apply(this, arguments);
        if (this._mmxSheet) return result;
        this.size = [Math.max(this.size?.[0] ?? 0, 620), Math.max(this.size?.[1] ?? 0, 780)];
        mountPanel(this);
        return result;
    };

    // The draw pass is where this frontend CREATES and re-arranges its output preview widgets
    // (`unsafeUpdatePreviews` runs from `onDrawBackground`), so it is also where a cap has to be
    // re-asserted: a widget that appears in this pass is a widget nothing has seen yet, and a
    // background tab throttles (or suspends) timers, so the draw hook is the reliable one - the
    // interval in startPreviewKeeper is the fallback for a node that is on screen but not drawn.
    //
    // No throttle on purpose: the check is a loop over the node's widgets plus one
    // `computeLayoutSize()` call each, and it only WRITES when a bound or a height is actually
    // wrong (see enforcePreviewCaps), so a frame costs nothing once the caps are in - while a
    // throttle would leave a window in which a late preview is drawn full size.
    const onDrawBackground = nodeType.prototype.onDrawBackground;
    nodeType.prototype.onDrawBackground = function () {
        const result = onDrawBackground?.apply(this, arguments);
        const part = this._mmxSheet;
        if (part) {
            const caps = enforcePreviewCaps(this, part.previewMode || nodePreviews(part.state), {
                skip: [DOM_WIDGET, DATA_WIDGET],
            });
            // A late or inflated preview changes the node's layout: settle it once.
            if (caps.changed) scheduleFit(this);
        }
        return result;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
        const result = onConfigure?.apply(this, arguments);
        if (this._mmxSheet) {
            // A loaded workflow carries a sheet_data payload from another session:
            // adopt it in place so the panel shows what will actually run.
            this._mmxSheet.panel.setState?.(readState(widgetOf(this, DATA_WIDGET)?.value || ""));
            this._mmxSheet.panel.refreshResults?.();
            // A workflow can be saved either way round: put the knob rows back where the
            // payload says they belong (setState above read the same flag).
            setKnobsVisible(this, !this._mmxSheet.panel.compactKnobs);
            applyNodePreviews(this, this._mmxSheet.panel.nodePreviews);
            // ...and a saved node size that no longer matches the panel (that is the
            // "node is suddenly enormous" state after a refresh) gets corrected too.
            scheduleFit(this);
        }
        return result;
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
        clearInterval(this._mmxSheetPoll);
        this._mmxSheetPoll = null;
        stopPreviewKeeper(this);
        for (const timer of this._mmxSheetFitTimers || []) clearTimeout(timer);
        this._mmxSheetFitTimers = null;
        // Listeners hold this node (and its panel) alive: the live stream one would keep a
        // deleted node's DOM in memory for the rest of the session.
        const events = this._mmxSheetEvents;
        if (events) {
            api.removeEventListener?.("execution_start", events.onStart);
            api.removeEventListener?.("execution_error", events.onStop);
            api.removeEventListener?.("execution_interrupted", events.onStop);
            api.removeEventListener?.("execution_success", events.onSuccess);
            api.removeEventListener?.(LIVE_PREVIEW_EVENT, events.onLive);
            this._mmxSheetEvents = null;
        }
        // The panel watches its own size to re-lay-out a resized node: that observer has to go
        // with the node, or it keeps a detached container alive.
        this._mmxSheet?.panel?.dispose?.();
        this._mmxSheet = null;
        return onRemoved?.apply(this, arguments);
    };
}

app.registerExtension({
    name: "MiniMaxH3.CharacterSheet.Panel",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== CLASS) return;
        wrapNode(nodeType);
    },
});

export { CLASS, DOM_WIDGET, DATA_WIDGET, BASE, mountPanel, listMedia, readState, toPayload };
