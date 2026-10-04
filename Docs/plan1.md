# Plan 1: Improve sticker quality without custom training

Prepared 4 October 2026. Scope: improve the existing laptop application for recognizable stickers from any uploaded person's photo. Keep the current FLUX 4B model size. This is a complete implementation plan, with the original folder review retained below as its evidence. The review below remains historical. Implementation details, fresh checks and unmet visual acceptance targets are recorded in [plan1-implementation.md](plan1-implementation.md).

## Outcome and constraints

Deliver clearer expressions, recognizable faces, consistent cartoons, correct anatomy, clean cutouts and readable captions. Use the existing RTX 4050 laptop with 6 GB VRAM and approximately 16 GB RAM. No custom model training or external GPU is part of this plan.

Photographic stickers and drawn cartoons require separate generation paths. Photographic mode should preserve the original head as far as the animation and composition permit. Cartoon mode should draw the person in an approved style. Neither path should promise pixel-identical identity after neural expression changes or perfect anatomy on every generation.

## Implementation phases

| Phase | Actions | Deliverable and completion check |
|---|---|---|
| 1. Reproducible baseline | Pin route, model hash, style, renderer, intent, tone and seed in benchmarks. Correct the misleading A-E and cartoon smoke routing. Save inputs, raw candidates, animation outputs, masks and final exports. | A baseline report that identifies exactly which pipeline produced every image. |
| 2. Immediate product fixes | Wire tone into submitted gesture/expression controls. Compose the subject and caption together, enlarge the readable face, improve the lower silhouette, and offer captionless export. Align UI claims and style examples with actual behavior. | Tone changes the submitted controls; figure/caption fit is clear at 128 and 256 pixels. |
| 3. Photographic identity preservation | Take the animation source from the original photo, align it with the edited body, retain the head/hair silhouette, and handle hand occlusion with separate foreground layers. Evaluate a supported mask-based edit workflow before adopting it. | Recognizable source appearance without face seams or overwritten fingers in reviewed examples. |
| 4. Independent acceptance checks | Separate identity, expression, pose/anatomy, framing and mask checks. Reject obvious defects before ranking. Treat unavailable scores as an unresolved check. Add review-needed outcomes and targeted retries. | The observed three-handed laughter is rejected; a strong face score cannot override an anatomy failure. |
| 5. Expression and mask quality | Benchmark curated expression drivers and available retargeting controls. Retain useful soft alpha, preserve intentional openings, and compare background-removal options under the same memory budget. | Distinct reactions; no destructive hole filling, hair clipping or obvious halos on multiple backgrounds. |
| 6. Direct cartoon route | Generate candidate character designs using the uploaded photo, select one recognizable design, and condition reactions on the original identity plus approved style where supported. Avoid chaining each generated reaction as the next identity reference. | Cohesive artwork with recognizable features; compare direct drawings against the current filter. |
| 7. Review and recovery | Provide candidate comparison, restore, expression intensity and correction choices such as hand/face/mask. Preserve existing artwork versions and route metadata. | A failed reaction can be corrected without discarding approved stickers or losing previous versions. |
| 8. Validation and release | Run required backend/frontend checks, a small varied portrait benchmark, full twelve-reaction packs and export checks. Verify the browser approval flow and actual phone/platform importing separately. | Functionality and visual acceptance both pass; retain the previous workflow for recovery. |

## Evaluation and acceptance

Use the same photos and reaction instructions before and after each meaningful change. Include facial hair, glasses, varied skin tones, age appearances, head angles, lighting and hand-adjacent gestures. Start with greeting, laughter and surprise, then expand to all twelve catalog reactions. Keep source images and evaluation ratings unchanged across compared variants.

Proposed engineering targets, not measured guarantees:

- A person recognizes themselves in at least 10 of 12 delivered reactions.
- Every delivered reaction communicates its intended emotion and pose.
- No obvious extra limbs, severe hand malformations, face seams or severe crop failures in delivered artwork; record rejected attempts as well as successful results.
- One coherent drawing style per cartoon pack.
- Faces and captions remain readable at 128/256-pixel preview size.
- Hair, clothing and intentional hand gaps survive alpha cleanup on light, dark and colored backgrounds.
- Tone changes actual conditioning or motion controls.
- Required recovery/export tests remain passing and the user can restore prior candidates.

SFace is advisory. It is not a recognition probability, emotion score or anatomy check. Calibrate thresholds separately for photographs and cartoons. Report raw success rate, retry/rejection rate, latency and resource use so curated final outputs do not hide failures.

## Dependencies, risks and recovery

