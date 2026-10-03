# Civitai post - 5tar5ystem MMH3 Character Sheet Maker (v1.0.0)

Copy from the line below into the Civitai article/description, then attach 3-5 images:
one finished sheet (the headline), the panel with references and roles filled in, the LIVE strip
mid-render, and the Results tab. Gallery order that reads best: sheet -> panel -> live strip ->
results.

---

# 5tar5ystem MMH3 Character Sheet Maker - turn your references into a finished H3 character sheet

Make a **character sheet** for MiniMax H3 out of the photos, videos and audio you already have:
say what each reference is for, tick the views / poses / expressions you want, and get one
composited sheet you can feed straight back into a **ref2va** workflow as a single image.

Built for ComfyUI's MiniMax H3. Renders on **ComfyUI core H3 nodes** - this pack adds the sheet,
nothing else.

**Node pack (GitHub):** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker
**Release page (v1.0.0):** https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker/releases/tag/v1.0.0
**Ready-made workflow** (drag it onto the canvas): https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker/blob/main/example_workflows/5tar5ystem%20MMH3%20Character%20Sheet%20Maker.json
**Workflow, direct download** (no GitHub account needed): https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker/releases/download/v1.0.0/5tar5ystem.MMH3.Character.Sheet.Maker.json
**Full manual:** the README in the repo (every knob, every option) - in-node too: the node's **Help** tab carries the same guide and checks your model files for you (✓/✗ with the exact folder to drop each one in).

## What it does

* **References with roles.** Up to 9 pictures, 3 videos (with their soundtracks) and 3 audios, each with a free-text role: *face and hair*, *body and clothes*, *this voice*. The role text is what the prompt says, and each cell gets exactly the references it can use - so one picture can carry identity while another carries the outfit.
* **A matrix of cells.** 15 views (face close-up, portrait, front, 90° profile, back, 45° views, over-shoulder, hands, legs...), 13 poses (neutral, A/T-pose, sitting, kneeling, walking, hands on hips...) and 20 expressions, including arousal / pleasure / orgasm written as face states. Tick, press **Build cells**, done.
* **You can read the prompt before you render.** The **Prompt** tab shows the exact per-cell text - identity, the reference legend with each role, framing, pose, expression, your extra words, the suppression list. No GPU, no queueing.
* **Face blur for references that must not supply a face.** Auto (blurs a reference whose role does not mention the face), on/off per tile, three scopes (face, face + hair, whole head) and hand-painted areas for tattoos, logos or a second person. Blurred copies are cached; your originals are never modified.
* **Latent continuation between cells** so a row reads as one take instead of unrelated frames (*Auto* only chains cells that share a camera distance).
* **Presets.** Two shipped full-sheet presets (balanced / fidelity) plus your own, saved into ComfyUI's user folder.
* **Composited sheet + the takes it came from**: the sheet with captions, per-cell picked stills, *every* frame of every cell, and each cell's clip with the audio H3 generated. Re-picking a frame and re-compositing costs no GPU time.
* **Watch it render, re-roll one cell.** A **LIVE** strip above the tabs plays a looping clip of the cell being denoised (`cell 2/5 · step 4/8 · 22-frame loop`), and **↻ new seed** stops the run to render *that one cell* again with a fresh seed - the other cells keep the frames they already have.

## Install (the node)

1. **ComfyUI-Manager** → *Custom Nodes Manager* → search **MMH3 Character Sheet** (publisher `5tar5ystem`) → Install.
   By hand instead: `cd ComfyUI/custom_nodes && git clone https://github.com/The5toryofthe5ecret5tar5ystem/5tar5ystem-MMH3-Character-Sheet-Maker.git ComfyUI-H3-Character-Sheet`
2. **Restart ComfyUI**, then hard-refresh the browser (`Ctrl+Shift+R`).
3. Load the **ready-made workflow** above (drag it onto the canvas) - it already wires the H3 ref2va checkpoint, the Qwen3-VL text encoder, both VAEs and a SaveImage, and pre-builds a 5-cell matrix.

Nothing else to install: no other custom node pack is needed. The node's **Help** tab lists the model files below with a ✓/✗ against your install.

## Models you need (and where they go)

