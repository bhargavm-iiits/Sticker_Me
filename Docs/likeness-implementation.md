> Historical record. Active Plan 1 routing, review controls and current validation are documented in [plan1-implementation.md](plan1-implementation.md). Claims below about exact-face preservation or filtered Cartoon routing are superseded.

# Face likeness implementation

Implemented the supplied face-likeness plan in the app, rather than only writing its proposed document. The user chose redrawn realistic and cartoon faces with different expressions. An identical photo face is not promised.

## Changes

- Uploads retain up to 2048 pixels and trim conservative near-black/white edge padding. YuNet rejects missing, tiny, or multiple substantial faces before checking the engine.
- Packs save a 512-square face crop, a clean outfit reference with 16-aligned dimensions, and a local SFace embedding. Older cartoon packs construct these references when needed; legacy cutout packs retain their original pipeline.
- The pose graph uses two chained reference latents at 768 square. The face graph uses the generated face crop plus the real face at 512 square. Both have matching scheduler/latent dimensions and generated human canvas graphs.
- Identity-first prompts retain facial hair, natural proportions, skin tone and original head angle. Likeness is the default portrait illustration style; Realistic and Cartoon remain available alongside Chibi and Comic. The greeting, apology and congratulations gestures keep the face visible.
- Pose candidates use deterministic distinct seeds and SFace scoring. Low or undetectable scores allow one extra candidate by default; the best measurable candidate wins. A face-detail pass is aligned using five landmarks and feathered into the artwork, then retained only when its whole-image similarity score is no worse. The base artwork is saved for audit.
- SQLite migration 3 adds stage/candidate attempt keys and advisory scores/notes. Refinement uploads register their attempt ownership before uploading, including when uploads fail. Recovery never mistakes a pose attempt for a refinement or retry. Cancellation checks remain between GPU calls.
- The diffusion model is Q6_K, the plan's lower-memory alternative to Q8. Official revision, size and SHA-256 are pinned. Q4/Q8 pins remain available for the benchmark. YuNet/SFace weights are pinned and installed in workspace runtime storage.
- The UI shows the selected face crop, guidance for better photographs, scores and low-score Redraw emphasis. Scores are estimates, not recognition probabilities.
- Exports record actual workflows, stage/candidate and scores. They exclude the uploaded face, body reference and embedding. Pack deletion cleans face/body inputs and owned crop/output copies; removing a sticker cleans its owned engine attempts before their cleanup keys are lost.
- Realistic artwork uses segmentation rather than white flood fill so a white shirt is not erased as background.

## Validation

Backend tests cover real astronaut-face detection/cropping/self-comparison, bad upload rejection, retry seed selection, weaker-refinement rejection, stage-specific recovery, interrupted crop-upload ownership, migration and scoped cleanup. API lifecycle tests use simulated generation, so they do not prove visual quality. Frontend TypeScript/Vite production build and engine diagnostics pass.

The local GPU comparison uses the existing uploaded portrait, three reactions and fixed initial seeds. Original packs were preserved; benchmark databases and images live under `runtime/likeness-ab`. Sampled whole-system memory includes other applications. The first comparison used the initial plan prompts, and revealed invented eyewear despite improved face detail. The final prompts omit named accessory examples, remove invented accessories during refinement and retain the original viewing angle; subsequent style checks use those revised prompts.

Measured sample results and artifact paths follow. Human recognition of 10 of 12 reactions and actual mobile importing are not yet acceptance-tested.

## Initial fixed-seed GPU comparison

| Variant | Median SFace cosine | Three reactions (seconds) | Sampled VRAM (MiB) | Sampled system RAM (GiB) |
|---|---:|---:|---:|---:|
| A | 0.077 | 131.56 | 3505 | 14.79 |
| B | 0.170 | 152.28 | 3889 | 14.98 |
| C | 0.239 | 348.24 | 3889 | 14.62 |
| D | 0.222 | 364.75 | 4401 | 14.40 |

A is the former single-reference cartoon prompt; B adds face/body references, larger output and likeness style; C adds retry/refinement; D adds Q6 precision. All three reactions in each initial variant remained below the provisional 0.30 target. Q6 did not improve the median over C in this small sample, so precision alone is not evidence of better identity. The initial prompt requested the same new face-visible gesture in the A greeting; the reproducible script now restores the former A gesture too. These initial images were visually inspected: facial hair is restored but invented eyewear remains. The final prompts address that failure explicitly.

Artifacts: `runtime/likeness-ab/50a7b9046b6345c88cdbe4fa4d813f96/result.json` and A/B/C/D contact sheets. These benchmark files contain the uploaded subject and stay local. Original user packs and uploaded references were preserved.

