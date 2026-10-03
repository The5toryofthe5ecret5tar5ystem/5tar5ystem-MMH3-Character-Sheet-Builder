// MiniMax H3 Character Sheet Maker — panel DOM + state (no ComfyUI imports).
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

export const VIEWS = [
    ["face", "Face close up"],
    ["portrait", "Portrait"],
    ["front", "Full body front"],
    ["profile", "Full body side"],
    ["back", "Full body back"],
];
export const POSES = [
    ["neutral", "Neutral"],
    ["a-pose", "A-pose"],
    ["t-pose", "T-pose"],
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
];
export const PICKS = ["auto", "last", "sharpest"];

//: What the model is told to put behind the figure. Mirrors BACKGROUNDS in
//: h3_character_sheet/sheet_spec.py (the wiring test compares the two).
export const BACKGROUNDS = [
    ["neutral", "Neutral grey"],
    ["white", "Flat white"],
    ["grey", "Mid grey"],
    ["black", "Flat black"],
    ["green", "Green screen"],
    ["blue", "Blue screen"],
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
        kind: "image",
        icon: "\u25a3",
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
        icon: "\u25b6",
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
        icon: "\u266a",
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

/** The per-cell continuation mode, defaulting to ``inherit``. */
/** How many columns the Settings tab packs the node's knobs into. */
export const KNOB_COLUMNS = 3;

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
export const PANEL_FIT = { headerTop: 86, rowGap: 20, rowHeight: 24, bottomPad: 20 };

/** Height the node needs for this panel: header + panel + knob rows.
 *
 * A saved workflow restores its own node size and the frontend only ever grows a
 * node, so the wiring re-measures after every panel change and snaps the node to
 * this number - otherwise a sheet that was tall while it was rendering stays tall
 * for good, leaving a huge empty area under the panel.
 */
export function panelFitHeight({ top, panelHeight, rows, rowsHeight } = {}) {
    const header = Number.isFinite(top) && top > 0 ? Number(top) : PANEL_FIT.headerTop;
    const height = Math.max(0, Number(panelHeight) || 0);
    const knobHeight = Number.isFinite(rowsHeight)
        ? Math.max(0, Number(rowsHeight))
        : Math.max(0, Number(rows) || 0) * PANEL_FIT.rowHeight;
    const gap = knobHeight > 0 ? PANEL_FIT.rowGap : 0;
    return Math.round(header + height + gap + knobHeight + PANEL_FIT.bottomPad);
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
  --mmx-danger: #e05561;
  width: 100%; height: 100%; box-sizing: border-box; overflow: auto;
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
.mmx-btn--icon { padding: 2px 6px; }
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
/* One pane at a time. A long pane (a run's 110 frame thumbnails) scrolls INSIDE the
   panel instead of growing the node: the node is only as tall as panel + knobs.
   Keep these as real CSS comments - a double-slash line in here eats the whole next
   rule, and then every tab renders blank. */
.mmx-pane { display: none; }
.mmx-pane.is-active { display: block; max-height: 520px; overflow-y: auto; }
/* The Settings grid is the exception to that cap: it is the one pane whose whole purpose is
   "every knob at once", its content is bounded (a few dozen fields), and a scrollbar inside a
   node the user has already made big enough is exactly what this tab exists to avoid. The
   wiring then grows the node to fit it (see fitNodeToPanel) instead of scrolling it. */
.mmx-pane--settings.is-active { max-height: none; }
.mmx-card {
  background: var(--mmx-card); border: 1px solid var(--mmx-line); border-radius: 8px;
  padding: 6px; margin: 0 0 8px;
}
.mmx-card.is-drop { border-color: var(--mmx-accent); }
.mmx-card__head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.mmx-label { font-size: 10px; font-weight: 650; text-transform: uppercase; letter-spacing: .06em; color: var(--mmx-muted); }
.mmx-count { font-size: 10px; color: var(--mmx-muted); }
.mmx-grid { display: grid; gap: 6px; align-items: start; }
/* One grid for every reference. Fixed height, tiles sized to fit inside. */
.mmx-refbox {
  display: flex; flex-wrap: wrap; align-content: flex-start; gap: 6px;
  padding: 4px; box-sizing: border-box; overflow: auto;
  background: rgba(0,0,0,.14); border: 1px solid var(--mmx-line); border-radius: 6px;
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
.mmx-tile--add .mmx-tile__note b { font-size: 18px; }
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
  font-size: 10px; line-height: 1; padding: 2px 4px; border-radius: 4px; flex: 0 0 auto;
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
.mmx-tile__note { display: flex; flex-direction: column; align-items: center; gap: 2px; color: var(--mmx-muted); text-align: center; padding: 4px; }
.mmx-tile__note b { font-size: 16px; font-weight: 500; }
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
  gap: 3px; opacity: 0; pointer-events: none; transition: opacity .12s;
}
.mmx-tile__actions .mmx-btn { width: 22px; height: 22px; min-height: 0; padding: 0; font-size: 12px; line-height: 1; }
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
/* Compact knobs: the node's own widgets, packed into columns the frontend cannot make.
   One grid per group, each field labelled, values written straight onto the widget. */
.mmx-settings__head { gap: 6px; }
.mmx-knob-group { margin-bottom: 8px; }
.mmx-knob-group__title {
  font-size: 10px; font-weight: 650; color: var(--mmx-muted); text-transform: uppercase;
  letter-spacing: .04em; margin: 2px 0 4px;
}
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

export function button(label, onClick, style = {}) {
    const node = element("button", { textContent: label, type: "button", className: "mmx-btn" }, style);
    node.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick(event);
    });
    return node;
}

