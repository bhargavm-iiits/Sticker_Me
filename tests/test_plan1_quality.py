import io
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw
from skimage.data import astronaut
from sqlalchemy.orm import Session

from backend.app import catalog, config, db, imaging, portrait, quality, worker
from tests.test_cutout_flow import client, create_pack, sample_upload
from tests.test_cartoon_flow import cartoon_engine, ready_pack


def test_tone_changes_submitted_instructions_and_animation_strength():
    intent = catalog.INTENT_BY_KEY["laughter"]
    assert len({catalog.gesture_edit_prompt(intent, t) for t in catalog.TONES}) == 3
    assert len({catalog.expression_driver_prompt(intent, t) for t in catalog.TONES}) == 3
    assert catalog.expression_strength("warm") < catalog.expression_strength("playful") < catalog.expression_strength("dramatic")
    assert catalog.expression_strength("dramatic", 1.3) <= 1.3


def test_extra_hand_blocks_even_a_high_identity_score(monkeypatch):
    monkeypatch.setattr(quality, "detect_faces", lambda *args: np.array([[20, 20, 80, 100] + [0] * 11]))
    monkeypatch.setattr(quality, "hand_regions", lambda image: [([0, 0, 10, 10], .9)] * 3)
    report = quality.evaluate(Image.new("RGB", (256, 256)), .99, "laughter", "realistic")
    assert report["status"] == "blocked"
    assert report["checks"]["identity"]["state"] == "screened"
    assert report["checks"]["anatomy"]["detected_hands"] == 3


def test_missing_checks_require_review_instead_of_silent_acceptance(monkeypatch):
    monkeypatch.setattr(quality, "detect_faces", lambda *args: np.empty((0, 15)))
    monkeypatch.setattr(quality, "hand_regions", lambda image: None)
    report = quality.evaluate(Image.new("RGB", (256, 256)), None, "surprise", "cartoon")
    assert report["status"] == "needs_review"
    assert report["checks"]["identity"]["state"] == report["checks"]["anatomy"]["state"] == "unavailable"


def test_soft_hair_alpha_and_large_finger_gaps_survive_cleanup(monkeypatch):
    cutout = Image.new("RGBA", (200, 200), "red")
    alpha = np.zeros((200, 200), np.uint8)
    alpha[20:180, 30:170] = 255
    alpha[18:20, 30:170] = 90
    alpha[70:100, 70:110] = 0  # intentional enclosed hand gap
    alpha[130:133, 90:93] = 0  # accidental small defect
    cutout.putalpha(Image.fromarray(alpha))
    monkeypatch.setattr(imaging, "remove_background", lambda image: cutout.copy())
    cleaned = np.asarray(imaging.person_cutout(cutout).getchannel("A"))
    assert cleaned[18, 80] == 90
    assert cleaned[80, 80] == 0
    assert cleaned[131, 91] == 255


def test_background_removal_preserves_straight_rgb_on_soft_white_edges(monkeypatch):
    import rembg
    image = Image.new('RGB', (80, 80), '#f8f8f8')
    alpha = Image.new('L', image.size, 0)
    ImageDraw.Draw(alpha).rectangle((15, 15, 65, 65), fill=128)
    ImageDraw.Draw(alpha).rectangle((20, 20, 60, 60), fill=255)
    def segment(source, *, session, only_mask):
        assert only_mask is True
        return alpha
    monkeypatch.setattr(rembg, 'remove', segment)
    monkeypatch.setattr(imaging, 'background_session', lambda model: object())
    cutout = imaging.remove_background(image)
    assert cutout.getpixel((16, 30)) == (248, 248, 248, 128)
    assert np.array_equal(np.asarray(cutout)[:, :, :3], np.asarray(image))


