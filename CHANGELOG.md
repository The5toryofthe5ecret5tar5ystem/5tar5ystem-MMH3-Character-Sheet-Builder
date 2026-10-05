# Changelog

All notable changes to **5tar5ystem MMH3 Character Sheet Builder** are recorded here. This pack
follows [semantic versioning](https://semver.org/): the node type (`MiniMaxH3CharacterSheet`) and
the payload contract are what "breaking" refers to, not the panel's layout.

## [2.0.0] - 2026-10-05

**The visual and workflow overhaul.** A major bump, because both halves of the pack changed shape:
what a render *is*, and what the node looks like while you drive it.

1. **The whole sheet comes out of one H3 render, and that is the default.** Every panel used to be
   its own 22-frame clip, composed after the fact - four renders, four chances to lose the likeness.
   One pass draws the arrangement as a single image, and the panels are sliced back out so per-view
   consumers (the RefMod export, the picker, the Results tab) read it exactly like a per-cell sheet.
   The per-cell pass is unchanged and one knob away, for the sheets that want a render per panel.
2. **The panel is a studio, not a form.** The proposal the layout was built from (icon rail + stage +
   control column + pinned footer) is now the frame, not just the styling: card rails instead of
   dropdowns, glyph ticks instead of checkbox walls, a reference canvas with a paint surface, result
   cards and a filmstrip, a live-stream tab, and the settings drawn in the panel so the node can stay
   compact.
3. **The supporting passes that make it a workflow**: your own presets, the RefMod suite (one render
   feeding four boards), clip export, face/clip/audio blur with hand-painted areas, and backdrops.

*(The entries below were first written while the one-pass mode was called the draft pass. It is now
the **one-pass sheet** - `single_pass`, ON by default - and the panels are sliced back out of the
sheet so per-view consumers such as the RefMod export work without a second render. The old names
(`render.draft`, the widget `draft_sheet`, the sink `H3SheetDraftSink`) still read as what they
mean.)*

### Added

* **The resolution control**: three square buttons (1080p / 1440p / 4K) above the presets. One click
  sets TWO paired sizes - the sheet canvas a one-pass render draws and the cell size a per-cell
  render uses - and the readout beside them says which pair is set, or **Custom** when the sizes
  were typed by hand. A chosen size is honoured as-is (so 4K renders at 3264x2176, over the 3.6 MP
  guidance ceiling), while an unchosen one still respects it: the panel writes the choice into
  `render.resolution` and `one_pass.one_pass_budget` reads it.
* **Two preset axes.** `layout` presets say what to draw (Hero + 4 panels, Expressions 2x3,
  Turnaround 3-in-a-row - each with its cells and its cell shape) and `quality` presets say how to
  sample it (One-pass sheet (default), Per-cell renders (classic), Max identity fidelity). Two
  selectors, two records (`render.preset` / `render.layoutPreset`), and **no preset sets a size** -
  that is what makes the resolution control stick.
* Panel slicing is a first-class output now: the one-pass sink writes `cells/<id>.png` and
  `frames/<id>/f0000.png` per panel (letterboxed onto the batch, never stretched), so the Results
  tab, the picker path and the RefMod export all read a one-pass sheet the way they read a per-cell
  one.
* **Detail crops and the two closeup boards.** Five new views - **mouth**, **feet**, **breasts**,
  **groin** and **butt** - plus two mouth expressions, **tongue out** and **ahego** (eyes rolled up,
  tongue out, worded so it reads on a mouth-only crop as well as on a face). Two layout presets
  build them 2x2: *Closeups 2x2 (SFW)* (eyes, mouth, hands, feet) and *Closeups 2x2 (NSFW)*
  (breasts, groin, butt, mouth-ahego). Each crop is its own `close` camera distance - so a mouth
  cell can never chain onto a full-body one - and the body crops join the "no face in frame" set,
  which keeps an expression line out of a prompt that has no mouth in it.
* **A drift test for the panel's tick lists**: the views, poses and expressions the panel draws are
  compared against the backend's own keys, in both directions, so a vocabulary addition cannot land
  on one side only.
* **The RefMod suite** - a third preset kind, `suite`, and one preset (`refmod-suite`): **four
  sheets from one queue**. A suite is data (`render.suite` = an ordered list of LAYOUT preset ids),
  resolved by the new `h3_character_sheet/suite.py`: hero + 4 panels (5 cells), the 2x3 expression
  board (6), the SFW detail crops (4) and the NSFW ones (4). One queue press builds **one graph per
  board** (each in its own `GraphBuilder`, merged, so no two boards can share a sampler) and each
  board renders into `<output>/minimax_sheets/<run>/<board>/` as a complete sheet folder - frames,
  cells, picks, its own `report.txt` and `manifest.json` - with a `suite.json` in the run folder
  naming the boards, their labels and their cell counts. The quality axis (steps, seed, reference
  sizing, resolution chips, continuation, clip export) stays the run's, and the suite preset states
  its mode (`singlePass: true`: four one-pass renders, not 19 per-cell clips). Boards are layout
  presets **by id**, so a board cannot drift from the layout the panel offers on its own; an unknown
  or non-layout board is reported in the warnings rather than rendered as an empty sheet, and the
  run's own cell list is ignored while a suite is active. In the panel the suite rides the **Layout**
  selector (it answers *which sheets render*), so picking a single layout after it returns to one
  sheet, while switching the quality preset leaves it alone; `render.suite` round-trips through a
  saved workflow (list or `a,b,c` string, deduped, capped at `MAX_SUITE_BOARDS`).
* `H3SheetOnePassSink` and `H3SheetCellSink` take an optional **`board`** input, and
  `SheetStore(..., board=…)` nests a sheet inside the run - that is all "one run, four sheets"
  needed on the storage side.
* The suite attaches **one** preview wrapper for every board (attaching it per board would stack four
  step clocks on one model), and reports the boards in render order in the log and in `suite.json`.

* **The panel is visual now (batch 1 of the redesign).** Two dropdowns, a wall of checkboxes and a
  prose hint bar became pictures:
  * **Card rails replace both preset selects.** Every layout preset is a card carrying a wireframe
    of the cells it actually builds (hero + 4, a 2x3 grid, three in a row, a 2x2 closeup board) and
    a cell count; the quality presets are cards too, drawn as one frame or a filmstrip, and the
    suite card shows its four boards. Applying one is a click on the picture; the sentences that
    used to fill the hint bar are the card's tooltip, and the bar itself is one line of fact (*"One
    pass (default) · Hero + 4 panels — 5 cell(s)"*). Cards are built from each preset's own ticks,
    so a card cannot drift from what applying it does, and `PANEL_CSS` gained the primitives
    (`mmx-pcard`, `mmx-pcard__art`, `mmx-rail`, `mmx-glyph`, `mmx-badge`).
  * **Glyph ticks replace the framing and expression checkbox rows.** Twenty framings are twelve
    drawn marks (a figure, a figure from behind, a head in profile, eyes, a mouth, hands, feet,
    legs, a torso, a lower body, a rear) with the angle reusing the figure, and sixteen expressions
    are six faces - each glyph a picture with the short word under it and a REAL hidden checkbox
    behind it, so the payload, `readCells` and every test that reads `boxes` are unchanged. Poses
    stay words on purpose: they are names, not shapes.
  * A **live harness** ships with the pack (`web/mockups/panel-preview.html`): it mounts the real
    panel module outside ComfyUI with a fake wiring layer, which is how the CSS collision below was
    caught and how the panel can be reviewed without a render.
  * **Reference tiles say their state in badges**, not sentences. A picture's bottom-left corner is
    now a badge row: `blur auto` / `blur on` / `blur off` (the badge IS the control - click to
    cycle, tooltip for the full sentence, so it is no longer *"Blur auto + paint"* in text), `N
    painted` when areas have been painted out by hand (the object-removal feature, visible without
    opening anything), and - on a video - `no blur yet` in red, because a face blur applies to
    picture references only and a silent gap was the wrong way to say so. A video keeps its
    filename in that same row: `motion.mp4  no blur yet`.
  * **The References tab has a canvas.** Clicking a reference tile now LOADS it into a pane at the
    top of the tab instead of opening the file picker, and that pane mounts the same parts the
    Preview overlay has always used - the paint surface (brush/lasso, size, undo, clear, apply) and
    the original/blurred comparison bar - *on the picture* rather than in an editor beside it. One
    builder (`previewParts`) feeds both, so the two cannot drift. The loaded tile is ringed
    (`.is-canvas`), changing a file moved to a **Replace...** button on the pane's head (where there
    is room for a word), and an empty grid says what the canvas is for. Inline, the picture takes
    52% of the pane's height so the tiles stay visible below it; the overlay keeps the whole pane.
  * **The Results tab leads with the sheet.** The sheet preview moved into the same kind of card the
    reference canvas uses: a head with the file name and an **Open** link, the sheet at the chosen
    *Panel preview* size, and a **filmstrip** underneath - one tile per cell, in cell order, each
    showing the frame the sheet actually uses (the cell's pick, not frame 0). Clicking a filmstrip
    tile scrolls to that cell's row and flashes it. The per-cell rows are untouched.
  * **The Settings tab is switches and short labels.** Every `toggle` knob (one-pass mode, keep
    frames, clip export, verbose log, blurring a reference...) is drawn as a **switch** instead of a
    bare checkbox - the checkbox is still the half that carries the value, and the CSS lights a
    sibling track with `input:checked + .mmx-switch`, so nothing is repainted to show a state. The
    *Compact node* checkbox in the header is a switch too. Knob **hints** stopped being a paragraph
    per field: a hint of `HINT_INLINE_LIMIT` (24) characters or fewer is printed under its control,
    a longer one is the control's tooltip - which is where every hint now lives as well. The
    "N knobs..." line under the header is one clause, with the reasoning behind it on hover.
  * **A bounded number is also a slider.** Any knob whose schema supplies a real `min` **and** `max`
    (cell size, steps, frames per cell, sheet edge) is drawn as a `<input type=range>` beside its
    box, sharing the schema's `step`, with the two moving together in both directions: a drag writes
    the box and commits it, a typed value clamps and moves the slider. The box stays the control -
    it is typable and it is the half that clamps - so this is additive, and a range that is not
    worth dragging gets no slider: four stops is not a range, and neither is one finer than 400
    steps. `numberSlider()` is exported and unit-tested on its own rule, not only through a fixture
    knob.
  * **Each group header carries its field count** (`Render · 4`) instead of another sentence. The
    tab's own size line is now `N knob(s) · 3 columns` and moved its reasoning to `title`, which
    was the last paragraph left on the tab.
* **The panel's FRAME is the proposal now, not just its contents.** The redesign's first pass
  restyled what was inside the six tabs and left the frame alone - a horizontal strip of words
  under the header and one full-width column - which is why the panel still looked nothing like the
  studio in the proposals. What changed:
  * **An icon rail.** The six tabs are 32px icon buttons in a column on the left (`RAIL_ICONS` +
    `railIcon()`, 24-grid line art that inherits the theme's colour), with the working area beside
    them in a `.mmx-shell` / `.mmx-body` pair. The count each tab used to spell out is a badge on
    the icon (`setTabCount`), the word is the tooltip, and the live strip moved into the body with
    the panes - it is content, and beside the rail it would have been an inch wide.
  * **The header is one line**: name + a status chip saying what will be drawn and at what size
    (`Hero + 4 panels · 1080p`, from the lit size card). The build tag moved into the title's
    tooltip instead of sitting next to the panel's name as a bare string.
  * **Sizes are cards.** Each of the three resolutions carries its own numbers (`1080p`,
    `1088px sheet`, `1024px cells`), so the price of 4K is legible without hovering.
  * **The References tab is a two-column studio**: stage left, tile wall right, head across the
    top - one `grid-template-areas` on the card that already owned it (a second rule with its own
    `display` would have lost the cascade to the flex rule further down the sheet). Under 700px of
    *container* width it folds back to one column, which is a container query because the panel's
    width is the node's width and nothing else knows it.
  * The paint surface now measures the STAGE for its width (that column, not the whole pane - the
    picture was being scaled for a width it did not have and overflowed its column into a
    thousand-pixel card) and caps the stage at three quarters of its own width, so a tall node
    cannot stretch the preview into an unreadable skin. The reference box's height FLOOR moved from
    an inline style into the stylesheet so the studio's tile column can raise it (178px → 320px).
* **The last two pieces of the proposal's studio: the footer bar and real card art.**
  * **A pinned footer.** The status line moved into a `.mmx-actionbar` at the bottom of the panel
    with **Rebuild sheet**, **Refresh** and a primary **Render** button, sticky to the bottom while
    the active pane scrolls. Render calls ComfyUI's own queue through a new wiring hook
    (`app.queuePrompt(0, 1)`) rather than a second renderer - and with no queue available (the
    standalone harness, the jsdom suite) the button is DISABLED with its reason in the tooltip
    instead of throwing when pressed. Rebuild/Refresh moved out of the header, which is now just
    the name and the status chip.
  * **Card art is your own last render** (the proposal's "phase 2"). `sheet_store.gallery_art()`
    reads the newest sheet folders, takes each manifest's `render.layoutPreset` (and every board a
    **suite** drew, because the page a suite rendered IS what each board looks like) and returns
    `/view` URLs, served through a new `gallery` action. The panel asks once, after the presets
    load, and a card with a render gets `.has-art` + `--mmx-card-art` (the rule the rails shipped
    with) plus a `yours` badge naming the run; a layout with no render keeps the drawn
    arrangement. The art is derived data - it never enters the payload - and the rails are
    REBUILT on arrival (`renderPresetRails` only moves the `is-active` ring, so it could not have
    added a background).
* **Two dead-space bugs the frame work exposed** (both visible in a screenshot, neither in jsdom):
  the preset hint line kept a row-era `flex: 1 1 240px` after the presets row became a COLUMN, so it
  rendered as a 240px band of nothing in the middle of the panel; and the panel's grid card had two
  competing `display` rules. Both pinned by tests now - along with the rail's icon/badge/tooltip
  contract, the size cards' three lines, the studio's grid areas, and the stylesheet floor.
* **Fixed a real crash the redesign exposed** (found in the browser, not in jsdom): the paint
  surface is *built* before it is mounted, and `sync()` measured the pane anyway - so a picture the
  browser already had cached (which completes synchronously) hit
  `getComputedStyle(null)` and threw, leaving the preview blank. `sync()` now bails out when the
  frame has no parent and relies on the deferred pass it already scheduled. jsdom could not see
  this: its images never report `complete`, so the immediate path never ran there.
  * **The panel's own prose is short on screen and long on hover.** New `mutedHint()` helper; the
    four paragraphs it replaced were the last text-heavy thing left after the rails and the glyphs:
    the reference box's "drop files anywhere" note, the prompt card's role explanation, the two
    notes under the Cells tab (render order, cell shape) and the tick plan (now "N cell(s) from the
    ticks" with the id list in the tooltip instead of twenty ids in a row). The Settings tab was
    already in this shape - switches for toggles, hints as tooltips with only the short ones inline
    (`HINT_INLINE_LIMIT`) - so it needed the least work: its group headers now carry a field count
    and every bounded number grew a slider.
* Fixed on the way: the new card styles first reused the class name `mmx-card`, which the Cells tab
  already used as its container - the new rules won and squeezed the glyph rows into one column.
  The redesign's classes are `mmx-pcard*`; the panel's own `mmx-card` is untouched.
* **Reference CLIPS are blurred too** (batch 2 of the redesign: "faces, objects, audio and video").
  `face_blur.blur_video_faces` is the picture pass repeated over time, with the one problem a still
  does not have - the face moves. Detection is **sampled** (`VIDEO_SAMPLES` = 12 frames, ends
  included) and every frame in between is *measured*: the box is interpolated between the two
  nearest detections and then re-detected inside a window around that prediction
  (`TRACK_SEARCH` / `_refine_box`), with the prediction standing when the model finds nothing in the
  window. The gap between samples is capped (`VIDEO_MAX_GAP` = 30 frames) and a longer clip gets
  **more samples** rather than a longer guess - a first pass at `ceil(total / gap)` produced gaps one
  frame over the cap (899 frames over 30 samples is 29 gaps of 31), which the sampling test caught and
  the fix (`(total - 1) / gap + 1`) pins.
  * The derived clip is written beside the other copies as `<name>-blurface-<key>.mp4`, at the
    source's own size and rate, and **its audio track is copied across** (`ffmpeg -c:a copy`, found
    through `imageio_ffmpeg` or `PATH`) - H3 reads a clip reference's sound as well as its pictures,
    so only the pixels may change. No ffmpeg means the clip is still written, and the note says
    `audio not carried`.
  * `CLIP_SUFFIXES` / `is_clip_name()` decide which pass runs; the preview route takes the panel's
    `kind` and falls back to the suffix, so a bare request (or an older panel) still blurs a clip as
    a clip. `BLUR_KINDS` is now `("picture", "video")`, so a clip is blurred by the **auto** rule too
    (a second person in an outfit clip goes) while the clip that IS the identity source stays
    protected - which matters more for clips than for pictures, since an H3 run whose motion comes
    from a clip usually takes its likeness from it. Audio keeps the honest `unsupported` answer: a
    voice has no pixels for a blur to remove.
  * In the panel a clip tile carries the **same** blur badge a picture has (filename kept beside it),
    the canvas mounts the **same** paint surface over the player and the **same** Original/Blurred
    bar, and the request names the kind so the route runs the clip pass. `mountPaintSurface` measures
    `videoWidth`/`videoHeight` and waits for `loadedmetadata` (a clip has no `load`), and the
    aspect-ratio reader no longer pairs `naturalWidth` with `videoHeight` - which had been
    remembering `undefined` for every clip tile.
  * **A sound reference is MUTED, not blurred** (the third kind of the same ask). A voice has no
    pixels, so the removal is the whole sound: `face_blur.mute_audio` writes `<name>-blurface-
    <key>.wav` with the source's own rate, length and channel count and no voice in it - silence,
    not a dropped track, because a file with its audio stream removed is one `LoadAudio` refuses
    (`-af volume=0`, with a pure-Python `wave` fallback for a `.wav` and a named reason for
    anything else without ffmpeg).
    * `auto` **keeps** a voice, which is where the sound rule deliberately parts from the picture
      rule: a face in a photo leaks an identity nobody asked for, while a sound reference is put
      there on purpose and is usually the performance itself - so `on` is what mutes. The badge
      says `mute auto` / `mute on` / `mute off` (not "blur"), a sound keeps its filename in the
      badge row (that row replaced the caption a thumbnail-less tile used to have), the canvas
      gives it the same Original/Muted bar over the player, and the plan report names a muted
      reference as `<Audio n>` so it is visible before a render. Painting a sound stays
      `unsupported` rather than being quietly dropped.
  * Painting a clip is **held across every frame**: one mark on the frame the tile shows, applied to
    the whole clip, which is what a logo, a watermark or a tattoo on a clip with steady framing
    needs. Per-frame masks for a performer who moves around are not what one painting is, and the
    README says so.

* **Draft pass** (`draft_sheet`, off by default; the *Draft pass (one render, whole sheet)*
  preset): ONE H3 clip for the whole sheet at H3's 5-frame minimum, first frame kept as the sheet
  image. The prompt folds the cell prompts into one - the identity block, the reference legend,
  the per-reference ownership rules, the identity reminder and the negative stay once, and each
  cell contributes one `Panel N of M (x=…, y=…, WxH): …` line in the cells' own words. The canvas
  is the sheet's own layout snapped up to a 32px grid and scaled to fit a 3.6 MP single-pass
  budget. ~1/20th of the sampling, and the panels agree by construction because one sampling
  context draws them all. Writes the still to the sheet's own image file, keeps every frame of the
  clip under `draft/`, records a `draft` block in the manifest, streams the panel's own live
  preview (marked `whole_sheet`, so the strip labels it as the sheet and its per-cell re-roll
  button stands down), and reports the trade in `report.txt`.
* `sheet_spec.build_sheet_prompt()` with `cell_shot_lines()` / `cell_closing_lines()`: the panel
  vocabulary now has ONE definition, shared by a cell prompt and the draft's sheet prompt, so the
  two can never disagree about what "left profile" means. `attributes_hidden_by_all()` hides an
  attribute only when no panel in the run can show it.
* `layout_rects(..., canvas=…)` and `draft_sheet.py` (`draft_plan` is pure data: size, frames,
  prompt, panel rects, notes).
* `H3SheetDraftSink` (internal): turns the one clip into the still, the kept frames and the
  manifest block.
* The sheet's `report.txt` now carries the builder's own lines - reference blurs, the preview
  switches, draft mode - through the payload (`SheetSpec.notes`).

### Fixed

* **The node's `report` output is the report again.** The builder appended its blur and preview
  lines to the *graph link* rather than to a string, so the STRING output held a formatted Python
  list repr (`"['0.0.0.sheet_grid', 2]\n\n…"`) instead of what `report.txt` says. The extra lines
  now travel in the payload and the output is the compositor's own report.
* Composing over a draft (the panel's *Rebuild*, a pick) no longer writes a canvas of empty cells
  over the draft still: there are no cell frames to compose, so the still is left alone and the
  answer says `draft`.

* **A side or back panel no longer invents the hairstyle.** The 90-degree profile came back wearing
  the *second* reference's hair - a front-facing identity picture says nothing about the side of a
  head, and the outfit reference (a whole other person, with their own dark hair) was right there
  with a plausible answer; every angle the identity picture *does* cover kept its braids. The views
  that have to invent the head - 90-degree profile, 135-degree back, from behind, the back-of-head
  crop - now carry one sentence of their own: "the hairstyle does not change with the camera: the
  same parting, the same length, the same colour and the same style as the reference picture, seen
  from the side - do not give the subject a different hairstyle because this view is a new angle."
  The sentence names the angle the panel is drawn from, appears only when a picture or clip is
  actually wired, and never appears on the views whose partings, lengths and colours the reference
  already shows.
* **The other-picture ban names hair.** It read "must not supply a face, a hairstyle, skin tone or
  facial features"; a second reference's *hair colour and length* is exactly what leaked into the
  profile, so the ban now says "a face, a hairstyle, hair colour, hair length, skin tone or facial
  features - the person visible in it is not the identity, do not copy their face or their hair".
* **The layout cards keep their drawn cells.** Card art (your own last render of each sheet) was on
  by default, which is backwards: the drawing is the card's answer to "which sheet, and how many
  cells", and a photo of a render replaces exactly that - a card already wearing a render also hid
  the cells it was about to draw. It is **off** by default now, with a **your renders** switch in the
  Sheets head to turn it back on.
* **A one-pass sheet is no longer painted into panel 1.** The whole sheet arrives as one frame and
  the stream reports `cell: 0`, so the box for the first panel wore it - five panels inside cell one,
  still there after the run. A one-pass (whole-sheet) stream now stays in the live strip and on the
  **Preview** tab where it belongs; a per-cell stream still marks its own panel, because that panel
  *is* the cell being drawn.

### Changed

* **The timing table leads with the default render.** A `4K` one-pass sheet (2048px cells, 3264 x 2176)
  takes **160-170 s** on an RTX 5090 at 8 steps, measured, and it is the first row now; the per-cell
  figures (Balanced 81 s, Fidelity 378 s for five cells at 22 frames) follow as the classic pass, with
  the reason for the gap named (a frame picker, per-cell clips and latent continuation). The
  resolution table's modelled token counts stay modelled, and now say which single number is measured.
* **The README's image set is the 2.0 one.** The headline is a `4K` one-pass render of the
  `Hero + 4 panels` layout (3264 x 2176, one 5-frame H3 pass) in place of the three 1.x sheet shots,
  followed by the Cells tab (layout cards, framing glyphs, resolution cards, the mode row) and the
  References tab mid-paint, both on a real graph with the RefMod export and the sheet it writes. The
  six pre-redesign images are no longer referenced by the README and stay in `images/` for the 1.1.0
  post.
* **`docs/civitai-post-2.0.md`** is a new post written for this version, covering only 2.0: one render
  per sheet, the panel, the prompt, what each mode gives up, the resolutions and their token costs,
  the blur passes, clips and continuation, the output folder, presets and the suite, the RefMod export,
  install, the model files, a first sheet, and the upgrade note. `docs/civitai-post.md` (1.1.0) is kept.
* The `v2.0.0` release carries the two example workflows as assets
  (`5tar5ystem.MMH3.Character.Sheet.Builder.json` and the `+ RefMod` one), so the post's direct
  download links resolve without a GitHub account.
* The README's screenshot gallery is the 2.0 panel: the **Cells** tab (layout cards, framing glyphs,
  the resolution cards, the mode row) and the **References** tab mid-paint, both on a real graph with
  the RefMod export and the sheet it writes. The earlier panel shots (`panel-references.png`,
  `panel-live-preview.png`, `panel-face-blur.png`) show the pre-redesign frame and are no longer used.
* Every preset states the draft flag explicitly, so applying a normal preset after *Draft pass*
  leaves draft mode - the `deviates` list on each preset records it.
* `tests/test_user_presets.py` derives the built-in preset count instead of hardcoding it.
* Both shipped example workflows carry the new widget's value, so they open with the draft off.
* **The panel's frame is proposal B's, structurally.** The header is one line (the panel's name and
  the size chip) with **no buttons** - Browse / Add Media / Clear moved into the references card's
  head and the sheet-folder actions into the control column's foot, so the primary action is pinned
  where B pins it instead of on a full-width strip the proposal does not have.
* **The Cells tab's stage is the sheet.** One box per cell in the arrangement the picked layout
  gives (drawn with the same `artShape` the layout cards use), each box naming its framing, the
  vocabulary scrolling underneath, and the cell being rendered wearing the live frame - B's "the
  sheet appears here as it denoises" instead of a paragraph of cell ids.

* **The control column is tab-scoped, like the mockup.** The Sheets tile wall, the sizes and the
  mode segment (with the mini reference avatars) live on the tab that decides the sheet; the
  References tab's column is the reference list; the other tabs show a read-out
  of what the sheet is and a link back. The first pass pinned the sheet block to every tab.
* **The reference stage shows the picture you are working on**, at the size its column allows, with
  the blur area named under it (the Original/Blurred buttons drive that picture, which is the one
  you paint on), and the paint tools sit directly under it.
* **The blur area is chips under the picture** (B' draws it there) instead of a dropdown in the
  reference list's header, and that header now states what the list holds ("3 pictures · 1 video").

* **The panel's frame, second pass (visual fidelity).** The stage and the control column are now
  **equal halves** on every tab (a wide stage beside a 336px strip made the right column read as an
  afterthought), a new node opens at **1080×700** so those halves are visible without scrolling,
  and the numeral badges are gone from the rail (icons and tooltips only).
* **The live stream is its own tab.** Frames arrive on **Preview** at stage size, and that tab's
  icon lights in the accent colour and **pulses** while a run is working (CSS-only: one class, one
  animation, standing down under `prefers-reduced-motion`). The stream no longer takes a row from
  every tab.
* **The references tab splits by kind of work**: picture + tools in the stage half, reference list +
  identity brief in the column half.
* **Fixed: a picture measured while its tab was hidden kept the guess.** A tab switch does not
  resize the panel, so no ResizeObserver fires, and a surface measured with a hidden pane fell back
  to the image's natural size (a picture taller than its own half). Every `paint` surface now
  registers its `sync`, and a tab switch re-measures them one frame later. Also fixed: the inline
  canvas's `inlineHeightShare` was never read (the surface looked for `heightShare`), so the picture
  ignored its height budget.

* **Per-panel drag and drop.** The tick rows are the sheet's default; every stage panel is now a
  drop target, so one panel can take its own **framing**, **pose**, **expression** or **face
  reference** without touching the other panels. A panel that differs is marked with a **×** that
  puts it back on the ticks. `SheetCell` gained `face_ref` (`"pictures:1"`), whose reference is
  promoted to `<Picture 1>` for that cell, given the face attribute, and protected from the
  automatic face blur (a blurred copy cannot supply a face) - with the tile's own "always blur"
  still winning, because that is the more explicit instruction about those pixels.
* **The resolution row lost its label.** "Resolution" plus a 96px gap was a third of the row; the
  three cards say what they are.
* **"Rebuild sheet" is now "Re-compose"**, with a tooltip saying what it is for. The render already
  writes the sheet at the end of a run (the sink composes it from the frames), and a pick
  re-composes it too; this is the no-re-render path for the changes that only affect the layout,
  the captions or the backdrop.

* **Fixed: the two columns collapsed into one below ~900px.** The responsive rule that stacks the
  halves on a narrow node lived in a container query that measured `.mmx-shell` **from** the shell
  itself - and a container cannot answer its own query, so the `flex-wrap: wrap` half of it never
  applied while the column's `flex: 1 1 100%` (a descendant rule, which did apply) gave the column
  the whole width and starved the stage to zero pixels: a single column with the picture gone. The
  query container is now the PANEL, the stack rule changes the wrap and both halves together, both
  halves have a 240px floor so neither can be starved, and the stack only fires below 640px (where
  two columns genuinely stop working). Verified at 1080/900/820/700/640/560px.
* The panel is `position: relative`, so an overlay (a preview, the folder browser) covers the
  panel rather than whatever positioned ancestor it happened to find.

* **The ticks own the panel list again.** `state.cells` was materialised once (by a per-panel drop,
  *Use these cells*, or a saved workflow) and then ignored the ticks, so unticking *back* left its
  panel on the stage and ticking *Back of head* never appeared. Every tick change now rebuilds the
  list from the ticks - in the arrangement's own order - and re-applies the panels the user edited
  by hand, so a dropped pose, face or expression survives a re-tick instead of being thrown away.
* **The reference stage is one picture, not three.** The before/after pair under the canvas (two
  thumbnails of the picture already on screen) is gone: the Original/Blurred buttons switch that one
  picture and the sentence beside them says which one is on screen, so the pair bought nothing and
  cost a third of the column's height. The picture's height budget went from `0.72` of the pane to
  `0.78`, and its column bound from three quarters of the column's width to the full width, which at
  1080×664 measures **284×379** where it was **197×263**.
* **The badge legend card is gone.** The rows under the tile wall explaining `blur auto` / `blur on`
  / `mute auto` / `N painted` restated what the tiles' own badges and tooltips say; the tile wall
  keeps the height instead.
* **The node has a floor of 760×620** as well as its 1080×700 default. The two columns stack under
  640px of panel and the node is 20px wider than its panel, so 760 is the first width where a
  column still has the ~356px the tile wall needs (at 700 the columns were 306px); `onResize` now
  clamps the size up to the floor (raising only - dragging a larger node is left alone), chaining
  the frontend's own handler.

* **The five read-out tabs have no control column.** Prompt, Results, Preview, Settings and Help
  gave half the panel to a "This sheet" read-out - a wide empty box beside the thing the user came
  to read. The column is now a property of the two tabs that DECIDE (`COLUMN_TABS`: Cells,
  References), so those five render at the panel's full width (measured 506px → **1020px** at a
  1080px node) and the read-out card goes with it. The pinned action bar is no longer inside the
  column: it is the **panel's** footer, so Render stays in one place on every tab.
* **The accent is the proposal's orange.** The panel took ComfyUI's `--p-primary-color`, which is
  blue, so **Render** was blue where proposal B draws it orange. It is now pinned to the mockup's
  `#ffb347` (with `#17171c` ink on it, like the mockup's own primary button) and the mockup's blue
  is left where the mockup uses it - as the second colour that rings a hand-picked frame.
* **One pass is lit out of the box.** A fresh node renders one-pass (the `single_pass` widget's own
  default) and no preset has been chosen, so the mode segment used to show nothing at all - which
  reads as "unknown" rather than as the default. The segment is now lit from the node's own knob
  when the panel has no preset of its own (`litModeId`), and a preset the user picked still wins.
* **The mode row fits.** Three mode names plus the steps chip is wider than the column at the
  node's narrow end, and the whole segment used to overflow it - the steps chip was the part that
  fell off the side of the node. The buttons may now shrink (10px, 6px padding) and the row may
  wrap, so the chip is always visible.
* **A wider node no longer makes the sheet cards taller.** Their art was a `3:2` box, so growing
  the node grew every card and pushed the size cards and the mode row down and out of the column
  (the reported "the sheets grow and block the resolution pickers"). In the column the art is a
  **fixed 62px** with the ratio turned off: measured, the wall is 359px tall at 900, 1080 and
  1440px where it used to grow, and every row stays inside the column.
* **The one-pass sheet prompt says the layout in words, and is written in H3's own sections.**
  A one-pass sheet is a single render that has to hold every panel, and pixel boxes alone were not
  enough: a hero + 4 sheet came back as *three* full-height columns with two panels missing. The
  prompt now (a) describes the arrangement the way a person would - "5 panels in 3 columns of equal
  width - the left column holds one tall panel that fills the full height; the middle column holds
  two panels stacked one above the other; ..." - (b) puts every panel's own place next to its box
  ("the middle column, upper half; x=1101, y=24, 1061x1034"), (c) says the panels are all drawn and
  none is merged, dropped, reordered or stretched, (d) asks for one common figure scale and ground
  line across the full-body panels, and (e) says the sheet is a *still*: complete in the first frame
  and unchanged to the last, so H3's clip frames cannot drift into a turntable. The prompt is now
  shaped like an H3 caption (`subject_definitions` / `summary` / `retention_analysis` /
  `detailed_description` / `overall_soundscape` / `non_diegetic_music`) - the structure the model is
  trained on and that the pack's own chains already use - and names the silent audio branch, since a
  sheet has nothing to say.
* **The identity picture's outfit is named as replaced.** "The clothing comes only from `<Picture 2>`"
  was not enough: a reference has no per-picture weight and the identity picture is usually a whole
  person wearing something, so a run with a low-cut dress in `<Picture 1>` kept rendering that dress
  even with `<Picture 2>` owning the clothing. When another reference owns the clothing, the prompt
  now also says "The person in `<Picture 1>` is wearing something else: that outfit is replaced ...
  do not mix the two garments."

## [1.2.3] - 2026-10-04

Chained turnarounds work as they always did, and the plan now names the one input that makes
them work - a reference that shows the body. A profile cell also stops being told to look away
and to hold eye contact in the same breath.

### Changed

* **`auto` chaining is back to "same camera distance", and the real cause of a frontal
  turnaround is now reported instead of guessed at.** An earlier note in this section claimed
  chaining front -> profile -> back was simply the wrong rule. It is not: that chain is *how a
  turnaround animates its turn* - the cell spends its first frames turning and settles by
  roughly frame 8 of 22, which is why the frame picker only ranks the settled tail - and three
  sheets rendered exactly that way with `continuity: auto`.
  What separates those from the failing ones is visible in the sheets' own embedded workflows:
  each chained turnaround that worked carried a reference whose role names the outfit or the
  body ("body and clothes", "body and bikini", "Dress, clothing"), while the failing run had a
  single `"face, hair, skin"` bust - nothing the model can re-pose the body from, so the
  hand-over's posture won and every full-body cell kept the angle it was handed. The rule is
  restored (`sheet_spec.continuation_keeps_scale`, one rule for the graph builder, the picker
  and the report), and the plan/report now names the failing combination instead of changing
  the plan quietly:

  > cell c3-profile: continues from a different angle (front -> profile) and no reference of its
  > own supplies the outfit or the body - the hand-over keeps the angle it was handed ... Add a
  > picture whose role names the body or the outfit, or set this cell's continuation to off.

  The turnaround preset keeps `auto` (it is the preset that most wants a chain) and its hint now
  says a body/outfit reference is what makes it work.

### Fixed

* **An expression that asks for eye contact is no longer used where the framing says there is
  none.** The smile option reads "Warm smile, eyes engaged."; on a `profile` cell that landed
  directly after the frame text's "gaze away from the camera, no eye contact with the viewer" -
  a contradiction the model resolved by turning the body back to the lens (no proven-good run
  used a non-neutral expression on a profile cell, so nothing that worked is affected).
  Expressions now carry an `aside` (the same expression without the gaze clause, e.g. "Warm
  smile.") and it is used exactly for the views whose own text forbids eye contact
  (`NO_EYE_CONTACT_VIEWS`, read from the view table so the two cannot drift apart). Face,
  portrait and frontal cells keep the full text.

## [1.2.2] - 2026-10-04

A sheet node keeps the size you give it: the automatic height fit is gone, so neither a page
refresh nor a tab switch can move the node any more.

### Changed

* **The node no longer resizes itself. The size you drag it to is the size it keeps.** The pack
  used to measure the panel after every change and snap the node to the height its content
  wanted, which meant your size was thrown away on a page refresh (reproduced live: a node
  dragged 260px taller came back at its content height the moment the workflow was configured)
  and on every panel re-layout - switching a tab was enough, and 1.2.1's tile geometry changed
  the content height, so it snapped to a *new* height rather than the one you set. That fit is
  gone, together with everything that could ask for it: the load/refresh pass, the panel's own
  `layoutChanged` report, the preview-cap passes, a preset being applied and the knob rows
  being hidden. The node opens at the size the workflow saved. The panel fills whatever box it
  is given (the reference tiles scale into it) and the active pane scrolls when its content
  needs more room, so a fixed node size has somewhere to put a long Results list.

### Fixed

* **A squeezed panel width is repaired without touching the node's size at all.** The frontend
  can write a squeezed inline width onto the DOM widget's wrapper (measured: an 880px node's
  wrapper at 345px); putting it back is now strictly a width correction - the only thing this
  pack writes is the wrapper's box, never `node.size`.

## [1.2.1] - 2026-10-04

Reference videos reach the RefMod bundle (as motion and as sound), the export expands date and
seed placeholders in its own name, and the panel no longer accepts a squeezed width from the
frontend.

### Added

* **Reference videos become a motion member in the RefMod bundle.** A video is the only
  thing in a sheet that carries *motion*, and until now the export ignored it completely:
  it called their `Create H3 RefMod` with `refs_image` only, so a sheet built from
  reference videos shipped as stills. `video_frames` (default 16) is how many
  **consecutive** frames each reference video contributes as `<name>_videos`, taken from
  `video_start`; the count is snapped to H3's causal grid (4k+1, so 16 -> 13 frames = a
  ~0.5s window) *before* the read, because a count off the grid makes their extractor
  re-sample the batch apart and a movement becomes a flipbook. Frames are decoded by
  ComfyUI's own video code (`InputImpl.VideoFromFile`) reading only the window asked for,
  shrunk to `ref_resolution` before the encode, and are tagged `pose_motion` whatever the
  appearance members are tagged. 0 turns the member off. `video_frames` and `video_start`
  are appended **last** and optional, so an already-saved workflow's widget values keep
  lining up.
* **The report gives the motion member its rows and flags one that hit `max_tokens`** (their
  extractor drops frames to fit). Motion is by far the costliest member per second, and the
  cost steps rather than climbs because H3 packs 5 latent frames per 17 pixel frames: measured
  on a 16:9 reference video, 13 frames at `ref_resolution` 512 is **896 rows** (2 latent
  frames) and the same window at 1152 is 4,608.
* **A reference video's soundtrack is now a voice source.** H3's own ref2va node pairs a
  reference video with its own audio slot (`ref_video_audios.ref_video_audio_N`), so the
  sound the sheet was conditioned on came from those files too - the voice ladder now walks
  *reference audio -> reference-video soundtracks -> cell clips -> connected audio* and
  names the member after what it used (`<name>_voice_videos`). A video with no audio track
  is skipped rather than treated as an error, and whatever the ladder passed over is named
  in the report.

### Changed

* **Audio reference tiles are square, not wide bars.** An audio reference has no shape of its
  own, so its tile took a 5:2 letterbox: a wide rectangle with one note glyph floating in the
  middle and the filename in a mostly empty strip, which read as a different kind of object
  beside the square pictures and stretched the grid. `tileAspect` now answers 1:1 for audio, so
  pictures and audios share one footprint and only video keeps a wide box - and a measured
  thumbnail still wins over any default. Panel-only change: hard-refresh (Ctrl+Shift+R).
* **A tile can no longer be narrower than 9:16.** The aspect clamp allowed a very tall photo
  down to 0.38, which made a tile narrower than a phone portrait - and at that width the tile's
  own chrome overlaps itself: the kind chip and the enable checkbox share the 4px top strip with
  the hover buttons, which are 18px wide. The floor is now `9/16` (`MIN_TILE_ASPECT`), so a
  taller-than-portrait reference letterboxes inside a portrait tile instead of squeezing the
  buttons on top of each other.

### Fixed

* **A squeezed panel is widened back to its node.** ComfyUI's frontend re-measures a DOM
  widget on selection and can write a *squeezed* inline width onto its wrapper - measured live
  on this build: an 880px node's wrapper came back at `width: 345px`, which compressed the
  whole panel to about a third of the node and the **Browse overlay** with it (that overlay is
  `position: absolute; inset: 0` of the panel, so it is never wider than the panel is). Nothing
  inside the panel can win against a `width` on the wrapper, so the repair is on the wrapper:
  `enforceWidgetWidth` re-asserts `node.size[0] - 20` (the invariant, measured at several
  sizes) from the node's draw pass, from the preview keeper for a node that is not being drawn,
  and from the height fit - which needs it first, because a narrow panel measures *taller*
  content. It only ever grows the wrapper and only writes when the number is wrong, so a frame
  costs one `parseFloat`.
* **`H3 Sheet → RefMod` expands `%date:...%` and `%seed%` in its `name`, like the Builder.**
  A name typed as `hero-%date:hhmmss%` was written to disk with the placeholder still in it
  (`hero-%date:hhmmss%.safetensors`), because the export passed the widget straight to their
  `save_bundle`. It now goes through the same `expand_tokens` the sheet node uses on
  `output_name`, once per export - and `%seed%` is expanded with the seed the sheet was
  rendered with (read from the manifest of the folder being exported, since that is the only
  place it is recorded). A name with no placeholder is untouched: no auto stamp, because a
  bundle is a file you name on purpose. Characters a file name may not carry on every
  filesystem (`%date:HH:mm%` asks for a colon) are transliterated rather than trusted.

## [1.2.0] - 2026-10-04

The voice member of a RefMod export now defaults to the voice the sheet was *built from*,
and the report says how much of the model's attention each member actually gets - the two
answers to "why does my voice reference do nothing?".

### Changed

* **`H3 Sheet → RefMod`: the voice comes from the sheet's own reference audio by default.**
  `voice_cell = -1` used to mean "the first cell that exported a clip", which made the
  bundle's voice the ~1s H3 generated for that one take; it is now a ladder - the sheet's
  **own reference audio** (the WAV in the Builder's References tab, recorded in the
  manifest's `spec.refs.audios`), else **every exported cell clip joined into one
  waveform**, else a connected `AUDIO`. `voice_cell = 0` still means "no sheet audio, use
  the connected clip", and `n` still forces the nth cell's clip (`<name>_voice_cellN`).
  The joined clips are one member (`<name>_voice_cells`) because the encoder takes a single
  waveform: clips are resampled to H3's 32 kHz and concatenated as samples, so the latent
  clock never cuts mid-frame. A manifest row whose file is gone is reported and skipped
  rather than failing the export, and the report names whatever the ladder passed over so
  the override is discoverable.
* **`voice_seconds` is documented as what it is: a ceiling, not a target.** A clip longer
  than the cap is truncated (from the front), never refused - and a *short* reference is the
  usual reason a bundle feels inert.

### Added

* **The export report gives every member its share of the bundle, and says what to do
  about a thin voice.** Rows are what a reference is worth: everything in a bundle is
  packed into one sequence the model attends over, and the video being generated adds its
  own rows on top of the bundle's. A measured 0.95s voice member is 76 rows next to the
  appearance members' thousands - **0.5% of the whole sequence** - which is why an A/B of
  *voice 1.0* against *voice 0.0* on a real bundle came out at noise level. Each member
  line now ends with its share of the bundle, and when the voice is under 2% the report
  names the `copies` count on *Load H3 RefMods* that would put it on the map (`copies 3`
  on a 0.5% member = 1.6%), or says so when even ten copies would stay thin.

## [1.1.0] - 2026-10-03

RefMods: a finished sheet can now be exported as one, appearance and voice together, and both
shipped workflows do it in a single queue.

### Changed

* **Cell shape now defaults to 3:4, not 9:16** - in the node, in *Balanced (recommended)* and
  in both *Full Character Sheet* presets. At the default 1024px short edge that is **768x1024**
  instead of 576x1024: a standing figure still fits head to toe, but the arms and a little of the
  surroundings stay in frame, where the phone-shaped cell was cropping them. `CELL_ASPECTS` lists
  3:4 first, the *Expression sheet* preset inherits the default instead of declaring its own, and
  the shipped example workflow was updated to match. Per-cell `aspect` still overrides it, so a
  cell that wants 9:16 keeps 9:16.

### Added

* **A second shipped workflow: `... Builder + RefMod.json`.** The same graph as the first example
  with the export node appended, wired to the sheet's `cells`, `sheet` *and* `sheet_dir` outputs and
  to both VAEs: one Queue renders the sheet, saves the PNG and writes the RefMod bundle. Its
  settings are the ones the release notes recommend - *Full Reference* at `ref_resolution` 1152 with
  a 9216 token cap, which keeps **all five** fidelity cells (5 x 1728 = 8640). That number is not
  cosmetic: the first draft of this example used 1472, where five cells cost 14030 tokens against
  the same 9216 cap, so the export silently shipped three of the five views. A test now derives the
  cost from the workflow's own `cell_size` / `cell_aspect` / `ref_resolution` / `max_tokens` and
  fails if a future edit re-introduces the cap, and another test refuses a shipped example whose
  payload names a machine-local reference (a picture or voice that only its author has would look
  like a broken example on every other install).
* **`H3 Sheet → RefMod`: export the sheet as a RefMod bundle with appearance *and* voice
  members.** A sheet is a multi-view identity board, which is what
  [ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod) wants: a latent
  that rides H3's own reference path for a fraction of the tokens a real reference costs. The new
  node writes one version-5 bundle - the picked cells stacked (`<name>_views`), the composite
  (`<name>_sheet`), a connected audio (`<name>_voice`) and/or the H3-generated audio of a cell's
  own exported clip (`<name>_voice_cellN`) - to `models/refmods/<subfolder>/<name>.safetensors`,
  the tree `Load H3 RefMods` lists. Both VAE encodes are that pack's own code (its `Create H3
  RefMod` and audio helper), so no VAE math is duplicated here and the file is exactly what its
  loader expects; the dependency is optional and a missing install is reported as
  `ComfyUI-MiniMaxH3Mod is not installed - clone ...` rather than a traceback in a graph. The
  report prints each member's token count and the total, because that - not the file size - is
  what a full-reference export costs at sampling time.
* **The Builder node outputs `sheet_dir`** (added last, so existing workflows keep their slots):
  the absolute folder the run wrote, so a downstream node can read the sheet's own files
  (clips, picks, manifest) without retyping or re-deriving the name - which is how the RefMod
  export finds the voice of a cell.
* **A voice member with no audio VAE is skipped, not fatal.** A voice is an H3 audio-VAE encode,
  so it needs that VAE connected; forgetting it used to fail the whole export *after* the
  appearance encodes were done. Now the voice is dropped, the bundle is still written, and the
  node's status leads with `voice: skipped - connect the MiniMax H3 audio VAE ... (VAELoader ->
  minimax_h3_audio_vae_fp32.safetensors)`.

### Fixed

* **A hand-picked frame no longer reverts to the rule.** Clicking a thumbnail in Results records a
  *manual* pick (`picks.json` with `manual: true`), and any later rebuild - another cell's click, or
  the Rebuild sheet button - used to drop that flag, so the next compose recomputed the cell from
  its `auto` / `last` / `sharpest` rule and the chosen frame was silently replaced. The mode is now
  a real one (`PICKS` gained `manual`), the store keeps a stored hand-pick authoritative, and the
  row says so: `picked frame 9 (chosen by hand)`. Choosing a rule for that cell still replaces it.
* **The Results tab no longer rebuilds itself on every click.** A pick, a rebuild, a poll or a tab
  switch used to re-create the whole pane - a few hundred `<img>` nodes, all re-fetched, with the
  scroll position thrown away, which read as the page "refreshing" and acting laggy. The pane now
  updates in place (one border, one label, the sheet image), and only redraws when the frames on
  disk actually changed.
* **A rebuild says what it wrote.** The status line names the file
  (`sheet rebuilt from the frames on disk → character_sheet-20261003-192805.png`), and the sheet
  preview is fetched with a cache-buster, so a recomposite inside the same second is visible
  instead of looking like nothing happened. (The export of a run is still one file, replaced on
  each rebuild - a new one per run.)
* **Clicking a frame is ~3.6x faster, and marks the click immediately.** Every rebuild decoded
  **all** the frames on disk (5 cells x 22 = 110 images) and then used five of them: measured on a
  5-cell sheet, 2.4s of a 3.0s re-compose was decoding. The pick index is now arithmetic unless the
  mode ranks (`sharpest` ranks *small* decimated copies), only the picked frame is read at full
  size, and a cell's still is rewritten only when it would change. The same sheet now re-composes
  in **1.06s** (was 3.04s) and a click lands in **0.84s** (was 3.01s) - and the thumbnail is marked
  and the row says `picking frame 10…` before the answer arrives, so the click is never in doubt.

## [1.0.1] - 2026-10-03

A polish release: the panel's Help tab stopped telling you about someone else's disk, the
Settings tab was laid out deliberately instead of by accident, the project and the repository
were renamed to **Builder**, and the README gained screenshots and measured render times. No
change to the node type, the pack folder or the payload - a saved workflow loads as it did.

### Changed

* **Renamed to `5tar5ystem MMH3 Character Sheet Builder`** (it was "…Maker"): the repository, the
  node's display name in ComfyUI's menu, the panel's Help title, the package metadata and the docs
  all follow. Nothing technical moved - the node type (`MiniMaxH3CharacterSheet`), the pack folder
  and the payload contract are unchanged, so saved workflows keep loading.
* **The Settings tab is laid out in rows that mean something.** Every knob now declares which line
  of its group it belongs on (`row` in `knobs.py`), instead of the grid deciding: *Cell size /
  Cell shape / Frames*, then *Steps / Sampler / Scheduler*, then **the seed next to its *Seed
  mode*** (they used to be a row apart, diagonally), then the two flow shifts. *Cell shape* moved
  from the *Sheet* group into *Render* with the other per-cell knobs, and the row numbers and
  widths are enforced by tests. Measured render times for the two full-sheet presets are in the
  README (~81 s for *Balanced*, ~378 s for *Fidelity* on an RTX 5090 at 8 steps).
* **The Help tab no longer names files on your disk.** The file check used to print
  `found: <file>` plus `also here: <every other match>`, which is a fact about one machine's model
  folder rather than an answer; each row now says where the file belongs and the ✓/✗ says the
  rest. The guide's `**bold**`, `*italic*` and `` `code` `` markers render as emphasis instead of
  reaching the tab as asterisks and backticks, and the tooltips have them stripped. The note
  pinning one community checkpoint's beta numbering was removed in favour of the step-count advice
  it was carrying.
* The shipped example workflow is `example_workflows/5tar5ystem MMH3 Character Sheet Builder.json`
  (renamed from `... Maker.json`; the contents are unchanged).
* Screenshots added under `images/`, used by the README and the Civitai writeup.

## [1.0.0] - 2026-10-03

The first release: a standalone character-sheet maker for ComfyUI's MiniMax H3, rendered by
ComfyUI **core H3 nodes** - no other custom node pack required.

### The sheet

* **One node, six tabs** - References, Cells, Prompt, Results, Settings, Help - mounted as an
  interface inside the node, with the native knob rows hidden (the panel draws them, three to a
  row, and the values still serialise with the workflow).
* **References with roles**: up to 9 pictures, 3 videos (with their soundtracks) and 3 audios;
  each tile carries a free-text role ("face and hair", "body and clothes", "this voice") that the
  prompt uses verbatim, plus per-tile enabled / blur state. Drag-to-reorder, drop to upload,
  Browse to reuse anything already in ComfyUI's folders.
* **A vocabulary, not a text box**: 15 views (face close-up, portrait, front, 90 deg profile,
  back, 45 deg views, over-shoulder, hands, legs, eyes...), 13 poses (neutral, A/T-pose, sitting,
  kneeling, crouching, lying, walking, contrapposto, hands on hips, arms crossed, reach-camera,
  hair touch) and 20 expressions (neutral through smile, smirk, laugh, pout, wink, determined,
  fear, crying, pain, and arousal / pleasure / orgasm as face states). Framing-aware assembly:
  a close-up never claims the body, a back view never claims the face.
* **A readable prompt**: the Prompt tab shows the exact per-cell text (identity, reference legend
  with each role, framing, pose, expression, extra words, suppression list) from the pack's
  planner - no GPU, no queueing.
* **Face blur** for references that must not supply a face: auto / on / off per tile, three scopes
  (face, face + hair, whole head), hand-painted areas, a "show me the blurred copy" preview, and
  cached derivatives in `input/h3_character_sheet/derived/`. Originals are never modified.
* **Latent continuation** between cells (Auto / On / Off, per cell override) so a row reads as one
  take; the plan, the wiring and the frame picker are pinned to agree by tests.
* **Layouts and captions**: hero-left / grid / strip, 1-6 columns, any aspect, captions, three
  backdrops (neutral, custom colour, a reference's own setting), fit controls.
* **Presets**: two shipped full-sheet presets (balanced / fidelity) plus your own, saved to
  ComfyUI's user folder.
* **Output**: a composited sheet, per-cell picked stills, **every** frame of every cell,
  per-cell clips with H3's own audio (24fps), and the manifest / picks / report on disk. Picking a
  different frame and re-compositing costs no GPU time.
* **Two extra nodes**: `H3 Character Sheet Grid` (composite a sheet from frames on disk, usable
  with any H3 workflow) and the internal cell saver.

### Watching it render

* **Live preview strip**: every sampling step streams a **looping clip** of the cell being
  denoised to the panel (`cell 2/5 · step 4/8 · 22-frame loop`), decoded with the `taeh3` tiny VAE
  **on the CPU in float32, on a worker thread** - it never touches the sampler's GPU or its
  thread. Clip length is measured, not guessed: the first clip probes one latent frame, later ones
  spend a 1.5s CPU budget at the measured rate (at least 3 latent frames, a still when even that
  would be expensive, at most 24 frames sent). Without a tiny VAE it falls back to latent2rgb.
  Off with `render.livePreview: false`.
* **↻ new seed**: on the live strip and on every Results row. It cancels the running prompt,
  writes a random seed onto **that one cell**, renders only that cell (`render.onlyCells`) - the
  others keep the frames already on disk - and then recomposes the sheet, naming any cells the
  cancelled run never reached.
* **ComfyUI's own sampler preview is muted** for sheet renders (an `OUTER_SAMPLE` wrapper swaps the
  previewer out for the duration, restoring it in a `finally`), because the panel is the preview.
  `render.comfyPreview: true` keeps it as well.

### Notes and limits

* Renders need an H3 ref2va checkpoint, the Qwen3-VL text encoder and **both** VAEs (H3 generates
  audio with every clip). The in-node Help tab checks all of them against your install.
* The face blur needs `ultralytics` + `cv2` and a `face_yolov8m.pt`; without them it reports why
  and wires the original reference untouched.
* The live preview's clips are a **prefix** of the cell (the tiny VAE's temporal blocks chain
  forward) and are decoded on the CPU: on a very large cell you get fewer frames, or a still.
* A re-roll cancels the run it replaces; cells that had not finished yet have no frames on disk and
  are reported as such (Run again fills them in).
* H3 samples 5, 22, 39... frames (17k+5 at 24fps): a requested length snaps **up** and the report
  says so.

### Development

* **290+ Python tests** (`pytest tests/ -q`, no GPU needed) and two frontend suites (jsdom panel +
  a wiring-contract test) under `npm test`.
* `test_sheet_graph` asserts the expansion uses **only** ComfyUI core H3 nodes plus this pack's
  grid, so the pack cannot silently grow a dependency.
* The standalone frontend tests are importable on a checkout that cannot install `node_modules`
  (jsdom is injected through `globalThis.__JSDOM__`).

[1.0.1]: https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/releases/tag/v1.0.1
[1.0.0]: https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/releases/tag/v1.0.0
