import io
import json

import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw
from skimage.data import astronaut
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import catalog, config, db, imaging, main, worker
from backend.app.comfy import ComfyEngine
from tests.test_cutout_flow import client, fake_cutout, sample_upload


class PhotoEngine:
    calls = []

    def __init__(self, database):
        pass

    def close(self):
        pass

    def generate(self, job_id, sticker_id, pack_id, intent, style, tone, seed, active, **kwargs):
        self.calls.append({"sticker": sticker_id, "intent": intent, "stage": kwargs.get("stage"), "route": kwargs.get("route"), "candidate": kwargs.get("candidate")})
        color = "#22aa44" if kwargs.get("stage") == "pose" else "#aa2244"
        image = Image.new("RGB", (768, 768) if kwargs.get("stage") == "pose" else (512, 512), "white")
        ImageDraw.Draw(image).rectangle((100, 100, 400, 400), fill=color)
        ImageDraw.Draw(image).text((20, 20), f"{intent}{seed}", fill="black")
        return image


@pytest.fixture
def photo(client, monkeypatch):
    PhotoEngine.calls = []
    monkeypatch.setattr(config, "PHOTO_EDIT", True)
    monkeypatch.setattr(config, "PHOTO_ANIMATION", True)
    monkeypatch.setattr(main, "photo_references", lambda image: (Image.new("RGB", (768, 768), "white"), Image.new("RGB", (512, 512), "white")))
    monkeypatch.setattr(main.portrait, "available", lambda: True)
    monkeypatch.setattr(worker, "ComfyEngine", PhotoEngine)
    monkeypatch.setattr(worker, "driver_crop", lambda canvas: Image.new("RGB", (512, 512), "white"))
    animated = Image.new("RGB", (768, 768), "#4455ff")
    count = iter(range(1000))

    def animate(gesture, canvas, driver, workspace, strength):
        image = animated.copy()
        ImageDraw.Draw(image).text((300, 700), str(next(count)), fill="white")
        return image

    monkeypatch.setattr(worker, "animate_expression", animate)
    return animated


def make_pack(client, style="realistic"):
    response = client.post("/api/packs", files={"photo": ("p.png", sample_upload(), "image/png")}, data={"consent": "true", "style": style})
    assert response.status_code == 201, response.text
    return response.json()


def stored_art(pack, sticker):
    with Session(db.engine) as session:
        path = config.pack_dir(pack["id"]) / session.get(db.Sticker, sticker["id"]).artwork_path
    with Image.open(path) as image:
        return image.convert("RGB")


def test_realistic_is_default_and_photo_route_animates_real_face(client, photo, monkeypatch):
    scores = iter([0.9, 0.8] * 3)
    monkeypatch.setattr(worker, "likeness", lambda reference, image: next(scores))
    response = client.post("/api/packs", files={"photo": ("p.png", sample_upload(), "image/png")}, data={"consent": "true"})
    pack = response.json()
    assert pack["style"] == "realistic"
    assert (config.pack_dir(pack["id"]) / "canvas.png").is_file() and (config.pack_dir(pack["id"]) / "face-clean.png").is_file()
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    assert result["status"] == "awaiting_approval", result["error"]
    ready = [s for s in result["stickers"] if s["status"] == "ready"]
    assert len(ready) == 3 and all(s["likeness_score"] == 0.8 and s["likeness_note"] is None for s in ready)
    assert [(c["stage"], c["route"]) for c in PhotoEngine.calls] == [("pose", "photo"), ("face", "photo")] * 3
    assert stored_art(pack, ready[0]).getpixel((5, 5)) == photo.getpixel((5, 5))


def test_low_expression_score_keeps_original_face(client, photo, monkeypatch):
    monkeypatch.setattr(config, "LIKENESS_RETRIES", 1)
    scores = iter([0.9, 0.2, 0.3] * 3)
    monkeypatch.setattr(worker, "likeness", lambda reference, image: next(scores))
    pack = make_pack(client)
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    for sticker in [s for s in result["stickers"] if s["status"] == "ready"]:
        assert sticker["likeness_score"] == 0.9
        assert "Expression candidate failed" in sticker["likeness_note"]
        assert "generated face requires review" in sticker["likeness_note"]
        art = stored_art(pack, sticker)
        assert art.getpixel((200, 200)) == (0x22, 0xAA, 0x44)
    assert [c["candidate"] for c in PhotoEngine.calls[:3]] == [0, 0, 1]


def test_animation_failure_falls_back_to_gesture_image(client, photo, monkeypatch):
    def broken(*args):
        raise RuntimeError("runner crashed")
    monkeypatch.setattr(worker, "animate_expression", broken)
    monkeypatch.setattr(worker, "likeness", lambda reference, image: 0.9)
    pack = make_pack(client)
    assert worker.run_once()
    result = client.get(f"/api/packs/{pack['id']}").json()
    ready = [s for s in result["stickers"] if s["status"] == "ready"]
    assert len(ready) == 3 and all("Expression animation unavailable" in s["likeness_note"] for s in ready)


