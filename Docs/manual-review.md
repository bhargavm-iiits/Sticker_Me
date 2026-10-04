# Manual review after full generation — 4 October 2026

The reported pack had twelve ready images, six accepted and six blocked by the automatic anatomy detector. Both the UI review button and the API rejected blocked images, so finishing the remaining nine did not make those buttons usable.

The review panel now labels such images **Check flagged image**, displays the detector warning, and offers **I checked it—accept anyway**. The user can accept a visually correct image or generate a correction. The editor shows the number of reviewed images out of the pack total. No stickers are accepted automatically by this change.

The review endpoint accepts an optional decision containing `override_detected` and the current `revision`. A flagged image requires both explicit override and matching revision. Stale versions, unfinished images and packs still generating remain unavailable for acceptance. Ordinary review requests remain compatible. Detector findings remain in `quality_report.checks`; the separate `quality_report.review` records the human decision, revision and whether it overrode a flag.

Three new tests passed: explicit flagged-preview acceptance with retained findings, stale/unfinished image rejection, and review of all nine remaining flagged stickers followed by successful pack export. The latter verifies no new generation and unchanged PNG bytes. The existing approval guard test also passed. TypeScript/Vite production compilation passed.

The API and production frontend are reloaded. [Release verification](../runtime/manual-review-verification.json) checks that the new decision schema and UI are served, stale review is rejected, and the actual user's accepted/blocked statuses remain unchanged until they review the images. Browser automation is unavailable; browser interaction is not claimed tested.

PNG downloads remain independent of review. The WhatsApp / Telegram ZIP becomes available once every image has been reviewed or retained as legacy artwork.
