"""Hash the actual installed model files once per file revision."""
import hashlib
from functools import lru_cache
from pathlib import Path
from . import config


@lru_cache(maxsize=16)
def file_hash(path: str, size: int, modified: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def models(graph: dict) -> list[dict]:
    root = config.ROOT / "runtime" / "comfyui" / "models"
    rows = []
    for node in graph.values():
        for key, folders in (("unet_name", ("unet", "diffusion_models")), ("clip_name", ("clip", "text_encoders")), ("vae_name", ("vae",))):
            name = node.get("inputs", {}).get(key)
            if not isinstance(name, str):
                continue
            path = next((root / folder / name for folder in folders if (root / folder / name).is_file()), None)
            if path is None:
                rows.append({"file": name, "sha256": None, "state": "unavailable"})
            else:
                stat = path.stat()
                rows.append({"file": name, "bytes": stat.st_size, "sha256": file_hash(str(path), stat.st_size, stat.st_mtime_ns)})
    return rows
