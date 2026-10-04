# StickerMe — Exact-face likeness fix

**Date:** 3 October 2026 · **Workspace:** `D:\Additional Project\Img_2_Sticker`
**Inputs analysed:** `Docs/work.md`; exported pack `Docs/stickerme-d6adcd73-040e-4515-980b-11e31ef97a4a` (12 artworks, `manifest.json`, `provenance.json`); the stored upload `runtime/packs/d6adcd73-…/reference.png` and the copy the engine received `runtime/comfyui/input/StickerMe/d6adcd73-….png`; `backend/app/*`; `workflows/*`; the pinned ComfyUI Flux2 code.

> **Honest target.** A cartoon can never be pixel-identical to a photo, because stylising changes the face. The achievable goal is a sticker that anyone who knows the person recognises immediately: the same face shape, eyes, nose, facial hair, skin tone and hair, drawn in a style. If you need photo-level identity, use the `realistic` or `likeness` style described in §4.1. `chibi` and `dramatic` will always look less like the person.

---

## 0. TL;DR — the changes that matter most

| # | Change | Why | Impact |
|---|---|---|---|
| 1 | Give the model a **high-resolution face crop** as a second reference image (face = image 1, body = image 2) | Today the face takes up only about 35 of the 1,024 reference tokens | ★★★★★ |
| 2 | **Stop shrinking the reference to 512×512** and **trim the black letterbox bars** | 55% of the reference image is padding or bars, not the person | ★★★★ |
| 3 | **Generate at 768×768 with chest-up framing** (head about 40% of the height); remove "generous empty padding" | The output face is drawn with only about 40 tokens | ★★★★ |
| 4 | **Rewrite the prompt with identity first.** Name the facial features, ban adding or removing facial hair, remove "simple flat colors" and "sticker art", add a `likeness` style | The current prompt pushes toward a template cartoon man | ★★★★ |
| 5 | **Face-detail second pass:** crop the generated face, redraw it against the real face, paste it back | Fixes the small-face problem directly (like ADetailer/FaceDetailer) | ★★★★ |
| 6 | **Likeness score + best-of-N:** YuNet + SFace (OpenCV, MIT/Apache-2.0) | No step checks likeness today; poor results pass silently | ★★★ |
| 7 | **Diffusion model Q4_K_M → Q8_0** (4.3 GB) or Q6_K (3.41 GB) | 4-bit quantisation loses fine facial detail | ★★ |

Do Phase 1 (items 1–4) first and A/B test it (§7). It needs no new AI models.

---

## 1. What is wrong — evidence from your pack

Comparing the 12 generated artworks with the uploaded photo:

- **Lost in every sticker:** the **mustache**, the **stubble/beard shadow**, the real **face shape** (it became rounder and younger), the **eye shape** (now generic dots), the **smile lines** and the **skin tone** (shifted lighter and more orange).
- **Kept well:** the white shirt, red tie, wristwatch, hair colour and volume. These are the **large regions** of the reference image.
- Stickers 05 and 08 contain a **white die-cut border drawn by the model itself**, caused by the words "sticker art" in the prompt. `compose_sticker` then adds a second outline, which wastes more pixels.

This pattern shows that the model keeps whatever it can actually *see* in the reference. The face is too small for it to see, so it fills in a stock cartoon face.

## 2. Root causes, ranked and measured

### 2.1 The face is starved of resolution in the reference (the main cause)
- `backend/app/comfy.py:75-81` `ComfyEngine.upload()` applies `ImageOps.pad(source, (512, 512), color="white")` to every reference.
- Your stored `reference.png` is **602×1024** with **black letterbox bars** (about 118 px at the top and 126 px at the bottom). Padding scales it to **301×512** inside a 512² canvas.
- The face (brow to chin) goes from **~167×215 px to ~84×108 px**.
- Flux2 latents are 128 channels at **1/16 resolution** (`comfy_extras/nodes_flux.py:56` `height // 16`; Flux2 `patch_size = 1`, `comfy/model_detection.py:279`). **One token = 16×16 px.**
- So the face is described by **≈5×7 ≈ 35 tokens out of 1,024 (≈3.4%)**. The shirt and background get most of the rest, which is why the outfit survives and the face does not.
- Breakdown of the 512² reference: person and scene ≈ 45%, white side padding ≈ 41%, black bars ≈ 14%.

