# StickerMe — Exact realistic face: implementation plan

**Date:** 3 October 2026 · **Pack analysed:** `runtime/packs/d830aee6-…` (Likeness style, 3 previews)
**Evidence:** fixed-seed GPU experiments on the same photo, run outside the app (scratchpad only; no app code or pack data changed).

---

## 1. Where we are

### Current previews, scored out of 10 (10 = looks exactly like the uploaded photo)

| Sticker | App score | Rating | What is wrong |
|---|---|---|---|
| 01 Hi! | 0.62 | **5/10** | Wider, heavier face; looks older; thicker mustache; lighter skin; shorter, flatter hair; black specks on the stubble from the Likeness shading |
| 04 LOL | 0.42 | **4/10** | Same wider, fuller face and specks; reads as a similar-looking man, not him |
| 05 OMG! | 0.41 | **3/10** | Generic stock "surprised man": bushy mustache, much lighter skin, different face |
| Outfit | — | **9/10** | Shirt, red tie and watch are correct |

**Overall: about 4/10.** The stickers capture the person's "type", not the person.

### Experiment results (same photo and seeds; App score = the same SFace similarity the app displays)

| Approach | Hi! | LOL | OMG! |
|---|---|---|---|
| Current: draw a new picture from the face + body references | 0.62 | 0.42 | 0.41 |
| Edit the actual photo in place (expression + arms in one step) | **0.74–0.79** | **0.52–0.57** | 0.40 |
| Edit the photo in place, **arms only** (face frozen) | **0.885** | **0.79** | **0.89** |
| **Arms only, then expression on a 768 px close-up** (chosen) | **0.79** | **0.66** | **0.50** |

Visual check:
- **In-place edits:** clearly him. Thin mustache, stubble, his hair, nose and smile lines.
- **Arms-only:** keeps his real 3/4 head angle too.
- **Big expression changes in one step (OMG!):** still produce a generic face.
- **Close-up expression step:** copied the trees and track from `face.png` into the sticker, because that reference still has the photo background.
- **Two-step OMG!:** the face is clearly closer to him (his hair, thin mustache, stubble and head angle), but the blend shows **ghost fingers and a ghost ear**. The expression step moved the hands slightly, and today's wide ellipse mask (`paste_feathered_ellipse`) blends over them. See fix 4.1 g.

## 2. Diagnosis

1. **The current pipeline invents a new picture.** New framing, a frontal head and new arms force the 4B model to re-imagine the face, so it drifts toward a generic face. Edits that stay aligned with the real photo keep identity, because the model copies the pixels that are already in place.
2. **Large expression changes at small face size drift.** The face is about 180 px wide in a 768 canvas. Doing the expression on a high-resolution close-up gives the model more pixels for the face.
3. **Reference hygiene:**
   - `face.png` keeps the photo background, which leaked into the output.
   - The u2netp background remover leaves a grey "smoke" halo: about 120k half-transparent pixels on this photo.
4. **Likeness/Cartoon shading** (`imaging.portrait_render`) turns stubble into black specks. Its Canny edges fire on skin texture.

## 3. New pipeline ("photo-edit route")

Used for **Realistic** (new default), **Likeness** and **Cartoon**. Chibi and Comic keep today's drawn route.

```text
Pack creation (CPU, once)
  reference.png ─► person_cutout() (hardened mask) ─► on white
     ├─► canvas.png      768² chest-up, aligned on the real face (head ≈ 45% of height)
     ├─► face-clean.png  512² face crop on WHITE (no trees/track)
     └─► face-embedding.npy (unchanged)

Per reaction (GPU)
  Step 1  pose stage  = GESTURE EDIT on canvas.png  (image 2 = face-clean.png)
          "change only the arms and hands; keep head, face, expression, angle unchanged"
          best-of-N until face similarity ≥ GESTURE_FLOOR (0.75)
  Step 2  face stage  = EXPRESSION EDIT on a 768² close-up crop of step 1 (image 2 = face-clean.png)
          "change only the facial expression; same person, same hands, white background"
          align by landmarks → colour-match → feathered paste back
          best-of-N until similarity ≥ EXPRESSION_FLOOR (0.55)
          if every candidate < EXPRESSION_MIN (0.45): keep step-1 image (original expression)
             and note "Kept your original expression to preserve your face"
  Step 3  Likeness/Cartoon only: portrait_render() with the speckle fix
  Then    hardened cutout → compose 512² sticker → export (unchanged)
```