function iconButton(glyph, title, onClick, extraClass = "") {
    const node = button(glyph, onClick);
    node.classList.add("mmx-btn--icon");
    if (extraClass) node.classList.add(extraClass);
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
    payload.ui = { compactKnobs: compactKnobs(state) };
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
function optionRow(label, options, selected, onToggle) {
    const row = element("div", { className: "mmx-row" }, { marginBottom: "3px" });
    row.append(element("span", { textContent: label, className: "mmx-muted" }, { flex: "0 0 62px" }));
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
    return { row, boxes };
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
        element("span", { className: "mmx-spacer" }),
        browseButton,
        addButton,
        button("Rebuild sheet", async () => {
            try {
                await hooks.compose?.();
                notify("sheet rebuilt from the frames on disk (no re-render).");
                await refreshResults();
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
    const auto = element("input", { type: "checkbox", checked: true });
    auto.title = "Poll the sheet folder while the panel is open";
    auto.dataset.mmxSheetAuto = "1";
    header.append(auto, element("span", { textContent: "auto-refresh", className: "mmx-muted" }));
    container.append(header);

    // -------------------------------------------------------------- presets
    // Whole-node recommended settings. The list comes from the pack's backend
    // (h3_character_sheet/presets.py) so it is one definition, not two: the panel can only
    // offer what the node actually implements. Applying one writes the node's own widgets
    // through hooks.applyWidgets and the panel-owned settings into its state.
    const presetsRow = element("div", { className: "mmx-row mmx-presets" });
    const presetSelect = element("select", { className: "mmx-select" });
    presetSelect.dataset.action = "preset";
    const presetHint = element("span", { className: "mmx-muted" }, { flex: "1 1 220px" });
    let presetList = [];

    function fillPresets(list, currentId = "") {
        presetList = Array.isArray(list) ? list : [];
        presetSelect.replaceChildren();
        const custom = element("option", { value: "", textContent: "Custom (no preset)" });
        presetSelect.append(custom);
        for (const entry of presetList) {
            presetSelect.append(element("option", { value: entry.id, textContent: entry.label }));
        }
        const known = presetList.some((entry) => entry.id === currentId);
        presetSelect.value = known ? currentId : "";
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
        presetHint.textContent = entry.hint + note;
    }

    /** Widget name -> what a person calls it, for the "changes:" line. */
    function labelOf(name) {
        const words = String(name || "").replace(/^sheet_/, "sheet ").replace(/_/g, " ");
        return words.charAt(0).toUpperCase() + words.slice(1);
    }

    async function applyPreset(entry) {
        // render.* keys the panel owns (continuation, clip export, ...).
        for (const [key, value] of Object.entries(entry.render || {})) {
            if (key === "continuity") state.continuity = value;
            else if (key === "exportVideo") state.exportVideo = value;
        }
        if (entry.build && Object.keys(entry.build).length) {
            // Ticks only: the preset says which cells it is FOR, and building them stays the
            // user's call - an existing cell list is never rewritten by a preset.
            for (const [key, values] of Object.entries(entry.build)) {
                if (Array.isArray(values) && values.length) state.build[key] = [...values];
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
        notify(`preset applied: ${entry.label}`);
    }

    presetSelect.addEventListener("change", async () => {
        const entry = presetList.find((item) => item.id === presetSelect.value);
        if (!entry) {
            state.presetId = "";
            showHint();
            persist();
            notify("preset cleared - the settings stay as they are");
            return;
        }
        await applyPreset(entry);
        showHint();
    });

    presetsRow.append(
        element("span", { textContent: "Preset", className: "mmx-muted" }, { flex: "0 0 96px" }),
        presetSelect,
        presetHint,
    );
    container.append(presetsRow);
    if (typeof hooks.listPresets === "function") {
        Promise.resolve(hooks.listPresets())
            .then((data) => fillPresets(data?.presets, String(state.presetId || "")))
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
    const settingsHead = element("div", { className: "mmx-row mmx-settings__head" }, { marginBottom: "4px" });
    settingsHead.append(
        compactBox,
        element(
            "label",
            { textContent: "Compact node", htmlFor: "mmx-compact-knobs" },
            { fontSize: "10px" },
        ),
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

    function renderSettings() {
        knobFields.clear();
        settingsHost.replaceChildren();
        let total = 0;
        for (const group of knobGroups) {
            const section = element("div", { className: "mmx-knob-group" });
            section.dataset.group = group.group;
            section.append(element("div", { textContent: group.group, className: "mmx-knob-group__title" }));
            const grid = element("div", { className: "mmx-knob-grid" }, {
                gridTemplateColumns: `repeat(${KNOB_COLUMNS}, minmax(0, 1fr))`,
            });
            for (const knob of group.knobs) {
                const { label, control } = knobField(knob);
                grid.append(label);
                knobFields.set(knob.name, control);
                total += 1;
            }
            section.append(grid);
            settingsHost.append(section);
        }
        settingsNote.textContent = total
            ? `${total} knobs - the same values the node renders with, in ${KNOB_COLUMNS} columns instead of ${total} node rows.`
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

    /** Adopt the backend's knob list (labels, groups, bounds) and show the live values. */
    function refreshSettings(data) {
        const groups = Array.isArray(data?.groups) && data.groups.length
            ? data.groups
            : (Array.isArray(data?.knobs) && data.knobs.length
                ? [{ group: "Settings", knobs: data.knobs }]
                : []);
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
                title: link.note || link.url,
            });
            // A click inside the panel must not reach the canvas (and with it the node).
            anchor.addEventListener("click", (event) => event.stopPropagation());
            host.append(anchor);
            if (link.note) host.append(element("span", { textContent: link.note, className: "mmx-help__link-note" }));
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
        if (item.what) card.append(element("div", { textContent: item.what, className: "mmx-req__what" }));
        card.append(element("div", {
            textContent: item.file_ok === false || !item.found
                ? `put it in: ${item.where}`
                : `found: ${item.found}`,
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
        if (item.note) card.append(element("div", { textContent: item.note, className: "mmx-req__what" }));
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
                block.append(element("div", { textContent: section.intro, className: "mmx-help__intro" }));
            }
            if (section.kind === "files") {
                for (const item of requirements) block.append(requirementRow(item));
            }
            if (section.steps?.length) {
                const list = element("ol", { className: "mmx-help__steps" });
                for (const step of section.steps) list.append(element("li", { textContent: step }));
                block.append(list);
            }
            if (section.bullets?.length) {
                const list = element("ul", { className: "mmx-help__bullets" });
                for (const bullet of section.bullets) list.append(element("li", { textContent: bullet }));
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
    container.append(
        tabBar, panes.references, panes.cells, panes.prompts, panes.results, panes.settings, panes.help,
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
            box.append(element("div", { className: "mmx-tile__note" }, {}, [
                element("b", { textContent: group.icon }),
                element("span", { textContent: slot.file.split("/").pop(), className: "mmx-muted" }),
            ]));
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
            textContent: group.icon,
            className: `mmx-tile__kind mmx-tile__kind--${group.kind}`,
        });
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
                iconButton("\ud83d\udc41", "Preview", (event) => {
                    event.stopPropagation();
                    openPreview(group, index);
                }),
                iconButton("\u2715", "Remove this reference", (event) => {
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
            element("b", { textContent: "+" }),
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
    /** Backdrop for every cell: a preset, or the user's own words. */
    function backgroundRow() {
        const row = element("div", { className: "mmx-row" }, { marginTop: "4px" });
        row.append(element("span", { textContent: "Background", className: "mmx-muted" }));
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
        if ((state.background || "neutral") !== "custom") box.style.display = "none";
        row.append(select, box);
        return row;
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
        boxHost.style.height = `${REF_SECTION.height}px`;
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
                            element("b", { textContent: item.kind === "video" ? "🎬" : "♪" }),
                            element("span", { textContent: item.kind, className: "mmx-muted" }),
                        ]));
                    }
                    // Which kind this is, so one picker can serve all three.
                    const chip = element("span", {
                        textContent: item.kind === "video" ? "\u25b6" : item.kind === "audio" ? "\u266a" : "\u25a3",
                        className: `mmx-tile__kind mmx-tile__kind--${item.kind}`,
                    }, { position: "absolute", top: "4px", left: "4px" });
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
        const views = optionRow("Views", VIEWS, new Set(state.build.views), syncBuild);
        const poses = optionRow("Poses", POSES, new Set(state.build.poses), syncBuild);
        const expressions = optionRow("Expressions", EXPRESSIONS, new Set(state.build.expressions), syncBuild);
        const background = backgroundRow();
        const order = element("div", {
            textContent: "Cells render top to bottom - the Results tab fills in that order.",
            className: "mmx-muted",
        }, { marginTop: "2px" });
        const shape = element("div", {
            textContent: "Cell shape comes from the node's cell_aspect (default 9:16, "
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
        actions.append(
            button("Build cells", () => {
                state.cells = plannedCells();
                state.build = ticks();
                persist();
                refresh();
                notify(`${state.cells.length} cell(s) built.`);
            }),
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
            const remove = button("✕", () => {
                state.cells.splice(index, 1);
                persist();
                refresh();
            });
            remove.classList.add("mmx-btn--icon", "mmx-btn--danger");
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
                selectBox(PICKS.map((key) => [key, key]), cell.pick || "auto", (value) => { cell.pick = value; persist(); }),
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
    const TAG_LABEL = { image: "Picture", video: "Video", audio: "Audio" };

    /** Every reference the RUN sends, as H3 tags (``<Picture 1>`` and friends). */
    function runRefTags() {
        return (mediaSlots(state.refs) || [])
            .filter((entry) => entry.active !== false)
            .map((entry) => `<${TAG_LABEL[entry.group.kind]} ${entry.ordinal}>`);
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
    function renderResults(sheet) {
        if (sheet !== undefined) lastSheet = sheet;
        results.replaceChildren();
        const shown = lastSheet;
        if (!shown || !Array.isArray(shown.cells) || !shown.cells.length) {
            results.append(element("div", {
                textContent: "Nothing rendered yet — queue the prompt to render the cells.",
                className: "mmx-muted",
            }));
            refreshTabs();
            return;
        }
        if (shown.sheetUrl) {
            results.append(element("img", { src: viewUrl(shown.sheetUrl), className: "mmx-sheet-preview" }, {
                maxWidth: "100%", border: "1px solid var(--mmx-line)", borderRadius: "6px", marginBottom: "4px",
            }));
        }
        results.append(element("div", {
            textContent: `${shown.counts?.rendered ?? 0}/${shown.counts?.cells ?? 0} cell(s) rendered · `
                + `${shown.counts?.frames ?? 0} frame(s) on disk · ${shown.dir || ""}`,
            className: "mmx-muted",
        }, { marginBottom: "4px" }));

        for (const cell of shown.cells) {
            const row = element("div", { className: "mmx-sheet-result-row" }, { marginBottom: "3px" });
            const caption = element("div", {
                textContent: `${cell.id} · ${cell.view || "?"}/${cell.pose || "?"}/${cell.expression || "?"} · `
                    + `picked ${cell.pickIndex ?? "-"} (${cell.pickMode || "auto"})`,
                className: "mmx-muted",
            });
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
                    border: index === cell.pickIndex ? "2px solid var(--mmx-accent)" : "1px solid var(--mmx-line)",
                    borderRadius: "4px",
                });
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
                    notify(`picking ${cell.id} frame ${index}…`);
                    try {
                        await hooks.pickFrame?.(cell.id, index);
                        notify(`${cell.id} → frame ${index}`);
                        await refreshResults();
                    } catch (error) {
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

    async function refreshResults() {
        try {
            const sheet = await hooks.listResults?.();
            renderResults(sheet ?? null);
        } catch (error) {
            notify(`results unavailable: ${error.message}`);
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
    }

    function dispose() {
        if (liveTimer) clearInterval(liveTimer);
        liveTimer = null;
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

    showTab("references");
    refresh();
    renderResults(null);
    return {
        container, status, results, refresh, renderResults, refreshResults, refreshTabs,
        refreshPlan, refreshSettings, syncSettings, renderHelp,
        autoRefresh: auto, openBrowse, openPreview, closeOverlay, showTab, setState, dispose,
        setRunning,
        get activeTab() { return activeTab; },
        get overlay() { return overlay; },
        get live() { return Boolean(liveTimer); },
        get promptBox() { return container.querySelector(".mmx-sheet-prompt"); },
        get negativeBox() { return container.querySelector(".mmx-sheet-negative"); },
        get knobFields() { return new Map(knobFields); },
        get knobs() { return knobGroups.flatMap((group) => group.knobs); },
        get compactKnobs() { return compactKnobs(state); },
    };
}

export const __internals = { optionRow, readChecks, selectBox, textInput };