Original-head animation needs alignment and occlusion handling; it can introduce seams if adopted without visual comparison. Multiple identity/style references and masked edits depend on actual workflow support and must be tested on this hardware. Hand/body landmarks can assist screening but cannot certify plausible anatomy. A visual review remains necessary for ambiguous cases. More retries consume time and must be measured.

Version authored changes and keep runtime/cache/model exclusions. Preserve existing packs and the current route. Introduce new workflows with explicit route versions; regenerate selected reactions deliberately instead of assuming old saved packs change automatically. If a phase reduces resemblance or quality, retain the last validated route and investigate that phase before expansion.

## Full folder review and evidence

The following review preserves the complete findings, source locations, sample measurements and original suggestions discussed in this session.


The app's job handling and editing features are in reasonable shape. The weak point is visual acceptance: the pipeline primarily checks face similarity, while the user needs recognizable identity, clear emotion, correct anatomy, consistent illustration, and a polished sticker silhouette together.

This was an analysis pass. Application source, existing packs, settings, and services were left unchanged. No new GPU generation was submitted. A previously running photo-route validation finished during the review; its saved outputs are included below.

**Scope and verification**

Reviewed the backend, frontend source/configuration, generation workflows and model manifests, setup/service scripts, tests, documentation, main application database, logs, and representative exported/generated images. Dependency environments, caches, binary weights, and the vendored ComfyUI tree were treated as installed infrastructure rather than individually audited source files. Not every saved image was inspected.

Fresh checks: `python -m pytest -q` finished with **46 passed**, one upstream Starlette/httpx deprecation warning, in 180.35 seconds. Frontend `tsc --noEmit -p tsconfig.json` passed. Doctor reported the engine, face models, background remover, and LivePortrait available on the RTX 4050 Laptop GPU with 6 GB VRAM and 15.2 GiB system RAM. The app API on port 8000 was not reachable during the check; the engine was running a pre-existing validation job. Browser interaction and phone importing were not tested.

**What the saved pictures reveal**

| Evidence | Observation | Implication |
|---|---|---|
| Exported original Cartoon pack under `Docs/stickerme-d6adcd73-040e-4515-980b-11e31ef97a4a` | Strong cartoon appearance, but a generic character; the inspected greeting loses the reference's facial hair | Illustration quality and identity have not been solved together |
| `runtime/likeness-review/contact-sheet.png` | Photographic redraws look smoother and more generic than the source; Cartoon is mostly a posterized version of the same portrait | The current Cartoon renderer is a filter, not an authored character style |
| Main app's newest Realistic pack, `d40b9d71-df2b-44ab-81e5-1f44522df0ba` | Recognizable resemblance, but altered eyes/skin/face appearance; rectangular torso bottoms and detached captions | Similarity and export compliance do not guarantee attractive stickers |
| Full photo-route check, `runtime/photo-route-check/446fe7bf70724af6ad73621f77b96057/contact-sheet.png` | Improved resemblance, but many reactions share a similar smile/head angle; “Busy” shows a tablet-like prop rather than the requested laptop typing; surprise has a dark patch near a hand | Reaction accuracy, prop accuracy, and compositing need separate evaluation |
| Newer three-preview photo-route check, `runtime/photo-route-check/597afc0bf0e54cb6b4349955d1af2c6a/contact-sheet.png` | “LOL” has three hands. Both its base gesture artwork and final animated artwork contain the extra hand. Final face also looks softer than the base | The extra hand originates in diffusion, and face animation adds another potential quality loss |

The full saved photo-route check totals **1295.1 seconds**, about 21.6 minutes, with median SFace cosine **0.904**. The newer three-preview check totals **650.7 seconds**, about 10.8 minutes, with scores **0.876 / 0.544 / 0.725** for greeting/laughter/surprise. These are historical/concurrent sample measurements, not clean performance comparisons. All three newer records have `note: null`, including the three-handed laughter. SFace scores are not percentages or calibrated recognition probabilities.

**1. The “exact face” promise exceeds the actual pipeline — highest priority**

In `workflows/klein4b-api.json`, the photo is encoded as reference conditioning; sampling starts from `EmptyFlux2LatentImage`. There is no regional edit mask or hard constraint that preserves head pixels. “Change only the arms and hands” is a prompt instruction, so the model can still change the face, expression, clothes, and lighting.

More importantly, `backend/app/portrait.py:56` crops the LivePortrait **source from `gesture`**, the diffusion output, rather than from the original `canvas`. It then pastes the animated head back into that output. LivePortrait therefore preserves the appearance of the generated gesture face, including any drift already introduced. It does not restore the original uploaded face. The newer laughter base visibly changes the source expression even before animation.