### 2.2 The output face is drawn too small
- `workflows/klein4b-api.json` nodes `9` and `11` fix the output at **512×512**.
- The prompt says *"Show head, shoulders, upper torso and all requested hands completely with generous empty padding"* (`catalog.py:50`).
- The result is a face about 95–105 px wide, so **≈6×7 tokens** are available to draw a specific person. That is not enough for anyone to be recognisable.

### 2.3 The prompt steers toward a generic template (`backend/app/catalog.py:29-53`)
- The style text is *"clean 2D cartoon illustration, bold smooth outlines, **simple flat colors**, expressive face, **sticker art**"*. Flat colours remove stubble, shading and skin-tone detail, and "sticker art" causes the self-drawn borders.
- The identity clause is generic ("face shape, facial features"). It never names the cues that make the face recognisable: facial hair, eye shape, nose, jaw, teeth, moles.
- It says "Transform…", "Change the facial expression…", "Change the pose…" and "Redraw the body and hands…": three strong change instructions against one weak "keep" instruction.
- Some gestures force a zoomed-out shot: raised fists, a raised waving hand, a bowed head that hides the face.

### 2.4 Model capacity and precision (secondary)
- The model is FLUX.2 Klein **4B** (the smallest variant), quantised to **Q4_K_M**, with a 4-step distilled sampler. The text encoder Qwen3-4B is also Q4. 4-bit weights cost fine detail, and fine detail is what identity depends on.

### 2.5 Nothing checks likeness
- `worker.process_cartoon` only rejects byte-identical artwork (`worker.py:125-129`). A sticker that looks like a different person is accepted.

### 2.6 Minor contributors
- Background clutter (trees, flags, track) competes for reference tokens.
- `normalize_upload` caps the stored photo at 1024 px (`imaging.py:33`), which discards detail from higher-resolution phone photos.
- Your photo is a 3/4 head turn in harsh sunlight, so a front-facing, evenly lit photo would help (§4.5). Fixes 2.1–2.3 matter much more than this.

---

## 3. Target pipeline

```text
Upload
 └─ normalize (keep up to 2048 px) → trim letterbox bars
 └─ YuNet face detection ─ none / several / too small → 400 with a clear message
 └─ save  face.png   (square head crop, 512², from full-res photo)
          body.png   (person on white, ≈0.25 MP, sides multiple of 16)
          face-embedding.npy (SFace, local only, never exported)

Per reaction
 Pass 1  refs [image 1 = face.png, image 2 = body.png] + identity-first prompt
         → 768×768 chest-up artwork            (best of N seeds by likeness score)
 Pass 2  detect face in pass-1 art → square crop → 512²
         refs [image 1 = crop, image 2 = face.png] + "repaint the face only" prompt
         → align by 5 landmarks → feathered ellipse paste-back
         → keep the pass-2 result only if its likeness score ≥ pass-1 score
 Then    existing white-background cleanup → compose 512² sticker → export
```

The ComfyUI engine already supports multi-reference for Flux2: chained `ReferenceLatent` nodes give each reference its own index (`comfy/model_detection.py:276-277` sets `default_ref_method = "index"`, `ref_index_scale = 10`; the loop is in `comfy/ldm/flux/model.py:360-392`). **No custom nodes are needed.**

---

## 4. Changes, file by file

### Phase 1 — biggest gain, no new AI models

#### 4.1 `backend/app/catalog.py` — prompts and styles

