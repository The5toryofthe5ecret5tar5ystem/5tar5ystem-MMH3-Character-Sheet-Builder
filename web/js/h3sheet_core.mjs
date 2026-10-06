// MiniMax H3 Character Sheet Builder — panel DOM + state (no ComfyUI imports).
//
// Kept free of `app`/`api` on purpose: the panel's structure (drag-and-drop
// reference tiles with roles, the cell matrix, the frame picker) is testable in
// jsdom, and only `h3sheet_ui.js` does IO (uploads, sheet routes, the DOM widget).
// This file owns everything the user sees; the wiring file owns how it is mounted.
//
// The reference area follows the Easy-Media Multi-Track picture grid: square
// tiles, thumbnails, index badges, hover actions, drag and drop of files straight
// from the desktop, drag-to-reorder between slots and a Browse overlay that lists
// what is already in ComfyUI's input/output folders.
//
// IO is injected through `hooks`:
//   stateChanged(payload)                  -> persist into the node's sheet_data widget
//   upload(file, groupKey)                 -> Promise<input-relative path>
//   listMedia({source, kind, query})       -> Promise<{items:[{name,path,url,kind}]}>
//   assetUrl(url)                          -> fetchable URL for a /view path
//   listResults()                          -> Promise<sheet listing | null>
//   pickFrame(cellId, index)               -> Promise<void>
//   compose()                              -> Promise<void>
//   clearSheet()                           -> Promise<void>
//   status(text)                           -> optional, called on notable events

//: The tick lists for the Cells tab. Mirrors VIEWS / POSES / EXPRESSIONS in
//: h3_character_sheet/sheet_spec.py - the backend owns the prompt text, this is only what
//: the panel offers, and the labels stay short because they sit in a legible grid.
export const VIEWS = [
    ["face", "Face close up"],
    ["portrait", "Portrait"],
    ["front", "Full body front"],
    ["profile", "Full body side"],
    ["back", "Full body back"],
    ["three-quarter", "3/4 front"],
    ["three-quarter-back", "3/4 back"],
    ["high-angle", "Full body high angle"],
    ["low-angle", "Full body low angle"],
    ["over-shoulder", "Over the shoulder"],
    ["face-profile", "Head profile"],
    ["head-back", "Back of head"],
    ["hands", "Hands"],
    ["eyes", "Eyes"],
    ["legs", "Legs & footwear"],
    ["mouth", "Mouth"],
    ["feet", "Feet"],
    ["breasts", "Breasts"],
    ["groin", "Groin"],
    ["butt", "Butt"],
];
export const POSES = [
    ["neutral", "Neutral"],
    ["a-pose", "A-pose"],
    ["t-pose", "T-pose"],
    ["sitting", "Sitting"],
    ["kneeling", "Kneeling"],
    ["crouching", "Crouching"],
    ["lying", "Lying on back"],
    ["walking", "Walking"],
    ["contrapposto", "Contrapposto"],
    ["hands-on-hips", "Hands on hips"],
    ["arms-crossed", "Arms crossed"],
    ["reach-camera", "Reach to camera"],
    ["hair-touch", "Hand through hair"],
];
export const EXPRESSIONS = [
    ["neutral", "Neutral"],
    ["smile", "Smile"],
    ["smirk", "Smirk"],
    ["frown", "Frown"],
    ["anger", "Anger"],
    ["fear", "Fear"],
    ["surprised", "Surprised"],
    ["embarrassed", "Embarrassed"],
    ["crying", "Crying"],
    ["closed-eyes", "Eyes closed"],
    ["lips-parted", "Lips parted"],
    ["tongue-out", "Tongue out"],
    ["ahego", "Ahego (eyes up, tongue out)"],
    ["laugh", "Laugh"],
    ["pout", "Pout"],
    ["wink", "Wink"],
    ["disgust", "Disgust"],
    ["determined", "Determined"],
    ["pain", "Pain"],
    ["aroused", "Aroused"],
    ["pleasure", "Pleasure"],
    ["orgasm", "Orgasm"],
];
export const PICKS = ["auto", "last", "sharpest", "manual"];

//: What the pick selector calls each mode. ``manual`` is what a click on a thumbnail records:
//: it is shown as the cell's mode afterwards, so a hand-picked frame is never a mystery.
export const PICK_LABELS = {
    auto: "auto (settled)",
    last: "last frame",
    sharpest: "sharpest frame",
    manual: "chosen by hand",
};

//: What the model is told to put behind the figure. Mirrors BACKGROUNDS in
//: h3_character_sheet/sheet_spec.py (the wiring test compares the two). Every preset is a
//: FLAT backdrop - no gradient, no vignette, no shadow - and ``reference`` takes its setting
//: from one of the sheet's own references.
export const BACKGROUNDS = [
    ["neutral", "Neutral grey"],
    ["tan", "Neutral tan"],
    ["white", "Flat white"],
    ["grey", "Mid grey"],
    ["black", "Flat black"],
    ["green", "Green screen"],
    ["blue", "Blue screen"],
    ["reference", "Reference image/video"],
    ["custom", "Custom..."],
];

//: The standard 8-view sheet. Mirrors DEFAULT_MATRIX in h3_character_sheet/planner.py
//: (the wiring test compares the two), and is what the node renders when a payload
//: has no cells at all.
export const DEFAULT_MATRIX = [
    ["face", "neutral", "neutral"],
    ["face", "neutral", "smile"],
    ["portrait", "neutral", "neutral"],
    ["front", "neutral", "neutral"],
    ["front", "a-pose", "neutral"],
    ["front", "t-pose", "neutral"],
    ["profile", "neutral", "neutral"],
    ["back", "neutral", "neutral"],
];

/** The default matrix as cell payloads (same shape ``Build cells`` produces). */
export function defaultCells() {
    return DEFAULT_MATRIX.map(([view, pose, expression]) => ({
        id: `${view}-${pose}-${expression}`, view, pose, expression,
    }));
}

export const REF_GROUPS = [
    {
        key: "pictures",
        file: "imageFile",
        label: "Pictures",
        // The kind is also the icon name: see ICONS (a text glyph used to live here, and
        // "\u25a3" read as "some box" rather than "a picture").
        kind: "image",
        slots: 9,
        columns: 3,
        accept: "image/*",
        role: "face and hair",
        hint: "identity, face, hair, body, clothing",
    },
    {
        key: "videos",
        file: "videoFile",
        label: "Videos",
        kind: "video",
        slots: 3,
        columns: 3,
        accept: "video/*",
        role: "clothing and body",
        hint: "clothing, body proportions, motion",
    },
    {
        key: "audios",
        file: "audioFile",
        label: "Audios",
        kind: "audio",
        slots: 3,
        columns: 2,
        accept: "audio/*",
        role: "voice and tone",
        hint: "voice / tone reference",
    },
];

//: How a picture reference treats the faces in it. ``auto`` (the default) blurs a
//: picture that is not the identity source - the outfit photo that is a whole second
//: person - and leaves the identity photo alone. Mirrors BLUR_MODES in sheet_spec.py.
export const BLUR_MODES = ["auto", "on", "off"];
export const BLUR_LABELS = { auto: "Blur auto", on: "Blur on", off: "Blur off" };
//: The same three states as short badges for the tile: the tile says its state in two words and the
//: sentence behind it is the tooltip (see BLUR_TITLES). ``blurButtonLabel`` keeps the long form for
//: anything that still wants a phrase.
export const BLUR_BADGE_LABELS = { auto: "blur auto", on: "blur on", off: "blur off" };
//: The same three states on a SOUND, which is muted rather than blurred: a voice has no
//: pixels, so the removal is the whole sound (silence at the source's own length).
export const MUTE_BADGE_LABELS = { auto: "mute auto", on: "mute on", off: "mute off" };
export const BLUR_TITLES = {
    auto: "Face blur: automatic - blurs this reference unless it is the identity reference",
    on: "Face blur: always - the faces in this reference are blurred before the render",
    off: "Face blur: never - this reference is sent exactly as it is",
};
export const MUTE_TITLES = {
    auto: "Voice: automatic - kept. A sound reference is added on purpose (it is usually the\n"
        + "performance itself), so it is only muted when you say so",
    on: "Voice: muted - the render gets silence at this reference's own length and channels",
    off: "Voice: kept - this sound is sent exactly as it is",
};

/** The blur mode a reference declares, defaulting to ``auto``. */
export function blurMode(slot) {
    const value = String(slot?.blurFace ?? slot?.blur_face ?? "").trim().toLowerCase();
    return BLUR_MODES.includes(value) ? value : "auto";
}

/** The next mode in the auto -> on -> off cycle (one click, no menu). */
export function nextBlurMode(mode) {
    const index = BLUR_MODES.indexOf(blurMode({ blurFace: mode }));
    return BLUR_MODES[(index + 1) % BLUR_MODES.length];
}

//: The rail's icons: one per tab, drawn as line art so the rail costs no image files and
//: inherits the theme's colours (a mark that is a <use> in the sprite would be hidden with
//: it, and these are chrome, not vocabulary).
export const RAIL_ICONS = {
    // Pictures: two plates and two strips - the tab's own subject, at a glance.
    references: '<rect x="3.5" y="5" width="7.6" height="7.6" rx="1"/>'
        + '<rect x="12.9" y="5" width="7.6" height="7.6" rx="1"/>'
        + '<rect x="3.5" y="15" width="7.6" height="3.2" rx="1"/>'
        + '<rect x="12.9" y="15" width="7.6" height="3.2" rx="1"/>',
    // Panels: the sheet's own 2x2.
    cells: '<rect x="3.5" y="3.5" width="7.6" height="7.6" rx="1"/>'
        + '<rect x="12.9" y="3.5" width="7.6" height="7.6" rx="1"/>'
        + '<rect x="3.5" y="12.9" width="7.6" height="7.6" rx="1"/>'
        + '<rect x="12.9" y="12.9" width="7.6" height="7.6" rx="1"/>',
    // Text lines.
    prompts: '<path d="M4 6.6h16M4 12h11M4 17.4h7"/>',
    // A sheet with a filmstrip down one side.
    results: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M9.6 4.5v15"/>',
    // A play mark in a screen: the render's own live stream, at full size, on its own tab.
    preview: '<rect x="3.2" y="4.6" width="17.6" height="12.4" rx="1.6"/>'
        + '<path d="M10.2 8.4l4.4 2.4-4.4 2.4z"/>'
        + '<path d="M8.5 19.6h7"/>',
    // Two sliders.
    settings: '<path d="M4 8.5h16M4 15.5h16"/><circle cx="9.4" cy="8.5" r="2"/>'
        + '<circle cx="14.6" cy="15.5" r="2"/>',
    // Three stacked plates: a stack of something applied to everything below it.
    loras: '<path d="M12 4.2l7.4 3.6-7.4 3.6-7.4-3.6z"/>'
        + '<path d="M4.6 12.2l7.4 3.6 7.4-3.6"/>'
        + '<path d="M4.6 16.2l7.4 3.6 7.4-3.6"/>',
    // A question, in a circle.
    help: '<circle cx="12" cy="12" r="8.4"/>'
        + '<path d="M9.9 9.8a2.3 2.3 0 1 1 3 2.2c-.8.3-1.1.8-1.1 1.6"/>'
        + '<path d="M11.8 16.8h.01"/>',
};

/** The rail button's contents: a 24-grid line icon that inherits its parent's colour. */
function railIcon(key) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
        + ' stroke-linecap="round" stroke-linejoin="round">'
        + (RAIL_ICONS[key] || "") + "</svg>";
}

/** The tab names, in one place: the rail's tooltips and its own labels read them. */
const TAB_TITLES = {
    references: "References",
    cells: "Cells",
    prompts: "Prompt",
    loras: "LoRAs",
    results: "Results",
    preview: "Preview",
    settings: "Settings",
    help: "Help",
};

//: The rail's order. Preview sits after Results: it is what you watch while a run works, and it
//: comes after the thing that run is producing. LoRAs sits with the settings: it is a decision
//: about how the sheet renders, not a step in building it - but a whole tab of its own, because a
//: stack is a list of rows and a stack of rows is not a knob.
export const TAB_ORDER = ["references", "cells", "prompts", "results", "preview", "loras", "settings", "help"];

//: How much of the head a blur covers. Mirrors BLUR_SCOPES in sheet_spec.py: the
//: detector reports the face box, so hair and headwear are covered by growing the patch
//: around it. One setting for the sheet - *whether* a picture is blurred stays per tile.
export const BLUR_SCOPES = [
    ["face", "Face only"],
    ["hair", "Face + hair"],
    ["head", "Whole head (hair, hats, glasses)"],
];
export const DEFAULT_BLUR_SCOPE = "hair";

/** The blur area a state declares, defaulting to ``hair``. */
export function blurScope(state) {
    const value = String(state?.blurScope ?? state?.blur_scope ?? "").trim().toLowerCase();
    return BLUR_SCOPES.some(([key]) => key === value) ? value : DEFAULT_BLUR_SCOPE;
}

//: The sheet's own LoRA stack (the LoRAs tab). One list on the SHEET rather than a loader node in
//: the graph: the node applies it to the model every cell samples through, so one list covers
//: every cell and every board of a suite. Mirrors MAX_LORAS / LORA_STRENGTH_RANGE in sheet_spec.py.
export const MAX_LORAS = 16;
export const DEFAULT_LORA_STRENGTH = 1;
export const LORA_STRENGTH_RANGE = [-4, 4];
export const LORA_STRENGTH_STEP = 0.05;
//: The slider's window when a file has no range saved for it. A LoRA's useful band is usually
//: 0..1.5 and occasionally negative (pushing one the other way is a real technique), so the
//: slider offers -1..2 while the number box takes the payload's own ±4.
export const DEFAULT_LORA_SLIDER_RANGE = [-1, 2];

/**
 * The sheet's LoRA stack: the payload's list, normalized into what the node will apply.
 *
 * The panel is the authoring surface, so this is where a bad row is dropped rather than sent:
 * no file, a repeat of a file already in the stack, a strength that is not a number, an entry
 * past the cap. Whatever survives is exactly what ``payload.loras`` carries and what the tab
 * draws - one list, one place it is decided.
 */
export function loraStack(state) {
    const raw = Array.isArray(state?.loras) ? state.loras : [];
    const out = [];
    const seen = new Set();
    for (const item of raw) {
        const file = String(item?.file || "").trim().replace(/\\/g, "/").replace(/^\.\//, "");
        if (!file || seen.has(file)) continue;
        const value = Number(item?.strength);
        const strength = Number.isFinite(value)
            ? Math.min(LORA_STRENGTH_RANGE[1], Math.max(LORA_STRENGTH_RANGE[0], value))
            : DEFAULT_LORA_STRENGTH;
        seen.add(file);
        out.push({ file, strength, on: item?.on !== false });
        if (out.length >= MAX_LORAS) break;
    }
    return out;
}

//: Latent continuation between cells. Mirrors CONTINUITY_* in sheet_spec.py: each cell is
//: its own short H3 clip, so by default cell 2 starts from its own noise. Switched on, the
//: last frames of the previous cell are anchored at the start of the next clip (H3's guide
//: API), so a run of cells continues instead of restarting - same room, light and framing.
//: ``auto`` is the honest default for a sheet: the hand-over carries the previous camera
//: distance, so a framing change (a face close-up, then a full body) is fought by the model
//: unless the cell is rendered on its own.
export const CONTINUITY_MODES = ["off", "auto", "on"];
export const CONTINUITY_LABELS = [
    ["off", "Off - every cell is independent"],
    ["auto", "Auto - continue only where the framing matches"],
    ["on", "On - always continue the previous cell"],
];
//: Frames handed over. A guide clip is cropped to the H3 17k+5 grid (5, 22, 39...), so 5
//: is the smallest hand-over; those frames of the new cell re-render the previous tail.
export const CONTINUITY_FRAMES = 5;

//: Camera distance per view, mirroring FRAMING_DISTANCES in sheet_spec.py.
export const FRAMING_DISTANCES = {
    face: "close",
    portrait: "medium",
    front: "full",
    profile: "full",
    back: "full",
};

/** How far the camera is for a view ("" when unknown - never matches another cell). */
export function framingDistance(view) {
    return FRAMING_DISTANCES[String(view || "").trim().toLowerCase()] || "";
}

//: Write each cell's rendered clip (frames + the audio H3 generated with them) next to
//: those frames, at H3's fixed 24 fps. Mirrors SheetRenderSpec.export_video: the sheet
//: composite stays the deliverable, the clips are the takes it was picked from.
export function exportVideo(state) {
    const value = state?.exportVideo ?? state?.render?.exportVideo;
    return value === undefined || value === null ? true : Boolean(value);
}

/** The sheet-wide continuation mode, defaulting to ``off``. */
export function continuity(state) {
    const value = String(state?.continuity ?? state?.render?.continuity ?? "").trim().toLowerCase();
    return CONTINUITY_MODES.includes(value) ? value : "off";
}

//: Per-cell override: inherit the sheet switch, or force it on / off for this cell.
export const CELL_CONTINUITY_MODES = ["inherit", "auto", "on", "off"];
export const CELL_CONTINUITY_LABELS = [
    ["inherit", "cont: inherit"],
    ["auto", "cont: auto"],
    ["on", "cont: continue"],
    ["off", "cont: no"],
];

/** How many columns the Settings tab packs the node's knobs into. */
export const KNOB_COLUMNS = 3;

// --------------------------------------------------------------------------- //
// the node's own output previews (the ones ComfyUI draws under the panel)
// --------------------------------------------------------------------------- //
// The frontend, not this pack, draws those, and it does it THREE different ways in the
// current build - which is why capping only one of them left the node huge:
//
//   * a still image is an `ImagePreviewWidget` named `$$canvas-image-preview`, drawn on the
//     CANVAS (no element, no class, no DOM option) at the height the widget layout gives it;
//   * an image sequence is a `$$comfy_animation_preview` DOM widget holding one `<img>`;
//   * a video is a `video-preview` DOM widget holding one `<video>`.
//
// All three are laid out by `_arrangeWidgets`, which asks each widget for
// `computeLayoutSize()` and gives `{minHeight, maxHeight}` to `distributeSpace`: an undefined
// `maxHeight` means unbounded, so that widget absorbs every pixel of height the node has left
// over. Overriding `computeLayoutSize` is therefore the pack's lever (see capPreviewWidget):
// it bounds the widget however the frontend chose to draw it. For the DOM kinds a class plus
// one stylesheet rule caps the MEDIA itself as well, since the wrapper's height and the drawn
// image's height are two different numbers:
//
//     .mmx-preview-compact.mmx-preview-compact img { height: 200px !important; ... }
//
// The doubled class is deliberate: the frontend's own `.comfy-img-preview img` rule has the
// same specificity as a single class + element, and its later-inserted stylesheets would win
// a tie, so the rule is written to out-specify it rather than rely on document order. `full`
// restores the widget's original function and removes the class.

/**
 * The panel's build tag, shown in the header and used as the module's cache-busting suffix by
 * ``h3sheet_ui.js`` (``import ... ?boot=h3sheet_vNN``).
 *
 * A browsing tab keeps the module it loaded first, so after a pack update the panel can be
 * running yesterday's code while the file on disk says otherwise - and a symptom like "the
 * setting does nothing" is impossible to tell apart from a bug from the outside. Printing the
 * build makes that a glance instead of an investigation; a test keeps it in step with the
 * import, so bumping one without the other fails the suite rather than confusing a user.
 */
export const PANEL_BUILD = "h3sheet_v88";

/**
 * The pack's own sample render, shown in a fresh node's reference canvas (see canvasCard).
 *
 * A path relative to the extension's web directory: the wiring resolves it with its own
 * `import.meta.url` through the `packAsset` hook, so the panel never guesses where it is served
 * from (and a bare module - a test - simply passes no hook and gets the plain hint instead).
 */
export const PLACEHOLDER_ART = "assets/sample-elf-girl.jpg";

/** How long a knob hint may be before it stops being printed under its field (it stays a tooltip).
 *
 * The knob grid is the widest surface in the panel: 23 knobs, each with a sentence, is a page of
 * prose. Short hints ("32px grid") still read as part of the field; anything longer becomes the
 * control's tooltip. */
export const HINT_INLINE_LIMIT = 24;

/** The frontend's own widget/host names, straight from the shipped frontend bundle. */
export const PREVIEW_HOST_CLASS = "comfy-img-preview";
//: A still image is NOT a DOM element in this frontend: an `ImagePreviewWidget` named
//: `$$canvas-image-preview` draws it on the canvas (so there is no element to class or to
//: style, and no `getMinHeight` option for the layout to read - see capPreviewWidget).
export const PREVIEW_CANVAS_IMAGE_WIDGET = "$$canvas-image-preview";
//: An image sequence is one <img> inside a DOM widget...
export const PREVIEW_ANIMATION_WIDGET = "$$comfy_animation_preview";
//: ...and a video is one <video> inside a DOM widget with its own layout sizing.
export const PREVIEW_VIDEO_WIDGET = "video-preview";
//: Every widget that IS an output preview. All three are capped the same way, or one of them
//: quietly keeps the node tall (which is exactly what happened to the still image).
export const PREVIEW_WIDGET_NAMES = [
    PREVIEW_CANVAS_IMAGE_WIDGET, PREVIEW_ANIMATION_WIDGET, PREVIEW_VIDEO_WIDGET,
];
/** The animation widget's name, kept as its own export (it was the only one recognised). */
export const PREVIEW_WIDGET_NAME = PREVIEW_ANIMATION_WIDGET;

/** The class (and rule id) the pack uses to cap them. */
export const PREVIEW_COMPACT_CLASS = "mmx-preview-compact";
export const PREVIEW_RULE_ID = "mmx-preview-compact-rule";

/** Height of one preview in `compact` mode (px): enough to judge a face, not the node. */
export const PREVIEW_COMPACT_HEIGHT = 200;

//: The tallest a `width` preview may get. Full width means the height the media's own aspect
//: needs at this node width - ~560px for a 16:9 sheet in a 1000px node, and ~1780px for a
//: portrait cell clip, which is a node nobody wants. Past this the preview is centred instead
//: (see previewWidthHeight): a portrait clip is never going to fill a wide node anyway.
export const PREVIEW_WIDTH_MAX_HEIGHT = 720;

/** The shortest a `width` preview may get, so a panorama is still a preview. */
export const PREVIEW_WIDTH_MIN_HEIGHT = 120;

//: Slack added to the computed height (px). The two paths that draw a preview both shave the box
//: before fitting the media into it - the DOM grid asks for `node.size[0] - 20` and the canvas
//: renderer reserves 15px when the size label is on - and the fit is a `min(scaleX, scaleY)`:
//: being a few px SHORT turns a full-width preview into a centred one, while being a few px TALL
//: only letterboxes it. So err long.
export const PREVIEW_WIDTH_SLACK = 16;

/**
 * `panel` = ComfyUI's own previews are removed, the panel shows the sheet (default),
 * `compact` = small and side by side, `width` = fills the node width, `off` = nothing.
 *
 * `panel` exists because SIZING the frontend's previews is a losing game. Measured on a real
 * node: the frontend creates `$$canvas-image-preview` when the sheet image finishes loading,
 * with its own `computeLayoutSize(){return{minHeight:220,minWidth:1}}` and NO maximum - so the
 * preview absorbed 1053px and the node became 2442px tall. Caps only land on it if a draw pass
 * or the keeper happens to run afterwards, which is exactly the case a background tab (or a
 * render that ends while the tab is busy) does not hit. So the panel stops feeding it instead:
 * the widget is removed from the node and `node.imgs` is cleared, every pass.
 */
export const NODE_PREVIEW_MODES = ["panel", "compact", "width", "full", "off"];
export const DEFAULT_NODE_PREVIEWS = "panel";

export const NODE_PREVIEW_LABELS = [
    ["panel", "Panel only (no node preview)"],
    ["compact", "Small (side by side)"],
    ["width", "Full width (stacked)"],
    ["full", "Full size (ComfyUI default)"],
    ["off", "Hidden (no preview anywhere)"],
];

/** How big the panel's OWN preview of the composed sheet may be. */
export const PANEL_PREVIEW_SIZES = [
    ["off", "Off"],
    ["small", "Small"],
    ["medium", "Medium"],
    ["full", "Full width"],
];
export const PANEL_PREVIEW_HEIGHTS = { off: 0, small: 240, medium: 420 };
export const DEFAULT_PANEL_PREVIEW = "medium";

/**
 * The websocket event the node's render streams frames on (see `preview_stream.py`).
 *
 * One event for the whole pack, carrying `cell`/`cells`/`step`/`steps` plus `frames` - a list of
 * JPEG data URLs making a looping clip of the cell being denoised - and the `fps` to play them at.
 * The panel filters by node id and sheet name, so two sheets rendering at once each show their own.
 */
export const LIVE_PREVIEW_EVENT = "h3_sheet_preview";
//: The streamed clip never grows past this on screen, however big the node is: it is a look at
//: the run, not the deliverable (the finished sheet is shown at the panel-preview size).
export const LIVE_PREVIEW_MAX_HEIGHT = 220;
//: Playback rate bounds for a streamed clip, in case a payload carries a silly one.
export const LIVE_FPS_RANGE = [1, 30];
//: What the strip's re-roll button does. A stream carries `whole_sheet` when its one clip IS the
//: sheet (the draft pass): there is no cell to re-roll and the seed that decides it is the node's
//: own, so the button is disabled and says what to do instead of failing on a cell id.
export const LIVE_RETRY_TITLE = "Stop the run and render this cell again with a new seed";
export const LIVE_RETRY_WHOLE_SHEET_TITLE =
    "A draft pass renders the whole sheet in one clip - change the seed knob and queue again to re-roll it";

/**
 * The resolution control's choices, and which one the node's sizes currently are.
 *
 * The backend owns the numbers (``presets.resolution_list`` -> ``sheet_spec.RESOLUTION_CHOICES``):
 * one choice sets TWO sizes - the sheet canvas a one-pass render draws and the cell size a
 * per-cell render uses. The presets deliberately do not touch either (see ``presets.py``), so
 * this control is the only thing that moves a size, and a size typed by hand in the Settings tab
 * simply reads as Custom.
 *
 * ``RESOLUTION_FALLBACK`` is the copy a standalone panel falls back to, so the chips still work
 * before the presets route answers (and in the jsdom tests, which have no backend at all).
 */
export const RESOLUTION_FALLBACK = [
    { key: "1080p", label: "1080p", sheetShortEdge: 1088, cellShortEdge: 1024,
      hint: "a 3:2 sheet renders 1632x1088 (~1.8 MP, ~3.5k tokens): the 16 GB tier" },
    { key: "1440p", label: "1440p", sheetShortEdge: 1440, cellShortEdge: 1024,
      hint: "a 3:2 sheet renders 2160x1440 (~3.1 MP, ~6k tokens): comfortable at 24 GB" },
    { key: "4k", label: "4K", sheetShortEdge: 2176, cellShortEdge: 2048,
      hint: "a 3:2 sheet renders 3264x2176 (~7.1 MP, ~14k tokens): the 32 GB tier" },
];

/** The chips' table: the backend's when it has answered, the panel's own copy otherwise. */
export function resolutionChoices(state) {
    const list = Array.isArray(state?.resolutions) ? state.resolutions : [];
    return list.filter((entry) => entry && entry.key).length ? list : RESOLUTION_FALLBACK;
}

/** The recorded choice (``"4k"``), or ``""`` for a hand-set size. */
export function resolution(state) {
    return String(state?.resolution ?? state?.render?.resolution ?? "").trim().toLowerCase();
}

/**
 * Which chip is active: the pair the node's widgets actually hold.
 *
 * Derived from the widgets rather than from a remembered id on purpose - the widgets are what
 * renders, so editing a size by hand turns the control into Custom immediately instead of leaving
 * a chip lit for a size that is no longer set. The payload's ``resolution`` flag is written from
 * this same answer, which is what lets a one-pass render honour a chosen 4K canvas and fall back
 * to the guidance ceiling for anything nobody chose.
 */
export function resolutionKeyFor(state, widgets) {
    const choices = resolutionChoices(state);
    const sheet = Number(widgets?.sheet_short_edge);
    const cell = Number(widgets?.cell_size);
    const match = choices.find((entry) => Number(entry.sheetShortEdge) === sheet
        && Number(entry.cellShortEdge) === cell);
    return match ? String(match.key) : "";
}

/** ``"1632px sheet · 1024px cells"``, or the Custom reading when nothing matches. */
export function resolutionLabel(state, widgets) {
    const key = resolutionKeyFor(state, widgets);
    const choice = resolutionChoices(state).find((entry) => String(entry.key) === key);
    if (choice) {
        return `${choice.sheetShortEdge}px sheet · ${choice.cellShortEdge}px cells`;
    }
    const sheet = Number(widgets?.sheet_short_edge) || 0;
    const cell = Number(widgets?.cell_size) || 0;
    return `Custom: ${sheet || "?"}px sheet · ${cell || "?"}px cells`;
}

/** The panel's own preview size, defaulting to a medium sheet. */
export function panelPreview(state) {
    const value = String(state?.panelPreview || "").toLowerCase();
    return PANEL_PREVIEW_SIZES.some(([key]) => key === value) ? value : DEFAULT_PANEL_PREVIEW;
}

/**
 * Whether the layout cards wear your own last render, or the drawn arrangement.
 *
 * Off by default: the drawing is the card's INFORMATION - which arrangement, and how many cells -
 * and a photo of the last sheet replaces exactly that. On, a layout you have rendered shows that
 * sheet with a `yours` badge.
 */
export function cardArt(state) {
    return state?.cardArt === true || state?.cardArt === "on";
}

/** The node-preview mode, defaulting to the compact one. */
export function nodePreviews(state) {
    const value = String(state?.nodePreviews || "").toLowerCase();
    return NODE_PREVIEW_MODES.includes(value) ? value : DEFAULT_NODE_PREVIEWS;
}

/**
 * The preview widgets and hosts on a node, as ``{widgets, hosts}``.
 *
 * Both kinds are found: the frontend's own preview widgets (by name - the canvas image one
 * has no element at all, the other two are DOM widgets) and the still-image hosts (by class -
 * they can sit inside any widget's element). Whatever the pack owns is skipped: the panel's
 * own DOM widget is not an output preview.
 */
export function previewParts(node, { skip = [] } = {}) {
    const widgets = [];
    const hosts = [];
    for (const widget of node?.widgets || []) {
        if (!widget || (widget.name && skip.includes(widget.name))) continue;
        const element = widget.element || widget.inputEl || null;
        const host = element?.classList?.contains?.(PREVIEW_HOST_CLASS)
            ? element
            : (element?.querySelector?.(`.${PREVIEW_HOST_CLASS}`) || null);
        const named = PREVIEW_WIDGET_NAMES.includes(widget.name);
        if (!host && !named) continue;
        if (!widgets.includes(widget)) widgets.push(widget);
        if (host && !hosts.includes(host)) hosts.push(host);
    }
    return { widgets, hosts };
}

/**
 * Remove ComfyUI's own preview widgets from a node, and take away what they would draw.
 *
 * The frontend's own remover (`removeCanvasImagePreview`) does the same two things - call the
 * widget's `onRemove` so it can unregister its listeners, then splice it out of `node.widgets` -
 * which is why this is a supported thing to do rather than poking at internals. `node.imgs` is
 * cleared as well: the widget is built FROM it, so leaving it populated is leaving the door open
 * for the next pass of the frontend's preview service to rebuild the widget.
 *
 * Returns how many widgets were removed, so the caller can re-fit the node once.
 */
export function removeNodePreviews(node, { skip = [] } = {}) {
    let removed = 0;
    for (const widget of [...(node?.widgets || [])]) {
        if (!widget || (widget.name && skip.includes(widget.name))) continue;
        if (!PREVIEW_WIDGET_NAMES.includes(widget.name)) continue;
        try {
            widget.onRemove?.();
        } catch (error) {
            // A widget that fails to clean up is still a widget we want gone.
        }
        const index = node.widgets.indexOf(widget);
        if (index >= 0) node.widgets.splice(index, 1);
        removed += 1;
    }
    if (removed) {
        if (Array.isArray(node?.imgs) && node.imgs.length) node.imgs = [];
        if (Array.isArray(node?.animatedImages) && node.animatedImages.length) node.animatedImages = [];
        node.setDirtyCanvas?.(true, true);
        node.graph?.setDirtyCanvas?.(true, true);
    }
    return removed;
}

/**
 * Bound one preview widget's height, the way THIS frontend lays widgets out.
 *
 * ``LGraphNode._arrangeWidgets`` asks every widget for ``computeLayoutSize()`` and hands
 * ``{minHeight, maxHeight}`` to ``distributeSpace`` - and a missing/undefined ``maxHeight``
 * means "unbounded", so that widget absorbs all the height the node has left over. The canvas
 * image preview asks for ``{minHeight: 220}`` with no maximum, which is why a finished sheet
 * was drawn ~900px tall however small the panel was: nothing the pack did - a CSS rule on
 * ``.comfy-img-preview img``, ``options.getMinHeight`` - could reach it, because there is no
 * element and no options hook on that path (``options.getMinHeight`` is only read by the
 * *generic* DOM widget, so the video preview, which defines its own ``computeLayoutSize``,
 * ignored it too). Overriding the widget's own function is the one lever that works for all
 * three kinds; the original is kept, so ``full`` hands the node back exactly what it had.
 */
export function capPreviewWidget(widget, mode, owner = null) {
    if (!widget) return false;
    if (!Object.prototype.hasOwnProperty.call(widget, "_mmxLayoutSize")) {
        widget._mmxLayoutSize = widget.computeLayoutSize || null;
    }
    const original = widget._mmxLayoutSize;
    const wanted = nodePreviews({ nodePreviews: mode });
    // ALSO clamp the DRAW call, not just the layout request.
    //
    // The layout lever above is only as good as the next pass of the frontend's own arranger, and
    // the frontend creates this widget when the sheet image finishes loading - measured on a real
    // node: `computeLayoutSize` still the frontend's `{minHeight:220}`, `computedHeight` 1053, a
    // 2442px node. That is the state a user sees when a render ends while the tab is not being
    // drawn (background tab, another window open, a screenshot taken mid-pass), and no timer can
    // promise otherwise. The draw call cannot be missed: the image IS drawn by it.
    if (!widget._mmxDrawPatched) {
        widget._mmxDrawPatched = true;
        const draw = widget.drawWidget;
        widget.drawWidget = function (ctx, opts) {
            const now = nodePreviews({ nodePreviews: widget._mmxMode || DEFAULT_NODE_PREVIEWS });
            if (now === "panel" || now === "off") return undefined;   // nothing to draw at all
            if (now !== "full") {
                const cap = now === "width" ? previewWidthHeight(this.node, this) : PREVIEW_COMPACT_HEIGHT;
                if (Number(this.computedHeight) !== cap) this.computedHeight = cap;
            }
            return typeof draw === "function" ? draw.apply(this, arguments) : undefined;
        };
    }
    widget._mmxMode = wanted;
    if (wanted === "full") {
        if (original) widget.computeLayoutSize = original;
        else delete widget.computeLayoutSize;
        return true;
    }
    if (wanted === "width") {
        // Recomputed on every call, not frozen at install time: the node is resizable, and a
        // full-width preview has to follow the width it is filling.
        const node = owner || widget.node || null;
        widget.computeLayoutSize = () => {
            const height = previewWidthHeight(node, widget);
            return { minHeight: height, maxHeight: height, minWidth: 1 };
        };
        return true;
    }
    const height = wanted === "off" ? 0 : PREVIEW_COMPACT_HEIGHT;
    widget.computeLayoutSize = () => ({ minHeight: height, maxHeight: height, minWidth: 1 });
    return true;
}

/**
 * The media aspect ratio (width / height) of one preview widget, or 16/9 when unknown.
 *
 * The three kinds hold their media differently, so each is asked the way it can answer:
 * a `video-preview` widget holds a `<video>` (its `videoWidth`/`videoHeight` are the real
 * pixels), the still-image host holds an `<img>` (`naturalWidth`/`naturalHeight`), and the
 * canvas image widget has NO element at all - its media lives on the node as `node.imgs`.
 * A missing answer falls back to 16/9 rather than guessing, and jsdom (no media at all)
 * exercises that path.
 */
export function previewMediaAspect(node, widget) {
    const element = widget?.element || widget?.inputEl || null;
    const video = element?.querySelector?.("video") || null;
    const videoWidth = Number(video?.videoWidth) || 0;
    const videoHeight = Number(video?.videoHeight) || 0;
    if (videoWidth > 0 && videoHeight > 0) return videoWidth / videoHeight;
    const img = element?.querySelector?.("img") || null;
    const naturalWidth = Number(img?.naturalWidth) || 0;
    const naturalHeight = Number(img?.naturalHeight) || 0;
    if (naturalWidth > 0 && naturalHeight > 0) return naturalWidth / naturalHeight;
    const images = node?.imgs || null;
    const still = images?.[Number(node?.imageIndex) || 0] || images?.[0] || null;
    const stillWidth = Number(still?.naturalWidth) || 0;
    const stillHeight = Number(still?.naturalHeight) || 0;
    if (stillWidth > 0 && stillHeight > 0) return stillWidth / stillHeight;
    return 16 / 9;
}

/**
 * How tall one preview must be to fill the node's width (px, clamped to the band).
 *
 * This is what makes full width possible at all. ComfyUI CONTAINS a preview inside the box
 * the layout hands it and never upscales it (`calculateImageGrid` and `renderPreview` both do
 * `min(scaleX, scaleY, 1)`), so the drawn width is decided by the HEIGHT: a 200px-tall box can
 * only ever show a wide sheet ~355px wide, whatever the node's width is. Asking for
 * `width / aspect` makes scaleY the limiting one, i.e. the media lands exactly on the node's
 * width.
 */
export function previewWidthHeight(node, widget) {
    const width = Math.max(80, Number(node?.size?.[0]) || 0);
    const aspect = previewMediaAspect(node, widget) || 16 / 9;
    const height = Math.round(width / aspect) + PREVIEW_WIDTH_SLACK;
    return Math.max(PREVIEW_WIDTH_MIN_HEIGHT, Math.min(PREVIEW_WIDTH_MAX_HEIGHT, height));
}

/** How tall a node preview should be in `mode` - the fit uses this to size the node.
 *
 * `compact` is a fixed number the fit can add up. `width` answers 0 on purpose: its height
 * comes from the aspect and the node's width, so the widget's own `computedHeight` (which the
 * layout just set from our function) is the number the fit should use.
 */
export function previewHeight(mode) {
    return nodePreviews({ nodePreviews: mode }) === "compact" ? PREVIEW_COMPACT_HEIGHT : 0;
}

/**
 * Install the one rule that caps every preview image (idempotent, document-level).
 *
 * The height lives in the rule text, so it is written once when the mode is first applied -
 * and the doubled class out-specifies the frontend's own `.comfy-img-preview img` rule instead
 * of racing it on document order.
 */
export function ensurePreviewRule() {
    if (typeof document === "undefined") return null;
    const existing = document.getElementById?.(PREVIEW_RULE_ID);
    if (existing) return existing;
    const style = document.createElement("style");
    style.id = PREVIEW_RULE_ID;
    style.textContent = [
        `.${PREVIEW_COMPACT_CLASS}.${PREVIEW_COMPACT_CLASS} img {`,
        `  height: ${PREVIEW_COMPACT_HEIGHT}px !important;`,
        "  width: auto !important;",
        "  max-width: 100% !important;",
        "  object-fit: contain !important;",
        "  margin: 0 auto !important;",
        "}",
        // A preview that is a video (or a wrapper around one) is capped the same way, and the
        // host itself cannot grow past the row the pack asked the layout for.
        `.${PREVIEW_COMPACT_CLASS}.${PREVIEW_COMPACT_CLASS} video {`,
        `  height: ${PREVIEW_COMPACT_HEIGHT}px !important;`,
        "  width: auto !important;",
        "  margin: 0 auto !important;",
        "}",
        `.${PREVIEW_COMPACT_CLASS}.${PREVIEW_COMPACT_CLASS} {`,
        `  max-height: ${PREVIEW_COMPACT_HEIGHT + 16}px !important;`,
        "  justify-content: center !important;",
        "}",
    ].join("\n");
    (document.head || document.documentElement)?.append(style);
    return style;
}

/**
 * Size the node's output previews: small and side by side, hidden, or ComfyUI's own way.
 *
 * `compact` caps the height and lets the width follow each image's own aspect ratio, which is
 * what makes two previews (the sheet and the cell sequence) sit next to each other instead of
 * stacking: the frontend's host is a wrapping flex row, so narrower cells simply fit.
 */
export function applyPreviewMode(node, mode, { skip = [] } = {}) {
    const wanted = nodePreviews({ nodePreviews: mode });
    if (wanted === "panel") {
        // Not a size: the widgets go away and the panel shows the sheet (see PANEL_PREVIEW_*).
        removeNodePreviews(node, { skip });
        return { mode: wanted, widgets: 0, hosts: 0 };
    }
    const { widgets, hosts } = previewParts(node, { skip });
    const compact = wanted === "compact";
    if (compact) ensurePreviewRule();
    for (const host of hosts) {
        if (compact) {
            host.classList?.add(PREVIEW_COMPACT_CLASS);
            host.style.display = "";
        } else {
            // `width` deliberately goes through this branch: the host is sized by the layout
            // (which is asking for the height the aspect needs), and the frontend's own
            // `.comfy-img-preview img/video` rules then fill it - `object-fit: contain`
            // letterboxes at worst, and with the right height there is nothing to letterbox.
            host.classList?.remove(PREVIEW_COMPACT_CLASS);
            host.style.display = wanted === "off" ? "none" : "";
        }
    }
    for (const widget of widgets) {
        const element = widget.element || widget.inputEl || null;
        // The layout's own lever, for every kind of preview widget - the DOM options below are
        // only read by the generic DOM widget, and the still image is not a DOM widget at all.
        capPreviewWidget(widget, wanted, node);
        if (wanted === "off") {
            if (widget._mmxPreviewSize === undefined) widget._mmxPreviewSize = widget.computeSize || null;
            element?.classList?.remove?.(PREVIEW_COMPACT_CLASS);
            widget.hidden = true;
            if (widget.options) widget.options.hidden = true;
            widget.computeSize = () => [0, 0];
        } else {
            widget.hidden = false;
            if (compact) element?.classList?.add?.(PREVIEW_COMPACT_CLASS);
            else element?.classList?.remove?.(PREVIEW_COMPACT_CLASS);
            if (widget.options) {
                widget.options.hidden = false;
                // The DOM-widget layout asks the widget how tall it may be: capping it here is
                // what stops ComfyUI giving the preview the node's whole leftover height.
                if (compact) {
                    widget.options.getMinHeight = () => PREVIEW_COMPACT_HEIGHT;
                    widget.options.getMaxHeight = () => PREVIEW_COMPACT_HEIGHT + 8;
                } else {
                    delete widget.options.getMinHeight;
                    delete widget.options.getMaxHeight;
                }
            }
            if (widget._mmxPreviewSize !== undefined) {
                if (widget._mmxPreviewSize) widget.computeSize = widget._mmxPreviewSize;
                else delete widget.computeSize;
                widget._mmxPreviewSize = undefined;
            }
        }
    }
    node?.setDirtyCanvas?.(true, true);
    node?.graph?.setDirtyCanvas?.(true, true);
    return { mode: wanted, widgets: widgets.length, hosts: hosts.length };
}

/**
 * Re-apply the preview caps, and pull back any preview widget the layout has inflated.
 *
 * `applyPreviewMode` runs on mount, on a workflow load, after a run and when the selector
 * changes - but a preview widget can appear AFTER any of those: the frontend adds the canvas
 * image widget when the image finally finishes loading, which on a multi-megabyte sheet PNG is
 * seconds after the run ended. A widget that arrives late is a widget nothing has capped, and an
 * uncapped preview is not just big: its `minHeight` joins the node's layout minimums while its
 * unbounded `maxHeight` also absorbs the free height, so the frontend's `_arrangeWidgets` grows
 * the node and this pack's node fit shrinks it back - every frame, which is the preview that
 * jitters up and down. Enforcing the cap on a light timer closes both: anything new gets the
 * bound, and a height the layout handed back out is written down again.
 *
 * Deliberately cheap and quiet: it only touches a widget whose bound or height is actually
 * wrong, and reports how many it touched so the caller can re-fit the node once.
 */
export function enforcePreviewCaps(node, mode, { skip = [] } = {}) {
    const wanted = nodePreviews({ nodePreviews: mode });
    if (wanted === "panel") {
        return { mode: wanted, changed: removeNodePreviews(node, { skip }) };
    }
    const { widgets } = previewParts(node, { skip });
    if (wanted === "full") return { mode: wanted, changed: 0 };
    let changed = 0;
    for (const widget of widgets) {
        // The height this widget SHOULD have in this mode. `width` recomputes from the node's
        // current width and the media's aspect, so a resize is corrected on the next pass.
        const cap = wanted === "off"
            ? 0
            : (wanted === "width" ? previewWidthHeight(node, widget) : PREVIEW_COMPACT_HEIGHT);
        const before = typeof widget.computeLayoutSize === "function" ? widget.computeLayoutSize() : null;
        capPreviewWidget(widget, wanted, node);
        const after = typeof widget.computeLayoutSize === "function" ? widget.computeLayoutSize() : null;
        // "Changed" drives the node re-fit, so it has to answer both questions: is the bound
        // wrong (`after !== cap`, e.g. this mode's height moved with a resize), and did THIS
        // pass install it (`before !== after`, e.g. a widget the frontend created late)? Only
        // the second one is true on the pass that caps a fresh widget, and only the first is
        // true after a resize - both have to re-sit the node, and neither fires when the
        // preview is already exactly as this mode wants it.
        if (
            !before || !after
            || after.minHeight !== cap || after.maxHeight !== cap
            || before.minHeight !== after.minHeight || before.maxHeight !== after.maxHeight
        ) {
            changed += 1;
        }
        if (wanted === "off") {
            if (widget.hidden !== true) {
                widget.hidden = true;
                if (widget.options) widget.options.hidden = true;
                changed += 1;
            }
            continue;
        }
        // A height above what this mode asked for means something re-arranged afterwards.
        if (Number(widget.computedHeight) > cap + 4) {
            widget.computedHeight = cap;
            changed += 1;
        }
    }
    if (changed) {
        node?.setDirtyCanvas?.(true, true);
        node?.graph?.setDirtyCanvas?.(true, true);
    }
    return { mode: wanted, changed };
}

/**
 * Should the node hide its own knob rows and let the panel draw them?
 *
 * The frontend lays a native widget out one per row, full width (there is no
 * column-span API), so the 23 knobs cost ~500px of node height that the panel can
 * spend in three columns instead. Default: yes - the Settings tab shows every knob,
 * with the same values, and the toggle in that tab brings the rows back.
 */
export function compactKnobs(state) {
    return state?.compactKnobs !== false;
}

/** Auto-refresh (the background poll of the sheet folder) - off unless a workflow says so. */
export function autoRefresh(state) {
    return state?.autoRefresh === true;
}

/**
 * Should the Results tab follow the board a suite render is currently drawing?
 *
 * A suite is one queue and several sheets, and the sheets render one after another: the board
 * being drawn is the only one with anything to watch, so the panel switches to it (see
 * setLivePreview) unless the user pinned a board instead. On by default - a chip click is what
 * turns it off, and the switch beside the row turns it back on.
 */
export function followBoard(state) {
    return state?.followBoard !== false;
}

/** The value the node's widget should get from a panel control. */
export function knobValue(knob, raw) {
    if (!knob) return raw;
    if (knob.kind === "toggle") return Boolean(raw);
    if (knob.kind === "number") {
        // A control clamps, the node would reject: a number input can be typed into
        // ("4000" in a 256..2048 box), and a cleared box must keep the default rather
        // than collapse to 0 (Number("") is 0, not NaN).
        const text = typeof raw === "string" ? raw.trim() : raw;
        if (text === "" || text == null) return Number(knob.default ?? 0);
        const number = Number(text);
        if (!Number.isFinite(number)) return Number(knob.default ?? 0);
        const min = Number.isFinite(knob.min) ? knob.min : -Infinity;
        const max = Number.isFinite(knob.max) ? knob.max : Infinity;
        return Math.min(max, Math.max(min, number));
    }
    return raw == null ? "" : String(raw);
}

/**
 * Every knob with the value it currently has on the node.
 *
 * The node is the source of truth (a workflow may carry anything), so a knob the
 * wiring could not read falls back to its schema default rather than showing blank.
 */
export function knobValues(knobs = [], values = {}) {
    return (knobs || []).map((knob) => ({
        ...knob,
        value: Object.prototype.hasOwnProperty.call(values || {}, knob.name) && values[knob.name] !== undefined
            ? values[knob.name]
            : knob.default,
    }));
}

export function cellContinuity(cell) {
    const value = String(cell?.continuity ?? "").trim().toLowerCase();
    return CELL_CONTINUITY_MODES.includes(value) ? value : "inherit";
}

/**
 * Does this cell continue from its predecessor, and with how many frames?
 *
 * Mirrors ``sheet_spec.continuity_plan`` so the panel can label a cell before the
 * backend is asked: the first cell never continues, a cell no longer than the hand-over
 * cannot (the guide would fill it), and ``auto`` only chains where the camera distance
 * already matches. The node and the report remain the authority.
 */
export function cellContinues(state, index) {
    const cell = state?.cells?.[index];
    if (!cell || index <= 0 || cell.enabled === false) return 0;
    const mode = cellContinuity(cell) === "inherit" ? continuity(state) : cellContinuity(cell);
    if (mode === "off") return 0;
    if (mode === "auto") {
        const previous = [...(state?.cells || [])].slice(0, index).reverse()
            .find((item) => item && item.enabled !== false);
        const mine = framingDistance(cell.view);
        if (!previous || !mine || mine !== framingDistance(previous.view)) return 0;
    }
    const frames = Number(cell.frames ?? state?.framesPerCell ?? 22) || 22;
    return frames > CONTINUITY_FRAMES ? CONTINUITY_FRAMES : 0;
}

/**
 * Is this cell held back by 'cont: auto' because its framing changed?
 *
 * The reason the panel can answer "why is this cell not continuing?" without asking the
 * backend: the hand-over carries the previous camera distance, so a new distance is a
 * deliberate break rather than a missed one.
 */
export function framingBreak(state, index) {
    const cell = state?.cells?.[index];
    if (!cell || index <= 0 || cell.enabled === false) return false;
    const mode = cellContinuity(cell) === "inherit" ? continuity(state) : cellContinuity(cell);
    if (mode !== "auto") return false;
    const previous = [...(state?.cells || [])].slice(0, index).reverse()
        .find((item) => item && item.enabled !== false);
    const mine = framingDistance(cell.view);
    return Boolean(previous) && (!mine || mine !== framingDistance(previous.view));
}

//: Hand-painted blur area. Strokes are stored NORMALIZED (0-1) on the reference, so the
//: painting is resolution-independent, survives a save, and stays editable. ``radius`` is
//: a fraction of the image's short edge, which is what the engine expects.
export const DEFAULT_PAINT_RADIUS = 0.03;
export const MIN_PAINT_RADIUS = 0.004;
export const MAX_PAINT_RADIUS = 0.12;

/** Turn a pointer event into a normalized point on the painted image (clamped to it). */
export function paintPoint(rect, clientX, clientY) {
    const width = rect?.width || 1;
    const height = rect?.height || 1;
    const x = (clientX - (rect?.left || 0)) / width;
    const y = (clientY - (rect?.top || 0)) / height;
    return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
}

/** The stroke's points in canvas pixels, for drawing the overlay. */
export function paintPath(stroke, width, height) {
    return (stroke?.points || []).map(([x, y]) => [x * width, y * height]);
}

/** How the tile's blur button reads when there is painting on the reference. */
export function blurButtonLabel(slot) {
    const mode = blurMode(slot);
    return Array.isArray(slot?.blurPaint) && slot.blurPaint.length
        ? `${BLUR_LABELS[mode]} + paint`
        : BLUR_LABELS[mode];
}

/** Slider position (1-30) for a brush radius, and back - the slider is easier to use. */
export function radiusToSlider(radius) {
    const span = MAX_PAINT_RADIUS - MIN_PAINT_RADIUS;
    const value = Math.min(MAX_PAINT_RADIUS, Math.max(MIN_PAINT_RADIUS, Number(radius) || DEFAULT_PAINT_RADIUS));
    return Math.round(1 + ((value - MIN_PAINT_RADIUS) / span) * 29);
}

export function sliderToRadius(position) {
    const span = MAX_PAINT_RADIUS - MIN_PAINT_RADIUS;
    const value = Math.min(30, Math.max(1, Math.round(Number(position) || 1)));
    return MIN_PAINT_RADIUS + ((value - 1) / 29) * span;
}

//: The references are ONE grid, sorted pictures -> video -> audio. The prompt tags
//: stay per kind (<Picture 2>, <Video 1>, <Audio 1>), so the order here is display
//: order only - it is what the user asked for: "pictures first, then video, audio".
export const SORTED_KINDS = ["image", "video", "audio"];

//: The reference area is a fixed size; the tiles take whatever height fits inside it
//: (see ``fitTileLayout``), so nothing is letterboxed and nothing scrolls.
export const REF_SECTION = { height: 178, width: 640, gap: 6, roleHeight: 24, minTile: 44 };

//: The narrowest a reference tile may get, as width / height: a phone portrait (9:16).
//: Anything narrower squeezes the tile's own chrome (see `clampAspect`).
//: The ceiling is a cinemascope clip (2.6:1); beyond that a single reference would eat
//: the whole row.
export const MIN_TILE_ASPECT = 9 / 16;
export const MAX_TILE_ASPECT = 2.6;

//: Node geometry measured on the live frontend: the DOM widget starts under the
//: node header (`widget.y`, 86px) and the node keeps 20px of its own below the panel
//: (measured: node height - widget.y - panel clientHeight). Kept as a measurement because
//: the panel fills whatever box it is given - nothing in this pack sizes the NODE any more
//: (see `enforceWidgetWidth`): the node keeps the size the user gave it, and the active pane
//: scrolls when its content needs more room than that.
export const PANEL_METRICS = { headerTop: 86, bottomInset: 20 };

//: The node's own inset around its DOM widget: a 880px node hosts an 860px panel.
//: Measured on the live frontend at several sizes, so it is exact - and it is the whole
//: invariant `enforceWidgetWidth` restores.
export const WIDGET_INSET = 20;

/** Put the panel's DOM-widget wrapper back to the node's own width.
 *
 * This frontend re-measures a DOM widget on selection and can write a SQUEEZED inline width
 * onto its wrapper (a 880px node's wrapper at ``width: 345px``), which compresses the whole
 * panel - every card, and the Browse overlay with it, because that overlay is only ever as
 * wide as the panel (``position: absolute; inset: 0``). The panel is not the thing that is
 * wrong, so nothing inside it can fix this: the wrapper's own width has to be put back.
 *
 * Grow only: a wrapper wider than the node is left alone (that is the frontend's layout
 * doing something deliberate), and the write happens only when the number is actually wrong,
 * so calling it every frame costs one parseFloat.
 *
 * The node's own size is never touched here or anywhere else in this pack: a panel that
 * resized its node on a tab switch or a refresh is exactly what users complained about.
 * This only ever puts the DOM widget's box back inside the size the node already has.
 */
export function enforceWidgetWidth(node, inset = WIDGET_INSET) {
    const element = node?._mmxSheet?.widget?.element;
    if (!element || !node.graph) return false;
    // The frontend can REPLACE the wrapper, so it is re-located every call instead of
    // remembered; the element itself is the one thing that stays put.
    const wrapper = element.closest?.(".dom-widget") || element.parentElement;
    if (!wrapper) return false;
    const want = panelWidthFor(node, inset);
    const current = Number.parseFloat(wrapper.style?.width || "") || 0;
    const capped = Number.parseFloat(wrapper.style?.maxWidth || "") || 0;
    if (current >= want && (!capped || capped >= want)) return false;
    wrapper.style.width = `${want}px`;
    wrapper.style.maxWidth = `${want}px`;
    return true;
}

/**
 * The size a NEW node opens at.
 *
 * The panel is two equal columns (see .mmx-stage/.mmx-col) plus a 32px rail, so the width is
 * chosen to give each column ~505px - enough for the sheet grid, the glyph rows and the tile
 * wall without horizontal scrolling - and the height for the sheet plus a short scroll of
 * vocabulary. It is applied once, when a node is created: a workflow that saved a size keeps
 * it, and nothing in the pack resizes the node afterwards (see layoutChanged).
 */
export const NODE_WIDTH = 1080;
export const NODE_HEIGHT = 700;

/**
 * The size the node may not go below.
 *
 * 760x620 is the smallest node the two-column design still works at. The panel stacks its columns
 * below 640px (2 x the 240px floor plus the rail and the gaps - see the container query in
 * PANEL_CSS), so the narrow floor has to sit above that with room to spare: 760 less the node's
 * 20px inset is a 740px panel, which is 2 x 356px columns - the ~350px a column needs for the
 * tile wall and the glyph rows. (At 700 the columns were 306px and the tiles 52px wide: legal, and
 * cramped enough that a hand-dragged node looks broken rather than small.) The height floor is the
 * sheet grid (a hero arrangement is five boxes) plus the tools under it. A drag that tries to go
 * below this is clamped in the wiring's `onResize`; nothing else in the pack touches the node's
 * size, and a workflow that saved something smaller keeps it (the panel stacks and scrolls).
 */
export const NODE_MIN_WIDTH = 760;
export const NODE_MIN_HEIGHT = 620;

/** The width the panel may occupy: the node's own width less its inset. */
export function panelWidthFor(node, inset = WIDGET_INSET) {
    return Math.max(240, Math.round(Number(node?.size?.[0]) || 0) - inset);
}

/** The reference group for a media kind. */
export function groupForKind(kind) {
    return REF_GROUPS.find((group) => group.kind === kind) || null;
}

/** Which group a file belongs to, decided by its extension (drop routing).
 *  Accepts a File (from a drop / picker) or a plain path (from Browse). */
export function groupForFile(file) {
    const probe = typeof file === "string" ? { name: file } : file;
    for (const kind of SORTED_KINDS) {
        const group = groupForKind(kind);
        if (group && fileMatchesGroup(probe, group)) return group;
    }
    return null;
}

/** H3's own names for the reference kinds (``<Picture 2>`` and friends).
 *
 *  Module level on purpose: the Cells tab's background row is built before the panel's own
 *  constants run, so it cannot borrow a helper defined further down the interface body.
 */
export const REF_TAG_LABEL = { image: "Picture", video: "Video", audio: "Audio" };

/** The H3 tag for one wired reference (``refTagLabel("image", 2)`` -> ``"<Picture 2>"``). */
export function refTagLabel(kind, ordinal) {
    const label = REF_TAG_LABEL[kind] || "Reference";
    return `<${label} ${ordinal}>`;
}

/**
 * Every filled reference in display order: pictures, then video, then audio, each
 * keeping its own ``<Picture N>`` numbering.
 */
export function mediaSlots(refs) {
    const slots = [];
    for (const kind of SORTED_KINDS) {
        const group = groupForKind(kind);
        if (!group) continue;
        let ordinal = 0;
        (refs?.[group.key] || []).forEach((slot, index) => {
            if (!slot?.file) return;
            // Only a reference the run actually sends earns a <Picture N> number: an
            // unchecked tile must not shift the numbers of the tiles after it, because
            // the prompt counts the references the render wires, not the tiles shown.
            const active = slot.enabled !== false;
            if (active) ordinal += 1;
            slots.push({ group, index, ordinal: active ? ordinal : null, active });
        });
    }
    return slots;
}

/**
 * Biggest tile height that keeps every tile inside a fixed box.
 *
 * Tiles keep the media's own shape, so the box is filled by *choosing a height* for
 * the given widths. One row is tried first (the tallest tiles); if the row is too
 * wide the tiles wrap, which costs vertical space, so the height comes down until the
 * whole set fits both ways. That is what stops a reference being letterboxed inside a
 * wider cell - and why the box never needs to scroll.
 */
export function fitTileLayout(aspects, options = {}) {
    const { width = REF_SECTION.width, height = REF_SECTION.height, gap = REF_SECTION.gap, minTile = REF_SECTION.minTile } = options;
    const list = (aspects || []).map((value) => (Number.isFinite(value) && value > 0 ? value : 1));
    const count = list.length;
    if (!count) return { tileHeight: height, perRow: 0, rows: 0 };
    const sorted = [...list].sort((a, b) => b - a);
    let best = { tileHeight: 0, perRow: count, rows: 1 };
    for (let rows = 1; rows <= count; rows += 1) {
        const perRow = Math.ceil(count / rows);
        const widest = sorted.slice(0, perRow).reduce((total, value) => total + value, 0);
        const usable = width - gap * (perRow + 1);
        const across = usable > 0 ? usable / widest : 0;
        // Wrapping costs a gap per extra row, so a second row halves the height budget.
        const down = (height - gap * (rows - 1)) / rows;
        const tileHeight = Math.max(minTile, Math.min(height, across, down));
        if (tileHeight > best.tileHeight) best = { tileHeight, perRow, rows };
    }
    return best;
}

/** The aspect a tile should take: the media's own shape, clamped to sane extremes.
 *
 * A picture and an audio reference are both square. The audio tile used to be 5:2 - a wide
 * letterbox with one note glyph floating in the middle of it - which read as a different
 * kind of object next to the square pictures, stretched the grid, and put the filename in a
 * strip that was mostly empty. Only video keeps a wide box, because only video has a shape
 * of its own to keep (and it is the media's, not ours: a measured thumbnail always wins).
 */
export function tileAspect(group, file, aspects) {
    const known = aspects?.get?.(file);
    const ratio = clampAspect(known);
    if (ratio) return ratio;
    return group?.kind === "video" ? 16 / 9 : 1;
}

// --------------------------------------------------------------------------- //
// styles (class based, so the panel matches the ComfyUI / Easy-Media look)
// --------------------------------------------------------------------------- //

//: The pictures the Cells tab draws instead of words. One sprite of marks (a framing box + what
//: fills it), then a table from each view / expression key to its mark, so 20 framings need twelve
//: drawings rather than twenty - an angle is the same figure tilted, and an expression is the same
//: head with a different mouth. A mark is referenced by id, so a glyph is 3 lines of DOM.
export const GLYPH_SPRITE = `
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="mk-head" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><ellipse cx="16" cy="16" rx="7.5" ry="9.5" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="13" cy="14" r="1" fill="currentColor"/><circle cx="19" cy="14" r="1" fill="currentColor"/><path d="M14 20.5c1.4 1 2.6 1 4 0" stroke="currentColor" stroke-width="1" fill="none"/></symbol>
<symbol id="mk-bust" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="12" r="4.6" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8.5 28c1.5-6 4.5-9 7.5-9s6 3 7.5 9" stroke="currentColor" stroke-width="1.3" fill="none"/></symbol>
<symbol id="mk-figure" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="7.5" r="2.8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M16 10.4v8.6M11.7 13.6h8.6M16 19l-2.8 8M16 19l2.8 8" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linecap="round"/></symbol>
<symbol id="mk-figure-side" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="18" cy="7.5" r="2.8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M17 10.4v8.6M17 13.6h-3.6M17 19l-2.4 8M17 19l2.4 8" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linecap="round"/></symbol>
<symbol id="mk-figure-back" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="7.5" r="2.8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M16 10.4v8.6M12.4 12.8h7.2M16 19l-2.8 8M16 19l2.8 8" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linecap="round"/><path d="M13.4 16.6h5.2" stroke="currentColor" stroke-width="1" opacity=".7"/></symbol>
<symbol id="mk-head-side" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M12 26c-2-2-3-5-3-9 0-5 3-9 7.5-9S23 12 23 16c0 3-1.4 5-3.6 6.4l.4 3.6Z" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="19" cy="15" r="1" fill="currentColor"/></symbol>
<symbol id="mk-head-back" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M11 27c-1.6-2-2.6-5-2.6-9 0-5 3.4-9 7.6-9s7.6 4 7.6 9c0 4-1 7-2.6 9Z" fill="none" stroke="currentColor" stroke-width="1.3"/></symbol>
<symbol id="mk-eyes" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M7 16c2.5-4 5-4 7 0-2 4-4.5 4-7 0Z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M18 16c2.5-4 5-4 7 0-2 4-4.5 4-7 0Z" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="10.5" cy="16" r="1.1" fill="currentColor"/><circle cx="21.5" cy="16" r="1.1" fill="currentColor"/></symbol>
<symbol id="mk-mouth" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M9 16c3.5-4.5 10.5-4.5 14 0-3.5 4.5-10.5 4.5-14 0Z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M10.5 16h11" stroke="currentColor" stroke-width="1" opacity=".8"/></symbol>
<symbol id="mk-hands" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M11 21V10.5a1.6 1.6 0 013.2 0V16m0-7.5a1.6 1.6 0 013.2 0V16m0-6a1.6 1.6 0 013.2 0v9c0 3-2 5-5 5h-2c-3 0-5-2-4.6-5Z" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
<symbol id="mk-feet" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M11 9v9c0 5 1 7 4 7 2 0 3-2 3-6V9c0-3-7-3-7 0Z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M21 11v7c0 4 .8 5.5 2.4 5.5 1.3 0 2-1.6 2-4.6V11c0-2.4-4.4-2.4-4.4 0Z" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
<symbol id="mk-legs" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M12 8h8l-1.4 16h-2.2L16 15l-.4 9h-2.2Z" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
<symbol id="mk-torso" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M11 12c0-4 2.2-6 5-6s5 2 5 6v7c0 3-2 4-5 4s-5-1-5-4Z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M13 16h6" stroke="currentColor" stroke-width="1"/></symbol>
<symbol id="mk-lower" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><path d="M10 10c0 6 1.5 12 6 12s6-6 6-12" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M13 12v8M19 12v8" stroke="currentColor" stroke-width="1"/></symbol>
<symbol id="mk-rear" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="12.5" cy="16" r="4.6" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="21" cy="16" r="4.6" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
<symbol id="ex-neutral" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="13" cy="14.5" r="1" fill="currentColor"/><circle cx="19" cy="14.5" r="1" fill="currentColor"/><path d="M13.6 20h4.8" stroke="currentColor" stroke-width="1.1"/></symbol>
<symbol id="ex-shut" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M11 15c1.4-1.6 2.6-1.6 4 0M17 15c1.4-1.6 2.6-1.6 4 0" stroke="currentColor" stroke-width="1.1" fill="none"/><path d="M13.6 20.4h4.8" stroke="currentColor" stroke-width="1.1"/></symbol>
<symbol id="ex-smile" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="13" cy="14.5" r="1" fill="currentColor"/><circle cx="19" cy="14.5" r="1" fill="currentColor"/><path d="M12.6 19c1.8 2.6 5 2.6 6.8 0" stroke="currentColor" stroke-width="1.2" fill="none"/></symbol>
<symbol id="ex-frown" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="13" cy="15" r="1" fill="currentColor"/><circle cx="19" cy="15" r="1" fill="currentColor"/><path d="M12.6 21.4c1.8-2.6 5-2.6 6.8 0" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M10.6 12.4l3 .8M21.4 12.4l-3 .8" stroke="currentColor" stroke-width="1"/></symbol>
<symbol id="ex-cry" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M11 15c1.4-1.6 2.6-1.6 4 0M17 15c1.4-1.6 2.6-1.6 4 0" stroke="currentColor" stroke-width="1.1" fill="none"/><path d="M12.6 21.4c1.8-2.6 5-2.6 6.8 0" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M12 17.4v2.4M20 17.4v2.4" stroke="currentColor" stroke-width="1" opacity=".8"/></symbol>
<symbol id="ex-open" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="13" cy="14.5" r="1" fill="currentColor"/><circle cx="19" cy="14.5" r="1" fill="currentColor"/><ellipse cx="16" cy="20.6" rx="2.6" ry="2" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
<symbol id="ex-wink" viewBox="0 0 32 32"><rect x="3" y="2" width="26" height="28" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><circle cx="16" cy="16" r="8.4" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M11 15c1.4-1.6 2.6-1.6 4 0" stroke="currentColor" stroke-width="1.1" fill="none"/><circle cx="19" cy="14.5" r="1" fill="currentColor"/><path d="M13 20.4c1.8 1 4 1 6 0" stroke="currentColor" stroke-width="1.2" fill="none"/></symbol>
</defs></svg>
`;

//: View key -> the mark that draws it. Angles reuse the figure; the detail crops get their own.
export const VIEW_MARKS = {
    face: "mk-head",
    portrait: "mk-bust",
    front: "mk-figure",
    profile: "mk-figure-side",
    back: "mk-figure-back",
    "three-quarter": "mk-figure",
    "three-quarter-back": "mk-figure-back",
    "high-angle": "mk-figure",
    "low-angle": "mk-figure",
    "over-shoulder": "mk-figure-back",
    "face-profile": "mk-head-side",
    "head-back": "mk-head-back",
    hands: "mk-hands",
    eyes: "mk-eyes",
    legs: "mk-legs",
    mouth: "mk-mouth",
    feet: "mk-feet",
    breasts: "mk-torso",
    groin: "mk-lower",
    butt: "mk-rear",
};

//: Expression key -> the face that draws it. Six faces cover sixteen words: the label under the
//: glyph is the exact word, so nothing is invented and nothing is lost.
export const EXPRESSION_MARKS = {
    neutral: "ex-neutral",
    smile: "ex-smile",
    smirk: "ex-smile",
    laugh: "ex-smile",
    frown: "ex-frown",
    anger: "ex-frown",
    fear: "ex-frown",
    pout: "ex-frown",
    surprised: "ex-open",
    embarrassed: "ex-open",
    "lips-parted": "ex-open",
    "tongue-out": "ex-open",
    ahego: "ex-open",
    crying: "ex-cry",
    "closed-eyes": "ex-shut",
    wink: "ex-wink",
    disgust: "ex-frown",
    determined: "ex-frown",
    pain: "ex-frown",
    aroused: "ex-open",
    pleasure: "ex-open",
    orgasm: "ex-open",
};

export const PANEL_CSS = `
.mmx-sheet {
  /* The panel is the query CONTAINER (see the stack rule near .mmx-shell): a container cannot
     answer its own query, so the width the layout reacts to has to be measured one level up.
     position: relative is the other half of that job: the overlay (a preview, a folder browser) is
     inset:0 inside the panel, and it must cover the PANEL - in the node it used to resolve against
     ComfyUI's fixed wrapper and outside one (the harness) against the whole page. */
  container-type: inline-size;
  position: relative;
  --mmx-bg: var(--comfy-menu-bg, #1b1b1f);
  --mmx-card: var(--comfy-input-bg, #232329);
  --mmx-card-2: var(--comfy-input-bg, #17171c);
  --mmx-line: var(--border-color, #3a3a44);
  --mmx-fg: var(--fg-color, #e6e6ee);
  --mmx-muted: var(--descrip-text, #9aa0ae);
  /* Proposal B's accent, pinned rather than taken from the theme: the render button, the lit chips
     and the live tab are the one colour the mockup uses to mean "this is the action", and
     ComfyUI's own primary is blue (the proposal's blue, #7fd1ff, is its SECOND colour - the ring
     on a picked frame). Read it as: orange for "do it", blue for "you chose this". */
  --mmx-accent: #ffb347;
  /* What reads on the accent: dark, like the proposal's own primary button ("color: #17171c"). */
  --mmx-accent-ink: #17171c;
  --mmx-accent-soft: rgba(255, 179, 71, .22);
  /* The Cells tab's group names: the same yellow-orange as the Build cells outline. */
  --mmx-tick: #ffb347;
  --mmx-danger: #e05561;
  width: 100%; height: 100%; box-sizing: border-box; overflow: auto;
  /* Column layout so the active pane can claim the leftover height (see .mmx-pane). */
  display: flex; flex-direction: column;
  padding: 6px; font-size: 11px; line-height: 1.35;
  background: var(--mmx-bg); color: var(--mmx-fg);
  font-family: ui-sans-serif, system-ui, "Segoe UI", sans-serif;
}
.mmx-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mmx-spacer { flex: 1 1 auto; }
.mmx-title { font-size: 12px; font-weight: 650; }
.mmx-muted { color: var(--mmx-muted); font-size: 10px; }
/* The preset bar sits directly under the title row: whole-node settings, before the
   references and the cells, because they decide what the render is going to cost. */
.mmx-presets {
  gap: 6px;
  padding: 5px 6px;
  border: 1px solid var(--mmx-line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}
.mmx-presets select { flex: 0 0 auto; min-width: 210px; font-size: 11px; }
.mmx-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--mmx-card); color: var(--mmx-fg);
  border: 1px solid var(--mmx-line); border-radius: 6px;
  padding: 3px 8px; cursor: pointer; font-size: 11px; line-height: 1.2;
}
.mmx-btn:hover { border-color: var(--mmx-accent); }
.mmx-btn--primary { background: var(--mmx-accent); border-color: var(--mmx-accent); color: var(--mmx-accent-ink); }
.mmx-btn--danger { color: var(--mmx-danger); }
/* The one action that creates the render (Cells -> Build cells). A yellow-orange outline so
   it reads as "this is the button" without shouting like a filled primary button would.
   Tint/foreground are local variables: the accent stays the blue the rest of the panel uses. */
.mmx-btn--build {
  border: 1px solid var(--mmx-build, #ff9f2e);
  color: var(--mmx-build, #ff9f2e);
  font-weight: 600;
  box-shadow: 0 0 0 1px rgba(255, 159, 46, 0.25);
}
.mmx-btn--build:hover {
  border-color: var(--mmx-build, #ff9f2e);
  background: rgba(255, 159, 46, 0.16);
  color: var(--mmx-build-bright, #ffb95e);
}
.mmx-btn--build:active { background: rgba(255, 159, 46, 0.28); }
/* An SVG icon: block-level so it carries no text baseline, and centred by whatever flex
   container holds it. These replaced font glyphs and an emoji, which came with their own
   bearings and sat off-centre inside their buttons with a lot of empty box around them. */
.mmx-icon { display: block; flex: 0 0 auto; }
/* Icon buttons are square and sized to the icon: no text baseline, no padding to balance. */
.mmx-btn--icon {
  padding: 0; width: 20px; height: 20px; min-height: 0; justify-content: center;
}
.mmx-input, .mmx-select {
  font-size: 10px; background: var(--mmx-card-2); color: var(--mmx-fg);
  border: 1px solid var(--mmx-line); border-radius: 6px; padding: 2px 5px;
}
.mmx-status { min-height: 14px; font-size: 10px; color: var(--mmx-muted); margin: 4px 0; }
/* The frame, from proposal B - three regions, side by side:
     [ icon rail ] [ the stage: the big preview + its tools + the live strip ] [ the controls ]
   The same six tabs are still here; they are simply no longer a sentence long. The CONTROL
   COLUMN is what the first pass got wrong: the sheet cards, the sizes and the references are
   not full-width rows above the panel, they are the right-hand column, and they stay there
   while the stage changes with the tab. */
.mmx-shell {
  display: flex; gap: 8px; align-items: stretch; flex: 1 1 auto; min-height: 0;
}
/* Two EQUAL columns, on every tab that has them: the stage and the control column are halves of
   the panel. An unequal pair (a wide stage, a 336px strip) made the eye read the right column as
   an afterthought, and which half you got depended on the tab. */
.mmx-stage {
  flex: 1 1 0; display: flex; flex-direction: column;
  /* A floor, so neither half can be starved to nothing by the other's content. */
  min-width: 240px;
}
/* The stage's subject: the sheet being built, drawn with the arrangement the picked layout gives.
   The panel grid, the gaps and the labels are the same vocabulary the preset cards use, at the
   size the stage allows - which is what makes B's stage read as "this is your sheet". */
.mmx-stage__sheet {
  flex: 1 1 auto; min-height: 240px; display: grid; gap: 6px;
  padding: 6px; background: #0b0b10; border: 1px solid var(--mmx-line); border-radius: 8px;
}
.mmx-stage__sheet.is-one { grid-template-columns: 1fr; }
.mmx-stage__sheet.is-hero { grid-template-columns: 1.35fr 1fr 1fr; grid-template-rows: 1fr 1fr; }
.mmx-stage__sheet.is-hero > .mmx-cellbox:first-child { grid-row: span 2; }
.mmx-stage__sheet.is-grid6 { grid-template-columns: repeat(3, 1fr); grid-template-rows: 1fr 1fr; }
.mmx-stage__sheet.is-grid4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.mmx-stage__sheet.is-row { grid-template-columns: repeat(3, 1fr); }
.mmx-stage__caption {
  display: flex; gap: 6px; align-items: baseline; min-height: 14px;
  font-size: 10px; color: var(--mmx-muted); font-variant-numeric: tabular-nums;
}
.mmx-stage__caption.is-live { color: var(--mmx-accent); }
.mmx-cellbox {
  position: relative; min-height: 54px; border-radius: 6px; overflow: hidden;
  background: #191922; border: 1px solid var(--mmx-line);
  display: flex; flex-direction: column; justify-content: flex-end; gap: 2px; padding: 5px;
}
.mmx-cellbox__view { font-size: 10px; font-weight: 600; color: var(--mmx-fg); }
.mmx-cellbox__meta { font-size: 9px; color: var(--mmx-muted); font-variant-numeric: tabular-nums; }
.mmx-cellbox.is-empty { background: #14141b; align-items: center; justify-content: center; }
.mmx-cellbox.is-empty .mmx-cellbox__view { color: var(--mmx-muted); font-size: 14px; }
.mmx-cellbox.has-frames { border-color: var(--mmx-tick); }
/* A panel you can put something on: the boxes are the sheet's drop targets (see wireCellDrop). */
.mmx-cellbox.is-drop {
  border-color: var(--mmx-accent); background-color: var(--mmx-accent-soft);
  box-shadow: 0 0 0 2px rgba(79, 140, 255, 0.35) inset;
}
/* A panel that asks for something the ticks do not: marked, and one click from going back. */
.mmx-cellbox.is-custom { border-color: var(--mmx-tick); border-style: dashed; }
.mmx-cellbox__reset {
  position: absolute; top: 3px; right: 3px; width: 16px; height: 16px; min-height: 0;
  padding: 0; justify-content: center; border-radius: 4px; font-size: 11px; line-height: 1;
  background: rgba(0, 0, 0, 0.45); border-color: var(--mmx-line); color: var(--mmx-muted);
}
.mmx-cellbox__reset:hover { color: var(--mmx-fg); border-color: var(--mmx-tick); }
/* The control that is in hand: a drag source, so the wall shows what is being placed. */
.mmx-glyph.is-dragging, label.is-dragging { border-color: var(--mmx-accent); color: var(--mmx-accent); }
/* The cell being rendered wears the live frame: B's caption promises the sheet appears here. */
.mmx-cellbox.is-live {
  background-image: var(--mmx-cell-shot); background-size: cover; background-position: center;
  border-color: var(--mmx-accent);
}
.mmx-cellbox.is-live .mmx-cellbox__view, .mmx-cellbox.is-live .mmx-cellbox__meta {
  text-shadow: 0 1px 2px #000c;
}
.mmx-col {
  flex: 1 1 0; min-width: 240px; display: flex; flex-direction: column; gap: 6px;
  overflow: auto; align-content: flex-start;
}
/* B's column reads top to bottom in ONE order (sheets, sizes, mode, the tab's own block), and
   the primary action is pinned under all of it: margin-top auto on the foot is what puts
   Render at the bottom of the column at any node height instead of floating under the mode. */
.mmx-col > .mmx-row, .mmx-col > .mmx-presets, .mmx-col > .mmx-resolutions { flex: 0 0 auto; }
/* Five of the seven tabs own no column (see COLUMN_TABS in the module): they are read-outs of the
   render, so the stage gets the whole panel instead of sharing it with an empty half. */
.mmx-col.is-off { display: none; }
.mmx-col__stack { flex: 1 1 auto; display: flex; flex-direction: column; gap: 6px; min-height: 0; }
/* The column's per-tab slot: the tab's blocks scroll inside it, so nothing ever slides under the
   pinned Render row (a scrolling flex parent would overlap the foot with its own content). */
.mmx-col__body {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden;
}
.mmx-col__body > .mmx-col__stack { overflow-y: auto; }
/* B's References section in the Sheets column: small avatars, one per wired reference. */
.mmx-mini { display: flex; flex-direction: column; gap: 4px; }
.mmx-mini__head {
  margin: 2px 0 0; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--mmx-muted);
}
.mmx-mini__row { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.mmx-mini__chip {
  min-width: 34px; height: 34px; padding: 0 5px; border-radius: 8px; font-size: 10px;
  background: #23232e; border: 1px solid var(--mmx-line); color: var(--mmx-fg);
  display: inline-flex; align-items: center; justify-content: center; text-align: center;
  line-height: 1.05; overflow: hidden;
}
.mmx-mini__chip.is-off { opacity: 0.45; }
.mmx-mini__chip--add { color: var(--mmx-muted); font-size: 15px; border-style: dashed; }
/* B's "Blur area" row: chips under the picture, where the picture is. */
.mmx-chiprow {
  display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 11px;
}
.mmx-chip {
  padding: 3px 9px; border-radius: 999px; font-size: 11px;
  background: #23232e; border: 1px solid var(--mmx-line); color: var(--mmx-fg);
}
.mmx-chip.is-on {
  background: var(--mmx-accent); border-color: var(--mmx-accent); color: #17171c;
}
/* The Board row's own switch: whether that row follows the render (see followSwitch). It sits at the
   far end of the row so it cannot be mistaken for a board, and stays quiet when it is off. */
.mmx-chip--follow { margin-left: auto; font-size: 10px; opacity: 0.8; }
.mmx-chip--follow.is-on { opacity: 1; }
/* The browse picker's folder trail: where the listing is pointed, and the way into a subfolder. It
   only exists in folder mode - the all-folders mode is one flat newest-first grid by definition. */
.mmx-browse__trail {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
  font-size: 11px; margin-bottom: 6px;
}
.mmx-browse__trail:empty { display: none; }
.mmx-chiprow__hint { font-size: 10px; }
.mmx-col__foot {
  margin-top: 4px; display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding-top: 2px;
}
/* The status bar's own rule pins it to the bottom of the scrolling pane; here it IS the bottom of
   the panel, so it is a plain row again. */
.mmx-foot .mmx-actionbar { margin-top: 0; padding: 4px 5px; position: static; flex: 1 1 380px; }
/* Render is the one wide control on the line, and it never leaves it: the sheet's own buttons wrap
   under it before it does. */
.mmx-foot > .mmx-btn--primary {
  flex: 0 0 auto; min-width: 146px; justify-content: center; padding: 6px 18px; font-weight: 650;
}
/* The mode axis is a SEGMENT in the column (B's "One pass | Per cell"): equal shares, one line,
   and the steps chip at the end of the same line. */
.mmx-modeseg { align-items: center; gap: 6px; flex-wrap: wrap; }
.mmx-modeseg .mmx-seg { flex: 1 1 auto; min-width: 0; }
/* The buttons share the line, and they may SHRINK: three mode names and a steps chip is more than a
   356px column holds at the full 11px, and the clipping was the whole segment overflowing the
   column (the steps chip was the part that fell off the side). */
.mmx-modeseg .mmx-seg .mmx-btn {
  flex: 1 1 0; min-width: 0; justify-content: center; padding: 3px 6px; font-size: 10px;
}
.mmx-chip--steps { flex: 0 0 auto; margin-left: auto; font-variant-numeric: tabular-nums; }
/* Two equal halves are the layout; they stack only when the panel is genuinely too narrow for
   them (2 x 240px + the rail + the gaps). BOTH children and the wrap change together: an
   earlier version set the column to 100% while the shell was still nowrap, which left the stage
   zero pixels wide - a single column that had swallowed the picture. */
@container (max-width: 640px) {
  .mmx-shell { flex-wrap: wrap; align-items: flex-start; }
  .mmx-stage, .mmx-col { flex: 1 1 100%; min-width: 0; }
  .mmx-stage { min-height: 280px; }
}
.mmx-tabs { display: flex; flex-direction: column; gap: 4px; flex: 0 0 auto; margin: 2px 0 0; }
/* In the column the rails are a GRID: the sheet cards wrap into a wall you can see at once,
   which is the point of B's SHEETS block (a scroller hides five of the six). */
.mmx-col .mmx-rail {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; overflow: visible;
}
.mmx-col .mmx-rail--wrap { grid-template-columns: repeat(2, minmax(0, 1fr)); }
/* The card art is a FIXED height in the column, not a 3:2 box: a wider node made every card taller
   (3:2 of a wider box), which pushed the size cards and the mode row out of the column and under
   the fold. The cards may get wider - they may not get taller. */
.mmx-col .mmx-pcard__art { aspect-ratio: auto; height: 62px; }
.mmx-col .mmx-pcard { width: auto; min-width: 0; }
.mmx-col .mmx-label { margin-top: 2px; }
.mmx-tab {
  position: relative; width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  background: transparent; color: var(--mmx-muted); border: 1px solid transparent;
  border-radius: 8px; cursor: pointer;
}
.mmx-tab__icon { display: flex; }
.mmx-tab__icon svg { width: 17px; height: 17px; display: block; }
.mmx-tab.is-active { background: var(--mmx-card); color: var(--mmx-fg); border-color: var(--mmx-line); }
/* A tab with something happening in it: lit in the accent colour and pulsing, so a render that is
   working says so from anywhere in the panel without a numeral badge on the corner. */
.mmx-tab.is-live { color: var(--mmx-accent); border-color: var(--mmx-accent); }
.mmx-tab.is-live::after {
  content: ""; position: absolute; inset: -2px; border-radius: 10px;
  border: 1px solid var(--mmx-accent); animation: mmx-tab-pulse 1.4s ease-out infinite;
}
@keyframes mmx-tab-pulse {
  0% { opacity: .85; transform: scale(.96); }
  70% { opacity: 0; transform: scale(1.18); }
  100% { opacity: 0; transform: scale(1.18); }
}
@media (prefers-reduced-motion: reduce) {
  .mmx-tab.is-live::after { animation: none; opacity: .8; }
}
/* The panel is a column and the ACTIVE PANE fills what is left of it, scrolling when its
   content needs more room than the node has (the .mmx-pane.is-active rule below). Panes used to
   cap themselves at 520px "so a long Results list scrolls inside the panel", which left an
   empty box under the content of a node the user had already made tall enough; a pane now
   grows with its content and the NODE is the thing that decides how much of it is on screen.
   The pack never resizes the node, so the size it has is the size the user dragged it to.
   Keep these as real CSS comments: a double-slash line in here eats the whole next rule, and
   then every tab renders blank. */
.mmx-pane { display: none; }
.mmx-pane.is-active { display: block; flex: 1 1 auto; min-height: 0; overflow-y: auto; }
/* A pane that has a STAGE: the picture on top, filling, and one scrolling column of settings
   underneath. This is B's stage/controls split, in the vertical direction the tab needs. */
.mmx-pane--fills.is-active {
  display: flex; flex-direction: column; gap: 6px; overflow: hidden;
}
.mmx-pane--fills > .mmx-stage__sheet { flex: 1 1 auto; min-height: 0; }
.mmx-pane__scroll {
  flex: 0 0 auto; max-height: 62%; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;
}
.mmx-card {
  background: var(--mmx-card); border: 1px solid var(--mmx-line); border-radius: 8px;
  padding: 6px; margin: 0 0 8px;
}
.mmx-card.is-drop { border-color: var(--mmx-accent); }
.mmx-card__head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.mmx-label { font-size: 10px; font-weight: 650; text-transform: uppercase; letter-spacing: .06em; color: var(--mmx-muted); }.mmx-count { font-size: 10px; color: var(--mmx-muted); }
/* The Cells tab's tick groups. Four rows of 15-20 checkboxes is a wall: each group gets its
   own rounded panel and its own slightly lighter grey, so the boundaries are readable without
   reading, and the group names are bold in the yellow-orange the Build cells outline uses
   rather than the quiet muted grey every hint wears. The shades step up in the order the tab
   is filled in (views -> poses -> expressions -> background), so the darkest panel is the one
   the eye lands on first. */
.mmx-tickgroup { border: 1px solid var(--mmx-line); border-radius: 8px; padding: 5px 7px; margin-bottom: 5px; }
.mmx-tickgroup--views { background: rgba(255,255,255,.035); }
.mmx-tickgroup--poses { background: rgba(255,255,255,.065); }
.mmx-tickgroup--expressions { background: rgba(255,255,255,.095); }
.mmx-tickgroup--background { background: rgba(255,255,255,.125); }
.mmx-tickgroup--boards { background: rgba(255,255,255,.155); }
.mmx-tickgroup__label {
  color: var(--mmx-tick); font-weight: 700; font-size: 10px;
  letter-spacing: .02em; align-self: center; white-space: nowrap;
}
.mmx-grid { display: grid; gap: 6px; align-items: start; }
/* One grid for every reference. Tiles are sized to fit the box, and the box FILLS the space
   the card has in the pane (the tile maths reads clientHeight/clientWidth), so a taller node
   means bigger tiles instead of a 178px strip with empty space under it. 178px is the floor. */
.mmx-refbox {
  display: flex; flex-wrap: wrap; align-content: flex-start; gap: 6px;
  flex: 1 1 auto; min-height: 178px;
  padding: 4px; box-sizing: border-box; overflow: auto;
  background: rgba(0,0,0,.14); border: 1px solid var(--mmx-line); border-radius: 6px;
}
/* The references card is the one card that stretches: its head stays put, its box grows. */
/* The references themselves live in the control column, under the sheet cards; the picture they
   are loaded into is the STAGE. Two regions, one card each - not one card with two columns. */
.mmx-card--refs-col {
  display: flex; flex-direction: column; gap: 6px; flex: 0 0 auto;
}
.mmx-card--refs-col > .mmx-refbox { min-height: 300px; }
/* The stage: the picture at the size the pane allows, with the paint bar and the before/after
   pair under it (see referenceParts). It takes the height the node has. */
.mmx-card--stage {
  display: flex; flex-direction: column; gap: 6px; flex: 1 1 auto; min-height: 0;
}
.mmx-refbox .mmx-sheet-ref { flex: 0 0 auto; }
.mmx-refbox .mmx-tile { width: 100%; max-height: none; }
.mmx-refbox .mmx-role { font-size: 10px; height: 20px; padding: 0 4px; }
.mmx-slot { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.mmx-tile {
  position: relative; overflow: hidden;
  background: #0d0d10; border: 1px solid var(--mmx-line); border-radius: 6px;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.mmx-tile.is-filled { border-color: var(--mmx-accent); }
.mmx-tile.is-dropping { border-color: var(--mmx-accent); box-shadow: inset 0 0 0 2px var(--mmx-accent); }
.mmx-tile.is-drag { opacity: .45; }
.mmx-tile--add { border-style: dashed; background: transparent; color: var(--mmx-muted); }
.mmx-tile--add:hover { border-color: var(--mmx-accent); color: var(--mmx-fg); }
.mmx-tile--add-empty { aspect-ratio: 16 / 6; }
.mmx-tile--add .mmx-tile__note { color: var(--mmx-muted); }
.mmx-tile--add .mmx-tile__note span { max-width: 100%; }
.mmx-tile__thumb { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: transparent; }
/* Top strip: ONE flowing row - kind badge and enable checkbox on the left, the hover
   actions on the right. It used to be three absolutely positioned layers stacked on the
   same corner (checkbox top-left, actions top-right, a strip across both), which put the
   checkbox, the blur toggle and the eye/remove buttons on top of each other and on the
   picture. The strip itself is positioned; its children are not. */
.mmx-tile__top { position: absolute; top: 0; left: 0; right: 0; z-index: 3; display: flex; align-items: center; gap: 4px; padding: 3px 4px; flex-wrap: nowrap; pointer-events: none; }
.mmx-tile__top > * { pointer-events: auto; }
.mmx-tile__kind {
  width: 18px; height: 18px; padding: 0; border-radius: 4px; flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,.66); color: #fff; border: 1px solid rgba(255,255,255,.18);
}
.mmx-tile__kind--video { color: #ffd8a8; }
.mmx-tile__kind--audio { color: #b7e4a8; }
/* The blur toggle sits on the picture's bottom-left corner - the spot the filename used
   to take. It is a state readout (auto / on / off), so it has to be visible without
   hovering, and that corner already carried a caption: it replaces the name instead of
   sharing the row under the tile, where it was squeezing the role box out of the way.
   The filename stays available in the tile tooltip and in the preview header. */
.mmx-tile__blur {
  position: absolute; left: 4px; bottom: 3px; z-index: 2; font-size: 10px; height: 18px;
  padding: 0 6px; border-radius: 4px; white-space: nowrap; cursor: pointer;
  background: rgba(0,0,0,.7); border: 1px solid rgba(255,255,255,.22); color: #cfe6ff;
}
.mmx-tile__blur--auto { color: #9fd0ff; border-color: rgba(159,208,255,.45); }
.mmx-tile__blur--on { color: #ffb4a2; border-color: rgba(255,180,162,.6); }
.mmx-switch-box { position: absolute; width: 0; height: 0; opacity: 0; margin: 0; }
/* A bounded number gets a slider under its box: same value, one drag instead of typing. */
.mmx-knob__slider { flex: 0 0 auto; width: 100%; height: 12px; margin: 0; accent-color: var(--mmx-tick); cursor: pointer; }
/* The switch itself: a pill with a knob that slides, lit by the input's own :checked state. */
.mmx-switch {
  position: relative; display: inline-block; flex: 0 0 auto; width: 28px; height: 15px;
  border-radius: 20px; background: var(--mmx-card-2); border: 1px solid var(--mmx-line);
  transition: background .12s, border-color .12s; cursor: pointer;
}
.mmx-switch::after {
  content: ""; position: absolute; top: 1px; left: 1px; width: 11px; height: 11px;
  border-radius: 50%; background: var(--mmx-muted); transition: transform .12s, background .12s;
}
input:checked + .mmx-switch { background: rgba(255,185,94,.22); border-color: var(--mmx-tick); }
input:checked + .mmx-switch::after { transform: translateX(13px); background: var(--mmx-tick); }
.mmx-knob--toggle { flex-direction: row; align-items: center; gap: 6px; }
.mmx-knob--toggle .mmx-knob__label { order: 2; }
.mmx-knob--toggle input { order: 1; }
.mmx-knob--toggle .mmx-switch { order: 1; }
.mmx-tile__blur--off { color: var(--mmx-muted); }
/* The badge row along the bottom of a tile: what this reference will do (its blur state), what has
   been painted out of it, and - for a video - that blurring it is not possible yet. The badges ARE
   the controls and the tooltips carry the sentences, so a tile says its state in two short words
   instead of a line of prose. */
.mmx-tile__badges {
  position: absolute; left: 3px; right: 3px; bottom: 3px; z-index: 2;
  display: flex; gap: 3px; flex-wrap: wrap; align-items: center;
}
.mmx-tile__badges .mmx-badge {
  background: rgba(0,0,0,.72); backdrop-filter: blur(2px); cursor: default; padding: 1px 5px;
}
button.mmx-badge { cursor: pointer; font: inherit; }
button.mmx-badge:hover { border-color: var(--mmx-tick); }
.mmx-badge--blur { color: #9fd0ff; border-color: rgba(159,208,255,.45); }
.mmx-badge--blur.mmx-badge--on { color: #ffb4a2; border-color: rgba(255,180,162,.6); }
.mmx-badge--blur.mmx-badge--off { color: var(--mmx-muted); }
.mmx-badge--paint { color: var(--mmx-tick); border-color: rgba(255,185,94,.5); }
.mmx-badge--warn { color: var(--mmx-danger); border-color: rgba(224,85,97,.5); }
/* A filename that shares the badge row (video tiles): same weight as a badge, no chrome. */
.mmx-tile__badge-name {
  font-size: 9px; color: #fff; text-shadow: 0 1px 3px #000c; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* The canvas at the top of the References tab: the reference you are working on, at the size the
   pane allows, with the paint surface and the before/after bar mounted ON the picture. It is the
   same parts the Preview overlay shows - the panel just has a place for them now. */
.mmx-canvas {
  border: 1px solid var(--mmx-line); border-radius: 8px; background: var(--mmx-card-2);
  padding: 6px; margin: 0 0 8px; display: flex; flex-direction: column; gap: 6px;
}
.mmx-canvas__head { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.mmx-canvas__empty {
  min-height: 92px; display: grid; place-items: center; text-align: center;
  border: 1px dashed var(--mmx-line); border-radius: 6px;
}
/* A fresh node's canvas: the pack's sample render instead of an empty box. The picture is sized to
   the pane (a reference would be), and the note under it says what it is so nobody reads it as a
   reference that is somehow already wired. */
.mmx-canvas__empty--art {
  display: flex; flex-direction: column; gap: 6px; min-height: 0; padding: 6px;
}
.mmx-canvas__art {
  max-width: 100%; max-height: 380px; width: auto; height: auto; object-fit: contain;
  border-radius: 6px; border: 1px solid var(--mmx-line); opacity: 0.92;
}
.mmx-canvas__artnote {
  display: flex; flex-direction: column; gap: 2px; text-align: left; font-size: 10px;
}
/* The tile whose reference is on the canvas. */
.mmx-sheet-ref.is-canvas .mmx-tile { border-color: var(--mmx-tick); box-shadow: 0 0 0 2px rgba(255,185,94,.22); }
/* Filmstrip: the picked frame of every cell, in cell order, under the sheet. Clicking one jumps
   to that cell's row (and flashes it), which is the fast path from "that panel is wrong" to the
   row whose thumbnails decide it. */
.mmx-film { display: flex; gap: 3px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
.mmx-film__item {
  position: relative; flex: 0 0 auto; width: 62px; height: 62px; padding: 0; cursor: pointer;
  border: 1px solid var(--mmx-line); border-radius: 5px; background: var(--mmx-card-2); overflow: hidden;
  font: inherit;
}
.mmx-film__item:hover { border-color: var(--mmx-tick); }
.mmx-film__name {
  position: absolute; left: 0; right: 0; bottom: 0; font-size: 8px; color: #fff; text-align: center;
  background: rgba(0,0,0,.62); padding: 1px 2px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.mmx-sheet-result-row.is-flash { outline: 2px solid var(--mmx-tick); border-radius: 4px; }
/* The preview's blur bar: original vs the copy the render wires. */
.mmx-preview__bar {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px; flex-wrap: wrap;
  border-top: 1px solid var(--mmx-line, rgba(255,255,255,.12)); font-size: 11px;
}
.mmx-preview__bar .mmx-btn.is-active { border-color: var(--mmx-accent); color: var(--mmx-fg); }
/* The resolution control: square buttons, one lit at a time. A chip is a decision, not a
   toggle - the group is exclusive, so the active one is filled rather than outlined, and the
   muted readout beside it says what the pair of sizes is (or reads Custom). */
.mmx-chip {
  flex: 0 0 auto; min-width: 54px; padding: 6px 10px; text-align: center;
  font-variant-numeric: tabular-nums;
}
.mmx-chip.is-active {
  background: var(--mmx-accent); border-color: var(--mmx-accent); color: var(--mmx-accent-ink);
}
.mmx-resolutions .mmx-chip.is-active:hover { border-color: var(--mmx-accent); }
.mmx-presets { flex-direction: column; align-items: stretch; gap: 6px; }
.mmx-resolutions { align-items: center; }
/* A size is a card carrying its own numbers (proposal B), not a word you have to hover to
   price. The active one is the only thing that says "this is what the render will use". */
.mmx-rescard {
  flex: 0 0 auto; min-width: 86px; display: flex; flex-direction: column; gap: 0;
  padding: 5px 9px; text-align: left; line-height: 1.25;
}
.mmx-rescard__label { font-size: 12px; font-weight: 600; }
.mmx-rescard__size, .mmx-rescard__cells {
  font-size: 9px; color: var(--mmx-muted); font-variant-numeric: tabular-nums;
}
.mmx-rescard.is-active { border-color: var(--mmx-accent); }
.mmx-rescard.is-active .mmx-rescard__label { color: var(--mmx-accent); }
/* Card art: your own last render of that layout, once there is one (see gallery_art in
   sheet_store.py). The card says where the picture came from, because a thumbnail of a real
   sheet next to "Hero + 4 panels" is the whole point of it. */
.mmx-pcard.has-art .mmx-pcard__art { border-color: var(--mmx-accent); }
.mmx-pcard__live {
  position: absolute; top: 4px; right: 4px; font-size: 8px; padding: 0 4px;
  border-radius: 6px; background: var(--mmx-accent); color: var(--mmx-accent-ink);
}
/* The panel's footer: the primary action, pinned to the bottom of the panel where proposal B
   puts it, with the status line it acts on beside it. */
.mmx-actionbar {
  display: flex; align-items: center; gap: 6px; margin-top: 6px; padding: 5px 6px;
  border: 1px solid var(--mmx-line); border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  position: sticky; bottom: 0; z-index: 3;
}
.mmx-actionbar .mmx-status { flex: 1 1 auto; min-width: 0; }
.mmx-btn--primary { background: var(--mmx-accent); border-color: var(--mmx-accent); color: var(--mmx-accent-ink); font-weight: 600; }
.mmx-btn--primary:disabled { opacity: .5; font-weight: 400; }

/* The header's one fact: what will be drawn, at what size ("Hero + 4 panels · 1080p"). */
.mmx-status { flex: 0 0 auto; min-width: 0; font-size: 10px; }

/* ------------------------------------------------------------------ visual primitives
   The panel used to be lists of words: two dropdowns, rows of tick boxes and a hint bar. These
   four pieces replace them - a CARD (an arrangement drawn from the preset's own cells), a GLYPH
   TOGGLE (a framing or expression as a picture), a CHIP (already existed) and a BADGE (state on a
   tile: identity, blur mode, painted areas). The payload is unchanged; only the surface is. */
.mmx-rail {
  display: flex; gap: 8px; align-items: flex-start; overflow-x: auto; overflow-y: hidden;
  padding: 2px 0 5px; scrollbar-width: thin;
}
.mmx-rail--wrap { flex-wrap: wrap; overflow-x: visible; }
.mmx-pcard {
  flex: 0 0 auto; width: 104px; border: 1px solid var(--mmx-line); border-radius: 9px;
  background: var(--mmx-card-2); padding: 5px; cursor: pointer; position: relative;
  display: flex; flex-direction: column; gap: 4px; text-align: left; font: inherit;
}
.mmx-pcard:hover { border-color: var(--mmx-tick); }
.mmx-pcard.is-active { border-color: var(--mmx-tick); box-shadow: 0 0 0 2px var(--mmx-accent-soft); }
.mmx-pcard.is-active::after {
  content: "✓"; position: absolute; top: 4px; right: 6px; font-size: 10px; color: var(--mmx-tick);
}
.mmx-pcard__art {
  aspect-ratio: 3 / 2; border-radius: 6px; background: #0b0b10; border: 1px solid var(--mmx-line);
  padding: 3px; display: grid; gap: 3px; overflow: hidden;
}
.mmx-pcard__art > i { display: block; background: #2c2c37; border-radius: 3px; }
.mmx-pcard__art.is-one { grid-template-columns: 1fr; }
.mmx-pcard__art.is-hero { grid-template-columns: 1.35fr 1fr 1fr; grid-template-rows: 1fr 1fr; }
.mmx-pcard__art.is-hero > i:first-child { grid-row: span 2; }
.mmx-pcard__art.is-grid6 { grid-template-columns: repeat(3, 1fr); grid-template-rows: 1fr 1fr; }
.mmx-pcard__art.is-grid4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.mmx-pcard__art.is-row { grid-template-columns: repeat(3, 1fr); }
.mmx-pcard__art.is-suite { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 4px; }
.mmx-pcard__art.is-suite > i {
  background: #0b0b10; border: 1px solid var(--mmx-line); border-radius: 4px;
  padding: 2px; display: grid; gap: 2px;
}
.mmx-pcard__art.is-suite > i.a1 { grid-template-columns: 1.3fr 1fr; grid-template-rows: 1fr 1fr; }
.mmx-pcard__art.is-suite > i.a1 > b:first-child { grid-row: span 2; }
.mmx-pcard__art.is-suite > i.a2 { grid-template-columns: repeat(3, 1fr); grid-template-rows: 1fr 1fr; }
.mmx-pcard__art.is-suite > i.a3, .mmx-pcard__art.is-suite > i.a4 {
  grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr;
}
.mmx-pcard__art b { background: #2c2c37; border-radius: 2px; }
/* Phase 2: when the panel knows the last render of this layout, the card wears it instead of the
   wireframe (the route serves the file; the panel sets --mmx-card-art). */
.mmx-pcard.has-art .mmx-pcard__art {
  background-image: var(--mmx-card-art); background-size: cover; background-position: center;
}
.mmx-pcard.has-art .mmx-pcard__art > * { display: none; }
.mmx-pcard__name { font-size: 10px; font-weight: 620; line-height: 1.2; color: var(--mmx-fg); }
.mmx-pcard__meta { font-size: 9px; color: var(--mmx-muted); }
.mmx-pcard--custom { border-style: dashed; }
.mmx-pcard--custom .mmx-pcard__art { place-items: center; display: grid; }
.mmx-pcard--custom .mmx-pcard__art::before { content: "+"; color: var(--mmx-muted); font-size: 15px; }
.mmx-tick { display: flex; flex-wrap: wrap; gap: 6px; }
.mmx-glyph {
  width: 58px; border: 1px solid var(--mmx-line); border-radius: 9px; background: var(--mmx-card-2);
  padding: 5px 3px 4px; display: flex; flex-direction: column; align-items: center; gap: 3px;
  cursor: pointer; font: inherit;
}
.mmx-glyph:hover { border-color: var(--mmx-tick); }
.mmx-glyph.is-on { border-color: var(--mmx-tick); background: rgba(255,185,94,.10); }
.mmx-glyph svg { width: 26px; height: 26px; display: block; }
.mmx-glyph span { font-size: 9px; color: var(--mmx-muted); text-align: center; line-height: 1.1; }
.mmx-glyph.is-on span { color: var(--mmx-fg); }
.mmx-badge {
  font-size: 9px; font-weight: 700; letter-spacing: .03em; border-radius: 20px; padding: 1px 5px;
  border: 1px solid var(--mmx-line); background: var(--mmx-card-2); color: var(--mmx-muted);
}
.mmx-badge--on { color: var(--mmx-tick); border-color: rgba(255,185,94,.5); }
/* Painting a blur area: the frame takes the image's own shape (sized in JS from the
   natural size and the stage box) so a canvas pixel IS an image pixel - no letterbox
   maths, and the marks land under the pointer at any node zoom. */
.mmx-paint__frame { position: relative; flex: 0 0 auto; }
.mmx-paint__frame img { display: block; width: 100%; height: 100%; object-fit: fill; }
.mmx-paint__canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; cursor: crosshair; }
.mmx-paint__canvas.is-idle { cursor: default; }
.mmx-paint__radius { width: 90px; }
.mmx-tile__note { display: flex; flex-direction: column; align-items: center; gap: 3px; color: var(--mmx-muted); text-align: center; padding: 4px; }
.mmx-tile__badge {
  position: absolute; right: 0; bottom: 0; z-index: 2;
  background: rgba(0,0,0,.62); color: #fff; font-size: 10px; padding: 0 5px; border-top-left-radius: 6px;
}
.mmx-tile__badge--off { opacity: .45; }
.mmx-tile__name {
  position: absolute; left: 0; right: 0; bottom: 0; z-index: 1;
  font-size: 9px; padding: 8px 22px 2px 4px; color: #fff; text-align: left;
  background: linear-gradient(transparent, rgba(0,0,0,.78));
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Preview / remove, stacked VERTICALLY in the tile's top-right corner and revealed on
   hover. A horizontal pair needed ~52px, which on a narrow tile ran off the right edge
   (the buttons ended up outside the picture and unclickable); a column needs ~22px and
   stays inside the tile. The top-left corner is the kind badge and the "use" checkbox,
   the bottom-left is the blur state, the bottom-right is the number - four corners, one
   owner each. */
.mmx-tile__actions {
  position: absolute; top: 3px; right: 3px; z-index: 4; display: flex; flex-direction: column;
  gap: 2px; opacity: 0; pointer-events: none; transition: opacity .12s;
}
/* Sized to the icon it holds (11px mark in an 18px box) and centred by flexbox, so the two
   buttons read as one small stack over the picture instead of two big grey squares. They also
   carry their own translucent chip colour, because they sit on a photo, not on the panel. */
.mmx-tile__actions .mmx-btn {
  width: 18px; height: 18px; min-height: 0; padding: 0; border-radius: 5px;
  justify-content: center; background: rgba(0,0,0,.66); border-color: rgba(255,255,255,.18);
}
.mmx-tile__actions .mmx-btn:hover { border-color: var(--mmx-accent); background: rgba(0,0,0,.8); }
.mmx-tile:hover .mmx-tile__actions, .mmx-tile:focus-within .mmx-tile__actions { opacity: 1; pointer-events: auto; }
/* In the top row, not pinned to a corner: it sits beside the kind badge, so the hover
   actions (far right) and the checkbox (left) can never land on the same pixels. */
.mmx-tile__use { position: static; flex: 0 0 auto; width: 13px; height: 13px; margin: 0; cursor: pointer; accent-color: var(--mmx-accent); }
.mmx-role { width: 100%; }
.mmx-overlay {
  position: absolute; inset: 0; z-index: 40; display: flex; flex-direction: column;
  background: var(--mmx-bg); border: 1px solid var(--mmx-line); border-radius: 8px; padding: 6px;
}
.mmx-overlay__head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.mmx-overlay__body { flex: 1 1 auto; overflow: auto; }
.mmx-pickgrid { display: grid; gap: 6px; grid-template-columns: repeat(auto-fill, minmax(88px, 1fr)); }
.mmx-pick {
  position: relative; aspect-ratio: 1 / 1; border: 1px solid var(--mmx-line); border-radius: 6px;
  background: #0d0d10; overflow: hidden; cursor: pointer; padding: 0;
}
.mmx-pick:hover { border-color: var(--mmx-accent); }
.mmx-pick img { width: 100%; height: 100%; object-fit: cover; }
.mmx-pick span {
  position: absolute; left: 0; right: 0; bottom: 0; font-size: 9px; color: #fff; text-align: left;
  padding: 8px 4px 2px; background: linear-gradient(transparent, rgba(0,0,0,.8));
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mmx-preview__stage { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.mmx-preview__stage img, .mmx-preview__stage video { max-width: 100%; max-height: 100%; object-fit: contain; }
.mmx-seg { display: inline-flex; border: 1px solid var(--mmx-line); border-radius: 6px; overflow: hidden; }
.mmx-seg .mmx-btn { border-radius: 0; border: none; }
.mmx-seg .mmx-btn.is-active { background: var(--mmx-accent); color: var(--mmx-accent-ink); }
.mmx-cell { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; border-bottom: 1px solid var(--mmx-line); padding: 3px 0; }
.mmx-cell__refs { flex: 1 0 100%; font-size: 10px; color: var(--mmx-muted); }
.mmx-prompt { border-bottom: 1px solid var(--mmx-line); padding: 4px 0; }
.mmx-prompt pre {
  margin: 3px 0 0; padding: 4px; border: 1px solid var(--mmx-line); border-radius: 6px;
  background: rgba(0,0,0,.14); color: var(--mmx-fg); font-size: 10px; line-height: 1.35;
  white-space: pre-wrap; word-break: break-word;
}
.mmx-results img { border-radius: 4px; }
/* The live stream: the one thing on screen between "queued" and the finished sheet. It sits
   above the tabs so it is visible whichever tab is open, and it is only as tall as one frame. */
.mmx-live { display: flex; flex-direction: column; gap: 3px; margin: 2px 0 6px; }
/* The Preview tab: the stream is the tab, so it gets the height, not a capped strip. */
.mmx-pane--preview.is-active {
  display: flex; flex-direction: column; gap: 6px; overflow: hidden;
}
.mmx-pane--preview .mmx-live { flex: 1 1 auto; min-height: 0; margin: 0; }
.mmx-pane--preview .mmx-live__frame {
  flex: 1 1 auto; min-height: 0; max-height: none;
}
.mmx-pane--preview .mmx-live__wait { flex: 1 1 auto; min-height: 0; }
.mmx-live__idle { display: flex; flex-direction: column; gap: 4px; padding: 10px 2px; }
.mmx-pane--preview.is-active:has(.mmx-live:not([style*="none"])) .mmx-live__idle { display: none; }
.mmx-live[hidden] { display: none; }.mmx-live__head { display: flex; align-items: center; gap: 6px; }
.mmx-live__tag {
  font-size: 9px; font-weight: 700; letter-spacing: .08em; color: #101014;
  background: var(--mmx-tick); border-radius: 3px; padding: 1px 5px;
}
.mmx-live__meta { font-size: 10px; color: var(--mmx-muted); }
.mmx-live__retry { margin-left: auto; }
.mmx-live__head { display: flex; align-items: center; gap: 6px; }
/* A quiet button: the re-roll is offered next to things you read, not instead of them. */
.mmx-btn--quiet {
  background: transparent; color: var(--mmx-muted); border: 1px solid var(--mmx-line);
  padding: 1px 5px; font-size: 9px; border-radius: 3px; line-height: 1.5;
}
.mmx-btn--quiet:hover:not(:disabled) { color: var(--mmx-tick); border-color: var(--mmx-tick); }
.mmx-btn--quiet:disabled { opacity: .5; }
.mmx-cell__retry { margin-left: 6px; }
.mmx-live__frame {
  width: 100%; max-height: 220px; object-fit: contain; border-radius: 4px;
  background: rgba(0,0,0,.25);
}
/* While a run is starting the frame's space is held open (dashed), so the node settles its
   height once instead of growing when the first frame lands. */
.mmx-live__wait {
  min-height: 180px; border: 1px dashed rgba(255,185,94,.35); border-radius: 4px;
  background: rgba(0,0,0,.14);
}
.mmx-live.is-waiting .mmx-live__frame { display: none; }
.mmx-live:not(.is-waiting) .mmx-live__wait { display: none; }
/* Compact knobs: the node's own widgets, packed into columns the frontend cannot make.
   One grid per declared row, each field labelled, values written straight onto the widget. */
.mmx-settings__head { gap: 6px; }
.mmx-knob-group { margin-bottom: 8px; }
.mmx-knob-group__title {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 650; color: var(--mmx-muted); text-transform: uppercase;
  letter-spacing: .04em; margin: 2px 0 4px;
}
/* One grid per row, stacked: a row is the backend's unit of "these belong together". */
.mmx-knob-rows { display: flex; flex-direction: column; gap: 5px; }
.mmx-knob-grid { display: grid; gap: 4px 8px; align-items: end; }
.mmx-knob { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mmx-knob__label { font-size: 10px; color: var(--mmx-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mmx-knob__hint { font-size: 9px; color: var(--mmx-muted); opacity: .8; }
.mmx-knob input, .mmx-knob select { width: 100%; box-sizing: border-box; }
.mmx-knob--toggle { flex-direction: row; align-items: center; gap: 5px; }
.mmx-knob--toggle input { width: auto; }
/* Help tab: the guide, the live file check and outbound links. A link must look like a
   link (the panel is otherwise all buttons), and it has to open in a new tab: the canvas
   is a single-page app, so navigating away loses unsaved work. */
.mmx-help__section { margin-bottom: 10px; }
.mmx-help__title { font-size: 11px; font-weight: 650; margin-bottom: 3px; }
.mmx-help__intro { font-size: 10px; color: var(--mmx-fg); margin-bottom: 3px; }
.mmx-help__steps, .mmx-help__bullets { margin: 0 0 3px; padding-left: 16px; }
.mmx-help__steps li, .mmx-help__bullets li { font-size: 10px; line-height: 1.4; margin-bottom: 2px; }
.mmx-help__links { display: flex; flex-direction: column; gap: 2px; margin-top: 3px; }
.mmx-help__link { font-size: 10px; color: var(--mmx-accent); text-decoration: none; }
.mmx-help__link:hover { text-decoration: underline; }
.mmx-help__link-note { color: var(--mmx-muted); }
.mmx-req {
  border: 1px solid var(--mmx-line); border-radius: 6px; padding: 4px 6px; margin-bottom: 4px;
  background: rgba(255, 255, 255, 0.02);
}
.mmx-req__head { gap: 6px; }
.mmx-req__mark { font-weight: 700; }
.mmx-req--missing { border-color: var(--mmx-danger); }
.mmx-req--missing .mmx-req__mark { color: var(--mmx-danger); }
.mmx-req--ok .mmx-req__mark { color: #46b96a; }
.mmx-req__path { font-size: 10px; color: var(--mmx-muted); word-break: break-all; }
.mmx-req__what { font-size: 10px; color: var(--mmx-muted); opacity: .9; }
.mmx-req__package { font-size: 10px; color: var(--mmx-muted); }
.mmx-req__package--missing { color: var(--mmx-danger); }
/* The guide is authored with inline markers (bold, italic and code); these rules are what
   makes them worth typing - before them the tab showed the asterisks and backticks. */
.mmx-help strong, .mmx-req strong { font-weight: 700; color: var(--mmx-fg); }
.mmx-help em, .mmx-req em { font-style: italic; color: var(--mmx-fg); }
.mmx-help code, .mmx-req code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9px;
  background: rgba(255, 255, 255, 0.07); border-radius: 3px; padding: 0 3px;
}
/* LoRAs tab: a stack of rows plus the library you add from, in one scrolling column. NOTE the
   display is on .mmx-pane--loras.is-active and NOT on .mmx-loras: the generic .mmx-pane rule hides
   an inactive pane, and an unscoped "display: flex" here ties with it and - being later in this
   sheet - WINS, which put this tab's rows on every other tab, the reference page included. Every
   pane's own layout belongs on its is-active rule; this one is not the exception. */
.mmx-pane--loras.is-active { display: flex; flex-direction: column; }
.mmx-loras { gap: 6px; padding: 6px 8px; }
.mmx-loras__head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mmx-loras__note { font-size: 10px; }
.mmx-loras__search { flex: 1 1 170px; min-width: 120px; }
.mmx-loras__rows { display: flex; flex-direction: column; gap: 4px; }
.mmx-loras__empty {
  display: flex; flex-direction: column; gap: 3px; padding: 10px;
  border: 1px dashed var(--mmx-line); border-radius: 8px;
}
.mmx-lora { border: 1px solid var(--mmx-line); border-radius: 6px; padding: 5px 6px; background: var(--mmx-card-2); }
.mmx-lora.is-off { opacity: .55; }
.mmx-lora__head { display: flex; align-items: center; gap: 6px; }
/* The switch is a LABEL around the (invisible) box and its track: the track is what a user sees and
   clicks, so without this the only clickable part of the control was a 0x0 transparent input. */
.mmx-lora__switch { display: flex; align-items: center; flex: 0 0 auto; cursor: pointer; }
.mmx-lora__title {
  display: flex; flex-direction: column; align-items: flex-start; gap: 1px; min-width: 0;
  flex: 1 1 auto; background: none; border: 0; padding: 0; color: var(--mmx-fg); cursor: pointer;
  text-align: left;
}
.mmx-lora__name { font-size: 11px; font-weight: 620; }
.mmx-lora__file {
  font-size: 9px; color: var(--mmx-muted); max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mmx-lora__strength { display: flex; align-items: center; gap: 4px; flex: 0 0 190px; }
.mmx-lora__number { width: 58px; }
.mmx-lora__slider { flex: 1 1 auto; min-width: 60px; }
.mmx-lora__actions { display: flex; align-items: center; gap: 2px; }
.mmx-lora__remove { color: var(--mmx-danger); }
.mmx-lora__card {
  display: flex; flex-direction: column; gap: 4px; margin-top: 5px; padding-top: 5px;
  border-top: 1px dashed var(--mmx-line);
}
.mmx-lora__facts { display: flex; flex-direction: column; gap: 2px; }
.mmx-lora__fact { display: grid; grid-template-columns: 96px 1fr auto; align-items: center; gap: 4px; }
.mmx-lora__factlabel { font-size: 9px; color: var(--mmx-muted); text-transform: uppercase; letter-spacing: .03em; }
.mmx-lora__factvalue, .mmx-lora__hash {
  font-size: 9px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all; color: var(--mmx-fg);
}
.mmx-lora__link { font-size: 10px; color: var(--mmx-accent); text-decoration: none; }
.mmx-lora__link:hover { text-decoration: underline; }
.mmx-lora__error { font-size: 9px; color: var(--mmx-danger); }
.mmx-lora__civitai {
  display: flex; flex-direction: column; gap: 3px; padding: 5px 6px; border-radius: 6px;
  border: 1px solid var(--mmx-line); background: rgba(255, 255, 255, 0.03);
}
.mmx-lora__civitaititle { font-size: 11px; font-weight: 620; }
.mmx-lora__words { display: flex; align-items: center; gap: 3px; flex-wrap: wrap; }
.mmx-lora__tags { font-size: 9px; }
.mmx-lora__desc { font-size: 10px; color: var(--mmx-muted); max-height: 84px; overflow: auto; }
.mmx-lora__shot { max-width: 180px; max-height: 180px; border-radius: 5px; align-self: flex-start; }
.mmx-lora__fields { display: flex; flex-direction: column; gap: 3px; }
.mmx-lora__field { display: grid; grid-template-columns: 96px 1fr; align-items: center; gap: 4px; }
.mmx-lora__field .mmx-input { width: 100%; box-sizing: border-box; }
.mmx-lora__notes { font-size: 10px; font-family: inherit; resize: vertical; }
.mmx-lora__saverow { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.mmx-chip--tiny { font-size: 9px; padding: 0 4px; }
.mmx-badge--warn { color: var(--mmx-danger); border-color: rgba(214, 92, 92, .55); }
.mmx-loras__browser {
  display: flex; flex-direction: column; gap: 4px; padding: 5px;
  border: 1px solid var(--mmx-line); border-radius: 6px; background: rgba(255, 255, 255, 0.02);
}
.mmx-loras__browserlabel {
  font-size: 9px; color: var(--mmx-muted); text-transform: uppercase; letter-spacing: .03em;
}
.mmx-loras__picklist { display: flex; flex-direction: column; gap: 2px; max-height: 200px; overflow: auto; }
.mmx-loras__pick {
  display: grid; grid-template-columns: 1fr auto; gap: 1px 6px; text-align: left;
  background: none; border: 0; border-radius: 4px; padding: 3px 4px; color: var(--mmx-fg); cursor: pointer;
}
.mmx-loras__pick:hover { background: rgba(255, 255, 255, 0.06); }
.mmx-loras__pickname { font-size: 10px; font-weight: 600; }
.mmx-loras__pickfile {
  grid-column: 1; font-size: 9px; color: var(--mmx-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
`;

// --------------------------------------------------------------------------- //
// small DOM helpers (no framework, no global state)
// --------------------------------------------------------------------------- //
export function element(tag, props = {}, style = {}, children = []) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    Object.assign(node.style, style);
    for (const child of children) if (child) node.append(child);
    return node;
}

/**
 * The guide's inline markers, turned into elements.
 *
 * The guide is written as prose with Markdown habits: `**bold**` for the thing being named,
 * `*italic*` for a value the reader has to recognise in the panel, and backticks for a path
 * or a setting. This panel never sets innerHTML, so those markers used to reach the tab as
 * literal asterisks - emphasis the reader never saw, and stars that mean nothing on screen.
 *
 * Only these markers are interpreted, and the text between them is inserted as TEXT, so a
 * lone asterisk (or one inside a prompt example) stays exactly as typed.
 */
const INLINE_MARKERS = /(\*\*[^*]+\*\*|``[^`]+``|`[^`]+`|\*[^*]+\*)/g;

export function inlineText(text) {
    const source = String(text ?? "");
    const host = element("span");
    let at = 0;
    for (const match of source.matchAll(INLINE_MARKERS)) {
        if (match.index > at) host.append(document.createTextNode(source.slice(at, match.index)));
        const token = match[0];
        if (token.startsWith("**")) host.append(element("strong", { textContent: token.slice(2, -2) }));
        else if (token.startsWith("``")) host.append(element("code", { textContent: token.slice(2, -2) }));
        else if (token.startsWith("`")) host.append(element("code", { textContent: token.slice(1, -1) }));
        else host.append(element("em", { textContent: token.slice(1, -1) }));
        at = match.index + token.length;
    }
    if (at < source.length) host.append(document.createTextNode(source.slice(at)));
    return host;
}

/** A block of guide text: markers rendered, everything else literal. */
export function richText(tag, text, className = "") {
    return element(tag, { className }, {}, [inlineText(text)]);
}

/**
 * The same sentence with its markers stripped - for the places a marker cannot be rendered,
 * such as the `title` tooltip on a link, which is plain text or nothing.
 */
export function plainText(text) {
    return String(text ?? "").replace(
        INLINE_MARKERS,
        (token) => token.replace(/^\*+|\*+$/g, "").replace(/^`+|`+$/g, ""),
    );
}

export function button(label, onClick, style = {}) {
    const node = element("button", { textContent: label, type: "button", className: "mmx-btn" }, style);
    node.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick(event);
    });
    return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * The panel's icons, as shapes on a 24x24 grid.
 *
 * These replaced TEXT glyphs - "\u25a3" for a picture, "\u25b6" for a video, "\u266a" for audio,
 * an eye EMOJI and "\u2715" - for two reasons one screenshot made obvious. A font glyph arrives
 * with its own side bearings and baseline, so the mark sits off-centre inside whatever box
 * holds it (and an emoji is drawn by the OS: a different size, shape and colour per machine).
 * Stroked paths on a shared grid, centred by flexbox, are centred by construction and are the
 * same drawing everywhere - and they take `currentColor`, so a chip's tint or a danger red
 * carries into the icon instead of being overridden by a glyph's own palette.
 *
 * Shapes (not markup strings) on purpose: nothing here is parsed as HTML, and a test can
 * count the geometry it is supposed to have. `fill: none` + `stroke` is what makes them
 * match the outline style of the buttons they live in.
 */
export const ICONS = {
    image: [
        ["rect", { x: 3, y: 4, width: 18, height: 16, rx: 2.5 }],
        ["circle", { cx: 8.6, cy: 9.6, r: 1.6 }],
        ["path", { d: "M4 16.8l4.7-4.7 4.6 4.6 2.7-2.7 3.7 3.7" }],
    ],
    video: [
        ["rect", { x: 2.6, y: 5.4, width: 18.8, height: 13.2, rx: 2.6 }],
        ["path", { d: "M10.3 9.2l4.6 2.8-4.6 2.8z" }],
    ],
    audio: [
        ["path", { d: "M9.2 16.8V6.5l9.3-1.9v10.2" }],
        ["circle", { cx: 6.6, cy: 17.2, r: 2.6 }],
        ["circle", { cx: 15.9, cy: 15.3, r: 2.6 }],
    ],
    preview: [
        ["path", { d: "M2 12s3.7-6.4 10-6.4S22 12 22 12s-3.7 6.4-10 6.4S2 12 2 12z" }],
        ["circle", { cx: 12, cy: 12, r: 2.9 }],
    ],
    remove: [
        ["path", { d: "M6.7 6.7l10.6 10.6" }],
        ["path", { d: "M17.3 6.7L6.7 17.3" }],
    ],
    plus: [
        ["path", { d: "M12 5.6v12.8" }],
        ["path", { d: "M5.6 12h12.8" }],
    ],
};

/**
 * One icon as an SVG element, sized and stroked with the current text colour.
 *
 * `size` is the icon's own box in px, so a caller can say how big the MARK is and let CSS
 * handle the box around it - which is the other half of the centring problem: the buttons are
 * sized to the icon rather than the icon being squeezed into a padded text button.
 */
export function icon(name, { size = 12, className = "mmx-icon" } = {}) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    for (const part of String(className).split(" ").filter(Boolean)) svg.classList.add(part);
    for (const [tag, attributes] of ICONS[name] || []) {
        const shape = document.createElementNS(SVG_NS, tag);
        for (const [key, value] of Object.entries(attributes)) shape.setAttribute(key, String(value));
        svg.append(shape);
    }
    return svg;
}

/**
 * A square icon button: the box is sized to the icon (not to a text line), and the SVG is
 * centred by flexbox, so the mark cannot drift off-centre the way a glyph does.
 */
function iconButton(name, title, onClick, extraClass = "", { size = 12, label = "" } = {}) {
    const node = button(label, onClick);
    node.classList.add("mmx-btn--icon");
    if (extraClass) node.classList.add(extraClass);
    node.append(icon(name, { size }));
    node.title = title;
    node.setAttribute("aria-label", title);
    return node;
}

// --------------------------------------------------------------------------- //
// state
// --------------------------------------------------------------------------- //
export function blankRefs() {
    const refs = {};
    for (const group of REF_GROUPS) {
        refs[group.key] = Array.from({ length: group.slots }, () => ({ file: "", role: "", enabled: false }));
    }
    return refs;
}

/** Parse a `sheet_data` string into panel state (never throws). */
export function readState(payload) {
    let data = payload;
    if (typeof payload === "string") {
        try {
            data = payload ? JSON.parse(payload) : {};
        } catch {
            data = {};
        }
    }
    if (!data || typeof data !== "object") data = {};
    const refs = blankRefs();
    for (const group of REF_GROUPS) {
        const items = Array.isArray(data.refs?.[group.key]) ? data.refs[group.key] : [];
        items.slice(0, group.slots).forEach((item, index) => {
            if (!item || typeof item !== "object") return;
            refs[group.key][index] = {
                file: String(item[group.file] || item.file || ""),
                role: String(item.role || ""),
                enabled: item.enabled !== false,
                blurFace: blurMode(item),
                // Painted blur areas come back with the workflow, so a saved painting is
                // editable rather than baked into a file somewhere.
                ...(Array.isArray(item.blurPaint) && item.blurPaint.length
                    ? { blurPaint: item.blurPaint.map((stroke) => ({ ...stroke })) }
                    : {}),
            };
        });
    }
    return {
        refs,
        // The sheet's own LoRA stack (the LoRAs tab): a workflow that renders through a stack has
        // to bring it back, or the next queue would render a different model than the one saved.
        loras: loraStack({ loras: data.loras }),
        prompt: String(data.globalPrompt || data.global_prompt || ""),
        negative: String(data.negativePrompt || data.negative_prompt || ""),
        background: String(data.render?.background || "neutral"),
        backgroundCustom: String(data.render?.backgroundCustom || ""),
        // Which reference supplies the backdrop when the choice above is "reference".
        backgroundRef: String(data.render?.backgroundRef || ""),
        blurScope: blurScope({ blurScope: data.render?.blurScope }),
        // Latent continuation: a render policy like the blur area, so it comes back with
        // the workflow and is applied to the cells the panel shows.
        continuity: continuity({ continuity: data.render?.continuity }),
        // Whether each cell's clip is exported next to its frames.
        exportVideo: exportVideo({ exportVideo: data.render?.exportVideo }),
        // Which recommended preset these settings came from (a record, not a lock).
        presetId: String(data.render?.preset || ""),
        // The layout preset, on its own axis: a layout says what to draw and a quality says how to
        // sample it, so a workflow records both and applying one cannot erase the other.
        layoutPreset: String(data.render?.layoutPreset || ""),
        // A SUITE: the layout presets to render as separate sheets in one run (see suite.py). It
        // rides the layout axis - it decides WHICH sheets render - so picking one layout after a
        // suite clears it, and the quality axis leaves it alone.
        suite: Array.isArray(data.render?.suite) ? [...data.render.suite] : [],
        // The chips' table, filled from the presets route (see resolutionChoices for the fallback).
        resolutions: [],
        // Whether the node keeps its own knob rows or lets the panel draw them.
        compactKnobs: data?.ui?.compactKnobs !== false,
        // How big ComfyUI's own output previews under the panel may be.
        nodePreviews: nodePreviews({ nodePreviews: data?.ui?.nodePreviews }),
        // How big the panel's OWN preview of the sheet is (its Results tab).
        panelPreview: panelPreview({ panelPreview: data?.ui?.panelPreview }),
        // Whether the panel polls the sheet folder on its own (off by default).
        autoRefresh: autoRefresh({ autoRefresh: data?.ui?.autoRefresh }),
        // Which sheet of a SUITE run the panel is showing (see selectBoard). A view preference
        // rather than a render setting, like the preview sizes - but it has to round-trip, or a
        // reopened workflow would silently go back to the run folder and show nothing.
        suiteBoard: String(data?.ui?.suiteBoard || ""),
        // Whether the Results tab follows the board the render is ON while a suite draws it (see
        // followBoard). On unless the user said otherwise: the board that is rendering is the one
        // with something to watch, and a chip click turns it off for good (a preference, not an
        // armed-for-one-run flag - the switch that turns it back on is in the row).
        followBoard: data?.ui?.followBoard !== false,
        build: {
            views: Array.isArray(data.build?.views) ? data.build.views.map(String) : ["face", "front"],
            poses: Array.isArray(data.build?.poses) ? data.build.poses.map(String) : ["neutral"],
            expressions: Array.isArray(data.build?.expressions)
                ? data.build.expressions.map(String)
                : ["neutral"],
        },
        cells: Array.isArray(data.cells) ? data.cells.map((cell) => ({ ...cell })) : [],
    };
}

/** Serialise panel state into the payload the node parses. */
export function toPayload(state) {
    const payload = { version: 1, refs: {}, cells: state.cells || [] };
    if (String(state.prompt || "").trim()) payload.globalPrompt = String(state.prompt).trim();
    if (String(state.negative || "").trim()) payload.negativePrompt = String(state.negative).trim();
    payload.build = {
        views: [...(state.build?.views || [])],
        poses: [...(state.build?.poses || [])],
        expressions: [...(state.build?.expressions || [])],
    };
    payload.render = { background: String(state.background || "neutral") };
    const custom = String(state.backgroundCustom || "").trim();
    if (custom) payload.render.backgroundCustom = custom;
    // Which reference the backdrop comes from. Written whenever one is chosen, and written
    // even when empty for a "reference" backdrop so a saved workflow says it is one and
    // says nothing is picked (the node then falls back to neutral and warns).
    const backdropRef = String(state.backgroundRef || "").trim();
    if (backdropRef || payload.render.background === "reference") {
        payload.render.backgroundRef = backdropRef;
    }
    // How far a face blur reaches. Written even at the default so a saved workflow says
    // what it renders - the node's own default is the same value.
    payload.render.blurScope = blurScope(state);
    // Same idea for continuation: the sheet switch is written, the per-cell override
    // rides along on the cells themselves (state.cells is serialised as-is below).
    payload.render.continuity = continuity(state);
    payload.render.exportVideo = exportVideo(state);
    // Which resolution chip is chosen - derived from the node's own sizes, so a hand-typed size
    // reads as Custom ("") and the guidance ceiling applies again (see one_pass.one_pass_budget).
    payload.render.resolution = resolutionKeyFor(state, state.knobValues);
    // The preset ids ride along so a saved workflow can say how the settings started.
    if (String(state?.presetId || "").trim()) payload.render.preset = String(state.presetId).trim();
    if (String(state?.layoutPreset || "").trim()) {
        payload.render.layoutPreset = String(state.layoutPreset).trim();
    }
    // The suite's boards, in render order. Written only when there are any: a payload that says
    // "suite: []" and one that says nothing mean the same thing, and the shorter one is honest
    // about a single-sheet run.
    if (Array.isArray(state?.suite) && state.suite.length) {
        payload.render.suite = state.suite.map((id) => String(id)).filter((id) => id);
    }
    // A view preference, not a render setting: it decides whether the node draws its own
    // knob rows or leaves that to the panel. Recorded so it survives a reload.
    payload.ui = {
        compactKnobs: compactKnobs(state),
        nodePreviews: nodePreviews(state),
        panelPreview: panelPreview(state),
        autoRefresh: autoRefresh(state),
        suiteBoard: String(state.suiteBoard || ""),
        followBoard: followBoard(state),
    };
    // The sheet's own LoRA stack (the LoRAs tab). Written only when there is one: a payload that
    // says "loras: []" and one that says nothing mean the same thing, and the shorter one is
    // honest about a sheet that uses no LoRAs.
    const loras = loraStack(state);
    if (loras.length) payload.loras = loras;
    for (const group of REF_GROUPS) {
        payload.refs[group.key] = (state.refs?.[group.key] || [])
            .filter((item) => item && item.file)
            .map((item) => ({
                [group.file]: item.file,
                role: item.role || "",
                enabled: item.enabled !== false,
                // Every kind carries its decision: a picture and a clip are blurred (the clip
                // frame by frame), a sound is muted. Painting stays picture/clip only - a voice
                // has no pixels to paint on, so a `blurPaint` can never reach a sound slot.
                blurFace: blurMode(item),
                ...(Array.isArray(item.blurPaint) && item.blurPaint.length
                    ? { blurPaint: item.blurPaint }
                    : {}),
            }));
    }
    return payload;
}

/** Cells for "Build cells": body views vary by pose, face views by expression. */
export function buildCells(views, poses, expressions) {
    const cells = [];
    // A body view with no pose ticked, or a face view with no expression ticked,
    // still means "the neutral one" - the node builds it the same way.
    poses = poses.length ? poses : ["neutral"];
    expressions = expressions.length ? expressions : ["neutral"];
    for (const view of views) {
        if (view === "front" || view === "profile" || view === "back") {
            for (const pose of poses) {
                cells.push({ id: `${view}-${pose}-neutral`, view, pose, expression: "neutral" });
            }
        } else {
            for (const expression of expressions) {
                cells.push({ id: `${view}-neutral-${expression}`, view, pose: "neutral", expression });
            }
        }
    }
    return cells.slice(0, 24);
}

export function countRendered(refs) {
    let total = 0;
    for (const group of REF_GROUPS) {
        total += (refs[group.key] || []).filter((item) => item.file).length;
    }
    return total;
}

/** Slot indexes that hold a file, in slot order. */
export function filledIndexes(refs, groupKey) {
    return (refs[groupKey] || []).map((slot, index) => (slot.file ? index : -1)).filter((index) => index >= 0);
}

/** Swap (default) or shift a slot inside one group. Returns True when it moved. */
export function moveSlot(refs, groupKey, from, to, { swap = true } = {}) {
    const slots = refs[groupKey] || [];
    if (from === to || from < 0 || to < 0 || from >= slots.length || to >= slots.length) return false;
    if (swap) {
        [slots[from], slots[to]] = [slots[to], slots[from]];
    } else {
        const [moved] = slots.splice(from, 1);
        slots.splice(to, 0, moved);
    }
    return true;
}

/** First empty slot at or after ``start`` (wrapping once), else ``null``. */
export function nextFreeSlot(refs, groupKey, start = 0) {
    const slots = refs[groupKey] || [];
    for (let index = Math.max(0, start); index < slots.length; index += 1) {
        if (!slots[index].file) return index;
    }
    for (let index = 0; index < Math.min(start, slots.length); index += 1) {
        if (!slots[index].file) return index;
    }
    return null;
}

/** Does a dropped file belong in this group? (`accept` is an ``"image/*"`` style hint) */
export function fileMatchesGroup(file, group) {
    const type = String(file?.type || "");
    const prefix = String(group.accept || "").replace("/*", "/");
    if (type) return type.startsWith(prefix);
    const name = String(file?.name || "").toLowerCase();
    const suffix = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
    const extensions = {
        image: [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif"],
        video: [".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg"],
        audio: [".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".aiff"],
    }[group.kind] || [];
    return extensions.includes(suffix);
}

/** The `/view` URL for an input-relative path (what every /view needs). */
export function refViewUrl(file) {
    const text = String(file || "");
    const slash = text.lastIndexOf("/");
    const name = slash >= 0 ? text.slice(slash + 1) : text;
    const subfolder = slash >= 0 ? text.slice(0, slash) : "";
    return "/view?filename=" + encodeURIComponent(name)
        + "&type=input&subfolder=" + encodeURIComponent(subfolder);
}

/**
 * Clamp a media aspect ratio: references keep their own shape (a 3:4 portrait stays
 * portrait, a 16:9 clip stays wide) but an extreme panorama or a huge vertical photo
 * cannot dominate the row.
 */
export function clampAspect(ratio) {
    const value = Number(ratio);
    if (!Number.isFinite(value) || value <= 0) return null;
    // The floor is a phone portrait (9:16), not a sliver: a narrower tile has no room for
    // its own chrome - the kind chip (18px) and the enable checkbox (13px) share the 4px
    // top strip with the 18px hover buttons, and below ~46px they land on each other. A
    // taller-than-portrait reference letterboxes inside a 9:16 tile instead (object-fit:
    // contain), which is the shape the tile was always going to show it in.
    return Math.min(MAX_TILE_ASPECT, Math.max(MIN_TILE_ASPECT, Math.round(value * 1000) / 1000));
}


// --------------------------------------------------------------------------- //
// panel
// --------------------------------------------------------------------------- //
/**
 * A line of guidance: short on screen, the whole sentence on hover.
 *
 * After the card rails and the glyph ticks, these paragraphs were the last text-heavy thing in the
 * panel - one under the reference box, one under the prompt card, one under each tick group. The
 * information is worth keeping; the paragraph is not. So the short form is drawn and the long form
 * is the tooltip, which is the same trade the preset cards and the tile badges already make.
 */
function mutedHint(short, full = "") {
    const line = element("span", { className: "mmx-muted", textContent: short });
    if (full) line.title = full;
    return line;
}

/**
 * What is being dragged onto a stage cell right now, or null.
 *
 * One object, set on `dragstart` and read on `drop`: the framing, pose and expression ticks and the
 * reference tiles all feed it, and a stage cell is the one drop target. The cell's own defaults come
 * from the tick rows (that is the sheet's layout - see `buildCells`); this is how ONE cell is
 * overridden without changing the ticks for every other cell.
 */
let dragCell = null;

/**
 * Make a tick (or a tile) draggable onto a cell, without taking its click away.
 *
 * Click still toggles the tick; a drag carries a payload instead. The class is on the SOURCE so the
 * wall shows which control is in hand, and `dragCell` is cleared on dragend whatever happened - a
 * cancelled drag must not leave a payload armed for the next stray drop.
 */
function draggableOnto(node, payload) {
    node.draggable = true;
    node.addEventListener("dragstart", (event) => {
        dragCell = payload;
        node.classList.add("is-dragging");
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = "copy";
            event.dataTransfer.setData("text/plain", `mmx-cell:${payload.kind}:${payload.key}`);
        }
    });
    node.addEventListener("dragend", () => {
        dragCell = null;
        node.classList.remove("is-dragging");
    });
    return node;
}

/** The tick row a control belongs to, as the cell field it sets ("view"/"pose"/"expression"). */
function kindOfTicks(label) {
    const text = String(label || "").toLowerCase();
    if (text.startsWith("framing")) return "view";
    if (text.startsWith("pose")) return "pose";
    if (text.startsWith("expression")) return "expression";
    if (text.startsWith("background")) return "background";
    return "view";
}

function optionRow(label, options, selected, onToggle, group = "", { drag = true } = {}) {
    // Each group of ticks lives in its own rounded panel (see .mmx-tickgroup): the four
    // groups are one wall of checkboxes otherwise, and "which row am I in" has to be
    // answerable at a glance. The wrapper is returned AS the row, so call sites that just
    // append `views.row` get the panel for free.
    const wrap = element("div", { className: `mmx-tickgroup mmx-tickgroup--${group || "other"}` });
    const row = element("div", { className: "mmx-row" }, { marginBottom: "0" });
    row.append(element("span", { textContent: label, className: "mmx-tickgroup__label" }, { flex: "0 0 62px" }));
    const boxes = [];
    for (const [key, text] of options) {
        const id = `mmx-sheet-${label.replace(/\s+/g, "-")}-${key}`;
        const box = element("input", { type: "checkbox", id, checked: selected.has(key) });
        box.dataset.key = key;
        box.addEventListener("change", onToggle);
        const caption = element("label", { textContent: text, htmlFor: id }, { fontSize: "10px", marginRight: "4px" });
        // Every tick is also a thing you can put on ONE cell: drag it onto a panel on the stage and
        // that panel asks for it (the ticks stay the sheet's default - see `applyCellDrop`). A row
        // whose ticks are not per-cell choices (the suite's boards, where a tick is a whole SHEET)
        // passes drag:false - a board dragged onto a panel would mean nothing.
        if (drag) {
            draggableOnto(caption, {
                kind: kindOfTicks(label), key, label: `${kindOfTicks(label)}: ${text}`,
            });
        }
        boxes.push(box);
        row.append(box, caption);
    }
    wrap.append(row);
    return { row: wrap, boxes };
}

/**
 * A switch: the checkbox carries the value, the sibling track is what you read.
 *
 * The input stays the element everything talks to (the payload, the wiring hooks, the tests) and
 * the CSS lights the track with `input:checked + .mmx-switch`, so on/off is a state and not a
 * repaint. The track has to be the input's IMMEDIATE next sibling for that selector to match -
 * which is why both are appended together at every call site.
 */
function switchBox(id, checked) {
    const box = element("input", { type: "checkbox", id, checked: Boolean(checked) });
    box.classList.add("mmx-switch-box");
    return box;
}

function switchTrack() {
    return element("span", { className: "mmx-switch" });
}

/**
 * A slider for a bounded number knob, or null when a range is not worth one.
 *
 * The number box stays the control (it is typable, it is what the tests drive, and it carries the
 * clamping): the slider is the fast way to feel what a value costs - "8 steps", "1024px cells" -
 * and it writes through the same commit. It is skipped when the range is a handful of positions
 * (a "slider" with four stops is a lie) or so fine that dragging cannot land on a value.
 */
export /** Whether a kind can have something removed from it (blur, or mute for a sound). */
function kindRemovable(kind) {
    return kind === "image" || kind === "video" || kind === "audio";
}

export function numberSlider(knob) {
    const min = Number(knob.min);
    const max = Number(knob.max);
    const step = Number(knob.step) || 1;
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
    if (max - min <= step * 4) return null;
    if ((max - min) / step > 400) return null;
    const slider = element("input", { className: "mmx-knob__slider" });
    slider.type = "range";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);
    slider.value = String(Math.min(max, Math.max(min, Number(knob.value) || min)));
    slider.title = `${min} to ${max}, in steps of ${step}`;
    return slider;
}

function readChecks(boxes, fallback) {
    const values = boxes.filter((box) => box.checked).map((box) => box.dataset.key);
    return values.length ? values : fallback;
}

/**
 * The same ticks as ``optionRow``, drawn as pictures.
 *
 * Two of the three tick groups are shapes, not names: "Full body side" and "eyes" are read faster
 * as a figure and a pair of eyes than as words in a row of sixteen checkboxes. Each glyph is a
 * ``<label>`` wrapping a REAL checkbox (hidden, so the payload, ``readChecks`` and every test that
 * reads ``boxes`` are unchanged) plus the SVG mark - the browser toggles the box, ``change`` fires
 * the same handler the checkbox row used, and the tick under the picture lights up.
 */
function glyphRow(label, options, selected, onToggle, group = "", marks = {}) {
    const wrap = element("div", { className: `mmx-tickgroup mmx-tickgroup--${group || "other"}` });
    const head = element("div", { className: "mmx-row" }, { marginBottom: "0" });
    head.append(element("span", { textContent: label, className: "mmx-tickgroup__label" }));
    const row = element("div", { className: "mmx-tick" });
    const boxes = [];
    const paint = () => {
        for (const item of row.querySelectorAll(".mmx-glyph")) {
            const box = item.querySelector("input");
            item.classList.toggle("is-on", Boolean(box && box.checked));
        }
    };
    for (const [key, text] of options) {
        const item = element("label", { className: "mmx-glyph" });
        item.dataset.key = key;
        // The full sentence stays as the tooltip; under the picture goes the short word.
        item.title = text;
        const box = element("input", { type: "checkbox", checked: selected.has(key) },
            { display: "none" });
        box.dataset.key = key;
        box.addEventListener("change", () => {
            onToggle();
            paint();
        });
        // Paint once more after the browser has finished the label's activation: a click on the
        // picture and a click on the box are the same gesture, and the class has to follow the
        // settled state rather than whichever `change` happened to arrive first.
        item.addEventListener("click", () => paint());
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        use.setAttribute("href", `#${marks[key] || "mk-head"}`);
        svg.append(use);
        const short = text.replace(/^Full body /, "").replace(/ close up$/, "");
        draggableOnto(item, { kind: kindOfTicks(label), key, label: `${kindOfTicks(label)}: ${text}` });
        item.append(box, svg, element("span", { textContent: short }));
        boxes.push(box);
        row.append(item);
    }
    wrap.append(head, row);
    paint();
    return { row: wrap, boxes };
}


function selectBox(options, value, onChange, extraClass = "mmx-select") {
    const select = element("select", { className: extraClass });
    for (const [key, text] of options) {
        const option = element("option", { value: key, textContent: text });
        if (key === value) option.selected = true;
        select.append(option);
    }
    select.addEventListener("change", () => onChange(select.value));
    return select;
}

/**
 * A row of chips that set ONE value (B's "Blur area: Hair / Face only / Whole head").
 *
 * A dropdown hides the choice behind a click; chips show what the setting can be and which one is
 * set, which is the whole reason the mockup draws them this way. `key` rides on the element as
 * `data-choice` so a test can click a named chip.
 */
function chipChoice(label, options, value, onPick, hint = "") {
    const row = element("div", { className: "mmx-chiprow" });
    if (label) row.append(element("span", { className: "mmx-muted", textContent: label }));
    for (const [key, text] of options) {
        const on = key === value;
        const chip = button(text, () => onPick(key));
        chip.classList.add("mmx-chip");
        chip.classList.toggle("is-on", on);
        chip.dataset.choice = key;
        chip.setAttribute("aria-pressed", on ? "true" : "false");
        row.append(chip);
    }
    if (hint) row.append(element("span", { className: "mmx-muted mmx-chiprow__hint", textContent: hint }));
    return row;
}

function textInput(value, placeholder, onChange, extraClass = "mmx-input", style = {}) {
    const input = element("input", { type: "text", value, placeholder, className: extraClass }, style);
    input.addEventListener("input", () => onChange(input.value));
    return input;
}

/**
 * Build the whole in-node interface.
 *
 * Returns the container plus the refresh entry points the wiring file needs
 * (`refresh` after state changes, `renderResults` after a listing arrives).
 */
export function buildSheetInterface({ state, hooks = {} }) {
    const notify = (text) => hooks.status?.(text);
    const persist = () => hooks.stateChanged?.(toPayload(state));
    const viewUrl = (url) => hooks.assetUrl?.(url) || url;
    // The pack's own sample render, for a canvas with nothing in it (see PLACEHOLDER_ART). The path
    // is relative to the extension's web directory, so the HOST resolves it - the wiring knows its
    // own URL, the harness knows its own, and a bare module passes no hook and gets the plain hint.
    const placeholderArt = () => {
        const resolved = typeof hooks.packAsset === "function" ? hooks.packAsset(PLACEHOLDER_ART) : "";
        return resolved ? String(resolved) : "";
    };

    const container = element("div", { className: "mmx-sheet" });
    const styleTag = element("style", { textContent: PANEL_CSS });
    // The glyph sprite, mounted once with the styles: every mark the Cells tab draws is a <use>
    // against these symbols, so the whole picture vocabulary costs one copy of this markup.
    const sprite = element("div", {}, { display: "none", width: "0", height: "0" });
    sprite.innerHTML = GLYPH_SPRITE;
    container.append(styleTag, sprite);

    // ------------------------------------------------------------- header
    // One line, two facts: the title on the left, and on the right what will be drawn and at
    // what size - the sentence proposal B's header carries instead of a wall of prose.
    const header = element("div", { className: "mmx-row" });
    const headerStatus = element("span", { className: "mmx-chip mmx-status" });
    headerStatus.title = "What this sheet will draw, and at what size";
    // B's header is ONE line and two facts - the name and what will be drawn at what size - so
    // the plumbing (browse, upload, clear, rebuild, refresh, auto-refresh) lives where it acts:
    // Browse / Add Media / Clear in the references card's head, the sheet-folder actions in the
    // control column's foot next to Render. A header full of buttons was most of why the panel
    // read as a form rather than as B's studio.
    header.append(
        element("span", {
            textContent: "Character Sheet Builder",
            className: "mmx-title",
            // The build tag used to sit next to the title as a bare string; it is a diagnostic,
            // so it belongs in the tooltip rather than in the site of the panel's name.
            title: `Panel build ${PANEL_BUILD} — if this is older than the pack on disk, reload`
                + " the page (Ctrl+Shift+R): a tab keeps the module it loaded first.",
        }),
        element("span", { className: "mmx-spacer" }),
        headerStatus,
    );
    // Auto-refresh OFF by default: polling the sheet folder is a background read the user did
    // not ask for, and the Results tabs are one click away. The button beside it does the same
    // read once, on demand. (A run still polls while it renders, so cells appear as they land -
    // that timer stops with the run.) The choice is remembered in the payload.
    const auto = element("input", { type: "checkbox", checked: autoRefresh(state) });
    auto.title = "Poll the sheet folder in the background (off: use Refresh)";
    auto.dataset.mmxSheetAuto = "1";
    auto.addEventListener("change", () => {
        state.autoRefresh = auto.checked;
        persist();
        notify(auto.checked ? "auto-refresh on - the Results tab follows the sheet folder" : "auto-refresh off - use Refresh");
    });
    const autoLabel = element("span", { textContent: "auto", className: "mmx-muted" });
    autoLabel.title = "Poll the sheet folder in the background (off: use Refresh)";
    const clearButton = button("Clear sheet", async () => {
        try {
            await hooks.clearSheet?.(boardName());
            notify("sheet folder cleared.");
            await refreshResults();
        } catch (error) {
            notify(`clear failed: ${error.message}`);
        }
    });
    clearButton.classList.add("mmx-btn--quiet");
    clearButton.dataset.action = "clear-sheet";
    clearButton.title = "Remove the sheet folder this run writes (frames, cells, picks)";
    container.append(header);

    // ------------------------------------------------------- resolution control
    // Square buttons, one lit at a time. This is the ONLY thing that moves a size: the presets
    // deliberately do not (see presets.py), so a chip can never be undone by applying a layout,
    // and a size typed into the Settings tab simply reads as Custom.
    const resRow = element("div", { className: "mmx-row mmx-resolutions" });
    const resNote = element("span", { className: "mmx-muted" }, { flex: "1 1 200px", fontSize: "10px" });
    const resButtons = new Map();

    /**
     * Proposal B's stage: the SHEET being built, drawn panel by panel.
     *
     * The layout you picked decides the arrangement (same `artShape` the cards use), each panel is
     * one cell of the run and says which framing it is, and the cell being rendered wears the live
     * frame - which is what B's caption promises ("the sheet appears here as it denoises"). A run
     * with no cells yet draws the cells the ticks ask for, so the stage is never empty.
     */
    function sheetPreview() {
        const wrap = element("div", { className: "mmx-stage__sheet" });
        const layout = presetList.find((item) => item.id === String(state.layoutPreset || ""));
        // The run's own panels, or the ones the ticks imply before anything is dropped on them
        // (`plannedCellsFromTicks`). Both are cells in the same shape, so a drop has a home either
        // way - `editableCells` materialises the plan the moment one lands.
        const cells = state.cells?.length ? state.cells : plannedCellsFromTicks();
        const shape = layout ? artShape(layout) : { cls: cells.length > 4 ? "is-grid6" : "is-grid4", count: Math.max(1, cells.length) };
        wrap.classList.add(shape.cls);
        // How many panels are DRAWN: the arrangement decides, and the count is what a reader can
        // see (the plan's own total is in the line under the sheet).
        wrap.dataset.cells = String(shape.count);
        wrap.title = layout
            ? `${layout.label} — ${cells.length} cell(s). The panels fill in as the render runs.`
            : `${cells.length} cell(s). Pick a layout on the right to change the arrangement.`;
        const live = livePreviewCell();
        for (let index = 0; index < shape.count; index += 1) {
            const cell = cells[index];
            const box = element("div", { className: "mmx-cellbox" });
            if (!cell) {
                box.classList.add("is-empty");
                box.append(element("span", { className: "mmx-cellbox__view", textContent: "+" }));
                wrap.append(box);
                continue;
            }
            box.dataset.cell = cell.id;
            box.dataset.index = String(index);
            if (cell.frames?.length) box.classList.add("has-frames");
            if (live && index === live.index) {
                box.classList.add("is-live");
                box.style.setProperty("--mmx-cell-shot", `url("${live.image}")`);
            }
            // What this ONE panel asks for. The ticks decide the sheet; a drop replaces the cell's
            // own framing/pose/expression (or its face reference), which is how a sheet is built
            // panel by panel instead of only as a cross product.
            box.append(
                element("span", { className: "mmx-cellbox__view", textContent: cellLabel(cell) }),
                element("span", { className: "mmx-cellbox__meta", textContent: cellMeta(cell) }),
            );
            box.title = cellTitle(cell, index);
            wireCellDrop(box, index);
            if (cellIsCustom(cell, index)) {
                box.classList.add("is-custom");
                const reset = button("×", () => resetCell(index));
                reset.classList.add("mmx-cellbox__reset");
                reset.dataset.action = "cell-reset";
                reset.title = "Back to what the ticks ask for in this panel";
                box.append(reset);
            }
            wrap.append(box);
        }
        return wrap;
    }

    /* ------------------------------------------------------- one cell at a time
     * The ticks are the sheet's DEFAULT (see buildCells): a cross product of what is ticked. Every
     * panel on the stage is also a drop target, so a framing, a pose, an expression or a reference
     * can be put on ONE panel - "this sheet is a turnaround, except this close-up is a smile taken
     * from the other picture" - without disturbing the other panels' defaults.
     */

    /** The cells the ticks imply, in the order `buildCells` would make them. */
    function plannedCellsFromTicks() {
        const build = state.build || {};
        return buildCells(
            build.views?.length ? build.views : ["front"],
            build.poses?.length ? build.poses : ["neutral"],
            build.expressions?.length ? build.expressions : ["neutral"],
        );
    }

    /**
     * The panels the user edited by hand, keyed by cell id, so a tick change can rebuild the list
     * around them (see `syncBuild`).
     *
     * What counts as edited is measured against the plan, not stored as a flag: a panel that
     * differs from what the ticks would have made is a panel somebody chose, and a panel whose id
     * is no longer in the plan (its framing was unticked) takes its edit with it.
     */
    function collectCellEdits() {
        const edits = {};
        const plan = plannedCellsFromTicks();
        for (const [index, cell] of (state.cells || []).entries()) {
            if (!cell?.id) continue;
            const planned = plan[index];
            const diff = {};
            if (planned) {
                if (cell.view !== planned.view) diff.view = cell.view;
                if (cell.pose !== planned.pose) diff.pose = cell.pose;
                if (cell.expression !== planned.expression) diff.expression = cell.expression;
            }
            if (cell.faceRef) diff.faceRef = cell.faceRef;
            if (Object.keys(diff).length) edits[cell.id] = diff;
        }
        return edits;
    }

    /** The cell list to edit: the run's own, or the ticks' plan materialised so a drop has a home. */
    function editableCells() {
        if (!state.cells?.length) state.cells = plannedCellsFromTicks();
        return state.cells;
    }

    /** The default the ticks give the panel at `index`, or null. */
    function tickDefaultAt(index) {
        return plannedCellsFromTicks()[index] || null;
    }

    /** Whether this panel asks for something the ticks do not (the box is marked, and resettable). */
    function cellIsCustom(cell, index) {
        if (cell.faceRef) return true;
        const planned = tickDefaultAt(index);
        if (!planned) return false;
        return cell.view !== planned.view || cell.pose !== planned.pose
            || cell.expression !== planned.expression;
    }

    function wireCellDrop(box, index) {
        box.addEventListener("dragover", (event) => {
            if (!dragCell) return;
            event.preventDefault();
            event.stopPropagation();
            if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
            box.classList.add("is-drop");
        });
        box.addEventListener("dragleave", () => box.classList.remove("is-drop"));
        box.addEventListener("drop", (event) => {
            box.classList.remove("is-drop");
            event.preventDefault();
            event.stopPropagation();
            const payload = dragCell;
            dragCell = null;
            if (payload) applyCellDrop(index, payload);
        });
    }

    /** Put what was dropped onto one panel, and persist the panel list with it. */
    function applyCellDrop(index, payload) {
        const cells = editableCells();
        const cell = cells[index];
        if (!cell) return;
        if (payload.kind === "ref") {
            cell.faceRef = `${payload.group.key}:${payload.index}`;
            notify(`${cell.id}: the face comes from ${payload.label}.`);
        } else if (payload.kind === "background") {
            // The backdrop is a sheet-wide setting, not a per-panel one: say so instead of
            // silently writing a field the node does not read.
            state.background = payload.key;
            notify(`Backdrop: ${payload.label}. It applies to every panel.`);
        } else {
            cell[payload.kind] = payload.key;
            notify(`${cell.id}: ${payload.label}.`);
        }
        persist();
        refresh();
    }

    /** Drop the overrides from one panel: back to what the ticks ask for. */
    function resetCell(index) {
        const cells = state.cells || [];
        const cell = cells[index];
        if (!cell) return;
        delete cell.faceRef;
        const planned = tickDefaultAt(index);
        if (planned) {
            cell.view = planned.view;
            cell.pose = planned.pose;
            cell.expression = planned.expression;
        }
        persist();
        refresh();
    }

    /** The panel's own line: the framing, then what it does with the pose or the expression. */
    function cellLabel(cell) {
        // Short words, the way the glyphs are captioned: a panel is 150px wide, and "Full body
        // side · Neutral" is a paragraph in it.
        const short = (text) => String(text || "")
            .replace(/^Full body /, "").replace(/ close up$/, "").replace(/^Head profile$/, "profile");
        const view = short(viewShort(cell.view));
        if (["face", "portrait"].includes(String(cell.view))) {
            const expression = (EXPRESSIONS.find(([key]) => key === cell.expression) || [])[1];
            return `${view} · ${short(expression || "neutral")}`;
        }
        if (["front", "profile", "back"].includes(String(cell.view))) {
            const pose = (POSES.find(([key]) => key === cell.pose) || [])[1];
            return `${view} · ${short(pose || "neutral")}`;
        }
        return view;
    }

    /** The panel's second line: the face it takes its likeness from, and what it has on disk. */
    function cellMeta(cell) {
        const bits = [];
        if (cell.faceRef) bits.push(`face: ${refLabelFor(cell.faceRef)}`);
        bits.push(cell.frames?.length ? "rendered" : `${cell.frames || 0}f`);
        return bits.join(" · ");
    }

    function cellTitle(cell, index) {
        const lines = [
            `${cell.id} - panel ${index + 1}`,
            `framing: ${viewShort(cell.view)}`,
            `pose: ${cell.pose}`,
            `expression: ${cell.expression}`,
            cell.faceRef ? `face reference: ${refLabelFor(cell.faceRef)}` : "",
            "Drop a framing, a pose, an expression or a reference tile here to set this panel "
                + "alone; the ticks stay the default for the rest.",
        ];
        return lines.filter(Boolean).join("\n");
    }

    /** "pictures:1" -> "Picture 2" (the tag the prompt will use), for a cell's face badge. */
    function refLabelFor(spec) {
        const [key, raw] = String(spec || "").split(":");
        const group = REF_GROUPS.find((item) => item.key === key);
        if (!group) return String(spec || "");
        return `${group.label.slice(0, -1)} ${Number(raw) + 1}`;
    }

    /** Swap the stage preview for a freshly drawn one (small: one panel per cell). */
    function repaintStagePreview() {
        const current = container.querySelector(".mmx-stage__sheet");
        if (!current) return;
        current.replaceWith(sheetPreview());
    }

    /**
     * The stage's caption: the live facts under the sheet, and what the sheet is when idle.
     *
     * A lookup rather than a stored node because the pane is rebuilt on every refresh, and the
     * caption belongs to the pane (the stage), not to the module.
     */
    function syncStageCaption() {
        const caption = container.querySelector("[data-mm-stage-caption]");
        const slot = caption?.querySelector(".mmx-stage__caption__live");
        if (!slot) return;
        slot.textContent = liveMetaText;
        caption.classList.toggle("is-live", Boolean(liveMetaText));
    }

    /** The live frame and the cell index it belongs to, or null when nothing is streaming. */
    function livePreviewCell() {
        if (!liveLast || !liveFrames.length || panelPreview(state) === "off") return null;
        // A ONE-PASS stream is the whole sheet, not one of its panels: painting it into a panel's
        // box would show five panels inside panel 1 - and the box would keep wearing that sheet
        // after the run, which is exactly "my cell was replaced by the rendered image". The sheet
        // belongs in the live strip and on the Preview tab (both of which take it); the plan's own
        // boxes stay the plan.
        if (liveLast.whole_sheet === true) return null;
        const cell = Number(liveLast.cell) || 0;
        return { index: cell > 1 ? cell - 1 : 0, image: liveFrames[0] };
    }

    /** The short label a panel shows: the vocabulary's own word for the framing. */
    function viewShort(key) {
        const found = VIEWS.find(([id]) => id === String(key || ""));
        return found ? found[1] : String(key || "cell");
    }

    /** The header's fact: the sheet being drawn, and the sizes it will be drawn at. */
    function syncHeaderStatus() {
        const layout = (presetList || []).find((item) => item.id === String(state.layoutPreset || ""));
        const cells = state.cells?.length || 0;
        const what = layout
            ? `${layout.label}`
            : (state.suite?.length ? `${state.suite.length} sheets` : `${cells} cell${cells === 1 ? "" : "s"}`);
        // The label of the card that is lit, or "Custom" when the sizes were typed by hand: the
        // header is one line, and the numbers themselves are on the cards below it.
        const active = resolutionKeyFor(state, state.knobValues);
        const choice = resolutionChoices(state).find((entry) => String(entry.key) === active);
        const size = choice ? String(choice.label) : "Custom";
        headerStatus.textContent = [what, size].filter(Boolean).join(" · ");
    }

    function renderResolutions() {
        const active = resolutionKeyFor(state, state.knobValues);
        for (const [key, node] of resButtons) {
            const on = key === active;
            node.classList.toggle("is-active", on);
            node.setAttribute("aria-pressed", on ? "true" : "false");
        }
        const choice = resolutionChoices(state).find((entry) => String(entry.key) === active);
        resNote.textContent = resolutionLabel(state, state.knobValues)
            + (choice && choice.hint ? ` — ${choice.hint}` : "");
        syncHeaderStatus();
    }

    function fillResolutions(list) {
        const choices = Array.isArray(list) && list.filter((entry) => entry?.key).length
            ? list
            : RESOLUTION_FALLBACK;
        // Kept on the state so every reader (the chips, the payload, a test) sees one table.
        state.resolutions = choices;
        resButtons.clear();
        // No label on this row: the three cards say what they are ("1080p / 1088px sheet /
        // 1024px cells"), and a word plus a 96px gap on the left was eating a third of the row
        // and pushing the sizes into a corner.
        resRow.replaceChildren();
        for (const choice of choices) {
            // A card rather than a chip: the proposal puts the numbers ON the size, so the
            // price of 4K is legible without hovering anything.
            const node = button("", () => applyResolution(choice));
            node.classList.add("mmx-rescard");
            node.dataset.resolution = choice.key;
            node.setAttribute("aria-pressed", "false");
            node.title = `${choice.sheetShortEdge}px sheet and ${choice.cellShortEdge}px cells`
                + (choice.hint ? ` — ${choice.hint}` : "");
            node.append(
                element("span", { className: "mmx-rescard__label", textContent: String(choice.label) }),
                element("span", {
                    className: "mmx-rescard__size",
                    textContent: `${choice.sheetShortEdge}px sheet`,
                }),
                element("span", {
                    className: "mmx-rescard__cells",
                    textContent: `${choice.cellShortEdge}px cells`,
                }),
            );
            resButtons.set(String(choice.key), node);
            resRow.append(node);
        }
        resRow.append(resNote);
        resRow.setAttribute("aria-label", "Sheet resolution");
        renderResolutions();
    }

    async function applyResolution(choice) {
        try {
            await hooks.applyWidgets?.({
                sheet_short_edge: choice.sheetShortEdge,
                cell_size: choice.cellShortEdge,
            });
        } catch (error) {
            notify(`resolution partly applied: ${error.message}`);
        }
        // The Settings tab draws these same knobs, so it has to re-read them or the panel would
        // be showing a size the render is not using.
        syncSettings();
        persist();
        renderResolutions();
        await refreshPlan();
        notify(`resolution: ${choice.label} — ${choice.sheetShortEdge}px sheet, `
            + `${choice.cellShortEdge}px cells`);
    }

    // -------------------------------------------------------------- presets
    // Two axes, one list: a LAYOUT preset says what to draw (cells, arrangement, cell shape) and
    // a QUALITY preset says how to sample it (mode, steps, reference sizing, continuation). The
    // list comes from the pack's backend (h3_character_sheet/presets.py) so it is one definition,
    // not two, and neither axis touches the sizes the resolution control owns.
    const presetsRow = element("div", { className: "mmx-row mmx-presets" });
    // Two RAILS, not two dropdowns: a layout preset is a picture of a sheet (its own cells, drawn),
    // and a quality preset is a picture of how many clips come out. The list is still the backend's
    // (presets.py) - the cards are built from each preset's own ticks, so they cannot drift from
    // what applying it does.
    const layoutSelect = element("div", { className: "mmx-rail" });
    layoutSelect.dataset.action = "layout-preset";
    // The quality axis is B's SEGMENTED CONTROL, not a second card wall: "how is the sheet
    // sampled" is one choice between two or three named ways, and a segment says that on one
    // line where three art cards said it in 220px of column. The cards' sentences are not lost -
    // they are the segment's tooltips (a segment has no room for "6 cells · faces").
    const presetSelect = element("div", { className: "mmx-seg" });
    presetSelect.dataset.action = "preset";
    // One line, and NOT a flexible one: the presets row became a COLUMN when the rails landed, and
    // a row-era "flex: 1 1 240px" in a column is a 240px-tall empty band under the cards (it was
    // the dead space in the middle of the panel).
    const presetHint = element("span", { className: "mmx-muted" }, { flex: "0 0 auto" });
    let presetList = [];
    // The panel's own last render of each layout (id -> {url, name}), used as card art. Derived
    // data: it is a picture of what is on disk right now, so it is never persisted.
    let galleryArt = {};
    let presetsStore = "";

    /** Fill one axis' selector: the presets of that kind, plus the "no preset" first entry. */
    /** How many cells a preset's own ticks build (1 when a tick list is empty). */
    function presetCellCount(entry) {
        const axis = (key) => {
            const values = entry?.build?.[key];
            return Array.isArray(values) && values.length ? values.length : 1;
        };
        return axis("views") * axis("poses") * axis("expressions");
    }

    /** The arrangement classes a card's wireframe draws, from the preset's own shape. */
    /**
     * The shape of an arrangement: how many panels, and which of the drawn layouts it is.
     *
     * One function because two things need to agree: the little picture on a preset card and the
     * STAGE (proposal B's big preview of the sheet being built). If they disagreed, the card you
     * picked would not look like the sheet you got.
     */
    function artShape(entry) {
        const kind = entry?.kind || "quality";
        if (kind === "quality") {
            const perCell = entry.render?.singlePass === false;
            return { cls: perCell ? "is-row" : "is-one", count: perCell ? 3 : 1 };
        }
        const layout = String(entry?.sheet?.layout || "");
        const count = presetCellCount(entry);
        if (layout === "hero-left") return { cls: "is-hero", count: 5 };
        if (count >= 6 || Number(entry?.sheet?.columns) >= 3) return { cls: "is-grid6", count: 6 };
        if (count === 3 || layout === "turnaround") return { cls: "is-row", count: 3 };
        return { cls: "is-grid4", count: 4 };
    }

    function presetArt(entry) {
        const kind = entry.kind || "quality";
        const art = element("div", { className: "mmx-pcard__art" });
        if (kind === "suite") {
            art.classList.add("is-suite");
            for (const [index, boardId] of (entry.boards || []).slice(0, 4).entries()) {
                const inner = element("i", { className: `a${index + 1}` });
                const board = presetList.find((item) => item.id === boardId);
                const count = board ? Math.min(presetCellCount(board), index === 0 ? 5 : 6) : 4;
                for (let step = 0; step < count; step += 1) inner.append(element("b"));
                art.append(inner);
            }
            return art;
        }
        if (kind === "quality") {
            // How many clips: one wide frame for the one-pass sheet, a strip for per-cell.
            const perCell = entry.render?.singlePass === false;
            art.classList.add(perCell ? "is-row" : "is-one");
            for (let step = 0; step < (perCell ? 3 : 1); step += 1) art.append(element("i"));
            return art;
        }
        // One shape decision, shared with the stage's sheet preview (see `artShape`): the card
        // you picked and the sheet you get are the same arrangement or the rail is lying.
        const shape = artShape(entry);
        art.classList.add(shape.cls);
        for (let step = 0; step < shape.count; step += 1) art.append(element("i"));
        return art;
    }

    /** One clickable card: arrangement picture, name, and what it costs. */
    function presetCard(entry, kind, onPick) {
        const card = element("button", { className: "mmx-pcard", type: "button" });
        card.dataset.presetId = entry.id;
        card.append(presetArt(entry));
        // The card wears your own last render of this layout when there is one AND the "your
        // renders on the cards" switch is on (see `cardArt`); otherwise it keeps the drawn
        // arrangement, which is what the card is for - "which sheet, and how many cells".
        const art = cardArt(state) ? galleryArt[String(entry.id || "").toLowerCase()] : null;
        if (art?.url) {
            card.classList.add("has-art");
            card.style.setProperty("--mmx-card-art", `url("${art.url}")`);
            card.append(element("span", {
                className: "mmx-pcard__live",
                textContent: "yours",
                title: `Card art: your last render of this layout (${art.name})`,
            }));
        }
        card.append(element("span", { className: "mmx-pcard__name", textContent: entry.label }));
        const meta = kind === "suite"
            ? `${(entry.boards || []).length} sheets`
            : (kind === "quality"
                ? (entry.render?.singlePass === false ? "per cell" : "one render")
                : `${presetCellCount(entry)} cell(s)`);
        card.append(element("span", { className: "mmx-pcard__meta", textContent: meta }));
        // The hint is a tooltip now: the sentence is one hover away instead of always on screen.
        const changed = Array.isArray(entry.deviates) ? entry.deviates : [];
        card.title = `${entry.hint}`
            + (entry.build && Object.keys(entry.build).length ? " Builds its cells." : "")
            + (changed.length
                ? ` Changes: ${changed.map((name) => labelOf(name)).join(", ")}.`
                : " Matches the node's own defaults.");
        card.setAttribute("aria-pressed", "false");
        card.addEventListener("click", () => onPick(entry));
        return card;
    }

    /**
     * The short form of a preset's label, for the segmented control.
     *
     * B's segment reads "One pass | Per cell": two or three words, because a segment is a
     * word-wide control. The pack's labels are sentences ("Per-cell renders (classic)"), so the
     * parenthetical goes, then the trailing noun that the segment's neighbours already imply
     * ("sheet", "renders", "fidelity"). Nothing is thrown away - the full label and the hint
     * stay in the tooltip.
     */
    function segLabel(entry) {
        const words = String(entry?.label || entry?.id || "")
            .replace(/\([^)]*\)/g, " ")
            .split(/[^A-Za-z0-9]+/)
            .filter(Boolean);
        while (words.length > 2
            && /^(sheet|sheets|render|renders|cell|cells|mode|classic|default|fidelity)$/i
                .test(words[words.length - 1])) {
            words.pop();
        }
        const short = words.slice(0, 3).join(" ");
        return short || String(entry?.label || "");
    }

    /** Fill the quality axis' segmented control from the same list the rails read. */
    function fillPresetSeg(seg, ofKind, currentId, onPick) {
        seg.replaceChildren();
        for (const entry of ofKind) {
            const node = button(segLabel(entry), () => {
                // Clicking the LIT segment clears the choice. A segment has no "Custom" entry the
                // way a card rail does, and the panel still has to be able to say "no quality
                // preset" - otherwise the payload would keep claiming settings the user has since
                // moved. Read from the DOM rather than from a captured flag: the segment is not
                // rebuilt when a preset is applied, only re-lit.
                const lit = seg.querySelector(".is-active")?.dataset.presetId || "";
                onPick(String(entry.id) === lit ? null : entry);
            });
            node.classList.add("mmx-btn");
            node.dataset.presetId = String(entry.id);
            node.setAttribute("aria-pressed", "false");
            node.title = `${entry.label} — ${entry.hint} (click again to clear)`;
            seg.append(node);
        }
        return ofKind.some((entry) => entry.id === currentId) ? currentId : "";
    }

    function fillPresetRail(rail, kind, currentId, onPick) {
        // The layout rail carries the suites too: a suite says WHICH sheets render, which is the
        // layout axis' question (the quality axis only decides how they are sampled).
        const ofKind = presetList.filter((entry) => {
            const entryKind = entry.kind || "quality";
            return entryKind === kind || (kind === "layout" && entryKind === "suite");
        });
        const custom = element("button", { className: "mmx-pcard mmx-pcard--custom", type: "button" });
        custom.dataset.presetId = "";
        custom.append(element("div", { className: "mmx-pcard__art" }));
        custom.append(element("span", { className: "mmx-pcard__name",
            textContent: kind === "layout" ? "Custom layout" : "Custom settings" }));
        custom.append(element("span", { className: "mmx-pcard__meta",
            textContent: kind === "layout" ? "as authored" : "as on the node" }));
        custom.title = kind === "layout"
            ? "No layout preset: the cells stay exactly as you authored them."
            : "No quality preset: the node keeps the settings it has now.";
        custom.setAttribute("aria-pressed", "false");
        custom.addEventListener("click", () => onPick(null));
        rail.replaceChildren(custom);
        for (const entry of ofKind) rail.append(presetCard(entry, entry.kind || kind, onPick));
        return ofKind.some((entry) => entry.id === currentId) ? currentId : "";
    }

    /**
     * Which quality segment reads as lit when no preset was ever applied.
     *
     * A fresh node is ONE-PASS (the `single_pass` widget's own default) and no preset has been
     * chosen, so the segment used to show nothing at all: the mode the render is in is the one
     * thing that row says, and "nothing lit" reads as "unknown" rather than as the default. The
     * node's own knob is the truth, so the segment is lit from it when the panel has no record -
     * and clicking that segment still APPLIES the preset, so the lit state is a description, not a
     * lock.
     */
    function litModeId() {
        const chosen = String(state.presetId || "");
        if (chosen) return chosen;
        const onePass = state.knobValues?.single_pass !== false;
        const quality = presetList.filter((entry) => (entry.kind || "quality") === "quality");
        // `render.singlePass` is the payload's own name for the knob (presets.py), and the node's
        // knob is written as `single_pass`: read either, so the two cannot disagree.
        const match = quality.find((entry) => {
            const wants = entry.render?.singlePass ?? entry.widgets?.single_pass;
            return wants === undefined || Boolean(wants) === onePass;
        });
        return match ? String(match.id) : "";
    }

    /** Light the cards on both axes to match the state (the record, not a second copy). */
    function renderPresetRails() {
        const active = { "": state.presetId, layout: state.layoutPreset };
        for (const [axis, rail] of [["", presetSelect], ["layout", layoutSelect]]) {
            const current = axis === "layout"
                ? String(state.layoutPreset || "")
                : litModeId();
            for (const card of rail.querySelectorAll("[data-preset-id]")) {
                const on = String(card.dataset.presetId || "") === current;
                card.classList.toggle("is-active", on);
                card.setAttribute("aria-pressed", on ? "true" : "false");
            }
            void active;
        }
    }

    function fillPresets(list, currentId = "") {
        presetList = Array.isArray(list) ? list : [];
        fillPresetSeg(presetSelect, presetList.filter((entry) => (entry.kind || "quality") === "quality"),
            currentId || String(state.presetId || ""), (entry) => {
                void applyQualityCard(entry);
            });
        fillPresetRail(layoutSelect, "layout", String(state.layoutPreset || ""), (entry) => {
            void applyLayoutCard(entry);
        });
        renderPresetRails();
        updateDeleteButton();
        showHint();
    }

    async function applyQualityCard(entry) {
        if (!entry) {
            state.presetId = "";
            renderPresetRails();
            updateDeleteButton();
            showHint();
            persist();
            notify("preset cleared - the settings stay as they are");
            return;
        }
        await applyPreset(entry);
        updateDeleteButton();
        showHint();
    }

    async function applyLayoutCard(entry) {
        if (!entry) {
            state.layoutPreset = "";
            state.suite = [];
            state.suiteBoard = "";
            renderPresetRails();
            // The line under the rails says what is set now, and it just changed.
            showHint();
            persist();
            notify("layout cleared - the cells stay as they are");
            return;
        }
        await applyPreset(entry);
        // The quality rail refreshed the hint and this one did not, so the line kept saying "pick a
        // sheet on the left rail" after a layout (or a suite) had been applied.
        showHint();
    }

    function showHint() {
        const entry = presetList.find((item) => item.id === String(state.presetId || ""));
        const layout = presetList.find((item) => item.id === String(state.layoutPreset || ""));
        // One line, and only the part that is a fact: what is set now. The sentences that used to
        // fill this bar live on the cards, one hover away.
        const parts = [];
        if (entry) parts.push(entry.label);
        if (layout) parts.push(layout.label);
        const sheets = (state.suite || []).length;
        if (!parts.length && !sheets) {
            presetHint.textContent = "Pick a sheet on the left rail; the resolution buttons set the "
                + "sizes. Hover a card for what it does.";
            return;
        }
        if (!parts.length) parts.push("Custom suite");
        const cells = state.cells?.length || presetCellCount(layout || entry || {});
        // A LoRA stack changes what renders as much as the layout does, and it has no card on the
        // rail: the one line the panel has for "this is what will render" says it.
        const stack = loraStack(state).filter((row) => row.on);
        presetHint.textContent = `${parts.join(" · ")} — ${sheets
            ? `${sheets} sheet${sheets === 1 ? "" : "s"}`
            : `${cells} cell(s)`}${stack.length
            ? ` + ${stack.length} LoRA${stack.length === 1 ? "" : "s"}` : ""}`;
    }

    /** Widget name -> what a person calls it, for the "changes:" line. */
    function labelOf(name) {
        const words = String(name || "").replace(/^sheet_/, "sheet ").replace(/_/g, " ");
        return words.charAt(0).toUpperCase() + words.slice(1);
    }

    /**
     * The settings on this node right now, as a preset body.
     *
     * What "save" means is "what I have", so the widget values come from the node itself
     * (hooks.readWidgets filled state.knobValues) rather than from a second copy the panel
     * keeps - a preset saved here has to reproduce the render, not the panel's idea of it.
     */
    function currentPresetBody(name) {
        const widgets = {};
        for (const [key, value] of Object.entries(state.knobValues || {})) {
            if (value === undefined || value === null || typeof value === "object") continue;
            widgets[key] = value;
        }
        const render = {
            continuity: continuity(state),
            exportVideo: exportVideo(state),
            background: String(state.background || "neutral"),
            blurScope: blurScope(state),
        };
        // The backdrop can BE a reference: remember which one, not just that it was one.
        if (String(state.background || "") === "reference") {
            render.backgroundRef = String(state.backgroundRef || "");
        }
        if (widgets.frames_per_cell !== undefined) render.framesPerCell = widgets.frames_per_cell;
        const ticks = state.build || {};
        return {
            name,
            render,
            widgets,
            sheet: {
                layout: widgets.sheet_layout,
                columns: widgets.sheet_columns,
                aspect: widgets.sheet_aspect,
                shortEdge: widgets.sheet_short_edge,
            },
            build: {
                views: [...(ticks.views || [])],
                poses: [...(ticks.poses || [])],
                expressions: [...(ticks.expressions || [])],
            },
        };
    }

    async function applyPreset(entry) {
        // render.* keys the panel owns (continuation, clip export, backdrop, ...). singlePass is a
        // NODE knob rather than panel state, so it is collected here and written with the preset's
        // widget group below - a suite that says "four one-pass renders" must not inherit a node
        // left in per-cell mode and render 19 clips instead.
        const knobs = {};
        for (const [key, value] of Object.entries(entry.render || {})) {
            if (key === "continuity") state.continuity = value;
            else if (key === "exportVideo") state.exportVideo = value;
            else if (key === "background") state.background = String(value || "neutral");
            else if (key === "backgroundRef") state.backgroundRef = String(value || "");
            else if (key === "singlePass") knobs.single_pass = Boolean(value);
        }
        let built = 0;
        if (entry.build && Object.keys(entry.build).length) {
            // The preset says which cells it is FOR, so applying it also BUILDS them: picking
            // "Full Character Sheet - Balanced" and then having to tick five boxes by hand was
            // the whole friction. A preset with no ticks (the settings-only ones) leaves an
            // existing cell list exactly as it is, and "Clear cells" still empties it.
            for (const [key, values] of Object.entries(entry.build)) {
                if (Array.isArray(values) && values.length) state.build[key] = [...values];
            }
            const cells = buildCells(
                state.build.views || [], state.build.poses || [], state.build.expressions || [],
            );
            if (cells.length) {
                state.cells = cells;
                built = cells.length;
            }
        }
        // The record lands on the axis the preset belongs to, so applying a layout after a
        // quality preset (or the other way round) cannot erase the other one's provenance. A
        // suite rides the layout axis, and picking one layout after it means one sheet again.
        const kind = entry.kind || "quality";
        if (kind === "suite") {
            state.suite = Array.isArray(entry.boards) ? [...entry.boards] : [];
            state.layoutPreset = entry.id;
            // A different suite means different boards: the remembered board would name a folder
            // the new run does not have, so the panel goes back to this run's first board.
            state.suiteBoard = "";
        } else if (kind === "layout") {
            state.layoutPreset = entry.id;
            state.suite = [];
            state.suiteBoard = "";
        } else {
            state.presetId = entry.id;
        }
        // The node's knobs: the preset's widget group plus its sheet group, mapped onto the
        // widgets that carry layout (which the panel does not own).
        const widgets = { ...knobs, ...(entry.widgets || {}) };
        const sheet = entry.sheet || {};
        if (sheet.layout) widgets.sheet_layout = sheet.layout;
        if (sheet.columns) widgets.sheet_columns = sheet.columns;
        if (sheet.aspect) widgets.sheet_aspect = sheet.aspect;
        if (sheet.shortEdge) widgets.sheet_short_edge = sheet.shortEdge;
        try {
            await hooks.applyWidgets?.(widgets);
        } catch (error) {
            notify(`preset partly applied: ${error.message}`);
        }
        // The Settings tab draws these same knobs: a preset that moved cell size or the
        // layout must show up there too, or the panel would be lying about the render.
        syncSettings();
        persist();
        refresh();
        await refreshPlan();
        // Show what was applied on its own axis (each rail's "Custom" card stays for the other one).
        renderPresetRails();
        notify(built
            ? `preset applied: ${entry.label} - ${built} cell(s) built`
            : (kind === "suite"
                ? `preset applied: ${entry.label} - ${state.suite.length} sheet(s) from one queue`
                : `preset applied: ${entry.label}`));
    }

    // The rails handle their own clicks (see fillPresetRail): a card IS the control now, so there
    // is no separate change listener and no select whose value could disagree with the state.

    // ------------------------------------------------- saving your own presets
    const presetSaveButton = button("Save...", () => showSaveRow(presetSaveRow.style.display === "none"));
    presetSaveButton.dataset.action = "preset-save-open";
    presetSaveButton.title = "Keep the settings on this node as a preset of your own";
    const presetDelete = button("Delete", () => removePreset());
    presetDelete.dataset.action = "preset-delete";
    let deleteArmed = false;
    let deleteTimer = 0;

    const presetName = element("input", {
        type: "text",
        className: "mmx-input mmx-preset-name",
        placeholder: "name this preset, e.g. My house style",
    }, { flex: "1 1 200px", minWidth: "150px" });
    const presetStoreNote = element("span", { className: "mmx-muted" }, { fontSize: "10px" });
    const presetSaveRow = element("div", { className: "mmx-row" }, { marginTop: "4px", display: "none" });
    presetSaveRow.append(
        presetName,
        button("Save preset", () => saveCurrentPreset()),
        button("Cancel", () => showSaveRow(false)),
        presetStoreNote,
    );

    function showSaveRow(open) {
        presetSaveRow.style.display = open ? "" : "none";
        if (!open) return;
        presetStoreNote.textContent = presetsStore
            ? `saved to ${presetsStore}`
            : "saved in ComfyUI's user directory";
        presetName.focus?.();
    }

    /** Reset the delete button to its un-armed state (and its two-step timer). */
    function disarmDelete() {
        deleteArmed = false;
        if (deleteTimer) {
            clearTimeout(deleteTimer);
            deleteTimer = 0;
        }
        presetDelete.textContent = "Delete";
    }

    function updateDeleteButton() {
        disarmDelete();
        const entry = presetList.find((item) => item.id === String(state.presetId || ""));
        const custom = Boolean(entry && entry.custom);
        presetDelete.disabled = !custom;
        presetDelete.title = custom
            ? "Remove this saved preset from the list"
            : "Only presets you saved yourself can be deleted";
    }

    async function saveCurrentPreset() {
        const name = String(presetName.value || "").trim();
        if (!name) {
            notify("give the preset a name first");
            presetName.focus?.();
            return;
        }
        if (typeof hooks.savePreset !== "function") {
            notify("saving presets needs the node's own backend");
            return;
        }
        try {
            const answer = await hooks.savePreset(currentPresetBody(name));
            if (!answer || answer.ok === false) {
                notify(String(answer?.reason || "could not save the preset"));
                return;
            }
            const saved = answer.preset || {};
            presetsStore = String(answer.store || presetsStore || "");
            if (saved.id) {
                // Saving IS choosing it: the workflow now records where these numbers came from.
                // Set BEFORE the rail is filled, because the rail lights the card that matches
                // the state - not the id it was handed.
                state.presetId = String(saved.id);
                persist();
            }
            fillPresets(answer.presets, String(saved.id || ""));
            presetName.value = "";
            showSaveRow(false);
            notify(`preset saved: ${saved.label || name}`);
        } catch (error) {
            notify(`could not save the preset: ${error.message}`);
        }
    }

    async function removePreset() {
        const entry = presetList.find((item) => item.id === String(state.presetId || ""));
        if (!entry || !entry.custom) return;
        if (!deleteArmed) {
            // Two steps, no browser dialog: a preset the user spent time on should not go away
            // on one stray click, and an un-armed button says what it will do.
            deleteArmed = true;
            presetDelete.textContent = "Really delete?";
            deleteTimer = setTimeout(() => disarmDelete(), 5000);
            notify(`press again to delete "${entry.label}"`);
            return;
        }
        disarmDelete();
        if (typeof hooks.deletePreset !== "function") {
            notify("deleting presets needs the node's own backend");
            return;
        }
        try {
            const answer = await hooks.deletePreset(entry.id);
            if (!answer || answer.ok === false) {
                notify(String(answer?.reason || "could not delete the preset"));
                return;
            }
            if (String(state.presetId || "") === entry.id) {
                state.presetId = "";
                persist();
            }
            fillPresets(answer.presets, "");
            notify(`preset deleted: ${entry.label}`);
        } catch (error) {
            notify(`could not delete the preset: ${error.message}`);
        }
    }

    // Layout rail on top (it is the bigger decision: which sheet you get), quality below it, and
    // one line of prose that says what is set now - see showHint.
    // The two rails are titled, not explained: the explanation was the same sentence every
    // time, and it is now the rail's tooltip.
    const layoutLabel = element("div", { className: "mmx-row" }, { marginBottom: "2px" });
    layoutLabel.title = "Which sheet to draw: the cells, their arrangement and the cell shape";
    // "your renders": the layout cards wear the drawing by default (see `cardArt` - the drawing is
    // what the card is for), and this switch puts your own last render of each sheet on them.
    const cardArtBox = switchBox("mmx-card-art", cardArt(state));
    const cardArtLabel = element("label", {
        className: "mmx-muted", htmlFor: "mmx-card-art", textContent: "your renders",
    });
    cardArtLabel.title = "Layout cards: the drawn arrangement, or your own last render of each sheet";
    cardArtBox.addEventListener("change", () => {
        state.cardArt = cardArtBox.checked;
        persist();
        // The rails are REBUILT, not re-lit: whether a card wears art is decided when it is built.
        fillPresets(presetList, String(state.presetId || ""));
        notify(cardArtBox.checked
            ? "layout cards: your own renders of each sheet"
            : "layout cards: the drawn arrangements");
    });
    layoutLabel.append(
        element("span", { textContent: "Sheets", className: "mmx-label" }),
        element("span", { className: "mmx-spacer" }),
        cardArtBox,
        switchTrack(),
        cardArtLabel,
        presetSaveButton,
        presetDelete,
    );
    // B's "How" line (the column's third block): the mode as a SEGMENT with its steps chip at
    // the end of the line - `[ One pass | Per cell ]  ·····  8 steps`. There is no "Mode" heading
    // in B, and the segments carry their own words, so the row's meaning is its tooltip.
    const modeRow = element("div", { className: "mmx-row mmx-modeseg" });
    modeRow.title = "How to sample the sheet: one render for the whole sheet, or one per cell."
        + " The steps count is on the Settings tab.";
    const stepsChip = button("steps", () => showTab("settings"));
    stepsChip.classList.add("mmx-btn", "mmx-btn--quiet", "mmx-chip--steps");
    stepsChip.dataset.action = "goto-steps";
    modeRow.append(
        presetSelect,
        element("span", { className: "mmx-spacer" }),
        stepsChip,
    );

    /** The chip reads the node's own steps knob, so it can never disagree with the render. */
    function syncStepsChip() {
        const raw = Number(state.knobValues?.steps);
        const known = Number.isFinite(raw);
        stepsChip.textContent = known ? `${raw} steps` : "steps";
        stepsChip.title = known
            ? `${raw} sampler steps per cell — the Settings tab has the slider`
            : "No steps reading yet — the Settings tab has the slider";
    }
    presetsRow.append(
        layoutLabel,
        layoutSelect,
        presetHint,
    );
    container.append(presetSaveRow);
    if (typeof hooks.listPresets === "function") {
        Promise.resolve(hooks.listPresets())
            .then((data) => {
                presetsStore = String(data?.store || "");
                fillResolutions(data?.resolutions);
                fillPresets(data?.presets, String(state.presetId || ""));
                // Asked for AFTER the rails exist, and its answer re-renders them with art.
                return typeof hooks.listGallery === "function" ? hooks.listGallery() : null;
            })
            .then((gallery) => {
                if (!gallery) return;
                // Phase 2: the card art is the user's own last render of each layout. Derived,
                // so it lives outside the state that is persisted into the node's payload.
                galleryArt = gallery.layouts && typeof gallery.layouts === "object"
                    ? gallery.layouts
                    : {};
                // The rails are REBUILT, not just re-activated: `renderPresetRails` only moves the
                // `is-active` ring, and a card's art is decided when the card is built.
                fillPresets(presetList, String(state.presetId || ""));
            })
            .catch(() => {
                fillResolutions(null);
                fillPresets([], "");
            });
    } else {
        fillResolutions(null);
        fillPresets([], "");
    }

    // ------------------------------------------------------------- footer
    // Proposal B's pinned bar: the primary action at the bottom, with the status line it acts
    // on beside it. "Render" is ComfyUI's own queue - the panel only presses the button (see
    // `hooks.queue` in the wiring), so what it queues is the graph the node is already part of.
    const status = element("div", { textContent: "ready", className: "mmx-status" });
    const actionbar = element("div", { className: "mmx-actionbar" });
    const renderButton = button("Render", async () => {
        try {
            await hooks.queue?.();
            notify("queued - the render follows the sheet folder, so cells appear as they land");
        } catch (error) {
            notify(`could not queue: ${error.message}`);
        }
    });
    renderButton.classList.add("mmx-btn--primary");
    renderButton.dataset.action = "render";
    if (typeof hooks.queue !== "function") {
        // The harness (and a bare panel without ComfyUI) has no queue to press. Disabled with a
        // reason beats a button that throws.
        renderButton.disabled = true;
        renderButton.title = "Queues the graph through ComfyUI - needs the live node";
    } else {
        renderButton.title = "Queue this sheet now (the same as ComfyUI's own queue button)";
    }
    const rebuildButton = button("Re-compose", async () => {
        try {
            const answer = await hooks.compose?.(boardName());
            const sheet = answer?.sheet || null;
            notify(sheet?.sheetFile
                ? `sheet rebuilt from the frames on disk → ${sheet.sheetFile} `
                    + "(a new file; the previous sheet is kept, no re-render)"
                : "sheet rebuilt from the frames on disk (no re-render).");
            await refreshResults(sheet);
        } catch (error) {
            notify(`rebuild failed: ${error.message}`);
        }
    });
    rebuildButton.dataset.action = "rebuild-sheet";
    // A render already writes the sheet (the sink composes it from the frames at the end of the
    // run), and a pick re-composes it too. This is for the changes that do NOT re-render - the
    // layout, the captions, the gap, the backdrop - so the sheet on disk matches what is on screen
    // without queueing the whole sheet again.
    rebuildButton.title = "Redraw the sheet from the frames already on disk - no re-render. "
        + "A render (and picking a frame) already composes one; use this after changing the "
        + "layout, the captions or the backdrop.";
    const refreshButton = button("Refresh", async () => {
        await refreshResults();
        notify("results refreshed from the sheet folder");
    });
    refreshButton.dataset.action = "refresh-results";
    // B pins the primary action at the bottom of the CONTROL COLUMN. The status line and the
    // sheet-folder actions sit directly above it, in the same column, instead of on a full-width
    // row of their own - which is what made the panel have a strip the proposal does not have.
    actionbar.append(
        status,
        element("span", { className: "mmx-spacer" }),
        clearButton,
        auto,
        autoLabel,
        rebuildButton,
        refreshButton,
    );

    // ------------------------------------------- compact settings (the node's knobs)
    // The node has 23 knobs and the frontend draws a native widget one per row, full
    // width - there is no column-span API (`computeLayoutSize` only lets a widget claim
    // its own space). So the knobs are drawn HERE, in a 2-3 column grid, and the node's
    // own rows are hidden (a hidden widget keeps its `widgets_values` slot and its prompt
    // input: the frontend only skips `serialize === false`). Values are read from and
    // written to the node's widgets through the wiring hooks, so a render started from
    // this panel is the same render as one started from the canvas.
    //
    // The labels, groups and bounds come from the backend (h3_character_sheet/knobs.py),
    // which reads them from the node schema: the panel cannot offer a value the node
    // would reject.
    let knobGroups = [];
    // How many columns the knob grid draws. The backend owns the number (``knobs.py``
    // KNOB_COLUMNS, sent with the list) because the rows are laid out against it.
    let knobColumns = KNOB_COLUMNS;
    const knobFields = new Map();

    const compactBox = switchBox("mmx-compact-knobs", compactKnobs(state));
    compactBox.addEventListener("change", () => {
        state.compactKnobs = compactBox.checked;
        // The flag says "the panel draws the knobs", the hook takes "show the node's rows".
        hooks.setKnobsVisible?.(!compactBox.checked);
        persist();
        notify(compactBox.checked
            ? "the node's knobs are now drawn here instead of on the node"
            : "the node's knobs are back on the node");
    });
    const settingsNote = element("div", { className: "mmx-muted", textContent: "reading the node's knobs..." });
    const settingsHost = element("div");

    // How big ComfyUI's own output previews (the images it draws UNDER the panel) may be.
    // Those are the frontend's widgets and it sizes each image from the node width, so a wide
    // node means a giant preview - and two of them make the node enormous. The pack caps them
    // (and lets them sit side by side) or hides them; this is the switch for that.
    const previewSelect = selectBox(
        NODE_PREVIEW_LABELS,
        nodePreviews(state),
        (value) => {
            state.nodePreviews = nodePreviews({ nodePreviews: value });
            hooks.setPreviewMode?.(state.nodePreviews);
            persist();
            const label = (NODE_PREVIEW_LABELS.find(([id]) => id === state.nodePreviews) || [])[1];
            notify(state.nodePreviews === "panel"
                ? "ComfyUI's own node previews are off - the sheet is in the Results tab"
                : state.nodePreviews === "off"
                    ? "no previews at all - the Results tab still has the sheet and the frames"
                    : `node previews: ${String(label || state.nodePreviews).toLowerCase()}`);
        },
    );
    previewSelect.dataset.action = "node-previews";

    // How big the panel's OWN preview of the finished sheet is (see renderResults). Independent
    // of the node previews above on purpose: with `panel` mode the node has none at all, so this
    // is the only place the sheet is visible without leaving the node.
    const panelPreviewSelect = selectBox(
        PANEL_PREVIEW_SIZES.map(([key, label]) => [key, `Panel preview: ${label}`]),
        panelPreview(state),
        (value) => {
            state.panelPreview = panelPreview({ panelPreview: value });
            persist();
            renderResults();
            scheduleFit(node);
        },
    );
    panelPreviewSelect.dataset.action = "panel-preview";
    previewSelect.title =
        "ComfyUI's own preview under this node is sized from the node width, and the frontend "
        + "re-creates it when the sheet image lands - which is why 'Small' and 'Full width' can "
        + "be overridden for a moment. 'Panel only' removes it outright (the sheet is in the "
        + "Results tab at the Panel preview size); 'ComfyUI default' hands it back untouched.";
    const settingsHead = element("div", { className: "mmx-row mmx-settings__head" }, { marginBottom: "4px" });
    settingsHead.append(
        // Input, then its track (the CSS matches `input:checked + .mmx-switch`, so they have to be
        // adjacent), then the label - which still toggles the box through htmlFor.
        compactBox,
        switchTrack(),
        element(
            "label",
            { textContent: "Compact node", htmlFor: "mmx-compact-knobs" },
            { fontSize: "10px" },
        ),
        element("span", { className: "mmx-muted", textContent: "node previews" }, { marginLeft: "8px" }),
        previewSelect,
        panelPreviewSelect,
        element("span", {}, { flex: "1 1 auto" }),
        button("Re-read node", () => {
            syncSettings();
            notify("knob values read from the node");
        }),
    );
    const settingsPane = element("div", { className: "mmx-pane mmx-pane--settings mmx-settings" });
    settingsPane.append(settingsHead, settingsNote, settingsHost);

    /** One field per knob: the control the schema says it needs. */
    function knobField(knob) {
        const label = element("label", { className: "mmx-knob" }, {
            gridColumn: `span ${Math.max(1, Number(knob.span) || 1)}`,
        });
        label.dataset.knob = knob.name;
        label.append(element("span", {
            textContent: knob.label || knob.name,
            className: "mmx-knob__label",
        }));
        const commit = (raw) => {
            const value = knobValue(knob, raw);
            state.knobValues = { ...(state.knobValues || {}), [knob.name]: value };
            hooks.applyWidgets?.({ [knob.name]: value });
            notify(`${knob.label || knob.name}: ${value === true ? "on" : value === false ? "off" : value}`);
        };
        let control = null;
        let slider = null;
        if (knob.kind === "toggle") {
            label.classList.add("mmx-knob--toggle");
            // The switch is the visible half; the checkbox behind it is what carries the value.
            const box = switchBox(`mmx-knob-${knob.name}`, knob.value);
            box.addEventListener("change", () => commit(box.checked));
            control = box;
            label.append(control, switchTrack());
            if (knob.hint) {
                // A toggle's hint is a sentence about a state, and it belongs on the switch.
                label.title = knob.hint;
            }
            return { label, control };
        } else if (knob.kind === "select" && Array.isArray(knob.options) && knob.options.length) {
            const select = element("select", { className: "mmx-select" });
            for (const choice of knob.options) {
                const option = element("option", { value: choice, textContent: choice });
                if (String(knob.value) === String(choice)) option.selected = true;
                select.append(option);
            }
            select.addEventListener("change", () => commit(select.value));
            control = select;
        } else {
            const input = element("input", { className: "mmx-input" });
            if (knob.kind === "number") {
                input.type = "number";
                if (Number.isFinite(knob.min)) input.min = String(knob.min);
                if (Number.isFinite(knob.max)) input.max = String(knob.max);
                if (Number.isFinite(knob.step)) input.step = String(knob.step);
            } else {
                input.type = "text";
            }
            input.value = knob.value == null ? "" : String(knob.value);
            input.addEventListener("change", () => commit(input.value));
            control = input;
            if (knob.kind === "number") {
                slider = numberSlider(knob);
                if (slider) {
                    // Drag -> the box (and the node); type -> the slider follows the clamped value.
                    const moveBox = () => {
                        input.value = slider.value;
                    };
                    slider.addEventListener("input", moveBox);
                    slider.addEventListener("change", () => {
                        moveBox();
                        commit(slider.value);
                    });
                    input.addEventListener("change", () => {
                        slider.value = String(knobValue(knob, input.value));
                    });
                }
            }
        }
        label.append(control);
        if (slider) label.append(slider);
        // A hint is a sentence about a knob, and one per knob made this grid the wordiest surface in
        // the panel. It is always on the control as a tooltip; only a SHORT one is printed under
        // the field, where it reads as a unit ("32px grid") instead of as a paragraph.
        if (knob.hint) {
            if (control) control.title = control.title || knob.hint;
            if (String(knob.hint).length <= HINT_INLINE_LIMIT) {
                label.append(element("span", { textContent: knob.hint, className: "mmx-knob__hint" }));
            }
        }
        return { label, control };
    }

    /**
     * The knobs of one group, split into the rows the backend declared.
     *
     * ``knobs.py`` gives every knob a ``row``: a deliberately placed line inside its group,
     * because a flowing three-column grid decides for itself where the next knob goes - which
     * is how the seed ended up a row away from the mode that governs it. A group sent without
     * rows (an older backend, or a fixture) falls back to one flowing grid, i.e. exactly the
     * old behaviour.
     */
    function knobRows(knobs) {
        const rows = [];
        for (const knob of knobs || []) {
            const index = Math.max(0, Math.trunc(Number(knob.row) || 0));
            while (rows.length <= index) rows.push([]);
            rows[index].push(knob);
        }
        return rows.filter((row) => row.length);
    }

    function renderSettings() {
        knobFields.clear();
        settingsHost.replaceChildren();
        let total = 0;
        for (const group of knobGroups) {
            const section = element("div", { className: "mmx-knob-group" });
            section.dataset.group = group.group;
            // The title is a shape you can scan (a bold word plus how many fields are under it)
            // rather than a sentence about the group.
            const title = element("div", { className: "mmx-knob-group__title" }, {}, [
                element("span", { textContent: group.group }),
                element("span", { className: "mmx-badge", textContent: String(group.knobs.length) }),
            ]);
            section.append(title);
            const body = element("div", { className: "mmx-knob-rows" });
            for (const row of knobRows(group.knobs)) {
                const grid = element("div", { className: "mmx-knob-grid" }, {
                    gridTemplateColumns: `repeat(${knobColumns}, minmax(0, 1fr))`,
                });
                for (const knob of row) {
                    const { label, control } = knobField(knob);
                    grid.append(label);
                    knobFields.set(knob.name, control);
                    total += 1;
                }
                body.append(grid);
            }
            section.append(body);
            settingsHost.append(section);
        }
        // One line of fact; the explanation of WHY the grid exists lives on it as a tooltip.
        settingsNote.textContent = total
            ? `${total} knob(s) · ${knobColumns} columns`
            : "no knobs reported by the node.";
        settingsNote.title = total
            ? "The same values the node renders with, in " + knobColumns + " columns instead of "
                + total + " node rows. Every field writes the node's own widget; `Re-read node` "
                + "pulls the current values back."
            : "The node's schema could not be read: the Settings tab has nothing to draw.";
    }

    /** Re-read the node's own widget values and redraw the fields with them. */
    function syncSettings(names = null) {
        const list = names || knobGroups.flatMap((group) => group.knobs.map((knob) => knob.name));
        if (!list.length) return null;
        const values = hooks.readWidgets?.(list);
        if (values && typeof values === "object") {
            state.knobValues = { ...(state.knobValues || {}), ...values };
        }
        knobGroups = knobGroups.map((group) => ({
            group: group.group,
            knobs: knobValues(group.knobs, state.knobValues),
        }));
        compactBox.checked = compactKnobs(state);
        renderSettings();
        // The chips read the node's own sizes, so a size typed in this grid turns them to Custom.
        renderResolutions();
        return state.knobValues;
    }

    /** Adopt the backend's knob list (labels, groups, rows, bounds) and show the live values. */
    function refreshSettings(data) {
        const groups = Array.isArray(data?.groups) && data.groups.length
            ? data.groups
            : (Array.isArray(data?.knobs) && data.knobs.length
                ? [{ group: "Settings", knobs: data.knobs }]
                : []);
        // The grid's width is the layout's own number (``knobs.py`` KNOB_COLUMNS).
        knobColumns = Math.max(1, Math.trunc(Number(data?.columns) || KNOB_COLUMNS));
        knobGroups = groups.map((group) => ({
            group: String(group.group || "Settings"),
            knobs: knobValues(group.knobs || [], state.knobValues),
        }));
        const names = knobGroups.flatMap((group) => group.knobs.map((knob) => knob.name));
        syncSettings(names);
        // Only now - with the knobs drawn here - is it safe to take the node's rows away.
        hooks.setKnobsVisible?.(!compactKnobs(state));
        return knobGroups;
    }

    if (typeof hooks.listKnobs === "function") {
        Promise.resolve(hooks.listKnobs())
            .then((data) => refreshSettings(data))
            .catch(() => {
                // The panel could not draw them, so the node keeps its own rows: a node
                // with no visible way to set its size is worse than a tall node.
                hooks.setKnobsVisible?.(true);
                settingsNote.textContent = "could not read the node's knobs - its own rows stay on the node.";
            });
    } else {
        settingsNote.textContent = "knob list unavailable.";
    }

    // ------------------------------------------------------------------- help
    // The guide ("how do I drive this?") and a LIVE check of the model files: the backend
    // lists the folders the running ComfyUI knows about, so a missing file is reported with
    // the path it should be at and a link to where it comes from. Content lives in
    // h3_character_sheet/help.py, so the panel cannot drift from what the node needs.
    const helpTitle = element("div", { className: "mmx-title", textContent: "Help" });
    const helpNote = element("div", { className: "mmx-muted", textContent: "reading the guide..." });
    const helpHost = element("div");
    const helpPane = element("div", { className: "mmx-pane mmx-pane--help mmx-help" });
    // The project name (from the backend) leads the tab, so the guide is self-identifying.
    helpTitle.dataset.project = "";
    helpPane.append(helpTitle, helpNote, helpHost);

    function helpLinks(links, className = "mmx-help__links") {
        const host = element("div", { className });
        for (const link of links || []) {
            if (!link?.url) continue;
            const anchor = element("a", {
                textContent: link.label || link.url,
                href: link.url,
                target: "_blank",
                rel: "noreferrer",
                className: "mmx-help__link",
                // A tooltip is plain text: the markers would show up as asterisks in it.
                title: plainText(link.note || link.url),
            });
            // A click inside the panel must not reach the canvas (and with it the node).
            anchor.addEventListener("click", (event) => event.stopPropagation());
            host.append(anchor);
            if (link.note) host.append(richText("span", link.note, "mmx-help__link-note"));
        }
        return host;
    }

    /** One file the node needs: what it is, whether this install has it, where it goes. */
    function requirementRow(item) {
        const card = element("div", { className: `mmx-req mmx-req--${item.ok ? "ok" : "missing"}` });
        card.dataset.req = item.id;
        const head = element("div", { className: "mmx-row mmx-req__head" });
        head.append(
            element("span", { textContent: item.ok ? "✓" : "✗", className: "mmx-req__mark" }),
            element("span", { textContent: item.label, className: "mmx-title" }),
            element("span", { textContent: item.node || "", className: "mmx-muted" }),
        );
        card.append(head);
        if (item.what) card.append(richText("div", item.what, "mmx-req__what"));
        // Where the file belongs - never which file this machine happens to have. The tab is
        // read by whoever installed the pack, on their install: a checkpoint name that only
        // exists on someone else's disk is noise, not help. What the row owes the reader is
        // "is it there, and where do I put it".
        card.append(element("div", {
            textContent: `${item.file_ok === false ? "put it in" : "in place"}: ${item.where}`,
            className: "mmx-req__path",
        }));
        // A file can be right and the feature still dead (the blur needs the ultralytics
        // package), so the package state is its own line rather than folded into the ✓.
        for (const entry of item.packages || []) {
            card.append(element("div", {
                textContent: `${entry.ok ? "✓" : "✗"} python package: ${entry.name}`,
                className: `mmx-req__package${entry.ok ? "" : " mmx-req__package--missing"}`,
            }));
        }
        if ((item.packages || []).length && (item.missing_packages || []).length) {
            card.append(element("div", {
                textContent: `install it into ComfyUI's own python: python_embeded/python -m pip install ${item.missing_packages.join(" ")}`,
                className: "mmx-req__path",
            }));
        }
        if (!item.ok && !(item.missing_packages || []).length) {
            card.append(element("div", {
                textContent: item.expect?.length ? `expect a file named like: ${item.expect.join(", ")}` : "",
                className: "mmx-req__path",
            }));
        }
        if (item.note) card.append(richText("div", item.note, "mmx-req__what"));
        if (item.links?.length) card.append(helpLinks(item.links));
        return card;
    }

    function renderHelp(data) {
        helpHost.replaceChildren();
        const sections = Array.isArray(data?.sections) ? data.sections : [];
        const requirements = Array.isArray(data?.requirements) ? data.requirements : [];
        if (!sections.length) {
            helpNote.textContent = "the guide could not be loaded (is the backend running?)";
            return;
        }
        helpTitle.textContent = String(data?.project || "Help");
        helpTitle.dataset.project = String(data?.project || "");
        const missing = Number(data?.missing?.length || 0);
        const missingPackages = Array.isArray(data?.missing_packages) ? data.missing_packages : [];
        helpNote.textContent = missing
            ? `${missing} of ${requirements.length} required files are missing or unusable`
                + (missingPackages.length ? ` (python package: ${missingPackages.join(", ")})` : "")
                + " - the sections below say where they go."
            : `${data?.project || "This pack"} - all ${requirements.length} required files found.`;
        for (const section of sections) {
            const block = element("div", { className: "mmx-help__section" });
            block.dataset.section = section.id;
            block.append(element("div", { textContent: section.title, className: "mmx-help__title" }));
            if (section.intro) {
                block.append(richText("div", section.intro, "mmx-help__intro"));
            }
            if (section.kind === "files") {
                for (const item of requirements) block.append(requirementRow(item));
            }
            if (section.steps?.length) {
                const list = element("ol", { className: "mmx-help__steps" });
                for (const step of section.steps) list.append(richText("li", step));
                block.append(list);
            }
            if (section.bullets?.length) {
                const list = element("ul", { className: "mmx-help__bullets" });
                for (const bullet of section.bullets) list.append(richText("li", bullet));
                block.append(list);
            }
            if (section.links?.length) block.append(helpLinks(section.links));
            helpHost.append(block);
        }
    }

    if (typeof hooks.listHelp === "function") {
        Promise.resolve(hooks.listHelp())
            .then((data) => renderHelp(data))
            .catch(() => { helpNote.textContent = "the guide could not be loaded (is the backend running?)"; });
    } else {
        helpNote.textContent = "the guide is not wired up.";
    }

    // B's "Sheets" column, top to bottom: the tile wall, the sizes, the mode segment with its
    // steps chip, and the references the sheet will be built from - the last as small avatars
    // that jump to the tab where they are edited, because a control column is for deciding.
    const refsMiniRow = element("div", { className: "mmx-mini" });
    refsMiniRow.append(element("h3", { className: "mmx-mini__head", textContent: "References" }));
    const refsMiniBox = element("div", { className: "mmx-mini__row" });
    refsMiniRow.append(refsMiniBox);
    /**
     * The avatars, one per reference this sheet will send.
     *
     * They are read-only on purpose: the picture is edited on the References tab (where the stage
     * can hold it at full size and the painter lives), so a click here goes there instead of
     * silently editing something that is not on screen.
     */
    function refreshRefsMini() {
        refsMiniBox.replaceChildren();
        const filled = mediaSlots(state.refs);
        const shown = filled.slice(0, 5);
        for (const entry of shown) {
            const chip = button("", () => showTab("references"));
            chip.classList.add("mmx-mini__chip");
            if (!entry.active) chip.classList.add("is-off");
            // `mediaSlots` returns the group and the index, not the slot itself: the slot is
            // where the role the user typed lives.
            const role = String(state.refs?.[entry.group.key]?.[entry.index]?.role || "").trim();
            // ONE word: B draws "face / body / fit", and a 34px avatar holding "body shape," is a
            // fragment rather than a label. The whole role is in the tooltip.
            const first = role.split(/[\s,/]+/)[0];
            const short = first ? first.slice(0, 9) : entry.group.label.slice(0, -1).toLowerCase();
            chip.append(element("span", { textContent: short }));
            chip.title = `${entry.group.label} ${entry.ordinal ?? "-"}: ${role || "no role yet"}`
                + " — opens the References tab, where it is edited";
            refsMiniBox.append(chip);
        }
        const add = button("+", () => pickFiles(null, null));
        add.classList.add("mmx-mini__chip", "mmx-mini__chip--add");
        add.dataset.action = "add-media";
        add.title = "Add a reference from disk (pictures, then video, then audio)";
        refsMiniBox.append(add);
        if (filled.length > shown.length) {
            refsMiniBox.append(element("span", {
                className: "mmx-muted",
                textContent: `+${filled.length - shown.length} more`,
            }));
        }
    }

    // ----------------------------------------------------------------- LoRAs
    // The sheet's own LoRA stack: one list on the SHEET instead of a loader node in the graph, so
    // every cell - and every board of a suite - samples through the same patches (the node applies
    // it; see lora_library.apply_stack). A loader wired into the model input still works and the
    // two compose, which is exactly why this tab exists: the stack belongs to the sheet, and the
    // two things a user needs about a file - how hard it should be pushed, and what it even is -
    // should not need a second program.
    const lorasPane = element("div", { className: "mmx-pane mmx-pane--loras mmx-loras" });
    const lorasHead = element("div", { className: "mmx-loras__head" });
    const lorasNote = element("div", { className: "mmx-muted mmx-loras__note" });
    const lorasHost = element("div", { className: "mmx-loras__rows" });
    // The library browser is ALWAYS in the flow, under the stack: the tab is "search a LoRA and click
    // it", and a list that only appears after clicking *Add* made the search box look broken.
    const loraBrowse = element("div", { className: "mmx-loras__browser" });
    const loraBrowseLabel = element("div", { className: "mmx-loras__browserlabel" });
    const loraPickList = element("div", { className: "mmx-loras__picklist" });
    loraBrowse.append(loraBrowseLabel, loraPickList);
    lorasPane.append(lorasHead, lorasNote, lorasHost, loraBrowse);

    //: The served library (file -> record): what models/loras holds, plus whatever metadata is
    //: already stored for each file. Fetched once when the tab opens, and on demand after that.
    let loraLibrary = new Map();
    let loraLibraryNote = "reading models/loras...";
    //: Which row is talking to the backend right now ("" = idle), so the tab can say so.
    let loraBusy = "";
    //: The card that is expanded, as a file name: it survives a re-render, because refreshing the
    //: library or toggling a row must not close what the user is reading. Rows start COLLAPSED -
    //: adding a LoRA is not a request to read its metadata.
    let openLoraCard = "";
    let loraPickQuery = "";
    let loraSaveTimer = null;
    const loraSearchBox = textInput("", "search models/loras to add", (value) => {
        loraPickQuery = value;
        renderLoraBrowser();
    }, "mmx-input mmx-loras__search");
    loraSearchBox.dataset.action = "lora-search";

    /** The library's record for one file, or null when this install does not have it. */
    function loraRecord(file) {
        return loraLibrary.get(String(file || "")) || null;
    }

    /** A file's name without its folder or extension - the fallback label. */
    function loraStem(file) {
        const base = String(file || "").split("/").pop() || "";
        return base.replace(/\.(safetensors|ckpt|pt|sft)$/i, "");
    }

    function loraTitle(entry) {
        const record = loraRecord(entry.file);
        return String(record?.name || record?.label || loraStem(entry.file) || entry.file);
    }

    function clampLoraStrength(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return DEFAULT_LORA_STRENGTH;
        const clamped = Math.min(LORA_STRENGTH_RANGE[1], Math.max(LORA_STRENGTH_RANGE[0], number));
        return Math.round(clamped * 1000) / 1000;
    }

    /** The slider's window for one file: its saved range, else the tab's default. */
    function loraSliderRange(file) {
        const record = loraRecord(file);
        const low = Number(record?.strengthMin);
        const high = Number(record?.strengthMax);
        if (Number.isFinite(low) && Number.isFinite(high) && high > low) return [low, high];
        return DEFAULT_LORA_SLIDER_RANGE;
    }

    /** Persist on a short delay: dragging a strength slider is one edit, not thirty. */
    function scheduleLoraSave() {
        clearTimeout(loraSaveTimer);
        loraSaveTimer = setTimeout(() => {
            loraSaveTimer = null;
            persist();
        }, 250);
    }

    function addLora(file) {
        const name = String(file || "").trim();
        if (!name) return;
        const stack = loraStack(state);
        if (stack.some((entry) => entry.file === name)) {
            notify(`${loraStem(name)} is already on the sheet`);
            return;
        }
        if (stack.length >= MAX_LORAS) {
            notify(`a sheet takes ${MAX_LORAS} LoRAs - that is the cap`);
            return;
        }
        stack.push({ file: name, strength: DEFAULT_LORA_STRENGTH, on: true });
        state.loras = stack;
        persist();
        // Adding one is done: the search clears, which collapses the browser list (and leaves the new
        // row collapsed too - its card is there when the user wants to read it).
        loraPickQuery = "";
        loraSearchBox.value = "";
        renderLoras();
        notify(`LoRA added: ${loraStem(name)} (applies to every cell)`);
    }

    function removeLora(file) {
        state.loras = loraStack(state).filter((entry) => entry.file !== file);
        if (openLoraCard === file) openLoraCard = "";
        persist();
        renderLoras();
        notify(`LoRA removed: ${loraStem(file)}`);
    }

    function toggleLoraCard(file) {
        openLoraCard = openLoraCard === file ? "" : String(file);
        renderLoras();
        // Opening the card is the moment to learn the file's digest: it is what Civitai is asked
        // about, and the row shows it. Cheap on a LoRA (tens of MB), and only on demand.
        if (openLoraCard && !String(loraRecord(file)?.sha256 || "")) loraInfoFor(file, { fetch: false });
    }

    /** The library list under the stack: what matches the search, minus what is already on it. */
    function renderLoraBrowser() {
        loraPickList.replaceChildren();
        const chosen = new Set(loraStack(state).map((entry) => entry.file));
        const query = loraPickQuery.trim().toLowerCase();
        const available = [...loraLibrary.values()]
            .filter((item) => !chosen.has(String(item.file || "")));
        if (!query) {
            // No query, no wall of 167 files: the box says what it is for, and typing is the way in.
            loraBrowseLabel.textContent = loraLibrary.size
                ? `add from models/loras (${available.length} not on the sheet) - type to search`
                : "add from models/loras";
            loraPickList.append(element("div", {
                className: "mmx-muted",
                textContent: loraLibrary.size
                    ? "Search above, then click a result to put it on the sheet."
                    : "reading the LoRA folder...",
            }));
            return;
        }
        const items = available
            .filter((item) => String(item.file || "").toLowerCase().includes(query)
                || String(item.name || item.label || "").toLowerCase().includes(query))
            .slice(0, 80);
        loraBrowseLabel.textContent = items.length
            ? `${items.length} match${items.length === 1 ? "" : "es"} - click one to add it`
            : "no match";
        if (!items.length) {
            loraPickList.append(element("div", {
                className: "mmx-muted",
                textContent: "nothing in models/loras matches that (or it is already on the sheet).",
            }));
            return;
        }
        for (const item of items) {
            const row = button("", () => addLora(item.file));
            row.classList.add("mmx-loras__pick");
            row.dataset.file = String(item.file || "");
            row.append(
                element("span", { className: "mmx-loras__pickname", textContent: String(item.name || item.label || loraStem(item.file)) }),
                element("span", { className: "mmx-loras__pickfile", textContent: String(item.file || "") }),
            );
            if (item.civitai?.found) {
                row.append(element("span", { className: "mmx-badge", textContent: "civitai" }));
            }
            loraPickList.append(row);
        }
    }

    function renderLoras() {
        lorasNote.textContent = loraBusy ? `working... ${loraBusy}` : loraLibraryNote;
        lorasHost.replaceChildren();
        const stack = loraStack(state);
        // Adopt the normalized list as the state's own. The rows below hand the SAME objects to
        // their switch and their slider, and `toPayload` reads the state back - so a commit is the
        // list changing, not a copy of it. (Without this, a toggle moved an object nobody kept.)
        state.loras = stack;
        if (!stack.length) {
            lorasHost.append(element("div", { className: "mmx-loras__empty" }, {}, [
                element("span", { className: "mmx-title", textContent: "No LoRAs on this sheet." }),
                element("span", {
                    className: "mmx-muted",
                    textContent: "One list here covers every cell - and every board of a suite. A "
                        + "LoRA loader wired into the node's model input still works; the two "
                        + "compose, so a stack here plus one in the graph is the same model.",
                }),
            ]));
        }
        for (const entry of stack) lorasHost.append(loraRow(entry));
        renderLoraBrowser();
    }

    /** One row: on/off, its own strength, and the facts about the file behind it. */
    function loraRow(entry) {
        const record = loraRecord(entry.file);
        const missing = !record || record.missing === true;
        const row = element("div", { className: "mmx-lora" });
        row.dataset.file = entry.file;
        row.classList.toggle("is-off", !entry.on);

        const head = element("div", { className: "mmx-lora__head" });
        const box = switchBox(`mmx-lora-on-${loraStem(entry.file).replace(/[^a-z0-9]+/gi, "-")}`, entry.on);
        box.classList.add("mmx-switch-box");
        box.dataset.action = "lora-toggle";
        box.title = entry.on ? "on - one click takes it out of the render" : "off - the row stays, the render skips it";
        box.addEventListener("change", () => {
            entry.on = box.checked;
            row.classList.toggle("is-off", !entry.on);
            box.title = entry.on ? "on - one click takes it out of the render" : "off - the row stays, the render skips it";
            persist();
            notify(`${loraTitle(entry)}: ${entry.on ? "on" : "off"}`);
        });
        // The visible half of the switch is a <span>, and the box behind it is a 0x0 transparent
        // input: wrapped in a label (htmlFor -> the box) the whole control is clickable, which is
        // what makes the track behave like a switch instead of like a picture of one.
        const switchWrap = element("label", { className: "mmx-lora__switch", htmlFor: box.id });
        switchWrap.title = "Take this LoRA out of the render without losing the row";
        switchWrap.append(box, switchTrack());
        head.append(switchWrap);

        const title = button("", () => toggleLoraCard(entry.file));
        title.classList.add("mmx-lora__title");
        title.dataset.action = "lora-card";
        title.title = "Show what this file is: its hash, and what Civitai has to say about it";
        title.append(
            element("span", { className: "mmx-lora__name", textContent: loraTitle(entry) }),
            element("span", { className: "mmx-lora__file", textContent: entry.file }),
        );
        if (missing) {
            title.append(element("span", {
                className: "mmx-badge mmx-badge--warn",
                textContent: "not installed",
                title: `models/loras has no ${entry.file} - the render will skip it and say so`,
            }));
        }
        head.append(title);

        const strength = element("div", { className: "mmx-lora__strength" });
        const [low, high] = loraSliderRange(entry.file);
        const number = element("input", {
            className: "mmx-input mmx-lora__number",
            type: "number",
            value: String(entry.strength),
            step: String(LORA_STRENGTH_STEP),
        });
        number.min = String(LORA_STRENGTH_RANGE[0]);
        number.max = String(LORA_STRENGTH_RANGE[1]);
        number.dataset.action = "lora-strength";
        number.title = `Strength - the box takes ${LORA_STRENGTH_RANGE[0]} to ${LORA_STRENGTH_RANGE[1]}`;
        const slider = element("input", { className: "mmx-knob__slider mmx-lora__slider", type: "range" });
        slider.min = String(low);
        slider.max = String(high);
        slider.step = String(LORA_STRENGTH_STEP);
        slider.value = String(Math.min(high, Math.max(low, entry.strength)));
        slider.dataset.action = "lora-slider";
        slider.title = `${low} to ${high}`
            + (record?.strengthMin != null && record?.strengthMax != null
                ? " (this LoRA's saved range)" : " (set a range in the card to change this)");
        const write = (raw, from) => {
            const value = clampLoraStrength(raw);
            entry.strength = value;
            // Both controls end on the ACCEPTED value: a box still reading "9" while the sheet
            // renders 4 is exactly the lie the pair is supposed to prevent. The slider is skipped
            // only when the change came from it - writing it back mid-drag fights the pointer.
            number.value = String(value);
            if (from !== "slider") slider.value = String(Math.min(high, Math.max(low, value)));
            scheduleLoraSave();
        };
        number.addEventListener("change", () => write(number.value, "number"));
        slider.addEventListener("input", () => write(slider.value, "slider"));
        strength.append(number, slider);
        head.append(strength);

        const actions = element("div", { className: "mmx-lora__actions" });
        const info = button(openLoraCard === entry.file ? "hide" : "info", () => toggleLoraCard(entry.file));
        info.classList.add("mmx-btn--quiet");
        info.dataset.action = "lora-info";
        info.title = "File, hash, Civitai, notes";
        const remove = button("\u2715", () => removeLora(entry.file));
        remove.classList.add("mmx-btn--quiet", "mmx-lora__remove");
        remove.dataset.action = "lora-remove";
        remove.title = "Take this LoRA off the sheet";
        actions.append(info, remove);
        head.append(actions);

        row.append(head);
        if (openLoraCard === entry.file) row.append(loraCard(entry));
        return row;
    }

    /** The card behind a row: the file's own facts, and the fields the user owns. */
    function loraCard(entry) {
        const record = loraRecord(entry.file) || {};
        const civitai = record.civitai && typeof record.civitai === "object" ? record.civitai : null;
        const card = element("div", { className: "mmx-lora__card" });
        card.dataset.file = entry.file;

        const facts = element("div", { className: "mmx-lora__facts" });
        const line = (label, value, extra = null) => {
            const row = element("div", { className: "mmx-lora__fact" });
            row.append(element("span", { className: "mmx-lora__factlabel", textContent: label }));
            row.append(extra || element("span", { className: "mmx-lora__factvalue", textContent: value }));
            facts.append(row);
            return row;
        };
        line("File", entry.file);
        const hash = String(record.sha256 || "");
        if (hash) {
            const copy = button("copy", () => {
                const clipboard = globalThis.navigator?.clipboard;
                if (clipboard?.writeText) {
                    clipboard.writeText(hash).then(
                        () => notify("sha256 copied"),
                        () => notify("could not copy - select the hash instead"),
                    );
                } else {
                    notify("this browser will not copy for the panel");
                }
            });
            copy.classList.add("mmx-btn--quiet");
            copy.dataset.action = "lora-copy-hash";
            const value = element("span", { className: "mmx-lora__hash", textContent: hash });
            value.title = hash;
            line("Hash (sha256)", hash, value);
            facts.lastChild.append(copy);
        } else {
            line("Hash (sha256)", loraBusy === entry.file ? "reading the file..." : "not read yet");
        }
        if (civitai?.found) {
            const link = element("a", {
                href: String(civitai.url || ""),
                target: "_blank",
                rel: "noreferrer noopener",
                textContent: "View on Civitai",
            });
            link.classList.add("mmx-lora__link");
            link.dataset.action = "lora-civitai-link";
            line("Civitai", "", link);
        } else {
            const ask = button(civitai ? "ask again" : "look up by hash", () => loraInfoFor(entry.file, { fetch: true, force: Boolean(civitai) }));
            ask.classList.add("mmx-btn--quiet");
            ask.dataset.action = "lora-civitai";
            line("Civitai", "", ask);
        }
        if (record.civitaiError && !civitai) {
            facts.append(element("div", { className: "mmx-muted mmx-lora__error", textContent: String(record.civitaiError) }));
        }
        card.append(facts);

        // The fetched answer, as a card rather than a JSON blob: the fields a user actually reads
        // off Civitai's page before deciding how hard to push a LoRA.
        if (civitai?.found) {
            const summary = element("div", { className: "mmx-lora__civitai" });
            const title = [civitai.modelName, civitai.versionName].filter(Boolean).join(" - ");
            if (title) summary.append(element("span", { className: "mmx-lora__civitaititle", textContent: title }));
            const meta = [
                civitai.type ? String(civitai.type) : "",
                civitai.baseModel ? `base ${civitai.baseModel}` : "",
                civitai.creator ? `by ${civitai.creator}` : "",
                civitai.nsfw ? "NSFW" : "",
            ].filter(Boolean);
            if (meta.length) {
                summary.append(element("span", { className: "mmx-muted", textContent: meta.join(" \u00b7 ") }));
            }
            if (Array.isArray(civitai.trainedWords) && civitai.trainedWords.length) {
                const row = element("div", { className: "mmx-lora__words" });
                row.append(element("span", { className: "mmx-lora__factlabel", textContent: "Trigger words" }));
                for (const word of civitai.trainedWords.slice(0, 12)) {
                    const chip = button(String(word), () => {
                        // The suite of words a LoRA was trained on is prompt material, and the
                        // prompt is one tab away: copy it rather than write it somewhere clever.
                        const clipboard = globalThis.navigator?.clipboard;
                        if (clipboard?.writeText) {
                            clipboard.writeText(String(word)).then(
                                () => notify(`"${word}" copied - paste it into the prompt`),
                                () => notify(`trigger word: ${word}`),
                            );
                        } else {
                            notify(`trigger word: ${word}`);
                        }
                    });
                    chip.classList.add("mmx-chip", "mmx-chip--tiny");
                    chip.dataset.action = "lora-word";
                    chip.title = "Copy this trigger word (it belongs in the prompt)";
                    row.append(chip);
                }
                summary.append(row);
            }
            if (Array.isArray(civitai.tags) && civitai.tags.length) {
                summary.append(element("span", {
                    className: "mmx-muted mmx-lora__tags",
                    textContent: civitai.tags.join(", "),
                }));
            }
            if (civitai.description) {
                summary.append(element("div", { className: "mmx-lora__desc", textContent: String(civitai.description) }));
            }
            const shot = Array.isArray(civitai.images) ? civitai.images[0] : "";
            if (shot) {
                const img = element("img", { className: "mmx-lora__shot", alt: "", src: viewUrl(String(shot)), loading: "lazy" });
                img.title = "Civitai's own sample for this version";
                summary.append(img);
            }
            card.append(summary);
        }

        // The fields the user owns. They live in the user directory (lora_library.store_path),
        // never in the LoRA file, and they are what the row shows next time.
        const fields = element("div", { className: "mmx-lora__fields" });
        const field = (label, value, kind, key) => {
            const wrap = element("label", { className: "mmx-lora__field" });
            wrap.append(element("span", { className: "mmx-lora__factlabel", textContent: label }));
            const input = kind === "notes"
                ? element("textarea", { className: "mmx-input mmx-lora__notes", value: String(value || "") })
                : textInput(String(value ?? ""), "", () => {}, "mmx-input mmx-lora__input");
            input.dataset.field = key;
            wrap.append(input);
            fields.append(wrap);
            return input;
        };
        const nameField = field("Name", record.name, "text", "name");
        const minField = field("Strength Min", record.strengthMin ?? "", "text", "strengthMin");
        const maxField = field("Strength Max", record.strengthMax ?? "", "text", "strengthMax");
        const notesField = field("Additional Notes", record.notes, "notes", "notes");
        for (const input of [minField, maxField]) {
            input.type = "number";
            input.step = String(LORA_STRENGTH_STEP);
            input.placeholder = "slider range";
        }
        notesField.rows = 3;
        const saveRow = element("div", { className: "mmx-lora__saverow" });
        const save = button("Save", () => {
            const fieldsOut = {
                file: entry.file,
                name: nameField.value,
                strengthMin: minField.value,
                strengthMax: maxField.value,
                notes: notesField.value,
            };
            if (typeof hooks.saveLoraInfo !== "function") {
                notify("saving LoRA info needs the ComfyUI routes (reload ComfyUI)");
                return;
            }
            save.disabled = true;
            Promise.resolve(hooks.saveLoraInfo(fieldsOut))
                .then((answer) => {
                    save.disabled = false;
                    if (!answer || answer.ok === false) {
                        notify(String(answer?.error || "could not save"));
                        return;
                    }
                    const item = loraLibrary.get(entry.file);
                    if (item) loraLibrary.set(entry.file, { ...item, ...(answer.record || {}) });
                    renderLoras();
                    notify(`saved: ${entry.file}`);
                })
                .catch(() => {
                    save.disabled = false;
                    notify("could not save the LoRA info");
                });
        });
        save.classList.add("mmx-btn--primary");
        save.dataset.action = "lora-save";
        saveRow.append(save);
        saveRow.append(element("span", {
            className: "mmx-muted",
            textContent: "name, strength range and notes live in ComfyUI's user folder - the LoRA file is never touched.",
        }));
        fields.append(saveRow);
        card.append(fields);
        return card;
    }

    /** Hash one LoRA - and, when asked, ask Civitai about it. Never blocks the tab. */
    function loraInfoFor(file, { fetch = false, force = false } = {}) {
        if (typeof hooks.loraInfo !== "function") {
            notify("LoRA info needs the ComfyUI routes (reload ComfyUI)");
            return Promise.resolve(null);
        }
        loraBusy = file;
        renderLoras();
        return Promise.resolve(hooks.loraInfo({ file, fetch, force }))
            .then((answer) => {
                loraBusy = "";
                if (!answer || answer.ok === false) {
                    notify(String(answer?.error || "could not read that LoRA"));
                    renderLoras();
                    return null;
                }
                const item = loraLibrary.get(file) || { file, folder: "", label: loraStem(file) };
                loraLibrary.set(file, {
                    ...item,
                    sha256: String(answer.sha256 || item.sha256 || ""),
                    ...(answer.civitai !== undefined ? { civitai: answer.civitai } : {}),
                    ...(answer.civitai && answer.civitai.found
                        ? { civitaiError: "" }
                        : {}),
                    ...(answer.civitai && !answer.civitai.found && answer.civitai.error
                        ? { civitaiError: String(answer.civitai.error) }
                        : {}),
                });
                renderLoras();
                if (fetch) {
                    const found = answer.civitai?.found;
                    notify(found
                        ? `Civitai: ${answer.civitai.modelName || loraStem(file)}`
                        : `Civitai: ${answer.civitai?.error || "nothing found"}`);
                }
                return answer;
            })
            .catch(() => {
                loraBusy = "";
                renderLoras();
                notify("could not read that LoRA");
                return null;
            });
    }

    /** Walk the rows that have no Civitai answer yet, one at a time, saying where it is. */
    async function fetchAllLoraInfo() {
        const pending = loraStack(state).filter((entry) => {
            const record = loraRecord(entry.file);
            return record && !record.civitai?.found;
        });
        if (!pending.length) {
            notify("every LoRA on the sheet already has its Civitai info");
            return;
        }
        notify(`asking Civitai about ${pending.length} LoRA(s)...`);
        let done = 0;
        for (const entry of pending) {
            done += 1;
            lorasNote.textContent = `Civitai ${done}/${pending.length}: ${loraStem(entry.file)}`;
            await loraInfoFor(entry.file, { fetch: true });
        }
        notify(`Civitai info fetched for ${pending.length} LoRA(s)`);
    }

    // The tab's own header: SEARCH first (that is the way in), then the two whole-library actions.
    // There is no "+ Add LoRA" button: the search box and the list under it are always there, so a
    // click on a result is the add.
    const loraFetchButton = button("Fetch Civitai info", () => fetchAllLoraInfo());
    loraFetchButton.classList.add("mmx-btn--quiet");
    loraFetchButton.dataset.action = "lora-fetch-all";
    loraFetchButton.title = "Hash each LoRA on the sheet and ask Civitai about it, one at a time";
    const loraRefreshButton = button("Refresh library", () => refreshLoras({ fresh: true }));
    loraRefreshButton.classList.add("mmx-btn--quiet");
    loraRefreshButton.dataset.action = "lora-refresh";
    loraRefreshButton.title = "Re-read models/loras (after adding a file by hand)";
    lorasHead.append(
        loraSearchBox,
        element("span", {}, { flex: "1 1 auto" }),
        loraFetchButton, loraRefreshButton,
    );

    /** Load the library once (and again when asked): the tab is usable the moment it opens. */
    function refreshLoras({ fresh = false } = {}) {
        if (typeof hooks.listLoras !== "function") {
            loraLibraryNote = "the LoRA list needs the ComfyUI routes (reload ComfyUI).";
            renderLoras();
            return Promise.resolve(null);
        }
        loraLibraryNote = loraLibrary.size ? loraLibraryNote : "reading models/loras...";
        return Promise.resolve(hooks.listLoras({ fresh }))
            .then((data) => {
                const items = Array.isArray(data?.items) ? data.items : [];
                loraLibrary = new Map(items.map((item) => [String(item.file || ""), item]));
                const missing = items.filter((item) => item.missing).length;
                loraLibraryNote = items.length
                    ? `${items.length} LoRA(s) in models/loras${missing ? ` \u00b7 ${missing} with no file on disk` : ""}`
                    : "no LoRAs in models/loras.";
                renderLoras();
                return data;
            })
            .catch(() => {
                loraLibraryNote = "could not read models/loras.";
                renderLoras();
                return null;
            });
    }

    let lorasLoaded = false;
    function ensureLoras() {
        if (lorasLoaded) return;
        lorasLoaded = true;
        refreshLoras();
    }

    // --------------------------------------------------------------- tabs
    const tabBar = element("div", { className: "mmx-tabs" });
    // The live stream is its own tab now (see `previewPane`): a render that is working has
    // something to show, and "look at this" is what a tab is for - the strip used to sit under
    // every tab whether or not anything was happening.
    const previewPane = element("div", { className: "mmx-pane mmx-pane--preview" });
    const panes = {
        references: element("div", { className: "mmx-pane is-active mmx-pane--references" }),
        cells: element("div", { className: "mmx-pane mmx-pane--cells" }),
        preview: previewPane,
        prompts: element("div", { className: "mmx-pane mmx-pane--prompts" }),
        results: element("div", { className: "mmx-pane mmx-pane--results mmx-results" }),
        loras: lorasPane,
        settings: settingsPane,
        help: helpPane,
    };
    const tabButtons = {};
    let activeTab = "references";
    function showTab(key) {
        activeTab = key;
        for (const [name, pane] of Object.entries(panes)) pane.classList.toggle("is-active", name === key);
        for (const [name, tab] of Object.entries(tabButtons)) tab.classList.toggle("is-active", name === key);
        syncColumn();
        if (key === "results") refreshResults();
        // The LoRA tab opens on a list, and a list has to come from the install: fetch it the
        // first time the tab is shown rather than on every panel mount (mounts are frequent, and
        // most of them are not about LoRAs).
        if (key === "loras") ensureLoras();
        // The prompt preview comes from the render's own planner, so it is fetched
        // rather than guessed - and it changes whenever the references or cells do.
        if (key === "cells" || key === "prompts") refreshPlan();
        // The pane decides how tall the panel is, so the node has to re-measure.
        hooks.layoutChanged?.();
        // …and a stage that was hidden while it was measured has to be measured again now that it
        // has a box. One frame later: the pane is `display: none` until the class above lands.
        const later = globalThis.requestAnimationFrame
            ? (fn) => globalThis.requestAnimationFrame(fn)
            : (fn) => setTimeout(fn, 16);
        later(() => syncPaintSurfaces());
    }
    /**
     * Light the rail up: "there is something happening in this tab".
     *
     * The Preview tab carries it while the render streams (see setLivePreview/openLiveStrip): the
     * mark is a class on the tab button, and the pulse is CSS, so it costs nothing per frame.
     */
    function setTabLive(key, live) {
        const tab = tabButtons[key];
        if (tab) tab.classList.toggle("is-live", Boolean(live));
    }

    // The rail shows an icon, never a sentence: the words are its tooltip, and the count rides
    // there too now that the numeral badge is gone.
    function setTabCount(key, count) {
        const tab = tabButtons[key];
        if (!tab) return;
        const label = TAB_TITLES[key] || key;
        tab.title = count ? `${label} — ${count}` : label;
    }

    for (const key of TAB_ORDER) {
        const label = TAB_TITLES[key];
        const tab = button("", () => showTab(key));
        tab.classList.add("mmx-tab");
        tab.dataset.tab = key;
        tab.title = label;
        tab.setAttribute("aria-label", label);
        const icon = element("span", { className: "mmx-tab__icon" });
        icon.innerHTML = railIcon(key);
        // The icon and nothing else: the small numeral badge that used to sit on the corner is
        // gone (it read as an unread-message count and cluttered the rail), and the number a tab
        // used to spell out now lives in the tooltip.
        tab.append(icon);
        tabButtons[key] = tab;
        tabBar.append(tab);
    }
    // The live stream lives in its OWN tab (see the rail's play mark): a render that is working
    // has something worth looking at, and the strip used to take a row from every tab whether or
    // not anything was happening. The rail's tab lights up and pulses while frames arrive, so the
    // stream is one click away without stealing the tab you are working on.
    const liveStrip = element("div", { className: "mmx-live" }, { display: "none" });
    const liveMeta = element("span", { className: "mmx-live__meta", textContent: "" });
    const liveFrame = element("img", { className: "mmx-live__frame", alt: "", src: "" });
    const liveWait = element("div", { className: "mmx-live__wait", title: "waiting for the render's first frame" });
    // "I don't like this one": stop the run and render this cell again with a new seed. Only the
    // cell on screen is re-rolled - the rest of the sheet keeps the frames already on disk, and
    // the panel recomposes the sheet from them afterwards.
    const liveRetry = button("↻ new seed", () => retryLiveCell());
    liveRetry.classList.add("mmx-btn--quiet", "mmx-live__retry");
    liveRetry.title = LIVE_RETRY_TITLE;
    liveStrip.append(
        element("div", { className: "mmx-live__head" }, {}, [
            element("span", { className: "mmx-live__tag", textContent: "LIVE" }),
            liveMeta,
            liveRetry,
        ]),
        liveFrame,
        liveWait,
    );
    previewPane.append(
        element("div", { className: "mmx-live__idle" }, {}, [
            element("span", { textContent: "Nothing is rendering yet.", className: "mmx-title" }),
            element("span", {
                textContent: "Start a render and its frames arrive here, live - the rail's play "
                    + "mark pulses while they do.",
                className: "mmx-muted",
            }),
        ]),
        liveStrip,
    );

    // ------------------------------------------------------------- the frame
    // Proposal B is three regions, and the CONTROL COLUMN is the one the first pass missed: the
    // sheet cards, the sizes, the mode and the references are a column on the right that stays
    // put while the STAGE (the big preview, its tools, the live strip) changes with the tab.
    const stage = element("div", { className: "mmx-stage" });
    // The live strip is content and it belongs under the stage, the way B puts it under the
    // preview: the active pane grows to fill the stage, so the strip is the last thing in it.
    stage.append(
        panes.references, panes.cells, panes.prompts, panes.results, panes.preview,
        panes.loras, panes.settings, panes.help,
    );
    const column = element("div", { className: "mmx-col" });
    // B's control column is **tab-scoped**, and that is the whole point of it: the sheet decisions
    // (which arrangement, which size, one pass or per cell, and the references the sheet is built
    // from) belong to the tab that makes them, and the References tab gets the reference list in
    // their place. The first pass put the sheet block in the column for every tab - a column of
    // sheet options while editing a reference - which is not what the mockup draws.
    const columnDyn = element("div", { className: "mmx-col__body" });
    const drawColumn = element("div", { className: "mmx-col__stack" });
    const refsColumn = element("div", { className: "mmx-col__stack" });
    // The SUITE's boards: which sheets a suite run renders, as ticks over the layout presets.
    //
    // A suite is several sheets in one queue, and the question a user asks next is "which of them
    // do I actually want" (the NSFW board on this character, the expression board on that one).
    // The backend already takes ANY list of layout presets as `render.suite` and validates each one,
    // so this needs no new payload key, no new route and no new server rule - it is the same tick
    // row the Cells tab uses (see optionRow), filled from the served preset list and invisible until
    // a suite is active (the suite card on the layout rail is the way in).
    const boardsRow = element("div");
    boardsRow.style.display = "none";
    boardsRow.dataset.action = "suite-boards-edit";
    /** Layout presets that can be a board: the same rule the node applies. */
    function boardChoices() {
        return presetList.filter(
            (entry) => (entry.kind || "quality") === "layout" && (entry.build?.views || []).length,
        );
    }
    /** The suite's boards in PRESET order, so the payload cannot depend on click order. */
    function suiteBoardIds() {
        const chosen = new Set((state.suite || []).map(String));
        return boardChoices().filter((entry) => chosen.has(entry.id)).map((entry) => entry.id);
    }
    function renderBoards() {
        const ordered = suiteBoardIds();
        boardsRow.style.display = ordered.length ? "" : "none";
        if (!ordered.length) {
            boardsRow.replaceChildren();
            return;
        }
        // optionRow returns {row, boxes}: the row IS the panel, the boxes are the inputs.
        boardsRow.replaceChildren(optionRow(
            "Boards",
            boardChoices().map((entry) => [entry.id, entry.label]),
            new Set(ordered),
            (event) => toggleBoard(event.target.dataset.key, event.target.checked),
            "boards",
            { drag: false },
        ).row);
    }
    /**
     * Put a board in the suite, or take it out.
     *
     * Editing the list also drops the preset's own id: a hand-picked suite is not the "RefMod suite
     * (4 sheets)" preset any more, and a saved workflow should not claim it is. Taking the last one
     * out means no suite at all - the sheet renders from the cells list again.
     */
    function toggleBoard(id, on) {
        const key = String(id || "");
        if (!key) return;
        const chosen = new Set(suiteBoardIds());
        if (on) chosen.add(key); else chosen.delete(key);
        state.suite = boardChoices().filter((entry) => chosen.has(entry.id)).map((entry) => entry.id);
        // The layout record follows the list: a hand-picked suite is not the "RefMod suite (4
        // sheets)" preset any more, and a saved workflow should not claim it is - but a list that
        // happens to match a suite card IS that card, so the rail lights up again when it does.
        const match = presetList.find((entry) => (entry.kind || "quality") === "suite"
            && (entry.boards || []).join("|") === state.suite.join("|"));
        state.layoutPreset = match ? match.id : "";
        renderBoards();
        showHint();
        renderPresetRails();
        persist();
        notify(state.suite.length
            ? `suite: ${state.suite.length} sheet(s) - ${state.suite.join(", ")}`
            : "suite: off - the sheet renders from the cells list again");
    }
    // The Sheets block IS the column's content on the tab that decides the sheet: arrangement,
    // size, mode, and the references the sheet is built from.
    drawColumn.append(presetsRow, boardsRow, resRow, modeRow, refsMiniRow);
    column.append(columnDyn);
    //: The only two tabs that DECIDE something, and so the only two that own a column.
    const COLUMN_TABS = new Set(["cells", "references"]);
    /**
     * Fill the column with the active tab's block - or take the column away.
     *
     * The blocks are MOVED, never rebuilt: the lit card, the typed size, the mode segment and the
     * reference list keep their own state, and switching tabs stays as cheap as it looks.
     *
     * Prompt, Results, Preview, Settings and Help are read-outs of the render, and a second half
     * holding nothing is a wide empty box beside the thing the user came to read: those tabs get
     * the whole panel, so their prompts, their frames and their live picture are as wide as the
     * node. That is what the proposal draws - its rail, then ONE full-width body.
     */
    function syncColumn() {
        const wanted = COLUMN_TABS.has(activeTab);
        column.classList.toggle("is-off", !wanted);
        if (!wanted) {
            columnDyn.replaceChildren();
            return;
        }
        columnDyn.replaceChildren(activeTab === "cells" ? drawColumn : refsColumn);
    }
    const shell = element("div", { className: "mmx-shell" });
    shell.append(tabBar, stage, column);
    // The pinned bar is the PANEL's, not the column's: "Render" is one action from one place, and
    // the five tabs without a column still have to be able to press it. The status line it acts on
    // rides in the same bar, so it reads the same wherever the user is.
    const columnFoot = element("div", { className: "mmx-col__foot mmx-foot" });
    columnFoot.append(actionbar, renderButton);
    container.append(shell, columnFoot);
    const refsHost = panes.references;
    const cellsHost = panes.cells;
    const promptsHost = panes.prompts;
    const results = panes.results;

    // ------------------------------------------------- hidden file picker
    let pendingTarget = null;
    const filePicker = element("input", { type: "file", multiple: true }, { display: "none" });
    filePicker.dataset.mmxSheetPicker = "1";
    filePicker.addEventListener("change", async () => {
        const files = Array.from(filePicker.files || []);
        filePicker.value = "";
        const target = pendingTarget;
        pendingTarget = null;
        if (!files.length) return;
        if (target?.group) {
            await acceptFiles(files, target.group, target.index ?? null);
            return;
        }
        for (const group of REF_GROUPS) {
            const mine = files.filter((file) => fileMatchesGroup(file, group));
            if (mine.length) await acceptFiles(mine, group, null);
        }
    });
    container.append(filePicker);




    /** Open the file picker; ``group`` (optional) limits which kinds are accepted. */
    function pickFiles(group, index = null) {
        pendingTarget = group ? { group, index } : null;
        filePicker.accept = group ? group.accept : "image/*,video/*,audio/*";
        filePicker.multiple = !group || group.slots > 1;
        filePicker.click();
    }
    /**
     * Take dropped / picked files. Without a group each file goes to its own kind
     * (pictures -> video -> audio), which is what the unified Add Media tile does.
     */
    async function acceptFiles(files, group = null, index = null) {
        if (!files.length) return 0;
        if (!group) {
            const routed = new Map();
            for (const file of files) {
                const own = groupForFile(file);
                if (!own) continue;
                if (!routed.has(own.key)) routed.set(own.key, { group: own, files: [] });
                routed.get(own.key).files.push(file);
            }
            const media = [...routed.values()];
            if (!media.length) {
                notify(`none of those ${files.length} file(s) are pictures, video or audio - ignored.`);
                return 0;
            }
            let added = 0;
            for (const entry of media) added += await acceptFiles(entry.files, entry.group, null);
            const skipped = files.length - media.reduce((total, entry) => total + entry.files.length, 0);
            if (skipped > 0) notify(`${skipped} file(s) were not media - ignored.`);
            return added;
        }

        const usable = files.filter((file) => fileMatchesGroup(file, group));
        const rejected = files.length - usable.length;
        if (!usable.length) {
            notify(`${group.label}: none of those ${files.length} file(s) are ${group.kind} files - ignored.`);
            return 0;
        }
        let slot = index ?? nextFreeSlot(state.refs, group.key, 0);
        if (slot === null) {
            notify(`${group.label} is full (${group.slots}) - drop onto a tile to replace it.`);
            return 0;
        }
        let added = 0;
        for (const file of usable) {
            if (slot === null) break;
            notify(`uploading ${file.name}...`);
            try {
                const path = await hooks.upload?.(file, group.key);
                if (!path) throw new Error("upload returned no path");
                state.refs[group.key][slot] = {
                    file: String(path),
                    role: state.refs[group.key][slot].role,
                    enabled: true,
                };
                added += 1;
                persist();
                slot = nextFreeSlot(state.refs, group.key, slot + 1);
            } catch (error) {
                notify(`upload failed: ${error.message}`);
                break;
            }
        }
        if (added) {
            notify(`added ${added} ${group.kind} reference(s).`);
            refresh();
            await refreshResults();
        }
        if (rejected > 0) notify(`${rejected} file(s) were not ${group.kind} files - ignored.`);
        if (added < usable.length && rejected === 0) {
            notify(`${group.label} is full - ${usable.length - added} file(s) not added.`);
        }
        return added;
    }
    /** Assign a path from the Browse overlay; without a group it is routed by kind. */
    function assignPath(group, index, path) {
        const owner = group || groupForFile(path);
        if (!owner) {
            notify(`${path} is not a picture, video or audio file - ignored.`);
            return false;
        }
        const target = index ?? nextFreeSlot(state.refs, owner.key, 0);
        if (target === null) {
            notify(`${owner.label} is full (${owner.slots}) - remove one first.`);
            return false;
        }
        state.refs[owner.key][target] = {
            file: String(path),
            role: state.refs[owner.key][target].role,
            enabled: true,
        };
        persist();
        refresh();
        const name = String(path).split("/").pop();
        notify(`${name} added as a ${owner.label.slice(0, -1).toLowerCase()} reference`);
        return true;
    }
    // ------------------------------------------------------ drag and drop
    let dragState = null; // { groupKey, index } while a filled tile is being dragged




    /** A drop is live when files are being dragged, or one of our own tiles is. */
    function dragActive(event) {
        const types = Array.from(event.dataTransfer?.types || []);
        return Boolean(dragState) || types.includes("Files");
    }
    function tileDrop(group, index, event) {
        const files = Array.from(event.dataTransfer?.files || []);
        if (files.length) {
            event.preventDefault();
            // A file of another kind replaces nothing here: it goes to its own kind.
            if (files.every((file) => fileMatchesGroup(file, group))) acceptFiles(files, group, index);
            else acceptFiles(files, null, null);
            return;
        }
        const moving = dragState;
        if (!moving) return;
        event.preventDefault();
        if (moving.groupKey !== group.key) {
            notify(`${group.label} stay together - the prompt numbers each kind separately.`);
            return;
        }
        if (moveSlot(state.refs, group.key, moving.index, index)) {
            persist();
            refresh();
            notify(`reordered ${group.label.toLowerCase()}`);
        }
    }
    // -------------------------------------------------------------- tiles
    /** One filled reference. `ordinal` is its 1-based position in the prompt
     *  (`<Picture 2>`), which is also the badge shown on the tile. */
    function tile(group, index, ordinal, isCanvas = false) {
        const slot = state.refs[group.key][index];
        const wrap = element("div", { className: "mmx-slot mmx-sheet-ref" });
        wrap.dataset.group = group.key;
        wrap.dataset.index = String(index);
        // The tile whose reference is on the canvas says so, so "which one am I looking at" is
        // answerable without reading the header (the canvas is resolved by the caller: with no
        // explicit pick it shows the first picture, and THAT tile is the one to mark).
        if (isCanvas) wrap.classList.add("is-canvas");

        const box = element("div", { className: "mmx-tile is-filled" });
        box.dataset.group = group.key;
        box.dataset.index = String(index);
        box.setAttribute("role", "button");
        box.tabIndex = 0;
        box.title = `${slot.file} — click to choose another file, drop to replace, drag to reorder`;

        const media = group.kind === "image" || group.kind === "video"
            ? element(group.kind === "image" ? "img" : "video", {
                className: "mmx-tile__thumb", draggable: false,
                ...(group.kind === "video" ? { muted: true, playsInline: true, preload: "metadata" } : {}),
            })
            : null;
        if (media && group.kind === "video") media.src = `${viewUrl(refViewUrl(slot.file))}#t=0.1`;
        if (media && group.kind === "image") media.src = viewUrl(refViewUrl(slot.file));
        if (media) {
            // No lazy loading: the tile takes the media's own shape, so the natural
            // size has to arrive (a deferred image would keep the default ratio).
            // A clip has videoWidth/videoHeight and no natural* at all, so the pair has to be
            // chosen by which one exists - reading naturalWidth and videoHeight together would
            // remember an aspect ratio of undefined for every clip tile.
            const read = () => (media.videoWidth
                ? rememberAspect(slot.file, media.videoWidth, media.videoHeight)
                : rememberAspect(slot.file, media.naturalWidth, media.naturalHeight));
            if ((media.complete && media.naturalWidth) || media.readyState >= 1) read();
            else media.addEventListener(group.kind === "image" ? "load" : "loadedmetadata", read, { once: true });
            box.append(media);
        } else {
            // No element to show (audio has no thumbnail): the icon alone. The filename is
            // already the tile's caption below, and saying it twice was pure noise.
            box.append(element("div", { className: "mmx-tile__note" }, {}, [icon(group.kind, { size: 22 })]));
        }
        // Bottom-left corner: the tile's BADGES. For every kind that can have something removed
        // it is that state (the badge cycles auto -> on -> off, so the sentence lives in the
        // tooltip instead of on the tile): a picture or a clip is blurred, a SOUND is muted -
        // there are no pixels in a voice, so the removal is the whole sound - plus how many areas
        // have been painted out of a picture or clip.
        const blurState = kindRemovable(group.kind) ? blurMode(slot) : null;
        const badges = element("div", { className: "mmx-tile__badges" });
        if (group.kind === "video" || group.kind === "audio") {
            // A clip and a sound keep their filename first: which file this is matters more at a
            // glance than its state, the two fit on the row together, and for a sound it is the
            // ONLY place the name appears (the badge row replaces the caption under a tile that
            // has no thumbnail).
            badges.append(element("span", {
                className: "mmx-tile__badge-name",
                textContent: slot.file.split("/").pop(),
                title: slot.file,
            }));
        }
        if (blurState) {
            const isAudio = group.kind === "audio";
            const labels = isAudio ? MUTE_BADGE_LABELS : BLUR_BADGE_LABELS;
            const titles = isAudio ? MUTE_TITLES : BLUR_TITLES;
            const blurBadge = element("button", {
                className: `mmx-badge mmx-badge--blur mmx-badge--${blurState}`,
                type: "button",
                textContent: labels[blurState],
            });
            blurBadge.dataset.blur = blurState;
            blurBadge.title = `${titles[blurState]}\n(click to change)\n${slot.file}`;
            blurBadge.addEventListener("click", (event) => {
                event.stopPropagation();
                slot.blurFace = nextBlurMode(blurState);
                persist();
                renderReferences();
            });
            badges.append(blurBadge);
        }
        const painted = Array.isArray(slot.blurPaint) ? slot.blurPaint.length : 0;
        if (painted) {
            badges.append(element("span", {
                className: "mmx-badge mmx-badge--paint",
                textContent: `${painted} painted`,
                title: `${painted} area(s) painted by hand on this reference - they are blurred\n`
                    + "before the render sees the file, which is how an object (a logo, a tattoo,\n"
                    + "a second person) is taken out. Open preview to add or clear areas.",
            }));
        }
        if (badges.children.length) box.append(badges);
        else if (!media) box.append(element("span", { textContent: slot.file.split("/").pop(), className: "mmx-tile__name" }));

        // Top strip: the kind icon, then the enable checkbox, then (far right, on hover)
        // preview and remove. Everything is in flow in this one row, so nothing can land
        // on top of anything else - and the blur toggle is not here at all (see the
        // foot row below the tile).
        const top = element("div", { className: "mmx-tile__top" });
        const active = slot.enabled !== false;
        const kindChip = element("span", {
            className: `mmx-tile__kind mmx-tile__kind--${group.kind}`,
        });
        kindChip.append(icon(group.kind, { size: 12 }));
        kindChip.title = active
            ? `${group.label} reference - number ${ordinal} of ${group.slots}`
            : `${group.label} reference - unchecked, not sent to the render`;
        const use = element("input", {
            type: "checkbox", checked: active, className: "mmx-tile__use",
        });
        use.title = "Use this reference";
        use.addEventListener("click", (event) => event.stopPropagation());
        use.addEventListener("change", () => {
            slot.enabled = use.checked;
            persist();
            // The numbers belong to the references the run sends, so unchecking one
            // renumbers the tiles after it - show that immediately.
            renderReferences();
        });
        box.append(top);
        box.append(element("span", {
            textContent: active ? String(ordinal) : "\u2013",
            className: active ? "mmx-tile__badge" : "mmx-tile__badge mmx-tile__badge--off",
            title: active
                ? `reference number ${ordinal} in the prompt`
                : "unchecked - this reference is not sent to the render",
        }));

        const actions = element("div", { className: "mmx-tile__actions" });
        if (slot.file) {
            actions.append(
                iconButton("preview", "Preview", (event) => {
                    event.stopPropagation();
                    openPreview(group, index);
                }),
                iconButton("remove", "Remove this reference", (event) => {
                    event.stopPropagation();
                    state.refs[group.key][index] = { file: "", role: slot.role, enabled: false };
                    persist();
                    refresh();
                }, "mmx-btn--danger"),
            );
        }
        // Top row: only the kind badge and the "use" checkbox. The hover actions are a
        // vertical stack in the top-right corner (see .mmx-tile__actions), so they cannot
        // push this row wide and off the tile.
        top.append(kindChip, use);
        box.append(actions);

        box.addEventListener("click", () => {
            // Clicking a tile LOADS it into the canvas (that is where a reference is worked on:
            // blur, paint, compare). An empty tile has nothing to load, so it still opens the
            // picker - and "Replace..." on the canvas head changes the file of a filled one.
            if (!slot.file) {
                pickFiles(group, index);
                return;
            }
            canvasPick = { group: group.key, index };
            renderReferences();
        });
        box.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                box.click();
            }
        });

        if (slot.file) {
            box.draggable = true;
            box.addEventListener("dragstart", (event) => {
                dragState = { group, groupKey: group.key, index };
                // The same drag also carries "this picture" for a stage cell: dropping a tile on a
                // panel says the likeness of that panel comes from this reference (see
                // `applyCellDrop`), while dropping it on another tile still moves the slot.
                //
                // The number is the TAG number (the ordinal among the references this run actually
                // sends - what the tile's badge shows and `<Picture N>` means), not the array
                // position: an unchecked tile shifts the tags, and the prompt follows the tags. A
                // tile that is not sent carries no payload at all - it cannot supply a face.
                dragCell = ordinal
                    ? {
                        kind: "ref", key: `${group.key}:${ordinal - 1}`, group, index,
                        label: `${group.label.slice(0, -1)} ${ordinal}`,
                    }
                    : null;
                box.classList.add("is-drag");
                if (event.dataTransfer) {
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", `mmx-slot:${group.key}:${index}`);
                }
            });
            box.addEventListener("dragend", () => {
                dragState = null;
                dragCell = null;
                box.classList.remove("is-drag");
            });
        }

        box.addEventListener("dragover", (event) => {
            if (!dragActive(event)) return;
            event.preventDefault();
            event.stopPropagation();
            box.classList.add("is-dropping");
        });
        box.addEventListener("dragleave", () => box.classList.remove("is-dropping"));
        box.addEventListener("drop", (event) => {
            box.classList.remove("is-dropping");
            event.stopPropagation();
            tileDrop(group, index, event);
        });

        const role = textInput(slot.role, group.role, (value) => {
            slot.role = value;
            persist();
        }, "mmx-input mmx-role mmx-sheet-ref-role");
        role.title = "What this reference is for (goes into every cell prompt)";

        // The role box gets the whole row: it is the one thing here that is typed into,
        // so nothing sits beside it (the blur toggle is on the picture instead).
        wrap.append(box, role);
        // Registered so the fixed-size box can re-fit every tile together.
        renderedTiles.push({ group, index, file: slot.file, wrap, box });
        return wrap;
    }

    /**
     * The single "Add Media" tile that ends the grid - one faint dashed tile, and one
     * file picker for pictures, video and audio (each file is routed by its kind).
     */
    function addMediaTile({ empty = false } = {}) {
        const wrap = element("div", { className: "mmx-slot mmx-sheet-add-slot" });
        const box = element("div", { className: `mmx-tile mmx-tile--add${empty ? " mmx-tile--add-empty" : ""}` });
        box.dataset.action = "add-media";
        box.setAttribute("role", "button");
        box.tabIndex = 0;
        box.title = "Add pictures, video or audio - drop files here, or click to browse";
        box.append(element("div", { className: "mmx-tile__note" }, {}, [
            icon("plus", { size: 20 }),
            element("span", {
                textContent: empty ? "Add Media - drop pictures, video or audio here" : "Add Media",
                className: "mmx-muted",
            }),
        ]));

        box.addEventListener("click", () => openBrowse(null, null));
        box.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                box.click();
            }
        });
        box.addEventListener("dragover", (event) => {
            if (!dragActive(event)) return;
            event.preventDefault();
            event.stopPropagation();
            box.classList.add("is-dropping");
        });
        box.addEventListener("dragleave", () => box.classList.remove("is-dropping"));
        box.addEventListener("drop", (event) => {
            box.classList.remove("is-dropping");
            event.stopPropagation();
            const files = Array.from(event.dataTransfer?.files || []);
            if (files.length) {
                event.preventDefault();
                acceptFiles(files, null, null);
                return;
            }
            const moving = dragState;
            if (!moving) return;
            const group = moving.group;
            const free = group ? nextFreeSlot(state.refs, group.key, 0) : null;
            if (group && free !== null && free !== moving.index
                && moveSlot(state.refs, group.key, moving.index, free)) {
                event.preventDefault();
                persist();
                refresh();
                notify(`moved ${group.label.toLowerCase()}`);
            }
        });

        wrap.append(box);
        return wrap;
    }

    // ------------------------------------------------------------- background
    /**
     * The wired references a ``reference`` backdrop can borrow a setting from.
     *
     * Value = ``"<group key>:<index>"`` with the index the RUN uses (0-based, counting only
     * the enabled references), which is exactly the number in the prompt's ``<Picture N>``
     * tag - so the panel and the node cannot disagree about which photo is meant. Audio has
     * no picture to take a room from and is not offered.
     */
    function backgroundRefOptions() {
        return mediaSlots(state.refs)
            .filter((entry) => entry.active !== false && entry.group.kind !== "audio")
            .map((entry) => {
                const slot = state.refs?.[entry.group.key]?.[entry.index] || {};
                const role = String(slot.role || "").trim();
                const file = String(slot.file || "").split("/").pop();
                const tag = refTagLabel(entry.group.kind, entry.ordinal);
                return { value: `${entry.group.key}:${entry.ordinal - 1}`, label: `${tag} \u00b7 ${role || file}` };
            });
    }

    /** ``"pictures:1"`` -> ``"<Picture 2>"`` (used to name a reference that is gone). */
    function backgroundRefKeyLabel(key) {
        const [group, slot] = String(key || "").split(":");
        const kind = String(group || "").replace(/s$/, "");
        return Number.isFinite(Number(slot)) && slot !== ""
            ? refTagLabel(kind, Number(slot) + 1)
            : String(key || "");
    }

    /** Backdrop for every cell: a preset, one of the references, or the user's own words. */
    function backgroundRow() {
        const wrap = element("div", { className: "mmx-tickgroup mmx-tickgroup--background" });
        const row = element("div", { className: "mmx-row" }, { flexWrap: "wrap" });
        row.append(element("span", { textContent: "Background", className: "mmx-tickgroup__label" }));
        const box = textInput(
            state.backgroundCustom || "",
            "behind the character, e.g. deep red velvet curtain",
            (value) => {
                state.backgroundCustom = value;
                persist();
            },
            "mmx-input mmx-sheet-background-custom",
        );
        box.style.flex = "1 1 180px";
        box.style.minWidth = "140px";
        const select = selectBox(BACKGROUNDS, state.background || "neutral", (value) => {
            state.background = value;
            persist();
            refresh();
        }, "mmx-select mmx-sheet-background");

        // The reference picker only exists for the one backdrop that needs it, but the
        // custom text box stays in the row (hidden) so switching back does not move things.
        const choice = state.background || "neutral";
        const options = backgroundRefOptions();
        const chosen = String(state.backgroundRef || "").trim();
        if (chosen && !options.some((entry) => entry.value === chosen)) {
            // The chosen reference was emptied or unchecked since: show it as-is so the
            // picker never silently displays a different reference than the payload sends.
            options.unshift({ value: chosen, label: `${backgroundRefKeyLabel(chosen)} \u00b7 not wired any more` });
        }
        const refWrap = element("div", { className: "mmx-row" }, { flex: "1 1 220px", gap: "4px" });
        const refSelect = selectBox(
            options.length
                ? options.map((entry) => [entry.value, entry.label])
                : [["", "no picture or video references yet"]],
            chosen,
            (value) => {
                state.backgroundRef = value;
                persist();
            },
            "mmx-select mmx-sheet-background-ref",
        );
        refSelect.title = "Use this reference's own setting behind the character - nobody and nothing from it is kept";
        if (!options.length) refSelect.disabled = true;
        refWrap.append(refSelect);
        if (!options.length) {
            refWrap.append(element("span", {
                textContent: "add a picture or video on the References tab first",
                className: "mmx-muted",
            }, { fontSize: "10px" }));
        }
        refWrap.style.display = choice === "reference" ? "" : "none";
        box.style.display = choice === "custom" ? "" : "none";

        row.append(select, refWrap, box);
        wrap.append(row);
        return wrap;
    }

    // ------------------------------------------------------- prompt card
    function promptCard() {
        const card = element("div", { className: "mmx-card" });
        const head = element("div", { className: "mmx-card__head" });
        head.append(
            element("span", { textContent: "Character", className: "mmx-label" }),
            element("span", {
                textContent: "who this is (identity / style) and what to keep out",
                className: "mmx-muted",
            }),
        );
        const rows = element("div", {}, { display: "grid", gap: "4px" });
        const promptBox = element("textarea", {
            value: state.prompt || "",
            placeholder: "young woman with long silver hair, blue eyes, petite, casual streetwear",
            className: "mmx-input mmx-sheet-prompt",
            rows: 2,
        }, { width: "100%", resize: "vertical", minHeight: "34px" });
        promptBox.title = "Goes at the top of every cell prompt: identity, hair, body, style";
        promptBox.addEventListener("input", () => {
            state.prompt = promptBox.value;
            persist();
        });
        const negativeBox = element("textarea", {
            value: state.negative || "",
            placeholder: "text, watermark, logo, phone, extra people",
            className: "mmx-input mmx-sheet-negative",
            rows: 1,
        }, { width: "100%", resize: "vertical", minHeight: "26px" });
        negativeBox.title = "Added to every cell prompt as \u201cDo not include: \u2026\u201d";
        negativeBox.addEventListener("input", () => {
            state.negative = negativeBox.value;
            persist();
        });
        rows.append(
            promptBox,
            element("div", { textContent: "Suppress", className: "mmx-muted" }),
            negativeBox,
            element("div", {
                textContent: "Name the attribute in each role - face, hair, clothing, body shape - and "
                    + "every cell takes it from that picture alone.",
                className: "mmx-muted",
                title: "Roles decide which picture supplies what: name the attribute in each role "
                    + "(face, hair, glasses / body, clothes). Every cell prompt then tells H3 to take "
                    + "that from its picture and not from the others, and a picture whose role does "
                    + "not mention the face can be blurred instead (see the tile badges).",
            }, { marginTop: "4px" }),
        );
        card.append(head, rows);
        return { card, promptBox, negativeBox };
    }

    // ------------------------------------------------------- ref sections
    /**
     * One grid for every reference.
     *
     * It used to be three stacked sections (pictures / videos / audios); the tiles are
     * the same but they share one fixed-size area, carry a kind badge, and are sorted
     * pictures -> video -> audio. The prompt tags stay per kind, so nothing about the
     * payload changed - only how it is presented.
     */
    // Which reference is loaded into the canvas at the top of the tab. Held as a group key +
    // index and re-resolved on every render, because slots move: a drag, a remove or a Clear
    // must not leave the canvas pointing at a file that is no longer there.
    let canvasPick = null;

    /** The slot the canvas should show: the pick if it still exists, else the first picture. */
    function canvasTarget(filled) {
        if (canvasPick) {
            const hit = filled.find((entry) => entry.group.key === canvasPick.group
                && entry.index === canvasPick.index);
            if (hit) return { group: hit.group, index: hit.index };
        }
        const first = filled.find((entry) => entry.group.kind === "image") || filled[0];
        return first ? { group: first.group, index: first.index } : null;
    }

    /**
     * The canvas: the reference you are working on, at the size the pane allows, with its tools ON
     * the picture instead of in a form beside it. Clicking a tile loads it here; the tiles below
     * stay the index of everything the run sends.
     */
    function canvasCard(filled, target) {
        const wrap = element("div", { className: "mmx-canvas" });
        wrap.dataset.action = "ref-canvas";
        // The share is the picture's height budget inside the pane: the paint tools and the blur
        // chips sit under it, and the sum has to fit the half the stage gets (see NODE_HEIGHT).
        // With the before/after pair gone the picture takes 0.72 of a 608px pane (~350px) and the
        // tools under it stay visible without scrolling.
        const parts = target
            ? referenceParts(target.group, target.index, { inlineHeightShare: 0.78 })
            : null;
        if (!parts) {
            // Nothing is wired yet. A fresh node used to open on a bare dashed box, which reads as a
            // broken pane rather than as "this is where a reference goes" - so the canvas shows the
            // pack's own sample render instead, sized like a reference and captioned as what it is.
            // It is a PLACEHOLDER: it is never in the payload, never in a graph, and the first
            // reference wired (or selected) replaces it.
            const art = placeholderArt();
            if (art) {
                const empty = element("div", { className: "mmx-canvas__empty mmx-canvas__empty--art" });
                empty.dataset.action = "ref-canvas-empty";
                empty.append(element("img", {
                    src: art,
                    alt: "the pack's sample character render",
                    className: "mmx-canvas__art",
                    title: "A sample render that ships with the pack - it is not part of your sheet. "
                        + "Add a reference and it opens here instead.",
                }));
                empty.append(element("div", { className: "mmx-canvas__artnote" }, {}, [
                    element("span", { textContent: "No references yet", className: "mmx-title" }),
                    element("span", {
                        textContent: "the picture is the pack's sample render, waiting for yours - "
                            + "a reference opens here to blur, paint or check against the original",
                        className: "mmx-muted",
                    }),
                ]));
                wrap.append(empty);
                return wrap;
            }
            wrap.append(element("div", { className: "mmx-canvas__empty" }, {}, [
                element("span", {
                    textContent: "Add a reference - it opens here to blur, paint or check against the original",
                    className: "mmx-muted",
                }),
            ]));
            return wrap;
        }
        const head = element("div", { className: "mmx-canvas__head" });
        head.append(
            element("span", {
                textContent: `${target.group.label.slice(0, -1)} ${target.index + 1}`,
                className: "mmx-title",
            }),
            element("span", {
                textContent: parts.slot.file.split("/").pop(),
                className: "mmx-muted",
                title: parts.slot.file,
            }),
            element("span", { className: "mmx-spacer" }),
        );
        // The tile's click selects; THIS is where you change the file, which is why the word
        // lives here (there is room) and the tiles keep their two hover icons.
        const replace = button("Replace...", () => openBrowse(target.group, target.index));
        replace.dataset.action = "ref-replace";
        replace.title = "Choose another file for this reference";
        head.append(replace);
        wrap.append(head, parts.stage, ...parts.extras);
        // B' puts "Blur area" directly under the picture, next to the thing it affects, instead of
        // in the list's header a column away. It is one setting for the whole sheet (a look, not a
        // per-picture decision): the tile's chip says WHETHER, this says HOW MUCH.
        const blurRow = chipChoice(
            "Blur area",
            BLUR_SCOPES,
            blurScope(state),
            (value) => {
                state.blurScope = value;
                persist();
                refresh();
            },
            "the patch grows around what is detected",
        );
        blurRow.dataset.action = "blur-scope";
        wrap.append(blurRow);
        return wrap;
    }

    function renderReferences() {
        // The surfaces about to be discarded must not stay in the registry: it holds closures over
        // their (dead) DOM.
        paintSyncs.length = 0;
        refsHost.replaceChildren();
        refsColumn.replaceChildren();
        refreshRefsMini();
        const prompt = promptCard();

        const filled = mediaSlots(state.refs);
        const capacity = REF_GROUPS.reduce((total, group) => total + group.slots, 0);

        const card = element("div", { className: "mmx-card mmx-card--refs" });
        const head = element("div", { className: "mmx-card__head" });
        const browse = button("Browse ComfyUI", () => openBrowse(null, null));
        browse.dataset.action = "browse-media";
        const upload = button("Add Media", () => pickFiles(null, null));
        upload.dataset.action = "add-media";
        const clear = button("Clear", () => {
            for (const group of REF_GROUPS) {
                state.refs[group.key] = state.refs[group.key].map((slot) => ({
                    file: "", role: slot.role, enabled: false,
                }));
            }
            persist();
            refresh();
        });
        clear.dataset.action = "clear-media";
        clear.classList.add("mmx-btn--danger");
        // The list's head says WHAT IS IN THE LIST, and nothing else: B' puts the per-kind counts
        // here ("9 pictures · 3 video · 3 audio") and hands the blur area to the stage, where the
        // picture it applies to is on screen.
        const perKind = [];
        for (const group of REF_GROUPS) {
            const n = filled.filter((entry) => entry.group.key === group.key).length;
            if (!n) continue;
            const noun = group.label.toLowerCase();
            perKind.push(`${n} ${n === 1 ? noun.replace(/s$/, "") : noun}`);
        }
        head.append(
            element("span", { textContent: "References", className: "mmx-label" }),
            element("span", { textContent: `${filled.length}/${capacity}`, className: "mmx-count mmx-sheet-count" }),
            element("span", {
                textContent: perKind.length ? perKind.join(" · ") : "nothing yet",
                className: "mmx-muted mmx-refcounts",
            }),
            element("span", { className: "mmx-spacer" }),
            browse, upload, clear,
        );

        const boxHost = element("div", { className: "mmx-refbox" });
        // The floor lives in the stylesheet (`.mmx-refbox` min-height, = REF_SECTION.height) and
        // NOT inline: the two-column studio raises that floor in its own column, which an inline
        // style would win against. The tile maths below reads the box's live clientWidth/Height,
        // so a taller or wider node means bigger tiles rather than a strip with empty space.
        renderedTiles = [];
        const canvasAt = canvasTarget(filled);
        for (const entry of filled) {
            const onCanvas = Boolean(canvasAt && canvasAt.group.key === entry.group.key
                && canvasAt.index === entry.index);
            boxHost.append(tile(entry.group, entry.index, entry.ordinal, onCanvas));
        }
        if (filled.length < capacity) boxHost.append(addMediaTile({ empty: filled.length === 0 }));
        // The column: the reference list. The stage: the picture, with its own head, paint bar
        // and before/after pair (canvasCard builds all three).

        const takeDrop = (event) => {
            event.preventDefault();
            const files = Array.from(event.dataTransfer?.files || []);
            if (files.length) {
                acceptFiles(files, null, null);
                return;
            }
            const moving = dragState;
            if (!moving) return;
            const group = moving.group;
            const free = group ? nextFreeSlot(state.refs, group.key, 0) : null;
            if (group && free !== null && moveSlot(state.refs, group.key, moving.index, free)) {
                persist();
                refresh();
                notify(`moved ${group.label.toLowerCase()}`);
            }
        };
        card.addEventListener("dragover", (event) => {
            if (!dragActive(event)) return;
            event.preventDefault();
            card.classList.add("is-drop");
        });
        card.addEventListener("dragleave", (event) => {
            if (card.contains(event.relatedTarget)) return;
            card.classList.remove("is-drop");
        });
        card.addEventListener("drop", (event) => {
            card.classList.remove("is-drop");
            takeDrop(event);
        });
        // The drop handlers below stay on this card: it is the reference LIST now, and the list is
        // what a file lands on (the stage next door holds the picture they are edited in).
        card.append(head, boxHost);
        refsColumn.append(card);
        refsColumn.append(mutedHint(
            "Drop files anywhere in this box - pictures, then video, then audio; the badge is their number in the prompt.",
            "Each file goes to its own kind (pictures first, then video, then audio) by extension, so a drop "
            + "of mixed files lands where it belongs. The box keeps its size and the tiles scale to fit it.",
        ));
        const stageCard = element("div", { className: "mmx-card mmx-card--stage" });
        stageCard.append(canvasCard(filled, canvasAt));
        // The stage is the PICTURE and its tools - the thing you work on, at the size the half
        // gives it. The identity brief is typing, not looking, so it lives in the column under
        // the reference list: two halves that each hold one kind of work instead of one half
        // holding both and scrolling.
        refsHost.append(stageCard);
        refsColumn.append(prompt.card);
        layoutTiles();
    }

    // ------------------------------------------------- the paint surfaces
    // Every mounted picture/clip registers its own `sync` here. A tab switch does not resize the
    // panel, so no ResizeObserver fires for it - and a surface that was measured while its pane was
    // hidden has no box to measure (it kept the size it guessed, which is how a picture ends up
    // taller than the half it lives in). Re-measuring on the way in is what keeps every tab's
    // stage the size of the stage.
    const paintSyncs = [];
    function syncPaintSurfaces() {
        for (const sync of paintSyncs) {
            try {
                sync();
            } catch (error) {
                // A surface whose picture never loaded has nothing to measure: it is not worth
                // breaking the tab switch over.
                void error;
            }
        }
    }

    // ------------------------------------------------------- tile sizing
    /** Measured media shapes, keyed by file: a tile takes its media's own aspect. */
    const tileAspects = new Map();
    let renderedTiles = [];
    let layoutQueued = false;

    /** Re-fit every tile into the fixed reference box (cheap, no DOM churn). */
    function layoutTiles() {
        layoutQueued = false;
        if (!renderedTiles.length) return;
        const box = renderedTiles[0].box.closest(".mmx-refbox");
        const measured = box?.clientWidth || 0;
        const width = measured > 40 ? measured - 2 * REF_SECTION.gap : REF_SECTION.width;
        const height = Math.max(
            REF_SECTION.minTile,
            (box?.clientHeight || REF_SECTION.height) - REF_SECTION.roleHeight - 2 * REF_SECTION.gap,
        );
        const aspects = renderedTiles.map((entry) => tileAspect(entry.group, entry.file, tileAspects));
        const { tileHeight } = fitTileLayout(aspects, { width, height, gap: REF_SECTION.gap });
        renderedTiles.forEach((entry, index) => {
            const ratio = aspects[index];
            entry.box.style.height = `${Math.round(tileHeight)}px`;
            entry.box.style.width = `${Math.max(24, Math.round(tileHeight * ratio))}px`;
            entry.wrap.style.width = `${Math.max(24, Math.round(tileHeight * ratio))}px`;
        });
        const add = box?.querySelector(".mmx-tile--add");
        if (add) {
            add.style.height = `${Math.round(tileHeight)}px`;
            add.style.width = `${Math.round(Math.max(70, tileHeight * 1.2))}px`;
        }
    }

    function queueLayout() {
        if (layoutQueued) return;
        layoutQueued = true;
        if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => layoutTiles());
        else setTimeout(() => layoutTiles(), 0);
    }

    /** Remember a media's shape the first time we see it, then re-fit the row. */
    function rememberAspect(file, width, height) {
        const ratio = clampAspect(Number(width) / Number(height));
        if (!file || !ratio || tileAspects.get(file) === ratio) return;
        tileAspects.set(file, ratio);
        queueLayout();
    }

    // ----------------------------------------------------------- overlays
    let overlay = null;
    function closeOverlay() {
        overlay?.remove();
        overlay = null;
        delete container.dataset.overlay;
        delete container.dataset.browseFor;
    }

    function openOverlay(className) {
        closeOverlay();
        overlay = element("div", { className: `mmx-overlay ${className}` });
        overlay.dataset.overlay = className;
        overlay.addEventListener("mousedown", (event) => {
            if (event.target === overlay) closeOverlay();
        });
        container.append(overlay);
        container.dataset.overlay = className;
        return overlay;
    }

    /**
     * The preview stage for one picture, with the face blur in it.
     *
     * "Preview" used to mean "the file as it is". For a picture that is going to be
     * blurred before the render wires it, that is the wrong picture: this shows the copy
     * the render will actually use, and offers the original for comparison. The blur is
     * computed by the same route the render uses (cached on disk), and the route reports
     * whether the render would blur this reference at all - so a photo that is left alone
     * says so instead of showing an edit that will not happen.
     */
    function blurPreviewBar(slot, media, slotIndex, kind = "image") {
        // The blur bar carries its own hook class as well as the shared bar styling: the paint
        // toolbar wears `mmx-preview__bar` too (same shape), so a selector for "the bar that says
        // what the render sends" must not be able to land on the brushes.
        const bar = element("div", { className: "mmx-preview__bar mmx-preview__blurbar" });
        const note = element("span", { className: "mmx-muted", textContent: "checking the face blur…" });
        const original = viewUrl(refViewUrl(slot.file));
        const originalButton = button("Original", () => show("original"));
        const blurredButton = button("Blurred", () => show("blurred"));
        blurredButton.dataset.action = "preview-blur";
        let blurredUrl = "";
        let applies = null;
        let report = null;

        function mark(which) {
            originalButton.classList.toggle("is-active", which === "original");
            blurredButton.classList.toggle("is-active", which === "blurred");
        }
        function show(which) {
            if (which === "blurred" && blurredUrl) {
                media.src = blurredUrl;
                mark("blurred");
                use("blurred");
            } else {
                media.src = original;
                mark("original");
                use("original");
            }
        }
        function use(which) {
            if (!report) return;
            const scope = (BLUR_SCOPES.find(([key]) => key === blurScope(state)) || [])[1];
            const detail = report.reason ? ` — ${report.reason}` : "";
            if (which === "blurred") {
                note.textContent = applies
                    ? `What the render sends: faces blurred, area "${scope}"${detail}`
                    : `Not what the render sends: this reference is left as it is `
                        + `(mode "${blurMode(slot)}")${detail}`;
            } else if (applies) {
                note.textContent = `The original. The render sends the blurred copy (area "${scope}").`;
            } else {
                note.textContent = `The render sends this reference unchanged (mode "${blurMode(slot)}")${detail}`;
            }
        }

        const fetchBlur = async () => {
            try {
                const answer = await hooks.blurReference?.({
                    file: slot.file,
                    scope: blurScope(state),
                    slot: slotIndex,
                    // Which pass the route should run: a clip is sampled, tracked and re-encoded,
                    // so guessing from the slot number would blur the wrong reference.
                    kind,
                });
                report = answer || null;
                if (answer?.ok && answer.url) {
                    blurredUrl = viewUrl(answer.url);
                    applies = answer.applies === true;
                    blurredButton.disabled = false;
                    show(applies ? "blurred" : "original");
                } else {
                    blurredButton.disabled = true;
                    note.textContent = answer?.applies === false
                        ? `Nothing to blur: the render sends this one as it is `
                            + `(mode "${blurMode(slot)}") - paint on it to blur an area.`
                        : `Nothing to blur: ${answer?.reason || "face blur unavailable"}`;
                }
            } catch (error) {
                blurredButton.disabled = true;
                note.textContent = `Nothing to blur: ${error.message}`;
            }
        };

        blurredButton.disabled = true;
        bar.append(originalButton, blurredButton, element("span", { className: "mmx-spacer" }), note);
        // No side-by-side pair under the picture: the Original/Blurred buttons already switch the
        // one picture between the file and the copy the render wires, and the sentence beside them
        // says which one is on screen. Two extra thumbnails of the same photo cost a third of the
        // stage's height and told the reader nothing the toggle did not.
        fetchBlur();
        return bar;
    }

    function openPreview(group, index) {
        const parts = referenceParts(group, index);
        if (!parts) return;
        const pane = openOverlay("mmx-preview");
        const head = element("div", { className: "mmx-overlay__head" });
        head.append(
            element("span", { textContent: `${group.label.slice(0, -1)} ${index + 1}`, className: "mmx-title" }),
            element("span", { textContent: parts.slot.file, className: "mmx-muted" }),
            element("span", { className: "mmx-spacer" }),
            button("Close", closeOverlay),
        );
        pane.append(head, parts.stage, ...parts.extras);
    }

    /**
     * Everything a reference is worked on with: its media in a stage, and the bars that go with it.
     *
     * ONE builder, two homes. The Preview button opens these parts in the overlay it always did,
     * and the canvas at the top of the References tab mounts them INLINE (see canvasCard) - so the
     * paint surface, the before/after bar and the blur note are literally the same code in both
     * places and cannot drift apart.
     */
    function referenceParts(group, index, options = null) {
        const { inlineHeightShare = null } = options || {};
        const slot = state.refs[group.key][index];
        if (!slot?.file) return null;
        const stage = element("div", { className: "mmx-preview__stage" });
        const url = viewUrl(refViewUrl(slot.file));
        // The prompts number the ENABLED references, and so does the engine: an unchecked
        // tile before this one shifts everything, so the slot has to be the ordinal from
        // mediaSlots rather than the raw array index.
        const entry = (mediaSlots(state.refs) || [])
            .find((item) => item.group.key === group.key && item.index === index);
        const slotNumber = Math.max(0, (entry?.ordinal || 1) - 1);
        const extras = [];
        if (group.kind === "image") {
            const image = element("img", { src: url, alt: slot.file });
            const paint = mountPaintSurface(slot, image, slotNumber, options);
            stage.append(paint.frame);
            extras.push(paint.toolbar, blurPreviewBar(slot, image, slotNumber));
        } else if (group.kind === "video") {
            // A clip is painted and previewed exactly like a picture: the surface sits over the
            // frame the video is showing (it is paused on its first frame), and the painting is
            // held across the whole clip by the engine, which is what makes painting a clip
            // useful at all - mark a logo once and it is gone from every frame.
            const clip = element("video", {
                src: url, controls: true, loop: true, playsInline: true, muted: true,
            });
            const paint = mountPaintSurface(slot, clip, slotNumber, options);
            stage.append(paint.frame);
            extras.push(paint.toolbar, blurPreviewBar(slot, clip, slotNumber, "video"));
        } else {
            // A sound has nothing to paint, but it does have an Original/Muted comparison: the
            // same bar, over the player, with the same route behind it.
            const sound = element("audio", { src: url, controls: true });
            stage.append(sound);
            extras.push(blurPreviewBar(slot, sound, slotNumber, "audio"));
        }
        return { slot, stage, extras, slotNumber };
    }

    /**
     * The paint surface: drag over the reference to mark exactly what to blur.
     *
     * A ``brush`` is a freehand stroke of the current radius, a ``lasso`` closes into a
     * filled shape for covering a large area in one gesture. Strokes go straight into the
     * reference (``slot.blurPaint``) and are persisted as they are drawn, so a save keeps
     * the painting and the render wires it. They are *added* to whatever the face-blur
     * mode blurs - with the mode at ``Blur off`` the painting is the only blur.
     */
    function mountPaintSurface(slot, image, slotNumber, options = null) {
        // `inlineHeightShare` is what referenceParts passes (the inline canvas takes a SHARE of the
        // pane); `heightShare` is the older name the overlay used. Reading only one of them meant
        // the share silently never applied to the canvas.
        const { heightShare = null, inlineHeightShare = null } = options || {};
        const share = inlineHeightShare ?? heightShare;
        const frame = element("div", { className: "mmx-paint__frame" });
        const canvas = element("canvas", { className: "mmx-paint__canvas is-idle" });
        frame.append(image, canvas);
        const strokes = () => (Array.isArray(slot.blurPaint) ? slot.blurPaint : (slot.blurPaint = []));
        const note = element("span", { className: "mmx-muted" });
        let tool = "brush";
        let radius = DEFAULT_PAINT_RADIUS;
        let drawing = null;
        let painting = false;

        function redraw() {
            const ctx = canvas.getContext?.("2d");
            if (!ctx) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const all = drawing ? [...strokes(), drawing] : strokes();
            for (const stroke of all) drawPaintedStroke(ctx, stroke, canvas.width, canvas.height);
        }

        /** Canvas size follows the drawn image, so a point maps 1:1 to the picture.
         *
         * The frame is given the image's shape and scaled into the stage by hand rather
         * than by CSS: percentage heights inside an auto-sized box resolve to nothing,
         * which left a 0x0 canvas the pointer could not reach.
         */
        function sync() {
            // A picture reports naturalWidth, a clip reports videoWidth - both are "how big is
            // the thing being painted" and the surface is the same either way.
            const naturalWidth = image.naturalWidth || image.videoWidth || 1;
            const naturalHeight = image.naturalHeight || image.videoHeight || 1;
            // The pane grows with its content, so the stage never constrains the frame by
            // itself: the pane's own max-height is the real ceiling (it is what keeps the
            // node from growing), minus the header and the two bars around the stage.
            //
            // The surface is BUILT before it is mounted (the caller appends `frame` to its stage),
            // and an already-cached image completes synchronously - so this first call can arrive
            // with no parent at all. Measuring then reads zeros and `getComputedStyle` needs an
            // element, so it bails out; the deferred pass below (and the first paint) call it again
            // once the frame is in the document. That is how a picture the browser already had
            // cached used to throw and leave the preview blank.
            const host = frame.closest(".mmx-pane") || frame.parentElement;
            if (!host) return;
            const stage = frame.parentElement;
            // The WIDTH comes from the stage when the stage is its own box: in the two-column
            // references studio the picture's home is one column of the card, not the whole pane,
            // and measuring the pane there scaled the picture for a width it does not have (the
            // frame overflowed its column and stretched the card to over a thousand pixels). The
            // pane is still the HEIGHT ceiling - that is the box the node gives us.
            const stageWidth = (stage && stage !== host ? stage.clientWidth : 0) || 0;
            let availableWidth = (stageWidth || host.clientWidth || naturalWidth);
            let availableHeight = (host.clientHeight || stage?.clientHeight || naturalHeight);
            const cap = parseFloat(globalThis.getComputedStyle?.(host)?.maxHeight || "");
            if (Number.isFinite(cap) && cap > 0) availableHeight = Math.min(availableHeight, cap);
            // Inline (the canvas at the top of the tab) the picture takes a SHARE of the pane, not
            // all of it: the tiles are the index of everything the run sends and being able to see
            // them is the point of the canvas being at the top rather than a tab of its own.
            if (share && host.clientHeight) {
                availableHeight = Math.min(availableHeight, host.clientHeight * share);
            }
            // A stage is never taller than its own width. With the picture's home now a column
            // instead of the whole pane, the pane's height stops being a useful ceiling for it -
            // and in a harness with no node the pane grows with whatever the stage asks for, which
            // is a feedback loop rather than a measurement. The width of the column is the bound
            // that does not depend on the thing being measured.
            if (stageWidth) availableHeight = Math.min(availableHeight, stageWidth);
            availableHeight = Math.max(60, availableHeight - 84);
            availableWidth = Math.max(60, availableWidth);
            const scale = Math.min(availableWidth / naturalWidth, availableHeight / naturalHeight);
            const width = Math.max(1, Math.round(naturalWidth * scale));
            const height = Math.max(1, Math.round(naturalHeight * scale));
            frame.style.width = `${width}px`;
            frame.style.height = `${height}px`;
            canvas.width = width;
            canvas.height = height;
            redraw();
        }
        function updateNote() {
            if (!painting) {
                note.textContent = strokes().length
                    ? `${strokes().length} painted area(s) — Apply to blur them (plus any detected faces).`
                    : "Paint over anything you want blurred.";
                return;
            }
            note.textContent = tool === "brush"
                ? "Drag to paint over the area, then Apply."
                : "Draw a loop around the area, then Apply.";
        }

        // A clip has no ``load``: its size arrives with the metadata, which for a local file is
        // usually before this line runs - so the ready check comes first and the listener is the
        // fallback, exactly as for a cached picture.
        if (image.videoWidth) sync();
        else if (image.complete && image.naturalWidth) sync();
        else image.addEventListener(image.tagName === "VIDEO" ? "loadedmetadata" : "load", sync, { once: true });
        // The pane may not have been laid out when the surface is built (a first sync then
        // falls back to the image's natural size and the frame overflows the stage), so
        // measure again once the browser has painted. Painting itself re-syncs too.
        const nextFrame = globalThis.requestAnimationFrame
            ? (fn) => globalThis.requestAnimationFrame(fn)
            : (fn) => setTimeout(fn, 16);
        nextFrame(() => nextFrame(sync));
        paintSyncs.push(sync);

        canvas.addEventListener("pointerdown", (event) => {
            if (!painting) return;
            // The frame is sized from the image, so marking before it has loaded would
            // paint against a placeholder shape and land in the wrong place.
            if (!image.naturalWidth && !image.videoWidth) {
                note.textContent = "waiting for the reference to load…";
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            sync();
            try {
                // Keeps the stroke alive when the pointer leaves the canvas. It throws
                // when there is no active pointer to capture (a synthetic event, or a
                // capture already lost), and that must not lose the stroke.
                canvas.setPointerCapture?.(event.pointerId);
            } catch {
                /* no capture: the stroke still paints while the pointer is over it */
            }
            const [x, y] = paintPoint(canvas.getBoundingClientRect(), event.clientX, event.clientY);
            drawing = { tool, radius, points: [[x, y]] };
            redraw();
        });
        canvas.addEventListener("pointermove", (event) => {
            if (!painting || !drawing) return;
            event.stopPropagation();
            const [x, y] = paintPoint(canvas.getBoundingClientRect(), event.clientX, event.clientY);
            const last = drawing.points[drawing.points.length - 1];
            if (Math.abs(x - last[0]) + Math.abs(y - last[1]) < 0.004) return;
            drawing.points.push([x, y]);
            redraw();
        });
        const finishStroke = () => {
            if (!drawing) return;
            const stroke = drawing;
            drawing = null;
            // A lasso needs an outline to fill; a stray click is not one.
            if (stroke.tool !== "lasso" || stroke.points.length >= 3) {
                strokes().push(stroke);
                persist();
            }
            redraw();
            updateNote();
        };
        canvas.addEventListener("pointerup", finishStroke);
        canvas.addEventListener("pointercancel", finishStroke);
        canvas.addEventListener("pointerleave", finishStroke);

        const toolbar = element("div", { className: "mmx-preview__bar" });
        const toolSeg = element("div", { className: "mmx-seg" });
        const buttons = {};
        for (const [key, label] of [["brush", "Brush"], ["lasso", "Lasso"]]) {
            const node = button(label, () => {
                tool = key;
                for (const [id, element_] of Object.entries(buttons)) {
                    element_.classList.toggle("is-active", id === tool);
                }
                updateNote();
            });
            node.dataset.paintTool = key;
            buttons[key] = node;
            toolSeg.append(node);
        }
        buttons.brush.classList.add("is-active");
        const toggle = button("Paint", () => {
            painting = !painting;
            toggle.classList.toggle("is-active", painting);
            canvas.classList.toggle("is-idle", !painting);
            // Painting is done on the original: the strokes are applied to that file, so
            // the user should see the pixels they are covering.
            if (painting) image.src = viewUrl(refViewUrl(slot.file));
            updateNote();
        });
        toggle.dataset.paintToggle = "1";
        const size = element("input", {
            type: "range", min: "1", max: "30", value: String(radiusToSlider(radius)),
            className: "mmx-paint__radius",
        });
        size.dataset.paintRadius = "1";
        size.title = "Brush size";
        size.addEventListener("input", () => {
            radius = sliderToRadius(size.value);
        });
        const undo = button("Undo", () => {
            strokes().pop();
            persist();
            redraw();
            updateNote();
        });
        undo.dataset.paintUndo = "1";
        const clearArea = button("Clear areas", () => {
            slot.blurPaint = [];
            persist();
            redraw();
            updateNote();
        });
        clearArea.dataset.paintClear = "1";
        const apply = button("Apply", async () => {
            note.textContent = "blurring the painted areas…";
            try {
                const answer = await hooks.blurReference?.({
                    file: slot.file,
                    scope: blurScope(state),
                    slot: slotNumber,
                });
                if (answer?.ok && answer.url) {
                    image.src = viewUrl(answer.url);
                    note.textContent = `${answer.reason}. This is the copy the render wires.`;
                    renderReferences();
                } else {
                    note.textContent = `Nothing blurred: ${answer?.reason || "face blur unavailable"}`;
                }
            } catch (error) {
                note.textContent = `Nothing blurred: ${error.message}`;
            }
        });
        apply.dataset.paintApply = "1";
        toolbar.append(
            toggle, toolSeg, size, undo, clearArea, apply,
            element("span", { className: "mmx-spacer" }), note,
        );
        updateNote();
        return { frame, toolbar, redraw };
    }

    /** Draw one stroke on the overlay canvas (translucent, so the photo stays readable). */
    function drawPaintedStroke(ctx, stroke, width, height) {
        const points = paintPath(stroke, width, height);
        if (!points.length) return;
        const radius = Math.max(2, (Number(stroke.radius) || DEFAULT_PAINT_RADIUS) * Math.min(width, height));
        ctx.save();
        ctx.fillStyle = "rgba(255,64,96,.32)";
        ctx.strokeStyle = "rgba(255,64,96,.9)";
        ctx.lineWidth = 1.5;
        if (String(stroke.tool) === "lasso" && points.length >= 3) {
            ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            for (const [x, y] of points.slice(1)) ctx.lineTo(x, y);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
        } else {
            ctx.lineWidth = Math.max(2, radius * 2);
            ctx.lineCap = "round";
            ctx.lineJoin = "round";
            ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            for (const [x, y] of points.slice(1)) ctx.lineTo(x, y);
            if (points.length === 1) ctx.lineTo(points[0][0] + 0.01, points[0][1]);
            ctx.stroke();
        }
        ctx.restore();
    }

    // The picker's own state: which source, which kind, the query, the folder it is looking at, and
    // whether it is looking at the whole tree. Both extras exist because the whole-tree listing is
    // a filesystem walk: with the folder mode on (the default) opening the picker is one directory
    // read, and "all folders" is the deliberate choice that pays for the walk (which the backend
    // then caches, so it is only paid once per folder).
    const browseState = { source: "inputs", kind: "all", query: "", folder: "", recursive: false };

    /** `index` = the slot being filled, or null for "first free slot".
     *  ``group`` null = the unified picker: every kind, each file routed by type. */
    function openBrowse(group, index) {
        browseState.kind = group ? group.kind : "all";
        browseState.query = "";
        renderBrowse(group, index);
    }

    function renderBrowse(group, index, { attempt = 0 } = {}) {
        const pane = openOverlay("mmx-browse");
        container.dataset.browseFor = `${group ? group.key : "media"}:${index ?? "auto"}`;

        const head = element("div", { className: "mmx-overlay__head" });
        const sourceSeg = element("div", { className: "mmx-seg" });
        for (const [key, label] of [["inputs", "Inputs"], ["outputs", "Outputs"]]) {
            const seg = button(label, () => {
                browseState.source = key;
                browseState.folder = "";
                renderBrowse(group, index);
            });
            if (browseState.source === key) seg.classList.add("is-active");
            sourceSeg.append(seg);
        }
        const kindSelect = selectBox(
            [["all", "All media"], ["image", "Images"], ["video", "Videos"], ["audio", "Audios"]],
            browseState.kind,
            (value) => {
                browseState.kind = value;
                renderBrowse(group, index);
            },
        );
        kindSelect.dataset.mmxBrowseKind = "1";
        const search = textInput(browseState.query, "search…", () => {}, "mmx-input");
        search.style.minWidth = "120px";
        search.dataset.mmxBrowseSearch = "1";
        let searchTimer = null;
        search.addEventListener("input", () => {
            browseState.query = search.value;
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => renderBrowse(group, index), 250);
        });
        const everyFolder = button(
            browseState.recursive ? "all folders · newest first" : "this folder",
            () => {
                browseState.recursive = !browseState.recursive;
                renderBrowse(group, index);
            },
        );
        everyFolder.classList.add("mmx-chip");
        everyFolder.dataset.action = "browse-mode";
        everyFolder.classList.toggle("is-on", browseState.recursive);
        everyFolder.title = browseState.recursive
            ? "Every file under this folder, newest first. Click to go back to the folder you are in "
                + "(one directory read instead of a walk of the whole tree)."
            : "Only the folder you are in, plus its subfolders to click into. Click for every file "
                + "under this folder, newest first.";
        head.append(
            element("span", {
                textContent: group ? `Choose ${group.label.toLowerCase()}` : "Choose media - pictures, video or audio",
                className: "mmx-title",
            }),
            sourceSeg,
            kindSelect,
            search,
            element("span", { className: "mmx-spacer" }),
            everyFolder,
            button("Upload from disk", () => pickFiles(group, index)),
            button("Close", closeOverlay),
        );

        const body = element("div", { className: "mmx-overlay__body" });
        const trail = element("div", { className: "mmx-browse__trail" });
        const grid = element("div", { className: "mmx-pickgrid" });
        const foot = element("div", { className: "mmx-muted" });
        foot.textContent = "Loading…";
        body.append(trail, grid);
        pane.append(head, body, foot);

        Promise.resolve(hooks.listMedia?.({ ...browseState }))
            .then((payload) => {
                if (!payload || payload.ok === false) {
                    foot.textContent = payload?.error || "Could not list that folder.";
                    return;
                }
                const items = payload.items || [];
                const folders = payload.folders || [];
                // Where we are, and the way back up: with folder mode the picker is a browser, so it
                // has to say which folder it is showing rather than leaving it to the file names.
                trail.replaceChildren();
                if (!browseState.recursive) {
                    const where = `${payload.source === "outputs" ? "output" : "input"}`
                        + (payload.subfolder ? `/${payload.subfolder}` : "");
                    if (payload.parent !== null && payload.parent !== undefined) {
                        const up = button("↑ up", () => {
                            browseState.folder = String(payload.parent || "");
                            renderBrowse(group, index);
                        });
                        up.classList.add("mmx-chip");
                        up.dataset.action = "browse-up";
                        trail.append(up);
                    }
                    trail.append(element("span", { textContent: where, className: "mmx-title" }));
                    for (const folder of folders) {
                        const chip = button(folder.name, () => {
                            browseState.folder = String(folder.path || "");
                            renderBrowse(group, index);
                        });
                        chip.classList.add("mmx-chip");
                        chip.dataset.action = "browse-folder";
                        chip.dataset.folder = String(folder.path || "");
                        chip.title = `Open ${folder.path}`;
                        trail.append(chip);
                    }
                    if (!folders.length && !items.length) {
                        trail.append(element("span", { textContent: "no subfolders", className: "mmx-muted" }));
                    }
                }
                grid.replaceChildren();
                for (const item of items) {
                    const card = element("button", { type: "button", className: "mmx-pick", title: item.path });
                    if (item.kind === "image") {
                        card.append(element("img", { src: viewUrl(item.url), alt: item.name, loading: "lazy" }));
                    } else {
                        card.append(element("div", { className: "mmx-tile__note" }, {}, [
                            icon(item.kind, { size: 22 }),
                            element("span", { textContent: item.kind, className: "mmx-muted" }),
                        ]));
                    }
                    // Which kind this is, so one picker can serve all three.
                    const chip = element("span", {
                        className: `mmx-tile__kind mmx-tile__kind--${item.kind}`,
                    }, { position: "absolute", top: "4px", left: "4px" });
                    chip.append(icon(item.kind, { size: 12 }));
                    card.style.position = "relative";
                    card.append(chip, element("span", { textContent: item.name }));
                    card.addEventListener("click", () => {
                        closeOverlay();
                        assignPath(group, index, item.path);
                    });
                    grid.append(card);
                }
                const where = browseState.recursive
                    ? `newest first across all of ${payload.source === "outputs" ? "output" : "input"}`
                    : `in ${payload.source === "outputs" ? "output" : "input"}${payload.subfolder ? `/${payload.subfolder}` : ""}`;
                const counted = items.length
                    ? `${items.length} file(s) ${where}${payload.truncated ? " — newest only" : ""}`
                    : (folders.length && !browseState.recursive
                        ? `no files here — ${folders.length} folder(s) to open`
                        : `Nothing here yet${browseState.query ? " matching " + JSON.stringify(browseState.query) : ""} — drop files on a tile, or use “Upload from disk”.`);
                foot.textContent = payload.partial
                    ? `${counted} · still reading this folder…`
                    : counted;
                // A capped scan hands back what it has and finishes in the background. One retry (a
                // couple of times, spaced out) is the most this should ever need: the second answer
                // comes from the cache.
                if (payload.partial && attempt < 3) {
                    setTimeout(() => {
                        if (overlay && overlay.dataset.overlay === "mmx-browse") {
                            renderBrowse(group, index, { attempt: attempt + 1 });
                        }
                    }, 1200);
                } else if (!payload.partial && payload.stale) {
                    // A stale answer was served while the real one was computed: say so quietly.
                    foot.textContent = `${counted} · refreshing…`;
                }
            })
            .catch((error) => {
                foot.textContent = `Could not list media: ${error.message}`;
            });

        if (browseState.query) {
            search.value = browseState.query;
            search.focus();
        }
    }

    // -------------------------------------------------------------- cells
    function renderCells() {
        cellsHost.replaceChildren();
        // B's stage belongs to this view: "what to draw" is answered by the sheet itself, so the
        // sheet fills the top of the pane and the vocabulary that fills it scrolls underneath.
        // (`.mmx-pane--fills` is what turns the pane into this two-row column; other tabs keep
        // the plain scrolling pane.)
        cellsHost.classList.add("mmx-pane--fills");
        const scroll = element("div", { className: "mmx-pane__scroll" });
        // B's line under the sheet: while a render runs it carries the live facts (which cell,
        // which step, how long the loop is); when nothing is streaming it says what the picture
        // is. It is the stage's own caption rather than a row of the filmstrip, so reading the
        // stage never means looking somewhere else.
        const caption = element("div", { className: "mmx-stage__caption" });
        caption.dataset.mmStageCaption = "1";
        const captionLive = element("span", { className: "mmx-stage__caption__live" });
        const captionHint = element("span", {
            className: "mmx-muted",
            textContent: "the sheet appears here as it denoises",
        });
        caption.append(captionLive, captionHint);
        cellsHost.append(sheetPreview(), caption, scroll);
        // The caption survives a rebuild: a refresh while a render runs must not lose the facts.
        syncStageCaption();
        const builder = element("div", { className: "mmx-card" });
        const planNote = element("div", { className: "mmx-muted" }, { marginTop: "2px" });
        const ticks = () => ({
            views: readChecks(views.boxes, []),
            poses: readChecks(poses.boxes, []),
            expressions: readChecks(expressions.boxes, []),
        });
        const plannedCells = () => {
            const picked = ticks();
            return buildCells(picked.views, picked.poses, picked.expressions);
        };
        function updatePlanNote() {
            const planned = plannedCells();
            if (planned.length) {
                // The count on screen, the list on hover: twenty cell ids in a row is a paragraph,
                // and the cells themselves are drawn as glyphs right above this line.
                planNote.textContent = `${planned.length} cell(s) from the ticks`;
                planNote.title = planned.map((cell) => cell.id).join(", ");
                return;
            }
            planNote.textContent = "No views ticked - an empty cell list renders the default 8-view "
                + "matrix.";
            planNote.title = "The node falls back to DEFAULT_MATRIX when the payload carries no "
                + "cells: a standard 8-view sheet (face, front, back, sides and two angles).";
        }
        // The ticks are part of the payload: if the cell list is ever empty (a panel
        // that reloaded without one) the node renders exactly what is ticked here.
        const syncBuild = () => {
            // The ticks ARE the sheet's panel list: changing them rebuilds it, keeping the panels
            // the user edited by hand (a dropped framing/pose/expression, or a panel that names its
            // own face reference). The list used to be materialised once - by a drop, by "Use these
            // cells", or by a saved workflow - and then ignored the ticks for ever: unticking
            // "back" left that panel on the stage, and ticking "back of head" never showed up.
            const edits = collectCellEdits();
            state.build = ticks();
            state.cells = plannedCellsFromTicks()
                .map((cell) => ({ ...cell, ...(edits[cell.id] || {}) }));
            persist();
            updatePlanNote();
            refresh();
        };
        const views = glyphRow("Framings", VIEWS, new Set(state.build.views), syncBuild, "views",
            VIEW_MARKS);
        const poses = optionRow("Poses", POSES, new Set(state.build.poses), syncBuild, "poses");
        const expressions = glyphRow("Expressions", EXPRESSIONS, new Set(state.build.expressions),
            syncBuild, "expressions", EXPRESSION_MARKS);
        const background = backgroundRow();
        const order = mutedHint(
            "Cells render top to bottom - Results fills in that order.",
            "A cell is one render: the sheet is composited from the picked frame of each, in this order.",
        );
        const shape = mutedHint(
            "Cell shape: 3:4 by default, overridable per cell.",
            "Cell shape comes from the node's cell_aspect (default 3:4, where cell_size is its SHORT "
            + "edge). A cell can override it with its own aspect.",
        );
        // Latent continuation: each cell is its own clip, so this is the one setting
        // that couples them. Off by default - independent poses are what a sheet is for.
        const continuityRow = element("div", { className: "mmx-row" }, { marginTop: "4px" });        const continuitySelect = selectBox(
            CONTINUITY_LABELS,
            continuity(state),
            (value) => {
                state.continuity = value;
                persist();
                refresh();
            },
        );
        continuitySelect.dataset.action = "continuity";
        continuitySelect.title =
            "Latent continuation: anchor the last " + CONTINUITY_FRAMES + " frames of the "
            + "previous cell at the start of the next one, so a run of cells continues "
            + "instead of restarting. Those frames of each cell re-render the previous "
            + "tail, and the picked frame stays after them. 'Auto' only chains cells that "
            + "share a camera distance (full body -> full body), which is how a turnaround "
            + "animates its turn - and it needs a reference that shows the body (an "
            + "outfit/body role), or the hand-over's angle wins and the report warns. "
            + "Per cell override below.";
        continuityRow.append(
            element("span", { textContent: "Latent continuation", className: "mmx-muted" },
                { flex: "0 0 96px" }),
            continuitySelect,
            element("span", {
                textContent: "auto = continue only where the framing already matches (a "
                    + "running full-body turn); on = always continue, even across a "
                    + "framing change (the clip keeps the previous camera distance: a "
                    + "full body after a chest-up lands mid-zoom). Off = every cell from "
                    + "its own noise.",
                className: "mmx-muted",
            }),
        );
        // Every cell is also written as a video (frames + its own audio). On by default:
        // the clip is what a finished edit cuts with, and it costs one encode per cell.
        const exportRow = element("div", { className: "mmx-row" }, { marginTop: "4px" });
        const exportBox = element("input", {
            type: "checkbox",
            checked: exportVideo(state),
        });
        exportBox.dataset.action = "export-video";
        exportBox.title =
            "Write each cell's rendered clip next to its frames "
            + "(clips/<cell>_0000N_.mp4 in the sheet folder, 24 fps with the audio H3 made "
            + "with those frames). The Results tab then offers a clip link per cell.";
        exportBox.addEventListener("change", () => {
            state.exportVideo = exportBox.checked;
            persist();
            notify(exportBox.checked ? "cell clips will be exported" : "cell clips off - the sheet keeps frames only");
        });
        exportRow.append(
            exportBox,
            element("label", { textContent: "Export each cell's clip (mp4 with audio)" },
                { fontSize: "10px" }),
            element("span", {
                textContent: "frames + the audio H3 generated, 24 fps, in the sheet folder under clips/. "
                    + "The sheet composite is unchanged; this is the take each cell was picked from.",
                className: "mmx-muted",
            }),
        );
        const actions = element("div", { className: "mmx-row" }, { marginTop: "4px" });
        // "Build cells" is the step that actually creates the render, so it is the one button
        // that carries a visible (yellow-orange) outline instead of the quiet default.
        const buildButton = button("Build cells", () => {
            state.cells = plannedCells();
            state.build = ticks();
            persist();
            refresh();
            notify(`${state.cells.length} cell(s) built.`);
        });
        buildButton.classList.add("mmx-btn--build");
        buildButton.title = "Create the cells from the ticks above, then Queue the prompt.";
        actions.append(
            buildButton,
            button("Clear cells", () => {
                state.cells = [];
                persist();
                refresh();
            }),
        );
        builder.append(views.row, poses.row, expressions.row, background, planNote, order, shape, continuityRow, exportRow, actions);
        scroll.append(builder);
        updatePlanNote();

        if (!state.cells.length) {
            const note = element("div", { className: "mmx-card" });
            const planned = plannedCells();
            note.append(
                element("div", {
                    textContent: planned.length
                        ? `No cell list stored, so the node will render the ${planned.length} cell(s) `
                            + "your ticks ask for. Materialise them to edit each cell."
                        : "No cell list and no views ticked, so the node will render the default 8-view "
                            + "matrix (face, face+smile, portrait, front, A-pose, T-pose, profile, back).",
                    className: "mmx-muted",
                }),
                element("div", { className: "mmx-row" }, { marginTop: "4px" }, [
                    button(planned.length ? `Use these ${planned.length} cells` : "Use the default 8 cells", () => {
                        state.cells = planned.length ? planned : defaultCells();
                        state.build = ticks();
                        persist();
                        refresh();
                        notify(`${state.cells.length} cell(s) in the list - edit or reorder them below.`);
                    }),
                ]),
            );
            scroll.append(note);
            scroll.append(element("div", {
                textContent: "Or tick views (and poses / expressions) above and press Build cells.",
                className: "mmx-muted",
            }));
            return;
        }

        const list = element("div", { className: "mmx-card" });
        state.cells.forEach((cell, index) => {
            const card = element("div", { className: "mmx-cell mmx-sheet-cell" });
            const enabled = element("input", { type: "checkbox", checked: cell.enabled !== false });
            enabled.title = "Render this cell";
            enabled.addEventListener("change", () => {
                cell.enabled = enabled.checked;
                persist();
            });
            const label = element("span", { textContent: `${index + 1}. ${cell.id}` }, {
                fontSize: "10px", flex: "0 0 96px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            });
            label.title = cell.id;

            const frames = element("input", {
                type: "number", value: cell.frames ?? "", min: "5", max: "425", step: "1",
                placeholder: "frames", className: "mmx-input",
            }, { width: "62px" });
            frames.title = "Frames sampled for this cell (empty = the node's frames_per_cell)";
            frames.addEventListener("change", () => {
                if (frames.value === "") delete cell.frames;
                else cell.frames = Number(frames.value);
                persist();
            });
            const seed = element("input", {
                type: "number", value: cell.seed ?? "", min: "0", step: "1",
                placeholder: "seed", className: "mmx-input",
            }, { width: "74px" });
            seed.title = "Empty = the node seed plus a per-cell offset";
            seed.addEventListener("change", () => {
                if (seed.value === "") delete cell.seed;
                else cell.seed = Number(seed.value);
                persist();
            });
            const extra = textInput(cell.extraPrompt || "", "extra prompt for this cell", (value) => {
                cell.extraPrompt = value;
                persist();
            }, "mmx-input mmx-sheet-cell-extra");
            extra.style.flex = "1 1 140px";
            extra.style.minWidth = "120px";

            const move = (delta) => button(delta < 0 ? "↑" : "↓", () => {
                const target = index + delta;
                if (target < 0 || target >= state.cells.length) return;
                [state.cells[index], state.cells[target]] = [state.cells[target], state.cells[index]];
                persist();
                refresh();
            });
            const remove = iconButton("remove", "Remove this cell", () => {
                state.cells.splice(index, 1);
                persist();
                refresh();
            }, "mmx-btn--danger");
            const continuityBadge = selectBox(
                CELL_CONTINUITY_LABELS,
                cellContinuity(cell),
                (value) => {
                    if (value === "inherit") delete cell.continuity;
                    else cell.continuity = value;
                    persist();
                    refresh();
                },
            );
            continuityBadge.title =
                "Latent continuation for this cell: inherit / auto (only where the camera "
                + "distance matches) / continue from the previous cell / render on its own "
                + "(beats the sheet switch either way)";
            continuityBadge.dataset.cellContinuity = cell.id;
            // The first cell has nothing before it, so continuing it is meaningless.
            if (index === 0) {
                continuityBadge.disabled = true;
                continuityBadge.title = "The first cell has no previous cell to continue from";
            }
            card.append(
                enabled, label,
                selectBox(VIEWS, cell.view || "front", (value) => { cell.view = value; persist(); }),
                selectBox(POSES, cell.pose || "neutral", (value) => { cell.pose = value; persist(); }),
                selectBox(EXPRESSIONS, cell.expression || "neutral", (value) => { cell.expression = value; persist(); }),
                selectBox(PICKS.map((key) => [key, PICK_LABELS[key] || key]), cell.pick || "auto", (value) => { cell.pick = value; persist(); }),
                frames, seed, continuityBadge, extra, move(-1), move(1), remove,
            );
            // Filled by refreshPlan(): the references this cell is actually wired with.
            const refsNote = element("div", { className: "mmx-cell__refs" });
            refsNote.dataset.cellRefs = cell.id;
            card.append(refsNote);
            // A silent marker for a continuing cell, so a chained run is visible without
            // opening the prompt preview: the backend resolves the real value.
            if (cellContinues(state, index)) {
                const badge = element("span", {
                    textContent: `↳ continues the cell before it (${CONTINUITY_FRAMES}f hand-over)`,
                    className: "mmx-muted",
                }, { fontSize: "10px" });
                badge.dataset.cellContinuityNote = cell.id;
                card.append(badge);
            } else if (index > 0 && framingBreak(state, index)) {
                // Auto held this cell back on purpose: say so, or it reads as a bug.
                const note = element("span", {
                    textContent: "↳ framing change - renders on its own (cont: auto)",
                    className: "mmx-muted",
                }, { fontSize: "10px" });
                note.dataset.cellFramingNote = cell.id;
                card.append(note);
            }
            list.append(card);
        });
        scroll.append(list);
    }

    // ----------------------------------------------------------- prompt preview
    // The final prompt is written by the pack's planner, not by this panel, so the
    // panel asks the backend (action "plan") instead of pretending to know: what you
    // read here is exactly what the render sends, including which references that
    // cell is wired with.
    let planCells = [];

    /** Every reference the RUN sends, as H3 tags (``<Picture 1>`` and friends). */
    function runRefTags() {
        return (mediaSlots(state.refs) || [])
            .filter((entry) => entry.active !== false)
            .map((entry) => refTagLabel(entry.group.kind, entry.ordinal));
    }

    function renderPlan(payload) {
        planCells = Array.isArray(payload?.cells) ? payload.cells : [];
        const full = runRefTags().join(", ");
        for (const note of container.querySelectorAll("[data-cell-refs]")) {
            const cell = planCells.find((item) => item.id === note.dataset.cellRefs);
            const tags = cell ? (cell.refs || []).join(", ") : "";
            note.textContent = cell && tags && tags !== full ? `conditioned on ${tags} only` : "";
        }

        promptsHost.replaceChildren();
        const head = element("div", { className: "mmx-row" }, { marginBottom: "4px" });
        head.append(
            element("span", {
                textContent: `Final prompt per cell - exactly what the render sends (${planCells.length} cell(s)).`,
                className: "mmx-muted",
            }),
            element("span", { className: "mmx-spacer" }),
            button("Refresh", () => refreshPlan()),
        );
        promptsHost.append(head);
        if (!planCells.length) {
            promptsHost.append(element("div", {
                textContent: "No cells yet - tick views and press Build cells, then Refresh.",
                className: "mmx-muted",
            }));
        }
        for (const [index, cell] of planCells.entries()) {
            const block = element("div", { className: "mmx-prompt" });
            const blurred = Array.isArray(cell.blurred) ? cell.blurred : [];
            const blurredMarks = blurred.length ? ` · face blurred: ${blurred.join(", ")}` : "";
            // Frames handed over from the previous cell, as the backend resolved them.
            const guide = Number(cell.continuity || 0) || 0;
            const marks = guide ? ` · continues ${guide}f from the cell above` : "";
            block.append(element("div", {
                textContent: `${index + 1}. ${cell.id} · references: ${(cell.refs || []).join(", ") || "none"}${blurredMarks}${marks}`,
                className: "mmx-muted",
            }));
            block.append(element("pre", { textContent: cell.prompt || "" }));
            promptsHost.append(block);
        }
        hooks.layoutChanged?.();
    }

    async function refreshPlan() {
        try {
            const payload = await hooks.planCells?.();
            renderPlan(payload);
        } catch (error) {
            notify(`prompt preview unavailable: ${error.message}`);
        }
    }

    // ------------------------------------------------------------ results
    let lastSheet = null;
    // What the pane is showing right now, so a pick or a rebuild can update it in place.
    const resultRows = new Map();    // cell id -> {row, pickSpan, thumbs: Map(index -> img)}
    let resultSignature = "";
    let resultHead = null;           // {image, link, counts}
    let resultBumps = 0;

    /** The "picked frame N (mode)" sentence - and honest about a hand-picked frame. */
    function pickText(cell) {
        const mode = String(cell?.pickMode || "auto");
        return `picked frame ${cell?.pickIndex ?? "-"} (${PICK_LABELS[mode] || mode})`;
    }

    /** Mark exactly one thumbnail in a row as the picked one. */
    function markThumb(thumb, picked) {
        thumb.style.border = picked
            ? "2px solid var(--mmx-accent)"
            : "1px solid var(--mmx-line)";
    }

    /** A URL the browser cannot answer from its cache (a rebuild inside the same second). */
    function cacheBust(url) {
        if (!url) return url;
        resultBumps += 1;
        return `${url}${url.includes("?") ? "&" : "?"}_r=${resultBumps}`;
    }

    function countsText(shown) {
        return `${shown?.counts?.rendered ?? 0}/${shown?.counts?.cells ?? 0} cell(s) rendered · `
            + `${shown?.counts?.frames ?? 0} frame(s) on disk · ${shown?.dir || ""}`;
    }

    /** The sheet itself and the counts line: what a rebuild changes without moving a row. */
    function updateSheetHead(shown) {
        if (!resultHead) return;
        if (resultHead.image && shown.sheetUrl) {
            resultHead.image.src = cacheBust(viewUrl(shown.sheetUrl));
            resultHead.image.title = `${shown.sheetFile || "sheet"} - click to open it full size`;
        }
        if (resultHead.link && shown.sheetUrl) resultHead.link.href = viewUrl(shown.sheetUrl);
        if (resultHead.counts) resultHead.counts.textContent = countsText(shown);
    }

    /** One row's pick label and border - the only things a pick changes. */
    function applyPickToRow(cell) {
        const parts = resultRows.get(cell?.id);
        if (!parts) return;
        parts.pickSpan.textContent = pickText(cell);
        for (const [index, thumb] of parts.thumbs) markThumb(thumb, index === cell.pickIndex);
    }
    /**
     * Which sheet of a suite run the panel is working on.
     *
     * A suite renders several sheets under ONE run name, one folder per board, so every call that
     * touches a folder has to say which board it means: the run folder holds no cells of its own.
     * Empty means "whatever this run is", which the backend answers with the run's first board -
     * so a normal single-sheet run is unaffected by the whole idea.
     */
    function boardName() {
        return String(state.suiteBoard || "").trim();
    }

    // The board row's own handles, so its chips and its follow switch can be re-read without
    // rebuilding the Results pane (see syncBoardRow).
    let boardRowNode = null;
    let boardRowChoices = [];
    let followNode = null;

    /** The board row: which sheet of a run the Results tab is showing (null for a plain sheet). */
    function boardRow(shown) {
        const boards = Array.isArray(shown?.boards) ? shown.boards : [];
        boardRowNode = null;
        boardRowChoices = [];
        followNode = null;
        if (!boards.length) return null;
        const current = String(shown?.board || boardName() || boards[0].folder || "");
        const row = chipChoice(
            "Board",
            boards.map((entry) => [String(entry.folder || entry.id || ""),
                String(entry.label || entry.id || "")]),
            current,
            (key) => selectBoard(key),
            boards.length === 1 ? "one sheet in this run" : `${boards.length} sheets from one queue`,
        );
        row.dataset.action = "suite-boards";
        for (const chip of row.querySelectorAll(".mmx-chip[data-choice]")) {
            const entry = boards.find((item) => String(item.folder || item.id) === chip.dataset.choice) || {};
            const bits = [];
            if (entry.cells) bits.push(`${entry.cells} cell(s)`);
            if (entry.layout) bits.push(`${entry.layout} layout`);
            bits.push(entry.rendered ? "rendered" : "not rendered yet");
            chip.title = `${entry.label || entry.id}: ${bits.join(" · ")}`;
        }
        if (boards.length > 1) {
            followNode = followSwitch();
            row.append(followNode);
        }
        boardRowNode = row;
        boardRowChoices = boards;
        syncBoardRow();
        return row;
    }

    /**
     * Re-light the board row's chips and re-read the follow switch.
     *
     * The row is otherwise only rebuilt when the LISTING changes (a light refresh keeps the
     * thumbnails and just repaints what moved), so a board switch - by a click or by the render
     * moving on - would leave the old chip lit and the switch saying the opposite of what it does.
     */
    function syncBoardRow() {
        if (!boardRowNode) return;
        const current = String(boardName() || lastSheet?.board
            || boardRowChoices[0]?.folder || boardRowChoices[0]?.id || "");
        for (const chip of boardRowNode.querySelectorAll(".mmx-chip[data-choice]")) {
            const on = String(chip.dataset.choice) === current;
            chip.classList.toggle("is-on", on);
            chip.setAttribute("aria-pressed", on ? "true" : "false");
        }
        if (followNode) {
            const on = followBoard(state);
            followNode.textContent = on ? "following the render" : "follow off";
            followNode.classList.toggle("is-on", on);
            followNode.setAttribute("aria-pressed", on ? "true" : "false");
            followNode.title = followTitle(on);
        }
    }

    function followTitle(on) {
        return on
            ? "The board row follows whichever board this suite is drawing. Click to stop following."
            : "The board row stays on the sheet you picked. Click to follow the render again.";
    }

    /**
     * The little switch that says whether the Results tab follows the render.
     *
     * It is on the row rather than buried in Settings because it is only ever a question while a
     * suite is drawing - and because a chip click turns it off, the user needs to see that it did.
     */
    function followSwitch() {
        const on = followBoard(state);
        const chip = button(on ? "following the render" : "follow off", () => {
            state.followBoard = !followBoard(state);
            persist();
            notify(followBoard(state)
                ? "following the render again - the board row will switch by itself"
                : "not following the render - the board row stays where you put it");
            syncBoardRow();
            refreshResults();
        });
        chip.classList.add("mmx-chip");
        chip.classList.add("mmx-chip--follow");
        chip.classList.toggle("is-on", on);
        chip.dataset.action = "suite-follow";
        chip.setAttribute("aria-pressed", on ? "true" : "false");
        chip.title = followTitle(on);
        return chip;
    }

    /**
     * Switch the Results tab to another sheet of the run.
     *
     * The choice is a view preference (it rides the payload's `ui` block, like the preview sizes),
     * and the listing is re-fetched because the board decides which folder answers. Re-compose,
     * picks and Clear follow it for free: they read the same state.
     *
     * `auto` marks the switch the live stream asked for (see setLivePreview) - a deliberate click
     * is a decision, so it turns following off rather than being immediately overruled by the
     * next board the render moves on to.
     */
    function selectBoard(folder, { auto = false } = {}) {
        const next = String(folder || "");
        if (boardName() === next) return;
        state.suiteBoard = next;
        if (!auto && followBoard(state)) state.followBoard = false;
        persist();
        // The row re-lights HERE rather than when the listing comes back: the fetch is a round trip,
        // and the tab should show which sheet it is about to draw immediately.
        syncBoardRow();
        notify(auto ? `results: following the render - ${next || "the sheet"}`
            : `results: ${next || "the sheet"}`);
        refreshResults();
    }

    function renderResults(sheet, { light = false } = {}) {
        if (sheet !== undefined) lastSheet = sheet;
        const shown = lastSheet;
        if (!shown || !Array.isArray(shown.cells) || !shown.cells.length) {
            // Nothing to show. Always repainted, light or not: this is the state Clear sheet
            // leaves behind, and a stale list of thumbnails would be worse than a redraw.
            results.replaceChildren();
            resultRows.clear();
            resultSignature = "";
            resultHead = null;
            const emptyBoards = boardRow(shown);
            if (emptyBoards) results.append(emptyBoards);
            results.append(element("div", {
                textContent: shown?.boards?.length
                    ? "This board has not rendered yet — Render, then Refresh."
                    : "Nothing rendered yet — queue the prompt to render the cells.",
                className: "mmx-muted",
            }));
            refreshTabs();
            return;
        }
        const signature = `${shown.sheetFile || ""}#`
            + shown.cells.map((cell) => `${cell.id}:${cell.frameCount}`).join("|");
        if (light && resultHead && signature === resultSignature) {
            // Same cells, same frames on disk: a pick or a rebuild only moves one border, one
            // label and the sheet image. Rebuilding the pane instead re-created every thumbnail
            // (hundreds of <img> nodes), re-fetched them all and threw away the scroll position.
            updateSheetHead(shown);
            for (const cell of shown.cells) applyPickToRow(cell);
            refreshTabs();
            return;
        }
        results.replaceChildren();
        resultRows.clear();
        resultSignature = signature;
        resultHead = null;
        const boardsRow = boardRow(shown);
        if (boardsRow) results.append(boardsRow);
        if (shown.sheetUrl) {
            const size = panelPreview(state);
            const height = PANEL_PREVIEW_HEIGHTS[size] || 0;
            if (size !== "off") {
                // The sheet is the biggest thing on this tab, and it is what the run is FOR - so it
                // gets the same card treatment the reference canvas has: a head that names the file
                // and offers the full-size view, then the sheet itself, then a filmstrip of the
                // frames the sheet is made of (one per cell, in cell order).
                const card = element("div", { className: "mmx-canvas mmx-canvas--sheet" });
                card.dataset.action = "sheet-canvas";
                const head = element("div", { className: "mmx-canvas__head" });
                const open = element("a", {
                    textContent: "Open", href: viewUrl(shown.sheetUrl), target: "_blank",
                    rel: "noreferrer", className: "mmx-btn mmx-btn--quiet",
                }, { textDecoration: "none" });
                open.title = "Open the sheet file at full size in a new tab";
                head.append(
                    element("span", { textContent: "Sheet", className: "mmx-title" }),
                    element("span", {
                        textContent: String(shown.sheetFile || "").split("/").pop(),
                        className: "mmx-muted",
                        title: shown.sheetFile || "",
                    }),
                    element("span", { className: "mmx-spacer" }),
                    open,
                );
                const image = element("img", {
                    src: viewUrl(shown.sheetUrl),
                    className: "mmx-sheet-preview",
                    title: `${shown.sheetFile || "sheet"} - click to open it full size`,
                }, height
                    ? { maxHeight: `${height}px`, width: "auto", maxWidth: "100%" }
                    : { width: "100%", height: "auto" });
                const link = element("a", {
                    href: viewUrl(shown.sheetUrl), target: "_blank", rel: "noreferrer",
                }, { display: "block" });
                link.append(image);
                card.append(head, link);
                resultHead = { image, link, counts: null, card };
                // The newest cell clip, playable in place: with `panel` preview mode this is the
                // only preview the node has, and a <video> beats a link you have to leave for.
                const withClip = (shown.cells || []).find((cell) => cell.clipUrl);
                if (withClip && size !== "small") {
                    const video = element("video", {
                        src: viewUrl(withClip.clipUrl),
                        controls: true, loop: true, muted: true, playsInline: true,
                        className: "mmx-clip-preview",
                        title: `${withClip.id} - the clip this cell rendered (${withClip.clipFile || ""})`,
                    }, height
                        ? { maxHeight: `${height}px`, maxWidth: "100%", marginBottom: "4px" }
                        : { width: "100%", maxWidth: "100%", marginBottom: "4px" });
                    card.append(video);
                }
                // The filmstrip: the picked frame of every cell, in cell order. It is the lineup of
                // what the sheet is built from, and clicking a frame jumps to that cell's row.
                const strip = element("div", { className: "mmx-film" });
                strip.dataset.action = "sheet-filmstrip";
                for (const cell of shown.cells) {
                    const frame = (cell.frames || [])[cell.pickIndex || 0] || (cell.frames || [])[0];
                    const url = frame?.url ? viewUrl(frame.url) : "";
                    const item = element("button", {
                        className: "mmx-film__item", type: "button",
                        title: `${cell.id} - frame ${cell.pickIndex ?? 0} of its clip; click to jump to its row`,
                    });
                    item.dataset.cell = cell.id;
                    if (url) {
                        item.append(element("img", { src: url, alt: cell.id }, {
                            width: "100%", height: "100%", objectFit: "cover",
                        }));
                    } else {
                        item.append(element("span", { textContent: cell.id, className: "mmx-muted" }));
                    }
                    item.append(element("span", { textContent: cell.id, className: "mmx-film__name" }));
                    item.addEventListener("click", () => {
                        const parts = resultRows.get(cell.id);
                        parts?.row?.scrollIntoView?.({ block: "center" });
                        if (parts?.row) {
                            parts.row.classList.add("is-flash");
                            setTimeout(() => parts.row.classList.remove("is-flash"), 900);
                        }
                    });
                    strip.append(item);
                }
                if (strip.children.length) card.append(strip);
                results.append(card);
            } else {
                results.append(element("div", {
                    textContent: `sheet: ${shown.sheetFile || shown.sheetUrl}`,
                    className: "mmx-muted",
                }, { marginBottom: "4px" }));
            }
        }
        const countsLine = element("div", {
            textContent: countsText(shown),
            className: "mmx-muted",
        }, { marginBottom: "4px" });
        results.append(countsLine);
        if (resultHead) resultHead.counts = countsLine;

        for (const cell of shown.cells) {
            const row = element("div", { className: "mmx-sheet-result-row" }, { marginBottom: "3px" });
            const caption = element("div", { className: "mmx-muted" });
            const pickSpan = element("span", {
                textContent: pickText(cell),
                title: "Which frame of this cell's clip the sheet uses. Click a thumbnail to decide it "
                    + "by hand - that choice stays until you pick a rule for this cell again.",
            });
            caption.append(
                element("span", {
                    textContent: `${cell.id} · ${cell.view || "?"}/${cell.pose || "?"}/${cell.expression || "?"} · `,
                }),
                pickSpan,
            );
            const parts = { row, pickSpan, thumbs: new Map() };
            resultRows.set(cell.id, parts);
            // The clip this cell generated (frames + its own audio). The sheet shows the
            // picked frame; this is the take it came from.
            const clipUrl = cell.clipUrl ? viewUrl(cell.clipUrl) : "";
            if (clipUrl) {
                const link = element("a", {
                    textContent: "\u25b6 clip",
                    href: clipUrl,
                    target: "_blank",
                    rel: "noreferrer",
                    className: "mmx-clip-link",
                }, { marginLeft: "6px" });
                link.dataset.cellClip = cell.id;
                link.title = `${cell.clipFile || "clip"} - the video this cell rendered, with its own audio`;
                caption.append(link);
            }
            // "This one is no good": render just this cell again with a new seed. The other
            // cells keep the frames already on disk, and the sheet is recomposed from them.
            const reroll = button("\u21bb new seed", () => retryCell(cell.id, reroll));
            reroll.classList.add("mmx-btn--quiet", "mmx-cell__retry");
            reroll.dataset.cellRetry = cell.id;
            reroll.title = `Render ${cell.id} again with a new seed (only this cell)`;
            caption.append(reroll);
            row.append(caption);
            const strip = element("div", {}, { display: "flex", gap: "2px", flexWrap: "wrap" });
            (cell.frames || []).forEach((frame, index) => {
                const url = viewUrl(frame.url);
                if (!url) {
                    // No usable /view URL (the sheet lives outside ComfyUI's output
                    // directory): a tile that says so beats a broken-image icon.
                    strip.append(element("div", {
                        className: "mmx-muted",
                        textContent: `${index}`,
                        title: frame.file || "frame",
                    }, { width: "54px", height: "54px", borderRadius: "4px", border: "1px dashed var(--mmx-line)",
                        display: "flex", alignItems: "center", justifyContent: "center" }));
                    return;
                }
                const thumb = element("img", {
                    src: url,
                    title: `frame ${index} — click to use it`,
                }, {
                    width: "54px", height: "54px", objectFit: "cover", cursor: "pointer",
                    border: "1px solid var(--mmx-line)",
                    borderRadius: "4px",
                });
                parts.thumbs.set(index, thumb);
                markThumb(thumb, index === cell.pickIndex);
                thumb.addEventListener("error", () => {
                    // The file is gone or unreadable: say it instead of showing the
                    // browser's broken-image glyph.
                    const note = element("div", {
                        className: "mmx-muted",
                        textContent: "×",
                        title: `could not load ${frame.file || "frame"}`,
                    }, { width: "54px", height: "54px", borderRadius: "4px", border: "1px dashed var(--mmx-line)",
                        display: "flex", alignItems: "center", justifyContent: "center" });
                    thumb.replaceWith(note);
                });
                thumb.addEventListener("click", async () => {
                    // The composite happens on the server (compose + PNG), so mark the click NOW:
                    // waiting for the answer made a click look ignored for a second or more.
                    // The label is a promise the response then keeps or takes back.
                    const previousLabel = parts.pickSpan.textContent;
                    for (const [otherIndex, other] of parts.thumbs) markThumb(other, otherIndex === index);
                    parts.pickSpan.textContent = `picking frame ${index}…`;
                    notify(`picking ${cell.id} frame ${index}…`);
                    try {
                        const answer = await hooks.pickFrame?.(cell.id, index, boardName());
                        const listing = answer?.sheet || null;
                        // A click is a decision, so record it on the node's own payload as well:
                        // the store keeps the frame, the payload keeps the mode, and the next
                        // queue renders the sheet the panel is showing.
                        const stateCell = (state.cells || []).find((item) => item.id === cell.id);
                        if (stateCell) {
                            stateCell.pick = "manual";
                            persist();
                        }
                        // Only this row moves (plus the sheet image, which is served fresh).
                        if (listing) renderResults(listing, { light: true });
                        notify(`${cell.id} → frame ${index}`
                            + (listing?.sheetFile ? ` · sheet updated: ${listing.sheetFile}` : ""));
                    } catch (error) {
                        // Put the row back the way the server still sees it.
                        parts.pickSpan.textContent = previousLabel;
                        applyPickToRow(cell);
                        notify(`pick failed: ${error.message}`);
                    }
                });
                strip.append(thumb);
            });
            if (!(cell.frames || []).length) {
                strip.append(element("span", { textContent: "no frames", className: "mmx-muted" }));
            }
            row.append(strip);
            results.append(row);
        }
        refreshTabs();
    }

    async function refreshResults(sheet) {
        // Every refresh goes through the in-place path: the pane is only actually rebuilt when
        // the frames on disk changed (`renderResults` compares a signature). A poll while the
        // tab is idle, a tab switch or a rebuild therefore costs a text assignment and a border,
        // not a few hundred re-created <img> nodes - which is what made the tab flicker, jump
        // and re-fetch every thumbnail.
        if (sheet === undefined) {
            try {
                sheet = await hooks.listResults?.(boardName());
            } catch (error) {
                notify(`results unavailable: ${error.message}`);
                return lastSheet;
            }
            renderResults(sheet ?? null, { light: true });
        } else {
            renderResults(sheet, { light: true });
        }
        return lastSheet;
    }

    function refreshTabs() {
        const filled = countRendered(state.refs);
        const slots = REF_GROUPS.reduce((total, group) => total + group.slots, 0);
        setTabCount("references", `${filled}/${slots}`);
        setTabCount("cells", state.cells.length ? String(state.cells.length) : "");
        syncHeaderStatus();
        const rendered = lastSheet?.counts?.rendered;
        setTabCount("results", rendered === undefined ? "" : String(rendered));
        // The stack's size rides the LoRAs tab's tooltip, the way the reference count rides its
        // own: a stack left on a workflow is a thing a user should be able to see from the rail.
        const stack = loraStack(state);
        setTabCount("loras", stack.length ? String(stack.length) : "");
        // Anything that changes what the panel shows can change how tall it is.
        hooks.layoutChanged?.();
    }

    // ---------------------------------------------------------- live results
    // The per-cell saver writes each cell as it finishes, so while a render is
    // running the Results tab can fill in cell by cell - but somebody has to go and
    // look. The wiring tells us when a prompt starts and stops; we poll in between.
    let liveTimer = null;
    let liveSeen = 0;
    async function liveTick() {
        if (!liveTimer) return;
        const before = liveSeen;
        await refreshResults();
        const now = lastSheet?.counts?.rendered ?? 0;
        if (now > before) {
            liveSeen = now;
            const total = lastSheet?.counts?.cells ?? state.cells.length;
            notify(`${now}/${total} cell(s) on disk - still rendering.`);
            if (activeTab !== "results") setTabCount("results", now ? String(now) : "");
        }
    }

    /** Called by the node wiring: a prompt is running (or has finished). */
    function setRunning(running) {
        if (running && !liveTimer) {
            liveSeen = lastSheet?.counts?.rendered ?? 0;
            liveTimer = setInterval(() => { liveTick(); }, 4000);
            notify("rendering - results update as each cell finishes.");
        } else if (!running && liveTimer) {
            clearInterval(liveTimer);
            liveTimer = null;
            refreshResults().then(() => refreshTabs());
        }
        // The stream belongs to a run: it appears when one starts and goes when it ends (the
        // finished sheet takes over in Results). Starting the run opens the strip's space right
        // away - a row that appears mid-render would resize the node mid-render.
        if (running) openLiveStrip();
        else setLivePreview(null);
        setTabLive("preview", Boolean(running));
    }

    /** Open the strip for a run that is starting: space held, no clip yet. */
    function openLiveStrip() {
        if (panelPreview(state) === "off") return;
        stopLiveLoop();
        liveCount = 0;
        liveLast = null;
        liveFrames = [];
        liveIndex = 0;
        liveRetry.disabled = false;
        liveRetry.title = LIVE_RETRY_TITLE;
        liveFrame.removeAttribute("src");
        liveStrip.classList.add("is-waiting");
        liveMeta.textContent = "waiting for the first frame…";
        if (liveStrip.style.display === "none") {
            liveStrip.style.display = "flex";
            hooks.layoutChanged?.();
        }
    }

    /**
     * Re-roll the cell the strip is showing, through the node wiring.
     *
     * The cell comes from the stream itself (`cell_id`), so this always acts on the cell that is
     * actually on screen - not on whatever the payload thinks runs next.
     */
    async function retryLiveCell() {
        const cellId = String(liveLast?.cell_id || "");
        // A whole-sheet stream has no cell to re-roll (see setLivePreview): the button is
        // disabled for it, and this guard keeps that true even if a click slips through.
        if (liveLast?.whole_sheet === true) return;
        if (!cellId || typeof hooks.retryCell !== "function") return;
        liveRetry.disabled = true;
        const label = liveMeta.textContent;
        liveMeta.textContent = `re-rolling ${cellId} with a new seed…`;
        let result = null;
        try {
            result = await hooks.retryCell({ cellId, cell: Number(liveLast?.cell) || 0 });
        } catch (error) {
            notify(`could not re-roll ${cellId}: ${error.message}`);
        }
        // The run that follows takes the strip over (and says what it is doing); on a refusal the
        // old label goes back so the button does not lie about what is on screen.
        liveRetry.disabled = liveLast?.whole_sheet === true;
        if (!result?.queued) liveMeta.textContent = label;
    }

    /**
     * Re-roll any cell from the Results list, whether or not a render is running.
     *
     * `cellId` is the cell whose frames should be replaced; each row offers it, so a bad cell can
     * be retried after the sheet is already on screen.
     */
    async function retryCell(cellId, trigger = null) {
        if (typeof hooks.retryCell !== "function") {
            notify("re-rolling needs the node wiring (the panel is running standalone).");
            return;
        }
        const id = String(cellId || "");
        if (!id) return;
        if (trigger) trigger.disabled = true;
        notify(`re-rendering ${id} with a new seed…`);
        try {
            await hooks.retryCell({ cellId: id });
        } catch (error) {
            notify(`could not re-roll ${id}: ${error.message}`);
        }
        if (trigger) trigger.disabled = false;
    }

    // ------------------------------------------------------------ live stream
    // A looping clip per sampling step, straight from the render (`preview_stream.py`), so the
    // panel shows what is being denoised instead of waiting for the first cell to land on disk.
    // Every frame is a JPEG data URL: nothing here fetches anything, and the loop is a timer.
    let liveCount = 0;
    let liveLast = null;
    // The stage caption's text: the same live facts the filmstrip prints.
    let liveMetaText = "";
    let liveFrames = [];
    let liveIndex = 0;
    let liveLoopTimer = null;

    function stopLiveLoop() {
        if (liveLoopTimer) clearInterval(liveLoopTimer);
        liveLoopTimer = null;
    }

    /** Play the clip we were last sent, at its own rate, looping in place. */
    function startLiveLoop() {
        stopLiveLoop();
        if (liveFrames.length < 2) return;
        const [low, high] = LIVE_FPS_RANGE;
        const fps = Math.min(high, Math.max(low, Number(liveLast?.fps) || 12));
        liveLoopTimer = setInterval(() => {
            if (!liveFrames.length) return;
            liveIndex = (liveIndex + 1) % liveFrames.length;
            liveFrame.src = liveFrames[liveIndex];
        }, Math.round(1000 / fps));
    }

    /**
     * Show one streamed clip, or clear the strip with `null`.
     *
     * `data` is the payload of the node's `h3_sheet_preview` event: `frames` (a list of JPEG data
     * URLs) and the `fps` to play them at. A single frame is simply a still. The panel-preview
     * setting decides whether there is a strip at all: with the panel's own preview switched Off,
     * the user asked for a smaller node, and a streaming clip is the opposite of that.
     */
    function setLivePreview(data) {
        const frames = Array.isArray(data?.frames)
            ? data.frames.filter((url) => typeof url === "string" && url)
            : (typeof data?.image === "string" && data.image ? [data.image] : []);
        if (!frames.length || panelPreview(state) === "off") {
            stopLiveLoop();
            liveStrip.classList.remove("is-waiting");
            liveStrip.style.display = "none";
            if (!frames.length) {
                liveCount = 0;
                liveLast = null;
                liveFrames = [];
                liveIndex = 0;
                liveFrame.removeAttribute("src");
                liveMeta.textContent = "";
            }
            // The stage's boxes let go of the live cell as well: no stream means nothing is being
            // drawn right now, and a box left wearing a stale frame would say otherwise.
            setTabLive("preview", false);
            liveMetaText = "";
            repaintStagePreview();
            syncStageCaption();
            return;
        }
        liveCount += 1;
        liveMetaText = "";
        liveLast = data;
        liveFrames = frames;
        liveIndex = 0;
        // The stage's sheet preview shows where the run has got to: the cell being rendered wears
        // the live frame, so the sheet fills in panel by panel instead of only in the strip.
        // AFTER the frame list is stored - the preview reads it to decide which box is live.
        repaintStagePreview();
        liveStrip.classList.remove("is-waiting");
        if (liveFrame.getAttribute("src") !== frames[0]) liveFrame.src = frames[0];
        startLiveLoop();
        const parts = [];
        const cell = Number(data.cell) || 0;
        const cells = Number(data.cells) || 0;
        // A draft pass renders the WHOLE sheet in one clip: the stream is marked `whole_sheet`, so
        // it says that instead of "cell 1", and there is no cell to re-roll - the seed that
        // decides a draft is the node's own, so the button would have nothing to act on.
        const whole = data.whole_sheet === true;
        if (whole) parts.push("whole sheet");
        else if (cell) parts.push(cells > 1 || cell > 1 ? `cell ${cell}${cells ? `/${cells}` : ""}` : "cell 1");
        liveRetry.disabled = whole;
        liveRetry.title = whole ? LIVE_RETRY_WHOLE_SHEET_TITLE : LIVE_RETRY_TITLE;
        const step = Number(data.step) || 0;
        const steps = Number(data.steps) || 0;
        if (step && steps) parts.push(`step ${step}/${steps}`);
        parts.push(frames.length === 1 ? "1 frame" : `${frames.length}-frame loop`);
        parts.push(`${liveCount} clip${liveCount === 1 ? "" : "s"}`);
        // One string, two places: the filmstrip prints it, and the stage's caption repeats it.
        // A suite's board goes FIRST, because it is the thing the cell number is relative to.
        const boardLabel = String(data.board_label || data.board || "");
        if (boardLabel) parts.unshift(boardLabel);
        const meta = parts.join(" · ");
        liveMeta.textContent = meta;
        liveMetaText = meta;
        followLiveBoard(data);
        syncStageCaption();
        if (liveStrip.style.display === "none") {
            liveStrip.style.display = "flex";
            // The strip adds a row to the panel: the node has to re-measure, exactly like a tab
            // switch or a new result does.
            hooks.layoutChanged?.();
        }
    }

    /**
     * Follow the board a suite render is drawing.
     *
     * The stream names it (``preview_stream`` is told the boards in render order by
     * ``suite.board_segments``), so the panel can show the sheet that is being worked on instead of
     * an empty folder for the whole run - the run renders one board at a time, and only the board
     * in hand has cells landing on disk. A plain single-sheet run never sends a board, so nothing
     * here can move the tab on its own, and switching is a preference the user can turn off (a
     * click on a chip, or the switch on the row).
     */
    function followLiveBoard(data) {
        const folder = String(data?.board_folder || data?.board || "");
        if (!folder || !followBoard(state) || folder === boardName()) return;
        // Only ever to a board this run actually has: a stale stream, or a run whose boards the
        // listing has not described yet, must not point the Results tab at a folder that is not
        // there.
        const boards = Array.isArray(lastSheet?.boards) ? lastSheet.boards : [];
        if (!boards.some((entry) => String(entry.folder || entry.id || "") === folder)) return;
        selectBoard(folder, { auto: true });
    }

    function dispose() {
        if (liveTimer) clearInterval(liveTimer);
        liveTimer = null;
        disposeObservers();
    }

    /**
     * Adopt different state in place.
     *
     * Every renderer here closes over `state`, so a workflow load (which produces a
     * fresh payload) must mutate this object rather than replace it - otherwise the
     * panel keeps showing the empty state it was built with.
     */
    function setState(next) {
        const fresh = next && typeof next === "object" ? next : {};
        state.refs = fresh.refs || blankRefs();
        state.cells = Array.isArray(fresh.cells) ? fresh.cells : [];
        state.prompt = String(fresh.prompt || "");
        state.negative = String(fresh.negative || "");
        // Everything else the payload owns comes across as well. This used to copy refs, cells,
        // prompt and the view switches only - so loading a workflow into an already-mounted node
        // kept THIS panel's build ticks, backdrop, suite and preset records, and the next persist()
        // then wrote those stale values back over the workflow it had just loaded. `resolutions`
        // and the knob values stay put: those come from the routes and the node, not the payload.
        state.build = {
            views: Array.isArray(fresh.build?.views) ? fresh.build.views.map(String) : ["face", "front"],
            poses: Array.isArray(fresh.build?.poses) ? fresh.build.poses.map(String) : ["neutral"],
            expressions: Array.isArray(fresh.build?.expressions)
                ? fresh.build.expressions.map(String)
                : ["neutral"],
        };
        state.background = String(fresh.background || "neutral");
        state.backgroundCustom = String(fresh.backgroundCustom || "");
        state.backgroundRef = String(fresh.backgroundRef || "");
        state.blurScope = blurScope(fresh);
        state.continuity = continuity(fresh);
        state.exportVideo = exportVideo(fresh);
        state.presetId = String(fresh.presetId || "");
        state.layoutPreset = String(fresh.layoutPreset || "");
        state.suite = Array.isArray(fresh.suite) ? fresh.suite.map(String) : [];
        state.suiteBoard = String(fresh.suiteBoard || "");
        // The sheet's LoRA stack comes with the workflow like everything else it decides.
        state.loras = loraStack(fresh);
        // ...and whether the Results tab follows the render (its own switch shows this).
        state.followBoard = followBoard(fresh);
        // A loaded workflow can carry a different compact preference and different knob
        // values, and the fields here must show what will actually render.
        state.compactKnobs = compactKnobs(fresh);
        // ...and its own answer to "should the panel poll the sheet folder?", which the header
        // switch has to agree with.
        state.autoRefresh = autoRefresh(fresh);
        auto.checked = state.autoRefresh;
        state.panelPreview = panelPreview(fresh);
        state.nodePreviews = nodePreviews(fresh);
        previewSelect.value = state.nodePreviews;
        panelPreviewSelect.value = state.panelPreview;
        syncSettings();
        refresh();
        return state;
    }

    function refresh() {
        closeOverlay();
        renderReferences();
        renderCells();
        renderBoards();
        renderLoras();
        // The line under the rails is a fact about what is set now, so it belongs on this path too:
        // a loaded workflow used to keep whatever the previous one had said there.
        showHint();
        refreshTabs();
        // The column follows the tab, and the tab is whatever the panel is showing: a refresh
        // (a new reference, a new cell list) must not leave the column showing the other tab's
        // block.
        syncColumn();
        // The prompt preview depends on the cells, the references and the node's
        // reference scope, so it is re-fetched whenever any of them changes.
        if (activeTab === "cells" || activeTab === "prompts") refreshPlan();
    }

    // Escape closes an overlay so the panel never traps the canvas.
    container.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && overlay) {
            event.stopPropagation();
            closeOverlay();
        }
    });

    // Re-lay-out the content when the node is resized.
    //
    // The tabs are built from the space they are given: the reference tiles are measured into
    // the box, the paint surface scales the picture into the pane, the results grid wraps. All
    // of that was computed once at render time, so a node the user made taller or wider kept
    // the small layout with empty space around it. The container's size comes from the node
    // (height: 100%), so re-rendering into it cannot start a resize loop.
    let lastSize = { width: 0, height: 0 };
    let relayoutTimer = null;
    const observers = [];
    function observeResize() {
        noteResize();
        if (typeof ResizeObserver !== "function") return;
        const observer = new ResizeObserver(() => noteResize());
        observer.observe(container);
        observers.push(observer);
    }

    function noteResize() {
        const width = Number(container.clientWidth) || 0;
        const height = Number(container.clientHeight) || 0;
        if (Math.abs(width - lastSize.width) < 12 && Math.abs(height - lastSize.height) < 12) return;
        lastSize = { width, height };
        clearTimeout(relayoutTimer);
        // Debounced: a drag emits a stream of sizes and only the last one matters.
        relayoutTimer = setTimeout(() => {
            relayoutTimer = null;
            renderReferences();
            refreshTabs();
        }, 180);
    }

    function disposeObservers() {
        clearTimeout(relayoutTimer);
        relayoutTimer = null;
        while (observers.length) observers.pop()?.disconnect?.();
    }

    showTab("references");
    refresh();
    renderResults(null);
    observeResize();
    return {
        container, status, results, refresh, renderResults, refreshResults, refreshTabs,
        refreshPlan, refreshSettings, syncSettings, renderHelp, noteResize,
        refreshLoras, renderLoras,
        autoRefresh: auto, openBrowse, openPreview, closeOverlay, showTab, setState, dispose,
        setRunning, setLivePreview,
        get activeTab() { return activeTab; },
        get loraLibrary() { return loraLibrary; },
        get loras() { return loraStack(state); },
        get overlay() { return overlay; },
        get live() { return Boolean(liveTimer); },
        get liveStrip() { return liveStrip; },
        get liveFrame() { return liveFrame; },
        get liveWait() { return liveWait; },
        get liveMeta() { return liveMeta; },
        get liveRetry() { return liveRetry; },
        retryCell,
        get liveFrames() { return liveCount; },
        get lastLiveFrame() { return liveLast; },
        get liveClip() { return liveFrames.slice(); },
        get liveIndex() { return liveIndex; },
        get livePlaying() { return Boolean(liveLoopTimer); },
        get promptBox() { return container.querySelector(".mmx-sheet-prompt"); },
        get negativeBox() { return container.querySelector(".mmx-sheet-negative"); },
        get knobFields() { return new Map(knobFields); },
        get knobs() { return knobGroups.flatMap((group) => group.knobs); },
        get compactKnobs() { return compactKnobs(state); },
        get nodePreviews() { return nodePreviews(state); },
    };
}

export const __internals = {
    optionRow, readChecks, selectBox, textInput, kindOfTicks, draggableOnto,
    dragCell: () => dragCell,
    loraStack,
};
