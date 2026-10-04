# StickerMe — completed work and continuation handoff

**Snapshot:** 3 October 2026, approximately 17:14 IST (+05:30).  
**Workspace:** `D:\Additional Project\Img_2_Sticker`.  
**Purpose:** Consolidate the work completed so far, implementation analysis, validation evidence, and remaining improvements. This is a resumable project summary, not a claim of exhaustive production readiness.

## 1. Quick resume

- The English-only cartoon sticker pipeline is implemented and demonstrated on the local GPU. New packs generate distinct artwork, expressions, and gestures rather than repeating one photograph.
- Three preview reactions are generated first. User approval generates the remaining nine. Selected redraw changes only one sticker; caption/mask edits are CPU-only.
- Existing photo-cutout packs are preserved as legacy packs. They are not automatically converted; create a new pack for cartoons.
- Previous validation: **22 tests passed**, frontend production build passed, Python compilation passed, real 12-sticker generation/export passed, and real single-sticker regeneration isolation passed.
- This documentation session rechecked source and saved benchmark records and collected **22 tests** successfully. It did **not** rerun the full suite, build, or GPU benchmarks.
- Current service snapshot: `scripts.services status` reports `engine_ready: true` and owned engine/worker running. The API at `127.0.0.1:8000` was reachable earlier in this session. Services were left untouched; an earlier successful shutdown test is historical, not the current state.
- The repeated full-pack benchmark took **474.12 seconds**, including three previews in **98.34 seconds**. These are sample timings, not guarantees.
- Browser interaction, actual mobile importing, broad portrait/style quality, and several recovery/privacy edge cases still need validation or hardening. See sections 8–9.

## 2. Request history and scope decisions

1. Reviewed the original build guide and recorded improvements in `Docs/update_1.md`.
2. Built the initial local application and documented setup/test commands and progress in `Docs/Build-Status.md`.
3. Changed the active product scope following the user's feedback: remove Telugu, actually cartoonize the person, and generate different hand gestures and facial expressions for each sticker.
4. Implemented and benchmarked the local generative pipeline, editor, recovery controls, and exports.
5. This request consolidates the completed work and a fresh source review into `Docs/work.md`; it does not implement the newly identified follow-ups below.

**Why the earlier stickers looked identical:** The first release removed the background from one photograph and changed captions. That was a cutout/compositing pipeline, not a generative image-editing pipeline; it could not redraw the face or hands. The new path supplies the original reference image, a reaction-specific prompt, and an independent seed to a local image-editing model for every sticker. There is no silent cutout fallback when the engine is unavailable.

Telugu requirements in historical planning documents are superseded. The active UI/API accepts English only. Extra languages, training, 24-sticker expansion, hosted generation, and one-click mobile installation are outside this release.

## 3. Completed implementation

| Area | Completed work | Main files |
|---|---|---|
| API and validation | FastAPI localhost service; photo/settings/consent validation; English-only creation; idempotency key and request fingerprint; engine-readiness rejection | `backend/app/main.py`, `config.py` |
| Persistence | SQLite WAL/foreign keys; pack, sticker, job, and durable attempt records; versioned migrations preserving legacy packs | `backend/app/db.py`, `migrations.py` |
| Generation | Reference-image editing with FLUX.2 Klein 4B GGUF; pinned workflow/bindings; model/node diagnostics; separate prompt and seed per reaction | `backend/app/comfy.py`, `catalog.py`, `workflows/` |
| Worker and recovery | Sequential processing; atomic claims; one worker per data directory; renewable leases; persisted attempts before submission; queue/history lookup; explicit uncertain outcomes | `backend/app/worker.py`, `comfy.py` |
| Approval and redraw | Three previews; approval reuses completed previews and generates nine more; one-sticker redraw preserves other images; completed work retained on resume | `main.py`, `worker.py` |
| Image processing | Input normalization; atomic PNG replacement; cartoon white-background cleanup with rembg fallback; outlined transparent 512-square composition; English caption wrapping | `backend/app/imaging.py` |
| Editing | Caption edit/removal; foreground erase/restore/reset/save mask; reorder/remove; generated-art and foreground layers; light/dark transparency preview | `main.py`, `frontend/src/App.tsx` |
| Progress | Application SSE snapshots with polling fallback, partial-result display, cancellation and resume controls | `main.py`, `frontend/src/App.tsx` |
| Export | ZIP containing bounded WhatsApp/Telegram assets, tray icon, cover, text-free layers, manifest, seeds and workflow provenance, manual-import instructions | `main.py`, `imaging.py` |
| Operations | Isolated Python environments; setup/repair/download scripts; hidden owned services; PID/child identity checks; logs, doctor, unit tests and separate GPU smoke scripts | Root PowerShell scripts, `scripts/`, `tests/` |

