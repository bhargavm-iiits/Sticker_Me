import hashlib
import json
import secrets
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import timedelta

from PIL import Image
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import config
from .comfy import ComfyEngine, GenerationCancelled
from .cleanup import engine_assets
from .db import Job, JobAttempt, Pack, Sticker, engine, init_db, utcnow
from .catalog import PHOTO_ROUTE, DRAWN_STYLES, expression_strength
from . import quality
from .versions import snapshot
from .imaging import compose_sticker, person_cutout, remove_background, remove_cartoon_background, save_png
from .imaging import detect_faces, square_box, align_by_landmarks, paste_feathered_ellipse, portrait_render
from .likeness import ensure_photo_references, ensure_references, likeness
from .portrait import animate_expression, driver_crop, preserve_original_head, close_runner


def record_score(job_id, sticker_id, stage, candidate, score):
    with Session(engine) as session:
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.sticker_id == sticker_id, JobAttempt.stage == stage, JobAttempt.candidate == candidate, JobAttempt.state == "completed").order_by(JobAttempt.created_at.desc()).limit(1))
        if attempt:
            attempt.likeness_score = score
            session.commit()


def candidate_seed(seed: int, candidate: int) -> int:
    return (seed - 1 + candidate * 1_000_003) % (2**31 - 1) + 1


def better(score, best_score) -> bool:
    return score is not None and (best_score is None or score > best_score)


