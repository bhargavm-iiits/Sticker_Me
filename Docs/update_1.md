# StickerMe build guide: review and implementation update 1

Reviewed 3 October 2026. Companion to [StickerMe-Build-Guide.md](StickerMe-Build-Guide.md). This review originally preceded implementation. The application and real GPU workflow are now implemented; see [Build-Status.md](Build-Status.md) for verified results and remaining quality limitations.

**Current scope override:** English only; no Telugu installation/localization work. New packs must independently generate cartoon faces, expressions and gestures, not reuse the same photo with different captions. The cutout-first fallback recommendation below describes the earlier feasibility stage, not the current default.

## Assessment

The guide has a sound first-release shape: preview approval, sequential generation, captions stored separately from artwork, durable jobs, and ZIP export that does not pretend to install stickers directly. The main dependency is whether FLUX.2 Klein 4B image editing works acceptably on an RTX 4050 with approximately 6 GB VRAM. ComfyUI's documented distilled example uses about 8.4 GB VRAM. A 2.6 GB GGUF weight file does not account for the encoder, VAE, activations, or runtime buffers. Keep Klein as a candidate until measured on the target machine.

## Improvements to make before implementation

### 1. Set a measurable model decision gate

Run the exact proposed GGUF model, compatible encoder, VAE, reference workflow, and low-memory settings on the target laptop. Generate three different reference edits, then repeat the run. Record model and workflow revisions, peak dedicated VRAM, system RAM, paging, wall-clock time per image, likeness, gesture accuracy, cropping, and segmentation quality. Agree on an acceptable time per sticker and approve the visual quality before selecting the default engine.

If the workflow fails or swaps excessively, release a clearly labelled photo-cutout and caption workflow first. A smaller generative fallback becomes available only after its own workflow and smoke test pass. Photo-cutout mode can produce caption variants from one pose; it must not claim to generate new facial expressions.

### 2. Break the master prompt into stage-sized tasks

The current master prompt spans model integration, persistent recovery, six screens, localization, and platform-specific exports. Implement one runnable stage at a time, with an acceptance check and recorded evidence for each. Keep the 24-intent catalog, 24-sticker expansion, extra languages, training, and direct sticker installation outside the first-release gate.

### 3. Save separate image layers

Keep four distinct assets per sticker or source: uploaded reference, generated text-free image, transparent cutout, and captioned output. A caption or language change should rerender only the captioned output. It should not rerun image generation or background removal. Offer a way to correct a foreground mask when segmentation clips hair, hands, glasses, or clothing. Validate transparency from alpha values, not from how the image looks on a checkerboard.

### 4. Define recovery when submission status is unknown

Create a durable job attempt before submitting to ComfyUI. Save the returned `prompt_id` and reconcile against `/queue` and `/history/{prompt_id}` after restart. A crash between submitting a prompt and storing its ID can leave an unknown outcome; represent that state explicitly and check before retrying. Do not promise exactly-once execution from the ComfyUI API alone. Only interrupt a running prompt after confirming that it belongs to this application; never clear a shared queue.

Use one worker with atomic job claims, leases and heartbeats, idempotency keys for user requests, and atomic output-file writes. Deletion must prevent an in-flight worker from recreating removed pack assets.

### 5. Complete export profiles

For WhatsApp static stickers, validate transparent 512 x 512 WebP files at no more than 100 KB each, a 96 x 96 tray icon at no more than 50 KB, and 3–30 stickers per pack. For Telegram static stickers, validate transparent PNG or WebP at no more than 512 KB, with one side 512 pixels, and associate at least one relevant emoji with each sticker. Store these emoji mappings and the tray icon in the export manifest. Keep profile limits configurable and verify them again before release.

The first release should offer **Download ZIP** and **View import instructions**. Direct WhatsApp or Telegram installation requires a separately built and tested integration.

### 6. Resolve the phone experience

A server bound to localhost is available on the laptop, not automatically in a phone browser. Treat mobile-first as responsive layout for version one and document how to transfer exported stickers to a phone. Phone browser access needs a separate local-network design with access controls. One-click installation needs a supported native or account-based integration.

### 7. Keep the release English-only

Use English starter phrases and editable custom captions. Remove the Telugu selector, API support and font/shaping readiness gate. Verify English wrapping and caption bounds with the actual export font. Additional languages are outside this release unless requested later.

### 8. Protect local photo data

Normalize orientation, bound upload bytes and decoded pixels, and strip unnecessary EXIF metadata from derived outputs. Serve only validated asset paths. Restrict browser origins and local API access so another browser page cannot silently submit photos or download private packs through the localhost service. Delete references, derived images, and queued work together when a pack is removed.

## Implementation sequence

| Stage | Deliverable | Exit check |
|---|---|---|
| 0. Feasibility | Hardware doctor and standalone Klein image-edit workflow | Measured three-image test and a decision on generative versus photo-cutout first release |
| 1. CPU vertical slice | Upload, orientation handling, cutout, caption composition, PNG/WebP/ZIP export | One real photo exports valid assets; a caption change reuses the saved cutout |
| 2. Durable backend | SQLite schema, one worker, attempts, leases, deletion, and recovery states | Restart, duplicate request, cancellation, and deletion tests pass |
| 3. Image integration | Pinned ComfyUI workflow, explicit node bindings, ownership, and reconciliation | Three previews and one sticker regeneration work through the app API |
| 4. Product UI | Six screens with progress, partial completion, errors, and editing | The 12-sticker browser journey completes end to end |
| 5. Release checks | Platform profiles, reviewed phrases, visual inspection, setup scripts | ZIP passes validators and a fresh Windows setup is reproducible |

## First-release acceptance

- Upload one permitted photo and produce a usable result with the selected, visibly identified engine.
- When generative mode is available, generate three previews sequentially, approve one appearance, create 12 stickers, and regenerate one selected sticker.
- Edit an English caption without GPU work or repeated background removal.
- Restart during a pack, reconcile completed and uncertain attempts, and resume without losing completed stickers.
- Export a ZIP and individual files that pass dimensions, transparency, size, clipping, tray-icon, and emoji-mapping checks for the selected profiles.
- Inspect the exported pack on light and dark chat backgrounds and verify English caption bounds with the actual font.
- Record real timings, memory use, installed versions, and any unverified target-hardware behavior. Do not report mocked generation as real inference.

## Source checks

- [ComfyUI Klein guide](https://docs.comfy.org/tutorials/flux/flux-2-klein): distilled 4B workflow and documented example memory use.
- [Unsloth Klein 4B GGUF files](https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF/tree/main) and [ComfyUI encoder files](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/tree/main/split_files/text_encoders): file variants and sizes.
- [ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes): prompt submission, queue, history, and interrupt endpoints.
- [WhatsApp Android sticker requirements](https://github.com/WhatsApp/stickers/blob/main/Android/README.md) and [Telegram sticker import requirements](https://core.telegram.org/import-stickers): static sticker formats and metadata requirements.
