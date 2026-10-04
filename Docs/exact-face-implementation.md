> Historical record. Active Plan 1 routing, review controls and current validation are documented in [plan1-implementation.md](plan1-implementation.md). Claims below about exact-face preservation or filtered Cartoon routing are superseded.

# Exact face: photo-edit route (handoff, 3 Oct 2026)

## What changed
- New default style **Realistic**. Realistic, Likeness and Cartoon never redraw the face:
  1. Klein edits the real photo, changing **arms/hands only** (`canvas.png` + `face-clean.png`).
  2. Klein draws the expression on a close-up of the photo (driver only).
  3. **LivePortrait** (MIT, `runtime/liveportrait`, pinned in `workflows/liveportrait.json`) warps the person's own face into that expression.
  4. A head-shaped paste puts it back. Below 0.45 similarity, the original expression is kept and the sticker note says so.
- Files:
  - New: `backend/app/portrait.py`, `scripts/liveportrait_runner.py` (engine env), `scripts/download_liveportrait.py`, `scripts/validate_photo_route.py`, `tests/test_photo_route.py`
  - Updated: `imaging.py` (person_cutout, aligned_canvas, portrait_matrix/warp_crop/paste_head, speckle fix), `catalog.py`, `comfy.py` (`route="photo"`), `worker.py` (`generate_photo`), `likeness.py`, `main.py`, `cleanup.py`, `config.py`, `setup.ps1`, frontend.
- Chibi/Comic keep the drawn route. `STICKERME_PHOTO_EDIT=0` disables the new route.

## Evidence (same photo, fixed seeds, SFace similarity)
| Reaction | Old app | New route |
|---|---|---|
| Hi! | 0.62 | 0.89 |
| LOL | 0.42 | 0.75 |
| OMG! | 0.41 | 0.60 |

- Tests: 46 passed. Frontend build passed.
- Full 12-reaction run in the real app pipeline, saved in `runtime/photo-route-check/446fe7bf70724af6ad73621f77b96057/` (`contact-sheet.png`, `result.json`):
  - Took 1296 s (about 108 s per sticker). Median similarity 0.905.

| Reaction | Similarity | Reaction | Similarity | Reaction | Similarity |
|---|---|---|---|---|---|
| greeting | 0.93 | surprise | 0.59 | affection | 0.96 |
| agreement | 0.95 | thanks | 0.94 | waiting | 0.88 |
| refusal | 0.91 | apology | 0.86 | busy | 0.90 |
| laughter | 0.83 | goodnight | 0.70 (2nd seed) | congrats | 0.94 |

  - Visually, all 12 are the same person as the photo.
  - Known defect: OMG! shows a dark patch left of the face near the raised hand. Possible cause: the head-paste ellipse or the hardened cut-out. Investigate this next.

## To do
1. Restart the app (Ctrl+C in the `start.ps1` terminal, then run `start.ps1` again) and create a new pack with Realistic.
2. Review the 12-reaction contact sheet, especially hands near the face (laughter, goodnight).
3. Delete the experiment copies of the user's face:
   - the scratchpad `exp-out`
   - `runtime/comfyui/input/StickerMe-exp`
   - `runtime/comfyui/output/StickerMe-exp`
4. Update `Docs/Build-Status.md` with the measured results.