## Revised realistic style

The accessory examples were removed and the face viewing angle is retained. The realistic prompt requests photographic editing and keeps reference skin detail; the refinement prompt describes a portrait crop rather than a drawing.

| Reaction | SFace cosine | Seconds |
|---|---:|---:|
| greeting | 0.615 | 85.70 |
| laughter | 0.485 | 76.75 |
| surprise | 0.416 | 76.73 |

Median: 0.485. Sampled VRAM: 4401 MiB; sampled system RAM: 12.28 GiB. All three are above the provisional 0.30 floor. Refinements that lowered similarity were rejected. Visual review found recognizable facial hair and no invented eyewear. This is a three-reaction sample, not proof of exact identity or recognition of 10 of 12 reactions.

Artifacts: `runtime/likeness-ab/57a1c1a9a364481a9fe32b2e4999ec40/result.json` and `D-contact-sheet.png`.

## Final illustration pipeline

Direct Cartoon generation remained less similar than realistic generation: the revised Q6 Cartoon sample scored 0.238 / 0.306 / 0.151. Removing invented accessories helped but did not sufficiently preserve the face's shape. To address the user's realistic + cartoon preference, production Likeness and Cartoon now generate photographic portraits first, then add deterministic shading/ink without moving facial features. Similarity scoring, retries and refinement acceptance use the rendered images. Each reaction still has independent generated pose/expression artwork; this is not a repeated-photo cutout fallback. Chibi and Comic retain their direct generative styles.

Likeness uses gentle smoothing/shading; Cartoon uses stronger smoothing, color shading and ink. Both preserve dimensions and geometric locations. The shader's color changes are bounded and its operations are local; it cannot guarantee that the preceding generated photo is identical to the uploaded person. The real astronaut sample retains SFace cosine above 0.5 under both styles. The app uses segmentation for these photographic illustration styles so white clothing remains foreground. Stored workflow metadata records the renderer and selected style for provenance.

Benchmark variant E checks this final pipeline. The A-D definitions remain available for reproduction, and `STICKERME_PORTRAIT_RENDER=0` disables the final rendering route.

## Final Cartoon GPU validation

| Reaction | SFace cosine | Seconds |
|---|---:|---:|
| greeting | 0.620 | 80.41 |
| laughter | 0.514 | 76.45 |
| surprise | 0.428 | 76.38 |

Median: 0.514. Total for three reactions: 233.24 seconds. Sampled VRAM: 4401 MiB; sampled system RAM: 12.37 GiB. All three rendered faces exceed the provisional 0.30 floor. Weaker or unalignable refinements were rejected.

Artifacts: `runtime/likeness-ab/d751ba4f831144448f550bd14f54ffbb/result.json` and `E-contact-sheet.png`. This validates the final Cartoon route; Realistic is validated separately above. Likeness uses the same photographic generation with gentler local shading. These advisory cosine scores are not identity probabilities or percentages.

## Composed sticker previews

`scripts.render_likeness_review` ran real background segmentation and the app's 512-square caption/outline composition on the three Realistic and three final Cartoon artworks. All six have foreground and transparency; all WebP files meet the 100 KiB limit, with the largest 30,540 bytes. The resulting local contact sheet was visually checked for face/clothing preservation and readable captions. These are review samples, not a full 12-reaction pack or proof of mobile importing.

Artifacts: `runtime/likeness-review/contact-sheet.png`, `runtime/likeness-review/sticker-previews.zip`, and `runtime/likeness-review/result.json`. The ZIP excludes the comparison sheet because that sheet includes the original source face; the ZIP contains only derived sticker images and preview metadata.

The engine was started without the ordinary worker, so existing packs were not processed or regenerated by the benchmarks. The engine remains available; use `start.ps1` to run the app/worker and create a new pack. Existing ready packs keep their artwork. Choose Realistic for photographic faces, Cartoon for stronger illustration shading, or the default Likeness for gentler shading.

## Final checks

- Full backend suite: **36 passed**, one existing upstream Starlette/httpx deprecation warning, in 122.54 seconds.
- Frontend: TypeScript and Vite production build passed.
- Python: backend and scripts compile successfully.
- Doctor: both workflow graphs, Q6 diffusion, encoder/VAE and face models available; engine ready.
- Actual GPU samples: three realistic and three final cartoon reactions completed locally.
- Actual composition/encoding: six transparent 512-square stickers passed size/transparency and WebP limits; contact sheet visually checked.

Full 12-reaction human recognition, broad photo/style calibration, live browser/canvas interaction and mobile importing remain unverified. Exact identity cannot be promised when the face is redrawn. The six previews provide concrete review evidence for the chosen realistic/cartoon approach.