Recommendation: establish an original-photo head layer for photographic mode. Animate that original source, then align and composite it into the edited body. Preserve the original hair/head silhouette and validate target head geometry before compositing. Use a supported masked edit workflow where feasible; otherwise explicitly composite only approved generated body/arm regions. Keep “exact face” out of UI claims until actual preservation tests support it. Animation remains neural synthesis and may change detail even with the correct source.

**2. Candidate selection optimizes one quality dimension**

`backend/app/worker.py:43` selects gesture and expression candidates by SFace similarity. It does not assess whether the requested emotion exists, whether there are two plausible arms/hands, whether a requested prop is correct, or whether the result is cropped safely. SHA-256 duplicate checking later detects only byte-identical artwork, not visually repetitive reactions.

`GESTURE_FLOOR=0.75` and `EXPRESSION_FLOOR=0.55` are early-stop targets, not hard acceptance gates. After retries, a weaker candidate may still be used. An animation with an unavailable score can also be accepted. Weak expression results below 0.45 revert to the gesture image, which itself is not guaranteed to retain the original expression. A high similarity score can favor a mild or unchanged expression over a strong reaction; the selection objective creates that incentive, although its effect needs controlled measurement.

Recommendation: separate identity, expression, anatomy/pose, and mask/composition checks. Reject obvious failures before ranking acceptable candidates. Add a `needs_review` state rather than marking every produced image ready. Use face landmarks for measurable eye/mouth changes and hand/body landmarks as screening tools, with manual review for ambiguous cases. Add perceptual comparisons to flag repeated expressions; perceptual similarity alone should not be treated as a full semantic check.

**3. Tone is currently ineffective in the default route**

`backend/app/comfy.py:140` and `:147` call `expression_driver_prompt(intent)` and `gesture_edit_prompt(intent)`. Neither function accepts tone. `generate_photo` receives tone but does not otherwise use it. Thus Playful/Warm/Dramatic cannot systematically change new Realistic, Likeness, or Cartoon packs under the default configuration. Random seeds may change output, but that is not tone control.

Recommendation: connect tone to expression/gesture instructions and calibrated per-intent motion strength. Add a small test that confirms the requested tone changes the actual submitted conditioning or motion parameters. Offer an expression-intensity adjustment in preview.

**4. Cartoon is a photographic filter**

`backend/app/imaging.py:159` performs bilateral smoothing, color quantization, and Canny-edge darkening. It preserves geometry, which helps resemblance, but cannot create deliberate illustrated shapes, expressive line work, or a cohesive character design. That matches the filtered-photo look in the comparison sheet. Raising filter strength risks flat skin patches and dark facial texture rather than better drawing.

Recommendation: keep filtered portraits as a clearly named illustrated-photo option. For a true Cartoon mode, first generate two or three recognizable character designs and let the user approve one. Supply the original photo for identity and the approved design for style on each reaction; do not chain reactions as identity references. Evaluate this against the existing approach before changing production. A compatible identity/style adapter or small style LoRA is a later experiment, not an assumed drop-in fix for Klein.

**5. Expression transfer and hand overlap need better control**

`backend/app/imaging.py:227` blends a fixed feathered head ellipse. It cannot distinguish face, hair, foreground fingers, or background. Hands beside cheeks can fall inside the pasted area and be overwritten or ghosted. The stored surprise defect is consistent with this risk, but its exact cause was not isolated. The newer laughter animation also visibly softens face detail.