def test_coherent_photo_route_never_animates_or_restores_a_second_face(client, photo, monkeypatch):
    monkeypatch.setattr(config, 'PHOTO_ANIMATION', False)
    monkeypatch.setattr(worker, 'likeness', lambda reference, image: .85)
    def forbidden(*args, **kwargs):
        raise AssertionError('Coherent reactions must not overlay another face')
    monkeypatch.setattr(worker, 'animate_expression', forbidden)
    monkeypatch.setattr(worker, 'preserve_original_head', forbidden)
    monkeypatch.setattr(worker, 'driver_crop', forbidden)
    pack = make_pack(client)
    assert worker.run_once()
    state = client.get(f"/api/packs/{pack['id']}").json()
    ready = [s for s in state['stickers'] if s['status'] == 'ready']
    assert len(ready) == 3
    assert {call['stage'] for call in PhotoEngine.calls} == {'pose'}
    assert all(s['quality_report']['route'] == 'coherent-photo-edit-v4' and s['quality_report']['parameters']['animation_multiplier'] == 0 for s in ready)


def test_coherent_photo_correction_cannot_reintroduce_regional_face_overlay(client, photo, monkeypatch):
    from backend.app import corrections
    monkeypatch.setattr(config, 'PHOTO_ANIMATION', False)
    monkeypatch.setattr(worker, 'likeness', lambda reference, image: .85)
    pack = make_pack(client)
    assert worker.run_once()
    state = client.get(f"/api/packs/{pack['id']}").json()
    sticker = next(s for s in state['stickers'] if s['status'] == 'ready')
    def forbidden(*args):
        raise AssertionError('A photo correction must keep a coherent face/jaw/neck')
    monkeypatch.setattr(corrections, 'localize', forbidden)
    response = client.post(f"/api/packs/{pack['id']}/stickers/{sticker['id']}/regenerate", json={'correction':'expression','intensity':1})
    assert response.status_code == 200, response.text
    assert worker.run_once()
    corrected = client.get(f"/api/packs/{pack['id']}").json()['stickers']
    item = next(s for s in corrected if s['id'] == sticker['id'])
    assert 'coherent replacement' in item['likeness_note']


def test_coherent_photo_does_not_require_experimental_animator(client, photo, monkeypatch):
    monkeypatch.setattr(config, 'PHOTO_ANIMATION', False)
    monkeypatch.setattr(main.portrait, 'available', lambda: False)
    assert make_pack(client)['style'] == 'realistic'


def test_coherent_photo_prompt_requests_natural_expression_and_single_render():
    intent = catalog.INTENT_BY_KEY['surprise']
    prompt = catalog.photo_reaction_prompt(intent)
    assert intent.gesture in prompt and 'slightly parted rounded lips' in prompt
    assert 'one coherent photograph' in prompt and 'Natural human eye size' in prompt
    assert catalog.photo_reaction_prompt(intent, intensity=.5) != catalog.photo_reaction_prompt(intent, intensity=1.3)
    assert len({catalog.photo_reaction_prompt(intent,tone) for tone in catalog.TONES}) == 3


def test_drawn_styles_keep_drawn_route(client, photo, monkeypatch):
    monkeypatch.setattr(worker, "likeness", lambda reference, image: None)
    pack = make_pack(client, "chibi")
    assert not (config.pack_dir(pack["id"]) / "canvas.png").exists()
    assert worker.run_once()
    assert {c["route"] for c in PhotoEngine.calls} == {None}


def test_missing_face_animation_rejects_photo_styles(client, photo, monkeypatch):
    monkeypatch.setattr(main.portrait, "available", lambda: False)
    response = client.post("/api/packs", files={"photo": ("p.png", sample_upload(), "image/png")}, data={"consent": "true"})
    assert response.status_code == 503 and "LivePortrait" in response.json()["detail"]


def test_photo_prompts_are_gender_neutral_and_scoped():
    for intent in catalog.INTENTS:
        gesture, driver = catalog.gesture_edit_prompt(intent), catalog.expression_driver_prompt(intent)
        assert intent.gesture in gesture and "Change only the arms and hands" in gesture and "facial expression, hair" in gesture
        assert intent.expression in driver and "Change only the facial expression" in driver
        for prompt in (gesture, driver):
            assert not {" he ", " his ", " she ", " her "} & {f" {w} " for w in prompt.lower().replace(",", " ").replace(".", " ").split()}
    assert next(iter(catalog.STYLES)) == "realistic" and catalog.PHOTO_ROUTE == {"realistic", "likeness"}


