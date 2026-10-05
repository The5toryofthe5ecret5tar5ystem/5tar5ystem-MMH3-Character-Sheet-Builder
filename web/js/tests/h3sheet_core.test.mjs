// Character Sheet Builder panel (jsdom): the interface a user actually sees.
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
{
    // The floor is a stylesheet rule, not an inline style, so the two-column studio can raise it
    // in its own column (an inline style would win against that). Still a FLOOR either way.
    const boxRule = /\.mmx-refbox \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(boxRule && boxRule[1].includes(`min-height: ${core.REF_SECTION.height}px`),
        "the box's height is a FLOOR: it grows with the pane so a taller node shows bigger tiles");
    assert.ok(/\.mmx-card--refs-col > \.mmx-refbox \{[^}]*min-height:\s*300px/.test(core.PANEL_CSS),
        "and the control column's tile list raises it, because a narrow column of tiles needs height");
}
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

// --- removal is a per-tile decision, on pictures, clips AND sounds -------------
// auto -> on -> off in one click, because the useful question ("is this reference the
// identity or is it an outfit?") is answered by the roles, and the rare override should
// not need a menu. A clip is blurred frame by frame; a SOUND cannot be blurred at all, so
// it is muted instead - and the badge says "mute", not "blur", because that is what happens.
const blurChips = () => [...panel.container.querySelectorAll(".mmx-refbox .mmx-tile__badges [data-blur]")];
assert.equal(blurChips().length, 3, "picture, clip and sound tiles all carry the badge");
assert.deepEqual(blurChips().map((chip) => chip.dataset.blur), ["auto", "auto", "auto"],
    "and all three start on auto");
assert.equal(blurChips()[0].textContent, "blur auto", "and it starts on auto");
assert.ok(blurChips()[0].classList.contains("mmx-badge--auto"), "styled by its mode");
assert.ok(blurChips()[0].title.includes("unless it is the identity reference"),
    "with the sentence that says what auto means");
// The badge is the control: click to cycle, exactly as the old text button did.
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "blur on", "one click turns it on");
assert.equal(saved.at(-1).refs.pictures[0].blurFace, "on", "and the choice persists into the payload");
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "blur off", "the next click turns it off");
click(blurChips()[0]);
assert.equal(blurChips()[0].textContent, "blur auto", "and the cycle wraps back to auto");
assert.equal(saved.at(-1).refs.pictures[0].blurFace, "auto", "round-tripped, not lost");
// The sound tile wears the same badge with the honest word on it, and its decision rides
// the payload like the others.
assert.equal(blurChips()[2].textContent, "mute auto", "a sound is muted, not blurred");
assert.ok(blurChips()[2].title.includes("only muted when you say so"),
    "with the sentence that says what auto means for a voice (kept, unless you say otherwise)");
click(blurChips()[2]);
assert.equal(blurChips()[2].textContent, "mute on", "one click mutes it");
assert.equal(saved.at(-1).refs.audios[0].blurFace, "on", "and the choice reaches the payload");
assert.ok(!saved.at(-1).refs.audios[0].blurPaint,
    "a sound never carries a painting: there are no pixels to paint on");
click(blurChips()[2]);
assert.equal(blurChips()[2].textContent, "mute off", "the next click keeps the voice");
click(blurChips()[2]);
assert.equal(blurChips()[2].textContent, "mute auto", "and the cycle wraps back to auto");
assert.equal(saved.at(-1).refs.audios[0].blurFace, "auto", "round-tripped, not lost");

// A clip is a blur target like any other, so the honest warning that used to live here
// ("picture references only") is gone - and the clip keeps its filename badge beside it.
const videoBadges = [...panel.container.querySelectorAll(".mmx-refbox .mmx-badge--warn")];
assert.deepEqual(videoBadges, [], "no clip is badged as un-blurrable any more");
// (The chips are re-queried after every click: persisting re-renders the tiles, so the
// element the click landed on is gone by the time the state is asserted.)
click(blurChips()[1]);
assert.equal(blurChips()[1].textContent, "blur on", "a clip cycles exactly like a picture");
assert.equal(saved.at(-1).refs.videos[0].blurFace, "on", "and the choice reaches the payload");
click(blurChips()[1]);
assert.equal(blurChips()[1].textContent, "blur off", "the next click turns it off");
click(blurChips()[1]);
assert.equal(blurChips()[1].textContent, "blur auto", "back at auto after the full cycle");
assert.equal(saved.at(-1).refs.videos[0].blurFace, "auto", "round-tripped, not lost");
assert.ok(panel.container.querySelector(".mmx-refbox .mmx-tile__badge-name"),
    "the clip still shows its filename");
