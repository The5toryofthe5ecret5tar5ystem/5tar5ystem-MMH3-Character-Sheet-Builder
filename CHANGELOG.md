# Changelog

All notable changes to **5tar5ystem MMH3 Character Sheet Builder** are recorded here. This pack
follows [semantic versioning](https://semver.org/): the node type (`MiniMaxH3CharacterSheet`) and
the payload contract are what "breaking" refers to, not the panel's layout.

## [Unreleased]

### Fixed

* **The panel width repair no longer moves the node's height.** Repairing a squeezed wrapper
  (1.2.1) asked for a height fit immediately afterwards, but the panel is still laid out for the
  squeezed width at that moment (it re-lays out on a debounce), so the fit measured the *narrow*
  content, set the node to that height, and the panel's own resize observer then asked for a
  different one - a two-state loop that kept resizing the node while the frontend rewrote the
  wrapper. The repair is now a width-only correction: the panel re-lays itself out for the width
  it gets back and brings the node to that height through `layoutChanged`, and the fit refuses to
  measure at all unless the wrapper is at least as wide as the node (`panelWidthMatches`), so a
  squeezed measurement can never become a node height.

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
