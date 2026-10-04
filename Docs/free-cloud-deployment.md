# Free cloud demo

Live site: https://stickerme-free.vercel.app

The free deployment runs the React UI on Vercel and calls the official public
`black-forest-labs/FLUX.2-klein-4B` Gradio Space directly from the visitor's browser.
It does not create a paid Render service or rent a GPU. The local FastAPI/ComfyUI
application remains available when `VITE_FREE_CLOUD` is unset or `false`.

The Hugging Face documentation describes free ZeroGPU hosting for qualifying
accounts. On 4 October 2026, the signed-in creation and duplication pages for this
account required PRO, so the demo uses the existing official Space instead.

## Features

- One portrait, five styles, three tones and twelve distinct reactions.
- Generate one reaction or up to three at a time; stop and retain completed work.
- White edge-background removal, outline and caption composition in the browser.
- Editable captions, redraw, manual face/hand review, and a keep-background option.
- Individual 512 x 512 PNGs and a ZIP containing PNGs plus generation metadata.
- Photo and finished packs saved as blobs in browser IndexedDB. No shared pack database.

## Limits

The public Space controls queueing, availability and GPU quota. Signing in to the
Hugging Face website does not authenticate API requests made by this separate
frontend; the demo uses the unauthenticated quota. No account token is bundled in
the app. A quota error stops a batch and retains completed stickers. There is no
automatic retry that consumes additional quota.

Photos are sent to Hugging Face only after the visitor checks the permission box
and clicks a generation button. Input retention is controlled by the public Space.
Local browser storage is device-specific and can be cleared or evicted. Download
a ZIP for a portable backup.

White background removal uses edge-connected pixels rather than the local
backend's rembg segmentation. Review the transparency, especially pale clothing
touching the background. The keep-background button provides a fallback.

This is a demo of the generation and PNG workflow. The local application's
character-design approval, advisory quality detectors, regional mask corrections,
immutable version history and WhatsApp/Telegram packaging are not in this mode.

## Build and deployment

From `frontend/` in PowerShell:

```powershell
$env:VITE_FREE_CLOUD = 'true'
npm.cmd ci
npm.cmd run test:cloud
npm.cmd run build
```

In Vercel, use `frontend` as the project root, the Vite preset, `npm run build`
as the build command, and `dist` as the output directory. Set `VITE_FREE_CLOUD=true`
for production and preview builds. Environment changes require a new deployment.
The frontend `vercel.json` configures SPA routing.

No private portraits, existing local pack files, Python environment or model
weights are uploaded to Vercel.

References:
- https://huggingface.co/spaces/black-forest-labs/FLUX.2-klein-4B
- https://huggingface.co/docs/hub/spaces-api-endpoints
- https://huggingface.co/docs/hub/spaces-zerogpu
- https://vercel.com/docs/frameworks/frontend/vite
