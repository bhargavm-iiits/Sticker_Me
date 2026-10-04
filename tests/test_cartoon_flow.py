import hashlib
import io
import json
import zipfile

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import config, db, main, worker
from backend.app.catalog import INTENTS, PREVIEW_INTENTS, artwork_prompt
from tests.test_cutout_flow import client, create_pack, fake_cutout, sample_upload


class FakeEngine:
    calls = []

    def __init__(self, database):
        pass

    def close(self):
        pass

    def generate(self, job_id, sticker_id, pack_id, intent, style, tone, seed, active, **kwargs):
        self.calls.append((sticker_id, intent, seed))
        image = Image.open(io.BytesIO(sample_upload())).convert("RGB")
        draw = ImageDraw.Draw(image)
        color = "#" + hashlib.sha256(f"{intent}{seed}".encode()).hexdigest()[:6]
        draw.rectangle((160, 290, 350, 490), fill=color)
        return image


@pytest.fixture
def cartoon_engine(monkeypatch):
    FakeEngine.calls = []
    monkeypatch.setattr(worker, "ComfyEngine", FakeEngine)
    monkeypatch.setattr(worker, "remove_background", fake_cutout)
    monkeypatch.setattr(worker, "remove_cartoon_background", fake_cutout)
    return FakeEngine


def ready_pack(client):
    pack = create_pack(client, legacy=False)
    assert worker.run_once()
    preview = client.get(f"/api/packs/{pack['id']}").json()
    assert preview["status"] == "awaiting_approval"
    assert {sticker["intent"] for sticker in preview["stickers"] if sticker["image_url"]} == PREVIEW_INTENTS
    assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409
    for sticker in preview["stickers"]:
        if sticker["image_url"]:
            assert client.post(f"/api/packs/{pack['id']}/stickers/{sticker['id']}/review").status_code == 200
    assert client.post(f"/api/packs/{pack['id']}/approve").status_code == 200
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    assert result["status"] == "ready"
    for sticker in result["stickers"]:
        assert client.post(f"/api/packs/{pack['id']}/stickers/{sticker['id']}/review").status_code == 200
    result = client.get(f"/api/packs/{pack['id']}").json()
    return result


def test_preview_approval_distinct_artwork_and_selected_regeneration(client, cartoon_engine):
    pack = ready_pack(client)
    assert len(cartoon_engine.calls) == 12
    assert len({call[1] for call in cartoon_engine.calls}) == 12
    directory = config.pack_dir(pack["id"])
    hashes = {sticker["id"]: hashlib.sha256((directory / f"{sticker['id']}.png").read_bytes()).hexdigest() for sticker in pack["stickers"]}
    first = pack["stickers"][0]
    assert client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/regenerate").status_code == 200
    assert worker.run_once()
    assert len(cartoon_engine.calls) == 13
    assert cartoon_engine.calls[-1][0] == first["id"]
    assert hashlib.sha256((directory / f"{first['id']}.png").read_bytes()).hexdigest() != hashes[first["id"]]
    for sticker in pack["stickers"][1:]:
        assert hashlib.sha256((directory / f"{sticker['id']}.png").read_bytes()).hexdigest() == hashes[sticker["id"]]
    assert client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/review").status_code == 200
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/packs/{pack['id']}/export").content)) as archive:
        assert len([name for name in archive.namelist() if name.endswith("-generated.png")]) == 12
        assert len({hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.endswith("-generated.png")}) == 12
        assert "provenance.json" in archive.namelist()
        assert not any("face.png" in name or "embedding" in name or "body.png" in name or "reference.png" in name for name in archive.namelist())


def test_caption_mask_reorder_remove_do_not_generate(client, cartoon_engine):
    pack = ready_pack(client)
    first = pack["stickers"][0]
    with Session(db.engine) as session:
        sticker = session.get(db.Sticker, first["id"])
        artwork_path = config.pack_dir(pack["id"]) / sticker.artwork_path
    original_hash = hashlib.sha256(artwork_path.read_bytes()).hexdigest()
    assert client.patch(f"/api/packs/{pack['id']}/stickers/{first['id']}", json={"caption": "New words"}).status_code == 200
    mask = fake_cutout(Image.open(io.BytesIO(sample_upload())))
    alpha = mask.getchannel("A")
    ImageDraw.Draw(alpha).rectangle((200, 100, 220, 120), fill=0)
    mask.putalpha(alpha)
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    result = client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/mask", files={"mask": ("mask.png", buffer.getvalue(), "image/png")})
    assert result.status_code == 200, result.text
    assert hashlib.sha256(artwork_path.read_bytes()).hexdigest() == original_hash
    assert len(cartoon_engine.calls) == 12
    order = [sticker["id"] for sticker in reversed(pack["stickers"])]
    reordered = client.put(f"/api/packs/{pack['id']}/order", json={"sticker_ids": order})
    assert [sticker["id"] for sticker in reordered.json()["stickers"]] == order
    animation = config.pack_dir(pack['id']) / f"{first['id']}-r1-animation-0"
    animation.mkdir()
    (animation / 'source.png').write_bytes(b'raw animation source')
    report = config.pack_dir(pack['id']) / f"{first['id']}-r1-pose-0.json"
    report.write_text('{}')
    removed = client.delete(f"/api/packs/{pack['id']}/stickers/{first['id']}")
    assert removed.status_code == 200
    assert len(removed.json()["stickers"]) == 11
    assert not animation.exists() and not report.exists()
    assert [sticker["position"] for sticker in removed.json()["stickers"]] == list(range(11))


