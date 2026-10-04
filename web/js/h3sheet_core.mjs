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
export const BLUR_TITLES = {
    auto: "Face blur: automatic - blurs this picture unless it is the identity reference",
    on: "Face blur: always - the faces in this picture are blurred before the render",
    off: "Face blur: never - this picture is sent exactly as it is",
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
export const PANEL_BUILD = "h3sheet_v56";

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

/** The panel's own preview size, defaulting to a medium sheet. */
export function panelPreview(state) {
    const value = String(state?.panelPreview || "").toLowerCase();
    return PANEL_PREVIEW_SIZES.some(([key]) => key === value) ? value : DEFAULT_PANEL_PREVIEW;
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

//: Node geometry measured on the live frontend: the DOM widget starts under the
//: node header (`widget.y`, 86px), the knob rows follow it with a small gap, and the node
//: keeps 20px below the panel of its own (measured: node height - widget.y - panel
//: clientHeight). The node is exactly as tall as that stack - a node taller than its panel
//: is the runaway "very very tall node" state, which only ever grows on its own.
//:
//: `maxHeight` is the ceiling for that stack: panes grow with their content now, so without
//: it a 110-thumbnail Results list would ask for a 3000px node. Past the ceiling the pane
//: scrolls again - inside a node that is already as tall as the screen. The wiring prefers a
//: viewport-derived ceiling and falls back to this one.
export const PANEL_FIT = { headerTop: 86, rowGap: 20, rowHeight: 24, bottomPad: 20, maxHeight: 1200 };

/** Height the node needs for this panel: header + panel + knob rows.
 *
 * A saved workflow restores its own node size and the frontend only ever grows a
 * node, so the wiring re-measures after every panel change and snaps the node to
 * this number - otherwise a sheet that was tall while it was rendering stays tall
 * for good, leaving a huge empty area under the panel.
 */
export function panelFitHeight({ top, panelHeight, rows, rowsHeight, ceiling } = {}) {
    const header = Number.isFinite(top) && top > 0 ? Number(top) : PANEL_FIT.headerTop;
    const height = Math.max(0, Number(panelHeight) || 0);
    const knobHeight = Number.isFinite(rowsHeight)
        ? Math.max(0, Number(rowsHeight))
        : Math.max(0, Number(rows) || 0) * PANEL_FIT.rowHeight;
    const gap = knobHeight > 0 ? PANEL_FIT.rowGap : 0;
    const wanted = Math.round(header + height + gap + knobHeight + PANEL_FIT.bottomPad);
    const limit = Number.isFinite(ceiling) && ceiling > 0 ? Number(ceiling) : PANEL_FIT.maxHeight;
    return Math.min(wanted, Math.round(limit));
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

/** The aspect a tile should take: the media's own shape, clamped to sane extremes. */
export function tileAspect(group, file, aspects) {
    const known = aspects?.get?.(file);
    const ratio = clampAspect(known);
    if (ratio) return ratio;
    return group?.kind === "video" ? 16 / 9 : group?.kind === "audio" ? 5 / 2 : 1;
}

// --------------------------------------------------------------------------- //
// styles (class based, so the panel matches the ComfyUI / Easy-Media look)
// --------------------------------------------------------------------------- //
export const PANEL_CSS = `
.mmx-sheet {
  --mmx-bg: var(--comfy-menu-bg, #1b1b1f);
  --mmx-card: var(--comfy-input-bg, #232329);
  --mmx-card-2: var(--comfy-input-bg, #17171c);
  --mmx-line: var(--border-color, #3a3a44);
  --mmx-fg: var(--fg-color, #e6e6ee);
  --mmx-muted: var(--descrip-text, #9aa0ae);
  --mmx-accent: var(--p-primary-color, #4f8cff);
  /* The Cells tab's group names: the same yellow-orange as the Build cells outline. */
  --mmx-tick: #ffb95e;
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
.mmx-btn--primary { background: var(--mmx-accent); border-color: var(--mmx-accent); color: #fff; }
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
.mmx-tabs { display: flex; gap: 4px; margin: 4px 0 6px; border-bottom: 1px solid var(--mmx-line); }
.mmx-tab {
  background: transparent; color: var(--mmx-muted); border: 1px solid transparent;
  border-bottom: none; border-radius: 6px 6px 0 0; padding: 4px 10px; cursor: pointer; font-size: 11px;
}
.mmx-tab.is-active { background: var(--mmx-card); color: var(--mmx-fg); border-color: var(--mmx-line); }
/* The panel is a column and the ACTIVE PANE fills what is left of it. Panes used to cap
   themselves at 520px "so a long Results list scrolls inside the panel" - which left an empty
   box under the content of a node the user had already made tall enough (every tab, not just
   the settings one). Now a pane grows with its content, the node fit measures that and sizes
   the node to it, and the ceiling in PANEL_FIT is what stops a 110-thumbnail Results list
   from making a 3000px node - past the ceiling the pane scrolls again, but inside a node that
   is already full-height. Keep these as real CSS comments: a double-slash line in here eats
   the whole next rule, and then every tab renders blank. */
.mmx-pane { display: none; }
.mmx-pane.is-active { display: block; flex: 1 1 auto; min-height: 0; overflow-y: auto; }
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
.mmx-card--refs { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }
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
.mmx-tile__blur--off { color: var(--mmx-muted); }
/* The preview's blur bar: original vs the copy the render wires. */
.mmx-preview__bar {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px; flex-wrap: wrap;
  border-top: 1px solid var(--mmx-line, rgba(255,255,255,.12)); font-size: 11px;
}
.mmx-preview__bar .mmx-btn.is-active { border-color: var(--mmx-accent); color: var(--mmx-fg); }
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
.mmx-seg .mmx-btn.is-active { background: var(--mmx-accent); color: #fff; }
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
        // Whether the node keeps its own knob rows or lets the panel draw them.
        compactKnobs: data?.ui?.compactKnobs !== false,
        // How big ComfyUI's own output previews under the panel may be.
        nodePreviews: nodePreviews({ nodePreviews: data?.ui?.nodePreviews }),
        // How big the panel's OWN preview of the sheet is (its Results tab).
        panelPreview: panelPreview({ panelPreview: data?.ui?.panelPreview }),
        // Whether the panel polls the sheet folder on its own (off by default).
        autoRefresh: autoRefresh({ autoRefresh: data?.ui?.autoRefresh }),
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
    // The preset id rides along so a saved workflow can say how the settings started.
    if (String(state?.presetId || "").trim()) payload.render.preset = String(state.presetId).trim();
    // A view preference, not a render setting: it decides whether the node draws its own
    // knob rows or leaves that to the panel. Recorded so it survives a reload.
    payload.ui = {
        compactKnobs: compactKnobs(state),
        nodePreviews: nodePreviews(state),
        panelPreview: panelPreview(state),
        autoRefresh: autoRefresh(state),
    };
    for (const group of REF_GROUPS) {
        payload.refs[group.key] = (state.refs?.[group.key] || [])
            .filter((item) => item && item.file)
            .map((item) => ({
                [group.file]: item.file,
                role: item.role || "",
                enabled: item.enabled !== false,
                // Only pictures can be blurred; leaving the field off a video keeps
                // the payload honest about what the node will do with it.
                ...(group.kind === "image"
                    ? {
                        blurFace: blurMode(item),
                        ...(Array.isArray(item.blurPaint) && item.blurPaint.length
                            ? { blurPaint: item.blurPaint }
                            : {}),
                    }
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
    // Wide enough that a phone photo (9:16) or a cinemascope clip keeps its own
    // shape: clamping it to 2:3 would put bars back in the tile.
    return Math.min(2.6, Math.max(0.38, Math.round(value * 1000) / 1000));
}


// --------------------------------------------------------------------------- //
// panel
// --------------------------------------------------------------------------- //
function optionRow(label, options, selected, onToggle, group = "") {
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
        boxes.push(box);
        row.append(box, caption);
    }
    wrap.append(row);
    return { row: wrap, boxes };
}

function readChecks(boxes, fallback) {
    const values = boxes.filter((box) => box.checked).map((box) => box.dataset.key);
    return values.length ? values : fallback;
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

    const container = element("div", { className: "mmx-sheet" });
    const styleTag = element("style", { textContent: PANEL_CSS });
    container.append(styleTag);

    // ------------------------------------------------------------- header
    const header = element("div", { className: "mmx-row" });
    const browseButton = button("Browse ComfyUI", () => openBrowse(REF_GROUPS[0], null));
    browseButton.title = "Pick references already in ComfyUI's input / output folders";
    const addButton = button("Upload references", () => pickFiles(null));
    addButton.title = "Add files from disk; each file lands in the first free slot of its kind";
    header.append(
        element("span", { textContent: "Character Sheet", className: "mmx-title" }),
        element("span", {
            textContent: PANEL_BUILD,
            className: "mmx-muted mmx-build",
            title: "The panel build this browser loaded. If it is older than the pack on disk,"
                + " reload the page (Ctrl+Shift+R) - a tab keeps the module it loaded first.",
        }),
        element("span", { className: "mmx-spacer" }),
        browseButton,
        addButton,
        button("Rebuild sheet", async () => {
            try {
                const answer = await hooks.compose?.();
                const sheet = answer?.sheet || null;
                notify(sheet?.sheetFile
                    ? `sheet rebuilt from the frames on disk → ${sheet.sheetFile} `
                        + "(a new file; the previous sheet is kept, no re-render)"
                    : "sheet rebuilt from the frames on disk (no re-render).");
                await refreshResults(sheet);
            } catch (error) {
                notify(`rebuild failed: ${error.message}`);
            }
        }),
        button("Clear sheet", async () => {
            try {
                await hooks.clearSheet?.();
                notify("sheet folder cleared.");
                await refreshResults();
            } catch (error) {
                notify(`clear failed: ${error.message}`);
            }
        }),
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
    const refreshButton = button("Refresh", async () => {
        await refreshResults();
        notify("results refreshed from the sheet folder");
    });
    refreshButton.dataset.action = "refresh-results";
    refreshButton.title = "Read the sheet folder again (new cells, new picks, new clips)";
    header.append(
        refreshButton,
        auto,
        element("span", { textContent: "auto-refresh", className: "mmx-muted" }),
    );
    container.append(header);

    // -------------------------------------------------------------- presets
    // Whole-node recommended settings. The list comes from the pack's backend
    // (h3_character_sheet/presets.py) so it is one definition, not two: the panel can only
    // offer what the node actually implements. Applying one writes the node's own widgets
    // through hooks.applyWidgets, the panel-owned settings into its state, and - when the
    // preset says which cells it is FOR - builds those cells. The user's own saved presets
    // ride in the same list (marked `custom`, stored by the backend in ComfyUI's user
    // directory) and are the only ones that can be deleted.
    const presetsRow = element("div", { className: "mmx-row mmx-presets" });
    const presetSelect = element("select", { className: "mmx-select" });
    presetSelect.dataset.action = "preset";
    const presetHint = element("span", { className: "mmx-muted" }, { flex: "1 1 220px" });
    let presetList = [];
    let presetsStore = "";

    function fillPresets(list, currentId = "") {
        presetList = Array.isArray(list) ? list : [];
        presetSelect.replaceChildren();
        const custom = element("option", { value: "", textContent: "Custom (no preset)" });
        presetSelect.append(custom);
        for (const entry of presetList) {
            presetSelect.append(element("option", {
                value: entry.id,
                textContent: entry.custom ? `${entry.label} (custom)` : entry.label,
            }));
        }
        const known = presetList.some((entry) => entry.id === currentId);
        presetSelect.value = known ? currentId : "";
        updateDeleteButton();
        showHint();
    }

    function showHint() {
        const entry = presetList.find((item) => item.id === presetSelect.value);
        if (!entry) {
            presetHint.textContent =
                "Presets set the whole node at once (cell size, frames, steps, reference "
                + "sizing, continuation, clip export, layout, shape). Editing a knob after "
                + "applying one is fine - it just becomes your own setting.";
            return;
        }
        // Say what it changes, not just what it is: a preset that quietly moves the node
        // off its defaults is how a user ends up with settings they never chose.
        const changed = Array.isArray(entry.deviates) ? entry.deviates : [];
        const note = changed.length
            ? ` Changes: ${changed.map((name) => labelOf(name)).join(", ")}.`
            : " Matches the node's own defaults.";
        const cells = entry.build && Object.keys(entry.build).length
            ? " Builds its cells."
            : "";
        presetHint.textContent = entry.hint + cells + note;
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
        // render.* keys the panel owns (continuation, clip export, backdrop, ...).
        for (const [key, value] of Object.entries(entry.render || {})) {
            if (key === "continuity") state.continuity = value;
            else if (key === "exportVideo") state.exportVideo = value;
            else if (key === "background") state.background = String(value || "neutral");
            else if (key === "backgroundRef") state.backgroundRef = String(value || "");
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
        state.presetId = entry.id;
        // The node's knobs: the preset's widget group plus its sheet group, mapped onto the
        // widgets that carry layout (which the panel does not own).
        const widgets = { ...(entry.widgets || {}) };
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
        notify(built
            ? `preset applied: ${entry.label} - ${built} cell(s) built`
            : `preset applied: ${entry.label}`);
    }

    presetSelect.addEventListener("change", async () => {
        const entry = presetList.find((item) => item.id === presetSelect.value);
        if (!entry) {
            state.presetId = "";
            updateDeleteButton();
            showHint();
            persist();
            notify("preset cleared - the settings stay as they are");
            return;
        }
        await applyPreset(entry);
        updateDeleteButton();
        showHint();
    });

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
        const entry = presetList.find((item) => item.id === presetSelect.value);
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
            fillPresets(answer.presets, String(saved.id || ""));
            if (saved.id) {
                // Saving IS choosing it: the workflow now records where these numbers came from.
                state.presetId = String(saved.id);
                persist();
            }
            presetName.value = "";
            showSaveRow(false);
            notify(`preset saved: ${saved.label || name}`);
        } catch (error) {
            notify(`could not save the preset: ${error.message}`);
        }
    }

    async function removePreset() {
        const entry = presetList.find((item) => item.id === presetSelect.value);
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

    presetsRow.append(
        element("span", { textContent: "Preset", className: "mmx-muted" }, { flex: "0 0 96px" }),
        presetSelect,
        presetSaveButton,
        presetDelete,
        presetHint,
    );
    container.append(presetsRow, presetSaveRow);
    if (typeof hooks.listPresets === "function") {
        Promise.resolve(hooks.listPresets())
            .then((data) => {
                presetsStore = String(data?.store || "");
                fillPresets(data?.presets, String(state.presetId || ""));
            })
            .catch(() => fillPresets([], ""));
    } else {
        fillPresets([], "");
    }

    const status = element("div", { textContent: "ready", className: "mmx-status" });
    container.append(status);

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

    const compactBox = element("input", { type: "checkbox", id: "mmx-compact-knobs" });
    compactBox.checked = compactKnobs(state);
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
        compactBox,
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
        if (knob.kind === "toggle") {
            label.classList.add("mmx-knob--toggle");
            const box = element("input", { type: "checkbox", checked: Boolean(knob.value) });
            box.addEventListener("change", () => commit(box.checked));
            control = box;
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
        }
        label.append(control);
        if (knob.hint) {
            label.append(element("span", { textContent: knob.hint, className: "mmx-knob__hint" }));
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
            section.append(element("div", { textContent: group.group, className: "mmx-knob-group__title" }));
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
        settingsNote.textContent = total
            ? `${total} knobs - the same values the node renders with, in ${knobColumns} columns instead of ${total} node rows.`
            : "no knobs reported by the node.";
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

    // --------------------------------------------------------------- tabs
    const tabBar = element("div", { className: "mmx-tabs" });
    const panes = {
        references: element("div", { className: "mmx-pane is-active mmx-pane--references" }),
        cells: element("div", { className: "mmx-pane mmx-pane--cells" }),
        prompts: element("div", { className: "mmx-pane mmx-pane--prompts" }),
        results: element("div", { className: "mmx-pane mmx-pane--results mmx-results" }),
        settings: settingsPane,
        help: helpPane,
    };
    const tabButtons = {};
    let activeTab = "references";
    function showTab(key) {
        activeTab = key;
        for (const [name, pane] of Object.entries(panes)) pane.classList.toggle("is-active", name === key);
        for (const [name, tab] of Object.entries(tabButtons)) tab.classList.toggle("is-active", name === key);
        if (key === "results") refreshResults();
        // The prompt preview comes from the render's own planner, so it is fetched
        // rather than guessed - and it changes whenever the references or cells do.
        if (key === "cells" || key === "prompts") refreshPlan();
        // The pane decides how tall the panel is, so the node has to re-measure.
        hooks.layoutChanged?.();
    }
    for (const [key, label] of [
        ["references", "References"], ["cells", "Cells"], ["prompts", "Prompt"],
        ["results", "Results"], ["settings", "Settings"], ["help", "Help"],
    ]) {
        const tab = button(label, () => showTab(key));
        tab.classList.add("mmx-tab");
        tab.dataset.tab = key;
        tabButtons[key] = tab;
        tabBar.append(tab);
    }
    // The live stream strip sits between the tabs and the panes: on every tab, and outside the
    // Results pane (which `renderResults` rebuilds from scratch on each refresh).
    const liveStrip = element("div", { className: "mmx-live" }, { display: "none" });
    const liveMeta = element("span", { className: "mmx-live__meta", textContent: "" });
    const liveFrame = element("img", { className: "mmx-live__frame", alt: "", src: "" });
    const liveWait = element("div", { className: "mmx-live__wait", title: "waiting for the render's first frame" });
    // "I don't like this one": stop the run and render this cell again with a new seed. Only the
    // cell on screen is re-rolled - the rest of the sheet keeps the frames already on disk, and
    // the panel recomposes the sheet from them afterwards.
    const liveRetry = button("↻ new seed", () => retryLiveCell());
    liveRetry.classList.add("mmx-btn--quiet", "mmx-live__retry");
    liveRetry.title = "Stop the run and render this cell again with a new seed";
    liveStrip.append(
        element("div", { className: "mmx-live__head" }, {}, [
            element("span", { className: "mmx-live__tag", textContent: "LIVE" }),
            liveMeta,
            liveRetry,
        ]),
        liveFrame,
        liveWait,
    );
    container.append(
        tabBar, liveStrip, panes.references, panes.cells, panes.prompts, panes.results, panes.settings, panes.help,
    );
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
    function tile(group, index, ordinal) {
        const slot = state.refs[group.key][index];
        const wrap = element("div", { className: "mmx-slot mmx-sheet-ref" });
        wrap.dataset.group = group.key;
        wrap.dataset.index = String(index);

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
            const read = () => (media.naturalWidth || media.videoWidth)
                ? rememberAspect(slot.file, media.naturalWidth, media.naturalHeight)
                : rememberAspect(slot.file, media.videoWidth, media.videoHeight);
            if ((media.complete && media.naturalWidth) || media.readyState >= 1) read();
            else media.addEventListener(group.kind === "image" ? "load" : "loadedmetadata", read, { once: true });
            box.append(media);
        } else {
            // No element to show (audio has no thumbnail): the icon alone. The filename is
            // already the tile's caption below, and saying it twice was pure noise.
            box.append(element("div", { className: "mmx-tile__note" }, {}, [icon(group.kind, { size: 22 })]));
        }
        // Bottom-left corner: the filename for a video / audio tile, and for a picture the
        // face-blur toggle. "auto" means "blur this unless it is the identity reference".
        const blurState = group.kind === "image" ? blurMode(slot) : null;
        if (blurState) {
            const blurButton = element("button", {
                textContent: blurButtonLabel(slot),
                className: `mmx-tile__blur mmx-tile__blur--${blurState}`,
                type: "button",
            });
            blurButton.title = `${BLUR_TITLES[blurState]}\n(click to change)\n${slot.file}`;
            blurButton.dataset.blur = blurState;
            blurButton.addEventListener("click", (event) => {
                event.stopPropagation();
                slot.blurFace = nextBlurMode(blurState);
                persist();
                renderReferences();
            });
            box.append(blurButton);
        } else {
            box.append(element("span", { textContent: slot.file.split("/").pop(), className: "mmx-tile__name" }));
        }

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
            if (slot.file) openBrowse(group, index);
            else pickFiles(group, index);
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
                box.classList.add("is-drag");
                if (event.dataTransfer) {
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", `mmx-slot:${group.key}:${index}`);
                }
            });
            box.addEventListener("dragend", () => {
                dragState = null;
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
                textContent: "Roles decide which picture supplies what: name the attribute in "
                    + "each role (face, hair, glasses / body, clothes). Every cell prompt then "
                    + "tells H3 to take that from its picture and not from the others.",
                className: "mmx-muted",
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
    function renderReferences() {
        refsHost.replaceChildren();
        const prompt = promptCard();
        refsHost.append(prompt.card);

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
        // How far a face blur reaches. Sheet-wide, because it is a look, not a
        // per-picture decision: the per-tile chip says WHETHER, this says HOW MUCH.
        const blurArea = selectBox(
            BLUR_SCOPES,
            blurScope(state),
            (value) => {
                state.blurScope = value;
                persist();
                refresh();
            },
        );
        blurArea.dataset.action = "blur-scope";
        blurArea.title =
            "How much of the head a face blur covers: the whole patch is grown around the detected face";
        head.append(
            element("span", { textContent: "References", className: "mmx-label" }),
            element("span", { textContent: `${filled.length}/${capacity}`, className: "mmx-count mmx-sheet-count" }),
            // Blur area sits with the title, before the long muted hint: a wrapping row
            // must never separate a label from its control (the buttons go last).
            element("span", { textContent: "Blur area", className: "mmx-muted" }),
            blurArea,
            element("span", {
                textContent: "pictures, then video, then audio — each role says what that reference supplies",
                className: "mmx-muted",
            }),
            element("span", { className: "mmx-spacer" }),
            browse, upload, clear,
        );

        const boxHost = element("div", { className: "mmx-refbox" });
        // The floor only: the box grows with the pane (`.mmx-refbox` is a flex item), and the
        // tile maths below reads its live clientHeight/clientWidth, so a taller or wider node
        // means bigger tiles rather than a 178px strip with empty space beneath it.
        boxHost.style.minHeight = `${REF_SECTION.height}px`;
        renderedTiles = [];
        for (const entry of filled) boxHost.append(tile(entry.group, entry.index, entry.ordinal));
        if (filled.length < capacity) boxHost.append(addMediaTile({ empty: filled.length === 0 }));
        card.append(head, boxHost);

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
        refsHost.append(card);
        refsHost.append(element("div", {
            textContent: "Drop pictures, video or audio anywhere in the box: each file goes to its own kind "
                + "(pictures first, then video, then audio) and the badge is its number in the prompt. "
                + "The box keeps its size and the tiles scale to fit it.",
            className: "mmx-muted",
        }));
        layoutTiles();
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
    function blurPreviewBar(slot, media, slotIndex) {
        const bar = element("div", { className: "mmx-preview__bar" });
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
        fetchBlur();
        return bar;
    }

    function openPreview(group, index) {
        const slot = state.refs[group.key][index];
        if (!slot?.file) return;
        const pane = openOverlay("mmx-preview");
        const head = element("div", { className: "mmx-overlay__head" });
        head.append(
            element("span", { textContent: `${group.label.slice(0, -1)} ${index + 1}`, className: "mmx-title" }),
            element("span", { textContent: slot.file, className: "mmx-muted" }),
            element("span", { className: "mmx-spacer" }),
            button("Close", closeOverlay),
        );
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
            const paint = mountPaintSurface(slot, image, slotNumber);
            stage.append(paint.frame);
            extras.push(blurPreviewBar(slot, image, slotNumber), paint.toolbar);
        } else if (group.kind === "video") {
            stage.append(element("video", { src: url, controls: true, loop: true, playsInline: true }));
        } else {
            stage.append(element("audio", { src: url, controls: true }));
        }
        pane.append(head, stage, ...extras);
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
    function mountPaintSurface(slot, image, slotNumber) {
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
            const naturalWidth = image.naturalWidth || 1;
            const naturalHeight = image.naturalHeight || 1;
            const stage = frame.parentElement;
            // The pane grows with its content, so the stage never constrains the frame by
            // itself: the pane's own max-height is the real ceiling (it is what keeps the
            // node from growing), minus the header and the two bars around the stage.
            const host = frame.closest(".mmx-pane") || stage;
            let availableWidth = (host?.clientWidth || stage?.clientWidth || naturalWidth);
            let availableHeight = (host?.clientHeight || stage?.clientHeight || naturalHeight);
            const cap = parseFloat(globalThis.getComputedStyle?.(host)?.maxHeight || "");
            if (Number.isFinite(cap) && cap > 0) availableHeight = Math.min(availableHeight, cap);
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

        if (image.complete && image.naturalWidth) sync();
        else image.addEventListener("load", sync, { once: true });
        // The pane may not have been laid out when the surface is built (a first sync then
        // falls back to the image's natural size and the frame overflows the stage), so
        // measure again once the browser has painted. Painting itself re-syncs too.
        const nextFrame = globalThis.requestAnimationFrame
            ? (fn) => globalThis.requestAnimationFrame(fn)
            : (fn) => setTimeout(fn, 16);
        nextFrame(() => nextFrame(sync));

        canvas.addEventListener("pointerdown", (event) => {
            if (!painting) return;
            // The frame is sized from the image, so marking before it has loaded would
            // paint against a placeholder shape and land in the wrong place.
            if (!image.naturalWidth) {
                note.textContent = "waiting for the image to load…";
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

    const browseState = { source: "inputs", kind: "all", query: "" };

    /** `index` = the slot being filled, or null for "first free slot".
     *  ``group`` null = the unified picker: every kind, each file routed by type. */
    function openBrowse(group, index) {
        browseState.kind = group ? group.kind : "all";
        browseState.query = "";
        renderBrowse(group, index);
    }

    function renderBrowse(group, index) {
        const pane = openOverlay("mmx-browse");
        container.dataset.browseFor = `${group ? group.key : "media"}:${index ?? "auto"}`;

        const head = element("div", { className: "mmx-overlay__head" });
        const sourceSeg = element("div", { className: "mmx-seg" });
        for (const [key, label] of [["inputs", "Inputs"], ["outputs", "Outputs"]]) {
            const seg = button(label, () => {
                browseState.source = key;
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
        head.append(
            element("span", {
                textContent: group ? `Choose ${group.label.toLowerCase()}` : "Choose media - pictures, video or audio",
                className: "mmx-title",
            }),
            sourceSeg,
            kindSelect,
            search,
            element("span", { className: "mmx-spacer" }),
            button("Upload from disk", () => pickFiles(group, index)),
            button("Close", closeOverlay),
        );

        const body = element("div", { className: "mmx-overlay__body" });
        const grid = element("div", { className: "mmx-pickgrid" });
        const foot = element("div", { className: "mmx-muted" });
        foot.textContent = "Loading…";
        body.append(grid);
        pane.append(head, body, foot);

        Promise.resolve(hooks.listMedia?.({ ...browseState }))
            .then((payload) => {
                if (!payload || payload.ok === false) {
                    foot.textContent = payload?.error || "Could not list that folder.";
                    return;
                }
                const items = payload.items || [];
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
                foot.textContent = items.length
                    ? `${items.length} file(s) in ${payload.source}${browseState.query ? ` matching “${browseState.query}”` : " (newest first)"}${payload.truncated ? " — newest only" : ""}`
                    : "Nothing here yet — drop files on a tile, or use “Upload from disk”.";
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
            planNote.textContent = planned.length
                ? `${planned.length} cell(s) from the ticks: ${planned.map((cell) => cell.id).join(", ")}`
                : "No views ticked - with an empty cell list the node would render the default 8-view matrix.";
        }
        // The ticks are part of the payload: if the cell list is ever empty (a panel
        // that reloaded without one) the node renders exactly what is ticked here.
        const syncBuild = () => {
            state.build = ticks();
            persist();
            updatePlanNote();
            refreshTabs();
        };
        const views = optionRow("Views", VIEWS, new Set(state.build.views), syncBuild, "views");
        const poses = optionRow("Poses", POSES, new Set(state.build.poses), syncBuild, "poses");
        const expressions = optionRow("Expressions", EXPRESSIONS, new Set(state.build.expressions), syncBuild, "expressions");
        const background = backgroundRow();
        const order = element("div", {
            textContent: "Cells render top to bottom - the Results tab fills in that order.",
            className: "mmx-muted",
        }, { marginTop: "2px" });
        const shape = element("div", {
            textContent: "Cell shape comes from the node's cell_aspect (default 3:4, "
                + "cell_size = short edge). Per-cell aspect overrides it.",
            className: "mmx-muted",
        }, { marginTop: "2px" });
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
            + "share a camera distance (full body -> full body), because the hand-over "
            + "carries the previous framing. Per cell override below.";
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
        cellsHost.append(builder);
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
            cellsHost.append(note);
            cellsHost.append(element("div", {
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
        cellsHost.append(list);
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
            results.append(element("div", {
                textContent: "Nothing rendered yet — queue the prompt to render the cells.",
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
        if (shown.sheetUrl) {
            const size = panelPreview(state);
            const height = PANEL_PREVIEW_HEIGHTS[size] || 0;
            if (size !== "off") {
                const image = element("img", {
                    src: viewUrl(shown.sheetUrl),
                    className: "mmx-sheet-preview",
                    title: `${shown.sheetFile || "sheet"} - click to open it full size`,
                }, height
                    ? { maxHeight: `${height}px`, width: "auto", maxWidth: "100%" }
                    : { width: "100%", height: "auto" });
                const link = element("a", {
                    href: viewUrl(shown.sheetUrl), target: "_blank", rel: "noreferrer",
                }, { display: "block", marginBottom: "4px" });
                link.append(image);
                results.append(link);
                resultHead = { image, link, counts: null };
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
                    results.append(video);
                }
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
                        const answer = await hooks.pickFrame?.(cell.id, index);
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
                sheet = await hooks.listResults?.();
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
        tabButtons.references.textContent = `References ${filled}/${slots}`;
        tabButtons.cells.textContent = `Cells ${state.cells.length}`;
        const rendered = lastSheet?.counts?.rendered;
        tabButtons.results.textContent = rendered === undefined ? "Results" : `Results ${rendered}`;
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
            if (activeTab !== "results") tabButtons.results.textContent = `Results ${now}`;
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
        liveRetry.disabled = false;
        // The run that follows takes the strip over (and says what it is doing); on a refusal the
        // old label goes back so the button does not lie about what is on screen.
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
            return;
        }
        liveCount += 1;
        liveLast = data;
        liveFrames = frames;
        liveIndex = 0;
        liveStrip.classList.remove("is-waiting");
        if (liveFrame.getAttribute("src") !== frames[0]) liveFrame.src = frames[0];
        startLiveLoop();
        const parts = [];
        const cell = Number(data.cell) || 0;
        const cells = Number(data.cells) || 0;
        if (cell) parts.push(cells > 1 || cell > 1 ? `cell ${cell}${cells ? `/${cells}` : ""}` : "cell 1");
        const step = Number(data.step) || 0;
        const steps = Number(data.steps) || 0;
        if (step && steps) parts.push(`step ${step}/${steps}`);
        parts.push(frames.length === 1 ? "1 frame" : `${frames.length}-frame loop`);
        parts.push(`${liveCount} clip${liveCount === 1 ? "" : "s"}`);
        liveMeta.textContent = parts.join(" · ");
        if (liveStrip.style.display === "none") {
            liveStrip.style.display = "flex";
            // The strip adds a row to the panel: the node has to re-measure, exactly like a tab
            // switch or a new result does.
            hooks.layoutChanged?.();
        }
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
        refreshTabs();
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
        autoRefresh: auto, openBrowse, openPreview, closeOverlay, showTab, setState, dispose,
        setRunning, setLivePreview,
        get activeTab() { return activeTab; },
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

export const __internals = { optionRow, readChecks, selectBox, textInput };
