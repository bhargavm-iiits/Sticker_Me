"""Independent, conservative checks. A detector result never certifies sticker quality."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from . import config
from .imaging import detect_faces

PALM_FILE = "palm_detection_mediapipe_2023feb.onnx"


@lru_cache(maxsize=1)
def palm_network():
    path = config.FACE_MODELS_DIR / PALM_FILE
    if not path.is_file():
        return None
    return cv2.dnn.readNet(str(path))


def _anchors():
    # MediaPipe short-range SSD: two anchors per cell at stride 8,
    # six at stride 16; all anchors have unit width and height.
    return np.asarray([((x + .5) / grid, (y + .5) / grid)
                       for grid, repeats in ((24, 2), (12, 6))
                       for y in range(grid) for x in range(grid) for _ in range(repeats)], np.float32)


def _palms(image):
    net = palm_network()
    if net is None:
        return None
    scale = 192 / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    small = np.asarray(image.convert("RGB").resize(size))
    left, top = (192 - size[0]) // 2, (192 - size[1]) // 2
    padded = np.zeros((192, 192, 3), np.float32)
    padded[top:top + size[1], left:left + size[0]] = small / 255.0
    net.setInput(padded[None])
    outputs = net.forward(net.getUnconnectedOutLayersNames())
    boxes = next(out for out in outputs if out.shape[-1] == 18)[0]
    logits = next(out for out in outputs if out.shape[-1] == 1)[0, :, 0]
    scores = 1 / (1 + np.exp(-np.clip(logits, -60, 60)))
    xy = (boxes[:, :2] / 192 + _anchors()) * 192
    wh = boxes[:, 2:4]
    rects = np.concatenate(((xy - wh / 2 - (left, top)) / scale, wh / scale), axis=1)
    keep = np.asarray(cv2.dnn.NMSBoxes(rects.tolist(), scores.tolist(), .35, .3)).ravel()
    return [(rects[index].tolist(), float(scores[index])) for index in keep]


def hand_regions(image):
    """Whole-image and overlapping crops catch small hands; merge duplicates."""
    found = _palms(image)
    if found is None:
        return None
    width, height = image.size
    for x in (0, round(width * .35)):
        for y in (0, round(height * .35)):
            crop = image.crop((x, y, min(width, x + round(width * .65)), min(height, y + round(height * .65))))
            for box, score in _palms(crop):
                box[0] += x
                box[1] += y
                found.append((box, score))
    # Horizontal/partly occluded hands are easily missed in the upright pass.
    # Rotate crops, map their boxes back, and merge detections in original coordinates.
    for rotation in (Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270):
        rotated = image.transpose(rotation)
        views = [(rotated, 0, 0)]
        rw, rh = rotated.size
        for x in (0, round(rw * .35)):
            for y in (0, round(rh * .35)):
                views.append((rotated.crop((x, y, min(rw, x + round(rw * .65)), min(rh, y + round(rh * .65)))), x, y))
        for view, vx, vy in views:
            for box, score in _palms(view):
                x, y, w, h = box
                corners = np.array([[x + vx, y + vy], [x + vx + w, y + vy + h]])
                if rotation == Image.Transpose.ROTATE_90:
                    mapped = np.column_stack((width - corners[:, 1], corners[:, 0]))
                elif rotation == Image.Transpose.ROTATE_180:
                    mapped = np.column_stack((width - corners[:, 0], height - corners[:, 1]))
                else:
                    mapped = np.column_stack((corners[:, 1], height - corners[:, 0]))
                low, high = mapped.min(axis=0), mapped.max(axis=0)
                found.append(([*low.tolist(), *(high - low).tolist()], score))
    if not found:
        return []
    indices = np.asarray(cv2.dnn.NMSBoxes([b for b, _ in found], [s for _, s in found], .35, .25)).ravel()
    return merge_regions([found[index] for index in indices])


def merge_regions(found):
    # Rotated views can put a palm box and a finger box on the same hand with
    # little IoU. Merge nearby centers using the original strongest detection;
    # do not let expanding unions chain across adjacent distinct hands.
    groups = []
    for box, score in sorted(found, key=lambda item: item[1], reverse=True):
        x, y, w, h = box
        centre = np.array([x + w / 2, y + h / 2])
        for anchor, union, confidence in groups:
            ax, ay, aw, ah = anchor
            distance = np.linalg.norm(centre - (ax + aw / 2, ay + ah / 2))
            if distance <= .65 * max(aw, ah, w, h):
                ux, uy, uw, uh = union
                low_x, low_y = min(ux, x), min(uy, y)
                union[:] = [low_x, low_y, max(ux + uw, x + w) - low_x, max(uy + uh, y + h) - low_y]
                break
        else:
            groups.append((box.copy(), box.copy(), score))
    return [(union, score) for _, union, score in groups]


def evaluate(image: Image.Image, score, intent: str, style: str, note=None):
    checks = {
        "identity": {"state": "unavailable" if score is None else "screened" if score >= config.LIKENESS_FLOOR else "review",
                     "score": score, "note": "Face similarity is advisory; compare with your photo."},
        "expression": {"state": "review", "note": f"Check that the {intent} expression, pose and prop match."},
        "style": {"state": "review", "note": "Compare the drawing with your approved character design." if style not in {"realistic", "likeness"} else "Check face detail and head alignment."},
    }
    blocked = False
    try:
        faces = detect_faces(image, .5)
        blocked = len(faces) > 1
        checks["framing"] = {"state": "blocked" if blocked else "review" if len(faces) != 1 else "screened",
                             "face_count": len(faces), "note": "Multiple faces detected." if blocked else "Check hair, sleeves and hands are fully inside the frame."}
        if len(faces) == 1:
            x, y, w, h = faces[0, :4]
            if min(x, y, image.width - x - w, image.height - y - h) < .02 * min(image.size):
                checks["framing"].update(state="review", note="Face is close to the edge; check cropping.")
    except (RuntimeError, cv2.error, OSError) as exc:
        checks["framing"] = {"state": "unavailable", "note": f"Face framing check unavailable: {exc}"}
    try:
        hands = hand_regions(image)
        extra = hands is not None and len(hands) > 2
        # The photographic palm model produces many false detections on ink/shading.
        # Do not apply its uncalibrated cartoon counts as a hard rejection gate.
        calibrated = style in {"realistic", "likeness"}
        blocked = blocked or (extra and calibrated)
        checks["anatomy"] = {"state": "unavailable" if hands is None else "blocked" if extra and calibrated else "review",
                             "detected_hands": None if hands is None else len(hands),
                             "confidence": [] if hands is None else [round(s, 3) for _, s in hands],
                             "note": "Possible extra hand detected; redraw this reaction. Detector findings can be false positives." if extra and calibrated else "Check hands visually: photographic detector counts are not calibrated for this drawing style." if not calibrated else "Check arms and fingers visually; the detector can miss or misread hands."}
    except (cv2.error, OSError, ValueError) as exc:
        checks["anatomy"] = {"state": "unavailable", "note": f"Hand check unavailable: {exc}"}
    if note:
        checks["generation"] = {"state": "review", "note": note}
    return {"status": "blocked" if blocked else "needs_review", "checks": checks}


def mask_report(cutout):
    alpha = np.asarray(cutout.getchannel("A"))
    coverage = float((alpha > 32).mean())
    return {"state": "review" if coverage > .9 or coverage < .03 else "screened", "coverage": round(coverage, 4),
            "note": "Check hair, white clothing, finger gaps and halos on light/dark backgrounds."}


def perceptual_hash(image):
    grey = np.asarray(image.convert("L").resize((9, 8)), np.int16)
    return (grey[:, 1:] > grey[:, :-1]).ravel()


def near_duplicate(image, previous):
    return int(np.count_nonzero(perceptual_hash(image) != perceptual_hash(previous))) <= 3