def save_candidate(directory, sticker_id, revision, stage, candidate, image, score, intent, style):
    report = quality.evaluate(image, score, intent, style)
    name = f"{sticker_id}-r{revision}-{stage}-{candidate}"
    save_png(image, directory / f"{name}.png")
    (directory / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def candidate_rank(report, score):
    return (report["status"] != "blocked", score if score is not None else -1)


def generate_photo(adapter, job_id, sticker_id, pack_id, intent, style, tone, seed, revision, *, intensity=1.0, correction=""):
    """Generate one photo reaction; face animation is experimental opt-in.

    Neural editing can alter detail; separate checks and explicit review remain required.
    """
    canvas_path, _ = ensure_photo_references(pack_id)
    directory = config.pack_dir(pack_id)
    reference = np.load(directory / "face-embedding.npy", allow_pickle=False)
    with Image.open(canvas_path) as source:
        canvas = source.convert("RGB")

    def engine(stage, candidate, inputs=None):
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        inputs = {**(inputs or {}), "correction": correction, "intensity": intensity}
        image = adapter.generate(job_id, sticker_id, pack_id, intent, style, tone, candidate_seed(seed, candidate), lambda: active(job_id), stage=stage, candidate=candidate, inputs=inputs, route="photo")
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        return image

    gesture, gesture_score, chosen_seed = None, None, seed
    gesture_rank = (False, -2)
    for candidate in range(config.LIKENESS_RETRIES + 1):
        image = engine("pose", candidate)
        score = likeness(reference, image)
        record_score(job_id, sticker_id, "pose", candidate, score)
        report = save_candidate(directory, sticker_id, revision, "pose", candidate, image, score, intent, style)
        if gesture is None or candidate_rank(report, score) > gesture_rank:
            gesture, gesture_score, chosen_seed = image, score, candidate_seed(seed, candidate)
            gesture_rank = candidate_rank(report, score)
        if report["status"] != "blocked" and score is not None and score >= config.GESTURE_FLOOR:
            break
    save_png(gesture, directory / f"{sticker_id}-art-{revision}-base.png")

    if not config.PHOTO_ANIMATION:
        # The reaction and jaw/neck are already rendered together. Never overlay
        # a second face, including the neutral-face restoration fallback.
        if style == 'likeness':
            gesture = portrait_render(gesture, style)
            gesture_score = likeness(reference, gesture)
        note = None if gesture_score is not None and gesture_score >= config.LIKENESS_FLOOR else 'Face similarity unavailable or low; inspect this coherent photo edit.'
        return gesture, gesture_score, chosen_seed, note

    image, score, note = gesture, gesture_score, None
    animated, animated_score = None, None
    animated_rank = (False, -2)
    crop = driver_crop(canvas)
    for candidate in range(config.LIKENESS_RETRIES + 1):
        driver = engine("face", candidate, {"crop": crop})
        try:
            result = animate_expression(gesture, canvas, driver, directory / f"{sticker_id}-r{revision}-animation-{candidate}", expression_strength(tone, intensity) * config.EXPRESSION_STRENGTH)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            if animated is None:
                note = f"Expression animation unavailable ({exc}); inspect the fallback face and pose."
            break
        if result is None:
            note = "Face alignment was unsafe after the gesture edit; inspect the fallback face and pose."
            break
        result_score = likeness(reference, result)
        save_png(driver, directory / f"{sticker_id}-r{revision}-driver-{candidate}.png")
        report = save_candidate(directory, sticker_id, revision, "expression", candidate, result, result_score, intent, style)
        record_score(job_id, sticker_id, "face", candidate, result_score)
        if animated is None or candidate_rank(report, result_score) > animated_rank:
            animated, animated_score = result, result_score
            animated_rank = candidate_rank(report, result_score)
        if report["status"] != "blocked" and result_score is not None and result_score >= config.EXPRESSION_FLOOR:
            break
    if animated is not None:
        if animated_score is not None and animated_score >= config.EXPRESSION_MIN and animated_rank[0]:
            image, score = animated, animated_score
        else:
            note = "Expression candidate failed similarity or anatomy screening; inspect the fallback face and pose."
    if image is gesture:
        try:
            restored = preserve_original_head(gesture, canvas)
        except (OSError, ValueError, RuntimeError):
            restored = None
        if restored is not None:
            image, score = restored, likeness(reference, restored)
            note = (note or "No expression candidate accepted.") + " Original-photo face restored inside the generated head outline; the requested expression still needs review."
        else:
            note = (note or "No expression candidate accepted.") + " Original face could not be safely restored; generated face requires review."
    if style == "likeness":
        image = portrait_render(image, style)
        score = likeness(reference, image)
    if score is None:
        note = note or "Face comparison unavailable for this artwork; review manually."
    elif score < config.LIKENESS_FLOOR:
        note = note or "Low face similarity after retries; review the face and redraw if needed."
    return image, score, chosen_seed, note


def generate_likeness(adapter, job_id, sticker_id, pack_id, intent, style, tone, seed, revision):
    with Session(engine) as session:
        pack = session.get(Pack, pack_id)
        stored = session.get(Sticker, sticker_id)
        options = json.loads(session.get(Job, job_id).payload)
        intensity = stored.expression_intensity
        design_path = pack.design_path
    correction = options.get("correction", "")
    if config.PHOTO_EDIT and style in PHOTO_ROUTE:
        return generate_photo(adapter, job_id, sticker_id, pack_id, intent, style, tone, seed, revision, intensity=intensity, correction=correction)
    ensure_references(pack_id)
    directory = config.pack_dir(pack_id)
    reference = np.load(directory / "face-embedding.npy", allow_pickle=False)
    preserve_geometry = config.PORTRAIT_RENDER and style == "likeness"
    generation_style = "realistic" if preserve_geometry else style
    best_image, best_score, best_seed = None, None, seed
    best_rank = (False, -2)
    inputs = {"correction": correction + f" Expression intensity: {intensity:.2f}; keep the requested reaction clear."}
    if design_path:
        with Image.open(directory / design_path) as design:
            inputs["design"] = design.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS)
    for candidate in range(config.LIKENESS_RETRIES + 1):
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        candidate_seed = (seed - 1 + candidate * 1_000_003) % (2**31 - 1) + 1
        image = adapter.generate(job_id, sticker_id, pack_id, intent, generation_style, tone, candidate_seed, lambda: active(job_id), stage="pose", candidate=candidate, inputs=inputs, render_style=style if preserve_geometry else None)
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        if preserve_geometry:
            image = portrait_render(image, style)
        score = likeness(reference, image)
        record_score(job_id, sticker_id, "pose", candidate, score)
        report = save_candidate(directory, sticker_id, revision, "pose", candidate, image, score, intent, style)
        if best_image is None or candidate_rank(report, score) > best_rank:
            best_image, best_score, best_seed = image, score, candidate_seed
            best_rank = candidate_rank(report, score)
        if report["status"] != "blocked" and score is not None and score >= config.LIKENESS_FLOOR:
            break
    save_png(best_image, directory / f"{sticker_id}-art-{revision}-base.png")
    note = None
    if config.FACE_REFINE:
        faces = detect_faces(best_image, 0.5)
        if len(faces) == 1:
            box = square_box(faces[0], 1.6, best_image.size)
            crop = best_image.crop(box).resize((512, 512), Image.Resampling.LANCZOS)
            if not active(job_id):
                raise GenerationCancelled("Generation cancelled")
            refinement_inputs = {"crop": crop}
            if design_path:
                with Image.open(directory / design_path) as design:
                    design = design.convert("RGB")
                    design_faces = detect_faces(design, .5)
                    if len(design_faces) == 1:
                        design = design.crop(square_box(design_faces[0], 1.6, design.size))
                    refinement_inputs["design"] = design.resize((512, 512), Image.Resampling.LANCZOS)
            refined = adapter.generate(job_id, sticker_id, pack_id, intent, generation_style, tone, best_seed, lambda: active(job_id), stage="face", candidate=0, inputs=refinement_inputs, render_style=style if preserve_geometry else None)
            if not active(job_id):
                raise GenerationCancelled("Generation cancelled")
            if preserve_geometry:
                refined = portrait_render(refined, style)
            aligned = align_by_landmarks(refined, crop)
            if aligned is not None:
                merged = paste_feathered_ellipse(best_image, aligned, box)
                merged_score = likeness(reference, merged)
                record_score(job_id, sticker_id, "face", 0, merged_score)
                if merged_score is not None and (best_score is None or merged_score >= best_score):
                    best_image, best_score = merged, merged_score
                else:
                    note = "Face refinement did not improve the score; original artwork retained."
            else:
                note = "Face refinement could not be aligned; original artwork retained."
        else:
            note = "A single face was not detected in artwork; review manually."
    if best_score is None:
        note = "Face comparison unavailable for this artwork; review manually."
    elif best_score < config.LIKENESS_FLOOR:
        note = "Low face similarity after retries; review the face and redraw if needed."
    return best_image, best_score, best_seed, note


