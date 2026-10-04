import hashlib
import io
import json
import zipfile

import pytest
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.app import config, db, main, worker
from backend.app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    packs = runtime / "packs"
    packs.mkdir(parents=True)
    monkeypatch.setattr(config, "PACKS_DIR", packs)
    test_engine = create_engine(f"sqlite:///{(runtime / 'test.sqlite3').as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(test_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(main, "engine_doctor", lambda: {"ready": True, "error": None})
    # Lifecycle tests use synthetic artwork; real detection has separate tests.
    monkeypatch.setattr(main, "face_reference", lambda image: image.resize((512, 512)))
    monkeypatch.setattr(main, "body_reference", lambda image: image.copy())
    monkeypatch.setattr(main, "embedding", lambda image: np.ones((1, 128), np.float32))
    monkeypatch.setattr(config, "FACE_REFINE", False)
    monkeypatch.setattr(config, "LIKENESS_RETRIES", 0)
    monkeypatch.setattr(config, "PORTRAIT_RENDER", True)
    # These lifecycle tests cover the drawn route; tests/test_photo_route.py covers photo editing.
    monkeypatch.setattr(config, "PHOTO_EDIT", False)
    monkeypatch.setattr(worker, "person_cutout", fake_cutout)
    monkeypatch.setattr(worker, "likeness", lambda reference, image: None)
    with TestClient(app) as test_client:
        yield test_client
    test_engine.dispose()


def sample_upload():
    image = Image.new("RGB", (512, 512), "#f0f0f0")
    draw = ImageDraw.Draw(image)
    draw.ellipse((130, 60, 380, 320), fill="#c17a5f")
    draw.rectangle((155, 280, 355, 500), fill="#515db6")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def fake_cutout(image):
    result = image.convert("RGBA")
    alpha = Image.new("L", result.size, 0)
    draw = ImageDraw.Draw(alpha)
    draw.ellipse((130, 60, 380, 320), fill=255)
    draw.rectangle((155, 280, 355, 500), fill=255)
    result.putalpha(alpha)
    return result


def create_pack(client, legacy=True):
    response = client.post(
        "/api/packs",
        files={"photo": ("portrait.png", sample_upload(), "image/png")},
        data={"name": "Test pack", "language": "en", "consent": "true"},
    )
    assert response.status_code == 201, response.text
    pack = response.json()
    if legacy:
        with Session(db.engine) as session:
            stored = session.get(db.Pack, pack["id"])
            stored.mode, stored.approved = "photo_cutout", True
            stored.jobs[0].kind, stored.jobs[0].total, stored.jobs[0].payload = "cutout_pack", 12, "{}"
            session.commit()
    return pack


def test_cutout_caption_edit_and_export(client, monkeypatch):
    monkeypatch.setattr(worker, "remove_background", fake_cutout)
    pack = create_pack(client)
    assert worker.run_once()
    current = client.get(f"/api/packs/{pack['id']}").json()
    assert current["status"] == "ready"
    assert len(current["stickers"]) == 12
    cutout_path = config.pack_dir(pack["id"]) / "cutout.png"
    original_hash = hashlib.sha256(cutout_path.read_bytes()).hexdigest()
    first = current["stickers"][0]
    response = client.patch(
        f"/api/packs/{pack['id']}/stickers/{first['id']}", json={"caption": "My own words"}
    )
    assert response.status_code == 200, response.text
    assert hashlib.sha256(cutout_path.read_bytes()).hexdigest() == original_hash
    with Image.open(io.BytesIO(client.get(first["image_url"]).content)) as image:
        assert image.size == (512, 512)
        assert image.getchannel("A").getextrema() == (0, 255)

    response = client.get(f"/api/packs/{pack['id']}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len([name for name in names if name.startswith("whatsapp/") and name.endswith(".webp")]) == 12
        assert len([name for name in names if name.startswith("telegram/")]) == 12
        assert "whatsapp/tray-icon.png" in names
        assert "artwork/text-free-cutout.png" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["stickers"][0]["caption"] == "My own words"
        assert all(item["emoji"] for item in manifest["stickers"])
        assert all(len(archive.read(name)) <= 100 * 1024 for name in names if name.startswith("whatsapp/") and name.endswith(".webp"))


def test_failed_pack_can_retry(client, monkeypatch):
    pack = create_pack(client)

    def fail_once(image):
        raise RuntimeError("Segmentation unavailable")

    monkeypatch.setattr(worker, "remove_background", fail_once)
    assert worker.run_once()
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "failed"
    assert client.post(f"/api/packs/{pack['id']}/retry").status_code == 200
    monkeypatch.setattr(worker, "remove_background", fake_cutout)
    assert worker.run_once()
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "ready"


def test_delete_during_processing_does_not_restore_pack(client, monkeypatch):
    pack = create_pack(client)

    def delete_during_cutout(image):
        response = client.delete(f"/api/packs/{pack['id']}")
        assert response.status_code == 202
        assert response.json()["status"] == "deleting"
        return fake_cutout(image)

    monkeypatch.setattr(worker, "remove_background", delete_during_cutout)
    assert worker.run_once()
    assert client.get(f"/api/packs/{pack['id']}").status_code == 404
    assert not config.pack_dir(pack["id"]).exists()


def test_upload_requires_permission_and_valid_image(client):
    no_permission = client.post(
        "/api/packs",
        files={"photo": ("portrait.png", sample_upload(), "image/png")},
        data={"consent": "false"},
    )
    assert no_permission.status_code == 400
    bad_image = client.post(
        "/api/packs",
        files={"photo": ("portrait.png", b"not an image", "image/png")},
        data={"consent": "true"},
    )
    assert bad_image.status_code == 400