// Painted areas are a badge too: it is the object-removal feature and it should be visible
// without opening anything.
const paintedSlot = core.readState(JSON.stringify({
    refs: { pictures: [{ file: "outfit.png", role: "clothing",
        blurPaint: [{ x: 0.2, y: 0.3, radius: 0.03 }, { x: 0.6, y: 0.5, radius: 0.03 }] }] },
}));
const paintPanel = core.buildSheetInterface({ state: paintedSlot, hooks: {} });
const painted = [...paintPanel.container.querySelectorAll(".mmx-badge--paint")];
assert.equal(painted.length, 1, "a painted reference gets a painted badge");
assert.equal(painted[0].textContent, "2 painted", "with the count");
ok.push("per-tile face blur: auto -> on -> off, pictures and clips");

// --- the footer: proposal B's pinned action bar -------------------------------
// The primary action is pinned at the bottom of the PANEL - not of a column - because the five
// tabs that own no column still have to be able to press it (see the tab-scoped column below).
// The sheet's own buttons (rebuild, refresh) ride in the status bar it acts on. "Render" queues
// through ComfyUI (the wiring's `queue` hook) - it is not a second renderer.
{
    const bar = panel.container.querySelector(".mmx-actionbar");
    assert.ok(bar, "the panel has a status bar");
    assert.equal(bar.lastElementChild.dataset.action, "refresh-results",
        "the status bar's own buttons end with Refresh");
    assert.ok(bar.querySelector(".mmx-status"), "the status line lives in the bar, not on its own");
    assert.ok(!panel.container.querySelector(":scope > .mmx-status"),
        "…and not twice: the bar is the only status row");
    const foot = panel.container.querySelector(":scope > .mmx-col__foot");
    assert.ok(foot, "Render is pinned in the PANEL's footer, not inside the column");
    assert.ok(!foot.closest(".mmx-col"), "so a tab without a column still has a Render button");
    assert.equal(foot.lastElementChild.dataset.action, "render", "with Render as its last button");
    assert.ok(foot.lastElementChild.classList.contains("mmx-btn--primary"), "and it is the primary one");
    // Anchored at the start of a line: the panel-foot override (`.mmx-foot .mmx-actionbar`) would
    // otherwise match first and it is deliberately static, being already at the bottom.
    const barRule = /\n\.mmx-actionbar \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(barRule && /position:\s*sticky/.test(barRule[1]) && /bottom:\s*0/.test(barRule[1]),
        "the status bar is pinned to the bottom while the pane scrolls");
    assert.ok(/\.mmx-foot \.mmx-actionbar \{[^}]*position:\s*static/.test(core.PANEL_CSS),
        "and in the panel foot it is a normal row, because that IS the bottom");
    // A button that cannot queue says so instead of throwing: the harness has no ComfyUI.
    assert.ok(foot.lastElementChild.disabled, "no queue hook means a disabled button");
    assert.match(foot.lastElementChild.title, /ComfyUI/);
    const queued = [];
    const withQueue = core.buildSheetInterface({
        state: core.readState(""),
        hooks: { status: () => {}, queue: async () => { queued.push("q"); } },
    });
    const live = withQueue.container.querySelector('[data-action="render"]');
    assert.ok(!live.disabled, "with a queue hook it is pressable");
    live.click();
    await tick();
    assert.deepEqual(queued, ["q"], "and pressing it asks the wiring to queue");
    ok.push("footer bar: pinned Render as the primary action, disabled without a queue");
}

