# Plan 1 implementation and validation — 4 October 2026

The application pipeline and review controls from [plan1.md](plan1.md) are implemented. The installed Klein **4B Q6_K** remains the generation model on the RTX 4050 laptop with 6 GB VRAM. No custom training, smaller replacement model or hosted GPU is introduced.

**Visual acceptance is incomplete.** The full cartoon QA pack communicates distinct reactions and shares a drawing style, but the sample person becomes a younger-looking character and gains invented facial hair. These outputs remain unaccepted. This release does not meet the proposed “recognizable in 10 of 12 reactions” target or establish perfect stickers for arbitrary uploaded people.

**Current photographic default:** following the repeated visual defects, automatic face overlays are disabled. Realistic/Likeness now use `coherent-photo-edit-v4` to generate expression and pose together. Photo corrections also retain one coherent replacement. The earlier original-photo animation work below is historical/experimental and requires `STICKERME_PHOTO_ANIMATION=1`. See [the latest Surprise repair and its limitations](overlap-fix.md).

## Implemented changes

| Plan phase | Implementation |
|---|---|
| Reproducibility | Corrected the misleading A–E and cartoon smoke routes. Staged QA supports an explicit style, tone and initial seed. Durable attempts retain exact submitted workflows, reference hashes, route, intent, stage, seed, workflow hash and installed local model hashes. Raw candidates, drivers, decoder outputs, transforms, masks and final stickers are retained. Earlier QA artifacts may predate the final metadata additions. |
| Composition and tone | Tone changes gesture/expression instructions and motion strength. Caption and foreground fit as one group; captions can be removed. Broad flat torso cuts receive a curved lower edge. Figure/caption artifacts are available at 128/256/512 pixels. UI claims describe the real generation paths and avoid promising exact identity. |
| Original-photo face | LivePortrait uses the original photograph as both appearance source and neutral expression reference. Decoder output is normalized to the 512px crop coordinates. Eye/nose landmark alignment and geometry guards reject unsafe composites. The face blend stays inside an inward-feathered facial oval; source segmentation can only restrict it. The generated pose retains its single hair/head/body silhouette and detected foreground hands are protected. Fallback attempts the original face; a note identifies unsafe restoration and generated-face fallback. |
| Independent checks | Identity, expression/pose/prop, style, framing, anatomy, mask and variety are reported separately. Unavailable checks require review. Possible extra hands in photographic styles and multiple detected faces block acceptance independently of face similarity. Rotated-view duplicate hand boxes are merged. Cartoon palm counts remain advisory because they are not calibrated for drawn shading. |
| Expression and alpha | Per-sticker expression intensity, tone strength, a reusable CPU animation process/source-feature cache, and evaluation scripts for saved drivers and segmentation alternatives. The animator is released after a job and can be disabled under RAM pressure. Soft alpha, small foreground details and useful enclosed finger gaps are retained. U2-NetP remains the default after the initial ISNet comparison. |
| Direct cartoons | Cartoon/Chibi/Comic generate two character designs before previews. Each reaction receives the original face, outfit and selected character. Face refinement also receives the selected character crop, avoiding a refinement pass that ignores its design. Designs can be retried. Reactions are not chained as identity references. |
| Review and recovery | Every new reaction requires explicit review before pack approval/export. Face/hand/expression corrections affect only the selected reaction. A region compositor retains surrounding artwork when reliable alignment/detection permit; otherwise the note says a full redraw was retained. Immutable versions support comparison and restore, including caption/mask edits. |
| Release checks | Backend suite, TypeScript/production build, real local design/previews/full-pack generation, saved photographic compositing, expression/mask comparison, selected GPU correction, format checks and migration preservation checks. Interactive browser and actual phone import checks remain outstanding. |

## Fresh validation evidence

- Latest Surprise repair: **72 backend tests passed**, production frontend build passed, and API/worker reloaded. The corrected saved Surprise uses its clean pose's own face at restrained strength 0.55 after visual inspection; its score changed 0.557 → 0.655. All 95 other sticker rows and existing version records were preserved. New default photo generation and corrections cannot invoke face animation/restoration or regional face overlays. Two isolated full-photo GPU trials exposed remaining identity/expression limitations and were not used as saved replacements. [Current details and before/after](overlap-fix.md).

- Follow-up transparency correction: **68 backend tests passed**. Fixed RGB being multiplied by alpha in both background removal and border rendering, which produced grey doubled shirt/hand edges. Eight current white-shirt stickers were rebuilt without changing artwork, mask geometry, captions or seeds. Both the API and worker were reloaded. The actual installed segmentation matches the repaired new Laughter cutout; previous-version hashes and exact served PNGs were checked. [Current comparison and verification](overlap-fix.md).

- Overlap correction: **66 backend tests passed** after adding coverage for source-mask expansion, eye/nose alignment independent of mouth expression, and unsafe geometry rejection. Four saved reactions from the affected white-shirt pack were recomposed from their original pose and raw animation artifacts, without a new GPU generation. Previous versions, captions and seeds are retained. [Repair details](overlap-fix.md) and [before/after sheet](../runtime/overlap-debug/d0d6147c-6d89-4193-b870-ffb6bd8d4464/before-after.png).

