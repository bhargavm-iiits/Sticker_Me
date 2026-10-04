"""Compare saved expression drivers at three strengths without new diffusion jobs.

Drivers are aligned 512px face crops. Use a JSON mapping such as
{"greeting": "greeting-driver.png", "laughter": "laughter-driver.png"}.
Paths resolve relative to the mapping file. This is evaluation, not automatic approval.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw
from backend.app import portrait, imaging, likeness, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Original photograph or saved canvas")
    parser.add_argument("--drivers", required=True, type=Path)
    parser.add_argument("--strengths", nargs="+", type=float, default=[.7, 1., 1.3])
    parser.add_argument("--output", type=Path, default=config.ROOT / "runtime" / "plan1-expression-review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with Image.open(args.source) as image:
        source = image.convert("RGB")
    crop = portrait.driver_crop(source)
    source_path = args.output / "original-crop.png"
    imaging.save_png(crop, source_path)
    reference = likeness.embedding(crop)
    mapping = json.loads(args.drivers.read_text(encoding="utf-8"))
    rows, tiles = [], [(crop, "Original photo")]
    try:
        for intent, path in mapping.items():
            path = (args.drivers.parent / path).resolve()
            for strength in args.strengths:
                output = args.output / f"{intent}-{strength:.2f}.png"
                job = {"source": str(source_path), "reference": str(source_path), "driver": str(path), "output": str(output), "multiplier": strength}
                began = time.monotonic()
                result = portrait.run([job], args.output)[0]
                tiles.append((result, f"{intent} / {strength:.2f}"))
                rows.append({"intent": intent, "strength": strength, "seconds": round(time.monotonic() - began, 2),
                             "score": likeness.likeness(reference, result) if reference is not None else None,
                             "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                             "driver_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "review": "Compare identity, eye/mouth expression, teeth and artifacts manually"})
                print(json.dumps(rows[-1]), flush=True)
    finally:
        portrait.close_runner()
    columns = 4
    sheet = Image.new("RGB", (256 * columns, 286 * ((len(tiles) + columns - 1) // columns)), "#ede8f5")
    for index, (tile, label) in enumerate(tiles):
        x, y = index % columns * 256, index // columns * 286
        sheet.paste(tile.resize((256, 256)), (x, y))
        ImageDraw.Draw(sheet).text((x + 6, y + 265), label, fill="black")
    imaging.save_png(sheet, args.output / "contact-sheet.png")
    (args.output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