// --- phase 2: the preset cards wear your own last render of each layout --------
{
    const galleryCalls = [];
    // A self-contained fixture, not the shared one: this block is about two cards, one of which
    // has a render on disk and one of which does not.
    const artPresets = [
        { id: "hero-4", kind: "layout", label: "Hero + 4 panels", cells: [
            { id: "hero", view: "front" }, { id: "f", view: "face" }] },
        { id: "expressions-6", kind: "layout", label: "Expressions 2x3", cells: [
            { id: "a", view: "face" }] },
        { id: "one-pass", kind: "quality", label: "One-pass sheet", render: { singlePass: true } },
    ];
    const withArt = core.buildSheetInterface({
        state: core.readState(""),
        hooks: {
            status: () => {},
            listPresets: async () => ({ presets: artPresets, resolutions: [] }),
            applyWidgets: async (values) => Object.keys(values),
            listGallery: async () => {
                galleryCalls.push("gallery");
                return {
                    layouts: {
                        "hero-4": { url: "/view?filename=hero.png&type=output", name: "hero run" },
                        "refmod-suite": { url: "/view?filename=suite.png&type=output", name: "suite run" },
                    },
                };
            },
        },
    });
    // Three ticks: presets, then the gallery, then the rails re-rendered with the art.
    await tick();
    await tick();
    await tick();
    assert.deepEqual(galleryCalls, ["gallery"], "the gallery is asked for once");
    // The Sheets rail is the Sheets column's content: it is on the tab that decides the sheet.
    withArt.showTab("cells");
    const layoutRail = withArt.container.querySelector('[data-action="layout-preset"]');
    // OFF by default: the drawing is the card's answer to "which sheet, and how many cells", and a
    // photo of the last render replaces exactly that - so a rendered layout keeps its drawn cells
    // until the user asks for the render.
    const hero = layoutRail.querySelector('[data-preset-id="hero-4"]');
    assert.ok(!hero.classList.contains("has-art"), "layout cards keep the drawn arrangement");
    assert.equal(hero.style.getPropertyValue("--mmx-card-art"), "",
        "even for a layout that HAS a render on disk");
    assert.equal(hero.querySelector(".mmx-pcard__live"), null, "and no badge claiming otherwise");
    // The switch in the Sheets head puts them back on, and the rails are rebuilt with the art.
    const cardArtSwitch = withArt.container.querySelector("#mmx-card-art");
    assert.ok(cardArtSwitch, "the Sheets head has the 'your renders' switch");
    cardArtSwitch.checked = true;
    cardArtSwitch.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await tick();
    const rail = withArt.container.querySelector('[data-action="layout-preset"]');
    const withRender = rail.querySelector('[data-preset-id="hero-4"]');
    assert.ok(withRender.classList.contains("has-art"),
        "switched on, a layout you have rendered wears your own render");
    assert.match(withRender.style.getPropertyValue("--mmx-card-art"), /hero\.png/,
        "the art is the sheet the backend reported");
    assert.equal(withRender.querySelector(".mmx-pcard__live").title.includes("hero run"), true,
        "and the card says which render it came from");
    // No render yet: the card keeps the drawn arrangement and claims nothing.
    const faces = rail.querySelector('[data-preset-id="expressions-6"]');
    assert.ok(faces && !faces.classList.contains("has-art"),
        "a layout you have never rendered keeps the drawn arrangement");
    assert.equal(faces.querySelector(".mmx-pcard__live"), null, "and no badge claiming otherwise");
    // A panel that cannot ask (an older backend) is fine: no art, no broken background.
    assert.ok(!panel.container.querySelector(".mmx-pcard.has-art"),
        "no gallery answer, no art - never a broken background");
    ok.push("card art: your own last render per layout, wireframe only as the fallback");
}

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

    // The picture's bottom-left corner is its BADGE ROW: the blur state (the badge is the
    // control) and how many areas were painted out. Short words you can read without hovering,
    // tooltips for the rest. A clip carries the same blur badge - and its filename, because
    // which clip this is matters more at a glance than its blur state does.
    const badges = box.querySelector(".mmx-tile__badges");
    assert.ok(badges, "the picture carries a badge row");
    assert.ok(badges.querySelector("[data-blur]"), "with its blur state on the tile");
    assert.ok(!box.querySelector(".mmx-tile__name"), "replacing the filename there, not adding to it");
    assert.ok(gridTiles()[1].querySelector(".mmx-tile__badges .mmx-tile__badge-name"),
        "a clip keeps its filename in that row");
    assert.ok(gridTiles()[1].querySelector(".mmx-tile__badges .mmx-badge--blur[data-blur]"),
        "beside the blur badge, which a clip has just like a picture");
    // The audio tile has no thumbnail, so it shows the kind icon - and its filename in ONE
    // place (the caption), which used to be repeated inside the placeholder. It also carries
    // the mute badge: the badge row is the tile's own, and a sound has a decision too.
    const audioTile = gridTiles()[2];
    assert.ok(audioTile.querySelector(".mmx-tile__note svg"), "the audio tile draws the kind icon");
    assert.equal(audioTile.querySelectorAll(".mmx-tile__badges [data-blur]").length, 1,
        "the sound tile carries its mute badge");
    assert.equal(audioTile.querySelector(".mmx-tile__badges [data-blur]").textContent, "mute auto");
    // Its filename moves into the badge row, which is now the row it has: a tile with badges
    // does not get the caption as well, and the name has to be somewhere on the tile.
    assert.equal(audioTile.querySelectorAll(".mmx-tile__badges .mmx-tile__badge-name").length, 1,
        "the sound keeps its filename in the badge row");
    assert.equal(audioTile.querySelectorAll(".mmx-tile__name").length, 0);
    assert.ok(!audioTile.querySelector(".mmx-tile__note span"),
        "and does not say the filename twice");
    const rule = /\.mmx-tile__badges \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(rule && /bottom:\s*3px/.test(rule[1]) && /left:\s*3px/.test(rule[1]),
        "pinned to the bottom-left corner on purpose");

    // The row under the tile belongs to the role box alone: it is the only thing here that
    // gets typed into, and a button beside it left no room to type.
    const wrap = gridWraps()[0];
    const siblings = [...wrap.children].filter((el) => el !== box);
    assert.equal(siblings.length, 1, "the row under the tile holds exactly one thing");
    assert.ok(siblings[0].classList.contains("mmx-sheet-ref-role"), "the role box, with the full width");
    ok.push("tile controls: quiet top row, blur/painted badges on the picture's bottom-left, "
        + "role box full width");
}