def claim_job() -> str | None:
    now = utcnow()
    with Session(engine) as session:
        session.execute(update(Job).where(Job.state == "running", Job.lease_until < now).values(state="queued", error="Reconnecting after worker restart", lease_until=None))
        candidate = session.scalar(select(Job.id).where(Job.state == "queued").order_by(Job.created_at).limit(1))
        if candidate is None:
            session.commit()
            return None
        claimed = session.execute(update(Job).where(Job.id == candidate, Job.state == "queued").values(state="running", attempts=Job.attempts + 1, lease_until=now + timedelta(seconds=60), error=None))
        session.commit()
        return candidate if claimed.rowcount == 1 else None


def check_active(session: Session, job_id: str) -> Pack | None:
    job = session.get(Job, job_id)
    if job is None or job.state != "running" or job.cancel_requested:
        return None
    pack = session.get(Pack, job.pack_id)
    return pack if pack is not None and pack.status != "deleting" else None


def active(job_id: str) -> bool:
    with Session(engine) as session:
        return check_active(session, job_id) is not None


@contextmanager
def heartbeat(job_id: str):
    stopped = threading.Event()

    def renew():
        while not stopped.wait(5):
            with Session(engine) as session:
                session.execute(update(Job).where(Job.id == job_id, Job.state == "running").values(lease_until=utcnow() + timedelta(seconds=60)))
                session.commit()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=6)


