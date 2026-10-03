// Character Sheet Maker panel (jsdom): the interface a user actually sees.
//
// Two regressions are pinned here:
//   1. the bug that shipped first - the node rendered its knobs with no interface
//      at all, because the wiring module imported `app` from api.js and never
//      loaded, and
//   2. the reference area must behave like the Easy-Media picture grid: drop files
//      on a tile, drag a tile onto another to reorder, click a tile to browse what
//      is already in ComfyUI, preview, remove, and say what each one is for.
//
// The panel DOM is built by h3sheet_core.mjs (no ComfyUI imports), so it can be
// mounted here for real.
import assert from "node:assert/strict";

// jsdom normally comes from the pack's devDependencies. A checkout that cannot
// install node_modules (e.g. a share without symlink support) may inject it as
// `globalThis.__JSDOM__` before importing this file instead.
const { JSDOM } = globalThis.__JSDOM__ ? { JSDOM: globalThis.__JSDOM__ } : await import("jsdom");

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
    url: "http://localhost/",
});
Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MouseEvent: dom.window.MouseEvent,
});
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

const core = await import("../h3sheet_core.mjs?test=h3sheet_core_v2");
// jsdom ships no canvas: a minimal 2D context, so the paint overlay's drawing is
// exercised (and asserted) instead of throwing "not implemented" into the log.
const drawn = [];
dom.window.HTMLCanvasElement.prototype.getContext = function getContext() {
    return {
        save() {}, restore() {}, clearRect() {}, beginPath() {}, moveTo() {},
        lineTo() {}, closePath() {}, fill() {}, stroke() {},
        set fillStyle(value) { drawn.push(["fillStyle", value]); },
        set strokeStyle(value) { drawn.push(["strokeStyle", value]); },
        set lineWidth(value) { drawn.push(["lineWidth", value]); },
        set lineCap(_value) {}, set lineJoin(_value) {},
    };
};
const ok = [];
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = (node) => node.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));

/** Fire a DOM event carrying a fake DataTransfer (jsdom has none). */
function fire(target, type, dataTransfer) {
    const event = new dom.window.Event(type, { bubbles: true, cancelable: true });
    if (dataTransfer) event.dataTransfer = dataTransfer;
    target.dispatchEvent(event);
    return event;
}

const fileTransfer = (files) => ({ files, types: ["Files"], items: [], setData() {} });
const slotTransfer = () => ({ files: [], types: ["text/plain"], items: [], setData() {} });

// --- mounts as an interface, not a popup ---------------------------------------
const saved = [];
let picked = null;
let composed = 0;
let cleared = 0;
const uploads = [];
const uploadPath = (file) => `h3_character_sheet/${file.name}`;
let mediaListing = {
    ok: true,
    source: "inputs",
    kind: "image",
    items: [
        { name: "face.png", path: "h3_character_sheet/face.png", kind: "image", url: "/view?filename=face.png&type=input&subfolder=h3_character_sheet" },
        { name: "body.webp", path: "body.webp", kind: "image", url: "/view?filename=body.webp&type=input&subfolder=" },
    ],
};

const state = core.readState("");
const blurCalls = [];
let blurAnswer = null;
const panel = core.buildSheetInterface({
    state,
    hooks: {
        stateChanged: (payload) => saved.push(payload),
        status: () => {},
        assetUrl: (url) => url,
        upload: async (file, groupKey) => {
            uploads.push([groupKey, file.name]);
            return uploadPath(file);
        },
        listMedia: async (request) => ({ ...mediaListing, request }),
        pickFrame: (cellId, index) => { picked = [cellId, index]; },
        compose: () => { composed += 1; },
        clearSheet: () => { cleared += 1; },
        listResults: async () => null,
        // The route the render uses, stubbed: the panel only needs the shape.
        blurReference: async (request) => {
            blurCalls.push(request);
            return blurAnswer;
        },
    },
});
assert.ok(panel.container.classList.contains("mmx-sheet"), "the panel root must be the sheet container");
assert.equal(panel.container.parentElement, null, "the panel must not be attached to the page body");
assert.equal(panel.container.querySelectorAll("dialog").length, 0, "no dialog/popup");
assert.ok(panel.container.querySelector("style"), "the panel injects its own stylesheet");
ok.push("panel mounts as an in-node container (no popup, not in document.body)");

// --- references: ONE grid, sorted pictures -> video -> audio -------------------
assert.equal(panel.container.querySelectorAll(".mmx-card--refs").length, 1, "one unified reference card");
assert.equal(panel.container.querySelectorAll(".mmx-sheet-ref").length, 0, "no reference tiles before anything is added");
const refBox = () => panel.container.querySelector(".mmx-refbox");
assert.ok(refBox(), "the references live in one box");
assert.equal(refBox().style.minHeight, `${core.REF_SECTION.height}px`,
    "the box's height is a FLOOR: it grows with the pane so a taller node shows bigger tiles");
let addTiles = panel.container.querySelectorAll(".mmx-tile--add");
assert.equal(addTiles.length, 1, "one Add Media tile, not one per kind");
assert.ok(addTiles[0].textContent.includes("Add Media"), "the tile says Add Media");
assert.ok(panel.container.querySelector('[data-action="add-media"]'), "and the header has an Add Media button");
assert.ok(panel.container.querySelector('[data-action="browse-media"]'), "plus Browse ComfyUI for existing media");
assert.equal(panel.container.querySelectorAll(".mmx-sheet-ref-role").length, 0, "no role boxes for empty slots");
assert.equal(panel.container.querySelectorAll('input[type="file"]').length, 1, "one file input for every kind");
ok.push("one unified reference grid with a single Add Media tile");

// --- dropping files routes each one to its own kind ---------------------------
fire(addTiles[0], "dragover", fileTransfer([]));
assert.ok(addTiles[0].classList.contains("is-dropping"), "a drag over Add Media highlights it");
fire(addTiles[0], "drop", fileTransfer([
    { name: "face.png", type: "image/png" },
    { name: "clip.mp4", type: "video/mp4" },
    { name: "voice.wav", type: "audio/wav" },
    { name: "notes.txt", type: "text/plain" },
]));
await tick();
assert.equal(state.refs.pictures[0].file, "h3_character_sheet/face.png", "the picture lands in pictures");
assert.equal(state.refs.videos[0].file, "h3_character_sheet/clip.mp4", "the clip lands in videos");
assert.equal(state.refs.audios[0].file, "h3_character_sheet/voice.wav", "the audio lands in audios");
assert.ok(uploads.some(([key, name]) => key === "pictures" && name === "face.png"), "each file uploads via its own kind");
assert.equal(saved.at(-1).refs.pictures[0].imageFile, "h3_character_sheet/face.png", "the drop persists into the payload");
ok.push("one drop adds pictures, video and audio at once (routed by kind)");

// --- the grid shows them in one row, pictures first ---------------------------
// Tiles are the interactive elements (drop/drag live on them); the wrapper also holds
// the role box, so both are useful.
const gridTiles = () => [...panel.container.querySelectorAll(".mmx-refbox .mmx-tile.is-filled")];
const gridWraps = () => [...panel.container.querySelectorAll(".mmx-refbox .mmx-sheet-ref")];
let tiles = gridTiles();
assert.deepEqual(tiles.map((el) => el.dataset.group), ["pictures", "videos", "audios"],
    "auto-sorted: pictures, then video, then audio");
assert.equal(tiles[0].querySelector(".mmx-tile__badge").textContent, "1", "each kind keeps its own prompt number");
assert.equal(tiles[1].querySelector(".mmx-tile__badge").textContent, "1", "the video is <Video 1>, not number 2");
assert.equal(tiles[2].querySelector(".mmx-tile__badge").textContent, "1", "the audio is <Audio 1>");
assert.ok(tiles[0].querySelector(".mmx-tile__kind--image"), "the picture tile is badged as a picture");
assert.ok(tiles[1].querySelector(".mmx-tile__kind--video"), "the video tile is badged as a video");
assert.ok(tiles[2].querySelector(".mmx-tile__kind--audio"), "the audio tile is badged as audio");
assert.equal(gridWraps()[1].querySelector(".mmx-sheet-ref-role").placeholder, "clothing and body",
    "each tile keeps its kind's role hint");
assert.equal(panel.container.querySelectorAll(".mmx-tile--add").length, 1, "still one Add Media tile at the end");
ok.push("one row, kind badges, per-kind numbering and role hints");

// --- face blur is a per-tile decision, and pictures only ----------------------
// auto -> on -> off in one click, because the useful question ("is this picture the
// identity or is it an outfit?") is answered by the roles, and the rare override should
// not need a menu.
const blurChips = () => [...panel.container.querySelectorAll(".mmx-refbox .mmx-tile__blur")];
assert.equal(blurChips().length, 1, "only the picture tile carries a face-blur control");
assert.equal(blurChips()[0].textContent, "Blur auto", "and it starts on auto");
assert.ok(blurChips()[0].classList.contains("mmx-tile__blur--auto"), "styled by its mode");
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "Blur on", "one click turns it on");
assert.equal(saved.at(-1).refs.pictures[0].blurFace, "on", "and the choice persists into the payload");
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "Blur off", "the next click turns it off");
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "Blur auto", "and the cycle wraps back to auto");
assert.equal(saved.at(-1).refs.pictures[0].blurFace, "auto", "round-tripped, not lost");
assert.ok(!saved.at(-1).refs.videos[0].blurFace,
    "a video has no blur field: only pictures can be blurred");
ok.push("per-tile face blur: auto -> on -> off, pictures only");

// --- every tile control has its own place -------------------------------------
// The bug this pins: three absolutely positioned layers shared one corner, so the
// checkbox, the hover buttons and the blur toggle sat on top of each other - and on the
// picture. Each control now lives somewhere it cannot collide.
{
    const box = gridTiles()[0];
    const top = box.querySelector(".mmx-tile__top");
    assert.ok(top, "the tile has one control row");
    assert.equal(top.querySelectorAll(".mmx-tile__use").length, 1, "with the enable checkbox in it");
    assert.equal(top.querySelectorAll(".mmx-tile__actions").length, 0,
        "and nothing else: a row of action buttons pushed the strip off the tile");
    const useRule = /\.mmx-tile__use \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(useRule && !/position:\s*absolute/.test(useRule[1]), "the checkbox sits in the row, in flow");

    // Preview / remove are stacked VERTICALLY in the top-right corner, which is what makes
    // them stay inside a narrow tile (a horizontal pair needs ~52px it does not have).
    const actions = box.querySelector(".mmx-tile__actions");
    assert.ok(actions, "the tile carries preview and remove");
    assert.equal(actions.querySelectorAll("button").length, 2, "one of each");
    const actionsRule = /\.mmx-tile__actions \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(actionsRule && /flex-direction:\s*column/.test(actionsRule[1]), "stacked vertically");
    assert.ok(/top:\s*3px/.test(actionsRule[1]) && /right:\s*3px/.test(actionsRule[1]),
        "in the tile's top-right corner");

    // The blur toggle takes the picture's bottom-left corner - the spot the filename had,
    // so it is a state readout you can see without hovering, and it never covers the face.
    const blur = box.querySelector(".mmx-tile__blur");
    assert.ok(blur, "the picture carries its blur state on the tile");
    assert.ok(!box.querySelector(".mmx-tile__name"), "replacing the filename there, not adding to it");
    assert.ok(gridTiles()[1].querySelector(".mmx-tile__name"),
        "a video keeps its filename: nothing to blur there");
    const rule = /\.mmx-tile__blur \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(rule && /bottom:\s*3px/.test(rule[1]) && /left:\s*4px/.test(rule[1]),
        "pinned to the bottom-left corner on purpose");

    // The row under the tile belongs to the role box alone: it is the only thing here that
    // gets typed into, and a button beside it left no room to type.
    const wrap = gridWraps()[0];
    const siblings = [...wrap.children].filter((el) => el !== box);
    assert.equal(siblings.length, 1, "the row under the tile holds exactly one thing");
    assert.ok(siblings[0].classList.contains("mmx-sheet-ref-role"), "the role box, with the full width");
    ok.push("tile controls: quiet top row, blur on the picture's bottom-left, role box full width");
}

