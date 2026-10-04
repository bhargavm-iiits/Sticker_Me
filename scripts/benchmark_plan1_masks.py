"""Compare segmentation and chat-size composition on identical saved artwork."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw
from backend.app import imaging
from backend.app.quality import mask_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", nargs="+", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["u2netp", "isnet-general-use"])
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "plan1-mask-review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    imaging.U2NET_HOME = ROOT / "runtime" / "models"
    rows, tiles = [], []
    for index, path in enumerate(args.images):
        with Image.open(path) as source:
            source = source.convert("RGB")
        for model in args.models:
            began = time.monotonic()
            cutout = imaging.remove_background(source, model)
            name = f"{index}-{model}"
            imaging.save_png(cutout, args.output / f"{name}-cutout.png")
            imaging.save_png(cutout.getchannel("A"), args.output / f"{name}-alpha.png")
            for size in (128, 256, 512):
                sticker = imaging.compose_sticker(cutout, "LOL", "en").resize((size, size), Image.Resampling.LANCZOS)
                imaging.save_png(sticker, args.output / f"{name}-{size}.png")
            for background in ("#ffffff", "#222237", "#47b997"):
                tile = Image.new("RGB", (256, 286), background)
                sticker = imaging.compose_sticker(cutout, "LOL", "en").resize((256, 256), Image.Resampling.LANCZOS)
                tile.paste(sticker, (0, 0), sticker)
                ImageDraw.Draw(tile).text((5, 264), name, fill="#777777")
                tiles.append(tile)
            rows.append({"input": str(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "model": model, "seconds": round(time.monotonic() - began, 2),
                         "process_rss_mib": round(psutil.Process().memory_info().rss / 1024**2, 1),
                         "mask": mask_report(cutout)})
            print(json.dumps(rows[-1]), flush=True)
    sheet = Image.new("RGB", (256 * 3, 286 * ((len(tiles) + 2) // 3)), "white")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (index % 3 * 256, index // 3 * 286))
    imaging.save_png(sheet, args.output / "contact-sheet.png")
    (args.output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