The frontend uses React/TypeScript/Vite with Tailwind and a responsive purple/lilac interface. Its seven screens cover home, upload, settings, progress, preview, editor, and export. Implementation exists; live browser/accessibility acceptance is not yet verified.

### Twelve reaction intents

| Intent | Requested expression/gesture |
|---|---|
| Greeting | Smile and wave |
| Agreement | Positive expression and thumbs-up |
| Refusal | Firm expression and crossed forearms |
| Laughter | Laughing, hand at belly and wiping a tear |
| Surprise | Wide-eyed expression, hands beside cheeks |
| Thanks | Grateful expression and palms together |
| Apology | Apologetic expression, hand on heart, bowed head |
| Affection | Loving expression and hand-heart shape |
| Waiting | Impatient expression and pointing at a wristwatch |
| Busy | Focused expression and laptop typing |
| Goodnight | Sleepy expression, cheek resting on hands/pillow |
| Congratulations | Celebratory expression, raised fists and confetti |

Greeting, laughter, and surprise are the preview set. Available styles are cartoon/chibi/comic; tones are playful/warm/dramatic. These are prompt controls, not separately trained models. Correct hands, expression, and likeness still require human review.

## 4. Architecture and lifecycle

```text
Upload and normalize original reference
  -> queue three preview reactions
  -> worker generates each from the same original reference
  -> show previews / awaiting approval
  -> approve -> generate remaining nine -> ready
  -> caption or mask edit / selected redraw / reorder / remove
  -> validate and export ZIP

Per reaction:
reference + intent/style/tone prompt + seed
  -> persisted attempt + ComfyUI reference-edit workflow
  -> generated RGB artwork
  -> cartoon background cleanup or rembg
  -> transparent foreground + outline + optional caption
  -> 512 x 512 sticker
```

- The original reference is reused for every generation, not the previous generated sticker. Prompts ask to retain identity, hair, outfit, and accessories and prohibit generated captions.
- Worker ownership uses a Windows process lock per data directory. Leases last 60 seconds and heartbeats run every 5 seconds; stale running jobs can be reclaimed.
- Packs use states including `queued`, `processing`, `awaiting_approval`, `ready`, `failed`, `cancelled`, and `deleting`. Jobs use `queued`, `running`, `done`, `failed`, and `cancelled`.
- Attempt records include prepared/submitting/submitted/completed/failed/cancelled/uncertain/abandoned states, stable client prompt UUID, workflow JSON, and reference hash.
- ComfyUI submission is reconciled using its queue/history HTTP endpoints. Engine polling is HTTP, not WebSockets. Frontend progress uses the application's SSE endpoint.
- Cancellation targets only a verified app-owned queue entry/prompt; unrelated ComfyUI tasks must not be globally cleared or interrupted.
- Normal API creation explicitly selects `cartoon`. The database model still defaults to `photo_cutout` for legacy compatibility: future internal creation code must choose the mode explicitly.
- Captions use saved foregrounds; mask editing uses generated artwork colors and supplied alpha. Neither edit should invoke generation.
- Export requires a ready pack with 3–30 stickers. WhatsApp files are transparent 512-square WebP at most 100 KiB; Telegram PNG/WebP at most 512 KiB; tray icon is 96-square PNG at most 50 KiB. These are the implemented validation thresholds, not an independent current-platform rules audit.
- Downloading a ZIP does not install a pack on a phone. No direct mobile integration or LAN access is implemented.

