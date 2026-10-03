"""Animate the person's own face to a new expression with LivePortrait.

The networks run in the engine environment (torch); this module prepares aligned
crops, calls scripts/liveportrait_runner.py and pastes the result back.
"""
import json
import cv2
import shutil
import subprocess
import os
import queue
import threading
from pathlib import Path
from uuid import uuid4

from PIL import Image

from . import config
from .imaging import detect_faces, paste_head, portrait_matrix, warp_crop, remove_background, align_face_patch

WEIGHTS = ("appearance_feature_extractor.pth", "motion_extractor.pth", "warping_module.pth", "spade_generator.pth", "stitching_retargeting_module.pth")
_runner = None
_responses = None
_runner_log = None
_runner_lock = threading.Lock()


def close_runner():
    global _runner, _responses, _runner_log
    with _runner_lock:
        if _runner is not None:
            if _runner.poll() is None:
                try:
                    _runner.stdin.write('{"shutdown":true}\n')
                    _runner.stdin.flush()
                    _runner.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    _runner.terminate()
                    try:
                        _runner.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _runner.kill()
                        _runner.wait(timeout=5)
            _runner.stdin.close()
            _runner.stdout.close()
        if _runner_log:
            _runner_log.close()
        _runner, _responses, _runner_log = None, None, None


def reusable():
    import psutil
    setting = os.environ.get("STICKERME_PORTRAIT_REUSE", "auto")
    return setting == "1" or (setting == "auto" and psutil.virtual_memory().available >= 3 * 1024**3)