// --- the canvas: the reference you are working on, tools ON the picture -------
// Clicking a tile loads it into the pane at the top of the tab instead of opening the picker,
// because that is where a reference is worked on (blur it, paint an area out, compare it with
// what the render receives). "Replace..." on the pane's head is where the file is changed.
{
    const canvas = () => panel.container.querySelector('[data-action="ref-canvas"]');
    assert.ok(canvas(), "the References tab carries a canvas");
    assert.ok(!canvas().querySelector(".mmx-canvas__empty"),
        "with a reference in it by default (the first picture)");
    assert.ok(canvas().querySelector("img")?.src.includes("face.png"),
        "showing that picture");
    // The tools live ON the picture: the paint surface and the before/after bar are the same
    // builders the Preview overlay uses, mounted inline here.
    assert.ok(canvas().querySelector(".mmx-paint__frame"), "the canvas mounts the paint surface");
    assert.ok(canvas().querySelector(".mmx-paint__canvas"), "with its own canvas over the picture");
    assert.ok(canvas().querySelector(".mmx-preview__blurbar"), "and the original/blurred comparison bar");
    assert.ok(gridWraps()[0].classList.contains("is-canvas"),
        "the tile whose reference is loaded says so");

    // Loading another reference is one click, and the canvas follows it.
    blurCalls.length = 0;
    click(gridTiles()[1]);
    assert.ok(canvas().querySelector("video"), "a video loads its own player into the canvas");
    // A clip is worked on like a picture: the same paint surface over the frame it is showing
    // (the engine holds the painting across every frame), the same before/after bar - and the
    // preview has to ask for the CLIP pass, which is a different job from one still.
    assert.ok(canvas().querySelector(".mmx-paint__frame"),
        "the clip gets the same paint surface a picture gets");
    assert.ok(canvas().querySelector(".mmx-preview__blurbar"), "and the same original/blurred bar");
    await tick();
    assert.equal(blurCalls.at(-1)?.kind, "video",
        "and the preview names the clip pass rather than guessing from the slot");
    assert.ok(gridWraps()[1].classList.contains("is-canvas"), "and the ring moves with it");
    assert.ok(!gridWraps()[0].classList.contains("is-canvas"), "off the previous tile");
    assert.ok(saved.length > 0, "selecting is a panel-state change, not a payload one");

    // Selecting must not have touched the payload's references.
    click(gridTiles()[0]);
    assert.ok(canvas().querySelector("img")?.src.includes("face.png"), "clicking back loads the picture");
    assert.equal(saved.at(-1).refs.pictures[0].imageFile, "h3_character_sheet/face.png",
        "and the payload still says what it said");

    // Replace... opens the picker for the loaded slot (the job the tile click used to do).
    const replace = canvas().querySelector('[data-action="ref-replace"]');
    assert.ok(replace, "the canvas offers Replace");
    click(replace);
    await tick();
    assert.ok(panel.container.querySelector(".mmx-browse, .mmx-overlay"),
        "and it opens the media picker");

    // An empty grid says what the canvas is for instead of rendering a blank box.
    const empty = core.buildSheetInterface({ state: core.readState(""), hooks: {} });
    empty.showTab("references");
    const emptyCanvas = empty.container.querySelector('[data-action="ref-canvas"]');
    assert.ok(emptyCanvas.querySelector(".mmx-canvas__empty"), "an empty canvas explains itself");
    assert.match(emptyCanvas.textContent, /Add a reference/);
    ok.push("references canvas: a tile click loads it into the pane, tools on the picture, "
        + "Replace on the head");
}