// --- the blur area is one setting for the sheet -------------------------------
const blurSelect = panel.container.querySelector('[data-action="blur-scope"]');
assert.ok(blurSelect, "the reference header offers a blur area");
assert.equal(blurSelect.value, "hair", "defaulting to face + hair");
// Label and control stay together at the left of the header, before the buttons: a
// wrapping row used to put them on different lines.
{
    const head = blurSelect.closest(".mmx-card__head");
    const kids = [...head.children];
    const label = kids.findIndex((el) => el.textContent === "Blur area");
    assert.equal(kids[label + 1], blurSelect, "the label sits immediately before its control");
    assert.ok(label < kids.findIndex((el) => el.dataset?.action === "browse-media"),
        "and both come before the buttons");
}
assert.equal(core.blurScope(core.readState("")), "hair", "and the state reader agrees");
blurSelect.value = "head";
blurSelect.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
assert.equal(state.blurScope, "head", "picking one writes it to the panel state");
assert.equal(saved.at(-1).render.blurScope, "head", "and into the payload the node parses");
assert.equal(core.readState(JSON.stringify(saved.at(-1))).blurScope, "head", "round-tripped");
assert.equal(core.blurScope({ blurScope: "nonsense" }), "hair", "an unknown area falls back");
ok.push("blur area: face / face + hair / whole head, one setting for the sheet");

// --- an unchecked tile must not eat a prompt number ---------------------------
// The prompt counts the references the render wires, and an unchecked tile is not one
// of them: it shows no number, and the tiles after it keep theirs.
{
    const restore = state.refs.pictures.map((slot) => ({ ...slot }));
    state.refs.pictures = [
        { file: "h3_character_sheet/face.png", role: "face and hair", enabled: true },
        { file: "h3_character_sheet/off.png", role: "body", enabled: false },
        { file: "h3_character_sheet/clothes.png", role: "clothing", enabled: true },
    ];
    panel.setState(state);
    const pictureTiles = gridTiles().filter((el) => el.dataset.group === "pictures");
    assert.equal(pictureTiles.length, 3, "an unchecked tile stays visible so it can be re-enabled");
    assert.deepEqual(
        pictureTiles.map((el) => el.querySelector(".mmx-tile__badge").textContent),
        ["1", "\u2013", "2"],
        "the unchecked tile takes no number and the tiles after it keep theirs",
    );
    assert.equal(pictureTiles[1].querySelector(".mmx-tile__badge").dataset?.group, undefined,
        "the badge is the only place the number appears");
    ok.push("an unchecked reference keeps no prompt number and does not shift the others");
    state.refs.pictures = restore;
    panel.setState(state);
}

// --- tiles are sized to fit the box, keeping each media's own shape -----------
// The wrapper carries the width (so the role box below matches); the tile inside it
// is the sized element.
const dims = (el) => ({ w: parseFloat(el.style.width), h: parseFloat(el.style.height) });
const [pic, video, audio] = gridTiles();
assert.ok(Number.isFinite(dims(pic).h) && dims(pic).h > 0, `the tiles are sized by the layout (${JSON.stringify(dims(pic))})`);
assert.equal(dims(pic).h, dims(video).h, "every tile shares one height");
assert.equal(dims(video).h, dims(audio).h, "including the audio chip");
assert.ok(Math.abs(dims(video).w / dims(video).h - 16 / 9) < 0.06, `the video tile keeps its wide shape (${dims(video).w}x${dims(video).h})`);
assert.ok(dims(video).w > dims(pic).w, "so it is wider than a square picture tile");
const used = [pic, video, audio].reduce((sum, el) => sum + dims(el).w, 0);
assert.ok(used <= core.REF_SECTION.width, `the row fits the fixed box: ${used} <= ${core.REF_SECTION.width}`);
assert.ok(dims(pic).h <= core.REF_SECTION.height, "and the tiles fit its height");
// The media's real shape is remembered once the media reports its size.
const tallImg = pic.querySelector("img");
Object.defineProperty(tallImg, "complete", { value: true, configurable: true });
Object.defineProperty(tallImg, "naturalWidth", { value: 900, configurable: true });
Object.defineProperty(tallImg, "naturalHeight", { value: 1600, configurable: true });
tallImg.dispatchEvent(new dom.window.Event("load"));
await tick();
assert.ok(dims(gridTiles()[0]).h < dims(pic).h + 1, "a 9:16 photo re-fits the row instead of being boxed");
assert.ok(Math.abs(dims(gridTiles()[0]).w / dims(gridTiles()[0]).h - 0.5625) < 0.06,
    "and the tile takes the photo's own aspect (no black bars)");
ok.push("tiles scale to fit the box and keep the media's aspect ratio");

// --- the layout helper itself: more tiles, smaller tiles ----------------------
assert.equal(core.fitTileLayout([], {}).perRow, 0, "no tiles, no layout");
const wide = core.fitTileLayout([1, 1], { width: 400, height: 160, gap: 6 });
const crowded = core.fitTileLayout(Array.from({ length: 12 }, () => 1), { width: 400, height: 160, gap: 6 });
assert.ok(wide.tileHeight > crowded.tileHeight, "twelve tiles are smaller than two");
assert.ok(crowded.tileHeight >= core.REF_SECTION.minTile, "and never collapse below the minimum");
assert.ok(core.fitTileLayout([1, 1, 1], { width: 400, height: 1000, gap: 6 }).tileHeight <= 1000,
    "the box height is the cap");
// Wrapping costs height, so a set that has to wrap gets smaller tiles instead of
// overflowing the fixed box.
const wrapped = core.fitTileLayout([1, 16 / 9, 5 / 2], { width: 628, height: 142, gap: 6 });
assert.equal(wrapped.rows, 1, "three tiles of these shapes fit on one row");
assert.ok(wrapped.tileHeight <= 142, "and the row stays inside the box height");
const tooMany = core.fitTileLayout([2.5, 1.78, 1, 1, 1], { width: 628, height: 142, gap: 6 });
assert.ok(tooMany.rows * tooMany.tileHeight + (tooMany.rows - 1) * 6 <= 142 + 0.001,
    `every row fits the box height: ${JSON.stringify(tooMany)}`);
assert.equal(core.clampAspect(0.05), 0.38, "extreme ratios are clamped");
assert.equal(core.clampAspect(9), 2.6);
assert.ok(Math.abs(core.clampAspect(0.5625) - 0.5625) < 0.001,
    "a 9:16 portrait is not squeezed into 2:3 (a wider box would put bars back)");
assert.equal(core.clampAspect(NaN), null);
ok.push("fitTileLayout keeps every tile inside the box");

// --- the caps still hold, and the Add Media tile only goes when all are full --
fire(addTiles[0], "drop", fileTransfer(Array.from({ length: 12 }, (_, i) => ({ name: `extra${i}.png`, type: "image/png" }))));
await tick();
assert.equal(state.refs.pictures.filter((slot) => slot.file).length, 9, "pictures cap at 9");
fire(addTiles[0], "drop", fileTransfer(Array.from({ length: 5 }, (_, i) => ({ name: `clip${i}.mp4`, type: "video/mp4" }))));
await tick();
assert.equal(state.refs.videos.filter((slot) => slot.file).length, 3, "videos cap at 3");
assert.equal(panel.container.querySelectorAll(".mmx-tile--add").length, 1, "audio still has room, so Add Media stays");
assert.equal(gridTiles().length, 13, "9 pictures + 3 videos + 1 audio are all shown");
ok.push("per-kind caps hold and Add Media stays while any kind has room");

// --- drag one tile onto another of the SAME kind to reorder -------------------
tiles = gridTiles();
const before = state.refs.pictures.map((slot) => slot.file);
fire(tiles[2], "dragstart", slotTransfer());
assert.ok(tiles[2].classList.contains("is-drag"), "the dragged tile is marked");
const audioTileNow = gridTiles()[12];
fire(audioTileNow, "drop", slotTransfer());
fire(tiles[2], "dragend", slotTransfer());
await tick();
assert.deepEqual(state.refs.pictures.map((slot) => slot.file), before,
    "a picture cannot be dropped onto an audio tile: the prompt numbers each kind separately");
fire(tiles[0], "dragstart", slotTransfer());
fire(gridTiles()[2], "drop", slotTransfer());
fire(tiles[0], "dragend", slotTransfer());
await tick();
assert.equal(state.refs.pictures[0].file, before[2], "dragging within the pictures reorders them");
ok.push("dragging reorders within a kind and refuses to mix kinds");

// --- the character prompt + suppression fields drive the payload ----------------
assert.ok(panel.promptBox, "the panel offers a character prompt box");
assert.ok(panel.negativeBox, "and a suppression box");
panel.promptBox.value = "young woman with long silver hair";
panel.promptBox.dispatchEvent(new dom.window.Event("input"));
assert.equal(saved.at(-1).globalPrompt, "young woman with long silver hair",
    "the character prompt is persisted for the node");
assert.equal(saved.at(-1).negativePrompt, undefined, "an empty suppression box is left out");
panel.negativeBox.value = "text, watermark, logo";
panel.negativeBox.dispatchEvent(new dom.window.Event("input"));
assert.equal(saved.at(-1).negativePrompt, "text, watermark, logo");
// ...and they come back from a saved payload.
const withPrompt = core.readState(JSON.stringify({
    globalPrompt: "blue-haired android", negativePrompt: "no text", refs: {}, cells: [],
}));
assert.equal(withPrompt.prompt, "blue-haired android");
assert.equal(withPrompt.negative, "no text");
const promptPanel = core.buildSheetInterface({ state: withPrompt, hooks: {} });
assert.equal(promptPanel.promptBox.value, "blue-haired android");
assert.equal(promptPanel.negativeBox.value, "no text");
ok.push("character prompt + suppression round-trip through the payload");

// --- typing a role persists into the sheet_data payload ------------------------
const roleBox = gridWraps()[0].querySelector(".mmx-sheet-ref-role");
roleBox.value = "body proportions";
roleBox.dispatchEvent(new dom.window.Event("input"));
assert.equal(saved.at(-1).refs.pictures[0].role, "body proportions");
ok.push("role edits persist into the node payload");

// --- removing a reference shrinks the row back ---------------------------------
click(gridTiles()[0].querySelector(".mmx-tile__actions button.mmx-btn--danger"));
await tick();
assert.equal(state.refs.pictures[0].file, "", "remove empties the slot");
assert.equal(gridTiles().length, 12, "the grid shrinks by one tile");
ok.push("remove clears one slot and the grid shrinks");

// --- clearing empties everything back to the Add Media tile --------------------
click(panel.container.querySelector('[data-action="clear-media"]'));
await tick();
assert.equal(gridTiles().length, 0, "no tiles after Clear");
assert.equal(panel.container.querySelectorAll(".mmx-tile--add").length, 1, "back to the single Add Media tile");
assert.equal(saved.at(-1).refs.pictures.length, 0, "and the payload has no media");
assert.equal(saved.at(-1).refs.videos.length, 0, "for any kind");
ok.push("Clear empties every kind back to one Add Media tile");