```python
STYLES = {
    "likeness": "semi-realistic cartoon portrait with clean line art and soft cel shading, realistic facial proportions",
    "cartoon": "clean 2D cartoon illustration with bold smooth outlines and soft cel shading, detailed recognizable face",
    "realistic": "photorealistic portrait of the real person, natural skin texture, soft studio lighting",
    "chibi": "cute chibi illustration with a large head that keeps the person's real facial features, small upper body",
    "comic": "colorful comic-book illustration with ink outlines and cel shading, detailed recognizable face",
}
TONES = {
    "playful": "playful and energetic, expressive but friendly",
    "warm": "warm and friendly, gentle expressive emotions",
    "dramatic": "strong, theatrical emotions while keeping the person's exact face proportions",
}


def artwork_prompt(intent: Intent, style: str, tone: str) -> str:
    return (
        "Image 1 is a close-up photo of a person's face. Image 2 shows the same person's hair, clothes and accessories. "
        f"Draw this exact person as a {STYLES[style]}. "
        "The face must be instantly recognizable as the person in image 1: copy the exact face shape, jawline, cheekbones, "
        "eye shape and spacing, eyebrows, nose, lips, teeth, ears and hairline, and keep any mustache, beard, stubble, moles, "
        "glasses or piercings exactly as shown. Do not add or remove facial hair or accessories. "
        "Match the skin tone of image 1 exactly. Keep the hairstyle, clothing, colors and accessories from image 2. "
        f"Change only the expression and the pose. Expression: {intent.expression}. Pose: {intent.gesture}. Mood: {TONES[tone]}. "
        "Framing: chest-up, the head is large and fills about 40 percent of the image height, the whole face is clearly visible, "
        "hands stay close to the face or chest and fully inside the frame. "
        "One person only, plain solid white background, no border or outline around the figure, "
        "no text, letters, logos, panels or extra people."
    )


def face_refine_prompt(intent: Intent, style: str) -> str:
    return (
        "Image 1 is a drawing of a face. Image 2 is a photo of the real person. "
        "Repaint only the face in image 1 so it is unmistakably the person in image 2: same face shape, jawline, eyes, eyebrows, "
        "nose, lips, teeth, ears and hairline, and the same mustache, beard, stubble, moles and glasses as image 2. "
        "Match the skin tone of image 2. "
        f"Keep everything else from image 1: the {STYLES[style]} line art and colors, the expression ({intent.expression}), "
        "head angle, position and size, hair outline, hands and white background. Do not move, rotate or resize the head. No text."
    )
```

Gesture edits in `INTENTS`, so the framing stays tight and the face stays visible:

| Intent | New `gesture` |
|---|---|
| greeting | `raising one open hand beside the face and waving hello` |
| apology | `head tilted slightly forward with the eyes still visible, one hand over the heart` |
| congrats | `raising both fists beside the head in celebration with a few confetti pieces` |

Keep the other gestures as they are.

- Put `likeness` first in `STYLES` and make it the default (see `main.py` and the frontend below).
- `test_prompts_require_distinct_expressions_and_gestures` still passes.

#### 4.2 `backend/app/imaging.py` — bar trimming, face crop, body reference

Add `opencv-python-headless>=4.10,<5` to `pyproject.toml` (app environment only, not the engine environment). `onnxruntime` and `scikit-image` are already installed.