// --- the panel's own prose is short on screen and long on hover ---------------
// After the card rails, the glyph ticks and the badges, these paragraphs were the last text-heavy
// thing in the panel. The information is worth keeping; the wall of words is not - so every one of
// them draws its short form and keeps the whole sentence in the tooltip.
{
    const long = (node) => (node?.textContent || "").length;
    // Found by its text, not by its pane: the hint sits under the reference LIST in the control
    // column now (the frame is rail | stage | column), not in the pane.
    const footer = [...panel.container.querySelectorAll(".mmx-muted")]
        .find((node) => node.textContent.startsWith("Drop files anywhere"));
    assert.ok(footer, "the reference box has a one-line hint");
    assert.ok(long(footer) < 120, `the line on screen stays short (got ${long(footer)} chars)`);
    assert.ok((footer.title || "").length > long(footer),
        "and the full sentence is one hover away");

    const roles = [...panel.container.querySelectorAll(".mmx-card .mmx-muted")]
        .find((node) => node.textContent.startsWith("Name the attribute"));
    assert.ok(roles, "the prompt card says what a role does in one line");
    assert.ok(long(roles) < 130, "short on screen");
    assert.ok((roles.title || "").includes("not from the others"), "the rest is the tooltip");

    // The tick plan keeps its count on screen and its list on hover (twenty cell ids is a
    // paragraph, and the cells are drawn as glyphs right above it).
    const note = [...panel.container.querySelectorAll(".mmx-pane--cells .mmx-muted")]
        .find((node) => node.textContent.includes("cell(s) from the ticks"));
    assert.ok(note, "the tick plan reports a count");
    assert.ok(!note.textContent.includes("-"), "without listing every id");
    assert.ok((note.title || "").includes("-"), "the ids are in the tooltip");
    ok.push("panel prose: guidance lines are short on screen and long on hover");
}

// --- the blur area is one setting for the sheet -------------------------------
// B' draws it as chips UNDER the picture, not as a dropdown in the list's header: it is a setting
// about the picture on screen, so it belongs next to that picture.
const blurRow = panel.container.querySelector('[data-action="blur-scope"]');
assert.ok(blurRow, "the stage offers a blur area under the picture");
assert.ok(blurRow.classList.contains("mmx-chiprow"), "drawn as chips, not a dropdown");
const blurAreaChips = [...blurRow.querySelectorAll("[data-choice]")];
assert.deepEqual(blurAreaChips.map((chip) => chip.dataset.choice), ["face", "hair", "head"],
    "one chip per area");
assert.deepEqual(blurAreaChips.map((chip) => chip.textContent),
    ["Face only", "Face + hair", "Whole head (hair, hats, glasses)"], "each naming its area");
assert.equal(blurAreaChips.filter((chip) => chip.classList.contains("is-on")).length, 1,
    "exactly one is lit");
assert.equal(blurRow.querySelector(".is-on").dataset.choice, "hair", "defaulting to face + hair");
// Where it sits: inside the picture's own card, after the paint bar - the canvas card, not the
// list's header a column away.
assert.ok(blurRow.closest('[data-action="ref-canvas"]'), "it lives in the picture's card");
assert.equal(panel.container.querySelector('.mmx-card__head [data-action="blur-scope"]'), null,
    "and NOT in the reference list's header any more");
assert.equal(core.blurScope(core.readState("")), "hair", "and the state reader agrees");
blurRow.querySelector('[data-choice="head"]').click();
assert.equal(state.blurScope, "head", "picking one writes it to the panel state");
assert.equal(saved.at(-1).render.blurScope, "head", "and into the payload the node parses");
assert.equal(core.readState(JSON.stringify(saved.at(-1))).blurScope, "head", "round-tripped");
assert.equal(core.blurScope({ blurScope: "nonsense" }), "hair", "an unknown area falls back");
ok.push("blur area: face / face + hair / whole head, as chips under the picture, one setting "
    + "for the sheet");

// --- the picture is the only picture: no before/after pair under it ---------------
// The pair (two thumbnails of the same photo) cost a third of the stage's height and told the
// reader nothing the Original/Blurred buttons did not: those switch the one picture between the
// file and the copy the render wires, and the sentence beside them says which one is on screen.
{
    const canvas = panel.container.querySelector('[data-action="ref-canvas"]');
    assert.equal(canvas.querySelector(".mmx-compare"), null, "no extra thumbnails under the picture");
    assert.ok(canvas.querySelector('[data-action="preview-blur"]'), "the Original/Blurred switch stays");
    assert.ok(canvas.querySelector(".mmx-preview__blurbar"), "with its sentence");
    const bar = canvas.querySelector(".mmx-preview__blurbar");
    assert.ok(/render sends|Nothing to blur|blurred/.test(bar.textContent + canvas.textContent),
        "which says what the render wires");
    assert.ok(!/mmx-compare/.test(core.PANEL_CSS), "and its stylesheet went with it");
    // With the pair gone the picture takes more of the pane: the share is what hands it the room.
    assert.match(core.PANEL_CSS, /\.mmx-preview__stage \{[^}]*flex: 1 1 auto/,
        "the stage still grows");
    ok.push("the reference stage shows one picture, not three");
}