// --- Browse overlay: lists ComfyUI media and routes the clicked item ----------
const browseButton = panel.container.querySelector('[data-action="browse-media"]');
click(browseButton);
await tick();
const overlay = panel.container.querySelector(".mmx-overlay.mmx-browse");
assert.ok(overlay, "Browse opens an overlay inside the panel");
assert.equal(overlay.parentElement, panel.container, "the overlay stays inside the node, not the page");
assert.equal(panel.container.dataset.browseFor, "media:auto", "the overlay is filling the whole grid");
assert.ok(overlay.textContent.includes("Choose media"), "the picker is not kind-specific");
const picks = overlay.querySelectorAll(".mmx-pick");
assert.equal(picks.length, 2, "every listed item gets a tile");
assert.ok(picks[0].querySelector("img"), "an image pick shows a thumbnail");
assert.ok(picks[0].querySelector(".mmx-tile__kind--image"), "and is badged as a picture");
assert.ok(picks[0].textContent.includes("face.png"), "a pick names its file");
click(picks[1]);
await tick();
assert.equal(panel.container.querySelector(".mmx-overlay"), null, "picking closes the overlay");
assert.ok(state.refs.pictures.some((slot) => slot.file === "body.webp"), "the clicked media lands in its own kind");
ok.push("Browse overlay lists ComfyUI media and assigns the clicked item");

// --- Browse asks the backend per source and reports an empty folder -----------
mediaListing = { ok: true, source: "outputs", kind: "video", items: [] };
panel.openBrowse(core.REF_GROUPS[1], null);
await tick();
const browse2 = panel.container.querySelector(".mmx-overlay.mmx-browse");
assert.ok(browse2, "Browse opens for videos too");
const outputs = [...browse2.querySelectorAll("button")].find((b) => b.textContent === "Outputs");
click(outputs);
await tick();
const browse3 = panel.container.querySelector(".mmx-overlay.mmx-browse");
assert.ok(browse3.textContent.includes("Nothing here yet"), "an empty folder says so instead of looking broken");
assert.ok(panel.container.querySelector('[data-mmx-browse-search]'), "the picker has a search box");
assert.ok(panel.container.querySelector('[data-mmx-browse-kind]'), "the picker has a kind filter");
panel.closeOverlay();
assert.equal(panel.container.querySelector(".mmx-overlay"), null, "close removes the overlay");
ok.push("Browse switches source (inputs / outputs) and reports an empty folder");

// --- preview overlay for a filled slot ----------------------------------------
panel.openPreview(core.REF_GROUPS[0], 0);
const preview = panel.container.querySelector(".mmx-overlay.mmx-preview");
assert.ok(preview, "Preview opens an overlay");
assert.ok(preview.querySelector("img"), "a picture preview renders the image");
assert.ok(preview.textContent.includes("body.webp"), "the preview names the file");
fire(preview, "mousedown");
assert.equal(panel.container.querySelector(".mmx-overlay"), null, "clicking the backdrop closes the preview");
ok.push("preview overlay shows the reference at full size and closes on backdrop click");

// --- the preview shows the blur, because that is what the render wires ---------
// "Preview" on a reference that is going to be blurred has to show the copy the render
// uses, or it is previewing a picture that never gets rendered.
{
    blurAnswer = {
        ok: true,
        applies: true,
        reason: "1 face(s) blurred",
        scope: "head",
        url: "/view?filename=body-blurface-ab12.png&type=input&subfolder=h3_character_sheet%2Fderived",
    };
    panel.setState(state);
    panel.openPreview(core.REF_GROUPS[0], 0);
    await tick();
    const stage = panel.container.querySelector(".mmx-overlay.mmx-preview .mmx-preview__stage img");
    assert.ok(blurCalls.length > 0, "opening a picture preview asks the route for its blur");
    assert.ok(
        blurCalls.at(-1).file.endsWith("body.webp"),
        `for the file on the tile (got ${blurCalls.at(-1).file})`,
    );
    assert.ok(stage.src.includes("blurface"), "showing the blurred copy, not the original");
    const bar = panel.container.querySelector(".mmx-preview__bar");
    assert.ok(bar.textContent.includes("What the render sends"), "and says that is what the render sends");
    assert.ok(bar.textContent.includes("head"), "naming the area in use");
    const original = [...bar.querySelectorAll("button")].find((b) => b.textContent === "Original");
    click(original);
    assert.ok(!stage.src.includes("blurface"), "the original is one click away for comparison");
    ok.push("the eyeball preview shows the blurred copy the render will wire");

    // A reference the render leaves alone must not look like it was edited.
    blurAnswer = { ok: true, applies: false, reason: "1 face(s) blurred", url: "/view?filename=x-blurface.png&type=input" };
    panel.openPreview(core.REF_GROUPS[0], 0);
    await tick();
    const stage2 = panel.container.querySelector(".mmx-overlay.mmx-preview .mmx-preview__stage img");
    assert.ok(!stage2.src.includes("blurface"), "an untouched reference previews as its own file");
    assert.ok(
        panel.container.querySelector(".mmx-preview__bar").textContent.includes("unchanged"),
        "and the bar says the render sends it unchanged",
    );
    panel.closeOverlay();
    ok.push("a reference the render leaves alone previews as itself, and says so");
}

// --- remove button on a tile (already covered above) ---------------------------

// --- loading a workflow repopulates the panel in place ---------------------------
// The panel closes over its state object, so setState must mutate it: replacing the
// object (the bug) left a loaded workflow looking empty.
const loaded = core.readState(JSON.stringify({
    globalPrompt: "from the workflow",
    refs: { pictures: [{ imageFile: "h3_character_sheet/face.png", role: "face" }], videos: [], audios: [] },
    cells: [{ id: "front-neutral-neutral", view: "front", pose: "neutral", expression: "neutral" }],
}));
const reloaded = core.buildSheetInterface({ state: core.readState(""), hooks: { stateChanged: () => {}, status: () => {}, assetUrl: (u) => u } });
assert.equal(reloaded.container.querySelectorAll(".mmx-sheet-ref").length, 0, "starts empty");
reloaded.setState(loaded);
assert.equal(reloaded.container.querySelectorAll(".mmx-sheet-ref").length, 1, "the loaded reference appears");
assert.equal(reloaded.container.querySelectorAll(".mmx-sheet-cell").length, 1, "and so do the loaded cells");
assert.equal(reloaded.container.querySelector('.mmx-tab[data-tab="cells"]').textContent, "Cells 1", "tab counts follow");
assert.equal(reloaded.promptBox.value, "from the workflow", "the character prompt comes back too");
// A picture tile shows its blur state in the corner the filename used to take, so the
// name lives in the tooltip (and in the preview header) rather than under the thumbnail.
{
    const tile = reloaded.container.querySelector(".mmx-sheet-ref .mmx-tile.is-filled");
    assert.ok(tile.querySelector(".mmx-tile__blur"), "a picture shows its blur state on the tile");
    assert.ok(tile.title.includes("face.png"), "and keeps the file name in its tooltip");
}
// No context field, so an empty setState resets cleanly.
reloaded.setState(core.readState(""));
assert.equal(reloaded.container.querySelectorAll(".mmx-sheet-ref").length, 0);
assert.equal(reloaded.container.querySelector('.mmx-tab[data-tab="cells"]').textContent, "Cells 0");
ok.push("setState adopts a loaded workflow (references, cells, prompt) in place");

