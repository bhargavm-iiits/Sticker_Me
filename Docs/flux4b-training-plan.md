# FLUX.2 Klein 4B training plan for StickerMe

Prepared 4 October 2026. Confirmed scope: generate recognizable cartoon reaction stickers for **any uploaded person**, using one consistent cartoon style. The user wants public dataset recommendations and training on the existing laptop GPU only (RTX 4050, 6 GB VRAM, approximately 16 GB RAM). No training has run and no trained checkpoint exists.

**Model choice**

Use `black-forest-labs/FLUX.2-klein-base-4B`, the undistilled four-billion-parameter foundation model, for training. The current app uses a Q6 GGUF of the distilled 4B model for inference. Base versus distilled describes training/inference behavior; BF16 versus Q6 describes weight representation. Quantization does not reduce the model's parameter count.

The [official model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B) identifies Base as the full-capacity model and demonstrates a 50-step inference configuration. The existing four-step distilled workflow must not be reused unchanged for Base inference.

LoRA also runs on the complete 4B architecture: it changes a limited set of adapter weights. Full fine-tuning updates the transformer weights themselves. Both options retain the four-billion-parameter foundation. Full fine-tuning is a training method, not a guarantee of better identity or anatomy. Conventional full transformer training is outside this laptop's memory capacity. The local candidate is a low-memory paired edit LoRA on the same 4B Base, with frozen VAE/text encoder. Its memory fit still needs measurement; this document does not substitute adapter training for a completed full fine-tune.

**What “exact face” can mean**

For cartoons, the acceptance target is that the person immediately recognizes their identity: face shape, eye spacing, nose, facial hair, hairline, age impression, skin tone, and distinguishing features. Those can be learned and evaluated, but neural generation cannot promise an exact face or perfect anatomy for every upload.

A cartoon changes pixels and a new expression changes facial geometry. A pixel-identical face would require keeping the original photo face, which is a separate photographic sticker mode. Continue offering that mode with original-head preservation. Evaluate the trained cartoon route on its own, without forcing a photographic head or the current posterization filter onto its drawing.

**Train the transformation, rather than memorizing one person**

Each example should contain an original person photo, an approved text-free cartoon of that same person, and an edit instruction describing the requested expression and gesture. Keep the style consistent across target images while varying people, head angles, outfits, lighting, backgrounds, and emotions.

