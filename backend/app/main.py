import asyncio
import hashlib
import io
import json
import secrets
import shutil
import zipfile
from contextlib import asynccontextmanager
from uuid import uuid4

import psutil
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, features
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .catalog import INTENTS, PHOTO_ROUTE, DRAWN_STYLES, PREVIEW_INTENTS, STYLES, TONES
from .comfy import engine_doctor
from .cleanup import engine_assets, engine_attempt_assets
from . import config
from .config import ROOT, U2NET_HOME, pack_dir
from . import db
from .db import Job, JobAttempt, Pack, Sticker, StickerVersion, get_session, init_db
from .versions import snapshot, FIELDS
from .quality import PALM_FILE
from .imaging import MAX_UPLOAD_BYTES, compose_sticker, encode_webp, font_path, normalize_upload, save_png
from .imaging import face_reference, body_reference
from .likeness import embedding, photo_references, save_embedding
from . import portrait


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    yield


app = FastAPI(title="StickerMe", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        return JSONResponse({"detail": "Local access only"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in {
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }:
        return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def serialize_pack(pack: Pack) -> dict:
    designs = []
    design_manifest = pack_dir(pack.id) / "designs.json"
    if design_manifest.is_file():
        try:
            designs = json.loads(design_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "id": pack.id,
        "name": pack.name,
        "language": pack.language,
        "mode": pack.mode,
        "style": pack.style,
        "tone": pack.tone,
        "approved": pack.approved,
        "status": pack.status,
        "error": pack.error,
        "design_url": f"/api/packs/{pack.id}/design/{pack.design_path.removeprefix('design-').removesuffix('.png')}" if pack.design_path else None,
        "designs": [{**item, "image_url": f"/api/packs/{pack.id}/design/{item['candidate']}"} for item in designs],
        "face_url": f"/api/packs/{pack.id}/face.png" if (pack_dir(pack.id) / "face.png").is_file() else None,
        "created_at": pack.created_at.isoformat(),
        "stickers": [
            {
                "id": sticker.id,
                "position": sticker.position,
                "intent": sticker.intent,
                "emoji": sticker.emoji,
                "caption": sticker.caption,
                "status": sticker.status,
                "revision": sticker.revision,
                "likeness_score": sticker.likeness_score,
                "likeness_note": sticker.likeness_note,
                "quality_status": sticker.quality_status,
                "quality_report": json.loads(sticker.quality_report or "{}"),
                "expression_intensity": sticker.expression_intensity,
                "image_url": f"/api/packs/{pack.id}/stickers/{sticker.id}.png?v={sticker.revision}" if (pack_dir(pack.id) / f"{sticker.id}.png").is_file() else None,
            }
            for sticker in pack.stickers
        ],
    }


def get_pack_or_404(session: Session, pack_id: str) -> Pack:
    pack = session.get(Pack, pack_id)
    if pack is None or pack.status == "deleting":
        raise HTTPException(404, "Pack not found")
    return pack


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "cartoon", "languages": ["en"]}


@app.get("/api/doctor")
def doctor() -> dict:
    try:
        english_font = str(font_path("en"))
    except RuntimeError:
        english_font = None
    return {
        "mode": "cartoon",
        "memory_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "raqm": features.check_feature("raqm"),
        "webp": features.check_module("webp"),
        "english_font": english_font,
        "rembg_model_present": (U2NET_HOME / "models" / "u2netp" / "u2netp.onnx").exists(),
        "comfyui": engine_doctor(),
        "face_animation": portrait.available(),
        "photo_animation_enabled": config.PHOTO_ANIMATION,
        "photo_styles": sorted(PHOTO_ROUTE) if config.PHOTO_EDIT else [],
        "hand_detector": (config.FACE_MODELS_DIR / PALM_FILE).is_file(),
        "styles": list(STYLES),
        "tones": list(TONES),
    }


@app.post("/api/packs", status_code=201)
async def create_pack(
    photo: UploadFile = File(...),
    name: str = Form("My stickers"),
    language: str = Form("en"),
    style: str = Form("realistic"),
    tone: str = Form("playful"),
    consent: bool = Form(False),
    idempotency_key: str | None = Header(None),
    session: Session = Depends(get_session),
) -> dict:
    if not consent:
        raise HTTPException(400, "Confirm that you have permission to use this photo")
    if language != "en":
        raise HTTPException(400, "Only English captions are supported")
    if style not in STYLES or tone not in TONES:
        raise HTTPException(400, "Choose a supported cartoon style and tone")
    if idempotency_key and (len(idempotency_key) > 64 or not idempotency_key.isascii()):
        raise HTTPException(400, "Idempotency key must be at most 64 ASCII characters")
    name = name.strip()[:80] or "My stickers"
    data = await photo.read(MAX_UPLOAD_BYTES + 1)
    try:
        image = normalize_upload(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    request_hash = hashlib.sha256(data + json.dumps([name, language, style, tone]).encode()).hexdigest()
    if idempotency_key:
        existing = session.scalar(select(Pack).where(Pack.request_key == idempotency_key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "This request key was already used for another photo or settings")
            return serialize_pack(existing)
    try:
        face = face_reference(image)
        feature = embedding(image)
        if feature is None:
            raise ValueError("No clear face found. Use a closer, well-lit photo.")
        body = body_reference(image)
        photo_edit = config.PHOTO_EDIT and style in PHOTO_ROUTE
        canvas, face_clean = photo_references(image) if photo_edit else (None, None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    diagnostics = engine_doctor()
    if not diagnostics["ready"]:
        raise HTTPException(503, f"Cartoon engine is not ready: {diagnostics['error']}. Run setup_engine.ps1 and start.ps1.")
    if photo_edit and config.PHOTO_ANIMATION and not portrait.available():
        raise HTTPException(503, "Face animation (LivePortrait) is not installed. Run setup.ps1 -DownloadModel.")
    pack_id = str(uuid4())
    directory = pack_dir(pack_id)
    save_png(image, directory / "reference.png")
    save_png(face, directory / "face.png")
    save_png(body, directory / "body.png")
    save_embedding(feature, directory / "face-embedding.npy")
    if photo_edit:
        save_png(canvas, directory / "canvas.png")
        save_png(face_clean, directory / "face-clean.png")
    pack = Pack(id=pack_id, name=name, language="en", mode="cartoon", style=style, tone=tone, request_key=idempotency_key, request_hash=request_hash)
    for position, intent in enumerate(INTENTS):
        pack.stickers.append(
            Sticker(id=str(uuid4()), position=position, intent=intent.key, emoji=intent.emoji, caption=intent.english)
        )
    targets = [sticker.id for sticker in pack.stickers if sticker.intent in PREVIEW_INTENTS]
    if style in DRAWN_STYLES:
        pack.jobs.append(Job(id=str(uuid4()), kind="design", total=2, payload=json.dumps({"sticker_ids": targets, "seeds": [secrets.randbelow(2**31 - 1) + 1 for _ in range(2)]})))
    else:
        pack.jobs.append(Job(id=str(uuid4()), kind="preview", total=len(targets), payload=json.dumps({"sticker_ids": targets})))
    session.add(pack)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        shutil.rmtree(directory, ignore_errors=True)
        existing = session.scalar(select(Pack).where(Pack.request_key == idempotency_key)) if idempotency_key else None
        if existing and existing.request_hash == request_hash:
            return serialize_pack(existing)
        raise HTTPException(409, "A conflicting pack request already exists")
    session.refresh(pack)
    return serialize_pack(pack)


@app.get("/api/packs")
def list_packs(session: Session = Depends(get_session)) -> list[dict]:
    packs = session.scalars(select(Pack).where(Pack.status != "deleting").order_by(Pack.created_at.desc())).all()
    return [serialize_pack(pack) for pack in packs]


@app.get("/api/packs/{pack_id}")
def get_pack(pack_id: str, session: Session = Depends(get_session)) -> dict:
    return serialize_pack(get_pack_or_404(session, pack_id))


@app.get("/api/packs/{pack_id}/job")
def get_job(pack_id: str, session: Session = Depends(get_session)) -> dict:
    pack = get_pack_or_404(session, pack_id)
    job = latest_job(pack)
    return serialize_job(job)


def latest_job(pack: Pack) -> Job:
    return max(pack.jobs, key=lambda job: job.created_at)


def serialize_job(job: Job) -> dict:
    from sqlalchemy.orm import object_session
    session = object_session(job)
    attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id).order_by(JobAttempt.created_at.desc()).limit(1)) if session else None
    phase = "Preparing references"
    if job.kind == "design":
        phase = "Creating character designs"
    elif attempt:
        phase = {"pose": "Generating gesture and artwork", "face": "Preparing facial expression"}.get(attempt.stage, phase)
    times = [json.loads(s.quality_report or "{}").get("seconds") for s in job.pack.stickers]
    times = [t for t in times if isinstance(t, (float, int)) and t > 0]
    estimate = round(sum(times) / len(times) * max(0, job.total - job.progress)) if times and job.kind != "design" else None
    return {"id": job.id, "kind": job.kind, "state": job.state, "progress": job.progress, "total": job.total, "error": job.error, "phase": phase, "estimated_remaining_seconds": estimate}


def editable(pack: Pack):
    if any(job.state in {"queued", "running"} for job in pack.jobs):
        raise HTTPException(409, "Wait for generation to finish, or cancel and wait for it to stop")


def owned_sticker(session: Session, pack_id: str, sticker_id: str) -> Sticker:
    sticker = session.get(Sticker, sticker_id)
    if sticker is None or sticker.pack_id != pack_id:
        raise HTTPException(404, "Sticker not found")
    return sticker


@app.get("/api/packs/{pack_id}/events")
async def pack_events(pack_id: str, request: Request, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)

    async def events():
        previous = None
        while not await request.is_disconnected():
            with Session(db.engine) as current:
                pack = current.get(Pack, pack_id)
                if pack is None or pack.status == "deleting":
                    yield 'event: gone\ndata: {}\n\n'
                    break
                body = json.dumps({"pack": serialize_pack(pack), "job": serialize_job(latest_job(pack))})
                terminal = pack.status not in {"queued", "processing"}
            if body != previous:
                yield f"event: snapshot\ndata: {body}\n\n"
                previous = body
            else:
                yield ": heartbeat\n\n"
            if terminal:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/packs/{pack_id}/approve")
def approve_pack(pack_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if pack.mode != "cartoon" or pack.status != "awaiting_approval":
        raise HTTPException(409, "Approve the three cartoon previews first")
    previews = [s for s in pack.stickers if s.intent in PREVIEW_INTENTS]
    if any(s.status != "ready" or s.quality_status not in {"accepted", "legacy"} for s in previews):
        raise HTTPException(409, "Review the face, expression and hands of each preview before approving")
    targets = [sticker.id for sticker in pack.stickers if sticker.status != "ready"]
    pack.approved, pack.status = True, "queued" if targets else "ready"
    if targets:
        pack.jobs.append(Job(id=str(uuid4()), kind="pack", total=len(targets), payload=json.dumps({"sticker_ids": targets})))
    session.commit()
    return serialize_pack(pack)


class Regeneration(BaseModel):
    correction: Literal["redraw", "face", "hands", "expression"] = "redraw"
    intensity: float = Field(1.0, ge=.25, le=1.3)


@app.post("/api/packs/{pack_id}/stickers/{sticker_id}/regenerate")
def regenerate_sticker(pack_id: str, sticker_id: str, update: Regeneration | None = None, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    if pack.mode != "cartoon" or not sticker.artwork_path or pack.status not in {"ready", "awaiting_approval"}:
        raise HTTPException(409, "Regeneration is available for generated cartoon reactions")
    snapshot(session, sticker)
    update = update or Regeneration(intensity=sticker.expression_intensity)
    corrections = {
        "redraw": "",
        "face": "Prioritize the original photo's face shape, facial hair, eyes, nose and hairline. Do not replace the person with a generic avatar.",
        "hands": "Correct the requested hand gesture: exactly two arms, at most two hands, plausible fingers. Keep hands clear of the face, all inside the frame.",
        "expression": "Make the requested facial emotion unmistakable while retaining the original person's facial features.",
    }
    sticker.expression_intensity = update.intensity
    sticker.status, sticker.seed = "pending", secrets.randbelow(2**31 - 1) + 1
    pack.status, pack.error = "queued", None
    pack.jobs.append(Job(id=str(uuid4()), kind="regenerate", total=1, payload=json.dumps({"sticker_ids": [sticker_id], "correction": corrections[update.correction], "correction_kind": update.correction})))
    session.commit()
    return serialize_pack(pack)


@app.get("/api/packs/{pack_id}/design/{candidate}")
def design_image(pack_id: str, candidate: int, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)
    path = pack_dir(pack_id) / f"design-{candidate}.png"
    if candidate not in {0, 1} or not path.is_file():
        raise HTTPException(404, "Character design not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


class DesignSelection(BaseModel):
    candidate: Literal[0, 1]


@app.post("/api/packs/{pack_id}/design")
def select_design(pack_id: str, selection: DesignSelection, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if pack.status != "awaiting_design":
        raise HTTPException(409, "Wait for the character designs to finish")
    designs = json.loads((pack_dir(pack_id) / "designs.json").read_text(encoding="utf-8"))
    chosen = next((d for d in designs if d["candidate"] == selection.candidate), None)
    if chosen is None or chosen["quality"]["status"] == "blocked":
        raise HTTPException(409, "Choose a design without a detected anatomy or duplicate-face failure")
    pack.design_path, pack.status = chosen["file"], "queued"
    targets = [s.id for s in pack.stickers if s.intent in PREVIEW_INTENTS]
    pack.jobs.append(Job(id=str(uuid4()), kind="preview", total=len(targets), payload=json.dumps({"sticker_ids": targets})))
    session.commit()
    return serialize_pack(pack)


@app.post("/api/packs/{pack_id}/design/retry")
def retry_design(pack_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if pack.status != "awaiting_design":
        raise HTTPException(409, "Design retry is available after reviewing the character designs")
    targets = [s.id for s in pack.stickers if s.intent in PREVIEW_INTENTS]
    pack.status = "queued"
    pack.jobs.append(Job(id=str(uuid4()), kind="design", total=2, payload=json.dumps({"sticker_ids": targets, "seeds": [secrets.randbelow(2**31 - 1) + 1 for _ in range(2)]})))
    session.commit()
    return serialize_pack(pack)


class StickerReviewDecision(BaseModel):
    override_detected: bool = False
    revision: int | None = Field(None, ge=0)


@app.post("/api/packs/{pack_id}/stickers/{sticker_id}/review")
def accept_sticker(pack_id: str, sticker_id: str, decision: StickerReviewDecision | None = None, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    decision = decision or StickerReviewDecision()
    if sticker.status != "ready":
        raise HTTPException(409, "Wait for this sticker to finish generating before reviewing it")
    if decision.revision is not None and decision.revision != sticker.revision:
        raise HTTPException(409, "This sticker changed. Refresh and review the current version")
    flagged = sticker.quality_status == "blocked"
    if flagged and not decision.override_detected:
        raise HTTPException(409, "An automatic check flagged this image. Inspect it, then explicitly accept it anyway or generate a correction")
    if flagged and decision.revision is None:
        raise HTTPException(409, "Review the current sticker revision before overriding the automatic check")
    report = json.loads(sticker.quality_report or "{}")
    report["reviewed"] = True
    # Keep detector findings intact; human acceptance is a separate decision.
    report["review"] = {"decision": "accepted", "revision": sticker.revision,
                        "overrode_automated_check": flagged}
    sticker.quality_status = "accepted"
    sticker.quality_report = json.dumps(report)
    session.commit()
    return serialize_pack(pack)


@app.get("/api/packs/{pack_id}/stickers/{sticker_id}/versions")
def sticker_versions(pack_id: str, sticker_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    snapshot(session, sticker)
    session.commit()
    versions = session.scalars(select(StickerVersion).where(StickerVersion.sticker_id == sticker.id).order_by(StickerVersion.revision.desc())).all()
    return [{"id": v.id, "revision": v.revision, "created_at": v.created_at.isoformat(),
             "image_url": f"/api/packs/{pack_id}/stickers/{sticker_id}/versions/{v.id}.png", **json.loads(v.snapshot)} for v in versions]


def owned_version(session, sticker_id, version_id):
    version = session.get(StickerVersion, version_id)
    if version is None or version.sticker_id != sticker_id:
        raise HTTPException(404, "Sticker version not found")
    return version


@app.get("/api/packs/{pack_id}/stickers/{sticker_id}/versions/{version_id}.png")
def version_image(pack_id: str, sticker_id: str, version_id: str, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)
    owned_sticker(session, pack_id, sticker_id)
    version = owned_version(session, sticker_id, version_id)
    return FileResponse(pack_dir(pack_id) / version.image_path, media_type="image/png")


@app.post("/api/packs/{pack_id}/stickers/{sticker_id}/versions/{version_id}/restore")
def restore_version(pack_id: str, sticker_id: str, version_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    version = owned_version(session, sticker_id, version_id)
    snapshot(session, sticker)
    values = json.loads(version.snapshot)
    for field in FIELDS:
        setattr(sticker, field, values[field])
    with Image.open(pack_dir(pack_id) / version.image_path) as saved:
        save_png(saved.copy(), pack_dir(pack_id) / f"{sticker.id}.png")
    sticker.revision += 1
    sticker.status = "ready"
    snapshot(session, sticker)
    session.commit()
    return serialize_pack(pack)


class CaptionUpdate(BaseModel):
    caption: str


@app.patch("/api/packs/{pack_id}/stickers/{sticker_id}")
def update_caption(pack_id: str, sticker_id: str, update: CaptionUpdate, session: Session = Depends(get_session)) -> dict:
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    if not sticker.cutout_path:
        raise HTTPException(409, "This sticker has not been generated yet")
    snapshot(session, sticker)
    cutout_path = pack_dir(pack_id) / sticker.cutout_path
    with Image.open(cutout_path) as source:
        try:
            image = compose_sticker(source.convert("RGBA"), update.caption, pack.language)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
    save_png(image, pack_dir(pack_id) / f"{sticker_id}.png")
    sticker.caption = update.caption.strip()
    sticker.revision += 1
    snapshot(session, sticker)
    session.commit()
    return serialize_pack(pack)


@app.get("/api/packs/{pack_id}/stickers/{sticker_id}.png")
def get_sticker_image(pack_id: str, sticker_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    sticker = session.get(Sticker, sticker_id)
    if sticker is None or sticker.pack_id != pack.id:
        raise HTTPException(404, "Sticker image not found")
    path = pack_dir(pack_id) / f"{sticker_id}.png"
    if not path.is_file():
        raise HTTPException(404, "Sticker image not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/packs/{pack_id}/stickers/{sticker_id}/download")
def download_sticker_png(pack_id: str, sticker_id: str, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)
    sticker = owned_sticker(session, pack_id, sticker_id)
    path = pack_dir(pack_id) / f"{sticker.id}.png"
    if not path.is_file():
        raise HTTPException(409, "This sticker has not been generated yet")
    return FileResponse(path, media_type="image/png", filename=f"{sticker.position + 1:02d}-{sticker.intent}.png")


@app.get("/api/packs/{pack_id}/face.png")
def get_face_image(pack_id: str, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)
    path = pack_dir(pack_id) / "face.png"
    if not path.is_file():
        raise HTTPException(404, "Face reference not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/packs/{pack_id}/stickers/{sticker_id}/layer/{layer}")
def sticker_layer(pack_id: str, sticker_id: str, layer: str, session: Session = Depends(get_session)):
    get_pack_or_404(session, pack_id)
    sticker = owned_sticker(session, pack_id, sticker_id)
    filename = {"artwork": sticker.artwork_path, "cutout": sticker.cutout_path}.get(layer)
    if not filename or not (pack_dir(pack_id) / filename).is_file():
        raise HTTPException(404, "Layer not found")
    return FileResponse(pack_dir(pack_id) / filename, media_type="image/png")


@app.post("/api/packs/{pack_id}/stickers/{sticker_id}/mask")
async def update_mask(pack_id: str, sticker_id: str, mask: UploadFile = File(...), session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    sticker = owned_sticker(session, pack_id, sticker_id)
    if not sticker.artwork_path:
        raise HTTPException(409, "Mask editing requires generated artwork")
    snapshot(session, sticker)
    data = await mask.read(MAX_UPLOAD_BYTES + 1)
    directory = pack_dir(pack_id)
    try:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("Mask exceeds 12 MB")
        with Image.open(directory / sticker.artwork_path) as source:
            original = source.convert("RGBA")
        with Image.open(io.BytesIO(data)) as uploaded:
            if uploaded.format != "PNG" or uploaded.mode != "RGBA" or uploaded.size != original.size:
                raise ValueError("Mask must be an RGBA PNG matching the original artwork dimensions")
            alpha = uploaded.getchannel("A")
            if alpha.getbbox() is None or alpha.getextrema() == (255, 255):
                raise ValueError("Mask must have foreground and transparency")
            original.putalpha(alpha)
        composed = compose_sticker(original, sticker.caption, "en")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, str(exc)) from exc
    sticker.revision += 1
    sticker.cutout_path = f"{sticker_id}-mask-{sticker.revision}.png"
    save_png(original, directory / sticker.cutout_path)
    save_png(composed, directory / f"{sticker_id}.png")
    if sticker.quality_status != "blocked":
        sticker.quality_status = "needs_review"
    snapshot(session, sticker)
    session.commit()
    return serialize_pack(pack)


class StickerOrder(BaseModel):
    sticker_ids: list[str]


@app.put("/api/packs/{pack_id}/order")
def reorder_pack(pack_id: str, order: StickerOrder, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if len(order.sticker_ids) != len(pack.stickers) or set(order.sticker_ids) != {sticker.id for sticker in pack.stickers}:
        raise HTTPException(400, "Provide every sticker ID exactly once")
    lookup = {sticker.id: sticker for sticker in pack.stickers}
    for position, sticker_id in enumerate(order.sticker_ids):
        lookup[sticker_id].position = position
    session.commit()
    session.expire(pack, ["stickers"])
    return serialize_pack(pack)


@app.delete("/api/packs/{pack_id}/stickers/{sticker_id}")
def remove_sticker(pack_id: str, sticker_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if not pack.approved or pack.status != "ready" or len(pack.stickers) <= 3:
        raise HTTPException(409, "Keep at least three stickers; finish preview approval first")
    sticker = owned_sticker(session, pack_id, sticker_id)
    attempt_ids = list(session.scalars(select(JobAttempt.id).where(JobAttempt.sticker_id == sticker.id)))
    session.delete(sticker)
    session.commit()
    engine_attempt_assets(attempt_ids)
    session.expire(pack, ["stickers"])
    for position, remaining in enumerate(pack.stickers):
        remaining.position = position
    session.commit()
    directory = pack_dir(pack_id).resolve()
    for path in directory.glob(f"{sticker_id}*"):
        # Include new candidate reports and nested raw-animation artifacts.
        if not path.resolve().is_relative_to(directory):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return serialize_pack(pack)


@app.post("/api/packs/{pack_id}/cancel")
def cancel_pack(pack_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    job = latest_job(pack)
    if job.state not in {"queued", "running"}:
        raise HTTPException(409, "No active generation")
    job.cancel_requested = True
    unresolved = session.scalar(select(JobAttempt.id).where(JobAttempt.job_id == job.id, JobAttempt.state.in_(["submitting", "submitted", "uncertain"])))
    if job.state == "queued" and not unresolved:
        job.state, pack.status = "cancelled", "cancelled"
    session.commit()
    return serialize_pack(pack)


@app.post("/api/packs/{pack_id}/retry")
def retry_pack(pack_id: str, session: Session = Depends(get_session)) -> dict:
    pack = get_pack_or_404(session, pack_id)
    editable(pack)
    if pack.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled packs can be resumed")
    job = latest_job(pack)
    uncertain = session.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.state == "uncertain")).all()
    for attempt in uncertain:
        attempt.state = "abandoned"
    job.cancel_requested = False
    job.state = "queued"
    job.error = None
    pack.status = "queued"
    pack.error = None
    session.commit()
    return serialize_pack(pack)


@app.delete("/api/packs/{pack_id}", status_code=202)
def delete_pack(pack_id: str, session: Session = Depends(get_session)) -> dict:
    pack = get_pack_or_404(session, pack_id)
    running = any(job.state == "running" for job in pack.jobs)
    unresolved = session.scalar(select(JobAttempt.id).join(Job, JobAttempt.job_id == Job.id).where(Job.pack_id == pack.id, JobAttempt.state.in_(["submitting", "submitted", "uncertain"])))
    if running or unresolved:
        pack.status = "deleting"
        for job in pack.jobs:
            job.cancel_requested = True
        if not running:
            latest_job(pack).state = "queued"
        session.commit()
        return {"status": "deleting"}
    directory = pack_dir(pack.id)
    attempts = session.scalars(select(JobAttempt.id).join(Job, JobAttempt.job_id == Job.id).where(Job.pack_id == pack.id)).all()
    engine_assets(pack.id, list(attempts))
    session.delete(pack)
    session.commit()
    shutil.rmtree(directory, ignore_errors=True)
    return {"status": "deleted"}


@app.get("/api/packs/{pack_id}/export")
def export_pack(pack_id: str, session: Session = Depends(get_session)):
    pack = get_pack_or_404(session, pack_id)
    if pack.status != "ready":
        raise HTTPException(409, "Pack is not ready")
    if pack.mode == "cartoon" and any(s.quality_status not in {"accepted", "legacy"} for s in pack.stickers):
        raise HTTPException(409, "Review and accept every sticker's face, expression and hands before exporting")
    if len(pack.stickers) < 3 or len(pack.stickers) > 30:
        raise HTTPException(409, "Pack needs 3 to 30 stickers")
    directory = pack_dir(pack_id)
    destination = directory / f"export-{uuid4()}.zip"
    temporary = destination.with_suffix(".zip.tmp")
    from .config import WORKFLOW_PATH
    model_name = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))["1"]["inputs"]["unet_name"]
    attempts = session.scalars(select(JobAttempt).join(Sticker, JobAttempt.sticker_id == Sticker.id).where(Sticker.pack_id == pack.id, JobAttempt.state == "completed")).all()
    used_models = sorted({node["inputs"]["unet_name"] for attempt in attempts for node in json.loads(attempt.workflow).values() if "unet_name" in node.get("inputs", {})})
    if used_models:
        model_name = ", ".join(used_models)
    manifest = {"name": pack.name, "mode": pack.mode, "language": pack.language, "style": pack.style, "tone": pack.tone, "engine": model_name if pack.mode == "cartoon" else "legacy cutout", "stickers": []}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if pack.mode != "cartoon":
                archive.write(directory / "cutout.png", "artwork/text-free-cutout.png")
            for sticker in pack.stickers:
                with Image.open(directory / f"{sticker.id}.png") as source:
                    image = source.convert("RGBA")
                if image.size != (512, 512) or image.getchannel("A").getextrema() == (255, 255):
                    raise ValueError(f"Sticker {sticker.position + 1} has invalid dimensions or transparency")
                whats_app = encode_webp(image, 100 * 1024)
                telegram_buffer = io.BytesIO()
                image.save(telegram_buffer, format="PNG", optimize=True)
                telegram = telegram_buffer.getvalue()
                telegram_extension = "png"
                if len(telegram) > 512 * 1024:
                    telegram = encode_webp(image, 512 * 1024)
                    telegram_extension = "webp"
                stem = f"{sticker.position + 1:02d}"
                if pack.mode == "cartoon":
                    archive.write(directory / sticker.artwork_path, f"artwork/{stem}-generated.png")
                    archive.write(directory / sticker.cutout_path, f"artwork/{stem}-text-free.png")
                archive.writestr(f"whatsapp/{stem}.webp", whats_app)
                archive.writestr(f"telegram/{stem}.{telegram_extension}", telegram)
                manifest["stickers"].append({"number": sticker.position + 1, "intent": sticker.intent, "emoji": sticker.emoji, "caption": sticker.caption, "seed": sticker.seed, "revision": sticker.revision, "quality_status": sticker.quality_status, "quality": json.loads(sticker.quality_report or "{}"), "expression_intensity": sticker.expression_intensity})
                if sticker.position == 0:
                    tray = image.resize((96, 96), Image.Resampling.LANCZOS)
                    tray_buffer = io.BytesIO()
                    tray.save(tray_buffer, format="PNG", optimize=True)
                    if tray_buffer.tell() > 50 * 1024:
                        raise ValueError("Tray icon exceeds 50 KB")
                    archive.writestr("whatsapp/tray-icon.png", tray_buffer.getvalue())
                    archive.writestr("cover.png", telegram_buffer.getvalue())
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("provenance.json", json.dumps([{"sticker_id": attempt.sticker_id, "prompt_id": attempt.prompt_id, "stage": attempt.stage, "candidate": attempt.candidate, "likeness_score": attempt.likeness_score, "reference_hash": attempt.reference_hash, "workflow": json.loads(attempt.workflow)} for attempt in attempts], indent=2))
            archive.writestr("IMPORT.txt", "StickerMe export. Transfer this ZIP to your phone. WhatsApp requires a compatible sticker app; Telegram stickers can be uploaded through @stickers. Downloading this ZIP does not install a pack automatically.\n")
        temporary.replace(destination)
    except (OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(destination, media_type="application/zip", filename=f"stickerme-{pack_id}.zip")


@app.get("/api/packs/{pack_id}/export/png")
def download_pack_pngs(pack_id: str, session: Session = Depends(get_session)):
    """Download saved PNGs independently of generation/review/platform approval."""
    pack = get_pack_or_404(session, pack_id)
    directory = pack_dir(pack_id)
    generated = [(sticker, directory / f"{sticker.id}.png") for sticker in pack.stickers
                 if (directory / f"{sticker.id}.png").is_file()]
    if not generated:
        raise HTTPException(409, "No generated stickers are available to download yet")
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for sticker, path in generated:
                archive.writestr(f"{sticker.position + 1:02d}-{sticker.intent}.png", path.read_bytes())
    except OSError as exc:
        raise HTTPException(409, "A saved sticker changed during download; refresh and try again") from exc
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="stickerme-{pack_id}-png.zip"',
        "Cache-Control": "no-store",
    })


dist_dir = ROOT / "frontend" / "dist"
if dist_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    index = dist_dir / "index.html"
    if index.is_file() and not path.startswith("api/"):
        return FileResponse(index)
    raise HTTPException(404, "Not found")