```python
import cv2
from .config import FACE_MODELS_DIR

def normalize_upload(data: bytes) -> Image.Image:
    ...
        image = trim_bars(image.convert("RGB"))
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)   # was 1024: keep facial detail
        return image


def trim_bars(image: Image.Image, tolerance: int = 10) -> Image.Image:
    """Remove solid letterbox/pillarbox strips (screenshots, padded phone photos)."""
    rgb = np.asarray(image).astype(np.int16)

    def uniform(line):
        return (np.abs(line - np.median(line, axis=0)).max(axis=1) <= tolerance).mean() > 0.98

    top, bottom, left, right = 0, rgb.shape[0], 0, rgb.shape[1]
    while bottom - top > 2 and uniform(rgb[top, left:right]): top += 1
    while bottom - top > 2 and uniform(rgb[bottom - 1, left:right]): bottom -= 1
    while right - left > 2 and uniform(rgb[top:bottom, left]): left += 1
    while right - left > 2 and uniform(rgb[top:bottom, right - 1]): right -= 1
    if (bottom - top) * (right - left) < 0.4 * rgb.shape[0] * rgb.shape[1]:
        return image                      # refuse suspicious over-crops
    return image.crop((left, top, right, bottom))


def detect_faces(image: Image.Image, score_threshold: float = 0.8) -> np.ndarray:
    """YuNet rows: x, y, w, h, 5 landmarks (10 values), score. Created per call: cheap and thread-safe."""
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(str(FACE_MODELS_DIR / "face_detection_yunet_2023mar.onnx"), "",
                                         (bgr.shape[1], bgr.shape[0]), score_threshold, 0.3, 50)
    _, faces = detector.detect(bgr)
    return np.empty((0, 15), np.float32) if faces is None else faces


def face_reference(image: Image.Image, size: int = 512) -> Image.Image:
    faces = detect_faces(image)
    if len(faces) == 0:
        raise ValueError("No clear face found. Use a well-lit, front-facing photo of one person.")
    faces = faces[np.argsort(-(faces[:, 2] * faces[:, 3]))]
    if len(faces) > 1 and faces[1, 2] * faces[1, 3] > 0.4 * faces[0, 2] * faces[0, 3]:
        raise ValueError("More than one face found. Use a photo with only one person.")
    x, y, w, h = faces[0, :4]
    if min(w, h) < 64:
        raise ValueError("The face is too small in this photo. Use a closer photo.")
    side = max(w, h) * 2.0                       # hair, ears, chin and a little neck
    cx, cy = x + w / 2, y + h / 2 - 0.1 * h      # bias upward for hair
    box = (max(0, round(cx - side / 2)), max(0, round(cy - side / 2)),
           min(image.width, round(cx + side / 2)), min(image.height, round(cy + side / 2)))
    return ImageOps.pad(image.crop(box), (size, size), color="white", method=Image.Resampling.LANCZOS)


def body_reference(image: Image.Image, megapixels: float = 0.25) -> Image.Image:
    try:
        cutout = remove_background(image)
        alpha = cutout.getchannel("A")
        white = Image.new("RGB", cutout.size, "white")
        white.paste(cutout.convert("RGB"), mask=alpha)
        image = white.crop(alpha.getbbox())
    except ValueError:
        pass                                      # keep the scene rather than fail
    scale = (megapixels * 1024 * 1024 / (image.width * image.height)) ** 0.5
    width, height = (max(16, round(value * scale / 16) * 16) for value in image.size)
    return image.resize((width, height), Image.Resampling.LANCZOS)
```

`config.py`: add `FACE_MODELS_DIR = ROOT / "runtime" / "models" / "face"`. Use a fixed path under `ROOT`, not `DATA_DIR`, so the smoke scripts that relocate `STICKERME_DATA_DIR` still find the model files.

#### 4.3 `backend/app/main.py` — `create_pack` (lines 115-171)

- Default style: `style: str = Form("likeness")`.
- Inside the existing `try: … except ValueError → 400` block, after `normalize_upload`, build `face = face_reference(image)` and `body = body_reference(image)`. Do this **before** `engine_doctor()`, so a bad photo is rejected immediately.
- Save `reference.png`, `face.png`, `body.png` and `face-embedding.npy` (§4.8) in the pack directory.
- Line 445: replace the hard-coded `"FLUX.2 Klein 4B Q4_K_M"` with the `unet_name` read from the workflow JSON, so the export stays correct after the model upgrade.

#### 4.4 `backend/app/comfy.py` — upload both references at their real size

