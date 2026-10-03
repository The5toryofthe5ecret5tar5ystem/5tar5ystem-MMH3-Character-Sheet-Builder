# 5tar5ystem MMH3 Character Sheet Maker

**Repo**: [The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker](https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker) ·
**License**: GPL-3.0 · **ComfyUI node**: `MiniMaxH3CharacterSheet` · **Installs as**: a
custom-node folder (any name), typically `ComfyUI-H3-Character-Sheet`

Standalone **MiniMax H3 character sheet maker** for ComfyUI: give it photos, videos
and audio of a person, say what each reference is for, pick a matrix of views /
poses / expressions, and get a composited character sheet you can feed straight
back into a **ref2va** workflow as a single reference image.

No other custom node pack is required. The renders are done by **ComfyUI core
MiniMax H3 nodes** (`MiniMaxH3ReferenceToVideo` -> `MiniMaxH3SigmaShift` -> sampler
-> `VAEDecode`); this pack adds the sheet: the cell matrix, the reference roles, the
frame picker and the compositor.

* Folder / node type: `ComfyUI-H3-Character-Sheet` / `MiniMaxH3CharacterSheet` (a
  workflow contract - the display name is cosmetic, the type is not).
* Panel tabs: **References · Cells · Prompt · Results · Settings · Help**.
* The **Help tab** carries this guide in the node, with a live ✓/✗ check of the model
  files below, so you can see what is missing from inside ComfyUI.

## Models you need

Four files plus one optional detector. The in-node **Help** tab checks all five
against your running install and tells you the folder to drop each one in.