def run_resident(request):
    global _runner, _responses, _runner_log
    if _runner is not None and _runner.poll() is not None:
        close_runner()
    with _runner_lock:
        if _runner is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _runner_log = (config.DATA_DIR / "portrait-runner.log").open("a", encoding="utf-8")
            _responses = queue.Queue()
            _runner = subprocess.Popen([str(config.ENGINE_PYTHON), str(config.ROOT / "scripts" / "liveportrait_runner.py"), "--serve"],
                                       cwd=config.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=_runner_log, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            process, responses = _runner, _responses
            def read_results():
                for line in process.stdout:
                    try:
                        responses.put(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                responses.put({"error": "Resident face animator exited; inspect portrait-runner.log"})
            threading.Thread(target=read_results, daemon=True).start()
        _runner.stdin.write(json.dumps(request) + "\n")
        _runner.stdin.flush()
        try:
            result = _responses.get(timeout=600)
        except queue.Empty as exc:
            raise subprocess.TimeoutExpired("Resident face animator", 600) from exc
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result


def available() -> bool:
    weights = config.LIVEPORTRAIT_DIR / "weights"
    return config.ENGINE_PYTHON.is_file() and (config.LIVEPORTRAIT_DIR / "src" / "modules").is_dir() and all((weights / name).is_file() for name in WEIGHTS)


def single_face(image: Image.Image, threshold: float = 0.5):
    faces = detect_faces(image, threshold)
    return faces[0] if len(faces) == 1 else None


def driver_crop(canvas: Image.Image) -> Image.Image:
    """Close-up of the real photo that the expression driver is drawn from (and compared to)."""
    face = single_face(canvas, 0.8)
    if face is None:
        raise ValueError("A single face was not found in the photo canvas")
    return warp_crop(canvas, portrait_matrix(face))


def run(jobs: list[dict], workspace: Path) -> list[Image.Image]:
    if not available():
        raise RuntimeError("LivePortrait is not installed. Run setup.ps1 -DownloadModel.")
    request = workspace / "request.json"
    request.write_text(json.dumps({"device": "auto", "jobs": jobs}), encoding="utf-8")
    if _runner is not None or reusable():
        try:
            run_resident({"device": "cpu", "jobs": jobs})
        except Exception:
            close_runner()
            raise
    else:
        result = subprocess.run(
            [str(config.ENGINE_PYTHON), str(config.ROOT / "scripts" / "liveportrait_runner.py"), str(request)],
            capture_output=True, text=True, timeout=600, cwd=str(config.ROOT), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(f"Face animation failed: {result.stderr.strip()[-600:]}")
    outputs = []
    for job in jobs:
        with Image.open(job["output"]) as image:
            outputs.append(image.convert("RGB"))
    return outputs


def animate_expression(gesture: Image.Image, canvas: Image.Image, driver: Image.Image, workspace_parent: Path, strength: float = 1.0) -> Image.Image | None:
    """Animate the original face, keeping the gesture image's hair/head silhouette.

    driver is the expression-edited driver_crop(canvas); returns None when no single face is
    found in the gesture image.
    """
    face, original_face = single_face(gesture), single_face(canvas, .8)
    if face is None or original_face is None:
        return None
    # Large head moves/scale changes make an original-head composite unreliable.
    ratio = face[2] / original_face[2]
    displacement = ((face[:2] + face[2:4] / 2) - (original_face[:2] + original_face[2:4] / 2))
    if not .8 <= ratio <= 1.25 or max(abs(displacement)) > .3 * original_face[2]:
        return None
    matrix = portrait_matrix(face)
    original_crop = warp_crop(canvas, portrait_matrix(original_face))
    workspace = workspace_parent / f".animate-{uuid4().hex}"
    workspace.mkdir(parents=True)
    try:
        paths = {name: workspace / f"{name}.png" for name in ("source", "driver", "reference", "output")}
        original_crop.save(paths["source"])
        driver.convert("RGB").resize((512, 512), Image.Resampling.LANCZOS).save(paths["driver"])
        original_crop.save(paths["reference"])
        job = {name: str(path) for name, path in paths.items()}
        job["multiplier"] = strength
        decoded = run([job], workspace)[0]
        # Keep raw motion output and source/driver crops for visual diagnosis.
        for name in ("source", "driver", "reference"):
            shutil.copyfile(paths[name], workspace_parent / f"{name}.png")
        decoded.save(workspace_parent / "animated-raw.png")
        (workspace_parent / "animation.json").write_text(json.dumps({"multiplier": strength, "source": "original-photo",
            "decoder_size": list(decoded.size), "crop_size": [512, 512], "target_transform": matrix.tolist()}, indent=2), encoding="utf-8")
        # Decoder sizes vary; the inverse transform expects a 512px crop.
        animated = decoded.resize((512, 512), Image.Resampling.LANCZOS)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    from .quality import hand_regions
    try:
        regions = hand_regions(gesture)
    except (OSError, ValueError, cv2.error):
        regions = None
    # Hand detector is conservative: protect detected foreground regions; failures
    # remain visible in the independent quality report rather than certifying anatomy.
    mask = remove_background(original_crop).getchannel("A")
    aligned = align_face_patch(gesture, animated, matrix, mask)
    if aligned is None:
        return None
    animated, mask = aligned
    return paste_head(gesture, animated, matrix, face, source_mask=mask,
                      protected_regions=[box for box, _ in regions] if regions else [])


def preserve_original_head(gesture: Image.Image, canvas: Image.Image) -> Image.Image | None:
    """Restore the original facial interior when animation cannot safely align."""
    face, original = single_face(gesture), single_face(canvas, .8)
    if face is None or original is None:
        return None
    ratio = face[2] / original[2]
    displacement = (face[:2] + face[2:4] / 2) - (original[:2] + original[2:4] / 2)
    if not .8 <= ratio <= 1.25 or max(abs(displacement)) > .3 * original[2]:
        return None
    crop = warp_crop(canvas, portrait_matrix(original))
    from .quality import hand_regions
    try:
        regions = hand_regions(gesture)
    except (OSError, ValueError, cv2.error):
        regions = []
    matrix = portrait_matrix(face)
    aligned = align_face_patch(gesture, crop, matrix, remove_background(crop).getchannel("A"))
    if aligned is None:
        return None
    crop, mask = aligned
    return paste_head(gesture, crop, matrix, face,
                      source_mask=mask,
                      protected_regions=[box for box, _ in regions] if regions else [])