def test_export_labels_historical_model_from_saved_attempt(client, cartoon_engine):
    from uuid import uuid4
    pack = ready_pack(client)
    with Session(db.engine) as session:
        stored = session.get(db.Pack, pack["id"])
        session.add(db.JobAttempt(id=str(uuid4()), job_id=stored.jobs[-1].id, sticker_id=pack["stickers"][0]["id"], prompt_id=str(uuid4()), state="completed", workflow=json.dumps({"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf"}}}), reference_hash="a" * 64))
        session.commit()
    response = client.get(f"/api/packs/{pack['id']}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert json.loads(archive.read("manifest.json"))["engine"] == "flux-2-klein-4b-Q4_K_M.gguf"
        provenance = json.loads(archive.read("provenance.json"))
        assert provenance[0]["stage"] == "pose" and provenance[0]["candidate"] == 0


def test_idempotency_and_english_only(client, cartoon_engine):
    kwargs = {"files": {"photo": ("portrait.png", sample_upload(), "image/png")}, "data": {"consent": "true"}, "headers": {"Idempotency-Key": "same-request"}}
    first = client.post("/api/packs", **kwargs)
    second = client.post("/api/packs", **kwargs)
    assert first.json()["id"] == second.json()["id"]
    kwargs["data"]["style"] = "chibi"
    assert client.post("/api/packs", **kwargs).status_code == 409
    kwargs["data"]["language"] = "te"
    assert client.post("/api/packs", **kwargs).status_code == 400
    with Session(db.engine) as session:
        assert len(session.scalars(select(db.Pack)).all()) == 1


def test_cancel_resume_retains_finished_preview(client, cartoon_engine, monkeypatch):
    pack = create_pack(client, legacy=False)
    original_generate = cartoon_engine.generate

    def cancel_second(self, *args, **kwargs):
        if len(self.calls) == 1:
            assert client.post(f"/api/packs/{pack['id']}/cancel").status_code == 200
        return original_generate(self, *args, **kwargs)

    monkeypatch.setattr(cartoon_engine, "generate", cancel_second)
    assert worker.run_once()
    partial = client.get(f"/api/packs/{pack['id']}").json()
    assert partial["status"] == "cancelled"
    assert len([sticker for sticker in partial["stickers"] if sticker["image_url"]]) == 1
    retained_id = next(sticker["id"] for sticker in partial["stickers"] if sticker["image_url"])
    monkeypatch.setattr(cartoon_engine, "generate", original_generate)
    assert client.post(f"/api/packs/{pack['id']}/retry").status_code == 200
    assert worker.run_once()
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "awaiting_approval"
    assert len([call for call in cartoon_engine.calls if call[0] == retained_id]) == 1


def test_engine_not_ready_has_no_photo_fallback(client, monkeypatch):
    monkeypatch.setattr(main, "engine_doctor", lambda: {"ready": False, "error": "Model missing"})
    response = client.post("/api/packs", files={"photo": ("portrait.png", sample_upload(), "image/png")}, data={"consent": "true"})
    assert response.status_code == 503
    with Session(db.engine) as session:
        assert session.scalar(select(db.Pack)) is None


def test_prompts_require_distinct_expressions_and_gestures():
    prompts = [artwork_prompt(intent, "cartoon", "playful") for intent in INTENTS]
    assert len(set(prompts)) == 12
    assert all(intent.expression in prompt and intent.gesture in prompt for intent, prompt in zip(INTENTS, prompts))
    assert all("image 1" in prompt and "Do not add or remove facial hair" in prompt for prompt in prompts)


def test_low_score_retries_different_seed_and_keeps_best(client, cartoon_engine, monkeypatch):
    monkeypatch.setattr(config, "LIKENESS_RETRIES", 1)
    scores = iter([0.2, 0.1, 0.1, 0.4, None, 0.5])
    monkeypatch.setattr(worker, "likeness", lambda reference, image: next(scores))
    pack = create_pack(client, legacy=False)
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    ready = [sticker for sticker in result["stickers"] if sticker["status"] == "ready"]
    assert [s["likeness_score"] for s in ready] == [0.2, 0.4, 0.5]
    assert len(cartoon_engine.calls) == 6
    assert cartoon_engine.calls[0][2] != cartoon_engine.calls[1][2]
    with Session(db.engine) as session:
        assert session.get(db.Sticker, ready[0]["id"]).seed == cartoon_engine.calls[0][2]
        assert session.get(db.Sticker, ready[1]["id"]).seed == cartoon_engine.calls[3][2]


def test_refinement_lower_score_is_rejected(client, cartoon_engine, monkeypatch):
    import numpy as np
    monkeypatch.setattr(config, "FACE_REFINE", True)
    monkeypatch.setattr(worker, "detect_faces", lambda image, threshold: np.array([[160, 100, 100, 120] + [0] * 11]))
    monkeypatch.setattr(worker, "align_by_landmarks", lambda refined, crop: refined)
    scores = iter([0.5, 0.1] * 3)
    monkeypatch.setattr(worker, "likeness", lambda reference, image: next(scores))
    pack = create_pack(client, legacy=False)
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    assert result["status"] == "awaiting_approval", result["error"]
    for sticker in result["stickers"]:
        if sticker["status"] != "ready": continue
        assert sticker["likeness_score"] == 0.5
        assert "original artwork retained" in sticker["likeness_note"]
        with Session(db.engine) as session:
            stored = session.get(db.Sticker, sticker["id"])
            path = config.pack_dir(pack["id"])
            assert (path / stored.artwork_path).read_bytes() == (path / stored.artwork_path.replace(".png", "-base.png")).read_bytes()
