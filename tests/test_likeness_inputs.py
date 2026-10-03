import io

import numpy as np
import pytest
from PIL import Image
from skimage.data import astronaut

from backend.app import imaging, main
from backend.app.likeness import embedding, likeness
from tests.test_cutout_flow import client


def test_trim_bars_and_preserve_normal_image():
    photo = Image.fromarray(astronaut())
    padded = Image.new("RGB", (512, 640), "black")
    padded.paste(photo, (0, 64))
    assert np.array_equal(np.asarray(imaging.trim_bars(padded)), np.asarray(photo))
    assert np.array_equal(np.asarray(imaging.trim_bars(photo)), np.asarray(photo))
    solid = Image.new("RGB", (512, 512), "#c17a5f")
    assert imaging.trim_bars(solid).size == solid.size


def test_real_face_crop_and_self_similarity():
    photo = Image.fromarray(astronaut())
    assert len(imaging.detect_faces(photo)) == 1
    crop = imaging.face_reference(photo)
    assert crop.size == (512, 512)
    faces = imaging.detect_faces(crop)
    assert len(faces) == 1 and min(faces[0, 2:4]) > 150
    feature = embedding(photo)
    assert feature.shape == (1, 128)
    assert likeness(feature, photo) > 0.99


def test_illustration_shading_retains_recognizable_face():
    photo = Image.fromarray(astronaut())
    feature = embedding(photo)
    for style in ("likeness", "cartoon"):
        illustrated = imaging.portrait_render(photo, style)
        assert illustrated.size == photo.size
        assert likeness(feature, illustrated) > 0.5


@pytest.mark.parametrize("faces,message", [([], "No clear face"), ([[10, 10, 100, 100], [130, 10, 95, 95]], "More than one face"), ([[10, 10, 30, 30]], "too small")])
def test_reject_invalid_face_inputs(monkeypatch, faces, message):
    monkeypatch.setattr(imaging, "detect_faces", lambda image: np.asarray([row + [0] * 11 for row in faces], np.float32).reshape(-1, 15))
    with pytest.raises(ValueError, match=message):
        imaging.face_reference(Image.new("RGB", (512, 512)))


def test_no_face_returns_400_before_engine_check(client, monkeypatch):
    monkeypatch.setattr(main, "face_reference", imaging.face_reference)
    def unexpected():
        pytest.fail("Engine should not be checked for a photo without a face")
    monkeypatch.setattr(main, "engine_doctor", unexpected)
    data = io.BytesIO()
    Image.new("RGB", (512, 512), "blue").save(data, format="PNG")
    response = client.post("/api/packs", files={"photo": ("no-face.png", data.getvalue(), "image/png")}, data={"consent": "true"})
    assert response.status_code == 400
    assert "No clear face" in response.json()["detail"]


def test_body_dimensions_and_upload_detail_preserved(monkeypatch):
    monkeypatch.setattr(imaging, "remove_background", lambda image: (_ for _ in ()).throw(ValueError("No mask")))
    body = imaging.body_reference(Image.fromarray(astronaut()))
    assert all(side % 16 == 0 for side in body.size)
    data = io.BytesIO()
    Image.new("RGB", (1600, 1200), "blue").save(data, format="PNG")
    assert imaging.normalize_upload(data.getvalue()).size == (1600, 1200)
