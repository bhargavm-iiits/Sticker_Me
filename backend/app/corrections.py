"""Restrict a correction to a region of the previous artwork when alignment permits."""
import cv2
import numpy as np
from PIL import Image

from .imaging import detect_faces
from .quality import hand_regions


def localize(original: Image.Image, candidate: Image.Image, kind: str):
    if kind not in {"face", "hands", "expression"}:
        return candidate, None
    before, after = detect_faces(original, .5), detect_faces(candidate, .5)
    if len(before) != 1 or len(after) != 1:
        return candidate, "Regional correction could not align a single face; review the full redraw."
    old, new = before[0], after[0]
    matrix, _ = cv2.estimateAffinePartial2D(np.asarray(new[4:14]).reshape(5, 2), np.asarray(old[4:14]).reshape(5, 2))
    if matrix is None:
        return candidate, "Regional correction could not align the face; review the full redraw."
    scale = float(np.linalg.norm(matrix[:, 0]))
    if not .8 <= scale <= 1.25:
        return candidate, "Head size changed too much for a regional correction; review the full redraw."
    width, height = original.size
    aligned = cv2.warpAffine(np.asarray(candidate.convert("RGB")), matrix, (width, height), borderValue=(255, 255, 255))
    mask = np.zeros((height, width), np.float32)
    x, y, w, h = map(float, old[:4])
    if kind in {"face", "expression"}:
        cv2.ellipse(mask, (round(x + w / 2), round(y + .5 * h)), (round(.62 * w), round(.7 * h)), 0, 0, 360, 1, -1)
    else:
        try:
            regions = hand_regions(original) + hand_regions(Image.fromarray(aligned))
        except (OSError, ValueError, cv2.error):
            regions = []
        if not regions:
            return candidate, "No reliable hand region was found; review the full redraw."
        for (hx, hy, hw, hh), _ in regions:
            cv2.rectangle(mask, (max(0, round(hx - .7 * hw)), max(0, round(hy - .7 * hh))),
                          (min(width - 1, round(hx + 1.7 * hw)), min(height - 1, round(hy + 2 * hh))), 1, -1)
        head = np.zeros_like(mask)
        cv2.ellipse(head, (round(x + w / 2), round(y + .4 * h)), (round(.65 * w), round(.8 * h)), 0, 0, 360, 1, -1)
        mask *= 1 - head
    mask = cv2.GaussianBlur(mask, (0, 0), max(2, .02 * w))[..., None]
    result = mask * aligned + (1 - mask) * np.asarray(original.convert("RGB"), np.float32)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8)), f"Applied a {kind} region correction over the previous artwork; check its edges and intended reaction."