def process_cutout(job_id: str):
    with Session(engine) as session:
        pack = check_active(session, job_id)
        directory, language = config.pack_dir(pack.id), pack.language
        stickers = [(sticker.id, sticker.caption) for sticker in pack.stickers]
    cutout_path = directory / "cutout.png"
    if not cutout_path.exists():
        with Image.open(directory / "reference.png") as source:
            cutout = remove_background(source.convert("RGB"))
        if not active(job_id):
            raise GenerationCancelled("Processing cancelled")
        save_png(cutout, cutout_path)
    with Image.open(cutout_path) as source:
        cutout = source.convert("RGBA")
    for position, (sticker_id, caption) in enumerate(stickers):
        if not active(job_id):
            raise GenerationCancelled("Processing cancelled")
        save_png(compose_sticker(cutout, caption, language), directory / f"{sticker_id}.png")
        with Session(engine) as session:
            sticker = session.get(Sticker, sticker_id)
            sticker.status, sticker.cutout_path = "ready", "cutout.png"
            session.get(Job, job_id).progress = position + 1
            session.commit()


def process_cartoon(job_id: str):
    adapter = ComfyEngine(engine)
    try:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            pack = session.get(Pack, job.pack_id)
            target_ids = json.loads(job.payload)["sticker_ids"]
            kind = job.kind
        if kind == "design":
            process_design(adapter, job_id, pack.id, target_ids[0])
            return
        completed = 0
        for sticker_id in target_ids:
            with Session(engine) as session:
                pack = check_active(session, job_id)
                if pack is None:
                    raise GenerationCancelled("Generation cancelled")
                sticker = session.get(Sticker, sticker_id)
                if sticker is None:
                    continue
                if sticker.status == "ready":
                    completed += 1
                    session.get(Job, job_id).progress = completed
                    session.commit()
                    continue
                sticker.status = "generating"
                if not sticker.seed:
                    sticker.seed = secrets.randbelow(2**31 - 1) + 1
                pack_id, intent, style, tone, seed, revision = pack.id, sticker.intent, pack.style, pack.tone, sticker.seed, sticker.revision + 1
                session.commit()
            began = time.monotonic()
            image, score, chosen_seed, note = generate_likeness(adapter, job_id, sticker_id, pack_id, intent, style, tone, seed, revision)
            with Session(engine) as session:
                options = json.loads(session.get(Job, job_id).payload)
                previous_art = session.get(Sticker, sticker_id).artwork_path
            if kind == "regenerate" and previous_art and options.get("correction_kind") in {"face", "hands", "expression"}:
                if config.PHOTO_EDIT and style in PHOTO_ROUTE and not config.PHOTO_ANIMATION:
                    regional_note = 'Generated one coherent replacement reaction to avoid face and hand blending seams; compare the previous version.'
                else:
                    from .corrections import localize
                    with Image.open(config.pack_dir(pack_id) / previous_art) as previous:
                        image, regional_note = localize(previous, image, options["correction_kind"])
                if regional_note:
                    note = " ".join(filter(None, [note, regional_note]))
                reference = np.load(config.pack_dir(pack_id) / "face-embedding.npy", allow_pickle=False)
                score = likeness(reference, image)
            if not active(job_id):
                raise GenerationCancelled("Generation cancelled")
            directory = config.pack_dir(pack_id)
            artwork_name = f"{sticker_id}-art-{revision}.png"
            cutout_name = f"{sticker_id}-cutout-{revision}.png"
            save_png(image, directory / artwork_name)
            digest = hashlib.sha256((directory / artwork_name).read_bytes()).hexdigest()
            with Session(engine) as session:
                others = session.scalars(select(Sticker).where(Sticker.pack_id == pack_id, Sticker.id != sticker_id, Sticker.artwork_path.is_not(None))).all()
                if any(hashlib.sha256((directory / other.artwork_path).read_bytes()).hexdigest() == digest for other in others):
                    session.execute(update(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.sticker_id == sticker_id).values(state="abandoned"))
                    session.get(Sticker, sticker_id).seed = (seed + 1_000_003) % (2**31 - 1) + 1
                    session.commit()
                    raise RuntimeError("The engine returned duplicate artwork. Regenerate this reaction.")
            # White photographic clothing can connect to the white background;
            # flood-fill cleanup is suitable for outlined drawings, not photos.
            photographic = style == "realistic" or ((config.PORTRAIT_RENDER or config.PHOTO_EDIT) and style == "likeness")
            cutout = person_cutout(image) if photographic else remove_cartoon_background(image)
            if not active(job_id):
                raise GenerationCancelled("Generation cancelled")
            save_png(cutout, directory / cutout_name)
            with Session(engine) as session:
                sticker = session.get(Sticker, sticker_id)
                if check_active(session, job_id) is None or sticker is None:
                    raise GenerationCancelled("Generation cancelled")
                snapshot(session, sticker)
                save_png(compose_sticker(cutout, sticker.caption, "en"), directory / f"{sticker_id}.png")
                report = quality.evaluate(image, score, intent, style, note)
                report["checks"]["mask"] = quality.mask_report(cutout)
                for other in session.scalars(select(Sticker).where(Sticker.pack_id == pack_id, Sticker.id != sticker_id, Sticker.artwork_path.is_not(None))):
                    with Image.open(directory / other.artwork_path) as prior:
                        if quality.near_duplicate(image, prior):
                            report["checks"]["variety"] = {"state": "review", "note": "This artwork resembles another reaction. Check that their expressions are distinct."}
                            break
                report["seconds"] = round(time.monotonic() - began, 2)
                report["route"] = ("original-photo-face-v3" if config.PHOTO_ANIMATION else "coherent-photo-edit-v4") if config.PHOTO_EDIT and style in PHOTO_ROUTE else "approved-cartoon-v2" if style in DRAWN_STYLES else "draw-v2"
                report["parameters"] = {"style": style, "tone": tone, "intent": intent,
                                        "seed": chosen_seed, "intensity": sticker.expression_intensity,
                                        "animation_multiplier": expression_strength(tone, sticker.expression_intensity) * config.EXPRESSION_STRENGTH if config.PHOTO_ANIMATION and style in PHOTO_ROUTE else 0,
                                        "renderer": "straight-alpha-border-v3", "mask_cleanup": "straight-alpha-v3",
                                        "mask_method": "u2netp" if photographic else "border-white-or-u2netp"}
                sticker.artwork_path, sticker.cutout_path = artwork_name, cutout_name
                sticker.status, sticker.revision = "ready", revision
                sticker.seed, sticker.likeness_score, sticker.likeness_note = chosen_seed, score, note
                sticker.quality_status, sticker.quality_report = report["status"], json.dumps(report)
                snapshot(session, sticker)
                completed += 1
                session.get(Job, job_id).progress = completed
                session.commit()
        with Session(engine) as session:
            pack = check_active(session, job_id)
            if pack:
                pack.status = "awaiting_approval" if kind == "preview" or not pack.approved else "ready"
                session.commit()
    finally:
        close_runner()
        adapter.close()


