# StickerMe

Complete step-by-step architecture, implementation and operating guide: [Architecture.md](Architecture.md).

Turn one permitted portrait into twelve separately generated sticker reactions using the installed FLUX.2 Klein **4B Q6_K** model on this laptop. English captions are editable or removable. Plan 1 adds explicit quality review; exact identity and perfect hands are not guaranteed.

## Start

```powershell
Set-Location "D:\Additional Project\Img_2_Sticker"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

Open http://127.0.0.1:8000. Choose a style and tone, then inspect the reference against every candidate:

- **Realistic / Likeness:** three previews first. Each expression and pose is generated together using the original photo as the identity reference. Likeness adds local shading. Photo corrections produce a coherent replacement rather than overlaying a second face.
- **Cartoon / Chibi / Comic:** choose one of two character designs first. Each reaction receives the original face, outfit and selected character as references.
- Review the face, intended emotion, gesture and hands of each preview before approving the remaining nine. Download saved PNGs at any time. Every reaction needs review for the WhatsApp / Telegram export. For an automated warning, inspect the image and use **I checked it—accept anyway** if it looks right, or generate a correction if it does not.
- Use **Generate correction**, expression intensity, **Fix mask**, caption removal and **Compare / restore** to improve one reaction. Regional corrections preserve surrounding artwork when alignment and detection permit; otherwise the note identifies a full redraw.

Existing packs remain available. Earlier artwork is labelled legacy and does not improve automatically; deliberately redraw a reaction or create a new pack.

## Installed stack and controls

FastAPI, SQLite migrations, one leased worker, React/TypeScript/Vite, local ComfyUI, Klein 4B Q6_K, Qwen3 4B Q4_K_M and Flux2 VAE. Models and dependencies remain pinned under `workflows/`. The application Python is `.venv`; CUDA inference uses `runtime/engine-env`. Miniconda base is unchanged. No model training is part of Plan 1.

YuNet/SFace provide advisory face screening. An OpenCV palm detector screens photographic anatomy; cartoon counts are advisory because ink/shading cause false detections. Automated checks cannot assess every expression, prop, finger or identity error. Manual review can explicitly override a flagged image while preserving the detector findings. The editor shows review progress across the whole pack.

Tone and per-sticker intensity affect the photo-edit instructions. Automatic LivePortrait face overlays are disabled by default because different viewing angles and large expression changes can create seams or double features. `STICKERME_PHOTO_ANIMATION=1` explicitly enables the experimental older animation route. It uses original-photo source/reference crops and a reusable CPU process while sufficient RAM is available. `STICKERME_PORTRAIT_REUSE=0` disables reuse; `1` forces CPU residency for benchmarking. Photo styles work without LivePortrait in the default mode.

U2-NetP remains the default segmentation model. Soft alpha and useful enclosed gaps survive cleanup. `scripts.benchmark_plan1_masks` compares installed alternatives on identical saved images before changing the default. Composition fits the figure and caption together and softens broad flat torso bottoms.

Segmentation attaches alpha to unchanged RGB; border rendering composites alpha once to avoid doubled grey edges. For saved affected images, preview with `python -m scripts.repair_sticker_alpha --packs PACK_ID` and inspect the comparison before applying with `--apply`. Previous versions are preserved. [Overlap and transparency repair details](Docs/overlap-fix.md).

Repair using `setup.ps1 -DownloadModel` and `setup_engine.ps1`. Existing pinned downloads are reused after hash verification. Stop verified owned services with `stop.ps1`. Pending work survives restarts; lost engine history requires explicit Resume rather than duplicate submission.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build --prefix frontend
.\.venv\Scripts\python.exe -m scripts.doctor
```

Real GPU checks require the ordinary worker stopped and the engine idle. They store isolated data under `runtime/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.services start-engine
.\.venv\Scripts\python.exe -m scripts.validate_plan1 --create --style cartoon
# Inspect runtime/plan1-validation/contact-sheet.png, then select a design:
.\.venv\Scripts\python.exe -m scripts.validate_plan1 --select-design 0
# Only after visual acceptance of the three previews:
.\.venv\Scripts\python.exe -m scripts.validate_plan1 --review greeting laughter surprise --continue-pack
# Review the remaining reactions explicitly before --export.
```

`--generate-all-unreviewed` generates a full QA set without accepting any artwork; it does not certify visual quality or permit export. `--run`, `--photo`, `--seed` and `--tone` make separate comparisons reproducible. `scripts.smoke_cartoon_pack` uses the same staged flow under `runtime/cartoon-smoke`. `scripts.likeness_ab` explicitly selects its historical drawn comparison route.

For the photographic route use `scripts.validate_photo_route --photo portrait.jpg --consent`. For expression-strength comparisons use `scripts.benchmark_plan1_expressions --source canvas.png --drivers drivers.json`. See each command's `--help`.

## Storage and exports

**Download PNGs** saves a ZIP containing the currently generated transparent PNGs with their captions, including previews or reactions still awaiting review. **Save PNG** on a card saves that image directly. These downloads preserve the saved pixels and do not change review status. The separate WhatsApp / Telegram ZIP retains its review requirements. [PNG download implementation and verification](Docs/png-downloads.md).

The local-only API provides interactive documentation at `/docs`. Packs contain the normalized reference, local face embedding, raw generation candidates, source/driver/animation artifacts, masks, quality reports and immutable versions. Embeddings are never exported. Pack deletion removes owned images/engine copies; model files remain installed. `STICKERME_DATA_DIR` relocates application data, and `STICKERME_COMFY_URL` selects a local engine.

ZIP exports contain transparent 512 × 512 WhatsApp WebP (≤100 KiB), Telegram PNG/WebP (≤512 KiB), a 96 × 96 tray PNG (≤50 KiB), text-free artwork, emoji/quality manifest and submitted workflow provenance. New attempts record route/style/tone/seed, reference hashes, workflow hash and installed model hashes. Keep 3–30 stickers.

A ZIP needs a compatible phone importer; it does not install automatically. Actual phone importing and interactive browser validation are separate acceptance checks.

Current implementation, measurements and outstanding visual targets: [Docs/plan1-implementation.md](Docs/plan1-implementation.md). Original complete plan: [Docs/plan1.md](Docs/plan1.md). Older build records remain historical.
