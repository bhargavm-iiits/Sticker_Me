# Local sticker workflows — Plan 1

Production retains Klein 4B Q6_K, Qwen3 4B Q4_K_M, Flux2 VAE, Euler/CFG 1 and four distilled steps. `models.json`, `model-precisions.json`, `face-models.json` and `liveportrait.json` pin model/code revisions and checksums. No custom training is added.

## Photographic route

Realistic and Likeness use `klein4b-api.json` to generate a gesture from the original photo canvas and face reference. Prompt instructions cannot guarantee preservation of the head. Tone changes gesture and expression instructions.

`klein4b-face-api.json` generates an expression driver from the original-photo crop. `scripts/liveportrait_runner.py` takes **source and neutral reference from the original photo**, transfers relative expression motion, and outputs a synthesized 256px crop. The compositor resizes it to the 512px transform coordinates, checks head scale/displacement, follows the source head/hair alpha and protects detected foreground hand regions. Failed animation tries a safe original-head fallback; its note identifies when only the generated face could be retained. Neural synthesis and compositing still need visual review.

The worker can reuse one CPU animator and cached source features during a job; low available RAM uses one-shot execution. It releases the resident process after the job. Raw source/driver/decoder output and transform parameters are saved per sticker/revision/candidate. Likeness alone applies geometry-preserving local shading. Route: `photo-edit+original-head-v2` in engine metadata; `original-photo-head-v2` in quality reports.

## Drawn character route

Cartoon, Chibi and Comic first generate two designs with the original face and outfit references. User selection is required before reaction previews. Each reaction uses those same original references plus the selected design through a third `ReferenceLatent` (dynamic nodes 20–22). Reactions never become the next reaction's identity reference. Design attempts and reaction candidates remain saved. Route: `approved-cartoon-v2`.

The 768px pose graph uses face node 4 and outfit node 17, chained through nodes 7/19. Node 13 receives the final reference conditioning. The 512px face-refinement graph is used only when alignment and an advisory score comparison permit blending. The model can still invent facial hair or change apparent identity; approval gates expose this failure rather than certify a design.

`bindings.json` and `bindings-face.json` map submitted inputs/output. Static `*-human.json` canvases represent the two-reference base graphs; the application's approved-design reference is inserted dynamically. `scripts.build_likeness_workflows` regenerates base graphs/canvases. Live canvas import is not verified.

## Quality, recovery and provenance

Identity, expression/pose/prop, style, framing, anatomy, mask and variety are reported separately. Unavailable checks remain unresolved. Obvious detected photographic extra hands or multiple faces block acceptance; uncalibrated cartoon palm counts require visual review. The palm detector can miss defects or produce false positives. SFace cosine is not a probability or an emotion/anatomy score.

Attempts retain stable job/sticker/stage/candidate IDs and exact submitted workflows for queue/history recovery. Stages are `design`, `pose` and `face`. Cancellation interrupts only owned prompts; unknown submissions require explicit resume. New metadata includes the requested intent, style, tone, route, seed, workflow SHA-256 and actual installed local model SHA-256 values. External local engines may have different installed weights; unavailable assets are recorded honestly.

Caption/mask edits use saved artwork. Immutable versions support comparison and restore. Regional face/expression/hand corrections align a new candidate to the previous artwork and composite only the chosen region when feasible. Fallback to a full redraw is explicitly noted.

## Evaluation

`klein4b-baseline-api.json` retains the Q4 single-reference graph. `scripts.likeness_ab` explicitly disables photo editing for A–E comparisons. `scripts.validate_plan1` provides staged, fixed-seed QA and optional unreviewed full-pack generation. Photographic validation, mask comparison and expression-strength comparison have separate scripts. Stop the ordinary worker before GPU benchmarks.

Core ComfyUI provides latent-mask nodes, but this base reference graph samples from an empty latent. Merely masking reference conditioning does not preserve original pixels. Plan 1 uses explicit head/regional compositing; a separate latent-mask route has not been adopted or claimed validated. See [official Klein guide](https://docs.comfy.org/tutorials/flux/flux-2-klein) and [ComfyUI mask implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/nodes.py).

LivePortrait is [MIT](https://github.com/KlingAIResearch/LivePortrait). [OpenCV Zoo](https://github.com/opencv/opencv_zoo) supplies YuNet (MIT), SFace and the palm detector (Apache-2.0). [rembg](https://github.com/danielgatis/rembg) documents segmentation choices. All are installed locally; no hosted model service is introduced.