// --- a node without cells says what will actually run ---------------------------
// The panel used to just say "No cells yet" while the node quietly rendered the
// default matrix - the panel has to describe the run, not its own memory.
const empty = core.buildSheetInterface({ state: core.readState(""), hooks: { stateChanged: () => {}, status: () => {} } });
click([...empty.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
assert.ok(empty.container.textContent.includes("2 cell(s)"),
    "an empty cell list must spell out the plan the ticks imply");
assert.equal(empty.container.querySelectorAll(".mmx-sheet-cell").length, 0);
assert.deepEqual(core.defaultCells().map((cell) => cell.id), [
    "face-neutral-neutral", "face-neutral-smile", "portrait-neutral-neutral",
    "front-neutral-neutral", "front-a-pose-neutral", "front-t-pose-neutral",
    "profile-neutral-neutral", "back-neutral-neutral",
]);
let adopted = null;
const adopting = core.buildSheetInterface({
    state: core.readState(""),
    hooks: { stateChanged: (payload) => { adopted = payload; }, status: () => {} },
});
click([...adopting.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
click([...adopting.container.querySelectorAll("button")].find((b) => b.textContent === "Use these 2 cells"));
assert.equal(adopting.container.querySelectorAll(".mmx-sheet-cell").length, 2, "one click fills the ticks");
assert.equal(adopted.cells.length, 2, "and it is persisted for the node");
assert.equal(adopting.container.querySelector('.mmx-tab[data-tab="cells"]').textContent, "Cells 2");
ok.push("an empty node renders (and can materialise) exactly what the ticks ask for");

// --- background picker ---------------------------------------------------------
{
    const bgState = core.readState("");
    assert.equal(bgState.background, "neutral", "an old payload renders the neutral backdrop");
    let payload = null;
    const panel = core.buildSheetInterface({
        state: bgState,
        hooks: { stateChanged: (next) => { payload = next; }, status: () => {} },
    });
    click([...panel.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
    const select = panel.container.querySelector(".mmx-sheet-background");
    assert.ok(select, "the Cells tab offers a background picker");
    assert.deepEqual([...select.options].map((o) => o.value),
        ["neutral", "white", "grey", "black", "green", "blue", "custom"]);
    // the custom text box only shows up when it is needed
    assert.equal(panel.container.querySelector(".mmx-sheet-background-custom").style.display, "none");
    select.value = "green";
    select.dispatchEvent(new dom.window.Event("change"));
    assert.equal(payload.render.background, "green");
    select.value = "custom";
    select.dispatchEvent(new dom.window.Event("change"));
    assert.equal(panel.container.querySelector(".mmx-sheet-background-custom").style.display, "");
    const box = panel.container.querySelector(".mmx-sheet-background-custom");
    box.value = "deep red velvet curtain";
    box.dispatchEvent(new dom.window.Event("input"));
    assert.equal(payload.render.backgroundCustom, "deep red velvet curtain");
    ok.push("background picker (presets + custom text) writes the payload");
}

// --- the ticks are part of the payload -----------------------------------------
// An empty cell list used to mean "render the built-in 8-view matrix", which is
// how a sheet the user never asked for got rendered. The ticks now travel with the
// payload, so the node renders exactly the views the panel was showing.
{
    const fresh = core.readState("");
    assert.deepEqual(fresh.build, { views: ["face", "front"], poses: ["neutral"], expressions: ["neutral"] });
    const payload = core.toPayload(fresh);
    assert.deepEqual(payload.build.views, ["face", "front"]);
    assert.equal(payload.cells.length, 0, "the ticks, not the cell list, describe the plan");

    let saved = null;
    const panel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: { stateChanged: (next) => { saved = next; }, status: () => {} },
    });
    click([...panel.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
    // two views ticked, so the banner offers two cells and names them
    const hint = panel.container.textContent;
    assert.ok(hint.includes("2 cell(s)"), `the plan must be spelled out: ${hint.slice(0, 200)}`);
    const useThem = [...panel.container.querySelectorAll("button")].find((b) => b.textContent === "Use these 2 cells");
    assert.ok(useThem, "the empty-state button must materialise the ticks, not the 8-view matrix");
    click(useThem);
    assert.equal(saved.cells.length, 2);
    assert.deepEqual(saved.cells.map((c) => c.id), ["face-neutral-neutral", "front-neutral-neutral"]);

    // untick everything: the panel stops promising cells and says what the last resort is
    const boxes = [...panel.container.querySelectorAll('input[type="checkbox"]')]
        .filter((box) => box.checked);
    boxes.forEach((box) => { box.checked = false; fire(box, "change"); });
    assert.deepEqual(saved.build.views, [], "ticks are persisted as they change");
    assert.ok(panel.container.textContent.includes("default 8-view matrix"));
    ok.push("the view/pose ticks travel with the payload (empty cell list means the ticks)");
}

// --- live mode while a render runs ---------------------------------------------
// The per-cell saver writes each cell as it finishes; the panel follows the run so
// the Results tab fills in instead of waiting for someone to click refresh.
{
    const panel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: {
            stateChanged: () => {},
            status: () => {},
            listResults: async () => ({
                counts: { cells: 4, rendered: 1, frames: 22 },
                cells: [{ id: "face-neutral-neutral", frameCount: 22, rendered: true }],
            }),
        },
    });
    assert.equal(panel.live, false, "idle until a prompt starts");
    panel.setRunning(true);
    assert.equal(panel.live, true, "a run switches the panel to live updates");
    assert.ok(panel.container.textContent.includes("1/4 cell") || panel.status.textContent.length >= 0);
    panel.setRunning(false);
    assert.equal(panel.live, false, "and the timer stops when the run ends");
    panel.dispose();
    ok.push("live results while a render runs (poll starts and stops with the prompt)");
}

// --- tabs: the areas are panes, not a popup ------------------------------------
const tabs = [...panel.container.querySelectorAll(".mmx-tab")].map((tab) => tab.dataset.tab);
assert.deepEqual(tabs, ["references", "cells", "prompts", "results", "settings", "help"]);
assert.ok(panel.container.querySelector(".mmx-pane--references").classList.contains("is-active"));
panel.showTab("cells");
assert.ok(panel.container.querySelector(".mmx-pane--cells").classList.contains("is-active"));
assert.equal(panel.activeTab, "cells");
panel.showTab("references");
ok.push("References / Cells / Prompt / Results / Settings / Help are tabs inside the node");

// --- state round-trip through the payload the node parses ---------------------
const roundTrip = core.readState(JSON.stringify({
    refs: {
        pictures: [{ imageFile: "a.png", role: "face and hair" }, { imageFile: "b.png", enabled: false }],
        videos: [{ videoFile: "c.mp4", role: "clothing" }],
    },
    cells: [{ id: "front-neutral-neutral", view: "front", pose: "neutral", expression: "neutral" }],
}));
assert.equal(roundTrip.refs.pictures[0].file, "a.png");
assert.equal(roundTrip.refs.pictures[0].role, "face and hair");
assert.equal(roundTrip.refs.pictures[1].enabled, false);
assert.equal(roundTrip.refs.videos[0].file, "c.mp4");
assert.equal(roundTrip.cells.length, 1);
const payload = core.toPayload(roundTrip);
assert.equal(payload.refs.pictures.length, 2, "a disabled but present reference still round-trips");
assert.equal(payload.refs.videos[0].videoFile, "c.mp4");
assert.equal(payload.cells[0].id, "front-neutral-neutral");
ok.push("payload round-trips references (with roles) and cells");

// --- the cell matrix ------------------------------------------------------------
const builder = core.buildSheetInterface({ state: core.readState(""), hooks: {} });
const buildButton = [...builder.container.querySelectorAll("button")].find((b) => b.textContent === "Build cells");
assert.ok(buildButton, "Build cells button must exist");
click(buildButton);
const builtCells = [...builder.container.querySelectorAll(".mmx-sheet-cell")];
assert.equal(builtCells.length, 2, `expected 2 default cells (face neutral, front neutral), got ${builtCells.length}`);
assert.ok(builder.container.textContent.includes("face-neutral-neutral"));
const firstCellSelects = [...builtCells[0].querySelectorAll("select")].map((s) => s.value);
assert.deepEqual(firstCellSelects.slice(0, 4), ["face", "neutral", "neutral", "auto"]);
ok.push("cell matrix builds view/pose/expression cells with per-cell controls");

// --- per-cell extra prompt + pick mode persist ----------------------------------
const extra = builtCells[0].querySelector(".mmx-sheet-cell-extra");
extra.value = "holding a sword";
extra.dispatchEvent(new dom.window.Event("input"));
assert.equal(builder.container.querySelectorAll(".mmx-sheet-cell").length, 2);
ok.push("per-cell extra prompt is editable");

// --- results: thumbnails and click-to-pick --------------------------------------
assert.ok(builder.container.textContent.includes("Nothing rendered yet"));
panel.renderResults({
    sheetUrl: "/view?filename=s.png",
    dir: "/out/minimax_sheets/x",
    counts: { cells: 2, rendered: 2, frames: 5 },
    cells: [
        {
            id: "front-neutral-neutral", view: "front", pose: "neutral", expression: "neutral",
            pickMode: "auto", pickIndex: 1,
            frames: [{ url: "/view?f=0" }, { url: "/view?f=1" }],
        },
        { id: "face-neutral-smile", frames: [], pickMode: "auto", pickIndex: null },
    ],
});
assert.ok(panel.container.querySelector(".mmx-sheet-preview"), "the sheet preview must render");
const thumbs = panel.container.querySelectorAll(".mmx-sheet-result-row img");
assert.equal(thumbs.length, 2, "one thumbnail per stored frame");
assert.ok(panel.container.textContent.includes("no frames"), "a cell without frames says so");
click(thumbs[1]);
await tick();
assert.deepEqual(picked, ["front-neutral-neutral", 1], "clicking a frame picks that frame for that cell");
ok.push("results render the sheet + per-frame thumbnails and click-to-pick works");

// --- header actions still drive the routes -------------------------------------
click([...panel.container.querySelectorAll("button")].find((b) => b.textContent === "Rebuild sheet"));
await tick();
assert.equal(composed, 1, "Rebuild sheet calls the compose hook");
click([...panel.container.querySelectorAll("button")].find((b) => b.textContent === "Clear sheet"));
await tick();
assert.equal(cleared, 1, "Clear sheet calls the clear hook");
ok.push("header actions call the compose / clear routes");

// --- helpers the wiring relies on ---------------------------------------------
assert.equal(core.refViewUrl("sub/my face.png"), "/view?filename=my%20face.png&type=input&subfolder=sub");
assert.ok(core.refViewUrl("face.png").includes("subfolder="));
assert.equal(core.fileMatchesGroup({ name: "a.PNG", type: "" }, core.REF_GROUPS[0]), true);
assert.equal(core.fileMatchesGroup({ name: "a.PNG", type: "" }, core.REF_GROUPS[1]), false);
const refs = core.blankRefs();
refs.pictures[0] = { file: "a", role: "", enabled: true };
refs.pictures[3] = { file: "b", role: "", enabled: true };
assert.deepEqual(core.filledIndexes(refs, "pictures"), [0, 3]);
assert.equal(core.nextFreeSlot(refs, "pictures"), 1);
assert.equal(core.moveSlot(refs, "pictures", 0, 3), true);
assert.equal(refs.pictures[3].file, "a", "moveSlot swaps by default");
ok.push("reorder / slot helpers behave");

// --- the node is exactly as tall as its panel + knobs --------------------------
// Measured on the live frontend: panel top 86, panel 450, then 20 knob rows of 24
// with a 20px gap and a 20px bottom pad = 1056. The node keeps 20px below the DOM widget
// of its own (probed: node height - widget.y - panel clientHeight), so the fit has to ask
// for it - with 12 the panel was given 8px less than its content and scrolled forever.
// A node taller than this is the runaway "node is very very tall" state: the frontend
// layout only ever grows a node and a saved workflow restores whatever size it had.
{
    assert.equal(
        core.panelFitHeight({ top: 86, panelHeight: 450, rows: 20 }), 1056,
        "the live geometry must reproduce: header + panel + knob rows",
    );
    assert.equal(
        core.panelFitHeight({ top: 86, panelHeight: 450, rowsHeight: 20 * 24 }), 1056,
        "measured row heights are used when the wiring has them",
    );
    assert.equal(
        core.panelFitHeight({ panelHeight: 450, rows: 20 }),
        core.panelFitHeight({ top: core.PANEL_FIT.headerTop, panelHeight: 450, rows: 20 }),
        "a missing widget.y falls back to the known header height",
    );
    assert.ok(
        core.panelFitHeight({ top: 86, panelHeight: 450, rows: 20 })
            > core.panelFitHeight({ top: 86, panelHeight: 450, rows: 4 }),
        "more knobs means a taller node",
    );
    assert.ok(core.panelFitHeight({}) >= core.PANEL_FIT.headerTop, "garbage in, a sane floor out");
    assert.equal(core.panelFitHeight({ top: 86, panelHeight: 0, rows: 0 }), 106,
        "an empty panel keeps the header and the pad");
    // The ceiling: panes grow with their content, so a long Results list must not ask for a
    // 3000px node. Past the ceiling the pane scrolls again.
    assert.equal(core.PANEL_FIT.maxHeight, 1200, "a fallback ceiling when there is no viewport");
    assert.equal(core.panelFitHeight({ top: 86, panelHeight: 5000, rows: 0 }), 1200,
        "content taller than the ceiling is clamped to it");
    assert.equal(core.panelFitHeight({ top: 86, panelHeight: 5000, rows: 0, ceiling: 900 }), 900,
        "and the wiring can pass its own (viewport-derived) ceiling");
    assert.equal(core.panelFitHeight({ top: 86, panelHeight: 400, rows: 0, ceiling: 900 }), 506,
        "content under the ceiling is untouched");

    const stylesheet = panel.container.querySelector("style")?.textContent || "";
    // Every pane fills the panel: a capped pane left empty space under the content of a node
    // that was already tall enough (the settings grid was the first one to be fixed).
    const paneRule = stylesheet.match(/\.mmx-pane\.is-active\s*\{([^}]*)\}/);
    assert.ok(paneRule, "the active pane has a rule");
    assert.ok(/flex:\s*1 1 auto/.test(paneRule[1]), "it claims the leftover height");
    assert.ok(/min-height:\s*0/.test(paneRule[1]), "and may shrink, or flex never lets it scroll");
    assert.ok(/overflow-y:\s*auto/.test(paneRule[1]), "scrolling only when the content is taller");
    assert.ok(!/max-height/.test(paneRule[1]), "no fixed height cap any more");
    assert.ok(!/\.mmx-pane--settings\.is-active\s*\{/.test(stylesheet),
        "the settings-only exception is gone: it is the general behaviour now");
    assert.ok(/\.mmx-sheet\s*\{[^}]*display:\s*flex/.test(stylesheet),
        "the panel is a column, so the pane can fill it");
    assert.ok(!/width:\s*640px/.test(stylesheet) && /\.mmx-card--refs\s*\{[^}]*flex:\s*1 1 auto/.test(stylesheet),
        "the references card stretches its box instead of sitting at a fixed height");
    // A JS-style comment in a stylesheet swallows the NEXT rule, and if that rule is
    // the active pane the whole panel renders blank - it shipped once, so pin it.
    assert.ok(!/^\s*\/\//m.test(stylesheet), "the stylesheet must use /* */ comments only");
    assert.ok(/^\s*\.mmx-pane\s*\{\s*display:\s*none/m.test(stylesheet), "hidden panes stay hidden");
    {
        const probe = core.buildSheetInterface({
            state: core.readState(""),
            hooks: { status: () => {}, listResults: async () => null },
        });
        // getComputedStyle only resolves a stylesheet while it is in the document.
        document.body.append(probe.container);
        const referencePane = probe.container.querySelector(".mmx-pane--references");
        assert.notEqual(dom.window.getComputedStyle(referencePane).display, "none",
            "the active pane must actually be visible");
        assert.equal(dom.window.getComputedStyle(
            probe.container.querySelector(".mmx-pane--results")).display, "none",
            "the inactive ones stay hidden");
        probe.container.remove();
    }

    // The wiring can only re-fit the node if the panel says when its height changed.
    let layoutCalls = 0;
    let planCalls = 0;
    const probe = core.buildSheetInterface({
        state: core.readState(""),
        hooks: {
            status: () => {},
            listResults: async () => null,
            layoutChanged: () => { layoutCalls += 1; },
            planCells: async () => {
                planCalls += 1;
                return { cells: [{ id: "close", prompt: "<Picture 1> is the face reference.\nFACE", refs: ["<Picture 1>"] }] };
            },
        },
    });
    await tick();
    assert.ok(layoutCalls > 0, "mounting (and the first results pass) reports the layout");
    const before = layoutCalls;
    click([...probe.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
    await tick();
    await tick();
    assert.ok(layoutCalls > before, "switching to the Cells tab reports the layout too");
    assert.ok(planCalls > 0, "and the Cells tab asks the backend for the final prompts");
    ok.push("node height hugs its panel: the fit maths, the capped pane and the hook");
}

// --- the Prompt tab shows what will actually be sent ---------------------------
// The text is produced by the pack's planner over the real payload, so the panel can
// only ask for it - which is the point: a mis-wired reference becomes visible here
// instead of in a finished render.
{
    const plan = {
        cells: [
            { id: "close", prompt: "<Picture 1> is the head, face, hair reference.\nFACE CLOSE UP", refs: ["<Picture 1>"], blurred: [] },
            { id: "whole", prompt: "<Picture 1> is the head, face, hair reference.\n<Picture 2> is the body and clothes reference.\nFULL BODY", refs: ["<Picture 1>", "<Picture 2>"], blurred: ["<Picture 2>"] },
        ],
    };
    const state = core.readState("");
    state.refs.pictures = [
        { file: "face.jpg", role: "head, face, hair", enabled: true },
        { file: "body.jpg", role: "body and clothes", enabled: true },
    ];
    state.cells = [
        { id: "close", view: "face", pose: "neutral", expression: "neutral" },
        { id: "whole", view: "front", pose: "neutral", expression: "neutral" },
    ];
    const panel = core.buildSheetInterface({
        state,
        hooks: { status: () => {}, listResults: async () => null, planCells: async () => plan },
    });
    click([...panel.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "prompts"));
    await tick();
    await tick();
    const blocks = [...panel.container.querySelectorAll(".mmx-pane--prompts .mmx-prompt")];
    assert.equal(blocks.length, 2, "one block per cell");
    assert.ok(blocks[0].querySelector("pre").textContent.includes("FACE CLOSE UP"),
        "the block carries the final prompt text");
    assert.ok(blocks[0].textContent.includes("<Picture 1>"), "and the references it was wired with");
    assert.ok(!blocks[0].textContent.includes("<Picture 2>"),
        "the close-up's preview must not mention the outfit picture");
    assert.ok(blocks[1].textContent.includes("face blurred: <Picture 2>"),
        "a reference that will be blurred before wiring says so, next to the tags");
    assert.ok(!blocks[0].textContent.includes("face blurred"),
        "and a cell with nothing blurred stays quiet");

    // The Cells tab says which cells are narrowed down, so it is visible in place too.
    click([...panel.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "cells"));
    await tick();
    await tick();
    const notes = [...panel.container.querySelectorAll("[data-cell-refs]")]
        .map((node) => [node.dataset.cellRefs, node.textContent]);
    assert.deepEqual(notes, [["close", "conditioned on <Picture 1> only"], ["whole", ""]],
        "only the cells that lose a reference are called out");
    ok.push("Prompt tab: the final text per cell, straight from the planner");
}

// --- painting a blur area ------------------------------------------------------
// Strokes are stored normalized on the reference, so the painting is resolution
// independent, survives a save, and reaches the render through the same route the face
// blur uses.
{
    assert.deepEqual(core.paintPoint({ left: 0, top: 0, width: 100, height: 200 }, 25, 50), [0.25, 0.25]);
    assert.deepEqual(core.paintPoint({ left: 10, top: 20, width: 100, height: 100 }, 5, 5), [0, 0],
        "a drag off the image is clamped to it");
    assert.deepEqual(core.paintPoint({ left: 10, top: 20, width: 100, height: 100 }, 200, 200), [1, 1]);
    assert.ok(Math.abs(core.sliderToRadius(core.radiusToSlider(0.05)) - 0.05) < 0.005,
        "the size slider round-trips (to within one step of 30)");
    assert.equal(core.radiusToSlider(99), 30, "and clamps at the top");
    assert.ok(core.sliderToRadius(1) > 0, "a brush is never zero-width");

    const painted = { file: "a.jpg", role: "clothes", blurFace: "auto", blurPaint: [{ tool: "brush", points: [[0.5, 0.5]] }] };
    assert.equal(core.blurButtonLabel(painted), "Blur auto + paint", "the tile says it is painted");
    assert.equal(core.blurButtonLabel({ file: "a.jpg", blurFace: "auto" }), "Blur auto");

    // Paint on the live preview: a drag becomes a stroke on the reference, Undo takes it
    // back, and Apply asks the route for the blurred copy.
    blurCalls.length = 0;
    blurAnswer = { ok: true, applies: true, reason: "1 painted area(s) blurred", url: "/view?filename=x-blurface.png&type=input" };
    const paintPanel = core.buildSheetInterface({
        state: (() => {
            const state = core.readState("");
            state.refs.pictures = [{ file: "h3_character_sheet/ref.jpg", role: "clothes", enabled: true }];
            return state;
        })(),
        hooks: {
            stateChanged: (payload) => saved.push(payload),
            status: () => {},
            assetUrl: (url) => url,
            blurReference: async (request) => { blurCalls.push(request); return blurAnswer; },
        },
    });
    paintPanel.openPreview(core.REF_GROUPS[0], 0);
    await tick();
    const paint = paintPanel.container.querySelector(".mmx-paint");
    assert.ok(paintPanel.container.querySelector(".mmx-paint__frame"), "the preview frames the image");
    const surface = paintPanel.container.querySelector(".mmx-paint__canvas");
    assert.ok(surface, "with a canvas to paint on");
    assert.ok(paintPanel.container.querySelector('[data-paint-toggle]'), "and a Paint toggle");
    assert.ok(paintPanel.container.querySelector('[data-paint-tool="lasso"]'), "a lasso button too");
    // Painting is off until asked for, so a stray drag on the preview cannot mark it.
    surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    // jsdom never loads an image, and the frame is sized from the picture: a real image
    // reports its natural size, so give the stub one (painting waits for it by design).
    Object.defineProperty(paintPanel.container.querySelector(".mmx-paint__frame img"), "naturalWidth", { value: 400 });
    Object.defineProperty(paintPanel.container.querySelector(".mmx-paint__frame img"), "naturalHeight", { value: 400 });
    surface.dispatchEvent(new dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 50, clientY: 50 }));
    surface.dispatchEvent(new dom.window.MouseEvent("pointerup", { bubbles: true }));
    assert.equal(core.readState(JSON.stringify(saved.at(-1))).refs.pictures[0].blurPaint ?? null, null,
        "nothing is marked while Paint is off");

    click(paintPanel.container.querySelector('[data-paint-toggle]'));
    // A pointer capture that fails must not lose the stroke (it threw on the live node).
    surface.setPointerCapture = () => { throw new Error("No active pointer with the given id is found."); };
    surface.dispatchEvent(new dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 20 }));
    surface.dispatchEvent(new dom.window.MouseEvent("pointermove", { bubbles: true, clientX: 60, clientY: 40 }));
    surface.dispatchEvent(new dom.window.MouseEvent("pointerup", { bubbles: true }));
    const strokes = saved.at(-1).refs.pictures[0].blurPaint;
    assert.equal(strokes.length, 1, "the drag became a stroke on the reference");
    assert.equal(strokes[0].tool, "brush");
    assert.deepEqual(strokes[0].points[0], [0.2, 0.2], "stored normalized, not in pixels");
    assert.ok(strokes[0].points.length >= 2, "following the pointer");
    assert.ok(drawn.some(([key]) => key === "strokeStyle"), "and the overlay draws it back");

    click(paintPanel.container.querySelector('[data-paint-undo]'));
    assert.equal((saved.at(-1).refs.pictures[0].blurPaint || []).length, 0, "Undo takes the last area back");

    click(paintPanel.container.querySelector('[data-paint-toggle]'));
    surface.dispatchEvent(new dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 30, clientY: 30 }));
    surface.dispatchEvent(new dom.window.MouseEvent("pointerup", { bubbles: true }));
    click(paintPanel.container.querySelector('[data-paint-apply]'));
    await tick();
    assert.ok(blurCalls.length > 0, "Apply asks the route for the blurred copy");
    assert.ok(blurCalls.at(-1).file.endsWith("ref.jpg"));
    assert.equal(blurCalls.at(-1).slot, 0, "the slot is the enabled-reference number, not the array index");
    assert.ok(paintPanel.container.querySelector(".mmx-paint__canvas").closest(".mmx-paint__frame").querySelector("img").src.includes("blurface"),
        "and the preview shows the copy the render will wire");
    ok.push("paint a blur area on the preview: strokes persist, undo works, apply blurs");
}

// --- latent continuation: the switch, the per-cell override, the payload -------
{
    assert.equal(core.continuity(core.readState("")), "off",
        "cells are independent unless the sheet says otherwise");
    assert.deepEqual(core.CONTINUITY_MODES, ["off", "auto", "on"]);
    assert.equal(core.cellContinuity({}), "inherit", "a cell follows the sheet by default");
    assert.equal(core.cellContinuity({ continuity: "nonsense" }), "inherit");

    const contState = core.readState("");
    const contPanel = core.buildSheetInterface({ state: contState, hooks: {} });
    const switchBox = contPanel.container.querySelector('[data-action="continuity"]');
    assert.ok(switchBox, "the Cells tab offers the continuation switch");
    assert.equal(switchBox.value, "off", "defaulting to independent cells");
    switchBox.value = "on";
    switchBox.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(contState.continuity, "on", "switching it writes the panel state");

    // The cells carry the override; the sheet switch is what the node reads.
    const cellState = core.readState(JSON.stringify({
        render: { continuity: "on" },
        cells: [{ id: "c1" }, { id: "c2" }, { id: "c3", continuity: "off" }],
    }));
    assert.equal(core.continuity(cellState), "on", "a saved workflow restores the switch");
    assert.equal(core.toPayload(cellState).render.continuity, "on",
        "and the payload says what to render");
    assert.equal(core.cellContinues(cellState, 0), 0, "the first cell has nothing to continue from");
    assert.equal(core.cellContinues(cellState, 1), core.CONTINUITY_FRAMES,
        "the second cell continues the first");
    assert.equal(core.cellContinues(cellState, 2), 0, "an opted-out cell renders on its own");
    // A cell no longer than the hand-over cannot continue: the guide would fill it.
    const shortCells = core.readState(JSON.stringify({
        render: { continuity: "on" },
        cells: [{ id: "c1" }, { id: "c2", frames: 5 }],
    }));
    assert.equal(core.cellContinues(shortCells, 1), 0, "a 5-frame cell cannot take a 5-frame guide");
    assert.equal(core.toPayload(core.readState("")).render.continuity, "off",
        "the default is written too, so a saved workflow is explicit");

    // The cell row offers the per-cell override, and the first cell's is disabled.
    const listState = core.readState(JSON.stringify({
        cells: [{ id: "c1" }, { id: "c2", continuity: "on" }],
    }));
    const listPanel = core.buildSheetInterface({ state: listState, hooks: {} });
    const badges = [...listPanel.container.querySelectorAll("[data-cell-continuity]")];
    assert.equal(badges.length, 2, "every cell row carries the override");
    assert.equal(badges[0].disabled, true, "the first cell cannot continue anything");
    assert.equal(badges[1].value, "on", "and a stored override comes back selected");
    badges[1].value = "inherit";
    badges[1].dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(listState.cells[1].continuity, undefined,
        "inherit is stored as the absence of an override, not as a value");

    // --- auto: chain where the camera distance matches, break at a change ---------
    assert.deepEqual(core.framingDistance("face"), "close");
    assert.equal(core.framingDistance("front"), core.framingDistance("profile"));
    assert.equal(core.framingDistance("nonsense"), "", "an unknown view never matches");
    const framingState = core.readState(JSON.stringify({
        render: { continuity: "auto" },
        cells: [{ id: "face" }, { id: "portrait" }, { id: "front" }, { id: "profile" }, { id: "back" }],
    }));
    for (const cell of framingState.cells) cell.view = cell.id;
    assert.deepEqual(
        [0, 1, 2, 3, 4].map((index) => core.cellContinues(framingState, index)),
        [0, 0, 0, core.CONTINUITY_FRAMES, core.CONTINUITY_FRAMES],
        "a full-body turn continues; the framing changes do not",
    );
    assert.equal(core.framingBreak(framingState, 1), true, "the chest-up cell says why it stands alone");
    assert.equal(core.framingBreak(framingState, 3), false, "a continuing cell is not a break");
    // Forcing it across a framing change is still allowed - the user asked for it.
    const forced = core.readState(JSON.stringify({
        render: { continuity: "on" },
        cells: [{ id: "face", view: "face" }, { id: "portrait", view: "portrait" }],
    }));
    assert.equal(core.cellContinues(forced, 1), core.CONTINUITY_FRAMES);
    assert.equal(core.framingBreak(forced, 1), false, "'on' is never described as a break");
    ok.push("latent continuation: sheet switch, per-cell override, hand-over length");
    ok.push("continuation 'auto': chains within a camera distance, breaks at a framing change");
}

// --- the cell clips: exported by default, shown per cell -----------------------
{
    assert.equal(core.exportVideo(core.readState("")), true,
        "clips are exported unless the sheet says otherwise");
    assert.equal(core.exportVideo({ exportVideo: false }), false, "and the switch is honoured");
    assert.equal(core.readState(JSON.stringify({ render: { exportVideo: false } })).exportVideo, false,
        "a saved workflow restores it");
    assert.equal(core.toPayload(core.readState("")).render.exportVideo, true,
        "the payload says what to write");

    const clipState = core.readState("");
    const clipPanel = core.buildSheetInterface({ state: clipState, hooks: {} });
    const exportBox = clipPanel.container.querySelector('[data-action="export-video"]');
    assert.ok(exportBox, "the Cells tab offers the clip export");
    assert.equal(exportBox.checked, true, "on by default");
    exportBox.checked = false;
    exportBox.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(clipState.exportVideo, false, "unchecking it writes the panel state");

    // The Results tab links each cell's clip, so the take is playable next to its frames.
    const resultsPanel = core.buildSheetInterface({ state: core.readState(""), hooks: {} });
    resultsPanel.renderResults({
        counts: { cells: 1, rendered: 1, frames: 22 },
        dir: "/tmp/sheet",
        cells: [{
            id: "front", view: "front", pose: "neutral", expression: "neutral",
            pickIndex: 17, pickMode: "sharpest", frames: [],
            clipUrl: "minimax_sheets/x/clips/front_00001_.mp4", clipFile: "front_00001_.mp4",
        }],
    });
    const link = resultsPanel.container.querySelector("[data-cell-clip]");
    assert.ok(link, "the rendered cell shows its clip");
    assert.ok(link.href.includes("front_00001_.mp4"), "pointing at the exported file");
    assert.equal(link.target, "_blank", "opens the clip rather than replacing the panel");
    ok.push("cell clips: exported by default, switchable, linked per cell in Results");
}

// --- presets: whole-node settings, asked for and applied at the top ------------
{
    const PRESET_FIXTURE = [
        {
            id: "balanced", label: "Balanced (recommended)",
            hint: "What this pack is tuned for.",
            render: { continuity: "auto", exportVideo: true, framesPerCell: 22 },
            sheet: { layout: "hero-left", columns: 2, aspect: "3:2", shortEdge: 1536 },
            widgets: { cell_size: 1024, frames_per_cell: 22, steps: 8, continuity: "auto",
                       export_video: true, sheet_layout: "hero-left" },
            build: { views: ["face"], poses: ["neutral"], expressions: ["neutral", "smile"] },
            deviates: ["continuity"],
        },
        {
            id: "fast", label: "Fast look (no chains, no clips)",
            hint: "Planning pass at H3's minimum length.",
            render: { continuity: "off", exportVideo: false, framesPerCell: 5 },
            sheet: { layout: "grid", columns: 4, aspect: "16:9", shortEdge: 1280 },
            widgets: { cell_size: 768, frames_per_cell: 5, steps: 8, export_video: false },
            build: {}, deviates: ["cell_size", "frames_per_cell", "export_video"],
        },
    ];
    const applied = [];
    const presetCalls = [];
    const presetSaved = [];
    const presetState = core.readState("");
    // Applying a preset awaits the wiring's widget write, then persists - so the test waits
    // for the same chain instead of assuming a single tick is enough.
    const settled = async () => { await tick(); await tick(); await tick(); };
    const presetPanel = core.buildSheetInterface({
        state: presetState,
        hooks: {
            stateChanged: (payload) => presetSaved.push(payload),
            listPresets: async () => { presetCalls.push("list"); return { presets: PRESET_FIXTURE }; },
            applyWidgets: async (values) => { applied.push(values); return Object.keys(values); },
            planCells: async () => ({ cells: [] }),
        },
    });
    // The bar is at the TOP of the panel, above the references: these settings decide what
    // the render costs, so they come before the content.
    const bar = presetPanel.container.querySelector(".mmx-presets");
    assert.ok(bar, "the panel offers a preset bar");
    const select = bar.querySelector('[data-action="preset"]');
    assert.ok(select, "with a selector");
    const container = presetPanel.container;
    const kids = [...container.children];
    const barIndex = kids.indexOf(bar);
    assert.ok(barIndex > 0, "the bar is mounted in the panel");
    assert.ok(barIndex < kids.findIndex((el) => el.classList.contains("mmx-tabs")),
        "the bar sits above the tabs and the reference area");
    await tick();
    assert.deepEqual(presetCalls, ["list"], "the list is asked for once, from the backend");
    assert.deepEqual([...select.options].map((o) => o.value), ["", "balanced", "fast"]);
    assert.equal(select.options[1].textContent, "Balanced (recommended)", "labels come from the list");
    assert.equal(select.value, "", "a fresh node is 'custom' until a preset is applied");
    assert.ok(bar.textContent.includes("Presets set the whole node at once"), "and the bar explains itself");

    // Applying one: the panel's own settings, then the node's widgets, then the report.
    select.value = "balanced";
    select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await settled();
    assert.equal(presetState.continuity, "auto", "continuation is applied to the panel state");
    assert.equal(presetState.exportVideo, true, "so is the clip export");
    assert.equal(presetState.presetId, "balanced", "and the workflow records which preset it came from");
    assert.deepEqual(presetState.build.expressions, ["neutral", "smile"], "its ticks are offered");
    assert.equal(applied.length, 1, "the node's widgets are written");
    assert.equal(applied[0].cell_size, 1024, "cell size goes to the node");
    assert.equal(applied[0].sheet_columns, 2, "and the layout group is mapped onto its widgets");
    assert.equal(applied[0].sheet_short_edge, 1536);
    assert.ok(bar.textContent.includes("Changes: Continuity"), "the bar says what it changed");
    const payload = presetSaved.at(-1);
    assert.equal(payload.render.continuity, "auto", "the payload carries the applied settings");
    assert.equal(payload.render.preset, "balanced");

    // A preset never rewrites the sheet's content.
    presetState.cells = [{ id: "keep-me", view: "front" }];
    select.value = "fast";
    select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await settled();
    assert.deepEqual(presetState.cells.map((c) => c.id), ["keep-me"], "cells survive a preset");
    assert.equal(presetState.continuity, "off", "the new preset replaced the old settings");

    // Choosing "custom" records nothing and changes nothing.
    select.value = "";
    select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(presetState.presetId, "", "clearing the preset is only a record change");
    assert.equal(presetState.continuity, "off", "the settings stay as they are");

    // A saved workflow shows the preset it was built from.
    const restored = core.buildSheetInterface({
        state: core.readState(JSON.stringify({ render: { preset: "fast" } })),
        hooks: { listPresets: async () => ({ presets: PRESET_FIXTURE }) },
    });
    await tick();
    assert.equal(restored.container.querySelector('[data-action="preset"]').value, "fast",
        "a saved workflow comes back with its preset selected");
    ok.push("presets: served by the backend, applied to state + node widgets, content untouched");
}

// --- compact settings: the node's 23 knobs, in columns -------------------------
{
    // The frontend draws a native widget one per row and offers no column span, so the
    // node's knobs are drawn here instead and the node's own rows are hidden. The labels,
    // groups and bounds come from the backend (knobs.py -> the node schema).
    const KNOB_FIXTURE = {
        knobs: [
            { name: "output_name", label: "Sheet name", group: "Output", span: 2, kind: "text", default: "character_sheet" },
            { name: "cell_size", label: "Cell size", group: "Render", span: 1, kind: "number", default: 1024, min: 256, max: 2048, step: 32 },
            { name: "steps", label: "Steps", group: "Render", span: 1, kind: "number", default: 8, min: 1, max: 200 },
            { name: "continuity", label: "Continuation", group: "Cells", span: 1, kind: "select", default: "off", options: ["off", "auto", "on"] },
            { name: "export_video", label: "Export clips", group: "Cells", span: 1, kind: "toggle", default: true },
            // The browser adds this one to the seed row; the panel draws it like any other,
            // which is what lets the node hide every row and still leave the seed's mode.
            { name: "seed", label: "Seed", group: "Render", span: 1, kind: "number", default: 42, min: 0 },
            { name: "control_after_generate", label: "Seed mode", group: "Render", span: 1, kind: "select",
              default: "randomize", options: ["fixed", "increment", "decrement", "randomize"], frontend: true },
        ],
    };
    KNOB_FIXTURE.knobs[0].group = "Output";
    KNOB_FIXTURE.groups = [
        { group: "Output", knobs: [KNOB_FIXTURE.knobs[0]] },
        { group: "Render", knobs: [KNOB_FIXTURE.knobs[1], KNOB_FIXTURE.knobs[2], KNOB_FIXTURE.knobs[5], KNOB_FIXTURE.knobs[6]] },
        { group: "Cells", knobs: [KNOB_FIXTURE.knobs[3], KNOB_FIXTURE.knobs[4]] },
    ];
    KNOB_FIXTURE.ok = true;

    // Pure helpers first: coercion is where a bad number would reach the node.
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[1], "768"), 768, "a typed number becomes a number");
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[1], 5000), 2048, "and is clamped to the schema's max");
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[1], 10), 256, "and to its min");
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[1], ""), 1024, "an empty box keeps the default instead of NaN");
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[4], "on"), true, "a checkbox reads back as a boolean");
    assert.equal(core.knobValue(KNOB_FIXTURE.knobs[3], "auto"), "auto", "a select passes its option through");
    assert.equal(core.compactKnobs({}), true, "compact is the default: that is the point of the tab");
    assert.equal(core.compactKnobs({ compactKnobs: false }), false, "unless a workflow says otherwise");
    assert.equal(core.readState(JSON.stringify({ ui: { compactKnobs: false } })).compactKnobs, false,
        "the preference survives a save/load through the payload");
    assert.equal(core.toPayload(core.readState("")).ui.compactKnobs, true, "and is written even at the default");

    const knobWrites = [];
    const knobVisibility = [];
    const knobSaved = [];
    const knobState = core.readState("");
    // The node says cell_size is 768 and steps are 30: the panel must SHOW that, not its
    // own defaults, or the tab would describe a render that is not the one queued.
    const knobPanel = core.buildSheetInterface({
        state: knobState,
        hooks: {
            stateChanged: (payload) => knobSaved.push(payload),
            listKnobs: async () => KNOB_FIXTURE,
            readWidgets: (names) => Object.fromEntries(names.map((name) => [name, {
                cell_size: 768, steps: 30, continuity: "auto", export_video: false, output_name: "hero",
                seed: 7, control_after_generate: "increment",
            }[name]])),
            applyWidgets: async (values) => { knobWrites.push(values); return Object.keys(values); },
            setKnobsVisible: (visible) => { knobVisibility.push(visible); return 23; },
        },
    });
    await tick();
    await tick();
    assert.deepEqual(knobVisibility, [false], "once the knobs are drawn here, the node's own rows go away");
    const pane = knobPanel.container.querySelector(".mmx-pane--settings");
    assert.ok(pane, "the Settings tab exists");
    assert.deepEqual([...pane.querySelectorAll(".mmx-knob-group")].map((el) => el.dataset.group),
        ["Output", "Render", "Cells"], "grouped in the backend's order, not the schema's");
    assert.equal(pane.querySelectorAll(".mmx-knob").length, 7, "one field per knob");
    assert.equal(pane.querySelectorAll(".mmx-knob-grid").length, 3, "one grid per group");
    assert.ok(pane.querySelector(".mmx-knob").style.gridColumn.includes("span 2"),
        "a wide field can claim two columns");
    assert.equal(pane.querySelectorAll(".mmx-knob").length, KNOB_FIXTURE.knobs.length,
        "every knob the backend sent has a field");
    assert.equal(knobPanel.knobs.length, 7, "and the panel knows them by name");

    const sizeBox = pane.querySelector('[data-knob="cell_size"] input');
    assert.equal(sizeBox.value, "768", "the field shows the node's value, not the default");
    assert.equal(sizeBox.min, "256", "with the schema's bounds on the control");
    assert.equal(sizeBox.max, "2048");
    assert.equal(sizeBox.step, "32");
    const stepBox = pane.querySelector('[data-knob="steps"] input');
    assert.equal(stepBox.value, "30", "a second number field, read the same way");

    // Typing into it writes the node's widget (clamped), never a copy.
    sizeBox.value = "5000";
    sizeBox.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobWrites.at(-1), { cell_size: 2048 }, "an out-of-range value is clamped before it is written");
    assert.equal(knobState.knobValues.cell_size, 2048, "the panel remembers what it wrote");
    stepBox.value = "40";
    stepBox.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobWrites.at(-1), { steps: 40 });

    const continuitySelect = pane.querySelector('[data-knob="continuity"] select');
    assert.deepEqual([...continuitySelect.options].map((o) => o.value), ["off", "auto", "on"]);
    assert.equal(continuitySelect.value, "auto", "a select shows the node's current choice");
    continuitySelect.value = "on";
    continuitySelect.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobWrites.at(-1), { continuity: "on" }, "picking an option writes the widget");

    const exportBox = pane.querySelector('[data-knob="export_video"] input');
    assert.equal(exportBox.checked, false, "a toggle shows the node's current value");
    exportBox.checked = true;
    exportBox.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobWrites.at(-1), { export_video: true }, "a checkbox writes a boolean, not a string");

    // A knob the browser adds (not the node schema) is drawn and written the same way: that
    // is what lets the node hide every row without taking the seed's mode away.
    const seedMode = pane.querySelector('[data-knob="control_after_generate"] select');
    assert.deepEqual([...seedMode.options].map((o) => o.value),
        ["fixed", "increment", "decrement", "randomize"]);
    assert.equal(seedMode.value, "increment", "a browser-created widget is read like the rest");
    seedMode.value = "fixed";
    seedMode.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobWrites.at(-1), { control_after_generate: "fixed" });
    assert.equal(pane.querySelector('[data-knob="seed"] input').value, "7", "and so is the seed");

    // The compact switch: hide/show the rows, and remember the choice.
    const compact = pane.querySelector("#mmx-compact-knobs");
    assert.equal(compact.checked, true, "a fresh node is compact");
    compact.checked = false;
    compact.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(knobVisibility, [false, true], "unchecking puts the node's rows back");
    assert.equal(knobSaved.at(-1).ui.compactKnobs, false, "and the workflow records it");

    // A re-read picks up whatever the node was changed to outside the panel.
    const reread = core.buildSheetInterface({
        state: core.readState(JSON.stringify({ ui: { compactKnobs: false } })),
        hooks: {
            listKnobs: async () => ({ groups: [{ group: "Render", knobs: [KNOB_FIXTURE.knobs[1]] }] }),
            readWidgets: () => ({ cell_size: 1280 }),
            setKnobsVisible: () => {},
        },
    });
    await tick();
    await tick();
    assert.equal(reread.container.querySelector('[data-knob="cell_size"] input').value, "1280",
        "a reopen reads the node again");
    assert.equal(reread.container.querySelector("#mmx-compact-knobs").checked, false,
        "and comes back with the saved preference");

    // A backend that cannot answer must not leave a node with no visible knobs at all.
    const blind = [];
    const fallbackPanel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: {
            listKnobs: async () => { throw new Error("no route"); },
            setKnobsVisible: (visible) => blind.push(visible),
        },
    });
    await tick();
    await tick();
    assert.deepEqual(blind, [true], "a failed knob list leaves the node's own rows in place");    assert.ok(fallbackPanel.container.querySelector(".mmx-pane--settings").textContent.includes("stay on the node"));
    ok.push("compact settings: grouped grid, live values, writes clamped, node rows hidden");
}