- `upload(self, image: Image.Image, name: str) -> str`: **remove `ImageOps.pad(..., (512, 512))`** and upload the given image as-is.
- In `generate()`, call a new `ensure_references(pack_id)`. For packs created before this change, it builds `face.png` and `body.png` from `reference.png`. If no face is found, raise a clear error (no silent fallback). Then upload `f"{pack_id}-face.png"` and `f"{pack_id}-body.png"`.
- `reference_hash` = SHA-256 of `face.png` bytes followed by `body.png` bytes.
- Generalise `workflow()` to `workflow(name: str, values: dict) -> dict` so it can load a graph plus its bindings file (`klein4b-api.json` + `bindings.json`, `klein4b-face-api.json` + `bindings-face.json`).
- Add `stage` (`"pose"` | `"face"`) and `candidate` (int) parameters to `generate()`, and **add both to the attempt lookup at line 112**. Without this, pass 2 or a best-of-N retry would find the completed pass-1 attempt and return its image again.

#### 4.5 `workflows/klein4b-api.json` + `bindings.json` — two references, 768² output

```json
{
  "1":  {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf"}},
  "2":  {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "Qwen3-4B-Q4_K_M.gguf", "type": "flux2"}},
  "3":  {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
  "4":  {"class_type": "LoadImage", "inputs": {"image": "face.png"}},
  "5":  {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["3", 0]}},
  "6":  {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
  "7":  {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["6", 0], "latent": ["5", 0]}},
  "17": {"class_type": "LoadImage", "inputs": {"image": "body.png"}},
  "18": {"class_type": "VAEEncode", "inputs": {"pixels": ["17", 0], "vae": ["3", 0]}},
  "19": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["7", 0], "latent": ["18", 0]}},
  "8":  {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["19", 0]}},
  "9":  {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 768, "height": 768, "batch_size": 1}},
  "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
  "11": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": 768, "height": 768}},
  "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
  "13": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["19", 0], "negative": ["8", 0], "cfg": 1}},
  "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["10", 0], "guider": ["13", 0], "sampler": ["12", 0], "sigmas": ["11", 0], "latent_image": ["9", 0]}},
  "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["3", 0]}},
  "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": "StickerMe"}}
}
```

`bindings.json`: `"face": ["4","image"]`, `"body": ["17","image"]`; keep `prompt`, `seed`, `output` and `prefix`.

- **Node 9 and node 11 sizes must match.** The scheduler derives its shift from the token count. Add a test for this.
- Regenerate `workflows/klein4b-human.json` with nodes 17–19 and their links (`test_workflow.py` checks that the canvas matches the API graph).
- Fallback if this is too slow: change 768 → 640 in nodes 9 and 11.
- Simpler alternative if two-reference prompting misbehaves in A/B testing: use one reference, the trimmed full photo scaled to about 1 MP (`ImageScaleToTotalPixels` already exists in the engine). The face then gets about 300 tokens instead of 35, at a higher token cost.

### Phase 2 — face-detail second pass

#### 4.6 `workflows/klein4b-face-api.json` + `bindings-face.json` (new)
- Same graph as §4.5, with node `4` = the crop of the generated face (**image 1**), node `17` = `face.png` (**image 2**), and nodes 9/11 at **512×512**. The output has the same size as the crop, so the geometry lines up.
- Upload the crop as `StickerMe/{attempt_id}-crop.png`, so cleanup can target it by attempt ID.

#### 4.7 `backend/app/worker.py` — `process_cartoon` (lines 91-150)

```python
image, score = best_pose_candidate(...)            # Pass 1, best-of-N (§4.8)
faces = detect_faces(image, score_threshold=0.5)   # lower threshold for drawn faces
if FACE_REFINE and len(faces):
    face = faces[np.argmax(faces[:, 2] * faces[:, 3])]
    box = square_box(face, scale=1.6, bounds=image.size)
    crop = image.crop(box).resize((512, 512), Image.Resampling.LANCZOS)
    refined = adapter.generate(..., stage="face", candidate=0, inputs={"crop": crop}, prompt=face_refine_prompt(...))
    refined = align_by_landmarks(refined, crop)     # cv2.estimateAffinePartial2D on 5 YuNet landmarks
    merged = paste_feathered_ellipse(image, refined.resize(box_size), box, feather=0.08)
    merged_score = likeness(reference_embedding, merged)
    if merged_score is not None and (score is None or merged_score >= score):
        image, score = merged, merged_score          # never accept a refine that lowers likeness
elif FACE_REFINE:
    sticker.likeness_note = "face not detected in artwork; review manually"
```

