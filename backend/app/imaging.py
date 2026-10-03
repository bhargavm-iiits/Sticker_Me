import io
import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import regex
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from scipy import ndimage
from scipy.ndimage import binary_propagation

from .config import U2NET_HOME, FACE_MODELS_DIR


CANVAS_SIZE = 512
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def normalize_upload(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Photo must be between 1 byte and 12 MB")
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Use a JPEG, PNG, or WebP photo")
        if image.width * image.height > MAX_PIXELS or min(image.size) < 256:
            raise ValueError("Photo dimensions must be at least 256 px and no more than 20 MP")
        image = ImageOps.exif_transpose(image)
        image = trim_bars(image.convert("RGB"))
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        return image
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The photo could not be decoded safely") from exc


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        image.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def trim_bars(image: Image.Image, tolerance: int = 10) -> Image.Image:
    """Trim near-black or near-white padding connected to the image edges.

    Require strips to match the same edge color, cap removal, and leave normal
    colored backgrounds alone. Uniformity alone would crop skin or clothing.
    """
    rgb = np.asarray(image.convert("RGB")).astype(np.int16)
    top, bottom, left, right = 0, image.height, 0, image.width

    def is_bar(line, color):
        return ((color.max() <= tolerance or color.min() >= 255 - tolerance)
                and (np.abs(line - color).max(axis=1) <= tolerance).mean() > 0.98)

    for edge in ("top", "bottom", "left", "right"):
        line = rgb[top, left:right] if edge == "top" else rgb[bottom - 1, left:right] if edge == "bottom" else rgb[top:bottom, left] if edge == "left" else rgb[top:bottom, right - 1]
        color = np.median(line, axis=0)
        limit = int((image.height if edge in {"top", "bottom"} else image.width) * 0.25)
        for _ in range(limit):
            line = rgb[top, left:right] if edge == "top" else rgb[bottom - 1, left:right] if edge == "bottom" else rgb[top:bottom, left] if edge == "left" else rgb[top:bottom, right - 1]
            if not is_bar(line, color):
                break
            if edge == "top": top += 1
            elif edge == "bottom": bottom -= 1
            elif edge == "left": left += 1
            else: right -= 1
    if (bottom - top) * (right - left) < 0.4 * image.width * image.height:
        return image
    return image.crop((left, top, right, bottom))


def detect_faces(image: Image.Image, score_threshold: float = 0.8) -> np.ndarray:
    path = FACE_MODELS_DIR / "face_detection_yunet_2023mar.onnx"
    if not path.is_file():
        raise RuntimeError("Face detector missing. Run setup.ps1 -DownloadModel.")
    # YuNet detects small faces best. Scale detection only; crop the original.
    scale = min(1.0, 1024 / max(image.size))
    small = image.convert("RGB").resize((round(image.width * scale), round(image.height * scale)))
    bgr = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(str(path), "", small.size, score_threshold, 0.3, 50)
    _, faces = detector.detect(bgr)
    if faces is None:
        return np.empty((0, 15), np.float32)
    faces[:, :14] /= scale
    return faces


def square_box(face, scale: float, bounds: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = face[:4]
    side = min(round(max(w, h) * scale), *bounds)
    cx, cy = x + w / 2, y + h / 2 - 0.1 * h
    left = max(0, min(bounds[0] - side, round(cx - side / 2)))
    top = max(0, min(bounds[1] - side, round(cy - side / 2)))
    return left, top, left + side, top + side


def face_reference(image: Image.Image, size: int = 512) -> Image.Image:
    faces = detect_faces(image)
    if not len(faces):
        raise ValueError("No clear face found. Use a well-lit, front-facing photo of one person.")
    faces = faces[np.argsort(-(faces[:, 2] * faces[:, 3]))]
    if len(faces) > 1 and faces[1, 2] * faces[1, 3] > 0.4 * faces[0, 2] * faces[0, 3]:
        raise ValueError("More than one face found. Use a photo with only one person.")
    if min(faces[0, 2:4]) < 64:
        raise ValueError("The face is too small in this photo. Use a closer photo.")
    return image.crop(square_box(faces[0], 2.0, image.size)).resize((size, size), Image.Resampling.LANCZOS)


def body_reference(image: Image.Image, megapixels: float = 0.25) -> Image.Image:
    try:
        cutout = remove_background(image)
        alpha = cutout.getchannel("A")
        white = Image.new("RGB", cutout.size, "white")
        white.paste(cutout.convert("RGB"), mask=alpha)
        image = white.crop(alpha.getbbox())
    except ValueError:
        pass
    scale = (megapixels * 1024 * 1024 / (image.width * image.height)) ** 0.5
    width, height = (max(16, round(value * scale / 16) * 16) for value in image.size)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def align_by_landmarks(refined: Image.Image, original: Image.Image) -> Image.Image | None:
    source, target = detect_faces(refined, 0.5), detect_faces(original, 0.5)
    if len(source) != 1 or len(target) != 1:
        return None
    matrix, inliers = cv2.estimateAffinePartial2D(source[0, 4:14].reshape(5, 2), target[0, 4:14].reshape(5, 2), method=cv2.LMEDS)
    if matrix is None or not np.isfinite(matrix).all():
        return None
    zoom = np.linalg.norm(matrix[0, :2])
    if not 0.75 <= zoom <= 1.3:
        return None
    result = cv2.warpAffine(np.asarray(refined.convert("RGB")), matrix, original.size, borderMode=cv2.BORDER_REFLECT)
    return Image.fromarray(result)


def paste_feathered_ellipse(image: Image.Image, refined: Image.Image, box, feather: float = 0.08) -> Image.Image:
    left, top, right, bottom = box
    size = right - left, bottom - top
    patch = refined.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    # Restrict the blend to the central face, preserving hair silhouette and hands.
    ImageDraw.Draw(mask).ellipse((size[0] * 0.18, size[1] * 0.20, size[0] * 0.82, size[1] * 0.85), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(size) * feather))
    result = image.convert("RGB").copy()
    result.paste(patch, (left, top), mask)
    return result


def portrait_render(image: Image.Image, style: str) -> Image.Image:
    """Illustration shading without moving the generated person's facial features."""
    if style not in {"likeness", "cartoon"}:
        return image
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    smooth = cv2.bilateralFilter(bgr, 9, 75 if style == "cartoon" else 35, 75)
    if style == "cartoon":
        smooth = cv2.bilateralFilter(smooth, 9, 75, 75)
    rgb = cv2.cvtColor(smooth, cv2.COLOR_BGR2RGB).astype(np.float32)
    step, mix, strength = (20, 0.75, 0.75) if style == "cartoon" else (8, 0.3, 0.2)
    quantized = np.clip(np.round(rgb / step) * step, 0, 255)
    colors = quantized * mix + rgb * (1 - mix)
    low, high, min_area = (90, 180, 20) if style == "cartoon" else (120, 240, 30)
    edges = cv2.Canny(cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY), low, high)
    # Stubble and pores produce tiny edge fragments that read as black specks; keep contour lines only.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False
    edges = cv2.GaussianBlur(keep[labels].astype(np.float32), (3, 3), 0.6)
    return Image.fromarray(np.clip(colors * (1 - strength * edges[:, :, None]), 0, 255).astype(np.uint8))


