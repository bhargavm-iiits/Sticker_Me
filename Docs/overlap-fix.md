# Saved sticker overlap correction — 4 October 2026

## Latest correction: incompatible face geometry and exaggerated Surprise

The third screenshot came from pack `d9ce2c8e-4811-477b-b509-1793d28d8108`. Its clean pose had a frontal smiling face, while the animation used the original angled photo and a heavily exaggerated expression driver. Fitting eyes/nose and blending a central oval did not reconcile the different cheeks and jaw. The merge introduced a bright cheek seam, large eyes and a stretched mouth. The corrected transparency code was already active; this defect was in the facial artwork.

The default Realistic/Likeness path is now **`coherent-photo-edit-v4`**: expression and gesture are generated together with the original photo references. It never calls the animator, neutral-face restoration or regional face/hand overlay. Corrections produce one coherent replacement and retain the previous version for comparison. Photographic prompts request restrained jaw motion and natural eye size; tone and intensity still change instructions. The old animation route requires explicit `STICKERME_PHOTO_ANIMATION=1` and remains experimental. The UI and model provenance describe the new default, and LivePortrait is no longer required to create photo-style packs.

Two isolated GPU trials produced four full-photo candidates. They removed the paste seam but drifted from the reference or gave an unsuitable expression, so none replaced the saved sticker. For this particular saved Surprise, three CPU repair candidates instead animated the clean pose's **own same-view face**, at strengths 0.25/0.40/0.55. The inspected 0.55 version retained the pose and removed the angled-face seam with a restrained open-mouth reaction. This is an explicit repair of saved artwork, not the default generation route. Its advisory similarity score is 0.655 versus 0.557 before repair; it remains unaccepted pending visual review.

Only that Surprise sticker was changed to revision 2. The surrounding pose pixels, seed and caption were preserved. All 95 other sticker records, packs, jobs, attempts and existing versions were verified unchanged. The original distorted version remains available to restore.

- [Current Surprise before/after](../runtime/surprise-repair/before-after.png), [three inspected repair candidates](../runtime/surprise-repair/candidates.png), and [production verification](../runtime/surprise-repair/verification.json).
- GPU trial artifacts: [first trial](../runtime/photo-route-check/21e00bfebfe04a798e7397740a947236/contact-sheet.png) and [second trial](../runtime/photo-route-check/bb89cc1848184f19bb144b047ee89c59/contact-sheet.png). These are rejected trial outputs, not accepted identity examples.

Validation: **72 backend tests passed**, and the production TypeScript/Vite build passed. New tests prohibit animation/restoration and regional overlays in the default photo path, allow photo packs without the optional animator, and check restrained expression/tone/intensity instructions. The API serves the corrected revision and reports photo animation disabled. Both worker and API are reloaded. Tests verify the pipeline behavior; the GPU trials still show that perfect identity and expression are not established for arbitrary people.

## Follow-up: grey doubled shirt and hand edges

The first correction addressed displaced head artwork but missed a separate transparency defect. A new pack (`c5c2701e-9f12-41df-afcb-f294a00368a7`) reproduced grey rings around shoulders and hands even though its raw artwork had clean edges.

The installed rembg default `naive_cutout` multiplies RGB by its mask while compositing against transparent black. The resulting soft pixels were subsequently interpreted as straight-alpha PNG pixels, darkening the edges again. The sticker-border code also used masked `paste` onto transparent black, causing the same RGB/alpha mistake in its white outline.

Background removal now requests only the segmentation mask and attaches it to the original RGB. The white border receives its alpha directly and is composited once. Soft hair, white clothing and finger gaps retain their mask geometry. Regression tests verify unchanged soft-edge RGB and white borders on white, purple and dark backgrounds.

Eight current stickers across the latest pack and the earlier white-shirt pack were rebuilt from their unchanged artwork and masks, including both Laughter and Surprise outputs. Captions, seeds, likeness scores, pack status and old versions remain intact. Appearance changes require review again. The API and worker were both reloaded; the existing GPU engine was retained.

- [Latest pack before/after on checkerboard and dark backgrounds](../runtime/alpha-fix/c5c2701e-9f12-41df-afcb-f294a00368a7/before-after.png).
- [Earlier pack before/after](../runtime/alpha-fix/d0d6147c-6d89-4193-b870-ffb6bd8d4464/before-after.png).
- [Applied repairs](../runtime/alpha-fix/applied.json) and [production verification](../runtime/alpha-fix/verification.json).

All **68 backend tests passed**. Production verification compares prior-version hashes, unchanged artwork and masks, preserved database records and the exact images served by the API. Running the actual installed segmentation on the new Laughter artwork matches the repaired cutout exactly. This verifies the transparency fix for future rendering without requiring another diffusion generation. Expressions, identity and generated anatomy still require visual review; Surprise in this pack retained a smiling fallback face.

To preview another pack without modifying it, use `python -m scripts.repair_sticker_alpha --packs PACK_ID`; inspect the comparison before adding `--apply`. This repairs alpha/color representation and preserves masks; it does not alter bad anatomy or other generated artwork defects. A database backup is saved before applying.

## Earlier head compositor correction

The saved gesture images contained one clean person. The compositor expanded the animated source-face mask into the hair and ears, layering displaced source outlines over the generated head. The sticker border then made those duplicated edges more visible.

The compositor now keeps the generated pose's hair, head and body outline. It aligns the animated eyes and nose to the target face and blends only inside an inward-feathered facial oval. The mouth is excluded from the alignment landmarks so expressions remain free to change. Source segmentation restricts the blend instead of enlarging it. Unsafe geometry returns the existing guarded fallback; detected hands remain protected.

The affected Greeting, Agreement, Refusal and Surprise stickers were repaired from saved clean poses and raw animation outputs. No new GPU generation was needed. Each repair increments the revision, preserves the prior version for restore, and retains the caption and seed. Laughter already matches its saved clean pose exactly and has no applied face composite; it was left unchanged. The cancelled pack remains cancelled and the repaired images still require visual review.

[Before/after comparison](../runtime/overlap-debug/d0d6147c-6d89-4193-b870-ffb6bd8d4464/before-after.png) and [repair measurements](../runtime/overlap-debug/d0d6147c-6d89-4193-b870-ffb6bd8d4464/repair.json).

The corrected SFace cosine scores are 0.839, 0.796, 0.801 and 0.705, respectively. They are slightly lower than the overlapping composites and are advisory; removing the duplicated outline does not establish perfect identity or anatomy. The generated hairstyle is retained rather than replacing its entire silhouette with the source photograph.

Earlier validation: **66 backend tests passed**. New regression checks verify that source alpha cannot add a second outer silhouette, mouth expression does not determine the alignment, and excessive face deformation is rejected. [Saved-data and serving verification](../runtime/overlap-debug/verification.json) records those historical production checks. These measurements and revisions predate the transparency repair above. Interactive browser verification remains unavailable in this environment.

For another photographic pack, `python -m scripts.repair_photo_composites --pack PACK_ID` writes a comparison without modifying saved stickers. Inspect it before using `--apply`. Repairs refuse active jobs or changed sticker revisions and require the corresponding saved pose and animation artifacts.