def test_soft_white_border_does_not_turn_grey_on_checkerboard():
    cutout = Image.new('RGBA', (200, 200), (255, 255, 255, 0))
    alpha = Image.new('L', cutout.size, 0)
    ImageDraw.Draw(alpha).ellipse((10, 10, 190, 190), fill=255)
    alpha = alpha.filter(imaging.ImageFilter.GaussianBlur(2))
    cutout.putalpha(alpha)
    sticker = imaging.compose_sticker(cutout, '', 'en')
    pixels = np.asarray(sticker)
    visible = pixels[:, :, 3] > 0
    assert np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255))
    assert pixels[:, :, :3][visible].min() == 255
    for color in ('white', '#d9c5ef', '#141414'):
        background = Image.new('RGBA', sticker.size, color)
        composed = np.asarray(Image.alpha_composite(background, sticker))
        expected = np.asarray(background)[:, :, :3].astype(np.int16)
        assert np.all(composed[:, :, :3].astype(np.int16) >= expected)


def test_caption_is_attached_to_figure_and_captionless_keeps_large_subject():
    cutout = Image.new("RGBA", (500, 500))
    ImageDraw.Draw(cutout).rectangle((100, 20, 400, 490), fill="#dd5500")
    result = np.asarray(imaging.compose_sticker(cutout, "Hi!", "en"))
    rows = (result[:, :, 3] > 128).any(axis=1)
    occupied = np.flatnonzero(rows)
    gaps = np.diff(occupied)
    assert gaps.max() <= 20
    plain = imaging.compose_sticker(cutout, "", "en")
    bbox = plain.getchannel("A").getbbox()
    assert bbox[3] - bbox[1] > 450
    assert bbox[0] > 0 and bbox[3] < 512


def test_animation_uses_original_photo_not_generated_face(tmp_path, monkeypatch):
    source = Image.fromarray(astronaut())
    face = imaging.detect_faces(source)[0]
    gesture = Image.new("RGB", source.size, "red")
    monkeypatch.setattr(portrait, "single_face", lambda *args: face)
    expected = imaging.warp_crop(source, imaging.portrait_matrix(face))
    seen = []

    def runner(jobs, workspace):
        with Image.open(jobs[0]["source"]) as image:
            seen.append(image.convert("RGB"))
        return [expected.resize((256, 256))]  # actual LivePortrait decoder size

    monkeypatch.setattr(portrait, "run", runner)
    monkeypatch.setattr(portrait, "remove_background", lambda image: image.convert("RGBA"))
    monkeypatch.setattr(quality, "hand_regions", lambda image: [])
    monkeypatch.setattr(portrait, 'align_face_patch', lambda target, patch, matrix, mask: (patch, mask))
    pasted_sizes = []
    paste = portrait.paste_head
    def record_paste(target, patch, *args, **kwargs):
        pasted_sizes.append(patch.size)
        return paste(target, patch, *args, **kwargs)
    monkeypatch.setattr(portrait, "paste_head", record_paste)
    result = portrait.animate_expression(gesture, source, expected, tmp_path)
    assert result is not None
    assert np.array_equal(np.asarray(seen[0]), np.asarray(expected))
    assert pasted_sizes == [(512, 512)]
    assert not list(tmp_path.glob('.animate-*'))
    assert (tmp_path / 'animated-raw.png').exists()
    assert json.loads((tmp_path / 'animation.json').read_text())['source'] == 'original-photo'


def test_foreground_hand_is_protected_during_head_composite():
    target = Image.new("RGB", (256, 256), "black")
    patch = Image.new("RGB", (256, 256), "white")
    face = np.array([80, 70, 100, 120])
    result = imaging.paste_head(target, patch, np.array([[1, 0, 0], [0, 1, 0]], np.float32), face,
                                protected_regions=[(130, 120, 20, 25)])
    assert max(result.getpixel((140, 135))) < 20
    assert min(result.getpixel((105, 115))) > 200


def test_source_alpha_cannot_copy_a_second_head_or_hand_outline():
    target = Image.new('RGB', (256, 256), '#112233')
    patch = Image.new('RGB', (256, 256), 'white')
    face = np.array([80, 70, 100, 120])
    result = imaging.paste_head(target, patch, np.array([[1, 0, 0], [0, 1, 0]], np.float32), face,
                               source_mask=Image.new('L', (256, 256), 255))
    pixels = np.asarray(result)
    original = np.asarray(target)
    yy, xx = np.mgrid[:256, :256]
    outside = ((xx - 130) / 46) ** 2 + ((yy - 132.4) / 51.6) ** 2 >= 1
    assert np.array_equal(pixels[outside], original[outside])
    assert result.getpixel((90, 50)) == target.getpixel((90, 50))  # old hair expansion leaked here
    assert min(result.getpixel((130, 125))) > 240


