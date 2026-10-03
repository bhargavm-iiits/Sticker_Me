"""Download official pinned OpenCV weights; verify size and LFS SHA-256."""
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "runtime" / "models" / "face"
    directory.mkdir(parents=True, exist_ok=True)
    specs = json.loads((ROOT / "workflows" / "face-models.json").read_text())
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for spec in specs:
            destination = directory / spec["file"]
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == spec["sha256"]:
                print(f"Verified {spec['file']}", flush=True)
                continue
            url = f"https://media.githubusercontent.com/media/{spec['repository']}/{spec['revision']}/{spec['path']}"
            partial = destination.with_suffix(".onnx.part")
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes(): output.write(chunk)
            if partial.stat().st_size != spec["bytes"] or hashlib.sha256(partial.read_bytes()).hexdigest() != spec["sha256"]:
                raise RuntimeError(f"Invalid face model download: {spec['file']}")
            partial.replace(destination)
            print(f"Downloaded and verified {spec['file']}", flush=True)
    (directory / "installed.json").write_text(json.dumps(specs, indent=2))


if __name__ == "__main__":
    main()
