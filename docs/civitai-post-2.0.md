# Civitai post - 5tar5ystem MMH3 Character Sheet Builder (v2.0.0)

Everything below the line is the copy. Paste it into the Civitai article or description, then
attach the images from `images/` in the repo, in the order listed.

Gallery order and what each image is:

1. `sheet-4k-onepass-hero-4-panels.png` - the finished 4K one-pass sheet: headshot, chest-up
   portrait, full body front, 90 degree side, back, in one image, 3264 x 2176;
2. `panel-cells-layout-cards.png` - the Cells tab: the layout cards, the framing glyphs, the
   resolution cards and the One pass mode row, on a real graph;
3. `panel-references-paint.png` - the References tab: a role under every tile and a blur area
   painted by hand over the reference that must not lend a face.

---

# 5tar5ystem MMH3 Character Sheet Builder 2.0

A character sheet builder for MiniMax H3 in ComfyUI. You give it photos, videos and audio of a
person, say what each reference is for, and it renders a sheet of views you can feed back into a
ref2va workflow as one image. This post is about version 2.0 only.

Version 2.0 changes two things: what a render is, and what the node looks like while you use it.

**Repo:** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder
**Release (v2.0.0):** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/releases/tag/v2.0.0
**Workflow, drag onto the canvas:** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/blob/main/example_workflows/5tar5ystem%20MMH3%20Character%20Sheet%20Builder.json
**Workflow, direct download:** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/releases/download/v2.0.0/5tar5ystem.MMH3.Character.Sheet.Builder.json
**Workflow with the RefMod export appended:** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder/releases/download/v2.0.0/5tar5ystem.MMH3.Character.Sheet.Builder.Plus.RefMod.json

The full manual is the README. The node's Help tab carries the same guide inside ComfyUI and checks
your install for the five model files it needs, with a tick or a cross against each one and the
folder it belongs in.

## What 2.0 is

Two changes carry the version.

**1. One render makes the whole sheet, and it is the default.** In 1.x every panel was its own short
clip, composited afterwards: five renders of 22 frames, five chances for the identity to drift
between panels. In 2.0 one H3 clip draws the entire arrangement as a single image. The 5-frame
minimum is enough because a sheet is a still. Frame 0 becomes the sheet, the other four frames are
kept under `one_pass/`, and every panel is cut back out of the sheet at the box the prompt asked for
and written where the per-cell pass writes its cells (`cells/<id>.png`, `frames/<id>/f0000.png`). The
picker, the Results tab and the RefMod export therefore work on a one-pass sheet without a second
render. For a five-cell sheet that is 5 sampled frames instead of 110, and the panels agree with each
other by construction, since identity, lighting, palette and style cannot drift when one sampling
context draws them all.

**2. The panel is a studio rather than a form.** The layout is the one drawn in
`web/mockups/panel-redesign-proposals.html` (proposal B): a narrow icon rail on the left holding the
seven tabs, a one-line header with a status chip, two equal halves on the tabs that decide something
(the stage and the control column), and a pinned footer whose primary action is Render.

## What is new in 2.0

* One-pass sheet as the default, with the per-cell pass unchanged and one switch away.
* The panel: icon rail, one-line header, sheet and picture stages, control column, pinned footer.
* Layout presets and quality presets as card rails. Each card draws what it does, so the layout card
  for "Hero + 4 panels" draws five boxes in the arrangement you will get.
* Framings and expressions as glyph toggles instead of rows of checkboxes. Poses stay words.
* A reference canvas: click a tile and it loads at the size of its column, with the paint surface,
  the Original / Blurred switch and the blur area chips on the picture itself.
* Drag and drop per panel: drop a framing, a pose, an expression or a reference tile onto one panel
  and only that panel changes.
* Clip blur, sound mute and hand-painted blur areas, on top of the picture blur 1.x had.
* Per-cell clip export, with the audio H3 generated, at 24 fps.
* The RefMod suite preset: four boards (hero sheet, expression board, SFW detail crops, NSFW detail
  crops) built and queued as one job.
* Your own presets, saved to ComfyUI's user folder and re-appliable to the next sheet.
* Backdrops, including one borrowed from a reference's own location.
* The live stream on its own tab, with the live strip that plays a looping clip while a cell is
  denoised.
* Settings drawn in the panel, grouped in three columns, with the node's own rows hidden so the node
  stays short. Help carries the guide with the live file check.

## The one-pass prompt

The one-pass prompt is not the per-cell prompt repeated. It is written in the sections H3's own
captions use: `subject_definitions` (which reference is the sole source of what), `summary`,
`retention_analysis` (ownership and preservation, including that the identity picture's own outfit is
replaced when another reference owns the clothing), `detailed_description` (the layout),
`overall_soundscape: None` and `non_diegetic_music: None`, because a sheet is silent.