def person_cutout(image: Image.Image) -> Image.Image:
    """Remove haze/islands while retaining soft hair edges and intentional openings."""
    cutout = remove_background(image)
    alpha = np.asarray(cutout.getchannel("A")).copy()
    labels, count = ndimage.label(alpha > 16)
    if not count:
        raise ValueError("Background removal did not find a person")
    core_sizes = np.bincount(labels[alpha > 128].ravel(), minlength=count + 1)
    core_sizes[0] = 0
    keep_labels = np.flatnonzero(core_sizes >= max(12, .002 * core_sizes.max()))
    keep = np.isin(labels, keep_labels)
    alpha[~keep] = 0
    # Fill only tiny enclosed mask defects, not the space between fingers/arms.
    holes = ndimage.binary_fill_holes(keep) & ~keep
    hole_labels, hole_count = ndimage.label(holes)
    sizes = np.bincount(hole_labels.ravel(), minlength=hole_count + 1)
    tiny = np.flatnonzero((sizes <= max(20, round(alpha.size * .0008))) & (np.arange(len(sizes)) > 0))
    alpha[np.isin(hole_labels, tiny)] = 255
    cutout.putalpha(Image.fromarray(alpha))
    return cutout


def on_white(cutout: Image.Image) -> Image.Image:
    white = Image.new("RGB", cutout.size, "white")
    white.paste(cutout.convert("RGB"), mask=cutout.getchannel("A"))
    return white