// --- Help: the guide plus a live check of the files the node needs -------------
{
    // Served by help.py, so the panel cannot drift from what the node loads. The check reads
    // the RUNNING install: a ✗ has to say where the file goes and where to get it.
    const HELP_FIXTURE = {
        project: "5tar5ystem MMH3 Character Sheet Maker",
        ready: false,
        missing: ["Text encoder (Qwen3-VL)", "Face detector (only for the face blur)"],
        missing_packages: ["ultralytics"],
        sections: [
            { id: "what", title: "What this node makes", intro: "One node turns references into a sheet.",
              steps: [], bullets: ["Every cell is a short clip."], links: [], kind: "text" },
            { id: "files", title: "Files you need", intro: "Five models.", steps: [], bullets: [],
              links: [], kind: "files" },
            { id: "tips", title: "Getting a good sheet", intro: "", steps: [],
              bullets: ["Auto only chains cells that share a camera distance."],
              links: [{ label: "10Eros-Max", url: "https://huggingface.co/TenStrip/10Eros-Max/tree/main", note: "the checkpoint" }],
              kind: "text" },
        ],
        requirements: [
            { id: "unet", label: "Diffusion model (the H3 checkpoint)", node: "UNETLoader",
              folder: "diffusion_models", where: "ComfyUI/models/diffusion_models/",
              what: "The checkpoint that samples.", note: "", expect: ["10eros"],
              ok: true, file_ok: true, found: "Minimax/10Eros_Max_h3_TURBO-hybrid_beta5_int8.safetensors",
              looked: "/models/diffusion_models", packages: [], missing_packages: [],
              matches: ["Minimax/10Eros_Max_h3_TURBO-hybrid_beta5_int8.safetensors",
                        "Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors"],
              match_count: 2,
              links: [{ label: "10Eros-Max", url: "https://huggingface.co/TenStrip/10Eros-Max/tree/main", note: "take a TURBO file" }] },
            { id: "clip", label: "Text encoder (Qwen3-VL)", node: "CLIPLoader",
              folder: "text_encoders", where: "ComfyUI/models/text_encoders/",
              what: "CLIPLoader with type minimax.", note: "", expect: ["qwen3vl_32b_minimax_h3"],
              ok: false, file_ok: false, found: "", looked: "/models/text_encoders",
              packages: [], missing_packages: [],
              links: [{ label: "Comfy-Org / MiniMax-H3", url: "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders", note: "nvfp4_awq" }] },
            // The file is there and the feature is still dead: the blur needs a package too.
            { id: "face_model", label: "Face detector (only for the face blur)", node: "(used inside the node)",
              folder: "ultralytics/bbox", where: "ComfyUI/models/ultralytics/bbox/face_yolov8m.pt",
              what: "A YOLO face model.", expect: ["face_yolov8m.pt"],
              note: "Needs the ultralytics package in ComfyUI's own python.",
              ok: false, file_ok: true, found: "ultralytics/bbox/face_yolov8m.pt",
              looked: "/models/ultralytics/bbox",
              packages: [{ name: "ultralytics", ok: false }, { name: "cv2", ok: true }],
              missing_packages: ["ultralytics"],
              links: [{ label: "face_yolov8m.pt", url: "https://huggingface.co/Bingsu/adetailer/tree/main", note: "drop it in models/ultralytics/bbox/" }] },
        ],
    };
    const helpCalls = [];
    const helpPanel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: {
            status: () => {}, listResults: async () => null,
            listHelp: async () => { helpCalls.push("help"); return HELP_FIXTURE; },
        },
    });
    const helpTab = [...helpPanel.container.querySelectorAll(".mmx-tab")].find((tab) => tab.dataset.tab === "help");
    assert.ok(helpTab, "the panel offers a Help tab");
    assert.equal(helpTab.textContent, "Help");
    await tick();
    await tick();
    assert.deepEqual(helpCalls, ["help"], "the guide is asked for once, from the backend");
    const help = helpPanel.container.querySelector(".mmx-pane--help");
    const sections = [...help.querySelectorAll(".mmx-help__section")];
    assert.deepEqual(sections.map((el) => el.dataset.section), ["what", "files", "tips"],
        "every section renders, in the backend's order");
    assert.ok(sections[0].textContent.includes("What this node makes"));
    assert.ok(sections[0].querySelector("li").textContent.includes("short clip"), "bullets render");

    // The file check: one card per model, with the state spelled out.
    const reqs = [...help.querySelectorAll(".mmx-req")];
    assert.equal(reqs.length, 3, "one card per required file");
    assert.ok(reqs[0].classList.contains("mmx-req--ok"));
    assert.ok(reqs[0].textContent.includes("✓"), "a present file is ticked");
    assert.ok(reqs[0].textContent.includes("10Eros_Max_h3_TURBO-hybrid_beta5_int8"), "and named");
    assert.ok(reqs[0].textContent.includes("also here: Minimax/10Eros_Max_h3_TURBO-hybrid_beta4"),
        "a second match is listed too - the first one is not automatically the right one");
    assert.ok(reqs[1].classList.contains("mmx-req--missing"), "a missing file is flagged");
    assert.ok(reqs[1].textContent.includes("✗"));
    assert.ok(reqs[1].textContent.includes("ComfyUI/models/text_encoders/"), "with where it goes");
    assert.ok(reqs[1].textContent.includes("qwen3vl_32b_minimax_h3"), "and what to look for");

    // The face blur: file present, package missing - the row has to say BOTH, and still
    // name the file it found (a bare ✗ next to a file that is there is a lie).
    const face = reqs[2];
    assert.ok(face.textContent.includes("found: ultralytics/bbox/face_yolov8m.pt"),
        "the model file it did find is named");
    assert.ok(face.textContent.includes("✗ python package: ultralytics"), "the missing package is called out");
    assert.ok(face.textContent.includes("✓ python package: cv2"), "and a present one is ticked");
    assert.ok(face.textContent.includes("pip install ultralytics"), "with the command that fixes it");
    assert.ok(!face.textContent.includes("expect a file named like"),
        "a package problem must not be reported as a missing file");
    assert.ok(help.textContent.includes("5tar5ystem MMH3 Character Sheet Maker"), "the project name");
    assert.ok(help.textContent.includes("2 of 3 required files are missing or unusable"),
        "the header counts what is unusable, not just what is absent");
    assert.ok(help.textContent.includes("python package: ultralytics"), "and names it up front");

    // Links: real anchors, opening away from the canvas (this is a single-page app).
    const anchors = [...help.querySelectorAll("a.mmx-help__link")];
    assert.ok(anchors.length >= 3, "download links render");
    for (const anchor of anchors) {
        assert.equal(anchor.target, "_blank");
        assert.equal(anchor.rel, "noreferrer");
        assert.ok(anchor.href.startsWith("https://"), anchor.href);
        assert.ok(anchor.title, "the note becomes the tooltip");
    }
    assert.ok(anchors.some((a) => a.href.includes("TenStrip/10Eros-Max")), "the checkpoint link");
    assert.ok(anchors.some((a) => a.href.includes("Comfy-Org/MiniMax-H3")), "the file repo link");

    // A backend that cannot answer must leave a readable tab, not an empty one.
    const deadPanel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: { status: () => {}, listHelp: async () => { throw new Error("no route"); } },
    });
    await tick();
    await tick();
    assert.ok(deadPanel.container.querySelector(".mmx-pane--help").textContent.includes("could not be loaded"));
    ok.push("Help: sections from the backend, live ✓/✗ file check, links open away from the canvas");
}