The layout is stated in words and in pixels. Each panel line carries its place both ways, for
example `Panel 2 of 5 (the middle column, upper half; x=1101, y=24, 1061x1034)`. On its own, pixel
boxes were not enough: an early hero + 4 sheet came back as three full-height columns with two panels
missing. The prompt also states that all panels are drawn and that none is merged, dropped, reordered
or stretched, that the full-body panels share one figure scale and one ground line, and that the sheet
is a still, complete in the first frame and unchanged to the last, so the clip cannot drift into a
turntable.

Panel placement is still guidance, not a hard constraint. H3 treats the words and the boxes as
semantic input, and it can reorder or merge panels. That is the honest description of any single-pass
multi-panel prompt. When a panel has to be exactly right, or the sheet will be enlarged, turn the
switch off and render per cell.

## What each mode gives up

| | One pass (default) | Per cell |
|---|---|---|
| Sampling | one clip, 5 frames | one clip per cell, 5 to 425 frames each |
| Pixels per panel | its share of one canvas | a full render each |
| Frame picker, clips, audio, latent continuation | no | yes |
| Panel placement | guidance | each cell is its own render |
| Per-panel re-roll | no | yes, one cell with a new seed |

## Resolution and memory

The resolution control above the presets is the only thing that sets a size. One click sets two paired
sizes: the canvas a one-pass render draws, and the cell size a per-cell render uses. No preset touches
either, so applying a layout cannot silently undo a 4K choice.

| Button | Sheet short edge | Cell size | A 3:2 sheet renders | Latent tokens |
|---|---|---|---|---|
| 1080p | 1088 | 1024 | 1632 x 1088 | about 3.5k |
| 1440p | 1440 | 1024 | 2160 x 1440 | about 6k |
| 4K | 2176 | 2048 | 3264 x 2176 | about 14k |

These are estimates from the pack's own numbers, not measurements: an int8 DiT is about 10.5 GB
resident, the nvfp4 text encoder about 5 GB, and activations scale with the token count. The
counter-intuitive part is worth knowing before you choose: a 4K one-pass render, about 14k tokens, is
cheaper than one 2048px cell at 22 frames, about 18k tokens, because the one-pass grid is only five
frames long.

Rough guidance: 16 GB cards at 1080p with cell_size 768 and clip export off; 24 GB cards at 1440p
comfortably and 4K likely; 32 GB cards at 4K and cell_size 2048. A wrong guess costs a re-render,
nothing worse.

## Blur: pictures, clips and sound

H3 conditions on every reference it is given at once and has no per-reference weight. A prompt can
ask for identity from the first picture and clothing from the second, but it cannot stop the model
reading a face that is present in the pixels. Blur removes it instead of arguing with it.

* **Pictures.** Auto blurs a reference whose role does not claim the face, with per-tile on and off.
  Three areas: face, face and hair, whole head.
* **Hand-painted areas.** For anything detection does not know about (a tattoo, a logo, a name tag, a
  second person), open the preview and paint. Brush and lasso, stored as points on the reference
  itself, so the painting is resolution-independent and travels with the workflow.
* **Reference clips.** Sampled on 12 frames, tracked between them, blurred frame by frame and written
  back as a new file with its audio track copied. With the tile set to blur off, only what you painted
  is blurred, which covers a logo or a watermark on a clip that keeps its framing.
* **Sound.** There is nothing to blur in a voice, so a sound whose tile says mute on is written as a
  silent copy at the source's own rate, length and channels. The reference stays a usable sound in the
  graph, it just carries no timbre. Auto keeps a voice, because a sound reference is usually added on
  purpose.

Blurred copies are cached in `input/h3_character_sheet/derived/` and keyed by the source's mtime and
size. Your original file is never modified.

## Clips, continuation and the sheet on disk

A per-cell render writes one clip per cell, h264 with the audio H3 generated alongside it, at 24 fps,
into the sheet's own folder. H3 has no fps input: its joint video and audio latent is fixed at 24 fps,
so the frame count is the duration and 22 frames is about 0.92 s. Switch it off while iterating and the
three nodes per cell and the encode disappear from the graph.

Latent continuation anchors the last five frames of the previous cell at frame 0 of the next one,
using ComfyUI core's H3 guide API. Auto chains only cells whose camera distance already matches, so a
turnaround continues while a framing change stays crisp. It is a soft anchor rather than a splice:
expect the same room, light and scale with a drifting pose. The frame picker skips the hand-over
frames and ranks only the settled tail, because a chaining clip spends its first frames still in the
previous pose.

Everything lands in one folder:

```
<output>/minimax_sheets/<name>/
    frames/<cellId>/f0000.png ...   every frame the cell rendered
    cells/<cellId>.png              the picked frame, or the panel sliced from a one-pass sheet
    clips/<cellId>_0000N_.mp4       the cell's clip, with its own audio
    one_pass/                       the four frames of a one-pass sheet after frame 0
    <name>.png                      the composited sheet
    <name>.json                     manifest: spec, picks, sizes, warnings
    picks.json                      cell -> {mode, index}
    report.txt                      human readable last run
```

## Presets and the RefMod suite