def process_design(adapter, job_id, pack_id, sticker_id):
    directory = config.pack_dir(pack_id)
    with Session(engine) as session:
        pack = session.get(Pack, pack_id)
        style, tone = pack.style, pack.tone
        options = json.loads(session.get(Job, job_id).payload)
    seeds = options["seeds"]
    reference = np.load(directory / "face-embedding.npy", allow_pickle=False)
    designs = []
    for candidate, seed in enumerate(seeds):
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        image = adapter.generate(job_id, sticker_id, pack_id, "greeting", style, tone, seed,
                                 lambda: active(job_id), stage="design", candidate=candidate)
        if not active(job_id):
            raise GenerationCancelled("Generation cancelled")
        score = likeness(reference, image)
        report = quality.evaluate(image, score, "character design", style)
        name = f"design-{candidate}.png"
        save_png(image, directory / f"design-{candidate}-{job_id}.png")
        save_png(image, directory / name)
        designs.append({"candidate": candidate, "file": name, "seed": seed, "score": score, "quality": report})
        (directory / "designs.json").write_text(json.dumps(designs, indent=2), encoding="utf-8")
        with Session(engine) as session:
            session.get(Job, job_id).progress = candidate + 1
            session.commit()
    with Session(engine) as session:
        pack = check_active(session, job_id)
        if pack:
            pack.status = "awaiting_design"
            session.commit()