No new models, no new downloads, no database migration. The existing `pose`/`face` stages and `candidate` keys carry the new steps, so recovery, cancellation and cleanup keep working.

---

## 4. Changes, file by file

### 4.1 `backend/app/imaging.py`

**a) Hardened person mask.** Replace direct `remove_background()` use for photo work.

```python
from scipy import ndimage

def person_cutout(image: Image.Image) -> Image.Image:
    cutout = remove_background(image)
    solid = np.asarray(cutout.getchannel("A")) > 128          # drop the grey haze
    labels, count = ndimage.label(solid)
    if not count:
        raise ValueError("Background removal did not find a person")
    sizes = np.bincount(labels.ravel())[1:]
    keep = np.isin(labels, np.flatnonzero(sizes >= 0.02 * sizes.max()) + 1)   # body + detached hands
    keep = ndimage.binary_fill_holes(keep)
    cutout.putalpha(Image.fromarray(keep.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1)))
    return cutout


def on_white(cutout: Image.Image) -> Image.Image:
    white = Image.new("RGB", cutout.size, "white")
    white.paste(cutout.convert("RGB"), mask=cutout.getchannel("A"))
    return white
```

**b) Aligned canvas.** This is the version validated in the experiment.

```python
def aligned_canvas(person: Image.Image, face, size: int = 768, scale: float = 3.0) -> Image.Image:
    """Chest-up square around the real face; outside the photo is white so arms can be raised."""
    x, y, w, h = face[:4]
    side = scale * h
    left, top = round(x + w / 2 - side / 2), round(y - 0.5 * h)
    canvas = Image.new("RGB", (round(side), round(side)), "white")
    canvas.paste(person, (-left, -top))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)
```

**c) Clean face crop:** `face_reference(on_white(person_cutout(image)))` → `face-clean.png`.

**d) Seam colour match.** Use it in step 2 before pasting.

```python
def match_colors(patch: Image.Image, target: Image.Image) -> Image.Image:
    """Match LAB mean/std of the pasted face to the step-1 crop; avoids visible seams and skin-tone shifts."""
    p = cv2.cvtColor(np.asarray(patch.convert("RGB")), cv2.COLOR_RGB2LAB).astype(np.float32)
    t = cv2.cvtColor(np.asarray(target.convert("RGB")), cv2.COLOR_RGB2LAB).astype(np.float32)
    p = (p - p.mean((0, 1))) / (p.std((0, 1)) + 1e-6) * t.std((0, 1)) + t.mean((0, 1))
    return Image.fromarray(cv2.cvtColor(np.clip(p, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB))
```

**e) `portrait_render` speckle fix.**
- Raise the Canny thresholds for `likeness` (for example 120/240).
- Drop edge components smaller than about 25 px (`cv2.connectedComponentsWithStats`) so stubble and pores stop becoming black dots.
- Keep the geometry-preserving behaviour.

**g) Tight landmark mask + ghost guard.** This fixes the double-exposed fingers and ear seen in the two-step OMG! test.

- Build the paste mask from YuNet's five landmarks instead of a fixed ellipse. With *d* = the distance between the eyes:
  - centre: between the eye line and the mouth line
  - horizontal radius ≈ 1.15 *d*
  - vertical radius ≈ 1.6 *d* (brow to chin)
  
  Cheeks, mouth and eyes are covered; ears and fingers beside the face are left out.
