import io
import json
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import db, worker
from backend.app.comfy import ComfyEngine, SubmissionUncertain
from tests.test_cutout_flow import client, create_pack


def context(client):
    pack = create_pack(client, legacy=False)
    with Session(db.engine) as session:
        stored = session.get(db.Pack, pack["id"])
        job_id = stored.jobs[0].id
    return pack["id"], job_id, pack["stickers"][0]["id"]


def output_history(prompt_id):
    return {prompt_id: {"status": {"status_str": "success"}, "outputs": {"16": {"images": [{"filename": "generated.png", "subfolder": "StickerMe", "type": "output"}]}}}}


def test_attempt_persisted_before_submission_and_history_reconnect(client):
    pack_id, job_id, sticker_id = context(client)
    submitted = []
    uploads = []

    def handler(request):
        if request.url.path == "/upload/image":
            uploads.append(request.content)
            return httpx.Response(200, json={"name": "reference.png", "subfolder": "StickerMe"})
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/prompt":
            body = json.loads(request.content)
            with Session(db.engine) as session:
                attempt = session.scalar(select(db.JobAttempt).where(db.JobAttempt.prompt_id == body["prompt_id"]))
                assert attempt and attempt.state == "submitting"
                assert attempt.reference_hash
                assert body["extra_data"]["stickerme_attempt"] == attempt.id
            submitted.append(body["prompt_id"])
            return httpx.Response(200, json={"prompt_id": body["prompt_id"]})
        if request.url.path.startswith("/history/"):
            prompt_id = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(200, json=output_history(prompt_id) if prompt_id in submitted else {})
        if request.url.path == "/view":
            buffer = io.BytesIO()
            Image.new("RGB", (512, 512), "red").save(buffer, format="PNG")
            return httpx.Response(200, content=buffer.getvalue())
        raise AssertionError(request.url)

    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    first = adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 123, lambda: True)
    second = adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 123, lambda: True)
    assert first.tobytes() == second.tobytes()
    assert len(submitted) == 1
    assert len(uploads) == 2
    assert f"{pack_id}-face.png".encode() in uploads[0]
    assert f"{pack_id}-body.png".encode() in uploads[1]
    adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 456, lambda: True, candidate=1)
    adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 456, lambda: True, stage="face", inputs={"crop": first, "design": first})
    assert len(submitted) == 3
    with Session(db.engine) as session:
        attempts = session.scalars(select(db.JobAttempt)).all()
        assert {(a.stage, a.candidate) for a in attempts} == {("pose", 0), ("pose", 1), ("face", 0)}
        assert len({a.prompt_id for a in attempts}) == 3
        face_attempt = next(a for a in attempts if a.stage == "face")
        face_graph = json.loads(face_attempt.workflow)
        assert face_graph['22']['inputs']['conditioning'] == ['19', 0]
        assert face_graph['13']['inputs']['positive'] == ['22', 0]
        assert face_graph['8']['inputs']['conditioning'] == ['22', 0]
        assert face_graph['16']['_meta']['stickerme_models']
        assert 'Image 2 remains the original identity reference' in face_graph['6']['inputs']['text']
    adapter.close()


def test_lost_submission_record_requires_explicit_resume(client):
    pack_id, job_id, sticker_id = context(client)
    prompt_id = str(uuid4())
    with Session(db.engine) as session:
        session.add(db.JobAttempt(id=str(uuid4()), job_id=job_id, sticker_id=sticker_id, prompt_id=prompt_id, workflow="{}", reference_hash="f" * 64, state="submitted"))
        session.get(db.Job, job_id).state = "failed"
        session.get(db.Pack, pack_id).status = "failed"
        session.commit()

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"queue_running": [], "queue_pending": []} if request.url.path == "/queue" else {})

    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    with pytest.raises(SubmissionUncertain):
        adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 123, lambda: True)
    with Session(db.engine) as session:
        assert session.scalar(select(db.JobAttempt)).state == "uncertain"
    assert client.post(f"/api/packs/{pack_id}/retry").status_code == 200
    with Session(db.engine) as session:
        assert session.scalar(select(db.JobAttempt)).state == "abandoned"
    adapter.close()


