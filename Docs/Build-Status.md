> Historical record. Active Plan 1 routing, review controls and current validation are documented in [plan1-implementation.md](plan1-implementation.md). Claims below about exact-face preservation or filtered Cartoon routing are superseded.

# StickerMe build status — 3 October 2026

## Face likeness release update - 3 October 2026

The new pipeline uses face + outfit references, 768-square pose generation, SFace scoring with deterministic retries, and an aligned 512-square face refinement that is kept only when similarity improves. YuNet/SFace models and Q6_K diffusion weights are installed and hash-verified. Migration 3 preserves older packs and separates pose/refinement/candidate recovery. Embeddings stay local and out of exports; owned face/body/crop files are cleaned on deletion.

The user selected redrawn realistic and cartoon faces with different expressions. Direct cartoon prompting still changed identity too much in the measured sample. Production Likeness and Cartoon therefore generate realistic portraits and apply local illustration shading while preserving facial geometry. Realistic keeps the photographic output. Chibi/Comic retain direct generative styles. A/B profiles A-D and the final E profile are reproducible using `scripts.likeness_ab`.

Real GPU validation on the existing uploaded photo: the former pipeline's median SFace cosine was 0.077; revised Realistic scored 0.485 median (0.416-0.615); final Cartoon scored 0.514 median (0.428-0.620). Final Cartoon's three reactions took 233.24 seconds, with sampled 4401 MiB VRAM and 12.37 GiB whole-system RAM. These are small-sample observations, not identity guarantees or recognition probabilities. Exact pixel identity, recognition of 10 of 12 reactions, and mobile importing are not established.

Six real 512-square transparent sticker previews (three in each selected style) were composed, visually reviewed, and encoded below the 100 KiB WebP limit; the largest was 30,540 bytes. `runtime/likeness-review/contact-sheet.png` shows the reference and previews locally. `runtime/likeness-review/sticker-previews.zip` includes only derived stickers and preview metadata, with no original face crop or embedding. Existing user packs were preserved.

The final frontend production build, Python compilation and model/workflow diagnostics pass. The full backend suite passes **36 tests** (one upstream deprecation warning). Detailed results are recorded in [likeness-implementation.md](likeness-implementation.md). The older sections below record the previous single-reference release and its historical measurements; they are superseded where they describe the active workflow or diffusion precision.


## Current release: English-only cartoon reactions

The original release reused one background-removed photo with different captions. That was a **cutout pipeline**, not image generation, so neither facial expressions nor hand poses could change. New packs now use a real local reference-image editing model to draw each reaction independently. No silent same-photo fallback is used.

**Telugu is removed from the active product scope, UI, API and typography requirements.** Historical planning documents are superseded by this scope. Existing cutout packs are preserved and clearly labelled legacy; create a new pack to obtain cartoons.

## Completed stages

| Stage | Implementation |
|---|---|
| English typography | English starter captions, editable/removable captions, grapheme-aware limits and wrapping, saved artwork reused for caption edits. No Telugu font/shaping installation required. |
| Editor | Per-sticker redraw, erase/restore foreground-mask brush, reset/save mask, reorder/remove, light/dark transparency preview. Separate generated art, foreground and captioned layers. |
| Durability | Versioned SQLite migrations, atomic job claims, one process-locked worker, renewable leases/heartbeats, durable attempts prepared before engine submission, stable client-generated prompt IDs, queue/history reconciliation, explicit uncertain outcome and user-initiated resume. |
| Request safety | Creation idempotency key plus photo/settings fingerprint, conflicting-key rejection, permission check, bounded image upload/decode, local-only requests and browser origins. |
| Generative engine | Installed and pinned ComfyUI/GGUF node, CUDA PyTorch environment, verified Klein diffusion GGUF/Qwen3 encoder/VAE downloads, checked-in API workflow and explicit bindings, compatibility diagnostics and real GPU execution. |
| Preview approval | Wave/laughter/surprise previews first; approval reuses those three and generates the other nine. No artwork generation on caption changes. |
| Different reactions | Twelve intent-specific facial expressions and hand gestures, independent seeds, original reference supplied for every image, duplicate-artwork detection. Selected redraw leaves other sticker files unchanged. |
| Progress and cancellation | SSE snapshots with polling fallback, partial results visible while processing, cancel/resume with completed images retained, app-owned targeted engine cancellation only. |
| Export | Individual 512 × 512 transparent PNGs, bounded WhatsApp/Telegram formats, tray icon, per-sticker text-free artwork, emoji manifest, seeds/workflow provenance, ZIP and honest import instructions. |
| Operations | Setup/repair, diagnostics, hidden local service launch, owned-process stop, logs, separate real-GPU smoke scripts and automated tests. Miniconda base unchanged. |

## Hardware and engine pins