- Feather about 6% of the crop side.
- **Ghost guard:** after merging, measure the mean absolute difference between `base` and `aligned` in the feather band. If it exceeds a threshold, the expression step moved something there (hands, ears). Shrink the mask to 85% and re-merge. If it still exceeds the threshold, try the next candidate.
- Test: synthetic "hand" bars beside a face must not appear twice after merging.

**f) Final sticker cutout.** For photographic routes, `worker.process_cartoon` uses `person_cutout()` instead of `remove_background()`.

### 4.2 `backend/app/likeness.py` — `ensure_references`

- Also produce `canvas.png` and `face-clean.png`. Detect the face on the full-resolution `reference.png` and build the canvas from the hardened cutout.
- Packs that already exist (including `d830aee6`) get these files on their next Redraw. No migration is needed.
- Return a small object or dict instead of the `(face, body)` tuple, and update both callers.

### 4.3 `backend/app/catalog.py`

- `STYLES`: put **`realistic` first** and make it the default.
- Add `PHOTO_ROUTE = {"realistic", "likeness", "cartoon"}`.
- New prompts. Keep them gender-neutral, because the app is for anyone.

```python
def gesture_edit_prompt(intent: Intent) -> str:
    return (
        "Edit image 1, a photo of a person. Image 2 is a close-up of the same person's face for reference. "
        "Keep the person's head, face, facial expression, hair, head angle, head size and head position exactly unchanged. "
        "Keep the clothes and accessories exactly as in the photo. "
        f"Change only the arms and hands to {intent.gesture}. Hands fully visible inside the frame and anatomically correct. "
        "Photorealistic photo, same lighting, plain solid white background. No text, no extra people."
    )


def expression_edit_prompt(intent: Intent) -> str:
    return (
        "Edit image 1, a close-up photo of a person. Image 2 is another photo of the same person. "
        f"Change only the facial expression to {intent.expression}. "
        "The person must remain exactly the same: identical face shape, jawline, cheekbones, nose, eye shape, eyebrows, "
        "facial hair, skin tone, skin texture, ears and hair. Keep the head angle, head position and size, the lighting, "
        "the plain white background and any hands or fingers exactly as in image 1. Photorealistic photo. No text."
    )
```

- Keep `artwork_prompt` and `face_refine_prompt` for Chibi and Comic.

### 4.4 Workflows

- Add `klein4b-expression-api.json` and `bindings-expression.json`. They are the face graph at **768²** (nodes 9 and 11), generated by `scripts/build_likeness_workflows.py` together with `klein4b-expression-human.json`.
- The pose graph is reused unchanged, with image 1 = canvas and image 2 = face-clean.
- `comfy.doctor()` checks all three graphs.

### 4.5 `backend/app/comfy.py`

- `workflow(name, values)`: accept `"expression"`, which maps to the new graph and bindings.
- `generate(..., route="draw" | "photo")`. When the route is `photo`:
  - **pose stage:** upload `{pack_id}-canvas.png` and `{pack_id}-face-clean.png`, prompt with `gesture_edit_prompt`.
  - **face stage:** upload `{attempt_id}-crop.png` (step-1 crop) and `{pack_id}-face-clean.png`, use graph `expression`, prompt with `expression_edit_prompt`.
  - `reference_hash` covers the actual uploaded inputs.
- Read the output node from the matching bindings file. Today line 207 only distinguishes `bindings.json` and `bindings-face.json`.

### 4.6 `backend/app/worker.py` — `generate_likeness`

