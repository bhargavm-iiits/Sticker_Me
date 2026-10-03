import concurrent.futures
import argparse
import hashlib
import json
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT / "runtime" / "comfyui"
MODELS = json.loads((ROOT / "workflows" / "models.json").read_text(encoding="utf-8"))


def download_model(spec: dict) -> dict:
    repository, filename = spec["repository"], spec["file"]
    folder = "unet" if filename.startswith("flux-2") else "text_encoders" if filename.startswith("Qwen") else "vae"
    expected_hash = spec["sha256"]
    destination = COMFY / "models" / folder / Path(filename).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    actual_hash = None
    if destination.exists():
        with destination.open("rb") as source:
            actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
    if actual_hash == expected_hash:
        print(f"Verified {destination.name}", flush=True)
    else:
        partial = destination.with_suffix(destination.suffix + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        url = f"https://huggingface.co/{repository}/resolve/{spec['revision']}/{filename}?download=true&timestamp={time.time_ns()}"
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with requests.get(url, headers=headers, stream=True, timeout=(60, 180)) as download:
            download.raise_for_status()
            mode = "ab" if offset and download.status_code == 206 else "wb"
            print(f"Downloading {destination.name}", flush=True)
            with partial.open(mode) as output:
                for chunk in download.iter_content(8 * 1024 * 1024):
                    output.write(chunk)
        with partial.open("rb") as source:
            actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(f"Hash mismatch for {filename}; remove its .part file and retry")
        partial.replace(destination)
        print(f"Downloaded and verified {destination.name}", flush=True)
    return spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--precision", choices=["Q4_K_M", "Q6_K", "Q8_0"])
    args = parser.parse_args()
    models = [spec.copy() for spec in MODELS]
    if args.precision:
        variants = json.loads((ROOT / "workflows" / "model-precisions.json").read_text())
        models[0].update(variants[args.precision])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        manifests = list(pool.map(download_model, models))
    destination = ROOT / "runtime" / "engine-models.json"
    destination.write_text(json.dumps(manifests, indent=2), encoding="utf-8")
    print("Engine model downloads complete", flush=True)


if __name__ == "__main__":
    main()