| What | File | Where | Link |
|---|---|---|---|
| Diffusion model | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` (official repack, ~20 steps) **or** a community TURBO checkpoint such as `10Eros_Max_h3_TURBO-hybrid_beta5_w4a8_14gb_optimized.safetensors` (8 steps) | `models/diffusion_models/` (a subfolder is fine) | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models · https://huggingface.co/TenStrip/10Eros-Max/tree/main |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` | same repo - H3 generates audio with every clip, so this is not optional |
| Face detector *(optional - only for the blur)* | `face_yolov8m.pt` **plus** the `ultralytics` + `opencv` python packages | `models/ultralytics/bbox/` | https://huggingface.co/Bingsu/adetailer/tree/main |
| Tiny VAE *(optional - only for the LIVE strip)* | a `taeh3` TAEHV decoder | `models/vae_approx/` | The file ComfyUI's own H3 previews / KJNodes' preview override use - if you already preview H3 you have it. Without it the strip falls back to latent2rgb (blurrier, still animating). |

**Steps**: 8 with a TURBO checkpoint (the node's default), 20-30 with a non-turbo one - one field in the **Settings** tab. With a TURBO file, do not also load a turbo LoRA, and skip cache/Spectrum nodes on ref2va runs (the 10Eros model card's own advice: they cost accuracy).

## First render, in five steps

1. Open the workflow, drop your references into the **References** tab, and type a role under each one (*face and hair*, *body and clothes*...). Fill in *Character* with who this is, and *Suppress* with what must not appear (`text, watermark, logo, extra people`).
2. **Cells** tab: tick the views / poses / expressions you want → **Build cells**. Or pick a **Preset** at the top and skip both steps - the full-sheet presets build their five cells for you.
3. Check the **Prompt** tab: that is the text every cell will render.
4. **Queue.** The LIVE strip shows each cell as it is denoised; the **Results** tab fills in as cells land on disk.
5. In **Results**, click any thumbnail to make it that cell's frame, then *Rebuild sheet* - that only re-composites, no GPU involved.

## Tips

* **One good identity reference beats six mediocre ones.** Extra pictures are for clothing, angles and objects; several *different* faces is the most common way a sheet goes wrong.
* **22 frames per cell** is the sweet spot for a usable still (H3's grid is 5, 22, 39... - a requested length snaps up and the report says so).
* **The role boxes are read word by word** - *face*, *hair*, *eyes*, *glasses*, *clothing* (and its swimwear/underwear words), *body*, *breasts*, *intimate*, *legwear*, *shoes*, *accessories*, *voice*. The picture that is the only claimant of one is called its **sole source**; the prompt is built from that.
* **Not happy with one cell?** Don't re-render the sheet: hit **↻ new seed** - on the cell you are watching, or on its row in Results. Only that cell is rendered again.
* **Watermarks in your references get learned.** Put them in *Suppress* and blur or crop what is burned into the pixels.

## Honest limits

* The live strip decodes on the **CPU** so it can never slow or crash a render - which is why, on a very large cell, you get fewer frames (or a single still) rather than a longer loop.
* A **re-roll cancels the run it replaces**. Cells already on disk are kept and reused; cells the cancelled run had not reached yet are reported by name so you can Run again to fill them in.
* The sheet is a fixed-canvas composite; the per-cell **clips** (with H3's audio) are the takes it was picked from.
* Face blur needs the detector *and* its python packages; without either it says so and wires your original reference untouched.

## Credits / license

**GPL-3.0.** The pack is standalone: sheets are rendered by ComfyUI's own MiniMax H3 nodes; the pack adds the panel, the cell matrix, reference roles, the frame picker and the compositor. `taeh3` tiny-VAE previews follow the H3 preview ecosystem (ComfyUI core's previewer / KJNodes). Full credits in `NOTICE` and the README.

Built by **5tar5ystem**. Feedback, sheets you made with it, and issues are welcome on GitHub.

---

## Post checklist (not part of the copy)

- [ ] Gallery: finished sheet (cover) → panel with references + roles → LIVE strip mid-render → Results tab.
- [ ] Tag the post with the H3 / MiniMax model this pack targets, and mention which checkpoint the sample sheet used.
- [ ] If the sample uses a community checkpoint, credit it in the description and link its page.
- [ ] Check the two repo links resolve (they do at v1.0.0) and that the workflow link still has `%20` for the spaces in the file name.
- [ ] Mention it needs ComfyUI with H3 core nodes (a recent build), and that a full sheet is minutes, not seconds, on a 24GB card at 1024px cells.