Split it into `generate_drawn()` (today's code, for Chibi/Comic) and `generate_photo()`:

```python
def generate_photo(adapter, job_id, sticker_id, pack_id, intent, style, tone, seed, revision):
    refs = ensure_references(pack_id)
    reference = np.load(refs["embedding"], allow_pickle=False)
    base, base_score, best_seed = best_of(adapter, "pose", config.GESTURE_FLOOR, ...)          # step 1
    save_png(base, directory / f"{sticker_id}-art-{revision}-base.png")
    image, score, note = base, base_score, None
    faces = detect_faces(base, 0.5)
    if len(faces) == 1:                                                                         # step 2
        box = square_box(faces[0], 1.8, base.size)
        crop = base.crop(box).resize((768, 768), Image.Resampling.LANCZOS)
        def candidate(c):
            out = adapter.generate(..., stage="face", candidate=c, inputs={"crop": crop}, route="photo")
            aligned = align_by_landmarks(out, crop) or out      # aligned edit: same frame if landmarks move
            merged = paste_face_landmarks(base, match_colors(aligned, crop), box)   # 4.1 g: tight mask + ghost guard
            return merged, likeness(reference, merged)
        merged, merged_score = best_of_candidates(candidate, config.EXPRESSION_FLOOR)
        if merged_score is not None and merged_score >= config.EXPRESSION_MIN:
            image, score = merged, merged_score
        else:
            note = "Kept your original expression to preserve your face. Redraw to try a new expression."
    else:
        note = "Face not found after the gesture edit; review manually."
    if style in {"likeness", "cartoon"}:
        image = portrait_render(image, style)
        score = likeness(reference, image)
    return image, score, best_seed, note
```

- Keep the `active(job_id)` cancellation checks between every GPU call, and keep `record_score()` for every candidate.
- Use deterministic candidate seeds, the same formula as today.

### 4.7 `backend/app/config.py`

```python
GESTURE_FLOOR = float(os.environ.get("STICKERME_GESTURE_FLOOR", "0.75"))      # face must survive the arm edit
EXPRESSION_FLOOR = float(os.environ.get("STICKERME_EXPRESSION_FLOOR", "0.55")) # stop retrying above this
EXPRESSION_MIN = float(os.environ.get("STICKERME_EXPRESSION_MIN", "0.45"))     # below: keep original expression
```

These are provisional values from one photo. Calibrate them on more consented photos and log the scores.

### 4.8 `backend/app/main.py`

- `create_pack`: change the default to `style = Form("realistic")`. Create and save `canvas.png` and `face-clean.png` with the other references, before the engine check.
- `face_url`: serve `face-clean.png` when it exists.
- The export manifest and provenance need no schema change; they already store actual workflows, stage, candidate and score. Never export `canvas.png`, `face-clean.png` or the embedding.

### 4.9 `frontend/src/App.tsx`

- Default style: `'realistic'` (lines 116 and 258). Order: Realistic, Likeness, Cartoon, Chibi ("fun, less exact"), Comic.
- Copy changes:
  - Hero: "A little cartoon you" → "The real you, in every mood".
  - Progress: "We keep your face and change the gesture, then the expression…".
  - Preview notice.
- Show `likeness_note` under the badge, for example the "kept your original expression" message.
- Tip on the upload screen: **"Your stickers keep your photo's head angle — use a front-facing photo for front-facing stickers."**

### 4.10 `backend/app/cleanup.py`

- Also delete `input/StickerMe/{pack_id}-canvas.png` and `{pack_id}-face-clean.png`.

### 4.11 Scripts and housekeeping

- `scripts/likeness_ab.py`: add **variant F** (photo route) and a `--intents all` option for the full 12-reaction check.
- Delete the experiment files:
  - `runtime/comfyui/input/StickerMe-exp/`
  - `runtime/comfyui/output/StickerMe-exp/`
  - the scratchpad outputs (they contain the user's face)

---

## 5. Tests

| File | Add or update |
|---|---|
| `tests/test_likeness_inputs.py` | `person_cutout` removes a synthetic grey haze and keeps a detached hand; `aligned_canvas` is 768², has a white background and the face near the expected position; `face-clean` has white corners; `match_colors` moves LAB means; the speckle fix leaves fewer small edge components |
| `tests/test_workflow.py` | Expression graph: nodes 9 and 11 = 768, bindings resolve, canvas JSON matches the API |
| `tests/test_cartoon_flow.py` | The Realistic route submits canvas + face-clean with the gesture prompt, then a crop + face-clean with the expression prompt; when the expression score is below `EXPRESSION_MIN`, it keeps the step-1 image and sets the note; Chibi still uses the drawn route; prompts contain no "he/his/she/her"; the default style is `realistic` |
| `tests/test_engine_recovery.py` | Face-stage candidates > 0 recover independently; photo-route uploads are cleaned up |
| `tests/test_cutout_flow.py` | Cleanup removes the canvas and face-clean inputs |

Run `.\.venv\Scripts\python.exe -m pytest -q` and `npm.cmd run build --prefix frontend`.

## 6. Verification on the GPU (engine idle, worker paused)

1. **Variant F on the same photo, preview set:** Hi!/LOL/OMG! with fixed seeds. Target: every score ≥ 0.55; Hi! ≥ 0.75.
2. **Contact sheet review by eye:** same face shape, thin mustache, stubble, hair height, skin tone; no background leak; no specks.
3. **All 12 reactions:** record seconds per sticker, scores, and how often the expression fallback triggers. Target: the person recognises themself in at least 10 of 12.
4. **Real app flow:** create a Realistic pack in the browser → previews → Redraw one → approve → export. WebP files ≤ 100 KiB.
5. Update `Docs/Build-Status.md` and `Docs/likeness-implementation.md` with measured numbers only.

## 7. Cost

| Step | Estimate per sticker |
|---|---|
| Gesture edit (768² + two references) | ~55–60 s (measured) |
| Expression edit (768² close-up) | ~60–95 s (measured range) |
| **Total, no retries** | **~2–2.5 min** (vs ~1.3 min today) |

- **Estimates:** 3 previews ≈ 6–8 min; full pack of 12 ≈ 25–35 min, plus any retries.
- **To make it faster:**
  - expression crop at 512 instead of 768
  - `STICKERME_LIKENESS_RETRIES=0`

## 8. Trade-offs and limits

- **Head angle comes from the uploaded photo.** That is why the face stays his. For front-facing stickers, upload a front-facing photo.
- **Strong expressions are the hardest case:** surprise, an angry frown, closed sleepy eyes. Two safeguards apply:
  - the expression step works on a high-resolution close-up
  - the minimum-similarity check keeps the original face rather than a stranger's
  
  Some reactions may therefore keep a smile; the note says so and Redraw retries.
- **"Exact" applies to Realistic.** Likeness and Cartoon add shading on top of the same photo-accurate result.
- **Scores are advisory.** SFace similarity is a single local model, not proof of identity. Always check the faces yourself.
- **Possible future option:** for photographic expression changes beyond what Klein can do, a dedicated expression-retargeting model (for example LivePortrait) could animate the real photo. It needs new downloads and a licence review, so it is not part of this plan.

## 9. Order of work

1. [ ] `imaging.py`: `person_cutout`, `on_white`, `aligned_canvas`, `match_colors`, `paste_face_landmarks` (tight mask + ghost guard), speckle fix
2. [ ] `likeness.ensure_references` + `main.create_pack`: `canvas.png`, `face-clean.png`
3. [ ] `catalog.py` prompts, style order, `PHOTO_ROUTE`
4. [ ] Expression workflow + bindings + build script + doctor
5. [ ] `comfy.generate(route=...)`, uploads, output bindings
6. [ ] `worker.generate_photo` / `generate_drawn`, config floors, hardened final cutout
7. [ ] Cleanup paths, frontend default and copy, note display
8. [ ] Tests → pytest + frontend build
9. [ ] GPU variant F (3 previews) → review → 12 reactions → browser flow
10. [ ] Remove experiment files; update docs with measured results
