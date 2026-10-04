import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("STICKERME_DATA_DIR", ROOT / "runtime")).resolve()
PACKS_DIR = DATA_DIR / "packs"
DB_PATH = DATA_DIR / "stickerme.sqlite3"
U2NET_HOME = DATA_DIR / "models"
COMFY_URL = os.environ.get("STICKERME_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
WORKFLOW_PATH = ROOT / "workflows" / "klein4b-api.json"
FACE_MODELS_DIR = ROOT / "runtime" / "models" / "face"
FACE_REFINE = os.environ.get("STICKERME_FACE_REFINE", "1") == "1"
LIKENESS_RETRIES = max(0, min(4, int(os.environ.get("STICKERME_LIKENESS_RETRIES", "1"))))
LIKENESS_FLOOR = float(os.environ.get("STICKERME_LIKENESS_FLOOR", "0.30"))
PORTRAIT_RENDER = os.environ.get("STICKERME_PORTRAIT_RENDER", "1") == "1"
# Photo-edit route: edit the real photo (arms only), then animate the person's own face.
PHOTO_EDIT = os.environ.get("STICKERME_PHOTO_EDIT", "1") == "1"
# Whole-photo reaction edits avoid blending incompatible face/head geometries.
# LivePortrait is an explicit experimental opt-in, not the default photo path.
PHOTO_ANIMATION = os.environ.get("STICKERME_PHOTO_ANIMATION", "0") == "1"
LIVEPORTRAIT_DIR = ROOT / "runtime" / "liveportrait"
ENGINE_PYTHON = ROOT / "runtime" / "engine-env" / "Scripts" / "python.exe"
GESTURE_FLOOR = float(os.environ.get("STICKERME_GESTURE_FLOOR", "0.75"))
EXPRESSION_FLOOR = float(os.environ.get("STICKERME_EXPRESSION_FLOOR", "0.55"))
EXPRESSION_MIN = float(os.environ.get("STICKERME_EXPRESSION_MIN", "0.45"))
EXPRESSION_STRENGTH = float(os.environ.get("STICKERME_EXPRESSION_STRENGTH", "1.0"))


def ensure_directories() -> None:
    for directory in (DATA_DIR, PACKS_DIR, U2NET_HOME):
        directory.mkdir(parents=True, exist_ok=True)


def pack_dir(pack_id: str) -> Path:
    return PACKS_DIR / pack_id