## 5. Environment, runtime, and file map

Miniconda base at `C:\Users\Bhargav\miniconda3` remains unchanged. Use the workspace's isolated executables, not an arbitrary base Python.

| Component | Recorded configuration |
|---|---|
| Hardware | RTX 4050 Laptop GPU, 6141 MiB VRAM; approximately 15.2 GiB physical RAM |
| App interpreter | `.venv/Scripts/python.exe`; workspace CPython 3.12.15 |
| Engine interpreter | `runtime/engine-env/Scripts/python.exe` |
| PyTorch | `2.11.0+cu128`; torchvision `0.26.0+cu128` |
| ComfyUI revision | `e9027f2b30f37bb3052714eb08fcf479542f4fc0` |
| ComfyUI-GGUF revision | `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` |
| Diffusion model | `flux-2-klein-4b-Q4_K_M.gguf` |
| Text encoder | `Qwen3-4B-Q4_K_M.gguf`, used as the Flux2 text encoder |
| VAE | `flux2-vae.safetensors` |
| Workflow | 512 x 512, four distilled Euler steps, CFG 1, reference latent conditioning |
| Memory policy | Low-VRAM engine mode; CPU text encoder/VAE; dynamic VRAM disabled; 0.8 GB reserve; engine previews disabled |
| Local endpoints | App `http://127.0.0.1:8000`; engine `http://127.0.0.1:8188` |

Model downloads total approximately 5.4 GB. Exact repository revisions, sizes, and SHA-256 hashes live in `workflows/models.json`; dependency pins live in `workflows/engine-requirements.txt`. Avoid replacing these models with unverified filename lookalikes.

- `workflows/klein4b-api.json`: executable API graph.
- `workflows/bindings.json`: reference node `4.image`, prompt `6.text`, seed `10.noise_seed`, output/prefix node `16`.
- `workflows/klein4b-human.json`: human canvas graph; schema/wiring checked, live canvas import not yet verified.
- `runtime/stickerme.sqlite3` and `runtime/packs/`: normal application data.
- `runtime/comfyui/`: managed engine checkout, models, inputs and outputs.
- `runtime/engine-models.json`: verified model installation record.
- `runtime/services.json`, `runtime/engine.log`, `runtime/worker.log`: owned-service metadata/logs; verbose engine log is `runtime/comfyui/engine.log`.
- `runtime/gpu-smoke/` and `runtime/cartoon-smoke/`: separate benchmark databases/artifacts, not the ordinary user-pack store.
- `STICKERME_DATA_DIR` relocates the app database/pack data. The managed engine remains under the workspace runtime directory.
- `STICKERME_COMFY_URL` selects an already-running compatible local engine. Automatic managed startup is for the default local engine.
- Workspace uv is `.tools/bin/uv.exe`; use `--cache-dir .cache/uv` for direct uv commands to avoid the restricted global cache.
- This workspace is not an application Git repository. Nested engine checkouts are repositories; do not initialize Git, create branches, or commit without a separate request.

## 6. Validation evidence and limitations

### Automated and operational checks

Previous full suite: **22 passed in 81.50 seconds**, with one upstream Starlette TestClient/httpx deprecation warning. Generation is mocked in backend unit tests; those tests alone do not prove image quality or GPU inference.