def test_photo_route_uploads_canvas_and_clean_face(client, monkeypatch):
    monkeypatch.setattr(config, "PHOTO_ANIMATION", True)
    monkeypatch.setattr(config, "PHOTO_EDIT", False)
    pack = client.post("/api/packs", files={"photo": ("p.png", sample_upload(), "image/png")}, data={"consent": "true"}).json()
    directory = config.pack_dir(pack["id"])
    imaging.save_png(Image.new("RGB", (768, 768), "white"), directory / "canvas.png")
    imaging.save_png(Image.new("RGB", (512, 512), "white"), directory / "face-clean.png")
    with Session(db.engine) as session:
        job_id = session.get(db.Pack, pack["id"]).jobs[0].id
    sticker_id = pack["stickers"][0]["id"]
    uploads, prompts = [], []

    def handler(request):
        if request.url.path == "/upload/image":
            uploads.append(request.content)
            return httpx.Response(200, json={"name": "x.png", "subfolder": "StickerMe"})
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/prompt":
            body = json.loads(request.content)
            prompts.append(body)
            return httpx.Response(200, json={"prompt_id": body["prompt_id"]})
        if request.url.path.startswith("/history/"):
            prompt_id = request.url.path.rsplit("/", 1)[1]
            done = any(p["prompt_id"] == prompt_id for p in prompts)
            return httpx.Response(200, json={prompt_id: {"status": {"status_str": "success"}, "outputs": {"16": {"images": [{"filename": "g.png", "subfolder": "StickerMe", "type": "output"}]}}}} if done else {})
        if request.url.path == "/view":
            buffer = io.BytesIO()
            Image.new("RGB", (768, 768), "red").save(buffer, format="PNG")
            return httpx.Response(200, content=buffer.getvalue())
        raise AssertionError(request.url)

    adapter = ComfyEngine(db.engine, httpx.MockTransport(handler))
    adapter.generate(job_id, sticker_id, pack["id"], "surprise", "realistic", "playful", 7, lambda: True, route="photo")
    adapter.generate(job_id, sticker_id, pack["id"], "surprise", "realistic", "playful", 7, lambda: True, stage="face", inputs={"crop": Image.new("RGB", (512, 512))}, route="photo")
    adapter.close()
    assert f"{pack['id']}-face-clean.png".encode() in uploads[0] and f"{pack['id']}-canvas.png".encode() in uploads[1]
    assert b"-crop.png" in uploads[3]
    pose_text, face_text = (p["prompt"]["6"]["inputs"]["text"] for p in prompts)
    assert "Change only the arms and hands" in pose_text and "Change only the facial expression" in face_text
    assert prompts[0]["prompt"]["16"]["_meta"]["stickerme_route"].startswith("photo-edit")


def test_person_cutout_removes_haze_and_keeps_detached_hand(monkeypatch):
    image = Image.new("RGB", (200, 200), "white")
    alpha = np.zeros((200, 200), np.uint8)
    alpha[40:160, 60:140] = 255      # body
    alpha[10:30, 10:30] = 255        # detached raised hand
    alpha[0:200, 160:200] = 60       # grey background haze
    alpha[100:104, 100:104] = 0      # hole inside the body
    cutout = image.convert("RGBA")
    cutout.putalpha(Image.fromarray(alpha))
    monkeypatch.setattr(imaging, "remove_background", lambda source: cutout.copy())
    result = np.asarray(imaging.person_cutout(image).getchannel("A"))
    assert result[180, 180] == 0 and result[20, 20] > 200 and result[101, 101] > 200


def test_canvas_crop_and_head_paste_round_trip():
    photo = Image.fromarray(astronaut())
    face = imaging.detect_faces(photo)[0]
    canvas = imaging.aligned_canvas(photo, face)
    assert canvas.size == (768, 768)
    face_canvas = imaging.detect_faces(canvas)[0]
    assert abs(face_canvas[0] + face_canvas[2] / 2 - 384) < 40
    matrix = imaging.portrait_matrix(face_canvas)
    crop = imaging.warp_crop(canvas, matrix)
    assert crop.size == (512, 512) and len(imaging.detect_faces(crop)) == 1
    pasted = imaging.paste_head(canvas, crop, matrix, face_canvas)
    difference = np.abs(np.asarray(pasted, np.int16) - np.asarray(canvas, np.int16))
    assert difference.mean() < 2.0


def test_shading_ignores_skin_speckles():
    rng = np.random.default_rng(1)
    skin = np.full((256, 256, 3), (180, 130, 100), np.uint8)
    speckled = skin.copy()
    for y, x in rng.integers(10, 246, size=(300, 2)):
        speckled[y:y + 2, x:x + 2] = (40, 30, 25)
    rendered = np.asarray(imaging.portrait_render(Image.fromarray(speckled), "likeness"), np.int16)
    edges_darkened = (np.asarray(Image.fromarray(speckled).convert("L"), np.int16) - np.asarray(Image.fromarray(rendered.astype(np.uint8)).convert("L"), np.int16)) > 25
    assert edges_darkened.mean() < 0.01