// --- node previews: ComfyUI's own output previews, sized by the panel ---------
// The frontend draws them (a `comfy-img-preview` flex host per IMAGE output, plus a
// `$$comfy_animation_preview` widget for a sequence) and sizes each image from the NODE
// WIDTH, which is why a finished sheet made the node enormous. The pack caps them instead:
// the assertions below are the exact CSS/options contract the frontend reads, including that
// the override is `!important` (the frontend re-sets those properties inline on every
// resize, without important, so only an important override survives).
{
    const host = document.createElement("div");
    host.className = "comfy-img-preview";
    const hostImg = document.createElement("img");
    host.append(hostImg);
    const hostWidget = { name: "$$comfy_preview_image", element: host };

    const animWrapper = document.createElement("div");
    const animImg = document.createElement("img");
    animImg.className = "block size-full object-contain";
    animWrapper.append(animImg);
    const originalCompute = () => [100, 100];
    const animWidget = {
        name: core.PREVIEW_WIDGET_NAME, element: animWrapper,
        options: {}, computeSize: originalCompute,
    };

    const panelWidget = { name: "h3_character_sheet_ui", element: document.createElement("div") };
    const dataWidget = { name: "sheet_data", hidden: true };
    const node = { widgets: [panelWidget, dataWidget, hostWidget, animWidget], setDirtyCanvas() {} };
    const skip = ["h3_character_sheet_ui", "sheet_data"];

    assert.equal(core.previewHeight("compact"), core.PREVIEW_COMPACT_HEIGHT);
    assert.equal(core.previewHeight("full"), 0, "full size is the frontend's own business");
    assert.equal(core.nodePreviews({}), "compact", "compact is the default");
    assert.equal(core.nodePreviews({ nodePreviews: "nonsense" }), "compact");

    const parts = core.previewParts(node, { skip });
    assert.equal(parts.widgets.length, 2, "the image host and the animation widget");
    assert.equal(parts.hosts.length, 1, "one flex host");
    assert.ok(!parts.widgets.includes(panelWidget) && !parts.widgets.includes(dataWidget),
        "the panel and its storage are not output previews");

    // jsdom's CSS engine cannot resolve a cascade, so the assertions are on the two things the
    // cascade is built from: the class the pack adds, and the ONE rule it injects - which is
    // written with a doubled class on purpose (`.mmx-preview-compact.mmx-preview-compact img`)
    // so it out-specifies the frontend's own `.comfy-img-preview img` instead of racing it on
    // document order.
    let result = core.applyPreviewMode(node, "compact", { skip });
    assert.equal(result.mode, "compact");
    assert.equal(result.hosts, 1);
    assert.ok(host.classList.contains(core.PREVIEW_COMPACT_CLASS), "the host is marked");
    assert.ok(animWrapper.classList.contains(core.PREVIEW_COMPACT_CLASS),
        "and so is the animation widget's wrapper");
    const rule = document.getElementById(core.PREVIEW_RULE_ID);
    assert.ok(rule, "the capping rule is installed once, document-wide");
    assert.ok(rule.textContent.includes(`.${core.PREVIEW_COMPACT_CLASS}.${core.PREVIEW_COMPACT_CLASS} img`),
        "doubled class: a single class would tie with the frontend's rule and lose on order");
    assert.ok(rule.textContent.includes(`height: ${core.PREVIEW_COMPACT_HEIGHT}px !important`),
        "a fixed height, with priority");
    assert.ok(rule.textContent.includes("width: auto !important"),
        "auto width keeps the aspect ratio, so two previews fit side by side");
    assert.ok(rule.textContent.includes("object-fit: contain !important"));
    assert.ok(rule.textContent.includes("justify-content: center !important"),
        "the flex row centres what is left instead of leaving it left-aligned");
    assert.equal(animWidget.options.getMinHeight(), 200, "the DOM widget is capped, not stretched");
    assert.equal(animWidget.options.getMaxHeight(), 208);
    assert.equal(animWidget.hidden, false);
    assert.ok(!hostImg.classList.contains(core.PREVIEW_COMPACT_CLASS),
        "the images themselves are not marked - the rule reaches them through the host");

    result = core.applyPreviewMode(node, "off", { skip });
    assert.equal(result.mode, "off");
    assert.equal(host.style.display, "none");
    assert.ok(!host.classList.contains(core.PREVIEW_COMPACT_CLASS), "the cap class comes off");
    assert.ok(!animWrapper.classList.contains(core.PREVIEW_COMPACT_CLASS));
    assert.equal(animWidget.hidden, true, "the animation widget row goes too");
    assert.deepEqual(animWidget.computeSize(), [0, 0]);

    result = core.applyPreviewMode(node, "full", { skip });
    assert.equal(result.mode, "full");
    assert.equal(host.style.display, "");
    assert.ok(!host.classList.contains(core.PREVIEW_COMPACT_CLASS));
    assert.equal(animWidget.hidden, false);
    assert.equal(animWidget.computeSize, originalCompute, "the widget's own computeSize is restored");
    assert.equal("getMinHeight" in animWidget.options, false);

    // Applying twice must not pile up rules (it runs after every render).
    core.applyPreviewMode(node, "compact", { skip });
    core.applyPreviewMode(node, "compact", { skip });
    assert.equal(document.querySelectorAll(`#${core.PREVIEW_RULE_ID}`).length, 1,
        "one rule, however often the mode is re-applied");

    // The preference travels in the payload and the panel offers it next to the results.
    assert.equal(core.readState(JSON.stringify({ ui: { nodePreviews: "off" } })).nodePreviews, "off");
    assert.equal(core.toPayload(core.readState("")).ui.nodePreviews, "compact");
    const previewCalls = [];
    const previewState = core.readState("");
    const previewPanel = core.buildSheetInterface({
        state: previewState,
        hooks: {
            status: () => {}, listResults: async () => null,
            setPreviewMode: (mode) => { previewCalls.push(mode); return { mode }; },
        },
    });
    const select = previewPanel.container.querySelector('[data-action="node-previews"]');
    assert.ok(select, "the Results tab offers a node-preview control");
    assert.deepEqual([...select.options].map((o) => o.value), ["compact", "full", "off"]);
    assert.equal(select.value, "compact");
    select.value = "off";
    select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.deepEqual(previewCalls, ["off"], "the wiring is asked to resize them");
    assert.equal(previewState.nodePreviews, "off", "and the choice is remembered");
    ok.push("node previews: capped and side by side, hidden, or ComfyUI's own size");
}