def test_face_alignment_uses_eyes_nose_and_keeps_expression(monkeypatch):
    face = np.array([80,70,100,120,100,110,150,110,130,140,105,170,150,170,.99], np.float32)
    target_face = face.copy()
    target_face[4:10] += np.array([12,8,12,8,12,8])
    target_face[10:14] += 70  # fitting mouth landmarks would distort expression
    results = iter([np.array([face]), np.array([target_face])])
    monkeypatch.setattr(imaging, 'detect_faces', lambda *args: next(results))
    patch = Image.new('RGB',(512,512),'black')
    ImageDraw.Draw(patch).rectangle((95,105,105,115),fill='white')
    aligned = imaging.align_face_patch(patch,patch,np.array([[1,0,0],[0,1,0]],np.float32),Image.new('L',(512,512),255))
    assert aligned is not None
    assert min(aligned[0].getpixel((112,118))) > 240


def test_face_alignment_rejects_large_geometry_changes(monkeypatch):
    face = np.array([80,70,100,120,100,110,150,110,130,140,105,170,150,170,.99], np.float32)
    target = face.copy()
    target[4:10] *= 2
    results = iter([np.array([face]), np.array([target])])
    monkeypatch.setattr(imaging,'detect_faces',lambda *args: next(results))
    image = Image.new('RGB',(512,512))
    assert imaging.align_face_patch(image,image,np.array([[1,0,0],[0,1,0]],np.float32),None) is None


def test_approval_requires_review_and_flagged_image_needs_explicit_override(client, cartoon_engine):
    pack = create_pack(client, legacy=False)
    worker.run_once()
    assert client.post(f"/api/packs/{pack['id']}/approve").status_code == 409
    state = client.get(f"/api/packs/{pack['id']}").json()
    first = next(s for s in state['stickers'] if s['image_url'])
    with Session(db.engine) as session:
        session.get(db.Sticker, first['id']).quality_status = 'blocked'
        session.commit()
    assert client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/review").status_code == 409
    assert client.post(f"/api/packs/{pack['id']}/approve").status_code == 409


def test_compare_restore_keeps_immutable_artwork_and_other_stickers(client, cartoon_engine):
    pack = ready_pack(client)
    first = pack['stickers'][0]
    base = f"/api/packs/{pack['id']}/stickers/{first['id']}"
    original = client.get(first['image_url']).content
    versions = client.get(base + '/versions').json()
    saved = versions[0]
    assert client.patch(base, json={'caption': 'New caption'}).status_code == 200
    assert client.get(first['image_url']).content != original
    response = client.post(base + f"/versions/{saved['id']}/restore")
    assert response.status_code == 200, response.text
    assert client.get(first['image_url']).content == original
    assert response.json()['stickers'][0]['revision'] > first['revision']
    other = pack['stickers'][1]
    assert client.post(f"/api/packs/{pack['id']}/stickers/{other['id']}/versions/{saved['id']}/restore").status_code == 404
    assert len(cartoon_engine.calls) == 12


def test_cartoon_requires_character_selection_before_reaction_preview(client, cartoon_engine):
    response = client.post('/api/packs', files={'photo': ('p.png', sample_upload(), 'image/png')}, data={'style': 'cartoon', 'consent': 'true'})
    assert response.status_code == 201
    pack = response.json()
    worker.run_once()
    state = client.get(f"/api/packs/{pack['id']}").json()
    assert state['status'] == 'awaiting_design'
    assert len(state['designs']) == 2 and not any(s['image_url'] for s in state['stickers'])
    assert client.post(f"/api/packs/{pack['id']}/design", json={'candidate': 0}).status_code == 200
    worker.run_once()
    state = client.get(f"/api/packs/{pack['id']}").json()
    assert state['status'] == 'awaiting_approval' and state['design_url']
    assert len(cartoon_engine.calls) == 5