| Test file | Tests | Coverage |
|---|---:|---|
| `tests/test_cartoon_flow.py` | 6 | Preview/approval, distinct simulated artwork, isolated redraw, CPU edits, idempotency, English-only validation, cancel/resume, no photo fallback, prompt requirements |
| `tests/test_cutout_flow.py` | 4 | Legacy caption/export, retry, deletion while processing, permission/upload validation |
| `tests/test_engine_recovery.py` | 6 | Attempt persistence/reconnection, unknown/server-error submissions, scoped cancellation, stale leases, unfinished-attempt deletion |
| `tests/test_migrations_and_masks.py` | 3 | Legacy migration, cartoon mask preservation, scoped engine-file cleanup |
| `tests/test_services.py` | 2 | Verified interpreter-child shutdown and PID-reuse protection |
| `tests/test_workflow.py` | 1 | Workflow bindings and canvas/API link consistency |

Frontend production build and Python compilation previously passed. Startup, API/frontend HTTP responses, doctor/readiness, unsupported-language rejection, hostile-origin rejection, duplicate API-port refusal, and owned engine/worker/interpreter-child shutdown were previously checked. These are not substitutes for browser interaction or a complete security audit.

In this documentation session, `pytest --collect-only -q` confirmed all 22 tests are discoverable and reproduced the deprecation warning. No new full-suite pass is claimed.

### Real GPU benchmarks

| Run | Observed result |
|---|---|
| Initial three raw edits | Wave 54.48 s; laughter 35.31 s; surprise 34.28 s |
| Refined three raw edits | 36.36 / 34.33 / 33.27 s |
| First full pack | Preview 105.55 s; total 451.58 s; 12 distinct artwork hashes; ZIP 7,077,903 bytes; sampled GPU 3537 MiB; whole-system RAM 14.78 GiB |
| Refined full pack | Preview 98.34 s; total 474.12 s; 12 distinct artwork hashes; ZIP 6,922,029 bytes; sampled GPU 3505 MiB; whole-system RAM 13.96 GiB |
| Selected regeneration | 33.66 s; all 11 other PNGs unchanged; original reference unchanged; subsequent caption edit preserved generated artwork; export passed |

Artifacts rechecked for this handoff:

- `runtime/gpu-smoke/result.json`: raw-edit adapter benchmark. This script does not complete normal pack/job lifecycle states and should not be mistaken for a full application acceptance test.
- `runtime/cartoon-smoke/result.json`: full API/worker preview-approval-generation-export benchmark; pack `c555d68b-a92a-4169-bce9-507f59d84bdd`.
- `runtime/cartoon-smoke/packs/c555d68b-a92a-4169-bce9-507f59d84bdd/contact-sheet.png`: later full-pack visual review sheet.
- `runtime/cartoon-smoke/regeneration.json`: isolated redraw evidence; sticker `9950c0ee-7dbd-4d22-b9d0-0434a5a282ee`.

The benchmarks used the bundled scikit-image astronaut sample, not a user's private portrait. GPU/system RAM was sampled periodically, approximately every two seconds: these are not exact allocator peaks; whole-system RAM includes other applications. Full runs overlapped some backend tests, and paging rates were not measured. Legacy CPU cutout timing is not evidence of cartoon generation.

### Visual findings

The sample shows actual cartoon conversion and differing expressions/poses. The initial prompt invented glasses and altered outfit/identity details. Removing unnecessary accessory wording improved the later sample; cartoon-specific white-background cleanup also reduced translucent hand artifacts. Likeness, clothing fidelity, correct anatomy, and successful gestures are still not guaranteed. Different image hashes prove different files, not semantic correctness.

Only the default cartoon/playful sample path has this recorded visual review. Broad personal-photo testing, all style/tone combinations, small-viewport/keyboard/canvas browser QA, live human-workflow import, and actual phone importing remain unverified.

## 7. Commands for continuing safely

Run from PowerShell:

```powershell
Set-Location "D:\Additional Project\Img_2_Sticker"
.\.venv\Scripts\python.exe -m scripts.services status
.\.venv\Scripts\python.exe -m scripts.doctor
```