Presets come in two axes. The layout axis says what to draw: Hero + 4 panels, Expressions 2x3,
Turnaround, the two Closeups 2x2 boards, or the RefMod suite. The quality axis says how to sample it:
one-pass sheet, per-cell renders, or max identity fidelity. A preset writes the node's own widgets and
builds its cells, so picking one and pressing Queue is the whole job. Your own presets save the same
things to `user/default/h3_character_sheet/presets.json`, and each one computes its own list of the
settings it moves off a fresh node.

The RefMod suite is a layout preset that renders four boards in one queue: the hero sheet, the
expression board, the SFW detail crops and the NSFW ones. Each board is a complete sheet folder under
the run name, and a `suite.json` records which boards belong together.

## Exporting the sheet as a RefMod

A character sheet is a multi-view identity board, which is what a RefMod wants: a VAE latent that H3
attends to like a real reference, at a fraction of the tokens. The `H3 Sheet -> RefMod` node (from
[ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod)) writes one bundle with
the picked cells stacked, the composite as a second member, and a voice member taken from the sheet's
own reference audio, the soundtracks of your reference videos, or a cell's generated audio. Full
Reference stores the real encode so a face survives; Compressed Reference pools it into a tiny grid
that carries concept rather than identity. The node's report prints each member's token count, because
the tokens are what the export costs at sampling time, not the file size.

## Install

1. ComfyUI-Manager, Custom Nodes Manager, search MMH3 Character Sheet (publisher `5tar5ystem`), then
   Install and restart ComfyUI.
   By hand:
   `cd ComfyUI/custom_nodes && git clone https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Builder.git ComfyUI-H3-Character-Sheet`
2. Restart ComfyUI, then hard refresh the browser with Ctrl+Shift+R.
3. Load the ready-made workflow. It wires the H3 ref2va checkpoint, the Qwen3-VL text encoder, both
   VAEs and a SaveImage, and pre-builds a five-cell matrix.

No other custom node pack is required. Renders use ComfyUI core H3 nodes; this pack adds the sheet.

## Models the pack needs

| What | File | Where |
|---|---|---|
| Diffusion model | a TURBO beta5 H3 checkpoint, for example `10Eros_Max_h3_TURBO-hybrid_beta5_w4a8_14gb_optimized.safetensors`, or the official repack `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` |
| Face detector, optional and only for the blur | `face_yolov8m.pt`, plus the `ultralytics` and `opencv` python packages | `models/ultralytics/bbox/` |
| Tiny VAE, optional and only for the live strip | a `taeh3` TAEHV decoder | `models/vae_approx/` |

Downloads: Comfy-Org's H3 repack at https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main, community
TURBO checkpoints at https://huggingface.co/TenStrip/10Eros-Max/tree/main, the face detector at
https://huggingface.co/Bingsu/adetailer/tree/main.

Steps: 8 with a TURBO checkpoint, which is the node's default, or 20 to 30 with a non-turbo one. With
a TURBO file, do not also load a turbo LoRA, and skip cache or Spectrum nodes on reference runs.

## A first sheet

1. Drop your references into the References tab and type a role under each one. Fill in the Character
   text with who this is and Suppress with what must not appear, for example `text, watermark, logo,
   extra people`.
2. Pick a layout card. The full-sheet presets build their five cells for you, or tick views, poses and
   expressions yourself and press Build cells.
3. Read the Prompt tab. That is the text the render will use, one section per panel in one-pass mode.
4. Press Render in the panel footer. The Preview tab shows the frames as they are denoised.
5. In Results, click a thumbnail to choose a different frame for a cell and press Re-compose. That only
   re-composites, so it costs no GPU time. In one-pass mode the panels are already the frames.

## Two things worth knowing

**Upgrading from 1.x.** The `single_pass` widget is on by default. A workflow saved before 2.0 has no
value for it, so it opens in one-pass mode. The One pass and Per cell segment in the Cells tab, or the
single_pass switch in Settings, puts it back to one render per cell. Nothing else in the payload
changed shape, and old sheet folders still list and re-compose.

**One good identity reference beats six mediocre ones.** Extra pictures are for clothing, angles and
objects. Several different faces is the most common way a sheet goes wrong, which is also what the
blur is for.

## Credits and license

GPL-3.0. Sheets are rendered by ComfyUI's own MiniMax H3 nodes; this pack adds the panel, the cell
matrix, the reference roles, the blur, the frame picker and the compositor. The sheet modules were
originally written inside ComfyUI-MiniMax-H3-Motion-Director and are carried here under the same
license. Full credits are in `NOTICE` and the README. Feedback and issues are welcome on GitHub.

---

## Notes for posting (not part of the copy)

* Attach the three images above in order. The sheet is the cover.
* Tag the post with the H3 / MiniMax model this pack targets, and name the checkpoint the sample
  sheet used if it is a community one.
* The release download links above use the GitHub release asset names generated from the workflow
  files, so the spaces are dots and the RefMod variant keeps its name.
* The screenshots are from a real graph on a 32 GB card. Say so if anyone asks how long a sheet
  takes: the README's timing table is five cells at 8 steps on an RTX 5090.