def test_targeted_correction_records_intensity_and_keeps_other_reactions(client, cartoon_engine):
    pack = ready_pack(client)
    first = pack['stickers'][0]
    response = client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/regenerate", json={'correction': 'hands', 'intensity': 1.2})
    assert response.status_code == 200
    with Session(db.engine) as session:
        job = session.get(db.Pack, pack['id']).jobs[-1]
        assert json.loads(job.payload)['correction_kind'] == 'hands'
        assert session.get(db.Sticker, first['id']).expression_intensity == 1.2
    worker.run_once()
    assert len(cartoon_engine.calls) == 13 and cartoon_engine.calls[-1][0] == first['id']
    assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409


def test_regeneration_applies_region_compositor(client, cartoon_engine, monkeypatch):
    from backend.app import corrections
    pack = ready_pack(client)
    first = pack['stickers'][0]
    seen = []
    def composite(original, candidate, kind):
        seen.append(kind)
        return candidate, 'Regional correction reviewed separately'
    monkeypatch.setattr(corrections, 'localize', composite)
    response = client.post(f"/api/packs/{pack['id']}/stickers/{first['id']}/regenerate", json={'correction': 'face', 'intensity': .8})
    assert response.status_code == 200
    worker.run_once()
    assert seen == ['face']
    updated = client.get(f"/api/packs/{pack['id']}").json()['stickers'][0]
    assert 'Regional correction' in updated['likeness_note']


def test_regional_face_correction_preserves_outside_pixels(monkeypatch):
    from backend.app import corrections
    face = np.array([70, 60, 80, 100, 90, 90, 130, 90, 110, 110, 95, 135, 125, 135, .99], np.float32)
    monkeypatch.setattr(corrections, "detect_faces", lambda *args: [face])
    original = Image.new("RGB", (256, 256), "red")
    candidate = Image.new("RGB", (256, 256), "blue")
    corrected, note = corrections.localize(original, candidate, "face")
    assert corrected.getpixel((10, 240)) == original.getpixel((10, 240))
    assert corrected.getpixel((110, 110))[2] > 240
    assert "region correction" in note


def test_cartoon_hand_detector_is_advisory_until_calibrated(monkeypatch):
    monkeypatch.setattr(quality, "detect_faces", lambda *args: np.array([[20, 20, 80, 100] + [0] * 11]))
    monkeypatch.setattr(quality, "hand_regions", lambda image: [([0, 0, 10, 10], .9)] * 5)
    report = quality.evaluate(Image.new("RGB", (256, 256)), .99, "laughter", "cartoon")
    assert report["status"] == "needs_review"
    assert report["checks"]["anatomy"]["state"] == "review"


def test_model_provenance_hashes_actual_installed_weights(tmp_path, monkeypatch):
    import hashlib
    from backend.app import provenance
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    folder = tmp_path / 'runtime' / 'comfyui' / 'models' / 'unet'
    folder.mkdir(parents=True)
    path = folder / 'test.gguf'
    path.write_bytes(b'original model')
    graph = {'1': {'inputs': {'unet_name': 'test.gguf'}}}
    first = provenance.models(graph)[0]
    assert first['sha256'] == hashlib.sha256(b'original model').hexdigest()
    path.write_bytes(b'changed weights of a different size')
    assert provenance.models(graph)[0]['sha256'] != first['sha256']


def test_design_progress_has_correct_phase_before_first_attempt(client, cartoon_engine):
    response = client.post('/api/packs', files={'photo': ('p.png', sample_upload(), 'image/png')}, data={'style': 'comic', 'consent': 'true'})
    assert response.status_code == 201
    job = client.get(f"/api/packs/{response.json()['id']}/job").json()
    assert job['phase'] == 'Creating character designs'


def test_rotated_views_do_not_count_one_hand_twice():
    boxes = [([94, 449, 165, 165], .99), ([121, 401, 117, 117], .87),
             ([522, 449, 161, 161], .98), ([563, 412, 102, 102], .92)]
    assert len(quality.merge_regions(boxes)) == 2
    distinct = [([256, 409, 104, 104], .97), ([432, 373, 106, 106], .96), ([378, 650, 80, 80], .54)]
    assert len(quality.merge_regions(distinct)) == 3
