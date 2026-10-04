# Changelog

All notable changes to **5tar5ystem MMH3 Character Sheet Builder** are recorded here. This pack
follows [semantic versioning](https://semver.org/): the node type (`MiniMaxH3CharacterSheet`) and
the payload contract are what "breaking" refers to, not the panel's layout.

## [Unreleased]

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