def aligned_canvas(person: Image.Image, face, size: int = 768, scale: float = 3.0) -> Image.Image:
    """Chest-up square around the real face; area outside the photo is white so arms can be raised."""
    x, y, w, h = (float(value) for value in face[:4])
    side = max(1, round(scale * h))
    left, top = round(x + w / 2 - side / 2), round(y - 0.5 * h)
    canvas = Image.new("RGB", (side, side), "white")
    canvas.paste(person.convert("RGB"), (-left, -top))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def portrait_matrix(face, size: int = 512, scale: float = 2.3, shift: float = -0.125) -> np.ndarray:
    """Similarity transform to a LivePortrait-style crop: eyes level, face about 45% of the width."""
    points = np.asarray(face[4:14], np.float64).reshape(5, 2)
    eyes, mouth = (points[0] + points[1]) / 2, (points[3] + points[4]) / 2
    down = (mouth - eyes) / max(np.linalg.norm(mouth - eyes), 1e-6)
    rotation = np.stack([np.array([down[1], -down[0]]), down])
    side = scale * max(float(face[2]), 0.8 * float(face[3]))
    centre = (eyes + mouth) / 2 + down * (shift * side)
    linear = size / side * rotation
    return np.hstack([linear, (size / 2 - linear @ centre)[:, None]]).astype(np.float32)


def warp_crop(image: Image.Image, matrix: np.ndarray, size: int = 512) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    return Image.fromarray(cv2.warpAffine(rgb, matrix, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255)))


def align_face_patch(target: Image.Image, patch: Image.Image, matrix: np.ndarray, source_mask):
    """Align eyes/nose to the target without fitting away the mouth expression."""
    patch = patch.convert('RGB').resize((512, 512), Image.Resampling.LANCZOS)
    source_faces = detect_faces(patch, .5)
    target_faces = detect_faces(warp_crop(target, matrix), .5)
    if len(source_faces) != 1 or len(target_faces) != 1:
        return None
    source_points = np.asarray(source_faces[0, 4:10], np.float32).reshape(3, 2)
    target_points = np.asarray(target_faces[0, 4:10], np.float32).reshape(3, 2)
    adjustment = cv2.getAffineTransform(source_points, target_points)
    scales = np.linalg.svd(adjustment[:, :2], compute_uv=False)
    if np.linalg.det(adjustment[:, :2]) <= 0 or scales.min() < .75 or scales.max() > 1.3:
        return None
    aligned = cv2.warpAffine(np.asarray(patch), adjustment, (512, 512), borderValue=(255,255,255))
    mask = cv2.warpAffine(np.asarray(source_mask.resize((512,512))), adjustment, (512,512)) if source_mask is not None else None
    return Image.fromarray(aligned), Image.fromarray(mask) if mask is not None else None