def process_job(job_id: str) -> None:
    try:
        with Session(engine) as session:
            pack = check_active(session, job_id)
            if pack is None:
                raise GenerationCancelled("Job cancelled")
            pack.status, pack.error = "processing", None
            mode = pack.mode
            session.commit()
        with heartbeat(job_id):
            if mode == "cartoon":
                process_cartoon(job_id)
            else:
                process_cutout(job_id)
        with Session(engine) as session:
            pack = check_active(session, job_id)
            if pack:
                if mode != "cartoon":
                    pack.status = "ready"
                job = session.get(Job, job_id)
                job.state, job.lease_until = "done", None
                session.commit()
    except Exception as exc:
        if isinstance(exc, GenerationCancelled):
            try:
                cancel_attempts(job_id)
            except Exception as cancellation_error:
                exc = RuntimeError(f"Cancellation could not be confirmed: {cancellation_error}")
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job:
                cancelled = isinstance(exc, GenerationCancelled) or job.cancel_requested
                job.state, job.error, job.lease_until = "cancelled" if cancelled else "failed", str(exc), None
                pack = session.get(Pack, job.pack_id)
                if pack and pack.status != "deleting":
                    pack.status, pack.error = "cancelled" if cancelled else "failed", str(exc)
                session.commit()
    finally:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            pack = session.get(Pack, job.pack_id) if job else None
            if pack and pack.status == "deleting":
                directory = config.pack_dir(pack.id)
                attempts = session.scalars(select(JobAttempt.id).join(Job, JobAttempt.job_id == Job.id).where(Job.pack_id == pack.id)).all()
                try:
                    for owned_job in pack.jobs:
                        cancel_attempts(owned_job.id)
                except Exception as exc:
                    job.state, job.error, job.lease_until = "queued", f"Waiting for safe engine cleanup: {exc}", None
                    session.commit()
                    time.sleep(1)
                    return
                engine_assets(pack.id, list(attempts))
                session.delete(pack)
                session.commit()
                shutil.rmtree(directory, ignore_errors=True)


def cancel_attempts(job_id: str):
    with Session(engine) as session:
        attempts = session.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.state.in_(["submitting", "submitted", "uncertain"]))).all()
        targets = [(attempt.id, attempt.prompt_id) for attempt in attempts]
    if not targets:
        return
    adapter = ComfyEngine(engine)
    try:
        for attempt_id, prompt_id in targets:
            adapter.cancel(prompt_id, attempt_id)
            adapter.set_attempt(attempt_id, "cancelled")
    finally:
        adapter.close()


def run_once() -> bool:
    job_id = claim_job()
    if job_id is None:
        return False
    process_job(job_id)
    return True


def main() -> None:
    import msvcrt

    init_db()
    config.ensure_directories()
    with (config.DATA_DIR / "worker.lock").open("a+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit("A StickerMe worker is already running")
        print("StickerMe cartoon worker ready", flush=True)
        try:
            while True:
                if not run_once():
                    time.sleep(1)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    main()