Recommendation: use an occlusion-aware face/hair mask, keep foreground hands above the animated layer, and reject excessive alignment differences. Start with gestures that leave the face unobstructed. Evaluate curated expression drivers or direct eye/mouth/smile controls instead of generating a new driver for every sticker. Upstream LivePortrait exposes image retargeting controls and regional expression animation; integrating them is additional work because this app downloads only a subset of its code/weights. See [LivePortrait controls](https://github.com/KlingAIResearch/LivePortrait/blob/main/app.py) and [regional animation documentation](https://github.com/KlingAIResearch/LivePortrait/blob/main/assets/docs/changelog/2024-08-19.md).

**6. Cutout cleanup sacrifices useful detail**

`backend/app/imaging.py:181` thresholds alpha at 128, drops components smaller than 2% of the largest, fills all enclosed holes, and blurs the resulting binary mask. This removes haze but can clip hair, remove small accents, and fill intentional openings between fingers or heart-shaped hands. A fixed ellipse for head pasting compounds these issues.

Recommendation: retain soft alpha at hair and skin edges, remove only small unwanted islands, and fill only small accidental holes. Inspect masks on white, dark, and colored backgrounds. Benchmark `isnet-general-use` or `birefnet-portrait` against the current U2-NetP using the same images and memory budget; better quality here is a hypothesis to test. These alternatives are documented by [rembg](https://github.com/danielgatis/rembg#models). Check compatibility with the installed version before integration.

**7. Composition makes the stickers feel unfinished**

`backend/app/imaging.py:325` shrinks captioned artwork to at most 420 × 352 pixels, uses a fixed white outline, and anchors the caption independently near the bottom. The resulting large gap, small face, and straight torso cut are visible across several packs. At chat size, these decisions reduce emotional readability.

Recommendation: lay out the figure and caption as one unit, anchor text to the foreground bounds with a modest gap, enlarge the head/upper body, and create a deliberate lower silhouette. Add a compact caption style and a captionless option in preview. Review real exports at 128 and 256 pixels, not only enlarged 512-pixel files. Rendering cannot repair a hand or sleeve already cropped by generation, so check framing before composition.

**8. The review controls do not let the user explain a failure**

The frontend offers Redraw and Fix mask, but redraw simply chooses a new seed for the whole reaction. There is no “keep this face,” “fix only the hand,” “stronger laugh,” or comparison with the prior version. Old versions exist on disk, yet the UI cannot restore them. Green “High similarity” starts at 0.45 regardless of style and says nothing about anatomy or aesthetics.

Recommendation: add targeted correction choices, candidate comparison and restore, separate quality labels, style examples, and progress stages with measured time estimates. Gate the default route's create button on LivePortrait readiness as well as engine readiness. The current hero still advertises individually drawn cartoons while the default is photographic.

**9. Evaluation and documentation have drifted**

The four packs in the main database were created using legacy/original/drawn pipelines. None has `canvas.png` or a saved `photo-edit+liveportrait-v1` attempt marker. The newer photo-route checks live separately. Existing artwork will not improve merely because the code was updated.

`scripts/likeness_ab.py:90` toggles refinement/rendering but never disables the now-default `PHOTO_EDIT`. With its default Likeness style, current A–E runs enter the photo route, so they no longer reproduce their advertised original-pipeline comparisons. Earlier saved results remain historical evidence; a new run needs explicit route selection. Variant A may also apply its original single-reference graph to the photo expression stage.

`scripts/smoke_cartoon_pack.py` omits an explicit style, so it now requests Realistic despite its name. `scripts/smoke_generation.py` directly calls the engine's drawn route and therefore does not exercise the default worker pipeline. The twelve-reaction photo validator exercises generation/finishing, but does not establish browser approval/export acceptance. Several documentation files still report different default styles, Q4/512 settings, and older test counts.

Recommendation: pin route/style/configuration in every benchmark, record final renderer and animation parameters, and compare the same photos/seeds. Add a small varied portrait set and human ratings for identity, emotion, anatomy, style, and small-screen readability. Preserve the existing recovery/export tests; passing them proves functionality, not visual quality.

**Suggested implementation order**

| Order | Work | Acceptance criterion |
|---|---|---|
| 1 | Compact composition; wire tone; correct claims and benchmark routing | Clear captions at chat size; tone affects submitted controls; benchmarks run their named routes |
| 2 | Animate original-photo head; protect foreground hands | Same source likeness across previews; no visible head seam or overwritten fingers |
| 3 | Add reaction/anatomy checks and targeted retries | Three-handed laughter is rejected; each accepted reaction visibly matches its intent |
| 4 | Calibrated expression presets and reusable animation process | Distinct reactions with retained likeness; measured latency improvement |
| 5 | Improved alpha cleanup and segmentation comparison | Hair/clothing preserved; intentional hand gaps transparent; no halos |
| 6 | Approved character design for true Cartoon mode | User approves both recognizability and drawing style before full-pack generation |

Keep a photographic mode and a true illustrated mode with separate acceptance criteria. Begin with a small set of successful, face-visible reactions before expanding all twelve. Avoid compensating for architectural issues by only lengthening prompts, increasing retries, raising resolution, or buying more VRAM.

The installed Q6 workflow already uses the distilled model's four-step regime. Four steps are intentional for this model; arbitrary step increases are not an established quality fix. ComfyUI distinguishes distilled and base workflows in its [official Klein guide](https://docs.comfy.org/tutorials/flux/flux-2-klein). Historical local A/B results also show Q6 did not improve median identity over Q4 in the initial sample. Benchmark any model change after correcting preservation and quality selection.

**Folder maintenance**

The workspace root is not currently a Git repository. Introduce version control for authored source and manifests before the next substantial refactor; preserve the runtime/cache exclusions. Experimental `StickerMe-exp` input/output folders still exist. Treat experiment retention and repeated export ZIP accumulation as housekeeping tasks, separate from visual quality. No files were removed in this review.

