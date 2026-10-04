# Plan 3: Combined sticker-quality improvements, training comparison and rollout

Prepared 4 October 2026. Objective: recognizable cartoon reaction stickers for any uploaded person in one consistent style, using FLUX 4B and the existing laptop only. This plan combines [Plan 1](plan1.md), application improvements without custom training, and [Plan 2](plan2.md), experimental paired edit LoRA training. It defines the order of work, a fair comparison, adoption criteria and fallback behavior. No implementation or training is claimed by saving this document.

## Recommendation and confirmed constraints

Improve the generation and finishing pipeline first. Then test a paired photo-to-cartoon adapter on FLUX.2 Klein Base 4B if a measured local training probe succeeds. Adopt the trained route only when it improves results on people excluded from training and remains usable on the laptop.

The strongest expected candidate for consistent cartoons is good paired training plus a corrected pipeline. This is a hypothesis, not a measured winner. Current app outputs have been reviewed; a trained checkpoint and controlled trained-versus-untrained benchmark do not yet exist.

- Target: any uploaded person, not a model trained to memorize one person's face.
- Drawing: one approved consistent cartoon style with controllable reactions.
- Model: retain FLUX 4B. Quantization and LoRA do not replace it with a smaller parameter-count model.
- Hardware: RTX 4050 laptop, 6 GB VRAM, approximately 16 GB host RAM. No external/cloud GPU is included.
- Data: public dataset recommendations are wanted, but a selected, verified and approved training subset does not exist yet.
- Quality: identity, expression, anatomy, style, masks and small-size readability must be evaluated separately.
- Claims: neural generation cannot guarantee an exact face or perfect anatomy for every upload. Original-head photographic stickers have a different preservation objective from redrawn cartoons.

## What changes with and without training

| Quality aspect | Current application without custom training | Improved application without custom training | Paired training plus application improvements |
|---|---|---|---|
| Face resemblance | Reference conditioning can redraw the face; animation starts from the generated gesture face. | Better references, original-head handling in photographic mode and independent selection can reduce drift. | Could improve cartoon identity if targets preserve the source faithfully; poor targets or overfitting can worsen it. |
| Cartoon appearance | Default Cartoon route often looks like a posterized photograph. | Direct illustration and an approved design/style reference can produce a more deliberate drawing. | Learns the target style more consistently if the data is coherent. |
| Pack consistency | Facial appearance and drawing can vary across reactions. | Shared approved design, original identity references and stable prompts can help. | Expected principal benefit of training; requires testing on unseen subjects. |
| Reactions | Reviewed outputs sometimes repeat smiles or miss the requested prop/gesture. | Explicit conditioning, tone controls, expression checks and targeted retries can help. | Can learn reactions and controls represented in the dataset; unsupported reactions still need evaluation. |
| Hands and anatomy | Extra hands were observed and accepted. | Reject obvious defects, improve pose/framing controls and use targeted corrections. | Face-only data does not solve hands. Correct gesture targets plus screening are still required. |
| Alpha and captions | Hair/gaps can be damaged; caption layout and torso silhouette can look unfinished. | Fix composition and mask handling directly in code. | Training offers little direct benefit to finishing-code defects. |
| Inference speed | Existing quantized distilled 4B inference runs locally. | Additional references/checks/retries can change latency and must be measured. | An adapter does not inherently make inference faster. Base and distilled inference must be measured separately. |
| Setup and resources | Existing inference environment is available. | Practical repository changes and local inference comparisons. | Requires curated pairs, a separate trainer environment and a successful low-memory feasibility probe. |

This table separates observed current behavior from proposed improvements. It contains no invented quality percentages or trained-result claims. Sources and detailed evidence are preserved in Plans 1 and 2 and the [original review](sticker-quality-review.md).

## Model and dataset decisions

Use `black-forest-labs/FLUX.2-klein-base-4B` for the training experiment. Keep the current distilled quantized 4B route for the initial baseline and fallback. Full-weight conventional training exceeds this laptop's memory budget. The local candidate is an adapter with frozen foundation weights, cached encoders/latents and supported memory-saving options; its fit is still unverified.

[BFL's training requirements](https://docs.bfl.ai/flux_2/flux2_klein_training) list 12 GB VRAM and 32 GB host RAM for the standard 4B training setup. [Musubi's documentation](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/flux_2.md) documents FP8 weights, caching, gradient checkpointing and CPU block swapping. Those features do not constitute a measured successful run on this 6 GB/16 GB laptop.

Dataset selection follows these roles:

| Candidate | Role | Decision gate |
|---|---|---|
| [Comic Faces v2](https://www.kaggle.com/datasets/defileroff/comic-faces-paired-synthetic-v2) | First paired synthetic photo/comic candidate to inspect. | Verify publisher/upstream terms, image dimensions, matching identities, defects and desired visual style. Count/resolution/license were not confirmed by the research tool. |
| [NVIDIA FFHQ](https://github.com/NVlabs/ffhq-dataset) | Verified varied photo source for a noncommercial research pilot; matching cartoon targets must be created and reviewed. | Preserve per-image metadata and comply with dataset/per-image terms. It is not commercially cleared or a source for developing facial recognition technology. |
| [Google Cartoon Set](https://google.github.io/cartoonset/download.html) | Optional style source if its particular avatar style is wanted. | CC BY 4.0, but unpaired with real photos; cannot substitute for identity-preserving edit examples. |
| [GenEAva](https://arxiv.org/abs/2504.07945) | Expression-data investigation candidate. | Dataset release, download, terms and actual reference-target layout must be verified before inclusion. |
| [WebCariA](https://cs.nju.edu.cn/huojing/WebCariA.htm) | Optional noncommercial identity/attribute research. | Author access application and use restrictions; caricature exaggeration and style variability make it unsuitable as the primary faithful-cartoon target set. |

Begin with a proposed 100-200 reviewed pairs in one style. This is a feasibility pilot, not a proven minimum for a product serving everyone. Start with simple face-visible reactions and add correct-hand examples deliberately. Split by identity, keep test subjects untouched, record data provenance and avoid accepting existing defective app outputs as ground truth. Plan 2 contains the complete manifest, review and training milestones.

## Integrated sequence and dependencies

| Stage | Actions | Exit criterion |
|---|---|---|
| C0. Preserve and baseline | Version authored source/workflows, record current configuration and retain existing packs. Correct benchmark route/style selection before measuring quality. | Reproducible current baseline with saved inputs, outputs and route metadata. |
| C1. Improve finishing and controls | Implement tone conditioning, compact caption composition, better silhouette, soft alpha and intentional gaps. Correct UI claims/examples. | Clear exports at chat size and tested control-to-conditioning behavior. |
| C2. Improve generation and review | Separate photographic head preservation from direct cartoon generation. Add independent identity, expression, anatomy/framing and mask checks, review-needed outcomes and targeted retries. | Improved untrained candidate that rejects the observed extra-hand failure and supports review/restore. |
| C3. Curate data and profile training | Inspect/verify source terms, approve style targets and subject splits, prepare a separate environment, cache data and profile loading/backward/optimizer peaks. | Approved pilot plus measured stable laptop updates, or an explicit documented hardware limit. |
| C4. Train and validate | Verify learning on a small subset, train the pilot if feasible, review validation checkpoints and adapter strength, retain complete metadata. | A candidate adapter with validation evidence, not merely a decreasing loss. |
| C5. Compare fairly | Compare unchanged current, improved untrained and trained variants on the same locked held-out subjects/reactions. Isolate Base/distilled and pipeline changes. | Report showing identity/style/emotion/anatomy and practical runtime outcomes, including failures. |
| C6. Adopt conditionally | Integrate the winning candidate as a versioned route, verify quantized laptop deployment and app/export behavior, retain fallback. | Better held-out quality without unacceptable regression or resource behavior. |
| C7. Expand by evidence | Add examples for measured failure categories; expand to twelve reactions and broader subject coverage. Re-test using independent subjects. | Improvements survive broader evaluation; repeated training is driven by identified errors. |

C1/C2 can proceed before training is viable. Data review can happen while application improvements are underway. GPU generation and training should be scheduled without competing for VRAM. No cloud fallback, smaller model substitution or purchase is assumed if C3 fails.

## Fair comparison protocol

Use these variants to avoid attributing pipeline fixes to training:

| Variant | Definition | Comparison purpose |
|---|---|---|
| A. Current baseline | Current quantized distilled 4B workflow and existing finishing behavior, with explicit route/configuration recorded. | Establish the actual starting point. |
| B. Improved untrained | Corrected cartoon/reference/quality/finishing pipeline using an untrained checkpoint. | Measure application improvements independently of custom training. |
| C. Base control | Same approved pipeline and reference layout using untrained Base 4B, with its suitable sampling configuration. | Control for changing distilled to Base; only run if local inference is feasible. |
| D. Trained Base | Same configuration as C plus the trained adapter at a validation-selected strength. | Isolate adapter benefit on the same Base foundation. |
| E. Trained distilled deployment | Corrected pipeline with the Base-trained adapter on distilled 4B, after loader/reference compatibility checks. | Evaluate the practical laptop deployment candidate against matched untrained distilled inference. |

Use the same seeds within matched checkpoint/pipeline pairs, but do not assume identical seeds make different Base/distilled architectures numerically equivalent. Use appropriate sampling settings for each model and record them. The existing distilled four-step regime is intentional; a Base checkpoint is not automatically a four-step model.

Keep the original uploaded photo as the identity reference. Use the same approved style reference where supported and the same reaction/tone instructions, output sizes, finishing parameters and retry budget for a matched comparison. If a parameter must differ for technical compatibility, record the difference rather than claiming an isolated training effect.

Proposed pilot evaluation: at least ten diverse held-out people, initially three reactions (greeting, laughter, surprise), then all twelve. Ten is a manageable planning target, not proof of broad population performance. Include difficult glasses/facial hair/head-angle/lighting examples and add explicit correct-hand/prop examples for applicable reactions. Ensure no held-out person's derivatives appear in training or checkpoint selection.

Record each raw candidate and failure, not only selected finals. Compare first-attempt quality as well as deliverable quality under equal retry budgets. Use side-by-side unlabeled images for visual ratings where practical, avoiding model-name bias. Review source photos beside outputs for identity and request subject recognition feedback where available.

## Measurements and adoption criteria

| Measurement | How to assess | Proposed gate |
|---|---|---|
| Recognition | Subject feedback or carefully defined human feature comparison with the source; advisory SFace recorded separately. | At least 10 recognizable reactions out of 12 per evaluated subject as an initial target. Ratings without subject feedback must be labeled accordingly. |
| Expression and pose | Whether the intended reaction, gesture and requested prop are visibly communicated. | Every accepted sticker matches its instruction. |
| Anatomy and seams | Review hand/arm counts, plausible shapes, head alignment, cropping and foreground occlusions. | No obvious severe defect in delivered artwork; record defect/rejection rates in raw attempts. |
| Style consistency | Compare line work, shading, palette, face/body proportions and character design across a pack. | One coherent approved style with no substantial identity regression. |
| Export quality | Inspect 128/256px previews and platform-size exports on multiple backgrounds. | Legible captions/expressions, clean alpha and intact useful details. |
| Runtime | Measure image/pack latency, retries, loading peaks, GPU memory, host RAM and paging behavior. | Stable local operation; acceptable latency must be agreed from measured results, not guessed in advance. |
| Recovery/functionality | Backend checks, frontend type check, app generation/approval/regeneration/restore and export workflow. | Existing required checks pass and the prior working route remains available. |

These are proposed engineering criteria, not achieved metrics. SFace cosine is not a percentage, recognition probability or complete quality score. Thresholds must be calibrated for the drawing style. Falling training loss and good training-subject outputs do not establish unseen-person generalization.

Adopt training only when it improves the intended cartoon/style task compared with the improved untrained candidate and does not materially degrade identity, anatomy or practical laptop use. If results are inconclusive, retain the improved untrained route and gather more independent evidence. A trained adapter should not be adopted solely because time was spent training it.

## App integration and recovery

- Keep photographic and cartoon routes separately versioned and labeled. Use original-head preservation for photographic mode; do not paste a photographic face or apply the current posterization filter to artwork that already has the desired trained drawing style.
- Record checkpoint/adapter hashes, adapter strength, source/reference layout, sampling settings, masks, renderer and retry outcomes with each generated version.
- Check exact trainer serialization and ComfyUI loader support before shipping. Confirm the adapter works with the selected quantized deployment representation; checkpoint compatibility is not assumed from its file extension alone.
- Preserve raw generation, expression/animation and final exports to isolate new defects. Keep captions, outline and platform compression as finishing operations.
- Maintain candidate comparison, restore and a route fallback. Existing saved packs remain intact; regeneration is an explicit operation.
- If the trained route fails quality or resource checks, fall back to the validated untrained 4B route. If defects originate in composition or segmentation, fix those components rather than retraining to compensate.

## Risks and limits

The principal training risk is data quality: an attractive target with a changed face teaches the wrong transformation. Random cartoon images teach style without establishing source-person correspondence. Synthetic paired data may not transfer cleanly to real uploads. Face-only data provides inadequate evidence for expressive bodies and hands. A pilot may overfit and larger datasets may exceed practical laptop runtime.

The principal hardware risk is host RAM as well as VRAM. CPU offload and caching can reduce GPU residency while still failing during initial checkpoint loading, reference encoding or backward/update steps. A successful forward pass does not prove training fit. Profile all stages and report failures without silently changing hardware or model size.

Full fine-tuning, face-specific adapters for each user, custom differentiable identity losses, training a new smaller model and cloud hardware are not part of this confirmed local plan. They would be distinct future decisions. Neither LoRA nor full fine-tuning guarantees perfect identity or anatomy; measured evaluation and rejection/review remain necessary.

## Deliverables and current status

1. Plan 1 implementation: corrected untrained pipeline, review/restore controls, saved baseline and visual/export checks.
2. Plan 2 feasibility: verified approved dataset, pinned environment/configuration and measured laptop memory probe.
3. If feasible: trained adapter, checkpoint-selection evidence and validation artifacts.
4. Locked held-out comparison report for matched variants, including quality, rejection rate and runtime/resource measurements.
5. If justified: versioned trained deployment workflow with compatibility checks and recovery to the improved untrained route.

Current status: all three plans are saved. Application improvements, dataset curation, training probes, training and adoption remain planned. The existing review/check results are evidence about the prior application state, not evidence that this combined plan has been completed.