// --- the ticks still own the panel list (untick removes, tick adds) --------------
// The reported bug: once the cell list had been materialised (a drop on a panel, "Use these
// cells", or a workflow that saved one), changing the ticks did nothing - unticking "back" left
// that panel on the stage and ticking "back of head" never appeared. The list is now rebuilt from
// the ticks on every tick change, with the panels the user edited by hand kept in place.
{
    const tickState = core.readState("");
    tickState.build = { views: ["face", "front", "back"], poses: ["neutral"], expressions: ["neutral"] };
    const tickPanel = core.buildSheetInterface({
        state: tickState,
        hooks: { status: () => {}, planCells: async () => ({ cells: [] }) },
    });
    await tick();
    tickPanel.showTab("cells");
    const pane = tickPanel.container.querySelector(".mmx-pane--cells");
    const views = () => [...pane.querySelectorAll(".mmx-cellbox__view")].map((n) => n.textContent);
    assert.deepEqual(views(), ["Face · Neutral", "front · Neutral", "back · Neutral"],
        "the stage starts as the ticks ask");
    // Untick "back": its panel goes.
    const back = pane.querySelector('.mmx-tickgroup--views .mmx-glyph[data-key="back"] input');
    back.checked = false;
    back.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await tick();
    assert.deepEqual(views(), ["Face · Neutral", "front · Neutral"],
        "unticking a framing removes its panel");
    assert.ok(!tickState.cells.some((cell) => cell.view === "back"),
        "and the cell list the payload sends says so");
    // Tick "back of head": its panel appears, in tick order.
    const headBack = pane.querySelector('.mmx-tickgroup--views .mmx-glyph[data-key="head-back"] input');
    headBack.checked = true;
    headBack.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await tick();
    assert.deepEqual(views(), ["Face · Neutral", "front · Neutral", "Back of head"],
        "ticking a new framing adds its panel");
    assert.deepEqual(core.toPayload(tickState).cells.map((cell) => cell.id),
        ["face-neutral-neutral", "front-neutral-neutral", "head-back-neutral-neutral"],
        "and the payload follows the ticks");
    // A panel edited by hand survives a tick change - it is a choice, not a plan artefact.
    // jsdom has no DataTransfer: a plain Event is enough, because the handlers only read
    // `event.dataTransfer` when it exists (see draggableOnto).
    const fire = (node, type) => node.dispatchEvent(new dom.window.Event(type, { bubbles: true, cancelable: true }));
    const smile = pane.querySelector('.mmx-tickgroup--expressions .mmx-glyph[data-key="smile"]');
    fire(smile, "dragstart");
    fire(pane.querySelector('.mmx-cellbox[data-index="0"]'), "dragover");
    fire(pane.querySelector('.mmx-cellbox[data-index="0"]'), "drop");
    fire(smile, "dragend");
    await tick();
    assert.equal(tickState.cells[0].expression, "smile", "the dropped expression is on the panel");
    const front = pane.querySelector('.mmx-tickgroup--views .mmx-glyph[data-key="front"] input');
    front.checked = false;
    front.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await tick();
    assert.equal(tickState.cells[0].expression, "smile",
        "and it is still there after the ticks change around it");
    assert.equal(tickState.cells[0].id, "face-neutral-neutral", "on the same panel");
    tickPanel.dispose();
    ok.push("the ticks own the panel list: untick removes, tick adds, hand-made panels stay");
}

// --- the node's floor is a size the design still works at -----------------------
// The numbers are only meaningful together with the container query: the halves stack below
// 640px of PANEL, and the node is 20px wider than its panel, so a floor at or under 660 would
// clamp the node to a size that immediately stacks. The floor therefore has to leave the two
// columns room to be columns - and the default has to be at or above the floor.
{
    assert.ok(core.NODE_MIN_WIDTH - 20 > 640,
        `the floor keeps the two columns (panel ${core.NODE_MIN_WIDTH - 20}px vs a 640px stack point)`);
    assert.ok(core.NODE_MIN_WIDTH - 20 >= 700,
        "with enough room left that a column is still a column, not a sliver");
    assert.ok(core.NODE_MIN_WIDTH <= core.NODE_WIDTH && core.NODE_MIN_HEIGHT <= core.NODE_HEIGHT,
        "and a node cannot open below its own floor");
    assert.match(core.PANEL_CSS, /@container \(max-width: 640px\)/,
        "the stack point the floor is measured against is the one in the stylesheet");
    ok.push(`the node's floor (${core.NODE_MIN_WIDTH}x${core.NODE_MIN_HEIGHT}) sits above the stack point`);
}