def paste_head(target: Image.Image, patch: Image.Image, matrix: np.ndarray, face, *, source_mask=None, protected_regions=()) -> Image.Image:
    """Replace the interior face while keeping the target's single head/body silhouette.

    A source-person alpha is not a head mask: enlarging it into hair/ears copies
    displaced outlines and can duplicate nearby hands. Feather strictly inward.
    """
    inverse = cv2.invertAffineTransform(matrix)
    width, height = target.size
    crop = patch.size[0]
    border = np.zeros((crop, crop), np.float32)
    border[16:-16, 16:-16] = 1
    inside = cv2.warpAffine(cv2.GaussianBlur(border, (0, 0), 6), inverse, (width, height), flags=cv2.INTER_LINEAR)
    x, y, w, h = (float(value) for value in face[:4])
    yy, xx = np.mgrid[:height, :width]
    radius = np.sqrt(((xx - x - .5 * w) / max(1, .46 * w)) ** 2
                     + ((yy - y - .52 * h) / max(1, .43 * h)) ** 2)
    head = np.clip((1 - radius) / .15, 0, 1).astype(np.float32)
    if source_mask is not None:
        segmented = cv2.warpAffine(np.asarray(source_mask, np.float32) / 255, inverse, (width, height), flags=cv2.INTER_LINEAR)
        # Alpha can restrict face replacement, never expand it into the silhouette.
        head *= np.clip(segmented, 0, 1)
    for region in protected_regions:
        hx, hy, hw, hh = region
        occlusion = np.zeros_like(head)
        cv2.rectangle(occlusion, (max(0, round(hx - .08 * hw)), max(0, round(hy - .12 * hh))),
                      (min(width - 1, round(hx + 1.08 * hw)), min(height - 1, round(hy + 1.1 * hh))), 1, -1)
        head *= 1 - cv2.GaussianBlur(occlusion, (0, 0), 2)
    weight = (head * inside)[..., None]
    warped = cv2.warpAffine(np.asarray(patch.convert("RGB")), inverse, (width, height), flags=cv2.INTER_LINEAR).astype(np.float32)
    blended = weight * warped + (1 - weight) * np.asarray(target.convert("RGB"), np.float32)
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))


@lru_cache(maxsize=2)
def background_session(model: str = "u2netp"):
    os.environ["U2NET_HOME"] = str(U2NET_HOME)
    from rembg import new_session

    return new_session(model)


def remove_background(image: Image.Image, model: str = "u2netp") -> Image.Image:
    from rembg import remove

    # rembg's default naive_cutout composites RGB against transparent black,
    # multiplying colors by alpha. PNG/Pillow expect straight RGB and alpha;
    # blending that result again makes a dark halo around soft shirt/hair edges.
    alpha = remove(image.convert("RGB"), session=background_session(model), only_mask=True)
    if not isinstance(alpha, Image.Image):
        alpha = Image.open(io.BytesIO(alpha))
    alpha = alpha.convert("L")
    if alpha.getextrema() == (255, 255) or alpha.getbbox() is None:
        raise ValueError("Background removal did not produce a usable transparent cutout")
    output = image.convert("RGBA")
    output.putalpha(alpha)
    return output


def remove_cartoon_background(image: Image.Image) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    near_white = rgb.min(axis=2) >= 235
    border = np.zeros(near_white.shape, dtype=bool)
    border[0, :] = border[-1, :] = True
    border[:, 0] = border[:, -1] = True
    if near_white[border].mean() < 0.8:
        return remove_background(image)
    background = binary_propagation(border & near_white, mask=near_white)
    output = image.convert("RGBA")
    output.putalpha(Image.fromarray(np.where(background, 0, 255).astype(np.uint8)))
    if output.getchannel("A").getbbox() is None:
        raise ValueError("Generated cartoon has no usable foreground")
    return output