Paired edit-LoRA training is demonstrated in [BFL's practical guide](https://huggingface.co/blog/black-forest-labs/flux-2-klein-lora). It is a useful starting method for testing dataset quality. Full-transformer training needs its own trainer configuration and memory profiling; the paired adapter recipe is not an already validated full-fine-tuning implementation.

Recommended data stages below are **project planning targets**, not proven minimums:

| Stage | Proposed data | Purpose |
|---|---|---|
| Dataset pilot | 100–200 carefully reviewed pairs across multiple people and reactions | Verify that targets preserve identity, instructions are usable, and training learns the intended transformation |
| General-person training | Expand toward thousands of curated pairs across many identities, with balanced reactions | Give a full fine-tune broader evidence than one-face memorization; measure whether added data improves unseen-person results |
| Difficult examples | Add reviewed cases with facial hair, glasses, darker/lighter skin, side angles, hands near cheeks, and unusual clothing | Address failure categories observed on the held-out set |

The exact dataset size depends on error rates and coverage. Twelve cartoons of one person do not establish a model that works for anyone. Repeating one image many times does not add identity or expression diversity.

Do not use the app's current outputs as automatic ground truth. The reviewed samples include identity drift, an extra hand, and blending artifacts. Generated targets may be used only after checking and correcting each one. Reference and target must depict the same person; changing the face while preserving clothing is not an acceptable pair.

**Public dataset findings and selection**

The sources below were checked on 4 October 2026. A published dataset is not automatically a ready-to-use sticker training set. None of the inspected sources establishes complete coverage of this app's twelve reactions, the user's chosen drawing style, same-person references, and correct hand gestures.

| Dataset and primary source | Available evidence | Recommended role and limits |
|---|---|---|
| [Comic Faces (paired, synthetic) v2](https://www.kaggle.com/datasets/defileroff/comic-faces-paired-synthetic-v2) | Publisher identifies it as paired synthetic faces for pix2pix or similar training. The dataset card body/license did not render through the research tool. | Closest straightforward candidate for a photo-to-comic prototype. Inspect a small sample for actual matching identities, resolution, desired style, and defects before selection. Verify publisher license and upstream provenance before downloading/training; the exact count, resolution, and license are not confirmed here. Synthetic faces do not prove performance on real user uploads, and face pairs do not cover hand gestures. |
| [FFHQ, NVIDIA](https://github.com/NVlabs/ffhq-dataset) | 70,000 aligned 1024px face photos with varied ages, ethnicities and accessories. Photos have per-image terms; the dataset is CC BY-NC-SA 4.0. | Best verified photo-source option for a noncommercial research pilot. It has no paired cartoons: select a diverse subset and create/review same-person targets in one style. Keep copyright metadata. Do not treat it as commercially cleared or use it to develop facial recognition technologies, which the publisher excludes. |
| [Google Cartoon Set](https://google.github.io/cartoonset/download.html) | 10k/100k randomly composed cartoon faces, attribute labels, CC BY 4.0. The 10k archive is listed as 450 MB. | Optional consistent avatar-style material if this exact visual style is wanted. It has no matching real-person photographs. It cannot by itself teach identity-preserving photo edits or reaction gestures. Do not mix its style indiscriminately with a different comic target style. |
| [GenEAva 1.0, authors' paper](https://arxiv.org/abs/2504.07945) | 13,230 synthetic cartoon avatars spanning 135 expressions; the framework stylizes generated realistic faces while preserving identity/expression. | Promising expression-data candidate. The advertised project page did not load, and a dataset download, license, and released reference-target layout could not be verified. Treat as an investigation candidate, not an available paired training set. A project-page template's website license is not a dataset license. |
| [WebCariA, Nanjing University](https://cs.nju.edu.cn/huojing/WebCariA.htm) | 6,024 caricatures and 5,974 photos of 252 identities. Author application required; noncommercial research/educational use and redistribution restrictions. | Auxiliary identity/attribute research only. Same-identity groups are not automatically aligned edit pairs. Exaggerated caricatures and varied styles conflict with this project's goal of faithful features in a consistent cartoon style. |

Recommended starting decision: inspect Comic Faces v2 first as a paired proof of concept, subject to verifying its terms. If its style/identity quality is unsuitable, build a 100-200 pair noncommercial research pilot from an FFHQ subset and manually approved cartoon targets. For a product training set, use photographs and commissioned/licensed targets with suitable rights. Google Cartoon Set is an optional style source, not a replacement for paired data. Keep GenEAva out of the training manifest until its release and terms are verified.

Add explicit reaction and correct-hand examples after the basic face transformation works. Do not expect a face-crop dataset to solve this repository's observed extra-hand failure. Separate training examples that preserve expression from examples that intentionally change expression; captions and inference conditioning must match the learned task. Hold out real, unseen subjects to assess the synthetic-to-real gap.

**Dataset structure and review**

Use a manifest with these fields per example:

```json
{
  "example_id": "person_001_laughter_01",
  "subject_id": "person_001",
  "reference": "reference/person_001_photo_01.jpg",
  "target": "target/person_001_laughter_01.png",
  "instruction": "Turn this person into the approved cartoon style, laughing with eyes closed, one hand on the belly and the other beside the cheek. Preserve this person's facial features, hair and outfit. Plain white background, no text.",
  "intent": "laughter",
  "tone": "playful",
  "split": "train",
  "quality_approved": true
}
```

Train on RGB targets with a plain background and consistent framing. Preserve optional transparent artwork separately for mask/composition evaluation. Generate captions, outline, platform sizing, and compression after image generation.

Caption controllable properties such as expression, pose, outfit, angle, and tone. Include different instruction phrasings so the model does not depend on one exact sentence. Select a face crop from the original at inference. Using a second face reference in training is an additional experiment: its reference layout must match the actual inference path, and the selected trainer must support it.

Assign train/validation/test splits by **subject identity** before training. The same person, source photo, or derivative must not appear in multiple splits. Start with approximately 80/10/10 subject splits when the dataset is large enough. Tiny pilots need explicit held-out people rather than trusting percentages. Keep test identities untouched during checkpoint selection.

**Hardware and training method**

The installed laptop has 6 GB VRAM and approximately 16 GB system RAM. It is below BFL's documented 4B training baseline of 12 GB VRAM and 32 GB system RAM. BFL's practical adapter example targets a 24 GB GPU. These are not sufficient evidence that full-weight training fits on 12 or 24 GB. See [training requirements](https://docs.bfl.ai/flux_2/flux2_klein_training).

For full-transformer training, a rough memory calculation for four billion trainable parameters is:

| Storage | Approximate decimal GB |
|---|---:|
| BF16 parameters | 8 |
| BF16 gradients | 8 |
| Two FP32 Adam states | 32 |
| Optional FP32 master parameters | 16 |
| Total before activations, references, encoders, and framework overhead | 48–64 |

This is an engineering estimate, not a measured Klein benchmark. Gradient precision, optimizer implementation, sharding, and offload change the total. The estimate explains why conventional full fine-tuning cannot be proposed on this 6 GB VRAM / 16 GB RAM laptop. The confirmed plan uses no cloud or external GPU.

**Experimental laptop-only route**

[Musubi Tuner's FLUX.2 documentation](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/flux_2.md) supports Klein Base 4B paired reference conditioning, latent/text-output caching, FP8 base weights, gradient checkpointing and CPU block swapping. These are documented features, not evidence that this particular laptop fits a paired training run. CPU offload moves the bottleneck into host RAM and transfer bandwidth; 16 GB system RAM is also a constraint.

Proposed first memory probe (engineering choices, not a published 6 GB benchmark):

- Separate training environment and original Base safetensors; do not mutate the working ComfyUI environment or attempt training on the Q6 GGUF.
- One reference and one target per example, 512px target resolution, batch size 1, LoRA rank 8 initially. Lower resolution/rank is a feasibility experiment, not a promised final-quality setting.
- Cache VAE latents for both target and reference and text encoder outputs in separate stages, so the encoder is not resident during transformer training.
- Use trainer-supported `--fp8_base --fp8_scaled`, `--gradient_checkpointing`, and block swapping. Start with the documented 4B swap ceiling of 13, then validate the pinned revision's behavior for Base 4B. Consider checkpoint CPU offload only after measuring host RAM. Use no data-loader workers initially on Windows to minimize duplication.
- Check checkpoint loading and caching peaks as well as steady-state steps. Use a small approved subset, complete forward/backward/optimizer updates, and record allocated/reserved VRAM, process/host RAM, and seconds per step. A successful import or forward pass alone does not prove training fits.
- If the first updates exhaust VRAM/RAM or require impractical paging, report the measured limit. Do not silently reduce model size, label a style filter as training, or claim a completed full fine-tune.

If this fits, run a short learning experiment and inspect held-out-person edits before committing to a longer run. Keep the original high-resolution targets so training can be improved later. Benchmark LoRA on both Base and distilled 4B; BFL documents Base-trained adapters used on distilled inference, but exact trainer serialization, ComfyUI loading, and quantized inference compatibility must be checked for this adapter.

Do not train the existing inference GGUF directly. Prepare a separate training environment with the original Base checkpoint, matching encoder/VAE, pinned trainer revision, and recorded configuration. First measure one forward/backward/update step, then run a short overfit/debug experiment on a small approved subset. Begin lower-resolution debugging and progress to the intended high-quality resolution only after memory and learning behavior are verified.

Learning rate, optimizer, trainable modules, batch size, image bucketing, and checkpoint frequency must be selected for the actual trainer and hardware. Do not claim an adapter learning rate or step count is a validated full-transformer recipe. No cloud GPU has been rented, no external dataset has been uploaded, and no paid job has started.

**Improvements to the current application for a trained 4B route**

| Existing location | Change | Reason |
|---|---|---|
| `workflows/` and `backend/app/comfy.py` | Add a separately versioned trained-cartoon workflow; keep original model/reference/renderer metadata | Make trained versus existing results reproducible without altering old packs |
| `backend/app/catalog.py` | Match generation instructions to the training data; wire tone into conditioning | Teach and use controllable reactions consistently |
| `backend/app/worker.py` | Screen anatomy, framing, expression, and identity independently before selecting a result | A high face score must not allow an extra hand or incorrect emotion |
| `backend/app/portrait.py` | Keep original-source face preservation for photographic mode; benchmark whether cartoon mode needs any retargeting | Avoid imposing a synthetic photographic head on a learned drawing style |
| `backend/app/imaging.py` | Replace the cartoon posterization path when using trained artwork; improve soft masks, intentional hand gaps, caption placement, and lower silhouette | Training does not fix destructive alpha cleanup or detached caption layout |
| `frontend/src/App.tsx` | Show actual style examples, candidate comparison, restore, and targeted corrections | Make remaining failures reviewable and recoverable |
| Benchmark scripts | Explicitly select trained/untrained route, checkpoint, reference layout, and identical seeds | Current A–E benchmark routing has drifted after the photo-route default changed |

A style-trained model may preserve visual identity better while still making bad hands. Hard-region preservation, pose guidance supported by the chosen workflow, and anatomy rejection remain complementary controls. Face-identity or landmark losses are possible later research additions; they require a differentiable implementation and calibration for cartoons, and should not be assumed available in the baseline trainer.

**Acceptance and deployment**

Before adopting a trained checkpoint, compare current inference, untrained Base, and trained Base on the same held-out photos and twelve reactions. For an adapter, also compare trained distilled inference. Full-fine-tuned Base weights do not automatically become a four-step distilled model.

Proposed initial acceptance targets, to confirm with the user:

- Held-out people recognize themselves in at least 10 of their 12 reactions.
- Each accepted reaction visibly communicates its intended emotion and pose.
- Zero obvious extra limbs, severe malformed hands, or face seams in delivered stickers; reject/retry failures and measure that rate.
- A consistent approved drawing style across a pack.
- Clear faces and captions at 128/256-pixel preview size.
- Preserved hair, clothing, and intentional gaps on light and dark backgrounds.

Use SFace as one advisory metric alongside human recognition, expression/pose checks, and mask/composition review. Calibrate similarity thresholds against the chosen cartoon style rather than transferring a photo threshold unchanged. Track rejection rate, retries, generation time, VRAM/RAM, and final export quality. Evaluate all model candidates before quantization, then repeat on the laptop's deployment representation to measure any degradation.

Training readiness now requires a verified/licensed dataset subset, approved drawing-style targets, and a measured successful laptop training probe. The general-person scope, public-data preference, and laptop-only hardware are confirmed. The missing dataset and unverified memory fit prevent an honest claim that training has started. This document prepares the training direction; it does not claim a trained checkpoint or achieved quality targets.
