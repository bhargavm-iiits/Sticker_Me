"""Download the pinned LivePortrait network code and weights into runtime/liveportrait.

Only the MIT-licensed networks are fetched. InsightFace detection models are not
downloaded; StickerMe crops faces with its own YuNet detector.
"""
import hashlib
import json
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "workflows" / "liveportrait.json").read_text(encoding="utf-8"))
DESTINATION = ROOT / "runtime" / "liveportrait"


def fetch(url: str, destination: Path, expected: str | None = None) -> None:
    if destination.exists() and expected:
        with destination.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == expected:
                print(f"Verified {destination.name}", flush=True)
                return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with requests.get(url, stream=True, timeout=(60, 180)) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_content(8 * 1024 * 1024):
                output.write(chunk)
    if expected:
        with partial.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Hash mismatch for {destination.name}")
    partial.replace(destination)
    print(f"Downloaded {destination.relative_to(ROOT)}", flush=True)


def main() -> None:
    code = MANIFEST["code"]
    for path in code["files"]:
        fetch(f"https://raw.githubusercontent.com/{code['repository']}/{code['revision']}/{path}", DESTINATION / path)
    weights = MANIFEST["weights"]
    for item in weights["files"]:
        url = f"https://huggingface.co/{weights['repository']}/resolve/{weights['revision']}/{item['file']}?download=true"
        fetch(url, DESTINATION / "weights" / Path(item["file"]).name, item["sha256"])
    (DESTINATION / "installed.json").write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    print("LivePortrait installed", flush=True)


if __name__ == "__main__":
    main()