// --- only the two tabs that decide something own a column ----------------------
// The panel is two equal halves on Cells and References, where the second half IS the decision
// (which sheet, how big, how sampled / which references). Prompt, Results, Preview, Settings and
// Help are read-outs of the render, and a second half holding nothing is a wide empty box beside
// the thing the user came to read: those tabs get the whole panel.
{
    const tabPanel = core.buildSheetInterface({
        state: core.readState(""),
        hooks: { status: () => {}, planCells: async () => ({ cells: [] }) },
    });
    await tick();
    const col = tabPanel.container.querySelector(".mmx-col");
    const colBody = col.querySelector(".mmx-col__body");
    assert.ok(col && colBody, "the panel has a control column");
    const withColumn = [];
    const without = [];
    for (const tab of core.TAB_ORDER) {
        tabPanel.showTab(tab);
        await tick();
        const off = col.classList.contains("is-off");
        (["cells", "references"].includes(tab) ? withColumn : without).push([tab, off, colBody.children.length]);
    }
    assert.deepEqual(withColumn.map(([tab, off]) => [tab, off]),
        [["references", false], ["cells", false]],
        "References and Cells keep the column, and it is shown");
    assert.ok(withColumn.every(([, , kids]) => kids === 1), "each of them fills it with its own block");
    for (const [tab, off, kids] of without) {
        assert.equal(off, true, `${tab} takes the column away`);
        assert.equal(kids, 0, `${tab} leaves nothing behind in it`);
    }
    assert.match(core.PANEL_CSS, /\.mmx-col\.is-off \{ display: none; \}/,
        "and the stylesheet is what hides it (the class alone would do nothing)");
    // The collapsed column must not cost width either: the stage is the panel.
    assert.ok(/\.mmx-stage \{[^}]*flex: 1 1 0/.test(core.PANEL_CSS) || /flex: 1 1 auto/.test(core.PANEL_CSS),
        "the stage grows into the space the column gave back");
    // Round trip: going back to Cells brings the block with it (it is MOVED, not rebuilt).
    tabPanel.showTab("cells");
    await tick();
    assert.ok(!col.classList.contains("is-off") && colBody.children.length === 1,
        "and coming back fills it again");
    tabPanel.dispose();
    ok.push("the column is a property of the two tabs that decide, not of the panel");
}