| What | File | Where it goes | Get it from |
|---|---|---|---|
| Diffusion model | a **TURBO beta5** H3 checkpoint, e.g. `10Eros_Max_h3_TURBO-hybrid_beta5_w4a8_14gb_optimized.safetensors` (14GB) or the `..._int8` 20GB build | `models/diffusion_models/` (a subfolder is fine) | [TenStrip/10Eros-Max](https://huggingface.co/TenStrip/10Eros-Max/tree/main) - or ComfyUI's own [repack](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models) (`minimax_h3_ref2va_pruned_int8_convrot`) at ~20 steps |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` | [Comfy-Org/MiniMax-H3 · text_encoders](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders) - `CLIPLoader` with type **minimax** |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` | [Comfy-Org/MiniMax-H3 · vae](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae) |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` | same repo - H3 generates audio with every clip, so this is not optional |
| Face detector *(optional)* | `face_yolov8m.pt` | `models/ultralytics/bbox/` - the models folder next to ComfyUI itself, which may differ from your `extra_model_paths.yaml` roots | [Bingsu/adetailer](https://huggingface.co/Bingsu/adetailer/tree/main), or install [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) which brings the file and the `ultralytics` package |

**Steps**: 8 is the default everywhere, because the community TURBO checkpoints bake the
turbo delta into the weights and their own recipe for `res_multistep` / `simple` is 6-8
steps. A non-turbo checkpoint wants 20-30 - that is one field in the **Settings** tab.
With a TURBO file, do **not** also load a turbo LoRA, and skip cache/Spectrum nodes on
reference runs (the 10Eros README's advice: they cost accuracy).

The face blur is the only thing that needs the detector, and it degrades gracefully: with
no model it reports "no face model found" and wires your original reference untouched.

## Nodes

| Node | What it does |
|---|---|
| `MiniMax H3 Character Sheet Maker` | The whole feature: references + cells -> N short H3 renders -> `H3SheetGrid`. Outputs `sheet` (IMAGE), `cells` (IMAGE batch) and `report`. |
| `H3 Character Sheet Grid` | Composites a sheet from per-cell frames. Use it on its own to re-composite a finished sheet, or with any other H3 workflow. |

## Using it

0. **Open the ready-made workflow**: `example_workflows/5tar5ystem MMH3 Character Sheet
   Maker.json` (it is also installed into your ComfyUI workflow list as
   *5tar5ystem MMH3 Character Sheet Maker*). It wires the H3 ref2va model, the Qwen3-VL
   text encoder, both VAEs and a SaveImage, and pre-builds a 5-cell matrix: face close-up,
   portrait, full body front, 90 deg profile and back, all neutral pose and expression -
   the same five the *Full Character Sheet* presets build, so the file is the shortest path
   from "opened it" to "queued it". Drop your references into the panel, type who the
   character is, press Queue.

### Presets (top of the panel)

The **Preset** selector at the top of the panel sets the whole node at once. The list is
served by the backend (`h3_character_sheet/presets.py`), so the panel can only offer what the
node implements, and each preset declares where it departs from a fresh node's defaults - the
bar prints that as *"Changes: Continuity, …"* rather than changing settings silently.

| Preset | What it sets |
| --- | --- |
| **Balanced (recommended)** | 1024px cells, 22 frames, 8 steps, `per framing` references, continuation `auto` (chains only where the camera distance matches), clips exported. What this pack is tuned for. |
| **Full Character Sheet - Balanced** | The finished article, 1024px cells on a 1536px sheet: headshot, chest-up portrait, full body front, full body 90-degree side and full body from behind - neutral expression, neutral pose, on a flat neutral tan backdrop. |
| **Full Character Sheet - Fidelity** | The same five cells and the same neutral tan backdrop at print resolution: 2048px cells on a 3840px sheet. Several times the render time and a very large PNG - for a sheet that will be enlarged or cut out. |
| **Fast look (no chains, no clips)** | 768px cells at H3's 5-frame minimum, every cell independent, nothing encoded - to find the framing, not to keep the result. |
| **Max identity fidelity** | The 2048px reference pipeline (several times slower) with independent cells, 2048px cells on a 3840px sheet. |
| **Turnaround (chained full body)** | Front -> profile -> back in one row; all three share a camera distance, so continuation holds the room, light and scale while the subject turns. |
| **Expression sheet (chained face)** | Five face close-ups in one row: identical framing, so the chain carries the light and the head position while only the expression changes. |

**Every preset samples at 8 steps** (and so does a fresh node). The community TURBO H3
checkpoints bake the turbo delta into the weights, and their own recipe for the
`res_multistep` / `simple` pair these presets set is **6-8 steps** - the pack used to default
to 25, which is the same image at roughly three times the cost. 8 is the top of that range, so
it gives the most motion. A non-turbo checkpoint (or a guidance/cfg workflow) still wants
20-30: that is one field in the **Settings** tab, and the presets never re-apply over it until
you pick one again.

A preset writes the node's own widgets (cell size, frames, steps, reference sizing,
continuation, clip export, layout, shape) plus the settings the panel owns, and it also
**builds its cells**: a preset that says which cells it is for (both *Full Character Sheet*
tiers, *Turnaround*, *Expression sheet*) creates them on the spot instead of only ticking the
boxes, so picking one and pressing Queue is the whole job. A preset with no ticks in it (the
settings-only ones) leaves an existing cell list alone, and *Clear cells* still empties it.
Editing a knob afterwards is expected; the applied preset id is recorded in the payload
(`render.preset`) so a saved workflow can say how its numbers started, and picking *Custom (no
preset)* only clears that record.

### Saving your own presets ("Save..." next to the selector)

After ten minutes of dialling in a sheet, the combination that worked should be one click
next time. **Save...** takes the settings the node has *right now* - every knob from the
Settings tab (cell size, steps, frames, sampler, reference sizing, layout, shape...), the
continuation switch, clip export, the backdrop (including which reference supplies it), the
face-blur area and the view/pose/expression ticks - names it, and puts it at the bottom of
the preset list marked **(custom)**. Choosing it later applies exactly that, cells included.

* Saved presets live in **ComfyUI's user directory**:
  `user/default/h3_character_sheet/presets.json`. That is configuration, not output, so
  clearing a render folder or updating ComfyUI does not take them with it. The **Save...**
  panel prints the path it wrote to.
* **Delete** removes the selected saved preset - and is only enabled for presets you saved
  yourself: the shipped recommendations are the pack's, not yours to lose. It asks twice
  (*"Really delete?"*) because a preset can represent real work.
* The store validates what it is given (numbers and strings only, ticks filtered against the
  sheet's vocabulary) and computes the **Changes:** line itself from the node's own defaults,
  so a saved preset says what it moves off a fresh node just like a built-in one.
* Up to 40 saved presets, and a name up to 40 characters; two presets may share a name (each
  gets its own id).

### Backdrops (Cells tab)

Every cell is rendered against the backdrop chosen in the **Cells** tab, and every one of them
is written as **flat**: no gradient, no vignette, no lighting falloff and no shadow of the
subject cast onto it. That is what makes a sheet read as one shoot instead of N photos. H3 is a
video model - told only "neutral tan" it builds a tan *room* - so each backdrop also says what
is **not** there (no room, no walls, no floor, no furniture) and that the subject is lit
separately from it. The same wording goes into every cell prompt, so the framing holds from
cell to cell.

| Backdrop | What it tells the model |
| --- | --- |
| **Neutral grey** (default) | A plain neutral background. |
| **Neutral tan** | A flat seamless neutral tan backdrop (`#c8b39b`) - the backdrop both **Full Character Sheet** presets are built around. |
| **Flat white** / **Mid grey** / **Flat black** | Studio backdrops; black also states the subject is lit separately from it. |
| **Green screen** / **Blue screen** | Chroma keys (`#00B140` / `#0000FF`) with the matching spill guard, so a keyed cut-out stays clean. |
| **Reference image/video** | Borrow *one reference's* own setting: choose a picture or a video in the box beside it and its location, backdrop and lighting are used behind the character - nobody and nothing else from that reference appears in shot. The picker counts the references the render actually **wires**, so its `<Picture 2>` is the same `<Picture 2>` the prompt names (an unchecked tile takes no number). |
| **Custom...** | Your own words, framed the same way: *"a flat uniform backdrop of deep red velvet curtain, flat and completely uniform, … nothing else in shot"*. |

If a "reference" backdrop points at a slot that has since been emptied or unchecked, the render
falls back to the neutral backdrop and says so in the plan warnings, rather than rendering a
setting nobody chose.

1. Add **MiniMax H3 Character Sheet Maker** and connect `model`, `video_vae`,
   `audio_vae`, `clip` (the same loaders any H3 workflow uses).
2. In the node's panel, fill the three **References** cards - **9 pictures, 3 videos,
   3 audios** - and say who the character is. Each card starts as a single dashed tile
   and **grows as you add**, the way the Easy-Media picture grid works:
   * **drop files onto that tile** (or onto the card): the row grows by one tile per
     reference, in order. Wrong kinds are refused, so a video cannot land in the
     picture row;
   * each tile keeps the **shape of its own media** (a 3:4 portrait stays portrait, a
     16:9 clip stays wide, audio is a wide chip) instead of forcing every reference
     into a square - ratios are clamped to a sane band so one extreme panorama or
     giant vertical photo cannot dominate the row;
   * **drag a filled tile onto another** to reorder references (the order is the
     order of `@image1`, `@image2`, ...); the badge on the tile is that number;
   * **click a tile** to pick something that is *already in ComfyUI* - the Browse
     overlay lists your `input` / `output` folders, newest first, with a search box
     and a kind filter, plus **Upload from disk**;
   * hover a tile for **preview** and **remove** - the two buttons are stacked
     vertically in the tile's top-right corner, which is narrow enough to stay inside a
     small tile (a horizontal pair ran off the right edge and was hard to click). Every
     corner has exactly one occupant: kind badge + "use" checkbox top-left, preview /
     remove top-right, blur state bottom-left, prompt number bottom-right;
   * every tile has a **role box** underneath ("face and hair", "her shoes",
     "voice") - that text is what ties a reference to its job in every cell prompt,
     and the box gets the whole row because it is the thing you type into;
   * a picture tile carries its **Blur** state in the bottom-left corner of the
     picture (`Blur auto` / `Blur on` / `Blur off`, one click to cycle) - the corner the
     filename used to take, so the name moves to the tile tooltip;
   * the **Character** card at the top takes the identity/style text that leads every
     cell prompt ("young woman with long silver hair, blue eyes, petite") and a
     **Suppress** line that is appended as *Do not include: ...* ("text, watermark,
     logo, phone, extra people").
   A full row (9 pictures / 3 videos / 3 audios) drops its add tile, and **Clear**
   returns the card to a single empty tile. The tabs show `References n/15`,
   `Cells n` and `Results n`, so the panel stays usable without scrolling through a
   wall of knobs.
3. In **Cells** - tick views / poses / expressions and press **Build cells**:
   * Views: face close up, portrait (chest + face), full body front, full body
     90 deg side, full body from behind, **3/4 front**, **3/4 back**, **full body from
     above (high angle)**, **full body from below (low angle)**, **over the shoulder**,
     **head profile**, **back of the head and hair**, **hands**, **eyes**, **legs and
     footwear**
   * Poses: neutral, A-pose, T-pose, **sitting, kneeling, crouching, lying on the back,
     walking, contrapposto, hands on hips, arms crossed, reach to camera (POV), hand
     through hair**
   * Expressions: neutral, smile, smirk, frown, anger, fear, surprised, embarrassed,
     crying, **eyes closed, lips parted, laugh, pout, wink, disgust, determined, pain,
     aroused, pleasure, orgasm (peak)**
   Pick which axis a view expands along by which ticks you leave on: a whole-body framing
   gets one cell per ticked pose, a facial framing one per ticked expression, and a detail
   crop (hands / legs / back of the head) exactly one neutral cell - it looks the same
   whatever the pose or the mouth is doing. The **eyes** close-up is the deliberate
   exception: an expression *is* what an eye shot is about.
   Then edit each cell (extra prompt, frames, seed, pick mode, continuation, order).
   The **Latent continuation** switch at the top of the tab is the sheet-wide
   setting (`Off` / `Auto` / `On` - use `Auto`); each cell's `cont:` control overrides
   it (`inherit` / `auto` / `continue` / `no`).
   See [Latent continuation between cells](#latent-continuation-between-cells) - it
   changes what the sheet is good for, so it is off by default.
4. Set `cell_size`, `frames_per_cell`, `steps`, sampler/scheduler, seed and the
   sheet knobs (**layout, columns, aspect, short edge, captions, background, fit,
   continuity**) - either on the node or in the **Settings** tab, where they are laid
   out in columns instead of one row each
   (see [Compact settings](#compact-settings-the-settings-tab)).
5. Queue. Each cell is a short clip (default 22 frames, snapped to H3's `17k+5`
   grid) and **every frame is kept**.
6. In **Results**, click any thumbnail to make it that cell's frame, then
   **Rebuild sheet** - a re-composite with no GPU work.

### Compact settings (the Settings tab)

Every knob this node has is also in the panel's **Settings** tab, in three columns instead of
one row each. A node row is one knob wide - the ComfyUI frontend draws a native widget full
width and has no column-span API (`computeLayoutSize` only lets a widget claim its own
space) - so 24 knobs cost roughly 500px of node height that the grid fits into ~150px.

* **Compact node** (on by default) hides the node's own rows; the values stay, and the panel
  writes the *same* widget objects. Hiding is presentational: a hidden widget keeps its
  `widgets_values` slot and its prompt input, because the frontend only skips
  `serialize === false`. Verified by building a prompt with all 25 rows hidden - `cell_size`,
  `steps`, `layout`, `continuity` and `sheet_data` were all still in `inputs`.
* The fields are grouped **Output / Render / References / Sheet / Cells / Debug**, and each
  one is the control the schema asks for (number box with the node's own `min`/`max`/`step`,
  a dropdown with the node's own list, a checkbox, a text box). Values are read from the node
  when the tab mounts, so a workflow always shows what it will render with.
* The knob list comes from the backend (`h3_character_sheet/knobs.py`), which reads the node
  schema - the panel cannot offer a value or a choice the node would reject. Editing a field
  writes the node's widget, so a render started from the panel and one started from the
  canvas are the same render.
* **Seed mode** (fixed / increment / decrement / randomize) is drawn too. It is not in the
  schema: the browser adds that widget to the seed row, and since the panel can write it, the
  node can hide the row without taking the setting away.
* Unchecking **Compact node** puts every row back (and is remembered in the payload), and if
  the knob list cannot be read the panel leaves the node's own rows alone rather than hiding
  knobs it cannot draw.

### Node previews (the same Settings tab)

ComfyUI's own output previews under the node are sized by the frontend, and two of them stack into a
very tall node. The **previews** selector next to *Compact node* decides what happens to them:

| Mode | What it does |
| --- | --- |
| **Panel only (no node preview)** (default) | **Removes** ComfyUI's own preview widgets from the node and clears the images they are built from, so the node is only as tall as its panel. The sheet is shown inside the panel instead (Results tab) - see *Panel preview* below. |
| **Small (side by side)** | Caps the sheet preview and the cell-clip preview at 200px tall, width following each media's own shape - two previews sit next to each other instead of stacking. |
| **Full width (stacked)** | Gives each preview the height its own aspect ratio needs for the node's current width, so the media fills the width edge to edge (~580px for a 16:9 sheet in a 1000px node). Two previews stack. Follows the node when it is resized, and stops at 720px tall. |
| **Full size (ComfyUI default)** | Hands the previews back to ComfyUI's own sizing. |
| **Hidden (no preview anywhere)** | No node previews, and the panel's own preview is set to *Off* as well. |

**Why "Panel only" is the default.** Sizing the frontend's previews is a losing game: it creates
`$$canvas-image-preview` **when the sheet image finishes loading**, with its own
`computeLayoutSize(){return{minHeight:220,minWidth:1}}` and no maximum. Measured on a real node that is
1053px of preview and a **2442px** node - and a cap only lands if a draw pass or the background keeper
happens to run afterwards, which is exactly what a render finishing in a background tab does not do.
Removing the widget (the frontend's own remover does `onRemove()` + `splice`, so this is a supported
move) leaves nothing to argue with. The sweep runs on every draw pass and on the 400ms keeper, because
the frontend re-adds the widget whenever new outputs arrive.

**The render mutes ComfyUI's own sampler preview.** Every mode above governs the *output*
previews - the images the node produced - which the frontend sizes itself. There is a second,
independent channel: while a sampler runs, ComfyUI can stream a per-step preview of the latent
(TAESD/tiny-VAE or latent2rgb), which the frontend paints in the node's preview area *during* the
render. The node never sees it: the sampler builds it in `latent_preview.prepare_callback` and
sends it from the progress hook as a binary websocket frame. So a sheet render wraps the model with
an `OUTER_SAMPLE` wrapper (`h3_character_sheet/preview_silence.py`) that swaps
`decode_latent_to_preview_image` for a no-op while sampling runs and restores it in a `finally`,
leaving the progress callback (and the progress bar) untouched. That is the lever KJNodes'
*Model Preview Override* uses for its `suppress_default_preview`.

Two things worth knowing:

* **On this box it changes nothing you can see**, because the launcher passes no `--preview-method`
  and ComfyUI's own default for that flag is `none`: the sampler was never producing previews here.
  It matters on any install that enables them (`--preview-method auto|taesd|latent2rgb` - common in
  other launchers), where a sheet render would otherwise stream a preview per step.
* Set `"comfyPreview": true` in the node's `render` payload to keep that stream for a run (it
  round-trips through the panel payload and the saved workflow). It is deliberate insurance rather
  than a switch you need day to day.

If you *want* a live preview during a sheet render, put *Model Preview Override* (KJNodes) between
the UNET loader and this node: it decodes the latent itself with a tiny VAE (`taeh3` is already
installed) and streams its own preview to its own panel widget, independent of the server's
`--preview-method`. It also mutes the built-in stream itself, so the two behaviours do not fight.

**Panel preview** is its own select next to *previews*: `Off` / `Small` (240px) / `Medium` (420px,
default) / `Full width`. It sizes the sheet image the **panel** draws in its Results tab - the sheet
plus the newest cell clip, both served from the output folder, both openable full size by clicking.
Two independent knobs on purpose: the node can keep a small ComfyUI preview while the panel shows a
big one, or the other way round.

**Why the compact cap cannot also be full width.** ComfyUI *contains* a preview inside the box the
layout hands it and never upscales it - both the grid calculation and the canvas draw end in
`min(scaleX, scaleY, 1)`. The drawn width is therefore decided by the **height**: a 200px-tall box can
only ever show a 16:9 sheet ~355px wide, however wide the node is. *Full width* works by asking for the
height (node width ÷ aspect), which makes the height the limiting scale and puts the media exactly on
the node's width. Two consequences worth knowing: an image narrower than the node is shown at its own
size rather than stretched, and a preview taller than the 720px cap is centred instead of filling the
width.

That needed three different levers, because this frontend draws the three kinds of preview
differently: a still image is an `ImagePreviewWidget` drawn **on the canvas** (`$$canvas-image-preview` -
no element, no class and no DOM option to reach), an image sequence is a `$$comfy_animation_preview`
DOM widget, and a video is a `video-preview` DOM widget with its own layout function. All three are
laid out by asking the widget for `computeLayoutSize()`, and an undefined `maxHeight` there means
"unbounded" - the widget then absorbs every pixel of node height left over, which is why capping only
the DOM kinds left the still image a ~900px-tall node. The pack bounds that function on all three
(remembering the original, so *Full size* puts it back) and additionally caps the media inside the DOM
kinds with one stylesheet rule. The height a *Full width* preview asks for is measured from whatever the
widget actually holds - a `<video>` reports `videoWidth`/`videoHeight`, the still-image host an `<img>`
with `naturalWidth`, and the canvas widget has no element at all, so its media is read from `node.imgs`.

The bound is re-asserted **on every draw pass** of the node, not just when the run ends: the frontend
creates those widgets when the image finishes loading (seconds after a run on a big sheet), which is
after any one-shot pass the pack could do. It is the same place the frontend creates them, the scan is
a loop over the node's widgets, and it only writes when a bound or a height is actually wrong - so a
settled node costs nothing. (A timer alone is not enough: a background tab throttles or suspends them,
and the widget appears while the node is being drawn.)

The header of the panel prints its **build tag** (`h3sheet_vNN`). A browser tab keeps the module it
loaded first, so if the panel looks like it is ignoring an update, the tag says whether that tab is
running the pack on disk or an older one - reload with `Ctrl+Shift+R` if it is behind.

### Where uploads go

Dropped / chosen files are uploaded through core `POST /upload/image` with
`subfolder=h3_character_sheet`, so they land in
`ComfyUI/input/h3_character_sheet/` and are referenced as
`h3_character_sheet/<file>` - the same input-relative paths core loaders expect.
Very large media needs a bigger `--max-upload-size` (this box runs with 5000).


## Reference roles (what the role box does)

Every tile has a role box, and its text is read **word by word** against a fixed vocabulary -
never by position. Picture 1 is the face only because you said so; swap the two role boxes and
the prompt swaps with them.

| Bucket | Words it reads |
| --- | --- |
| face / eyes / glasses / hair | face, facial features, makeup, lipstick, eyes, iris, glasses, spectacles, hair, bangs, ponytail, fringe |
| clothing | cloth(es), outfit, dress, skirt, shirt, top, uniform, apron, cosplay, costume, wardrobe, lingerie, trousers, pants, jacket, bikini, swimsuit, swimwear, underwear, bra, panties, thong, leotard, bodysuit, corset, camisole, garter, nightgown, robe |
| body | body, figure, proportions, shape, build, skin, tattoo, height, chest, waist, hip, thigh, torso, silhouette, navel, abdomen, midriff, muscle, curves |
| breasts | breast(s), boob(s), tit(s), bust, nipple(s), areola |
| intimate | butt, ass, glutes, crotch, pubic, vulva, vagina, labia, mons, pussy, penis, cock, dick, scrotum, testicles, anus |
| legwear / shoes | socks, stockings, tights, shoes, boots, heels, sandals, slippers |
| accessories | accessory, bow, jewel(ry), necklace, earrings, hat, gloves, choker, belt |
| voice | voice, speech, accent |

Plurals count (`tops`, `clothes`), and a keyword only matches the **whole** word plus a plural
or gerund ending: `topic` is not `top` and `titles` is not `tit`.

* A reference that is the **only** enabled claimant of an attribute is called its *sole source*
  (`<Picture 1> (head, face, hair) is the sole source of the face and the hair.`), and every
  other reference is then told it `must not change` that attribute. Two references claiming the
  same thing drops the word *sole* - which is the point: it names the blend instead of allowing
  it.
* A reference demoted to a non-likeness job (clothes, body) is also told outright that
  `the person visible in it is not the identity, do not copy their face`, because a
  full-length reference photo is a whole second person.
* Words the vocabulary does not read (`head`, `elf ears`) are kept in brackets next to the tag,
  so your own description still reaches the model; a role it understands completely is not
  repeated.
* An empty role box makes **no claim at all** - it never guesses, and a cell with no face claim
  gets no "the identity comes from ..." line rather than a wrong one.
* The same reading drives the rest of the pack: the framing filter leaves a reference out of a
  cell whose framing cannot show its whole role (an outfit for a face close-up, a nude body for
  a close-up), and *Blur auto* blurs a picture whose role does not claim the face.

## Face blur on reference pictures

H3 conditions on every reference it is given at once and has **no per-reference
weight**. A prompt can therefore *ask* for "identity from `@image1`, clothing from
`@image2`", but it cannot stop the model reading a face that is present in the pixels -
and a full-body outfit photo is a whole second person, so it is a whole second identity.
The prompts name that outright ("`<Picture 2>` must not supply a face, a hairstyle, skin
tone or facial features - the person visible in it is not the identity"). The **face
blur** removes it instead of arguing with it.

Every picture tile carries its blur state in the bottom-left corner of the picture -
click to cycle `auto` -> `on` -> `off`. The corner already held the filename, so the
button replaced it rather than adding another layer to the thumbnail; the role box
underneath keeps its full width, because that is the field with typing in it.

| Mode | What happens |
| --- | --- |
| **auto** (default) | Blurred **unless** this picture is the run's identity reference. The identity reference is the first one whose role claims the face (then the hair), so the outfit / prop / reference-sheet pictures get blurred and the headshot is sent untouched. A role box that says nothing is left alone - blurring the only face in the run is not recoverable. |
| **on** | Always blurred, even if it is the identity reference. |
| **off** | Never blurred. |

It is a picture-only job: a video reference would need per-frame detection and a
re-encode, so an `on` on a video is reported in the run report and skipped.

### How much of the head is covered

The **Blur area** select in the references header sets how far the patch reaches. There
is no hair or headwear detector here, so the extra area is geometry: the detected face
box grown around itself.

| Area | Covers |
| --- | --- |
| Face only | The likeness, box plus a small margin. |
| **Face + hair** (default) | Plus the hair, whose colour and shape are identity too. |
| Whole head | Plus whatever is worn on or over it - bows, hats, hoods, glasses, earrings - and long hair down to the shoulders, still stopping above the neckline. It can overlap a high collar on a full-body reference; that is the trade for covering headwear. |

### Painting a blur area by hand

Auto-detection only knows faces. For anything else - a tattoo, a logo, a name tag, a
prop, a plant in the background - open the **eyeball** preview and press **Paint**:

* **Brush** drags a freehand stroke at the current size; **Lasso** closes a loop and
  fills it, so a big area is one gesture.
* Strokes are drawn on the picture as a translucent red overlay; `Undo` takes the last
  one back, `Clear areas` wipes the lot.
* **Apply** blurs exactly what you painted and switches the preview to the copy the
  render will wire; the note under it says how many areas (and faces) were blurred.

Strokes are stored as **normalized points on the reference itself**, not as a baked
image: the painting is resolution-independent, travels with the workflow, and stays
editable (and the same painting applies however large the reference is).

Painted areas are **added** to the face blur - and with the tile set to `Blur off` they
are the only thing that gets blurred:

| Tile mode | With painting | Result |
| --- | --- | --- |
| `Blur auto` / `on` | + painted areas | painted areas **plus** detected faces |
| `Blur off` | + painted areas | **only** what you painted |

A tile with painting shows it in its label (`Blur auto + paint`). Painting is a
picture-only tool, like the rest of the face blur: a video would need per-frame work.

### Seeing it before you render

The **eyeball** on a picture tile opens the preview, and for a picture with the blur in
play it previews **the copy the render will wire**, with an **Original / Blurred** toggle
to compare. The bar underneath says which it is showing and whether the render would blur
that reference at all - a picture the render leaves alone says so instead of showing an
edit that will not happen. The blur is computed on demand by the same route the render
uses (~0.4 s once, cached after).

Detection uses the YOLO face model already used by ComfyUI's detector nodes
(`models/ultralytics/bbox/face_yolov8m.pt`; the panel reports if it is missing),
runs on **CPU**, ~0.1-1.5 s for a reference photo, and the blurred copies are cached
in `ComfyUI/input/h3_character_sheet/derived/` keyed by the source file's mtime and
size - a substitute file with the same name is re-blurred, and the original is never
modified. The face is blurred through a soft ellipse grown to cover the hair and jaw
(`PAD_X` / `PAD_Y` / `SIGMA` in `h3_character_sheet/face_blur.py`), so the body, pose
and garment stay fully usable for proportions and wardrobe while the likeness is gone.

`POST /h3-character-sheet/action` with
`{"action":"blur","file":"h3_character_sheet/x.jpg","scope":"head"}` does it on demand
and answers with the copy's `/view` URL plus `applies` - whether the render would blur
that reference, given the `spec` and `slot` the panel sends. That is what the preview
uses to show you the result before any GPU time is spent. The **Prompt** tab lists the
tags that will arrive blurred, marked `face blurred: <Picture 2>`.


## Layouts

| Layout | Result |
|---|---|
| `hero-left` | cell 1 is the hero and spans the left column; the rest fill the grid beside it (2 columns + 4 cells = the classic portrait with a 2x2 of angles) |
| `grid` | uniform N-column grid, row-major |
| `turnaround` | one row, every cell side by side |
| `custom` | per-cell `row` / `col` / `rowSpan` / `colSpan` in the payload |

## Output on disk

```text
<output>/minimax_sheets/<name>/
    frames/<cellId>/f0000.png ...   every frame the cell rendered
    cells/<cellId>.png              the picked frame
    clips/<cellId>_0000N_.mp4       the cell's rendered clip (frames + its own audio)
    <name>.png                      the composited sheet
    <name>.json                     manifest: spec, picks, sizes, warnings
    picks.json                      cell -> {mode, index}
    report.txt                      human readable last run
```

`name` comes from the `output_name` widget. Because the frames stay on disk, a
different layout / aspect / picks never needs a re-render. The panel's Rebuild
button (or `POST /h3-character-sheet/action` with `{"action":"compose", ...}`) uses
the same code path.

## How a cell is rendered

Per cell the expansion is the official reference-to-video chain:

```text
MiniMaxH3ReferenceToVideo(clip, video_vae, audio_vae, prompt, ref_image_0..8,
                          ref_video_0..2, ref_video_audio_0..2, ref_audio_0..2)
    -> conditioning + AV latent
MiniMaxH3SigmaShift(model, shift_video, shift_audio) -> model     (shared by all cells)
KSamplerSelect + BasicScheduler(shifted model)       -> sampler + sigmas
BasicGuider(shifted model, conditioning)
RandomNoise(cell seed) -> SamplerCustomAdvanced -> VAEDecode(video_vae)
    -> cell frames -> H3SheetGrid (all cells) -> sheet
    -> VAEDecodeAudio(same latent) + CreateVideo(24 fps) + SaveVideo
       -> clips/<cell>_0000N_.mp4        (the export_video widget, on by default)
```

Cells are independent by default: they do not chain, and each gets its own derived
seed, so one cell's stance cannot leak into the next.

### Cell clips (the video each cell generated)

A sheet renders one short clip per cell and the composite keeps one frame of each -
which is what a *character sheet* is, but it throws the animation away. `export_video`
(default **on**) writes each cell's clip, with the audio H3 generated alongside it,
into the sheet's own folder:

* **24 fps, always.** H3 has no fps input: its joint video+audio latent is fixed at
  24 fps, so the frame count is the duration (22 frames = 0.92 s). Stamping a clip at
  another rate would only change playback speed and drift against its own soundtrack.
* **One file per cell**, `clips/<cellId>_0000N_.mp4` (core `SaveVideo` counts, so a
  re-render adds a file instead of overwriting one). h264 + the generated audio, which
  plays anywhere and drops straight into an edit.
* **Core nodes only**: `VAEDecodeAudio` on the same AV latent the frames came from,
  then `CreateVideo(fps=24)` -> `SaveVideo`. Nothing is re-encoded twice, and no new
  dependency is added.
* **The Results tab links them**: every rendered cell shows `▶ clip` next to its frame
  thumbnails, so the take is one click away. The export is also listed in the run
  report, and `GET /h3-character-sheet` reports `clipUrl` / `clipFile` per cell.
* **Switch it off** with the panel's checkbox or the node's `export_video` widget when
  you are iterating and only want the sheet: it removes the three nodes per cell and
  the encode.

### Latent continuation between cells

Each cell is its own short H3 clip, so the *one* thing that couples them is
switched on deliberately: the node's **continuity** widget (the panel's "Latent
continuation" control in the Cells tab, off by default).

With it on, the last frames of the previous cell are anchored at frame 0 of the
next clip, using ComfyUI core's H3 guide API:

```text
VAEDecode(previous cell) -> ImageFromBatch(batch_index=-5, length=5) -> tail
MiniMaxH3ReferenceToVideo(cell N) -> conditioning + AV latent
MiniMaxH3AddGuide(positive=conditioning, latent=AV latent, vae=video_vae,
                  image=tail, frame_idx=0) -> guided conditioning
    -> the guider samples the guided conditioning instead of the raw one
```

* **Hand-over length is 5 frames.** A guide clip is cropped to H3's `17k + 5` grid
  (5, 22, 39...), so 5 is the smallest hand-over; the clip length does not change -
  the first 5 frames of a continuing cell re-render the previous tail and everything
  after them is the new pose. Sampling cost is unchanged; the only addition is one
  video-VAE encode of 5 frames per continuing cell.
* **Three modes.** `off` renders every cell from its own noise. `auto` chains only
  cells whose **camera distance already matches** (`face` close, `portrait` medium,
  `front` / `profile` / `back` full), so a full-body turn continues while the
  framing changes in a sheet stay crisp. `on` chains everything, including across a
  framing change - and says so in the report, because the hand-over carries the
  previous camera distance: a chest-up cell continuing a face close-up stays a
  close-up, and a full body continuing a chest-up cell lands mid-zoom with the feet
  cut off. **`auto` is the mode to use on a normal sheet.**
* **The first cell never continues** (nothing precedes it), and a cell whose own
  length is not larger than the hand-over cannot: the guide would fill the whole
  clip and the cell would be a copy of its predecessor. That is reported as a
  warning instead of rendered.
* **Picks skip the hand-over - and only rank the settled tail.** The first 5 frames are
  a duplicate of the cell above, so they are never picked; and because a continuing clip
  spends its next frames *getting* to the new pose (a 90 deg turn lands around frame 8 of
  22), `auto` / `sharpest` only rank the last part of the clip. Without that, `sharpest`
  picks the hand-over: measured on a real sheet it scored frames 0-7 highest, because the
  pose it was handed is the sharpest part of the clip. An explicit hand-picked frame
  index is still honoured - the panel shows every frame.
* **It is a soft anchor, not a splice.** The tail is conditioning, so the model
  continues from it but is free to drift: expect the same room, light and scale with
  a drifting pose, not a frame-exact cut. The prompt is unchanged either way.
* **Per-cell override:** `cont: inherit` follows the sheet switch, `cont: auto` /
  `cont: continue` / `cont: no` force it for that cell. The Cells tab marks a
  continuing cell with `↳ continues the cell before it` and an `auto` break with
  `↳ framing change - renders on its own`, so the plan is readable before a render.
  A cell whose aspect differs from its predecessor still works (the guide is resized
  to the target), but the framing is then cropped, so keep a chained run in one shape.

### Framing

Each view's prompt states the **shot size** and what must not be cropped, because
that is what the model reads first and where "her feet were cut off" is won:

| View | What the prompt asks for |
| --- | --- |
| Face close up | Tight close-up of the face, head and shoulders only, *not a full body*. |
| Portrait | Medium close-up framed at the chest: top of the head **and** chest inside the frame, *not a face-only close-up*. |
| Full body (front / 90 deg / back) | *Full-length wide shot, camera far back*: the whole figure from the top of the head to the soles of the feet inside the frame with space above and below, **nothing cropped**, no push-in, not a medium shot. |

If a full-body cell still comes back zoomed in, it is usually because it **continued**
a closer cell - set that cell (or the sheet) to `auto`.

## HTTP routes

* `GET /h3-character-sheet?name=<sheet>&node_id=<id>` - listing (cells, frames,
  picks, sheet URL) for the panel.
* `GET /h3-character-sheet/media?source=inputs|outputs&kind=image|video|audio|all&q=&recursive=1&limit=`
  - the Browse picker's listing: `{ok, source, kind, folders, items:[{name, path,
  subfolder, kind, url, size, mtime}], truncated}`, newest first when recursive.
  Only ComfyUI's own input / output folders are served, and a request that tries to
  leave them is refused.
* `POST /h3-character-sheet/action` - `list` | `plan` | `compose` | `pick` |
  `delete` | `clear` | `names` | `blur` | `presets` | `save-preset` | `delete-preset` |
  `knobs` (`blur` = face blur one reference and answer with the copy's URL, `presets` = the
  recommended whole-node settings **plus the user's saved ones** (each entry carries
  `custom`), `save-preset` = store the settings the panel sent as one of those (answering
  with the whole list), `delete-preset` = remove one by id (a built-in is refused with a
  reason), `knobs` = the node's own widgets described for the Settings tab).

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker.git \
  ComfyUI-H3-Character-Sheet
# restart ComfyUI, then hard-refresh the browser (Ctrl+Shift+R)
```

The pack needs the models in [Models you need](#models-you-need) before a render will
start. Open the node's **Help** tab first: it checks your install and tells you which of
them are missing, where each one goes, and links to each download.

Requirements: a ComfyUI build with the MiniMax H3 core nodes
(`comfy_extras/nodes_minimax_h3.py`) and Pillow (ships with ComfyUI). See
`requirements.txt`.

## Development

```bash
pip install pytest
PYTHONPATH=/path/to/ComfyUI pytest tests/ -q      # 290+ tests, no GPU needed
npm install && npm test                            # panel (jsdom) + wiring tests
```

The tests are the point of the structure: `sheet_spec` / `sheet_layout` /
`sheet_store` / `sheet_media` / `planner` / `sheet_pass_core` are pure and cover the
vocabulary, prompt assembly, layout maths, picks, the folder listing and the on-disk
contract; `test_sheet_graph` asserts the expansion uses **only** ComfyUI core H3
nodes plus this pack's grid (so the pack cannot silently grow a dependency) - that
allow-list includes the two nodes continuation needs (`MiniMaxH3AddGuide`,
`ImageFromBatch`); `test_sheet_continuity` pins the three-way agreement between the
plan, the wiring and the frame picker; and the jsdom tests mount the real panel and
drive it - 15 tiles with roles, a dropped file uploading into the exact slot,
drag-to-reorder, the Browse overlay assigning a listed file, preview / remove, the
cell matrix, the continuation switch and click-to-pick.

If your checkout cannot install `node_modules` (a share without symlink support),
inject jsdom instead:

```bash
node -e 'import("node:module")' # or run a wrapper that sets globalThis.__JSDOM__
```

## Credits

Character-sheet design and code: this pack. Renders use ComfyUI's MiniMax H3
implementation. The sheet modules were originally written inside
`ComfyUI-MiniMax-H3-Motion-Director` and are carried here as a standalone pack under
the same license (GPL-3.0) - see `NOTICE`.

## License

GPL-3.0. See `LICENSE`.