| Item | Verified value |
|---|---|
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB dedicated VRAM |
| System memory | 15.2 GiB physical RAM reported by psutil |
| App Python | Workspace CPython 3.12.15 |
| CUDA runtime packages | PyTorch 2.11.0+cu128, torchvision 0.26.0+cu128 |
| ComfyUI | `e9027f2b30f37bb3052714eb08fcf479542f4fc0` |
| ComfyUI-GGUF | `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` |
| Diffusion | `flux-2-klein-4b-Q4_K_M.gguf` |
| Encoder | `Qwen3-4B-Q4_K_M.gguf`, loaded successfully as ComfyUI's Flux2 text encoder |
| VAE | `flux2-vae.safetensors` |
| Workflow | 512 square reference edit, four distilled Euler steps, CFG 1; CPU text encoder/VAE, low-VRAM GPU policy, 0.8 GB reserved VRAM, previews disabled |

Exact model repository revisions and SHA-256 values are in `workflows/models.json`; engine dependency versions are in `workflows/engine-requirements.txt`. The graph is derived from the [official distilled reference-edit workflow](https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_flux2_klein_image_edit_4b_distilled.json), with GGUF loaders and laptop-sized dimensions.

## Validation evidence

- **22 backend tests passed** for legacy compatibility, preview approval, twelve unique simulated reactions, selected redraw isolation, caption/mask editing without GPU calls, ordering/removal, idempotency, English-only rejection, no cutout fallback, cancellation/resume, attempt persistence/reconnection, unknown/server-error submission outcomes, scoped cancellation/deletion cleanup, stale leases, migrations, workflow bindings, cartoon masks and safe interpreter-child shutdown/PID-reuse protection. Generation is mocked in these tests.
- TypeScript/Vite production build passed. Python compilation passed. Engine diagnostics report the required nodes/models and CUDA GPU available. The pinned engine dependency repair script ran successfully.
- **Real GPU three-image test:** wave 54.48 s, laughter 35.31 s, surprise 34.28 s. All three had different expressions/poses. A repeated run with the refined identity prompt took **36.36 / 34.33 / 33.27 s**.
- **Real 12-sticker pack:** three previews in **105.55 s**, complete generation/segmentation/export in **451.58 s**; **12 distinct generated artwork hashes**, 12 compliant WhatsApp outputs, ZIP **7,077,903 bytes**. Sampled whole-GPU peak **3537 MiB**; sampled whole-system RAM peak **14.78 GiB**. These are periodic samples, not allocator peaks; system RAM includes other running applications. No page-fault/paging-rate benchmark is claimed.
- **Repeated full pack with refined prompt and cartoon-specific cleanup:** three previews **98.34 s**, full run **474.12 s**, **12 unique artworks**, ZIP **6,922,029 bytes**, sampled GPU peak **3505 MiB**, whole-system RAM peak **13.96 GiB**. Both full runs overlapped some backend tests; timings are sample observations, not clean-room performance guarantees. The later contact sheet no longer has the invented glasses or translucent hand artifacts seen initially, although identity/clothing can still drift.
- Full-pack artifacts: `runtime/cartoon-smoke/result.json` and its saved contact sheet/ZIP. Three-image artifacts: `runtime/gpu-smoke/result.json`. These use the bundled scikit-image astronaut photo, not a user's private photo.
- **Real selected regeneration:** one wave sticker redrawn in **33.66 s** through the app API/worker, all **11 other PNGs unchanged**, original reference unchanged, subsequent caption edit preserved generated artwork, and export succeeded. Evidence: `runtime/cartoon-smoke/regeneration.json`.
- Cold `start.ps1` launch started the managed engine/worker and served the API/built frontend at `127.0.0.1:8000`, with engine readiness confirmed. Service metadata includes Windows virtual-environment interpreter children; shutdown verifies their identity as well as the launcher PID. A real stop check left no managed engine/worker processes, and the validation API was stopped. Duplicate API startup is refused without stopping the existing app. Live browser interaction remains unverified because no browser control surface is available in this environment.

## Visual review and honest limits

The real sample verifies **cartoon conversion and different gestures/expressions**, not perfect identity retention. The first prompt added glasses to the astronaut sample and changed clothing details. The refined prompt removed unnecessary accessory terms; the repeated wave no longer added glasses. Likeness and gesture accuracy still require user review, and every individual sticker can be redrawn.

The initial photographic segmentation model left translucent artifacts around some cartoon hands/confetti. Cartoon-specific white-background cleanup now avoids that loss for plain-white outputs; a mask editor handles difficult residuals. Exact accessory matching, flawless hands, native-speaker/subject quality approval, every style/tone combination and phone-app importing are not asserted as tested.

## Run and test

```powershell
Set-Location "D:\Additional Project\Img_2_Sticker"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

Open http://127.0.0.1:8000 and create a **new** pack. Review/approve its three cartoons, then generate the other nine.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build --prefix frontend
.\.venv\Scripts\python.exe -m scripts.doctor
```

Real GPU tests, with local services running:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_generation
.\.venv\Scripts\python.exe -m scripts.smoke_cartoon_pack
```

The second command takes several minutes. Stop owned background services with `stop.ps1`. Extra languages, 24-sticker expansion, training and one-click mobile installation remain outside this release, not unfinished English cartoon features.
