"""Local face comparison. Scores are advisory, not a calibrated identity guarantee."""
import os
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from .config import FACE_MODELS_DIR, pack_dir
from .imaging import aligned_canvas, body_reference, detect_faces, face_reference, on_white, person_cutout, save_png


def _recognizer():
    path = FACE_MODELS_DIR / "face_recognition_sface_2021dec.onnx"
    if not path.is_file():
        raise RuntimeError("Face comparison model missing. Run setup.ps1 -DownloadModel.")
    return cv2.FaceRecognizerSF.create(str(path), "")


def embedding(image, score_threshold=0.8):
    faces = detect_faces(image, score_threshold)
    if not len(faces):
        return None
    face = faces[np.argmax(faces[:, 2] * faces[:, 3])]
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    recognizer = _recognizer()
    return recognizer.feature(recognizer.alignCrop(bgr, face)).copy()


def likeness(reference: np.ndarray, image) -> float | None:
    feature = embedding(image, 0.5)
    if feature is None:
        return None
    score = float(_recognizer().match(reference, feature, cv2.FaceRecognizerSF_FR_COSINE))
    return max(-1.0, min(1.0, score)) if np.isfinite(score) else None


def save_embedding(feature, path):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            np.save(output, feature, allow_pickle=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_references(pack_id: str):
    directory = pack_dir(pack_id)
    if not all((directory / name).is_file() for name in ("face.png", "body.png", "face-embedding.npy")):
        with Image.open(directory / "reference.png") as source:
            image = source.convert("RGB")
        face = face_reference(image)
        feature = embedding(image)
        if feature is None:
            raise ValueError("No clear face found in this pack. Start over with a closer, well-lit photo.")
        save_png(face, directory / "face.png")
        save_png(body_reference(image), directory / "body.png")
        save_embedding(feature, directory / "face-embedding.npy")
    return directory / "face.png", directory / "body.png"


def photo_references(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Aligned 768 chest-up canvas and a 512 face crop, both of the real person on white."""
    faces = detect_faces(image)
    if not len(faces):
        raise ValueError("No clear face found. Use a well-lit, front-facing photo of one person.")
    person = on_white(person_cutout(image))
    return aligned_canvas(person, faces[np.argmax(faces[:, 2] * faces[:, 3])]), face_reference(person)


def ensure_photo_references(pack_id: str):
    ensure_references(pack_id)
    directory = pack_dir(pack_id)
    if not all((directory / name).is_file() for name in ("canvas.png", "face-clean.png")):
        with Image.open(directory / "reference.png") as source:
            canvas, face = photo_references(source.convert("RGB"))
        save_png(canvas, directory / "canvas.png")
        save_png(face, directory / "face-clean.png")
    return directory / "canvas.png", directory / "face-clean.png"