- Backend suite: **63 passed**, one upstream Starlette/httpx deprecation warning. After the final approved-design refinement/provenance changes, the nine engine recovery/workflow tests also passed. The extended caption/mask/reorder/removal test passed and verifies cleanup of new raw-animation folders and candidate reports. Python compilation passed.
- Frontend: `npm.cmd run build` passed TypeScript and Vite production compilation. The production API serves the built frontend. Browser automation reported no available browsers; interactive UI behavior is therefore not claimed verified.
- Diagnostics: installed engine, face models, LivePortrait, palm detector, background-removal model and English font are available. The generation model size remains 4B.
- Real GPU QA: two designs and all twelve reactions generated in isolated `runtime/plan1-validation`. The selected face correction completed in **145.88 seconds**, preserved the reference and other **11** images, retained its immutable previous version and remained blocked from export until review. No QA artwork was automatically accepted.
- All twelve real sticker files passed transparency/512px dimension checks and WhatsApp/Telegram encoding limits. Largest WhatsApp WebP: **67,416 bytes**. This verifies export formatting, not likeness or actual phone installation. API ZIP creation/approval/export gates are also exercised in backend tests.
- Existing production records are compared against a SQLite backup after migration 4; packs, stickers, jobs and original attempt fields must remain unchanged. The normal application is started on port 8000 with its original data directory, separate from QA data.

### Saved photographic head comparison

Same original canvas and saved gesture artwork, with each historical final expression cropped as a driver and strength 0.7. This isolates the compositor/source change; it is **not** a controlled new diffusion benchmark or a cross-person identity calibration.

| Reaction | Historical SFace cosine | Original-head composite | Anatomy outcome |
|---|---:|---:|---|
| Greeting | 0.876 | 0.923 | Needs visual review |
| Laughter | 0.544 | 0.777 | Three hands detected; blocked despite the higher face score |
| Surprise | 0.725 | 0.810 | Two hand regions after duplicate merging; needs visual review |

These measurements describe the earlier compositor. The later saved white-shirt outputs exposed duplicated hair/head edges caused by its expanded mask. The overlap correction now retains the generated silhouette and transfers only the aligned facial interior. Neural motion can still soften detail, and hand protection depends on imperfect detection. SFace cosine is advisory, not a probability of recognition.

### Expression and segmentation comparison

Saved laughter driver, original face source, CPU resident animator: strength 0.7/1.0/1.3 scored **0.803/0.692/0.647**. The first call took 9.47s; subsequent cached calls took 4.75/5.11s. Stronger deformation increased expression and changed face detail. This is one driver and one source; it does not establish per-intent calibration or a controlled speed comparison against repeated one-shot inference.

On identical saved photographic laughter artwork, U2-NetP used **468.1 MiB process RSS** and 2.03s; ISNet general use reached **1,292.2 MiB process RSS** and 36.28s. The ISNet timing includes its first model download/load, and RSS includes both cached segmentation sessions, so these numbers are not steady-state model latency or independent per-model peaks. ISNet gave cleaner inspected edges on white/dark/green backgrounds. Its additional memory cost and this small sample do not justify replacing the default yet. Segmentation does not repair the artwork's extra hand.

## Saved artifacts

- [Full cartoon QA contact sheet](../runtime/plan1-validation/contact-sheet.png), [pack state](../runtime/plan1-validation/pack.json), [format check](../runtime/plan1-validation/format-check.json), [selected-correction check](../runtime/plan1-validation/regeneration.json).
- [Original-head comparison](../runtime/plan1-photo-composites/contact-sheet.png) and [measurements](../runtime/plan1-photo-composites/results.json).
- [Expression-strength comparison](../runtime/plan1-expression-review/contact-sheet.png) and [measurements](../runtime/plan1-expression-review/results.json).
- [Segmentation/background comparison](../runtime/plan1-mask-review/contact-sheet.png) and [measurements](../runtime/plan1-mask-review/results.json).
- [Production preservation/health check](../runtime/plan1-release-check.json), [source hash manifest](../runtime/plan1-source-manifest.json), and `runtime/plan1-source-baseline/` with the pre-migration database and early source snapshots.

## Recovery and remaining acceptance work

Existing artwork is preserved and labelled legacy. New changes apply when creating a pack or deliberately regenerating a reaction. Use Compare / restore to recover a better previous version. Turning off resident animation with `STICKERME_PORTRAIT_REUSE=0` preserves one-shot execution. The original source snapshot contains an early version of the catalog tone/route changes, so it is not a pristine pre-task checkout.

Git initialization was attempted, but creating root `.git` metadata caused sandbox ownership/setup errors. Only that newly created empty metadata was removed. The workspace remains without Git; source snapshots and hashes provide a review/recovery record, but a normal Git repository still needs to be established in a compatible environment.

Core ComfyUI has latent-mask nodes, while the installed reference graph starts from an empty latent. Masking conditioning alone is not a hard head-pixel constraint. A separate masked-diffusion route was evaluated at the architecture level and has not been adopted or claimed visually validated; this implementation uses head/regional compositing. [ComfyUI's implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/nodes.py) shows the latent-mask distinction.

Remaining visual acceptance: a consented portrait set spanning facial hair, glasses, age appearances, skin tones, head angles and lighting; a controlled before/after benchmark using identical inputs/seeds; per-intent curated-driver/retargeting evaluation; correction-edge and mask review across more examples; recognizable full packs for unseen people; interactive browser review/restore/export; and actual phone importing. The engineering changes and twelve-file generation/format checks do not replace those checks.

For now, Realistic or Likeness uses the stronger original-photo head path. For a drawn pack, reject a character design that does not resemble the person and inspect all reactions before accepting them. Training experiments remain in [plan2.md](plan2.md); the complete comparison remains in [plan3.md](plan3.md).
