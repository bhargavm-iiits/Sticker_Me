# PNG downloads — 4 October 2026

The reported pack had all twelve reactions generated, but six had automated `blocked` quality status. The existing export control required every reaction to be accepted, preventing the user from saving their images.

Saved images can now be downloaded independently of pack approval and quality status. The **Download PNGs** button is available above the preview/editor/progress/export pages when saved images exist. It saves a ZIP of the available transparent PNGs with the current captions. Each review card also has **Save PNG**. The WhatsApp / Telegram export is labelled separately and retains its review checks. Downloading does not approve stickers or alter artwork, quality status or revisions.

- Pack PNG endpoint: `GET /api/packs/{pack_id}/export/png`. Only generated image files are included; an empty pack returns 409. Filenames follow `01-greeting.png`, `02-agreement.png`, etc. The response contains PNGs only and does not apply platform-specific WebP conversion or file-size restrictions.
- Single PNG endpoint: `GET /api/packs/{pack_id}/stickers/{sticker_id}/download`. It sends an attachment with a descriptive filename, checks pack ownership and reports an unavailable image rather than downloading an error page.

Five download tests passed: blocked/unreviewed full packs, partial previews, current caption updates, ownership validation, empty/missing packs and legacy cutouts. Four existing export/approval regression tests also passed. The TypeScript/Vite production build passed. Browser automation is unavailable; native browser download interaction is not claimed tested.

The actual reported pack `4a3623a4-bbdb-4096-93aa-205a07571601` was downloaded through the live API. All twelve files are 512×512 transparent RGBA PNGs; ZIP and individual download bytes match the displayed saved images. Six blocked reactions are included without changing their review status. The production frontend and API are reloaded.

[Download the twelve PNGs as a ZIP](../runtime/downloads/stickerme-4a3623a4-bbdb-4096-93aa-205a07571601-png.zip), [individual PNG folder](../runtime/downloads/stickerme-4a3623a4-bbdb-4096-93aa-205a07571601-png), and [live verification](../runtime/downloads/png-download-verification.json).