- Save the pass-1 image as `{sticker_id}-art-{revision}-base.png` for auditing, and the final image as the normal `-art-{revision}.png`.
- Keep the existing `active(job_id)` cancellation checks between every GPU call.
- If the pasted face shows a colour seam, match the mean and standard deviation (in LAB) of the pasted ellipse to a 10 px ring around it before blending.

### Phase 3 — measure likeness and select the best

#### 4.8 New `backend/app/likeness.py`

```python
import cv2, numpy as np
from .config import FACE_MODELS_DIR
from .imaging import detect_faces

def _recognizer():
    return cv2.FaceRecognizerSF.create(str(FACE_MODELS_DIR / "face_recognition_sface_2021dec.onnx"), "")

def embedding(image, score_threshold=0.8):
    faces = detect_faces(image, score_threshold)
    if len(faces) == 0:
        return None
    face = faces[np.argmax(faces[:, 2] * faces[:, 3])]
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    recognizer = _recognizer()
    return recognizer.feature(recognizer.alignCrop(bgr, face)).copy()

def likeness(reference: np.ndarray, image) -> float | None:
    feature = embedding(image, score_threshold=0.5)
    return None if feature is None else float(_recognizer().match(reference, feature, cv2.FaceRecognizerSF_FR_COSINE))
```

- **Best-of-N in the worker:** candidate seeds are derived deterministically, `(sticker.seed + candidate * 1_000_003) % (2**31 - 1) + 1`, so crash recovery reuses the same attempts. Stop at the first score ≥ `LIKENESS_FLOOR`; otherwise keep the highest score. Store the chosen seed on `sticker.seed`.
- **Threshold:** OpenCV's published cosine threshold for SFace (0.363) is calibrated for **photo vs photo**. Drawings score lower. Start with a provisional floor of **0.30**, log the scores, and calibrate it on your own consented photos. Treat `None` (no face detected) as "needs review", **not** as a failure.
- **Model files** (new `workflows/face-models.json`, downloaded by `setup.ps1` into `runtime/models/face/`, pinned commit + SHA-256 like `models.json`):
  - `face_detection_yunet_2023mar.onnx`, OpenCV Zoo, **MIT**, works with OpenCV 4.x
  - `face_recognition_sface_2021dec.onnx`, OpenCV Zoo, **Apache-2.0**
- **Do not use InsightFace `buffalo_l`/`antelopev2`.** Their pretrained weights are licensed for non-commercial research only.
- **Privacy:** `face-embedding.npy` is biometric data. Keep it in the pack directory only, never put it in the export ZIP or `provenance.json`, and delete it with the pack (it lives inside the pack directory, so existing deletion covers it).

#### 4.9 Database — `backend/app/db.py` + `migrations.py` (new version 3)
- `JobAttempt.stage: String(16), default "pose"`, `JobAttempt.candidate: Integer, default 0`.
- `Sticker.likeness_score: Float | None`, `Sticker.likeness_note: Text | None`.
- Add a `version=3` block in `migrations.upgrade()`. It inspects the existing columns first, because on a fresh database `metadata.create_all` in version 1 already creates them, then `ALTER TABLE … ADD COLUMN` for whatever is missing.
- `serialize_pack()` (`main.py:56-80`): add `likeness_score` and `likeness_note` for each sticker.

### Phase 4 — model precision

#### 4.10 `workflows/models.json` + `klein4b-api.json` node 1
- Switch the diffusion model to **`flux-2-klein-4b-Q8_0.gguf` (4.3 GB)**, which is close to bf16 quality. Pin the repository revision and SHA-256 from the Hugging Face file page, the same way the current entry is pinned. `download_engine.py` already routes `flux-2*` files to `models/unet`.
- **RAM risk:** your earlier full-pack run reached 13.96 GiB of 15.2 GiB whole-system RAM. Q8 adds about 1.7 GB. If the system starts paging, use **`Q6_K` (3.41 GB)** instead. Leave the text encoder at Q4 for now, because it runs on the CPU and Q8 would add RAM pressure.
- **Do not move to Klein 9B.** Its licence is non-commercial, it needs about 19.6 GB VRAM (distilled) and a Qwen3-8B text encoder, so it does not fit a 6 GB GPU with 15 GB RAM.
- Keep 4 steps and CFG 1. The distilled model is tuned for that.

