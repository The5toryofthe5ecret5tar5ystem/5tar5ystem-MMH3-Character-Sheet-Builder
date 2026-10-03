// Character Sheet Maker wiring contract (standalone pack).
//
// Guards the two things that silently produce a node with "no interface":
// importing `app` from the wrong ComfyUI module (the whole panel module then fails
// to load), and the panel not being mounted inside the node. Also pins the route
// namespace, the reference limits and the payload contract.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative) => readFileSync(join(here, "..", "..", "..", relative), "utf8");

const wiring = read("web/js/h3sheet_ui.js");
const core = read("web/js/h3sheet_core.mjs");
const routes = read("h3_character_sheet/sheet_routes.py");
const sheet = read("h3_character_sheet/nodes/sheet.py");
const grid = read("h3_character_sheet/nodes/grid.py");
const init = read("h3_character_sheet/__init__.py");

const ok = [];
// The standalone test runner skips any file whose SOURCE mentions ComfyUI's
// frontend api.js path, so assemble it here.
const API_MODULE = "../../scripts/" + "api.js";

// --- imports that keep the panel loading ---------------------------------------
assert.ok(wiring.includes('import { app } from "../../scripts/app.js";'),
    "app must be imported from ../../scripts/app.js");
assert.ok(wiring.includes(`import { api } from "${API_MODULE}";`),
    "api must be imported from ../../scripts/api.js");
assert.ok(!wiring.includes(`import { app } from "${API_MODULE}"`),
    "app must never be imported from api.js (no such export: the panel would not load)");
ok.push("correct ComfyUI imports (app from app.js, api from api.js)");

assert.ok(wiring.includes("panel.setRunning(true)"),
    "the panel must follow a running prompt so results fill in cell by cell");