def test_refinement_upload_failure_retains_crop_cleanup_ownership(client):
    pack_id, job_id, sticker_id = context(client)
    def handler(request):
        assert request.url.path == "/upload/image"
        with Session(db.engine) as session:
            attempt = session.scalar(select(db.JobAttempt))
            assert attempt.stage == "face" and attempt.state == "prepared"
            assert f"{attempt.id}-crop.png".encode() in request.content
        return httpx.Response(500, text="Upload interrupted")
    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        adapter.generate(job_id, sticker_id, pack_id, "greeting", "likeness", "warm", 123, lambda: True, stage="face", inputs={"crop": Image.new("RGB", (512, 512))})
    with Session(db.engine) as session:
        attempt = session.scalar(select(db.JobAttempt))
        assert attempt.stage == "face" and attempt.state == "failed"
    adapter.close()


def test_submission_server_error_is_uncertain_not_silently_duplicated(client):
    pack_id, job_id, sticker_id = context(client)
    submitted = []

    def handler(request):
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "reference.png", "subfolder": "StickerMe"})
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/prompt":
            submitted.append(json.loads(request.content)["prompt_id"])
            return httpx.Response(500, text="Uncertain submission outcome")
        return httpx.Response(200, json={})

    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    for repeat in range(2):
        with pytest.raises(SubmissionUncertain):
            adapter.generate(job_id, sticker_id, pack_id, "greeting", "cartoon", "playful", 123, lambda: True)
    assert len(submitted) == 1
    with Session(db.engine) as session:
        assert session.scalar(select(db.JobAttempt)).state == "uncertain"
    adapter.close()


def test_cancel_never_interrupts_another_apps_prompt(client):
    context(client)
    prompt_id, attempt_id = str(uuid4()), str(uuid4())
    posts = []
    owner = {"stickerme_attempt": "another-app"}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"queue_running": [] if len(posts) == 2 else [[0, prompt_id, {}, owner]], "queue_pending": []})
        posts.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    adapter.cancel(prompt_id, attempt_id)
    assert posts == []
    owner["stickerme_attempt"] = attempt_id
    adapter.cancel(prompt_id, attempt_id)
    assert posts == [("/queue", {"delete": [prompt_id]}), ("/interrupt", {"prompt_id": prompt_id})]
    adapter.close()


def test_stale_job_lease_can_be_reclaimed(client):
    from datetime import timedelta

    pack_id, job_id, sticker_id = context(client)
    with Session(db.engine) as session:
        job = session.get(db.Job, job_id)
        job.state, job.lease_until = "running", db.utcnow() - timedelta(seconds=1)
        session.commit()
    assert worker.claim_job() == job_id
    assert worker.claim_job() is None


def test_deletion_reconciles_an_unfinished_owned_engine_attempt(client, monkeypatch):
    pack_id, job_id, sticker_id = context(client)
    prompt_id, attempt_id = str(uuid4()), str(uuid4())
    with Session(db.engine) as session:
        session.add(db.JobAttempt(id=attempt_id, job_id=job_id, sticker_id=sticker_id, prompt_id=prompt_id, workflow="{}", reference_hash="f" * 64, state="submitted"))
        session.get(db.Job, job_id).state = "failed"
        session.get(db.Pack, pack_id).status = "failed"
        session.commit()
    cancelled = []

    class CleanupEngine:
        def __init__(self, database):
            pass

        def cancel(self, target_prompt, target_attempt):
            cancelled.append((target_prompt, target_attempt))

        def set_attempt(self, target_attempt, state):
            with Session(db.engine) as session:
                session.get(db.JobAttempt, target_attempt).state = state
                session.commit()

        def close(self):
            pass

    monkeypatch.setattr(worker, "ComfyEngine", CleanupEngine)
    response = client.delete(f"/api/packs/{pack_id}")
    assert response.json()["status"] == "deleting"
    assert worker.run_once()
    assert cancelled == [(prompt_id, attempt_id)]
    assert client.get(f"/api/packs/{pack_id}").status_code == 404