### Phase 5 — upload guidance and UI (`frontend/src/App.tsx`)
- Style picker: add **"Likeness (recommended)"** first and make it the default (`useState('likeness')` at line 116 and in the reset at line 258). Add "Realistic". Label `chibi` as "fun, less exact".
- Upload screen guidance: one person, face toward the camera, even light, no sunglasses or mask, face filling at least about 1/4 of the photo width, no beauty filters.
- After creation, show **"This is the face we'll use"** with the `face.png` crop, served by a new `GET /api/packs/{id}/face.png` that follows the `stickers/{sticker_id}.png` route pattern. Offer "Wrong face? Start over".
- Previews and editor: show a likeness badge (High / Medium / Low / "Check manually") from `likeness_score`, and highlight **Redraw** when the score is low.
- Optional later: accept a second face photo (for example front plus 3/4 view) as an extra reference image.

### Phase 6 — housekeeping that the change requires
- `backend/app/cleanup.py:13`: also delete `input/StickerMe/{pack_id}-face.png`, `{pack_id}-body.png` and `{attempt_id}-crop.png` for each owned attempt.
- `comfy.py` `doctor()`: check the nodes of **both** workflow graphs and that the two face ONNX files exist; show this in `/api/doctor`.
- Export (`main.py:445-480`): add `stage`, `candidate` and `likeness_score` to `provenance.json`. Never include `face.png` or the embedding unless the user explicitly opts in.
- Update `workflows/README.md`, `README.md` and `Docs/Build-Status.md` with the new pipeline and measured results.

---

## 5. Settings (`backend/app/config.py`)

```python
FACE_MODELS_DIR = ROOT / "runtime" / "models" / "face"
FACE_REFINE = os.environ.get("STICKERME_FACE_REFINE", "1") == "1"       # Phase 2 on/off
LIKENESS_RETRIES = int(os.environ.get("STICKERME_LIKENESS_RETRIES", "1"))  # extra pass-1 seeds
LIKENESS_FLOOR = float(os.environ.get("STICKERME_LIKENESS_FLOOR", "0.30")) # provisional; calibrate
```

Output and reference sizes stay inside the workflow JSON files, and tests check that they match.

## 6. Tests to add or update

| File | What to check |
|---|---|
| `tests/test_workflow.py` | Bindings for `face`/`body`; chain `7 → 19`; node 9 size = node 11 size; canvas parity for nodes 17–19; the same checks for `klein4b-face-api.json` |
| new `tests/test_likeness_inputs.py` | `trim_bars` removes synthetic black bars and does not over-crop a normal photo; `face_reference` finds the face in `skimage.data.astronaut()` and returns 512² containing the detected box; no-face, two-face and tiny-face images raise the right `ValueError` |
| `tests/test_cartoon_flow.py` | Create with a no-face image → 400; the mocked engine receives two uploads; the prompt contains "image 1" and "Do not add or remove facial hair"; a low mocked score triggers one retry with a **different** seed and keeps the best; a refine that lowers the score is rejected |
| `tests/test_engine_recovery.py` | The attempt lookup is separated by `stage`/`candidate`; pass 2 never reuses the pass-1 history |
| `tests/test_migrations_and_masks.py` | Version 3 adds the columns to a version-2 database without data loss |
| `tests/test_cutout_flow.py` | Cleanup also removes the face, body and crop engine inputs |

## 7. Verification — A/B acceptance