def font_path(language: str) -> Path:
    local = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    if language != "en":
        raise RuntimeError("Only English captions are supported")
    candidates = [local / "NotoSans-Bold.ttf", Path("C:/Windows/Fonts/arialbd.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(f"No usable {language} font found; install a supported font")


def wrap_caption(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        if draw.textlength(word, font=font) <= max_width:
            line = word
            continue
        for grapheme in regex.findall(r"\X", word):
            candidate = line + grapheme
            if line and draw.textlength(candidate, font=font) > max_width:
                lines.append(line)
                line = grapheme
            else:
                line = candidate
    if line:
        lines.append(line)
    return lines


def compose_sticker(cutout: Image.Image, caption: str, language: str) -> Image.Image:
    caption = unicodedata.normalize("NFC", caption).strip()
    if len(regex.findall(r"\X", caption)) > 48:
        raise ValueError("Caption is too long (maximum 48 characters)")
    if language != "en":
        raise ValueError("Only English captions are supported")

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    alpha = cutout.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("The cutout has no foreground")
    text_layer = None
    text_height = 0
    if caption:
        draw = ImageDraw.Draw(canvas)
        for size in range(42, 19, -2):
            font = ImageFont.truetype(str(font_path(language)), size)
            lines = wrap_caption(draw, caption, font, 456)
            if len(lines) <= 2:
                break
        else:
            raise ValueError("Caption does not fit on the sticker")
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=4) for line in lines]
        text_height = sum(box[3] - box[1] for box in boxes) + 4 * (len(lines) - 1)
        text_layer = Image.new("RGBA", (CANVAS_SIZE, text_height), (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_layer)
        y = 0
        for line, box in zip(lines, boxes):
            text_draw.text(((CANVAS_SIZE - (box[2] - box[0])) / 2 - box[0], y - box[1]), line,
                           font=font, fill="#FFFFFF", stroke_width=4, stroke_fill="#38215F")
            y += box[3] - box[1] + 4
    # Figure and words form one centered group, with a small shared gap.
    border, gap = 9, 6 if caption else 0
    person = cutout.crop(bounds)
    person.thumbnail((466, CANVAS_SIZE - 28 - 2 * border - gap - text_height), Image.Resampling.LANCZOS)
    mask = person.getchannel("A")
    row = np.asarray(mask)[-1] > 128
    if row.mean() > .55:
        # Round only a broad flat torso cut; do not reshape hair or detached hands.
        edges = np.flatnonzero(row)
        centre, half = (edges[0] + edges[-1]) / 2, max(1, (edges[-1] - edges[0]) / 2)
        depth = min(24, person.height // 12)
        yy, xx = np.mgrid[:person.height, :person.width]
        curve = person.height - 1 - depth * np.clip(abs((xx - centre) / half), 0, 1) ** 4
        rounded = np.clip((curve - yy + 1) / 2, 0, 1)
        person.putalpha(Image.fromarray((np.asarray(mask, np.float32) * rounded).astype(np.uint8)))
    person = ImageOps.expand(person, border=border, fill=(0, 0, 0, 0))
    left = (CANVAS_SIZE - person.width) // 2
    top = (CANVAS_SIZE - person.height - gap - text_height) // 2
    outline = person.getchannel("A").filter(ImageFilter.MaxFilter(15))
    white = Image.new("RGBA", person.size, "white")
    white.putalpha(outline)
    # Apply alpha once. paste(..., mask) onto transparent black stores darkened
    # RGB at partial alpha and creates another grey outline on a colored page.
    canvas.alpha_composite(white, (left, top))
    canvas.alpha_composite(person, (left, top))
    if text_layer:
        canvas.alpha_composite(text_layer, (0, top + person.height + gap))
    return canvas


def encode_webp(image: Image.Image, maximum_bytes: int) -> bytes:
    for quality in (90, 80, 70, 60, 50, 40):
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        if output.tell() <= maximum_bytes:
            return output.getvalue()
    raise ValueError(f"Sticker cannot fit the {maximum_bytes // 1024} KB WebP limit legibly")