// --- mounted inside the node, interface first, no popup ------------------------
assert.ok(wiring.includes("addDOMWidget("), "the panel must mount as a DOM widget");
assert.ok(!/document\.body\.append|showModal/.test(wiring), "no popup/modal");
assert.ok(/node\.widgets = \[widget, \.\.\.node\.widgets\.filter/.test(wiring),
    "the panel must sit above the knobs (interface first)");
assert.ok(wiring.includes('const CLASS = "MiniMaxH3CharacterSheet"'), "class name drift");
assert.ok(sheet.includes('node_id="MiniMaxH3CharacterSheet"'), "node_id drift");
assert.ok(init.includes('"MiniMaxH3CharacterSheet"'), "__init__ must export the node");
ok.push("panel is an in-node DOM widget above the knobs, no popup");

// --- the pack is standalone -----------------------------------------------------
assert.ok(!/from \.\.\.\.|motion_director|MotionDirector/.test(sheet + grid + core + wiring),
    "the pack must not import or reference the Motion Director");
assert.ok(sheet.includes('"MiniMaxH3ReferenceToVideo"'),
    "the sheet must render through the core H3 reference node");
assert.ok(sheet.includes('"MiniMaxH3SigmaShift"'), "the sheet must use the core sigma shift node");
assert.ok(sheet.includes('"H3SheetGrid"'), "the sheet must finish in this pack's grid node");
assert.ok(grid.includes('node_id="H3SheetGrid"'), "grid node_id drift");
ok.push("standalone: expansion uses ComfyUI core H3 nodes + this pack's grid only");

// --- payload + routes -----------------------------------------------------------
assert.ok(wiring.includes('const DATA_WIDGET = "sheet_data"'), "the panel must write sheet_data");
assert.ok(core.includes("export function buildSheetInterface"), "core must export the panel builder");
assert.ok(core.includes("export function toPayload") && core.includes("export function readState"),
    "core owns the payload round-trip");
assert.ok(core.includes("slots: 9") && core.includes("slots: 3"),
    "reference limits must match H3 (9 pictures, 3 videos, 3 audios)");
assert.ok(routes.includes('BASE = "/h3-character-sheet"'), "route base must be the pack's own");
assert.ok(wiring.includes('const BASE = "/h3-character-sheet"'), "panel and backend route base differ");
assert.ok(routes.includes("def register_routes()") && init.includes("register_routes"),
    "the pack must register its own routes");
ok.push("payload contract, reference limits and route namespace agree");

// --- the reference grid is wired to real IO ------------------------------------
const media = read("h3_character_sheet/sheet_media.py");
assert.ok(core.includes("class=\"mmx-card--refs\"") || core.includes("mmx-card--refs"),
    "the reference area must render per-kind cards");
assert.ok(/dragstart|dragover|drop/.test(core), "the tiles must handle drag and drop");
assert.ok(core.includes("hooks.listMedia"), "the Browse overlay must ask the wiring for media");
assert.ok(wiring.includes("listMedia"), "the wiring must provide the listMedia hook");
assert.ok(wiring.includes("panel.setState?.(readState("),
    "onConfigure must push loaded state into the panel (setState, not a new object)");
assert.ok(core.includes("function setState(next)"), "the panel must expose setState");
assert.ok(wiring.includes("`/media?${params.toString()}`"), "the hook must call the pack's /media route");
assert.ok(wiring.includes('api.fetchApi("/upload/image"'), "drops must upload through core /upload/image");
assert.ok(wiring.includes('body.append("subfolder", "h3_character_sheet")'),
    "uploads go to a dedicated input subfolder");
assert.ok(wiring.includes("boot=h3sheet_v42"),
    "core module imports must carry a fresh boot tag (bump it on every JS change, or browsers keep the cached panel)");
assert.ok(wiring.includes("panelFitHeight") && wiring.includes("resizing_node === node"),
    "the wiring must re-measure the node from its panel and never fight a drag");
assert.ok(wiring.includes("element.scrollHeight"),
    "the fit must measure the panel's CONTENT: clientHeight is imposed by the node, so only "
    + "scrollHeight can tell the node it is too short for the pane it is showing");
assert.ok(wiring.includes("layoutChanged: () => scheduleFit(node)"),
    "a pane change (which changes the panel's height) has to re-fit the node");
assert.ok(wiring.includes("action: \"presets\""),
    "the panel must ask the backend for the preset list, not carry its own copy");
// Saving and deleting the user's own presets: the route names have to match, both ways.
assert.ok(wiring.includes("savePreset: (body) => presetStore(node, \"save-preset\", body)"),
    "the panel saves through the preset store route");
assert.ok(wiring.includes("deletePreset: (id) => presetStore(node, \"delete-preset\", { id })"),
    "and deletes through it");
{
    const routes = read("h3_character_sheet/sheet_routes.py");
    for (const action of ["save-preset", "delete-preset"]) {
        assert.ok(routes.includes(`"${action}"`),
            `the ${action} action must be registered, or the panel gets a 400 for asking`);
        assert.ok(wiring.includes(`"${action}"`), `and the wiring must call it by that name`);
    }
}
// Compact knobs: the node's own rows come off, the values stay.
assert.ok(wiring.includes("action: \"knobs\""),
    "the knob list must come from the backend (labels, groups and bounds from the node schema)");
assert.ok(wiring.includes("setKnobsVisible: (visible) => setKnobsVisible(node, visible)"),
    "the panel has to be able to take the node's own knob rows away");
assert.ok(/widget\.computeSize = \(\) => \[0, 0\]/.test(wiring),
    "a hidden knob collapses to zero height, the idiom this pack already uses for sheet_data");
assert.ok(wiring.includes("INTERNAL_WIDGETS"),
    "only the panel and its storage are exempt: every knob row goes, so the node is panel-height");
assert.ok(read("h3_character_sheet/knobs.py").includes("FRONTEND_KNOBS"),
    "the browser's own seed-mode widget is described too, or hiding it would lose the setting");
// The Help tab: the guide and the file check both come from the backend.
assert.ok(wiring.includes("action: \"help\""),
    "the guide must be served by the backend (help.py), not carried in the panel");
assert.ok(wiring.includes("listHelp"), "the panel asks for it through a hook");
assert.ok(wiring.includes("readWidgets: (names) => readWidgets(node, names)"),
    "the settings fields show the node's live values, not copies");
// ComfyUI's own output previews scale with the node width; the pack sizes them.
assert.ok(wiring.includes("applyPreviewMode") && wiring.includes("setPreviewMode:"),
    "the panel has to be able to resize the node's own preview widgets");
assert.ok(wiring.includes("isPreviewWidget(item, widget)"),
    "the node fit must count a capped preview at its capped height, not at the frontend's");
assert.ok(wiring.includes("schedulePreviewMode(node)"),
    "the frontend rebuilds the previews after a run, so the size is re-applied then too");
// Panes fill the node now, so the fit needs a ceiling and the panel watches its own size.
assert.ok(wiring.includes("ceiling: fitCeiling()"),
    "the node fit is capped by the viewport, or a long Results list asks for a 3000px node");
assert.ok(wiring.includes("panel?.dispose?.()"),
    "the resize observer goes with the node (onRemoved disposes the panel)");
assert.ok(routes.includes('"knobs"'), "the action route must list knobs among its actions");
assert.ok(wiring.includes("widget.value = value"),
    "applying a preset has to write the node's own widgets (cell_size, steps, layout...)");
assert.ok(/payload\.cells = current\.cells/.test(wiring),
    "persisting must not wipe a workflow's cells when the panel has none");
// The JS default matrix and the Python one must stay identical.
{
    const planner = read("h3_character_sheet/planner.py");
    const block = planner.slice(planner.indexOf("DEFAULT_MATRIX"), planner.indexOf("def default_cells"));
    const pythonCells = [...block.matchAll(/\("([a-z-]+)", "([a-z-]+)", "([a-z-]+)"\)/g)]
        .map((m) => `${m[1]}-${m[2]}-${m[3]}`);
    const jsBlock = core.slice(core.indexOf("DEFAULT_MATRIX"), core.indexOf("export function defaultCells"));
    const jsCells = [...jsBlock.matchAll(/\["([a-z-]+)", "([a-z-]+)", "([a-z-]+)"\]/g)]
        .map((m) => `${m[1]}-${m[2]}-${m[3]}`);
    assert.deepEqual(jsCells, pythonCells,
        "the panel's default matrix must match the node's fallback exactly");
    assert.equal(jsCells.length, 8);
}
// Same for the background presets: the picker must offer what the node parses.
{
    const spec = read("h3_character_sheet/sheet_spec.py");
    const block = spec.slice(spec.indexOf("BACKGROUNDS"), spec.indexOf("VIEW_KEYS = tuple"));
    const pythonKeys = [...block.matchAll(/SheetOption\(\s*"([a-z]+)"/g)].map((m) => m[1]);
    const jsBlock = core.slice(core.indexOf("export const BACKGROUNDS"), core.indexOf("export const DEFAULT_MATRIX"));
    const jsKeys = [...jsBlock.matchAll(/\["([a-z]+)",/g)].map((m) => m[1]);
    assert.deepEqual(jsKeys, pythonKeys,
        "the background picker must list exactly the presets the node understands");
    assert.ok(pythonKeys.includes("custom"), "custom text must stay available");
}
assert.ok(media.includes("def list_media") && media.includes("resolve_subfolder"),
    "the backend must list media and refuse traversal");
assert.ok(routes.includes('BASE + "/media"'), "the media route must be registered");
ok.push("reference grid: drops upload, Browse reads /media, routes registered");

console.log("h3sheet_ui wiring: PASS");
for (const line of ok) console.log(" -", line);