The services are running at this snapshot. Open `http://127.0.0.1:8000` if the API is still running; do not start a duplicate instance. If stopped, launch:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

Create a new pack, review its three previews, and approve to generate the other nine. Existing legacy packs stay cutouts.

Focused validation after future changes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build --prefix frontend
```

Use `npm.cmd` because execution policy blocks `npm.ps1` in this environment. The TestClient deprecation is an upstream dependency warning; do not blindly change dependencies to suppress it.

Optional real GPU checks, **only when the engine is idle and no personal pack is being processed**:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_generation
.\.venv\Scripts\python.exe -m scripts.smoke_cartoon_pack
.\.venv\Scripts\python.exe -m scripts.smoke_regeneration
```

The full-pack test takes several minutes. Regeneration requires an existing successful full-pack benchmark result. Benchmark data is separated from ordinary packs, but these scripts still share the GPU/engine.

Setup/repair when needed, not as a routine restart:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -DownloadModel
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_engine.ps1
# Dependency/source repair without downloading model files:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_engine.ps1 -SkipDownloads
```

The engine setup uses pinned upstream revisions and a separate environment. A complete fresh Windows install is not yet an independently repeated acceptance result; existing-environment repair has been tested.

For a normal shutdown, use Ctrl+C in the terminal running `start.ps1`; its cleanup stops owned background services. `stop.ps1` stops owned worker/engine processes, **not an independently running foreground API**. Do not stop services while a wanted generation is active. Separately started ComfyUI instances must remain untouched.

## 8. Implementation review and improvements

### What the design gets right

- Root-cause fix: actual reference-image generation replaces repeated cutout compositing.
- Preview approval limits wasted generation; independent reactions and selected redraw offer useful user control.
- Original-reference reuse avoids accumulating drift by chaining generated images.
- Durable attempt records, explicit uncertainty, scoped cancellation, idempotent creation, and isolated service ownership are strong foundations.
- Saved art/foreground/caption layers make inexpensive edits possible without burning another GPU generation.
- Pinned runtime/models and saved benchmark artifacts make the current result reproducible enough to continue locally.

### Priority 1 — conditional recovery and privacy defects found in source

These are **source-review findings**, not newly reproduced failures. Current tests and successful GPU runs do not cover the triggering conditions. They require focused fixes/tests before calling the app fully hardened.

1. **Duplicate-artwork retry can repeat the same rejected result.** `ComfyEngine.generate` marks an attempt completed before `worker.process_cartoon` checks the artwork hash. If that check rejects a duplicate, pack retry keeps the seed and reuses the completed attempt/history output, so it can reject the same image again. The redraw endpoint is not available for failed packs. Add a regression test and deliberately invalidate/reseed only the rejected reaction, preserving other completed stickers.
2. **Removing a sticker can orphan its ComfyUI output copies.** `main.remove_sticker` deletes the sticker, cascading its attempt records, and deletes local PNGs, but does not remove the corresponding engine output files. Later pack deletion loses the attempt IDs needed for targeted cleanup. Capture the attempt IDs and clean only their owned engine outputs before losing those records; retain the shared reference and other stickers.
3. **Pack filesystem deletion is not durably guaranteed.** Main/worker cleanup commits database deletion and uses `shutil.rmtree(..., ignore_errors=True)`. Locked files, permissions, or a crash after the database commit can leave private files without a durable cleanup record. Use tombstones or a cleanup ledger, verify removal, and retry failures explicitly.

### Priority 2 — reliability, compatibility, and concurrency hardening

4. **Reconcile again before abandoning uncertain submissions.** `retry_pack` changes uncertain attempts to abandoned, and the adapter blocks an uncertain state even if a late queue/history record exists. Recheck owned queue/history before issuing another attempt; reconnect or cancel the old owned submission where appropriate. Explicit user resume authorizes new work but is not a proof of exactly-once execution. Also retain/reconcile any returned prompt ID if an alternate engine ignores the requested UUID.
5. **Make finalization and competing edits atomic.** Pack completion and job completion occur in separate worker transactions; a cancellation at the boundary deserves a regression test. API editability checks are read checks, not per-pack locks or compare-and-swap protection, so simultaneous tabs/requests can race revisions, approval, redraw, or file/database updates. Add optimistic versions or serialization and targeted cancellation/crash/concurrent-edit tests. Atomic file replacement alone does not make a database/file update atomic.
6. **Strengthen alternate-engine compatibility checks.** Doctor verifies nodes/models but not all stable-client-UUID and targeted-interrupt behavior. The pinned managed engine is demonstrated; arbitrary external versions are not. Require capabilities/version compatibility rather than introducing an unsafe global-interrupt fallback.

### Priority 3 — quality, retention, and release acceptance

- Run real browser acceptance: all seven screens, SSE reconnect/polling, preview approval, redraw, caption/mask editing, reorder/remove, export, reload/resume, narrow viewports, keyboard navigation, and mask-dialog usability. Import the human graph into ComfyUI's canvas.
- Build a consented portrait suite covering lighting, accessories, hair, skin tones, hands, transparent PNG/WebP inputs, and every supported style/tone. RGB conversion of transparent uploads deserves explicit alpha-compositing tests. Border-connected white removal can leave enclosed background holes; test and expose manual correction clearly.
- Add model repository hashes, engine/node revisions, and memory settings to exported provenance. Current export records workflow/prompt IDs/reference hashes and sticker seeds, but not the full pinned runtime manifest.
- Define conservative retention for old artwork revisions and per-export ZIPs; currently they accumulate. Preserve current assets and audit data, and do not silently delete user packs.
- Keep the deployment local. Loopback-client/Origin checks are not authentication or a Host allowlist; LAN/public hosting would need a separate security design. Managed cleanup does not automatically cover another engine's filesystem or its in-memory history.
- Add fresh-install/repair/upgrade checks on a clean Windows setup, including font availability, uv path assumptions, interruption/resume, and low-memory behavior. Do not infer portability from one configured laptop.

## 9. Recommended next implementation sequence

1. Add reproducing regression tests for duplicate-result retry, removed-sticker engine cleanup, and locked/crash-interrupted deletion; then fix those paths with scoped, durable cleanup/recovery.
2. Add late-history/uncertain-resume, cancellation-finalization, worker-kill/restart, and concurrent-edit tests. Preserve finished artwork and never affect unrelated engine jobs.
3. Run the focused tests, full backend suite, and frontend build after fixes; rerun a real pack/redraw benchmark only while the engine is idle.
4. Perform browser/canvas acceptance and a broader portrait quality review. Record observed failures separately from inferred risks.
5. Improve exported provenance and retention policy; update `Docs/Build-Status.md` with fresh evidence rather than marking unverified checks complete.

## 10. Continuation guardrails

- Do not reintroduce Telugu or hidden same-photo fallback; do not promise perfect likeness or hands.
- Keep Miniconda base unchanged; keep app and engine environments isolated.
- Preserve existing packs, references, and owned-service identity checks. Do not perform broad runtime deletion, global queue clear, or global interrupt.
- Do not restart/stop the currently running services merely to read this handoff. Check current status before any operational change.
- Treat `Docs/StickerMe-Build-Guide.md` and `Docs/update_1.md` as planning history where they conflict with the current English-only generative scope. `Docs/Build-Status.md` records previous implementation evidence; this document adds the current handoff and unresolved review findings.
- This session changed only `Docs/work.md`. It did not fix the listed follow-ups, regenerate stickers, rerun full validation, or operate services. This file supplies compact continuation context; it does not assert that the client's `/compact` command was executed by the agent.