// --- the mode segment is lit by the NODE's own knob ----------------------------
// A fresh node renders one-pass (that is the `single_pass` widget's own default) and no preset has
// been chosen, so the segment used to show nothing at all - which reads as "unknown" rather than
// as the default. The knob is the truth; a chosen preset still wins.
{
    const quality = [
        { id: "balanced", kind: "quality", label: "One-pass sheet (default)", render: { singlePass: true } },
        { id: "per-cell", kind: "quality", label: "Per-cell renders (classic)",
            render: { singlePass: false }, widgets: { single_pass: false } },
        { id: "identity", kind: "quality", label: "Max identity fidelity",
            render: { singlePass: false }, widgets: { single_pass: false } },
    ];
    const build = async (knobValues, presetId) => {
        const state = core.readState("");
        state.knobValues = { ...(state.knobValues || {}), ...knobValues };
        state.presetId = presetId;
        const p = core.buildSheetInterface({
            state,
            hooks: { status: () => {}, listPresets: async () => ({ presets: quality, resolutions: [] }) },
        });
        await tick();
        // The segment is the COLUMN's, and the column is the Cells tab's (see the block above).
        p.showTab("cells");
        await tick();
        const seg = p.container.querySelector('.mmx-seg[data-action="preset"]');
        const lit = [...seg.querySelectorAll(".mmx-btn.is-active")].map((n) => n.dataset.presetId);
        const labels = [...seg.querySelectorAll(".mmx-btn")].map((n) => n.textContent);
        p.dispose();
        return { lit, labels };
    };
    const fresh = await build({ single_pass: true, steps: 8 }, "");
    assert.deepEqual(fresh.lit, ["balanced"], "a fresh one-pass node lights One pass");
    assert.deepEqual(fresh.labels, ["One pass", "Per cell", "Max identity"],
        "and the three modes are named on the line");
    const perCell = await build({ single_pass: false }, "");
    assert.deepEqual(perCell.lit, ["per-cell"], "a node switched to per-cell lights that one");
    const chosen = await build({ single_pass: true }, "identity");
    assert.deepEqual(chosen.lit, ["identity"], "a preset the user picked wins over the knob");
    assert.ok(!/\.mmx-seg \.mmx-btn \{/.test(core.PANEL_CSS)
        || /\.mmx-modeseg \.mmx-seg \.mmx-btn \{[^}]*min-width: 0/.test(core.PANEL_CSS),
        "the segment's buttons may shrink, or the steps chip falls off the side of the node");
    ok.push("the mode segment says which mode the node is in, out of the box");
}

// --- a wider node does not make the sheet cards taller -------------------------
// The card art was a 3:2 box, so a wider node made every card taller and pushed the size cards and
// the mode row down the column - the reported "the sheets grow and block the resolution pickers".
// In the column the art is a FIXED height: the cards may get wider, they may not get taller.
{
    const rule = /\.mmx-col \.mmx-pcard__art \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(rule, "the column's own card art rule exists");
    assert.match(rule[1], /height:\s*62px/, "and pins the art's height");
    assert.match(rule[1], /aspect-ratio:\s*auto/, "overriding the 3:2 the rails use elsewhere");
    assert.match(core.PANEL_CSS, /\.mmx-pcard__art \{[^}]*aspect-ratio: 3 \/ 2/,
        "while the free-standing rail keeps its proportions");
    assert.match(core.PANEL_CSS, /\.mmx-modeseg \{[^}]*flex-wrap: wrap/,
        "and the mode row may wrap, so the steps chip is never pushed out of the column");
    ok.push("the sheet cards keep their height when the node is made wider");
}

// --- the accent is the proposal's orange --------------------------------------
// ComfyUI's own primary is blue, and the panel used to take it: the mockup's render button, lit
// chips and live tab are ORANGE (#ffb347), and the mockup's blue is its second colour.
{
    assert.match(core.PANEL_CSS, /--mmx-accent: #ffb347;/,
        "the accent is proposal B's orange, not the theme's blue");
    assert.ok(!/--mmx-accent: var\(--p-primary-color/.test(core.PANEL_CSS),
        "and it is pinned, so a blue theme cannot bring the blue button back");
    assert.match(core.PANEL_CSS, /--mmx-accent-ink: #17171c;/,
        "the text on the accent is dark, like the mockup's own primary button");
    const primary = /\.mmx-btn--primary \{([^}]*)\}/.exec(core.PANEL_CSS);
    assert.ok(primary && /color: var\(--mmx-accent-ink\)/.test(primary[1]),
        "the Render button is the accent with dark text on it");
    assert.ok(!/background: var\(--mmx-accent\)[^;]*color: #fff/.test(core.PANEL_CSS),
        "nothing writes white on the accent any more");
    ok.push("the primary action wears the proposal's orange");
}

// --- a one-pass stream is the sheet, not a panel --------------------------------
// The reported symptom: a panel's box came back wearing the rendered image instead of the plan.
// A one-pass (whole-sheet) stream sends the ENTIRE sheet, and `liveLast.cell` is 0 for it - so it
// was painted into panel 1's box and stayed there. The strip and the Preview tab take the sheet;
// the panels keep the plan.
{
    const shell = core.buildSheetInterface({
        state: core.readState(""),
        hooks: { status: () => {}, planCells: async () => ({ cells: [] }) },
    });
    await tick();
    shell.showTab("cells");
    await tick();
    const boxes = () => [...shell.container.querySelectorAll(".mmx-cellbox")];
    const painting = boxes().filter((box) => box.style.getPropertyValue("--mmx-cell-shot"));
    assert.deepEqual(painting, [], "no box is painted before anything streams");

    shell.setLivePreview({ frames: ["data:image/png;base64,AAAA"], whole_sheet: true, cell: 0,
        cells: 5, step: 3, steps: 8 });
    await tick();
    assert.equal(boxes().filter((box) => box.classList.contains("is-live")).length, 0,
        "the whole sheet is not painted into a panel's box");
    assert.deepEqual(boxes().filter((box) => box.style.getPropertyValue("--mmx-cell-shot")), [],
        "and no panel keeps the sheet as its own frame");
    // The sheet is still ON SCREEN: the strip takes it, which is the point of the fix.
    const strip = shell.container.querySelector(".mmx-live");
    assert.equal(strip.style.display, "flex", "the live strip shows the whole sheet");
    assert.match(strip.querySelector(".mmx-live__frame").getAttribute("src"), /AAAA/);

    // A PER-CELL stream still marks its own panel: that one IS the cell being drawn.
    shell.setLivePreview({ frames: ["data:image/png;base64,BBBB"], cell: 2, cells: 5, step: 1,
        steps: 8 });
    await tick();
    const live = boxes().filter((box) => box.classList.contains("is-live"));
    assert.equal(live.length, 1, "one panel is live");
    assert.equal(live[0].dataset.index, "1", "and it is the cell the stream names");
    assert.match(live[0].style.getPropertyValue("--mmx-cell-shot"), /BBBB/);
    // The stream ending lets the boxes go: nothing is being drawn, so nothing wears a frame.
    shell.setLivePreview({});
    await tick();
    assert.deepEqual(boxes().filter((box) => box.classList.contains("is-live")), [],
        "the boxes stop being live when the stream does");
    shell.dispose();
    ok.push("a one-pass stream never replaces a panel: the cells keep the plan");
}

console.log("h3sheet_core: PASS");
for (const line of ok) console.log(" -", line);