1. Run `.\.venv\Scripts\python.exe -m pytest -q` and `npm.cmd run build --prefix frontend`.
2. Add `scripts/likeness_ab.py`. It takes a **consented** photo path and runs the three preview intents with **fixed seeds** under these configurations:
   - **A** baseline (current code)
   - **B** Phase 1
   - **C** Phase 1 + 2
   - **D** C + Q8_0
   
   For each, it records seconds per sticker, peak sampled VRAM/RAM, the SFace score per sticker, and a contact sheet with the reference face crop in the first cell.
3. Extend `scripts/smoke_cartoon_pack.py` to write likeness scores into `result.json` and add the face crop to the contact sheet.
4. **Accept when:** the median likeness score rises clearly from A to C, **and** a person who knows the subject, shown the sheets blind, picks C over A and recognises the person in at least 10 of 12 stickers.
5. Run GPU benchmarks **only while the engine is idle** (the `work.md` guardrails apply).

## 8. Performance budget (estimate — measure it)

| Run | Image tokens per sticker | vs today |
|---|---|---|
| Today: 512² output + 512² reference | 1,024 + 1,024 = 2,048 | 1× |
| Pass 1: 768² output + 512² face + ~0.25 MP body | 2,304 + 1,024 + ~1,000 ≈ 4,300 | ≈2.1× tokens |
| Pass 2: 512² output + two 512² references | 1,024 + 1,024 + 1,024 = 3,072 | ≈1.5× tokens |

- Today the time is about 33–36 s per sticker and 474 s per 12-sticker pack.
- **Estimate:** 60–120 s per sticker with passes 1 and 2, so about 12–24 min per pack, plus any best-of-N retries.
- To reduce time:
  - output 640² instead of 768²
  - body reference at 0.15 MP
  - `STICKERME_LIKENESS_RETRIES=0`
  - pass 2 only for stickers whose pass-1 score is below the floor

## 9. What not to do

- Do not chain generated stickers as references for the next sticker. Identity drift compounds, so keep using the original photo, as the app does today.
- Do not use InsightFace pretrained models (non-commercial licence) or Klein 9B (non-commercial, too large).
- Do not train a per-user LoRA. It needs many photos and GPU training time, and training is outside this release's scope.
- Do not silently fall back to the photo cutout when no face is found. Reject with a helpful message.
- Do not claim "exact" likeness in the UI. Show the measured score and keep **Redraw**.

## 10. Implementation order (checklist)

1. [ ] Add `opencv-python-headless` and the face ONNX files to setup (pinned + SHA-256).
2. [ ] `imaging.py`: `trim_bars`, 2048 cap, `detect_faces`, `face_reference`, `body_reference`.
3. [ ] `main.py`: validate the face at creation, save `face.png`/`body.png`/`face-embedding.npy`, default style `likeness`, dynamic engine label.
4. [ ] `catalog.py`: new prompt, styles, tones, gesture edits.
5. [ ] Workflow JSON (API + human), bindings; `comfy.py` upload/`workflow()`/`ensure_references`.
6. [ ] Tests from §6 for Phase 1 → pytest → A/B run **A vs B**.
7. [ ] Migration v3 + `stage`/`candidate` attempt keys + `likeness.py` + best-of-N.
8. [ ] Face-detail pass (`klein4b-face-api.json`, worker crop/align/paste, keep-if-better).
9. [ ] Cleanup, doctor, provenance updates → A/B **C**.
10. [ ] Q8_0 (or Q6_K) download + pin → A/B **D**; watch RAM.
11. [ ] Frontend: likeness style default, face preview, likeness badge, guidance text → `npm.cmd run build`.
12. [ ] Update `Build-Status.md` and READMEs with measured numbers only.

---

*Sources for external model facts:* [FLUX.2-klein-4B model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) (Apache-2.0), [Comfy blog — FLUX.2 klein](https://blog.comfy.org/p/flux2-klein-4b-fast-local-image-editing) (VRAM by variant), [unsloth/FLUX.2-klein-4B-GGUF](https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF/tree/main) (Q6_K 3.41 GB, Q8_0 4.3 GB), [FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B) (non-commercial), [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT), [OpenCV Zoo SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) (Apache-2.0).