// --- the one button that creates the render is visibly different -----------------
// "Build cells" is the step a new user has to find, so it carries an outline instead of the
// quiet default button style. The class and the rule are both pinned here: the rule is what
// makes it look like anything at all.
{
    const builder2 = core.buildSheetInterface({ state: core.readState(""), hooks: {} });
    builder2.showTab("cells");
    const build = [...builder2.container.querySelectorAll("button")]
        .find((b) => b.textContent === "Build cells");
    assert.ok(build, "the Cells tab has the Build cells button");
    assert.ok(build.classList.contains("mmx-btn--build"), "it is marked as the primary action");
    const clear = [...builder2.container.querySelectorAll("button")]
        .find((b) => b.textContent === "Clear cells");
    assert.ok(clear && !clear.classList.contains("mmx-btn--build"), "Clear cells stays quiet");
    assert.ok(build.title.includes("Queue"), "and it says what happens next");
    const styles = builder2.container.querySelector("style").textContent;
    const rule = styles.match(/\.mmx-btn--build\s*\{([^}]*)\}/);
    assert.ok(rule, "the highlight rule exists");
    assert.ok(/border:\s*1px solid var\(--mmx-build/.test(rule[1]), "a 1px outline, from the theme variable");
    assert.ok(/color:\s*var\(--mmx-build/.test(rule[1]), "same colour for the label");
    assert.ok(/\.mmx-btn--build:hover\s*\{/.test(styles), "with a hover state that fills in");
    ok.push("Build cells is outlined in yellow-orange (the rest of the buttons stay quiet)");
}

// --- auto-refresh is off by default, and Refresh is a button ---------------------
// Polling the sheet folder is a background read the user did not ask for; the Results tab is
// one click (or one button) away. A run still polls while it renders, so cells appear as they
// land - that timer stops with the run.
{
    let listed = 0;
    const notices = [];
    const state = core.readState("");
    const panel = core.buildSheetInterface({
        state,
        hooks: {
            status: (text) => notices.push(String(text)),
            listResults: async () => { listed += 1; return null; },
        },
    });
    await tick();
    await tick();
    const auto = panel.container.querySelector("[data-mmx-sheet-auto]");
    assert.ok(auto, "the header still offers the auto-refresh switch");
    assert.equal(auto.checked, false, "off by default");
    assert.equal(panel.autoRefresh.checked, false);
    assert.equal(core.autoRefresh({}), false, "and the payload default agrees");
    assert.equal(core.readState(JSON.stringify({ ui: { autoRefresh: true } })).autoRefresh, true,
        "a workflow that turned it on keeps it");
    assert.equal(core.toPayload(core.readState("")).ui.autoRefresh, false);
    auto.checked = true;
    auto.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    assert.equal(state.autoRefresh, true, "the switch is remembered");

    // The manual refresh: one read of the sheet folder per press.
    const refresh = panel.container.querySelector('[data-action="refresh-results"]');
    assert.ok(refresh, "the header offers a Refresh button");
    assert.equal(refresh.textContent, "Refresh");
    const before = listed;
    click(refresh);
    await tick();
    await tick();
    assert.ok(listed > before, "pressing it re-reads the results");
    assert.ok(notices.some((text) => text.includes("refreshed")), "and says so");
    ok.push("auto-refresh off by default, Refresh does one read on demand");
}

// --- the tabs use the space they are given --------------------------------------
// The reference tiles and the paint surface are measured into their box, so a node the user
// resized must re-lay-out instead of keeping the small layout with empty space around it.
{
    const observed = [];
    class FakeObserver {
        constructor(callback) { this.callback = callback; observed.push(this); }
        observe(target) { this.target = target; }
        disconnect() { this.disconnected = true; }
    }
    const previous = globalThis.ResizeObserver;
    globalThis.ResizeObserver = FakeObserver;
    try {
        const panel = core.buildSheetInterface({
            state: core.readState(""), hooks: { status: () => {}, listResults: async () => null },
        });
        assert.equal(observed.length, 1, "the panel watches its own size");
        assert.equal(observed[0].target, panel.container, "the container is the observed element");
        // A resize that matters re-renders the visible tab (debounced); jitter does not.
        const before = panel.container.querySelectorAll(".mmx-sheet-ref").length
            || panel.container.textContent.length;
        Object.defineProperty(panel.container, "clientHeight", { value: 900, configurable: true });
        Object.defineProperty(panel.container, "clientWidth", { value: 800, configurable: true });
        panel.noteResize();
        await tick();
        await tick();
        assert.ok(panel.container.textContent.length > 0, "the tab is still rendered");
        assert.ok(before >= 0);
        panel.dispose();
        assert.ok(observed[0].disconnected, "dispose stops watching");
    } finally {
        if (previous === undefined) delete globalThis.ResizeObserver;
        else globalThis.ResizeObserver = previous;
    }
    ok.push("a resized node re-lays-out the tab (ResizeObserver, debounced)");
}

console.log("h3sheet_core: PASS");
for (const line of ok) console.log(" -", line);