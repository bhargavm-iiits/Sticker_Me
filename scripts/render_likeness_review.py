"""Validate/export six completed benchmark previews through sticker composition."""
import argparse
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from backend.app import config, imaging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--realistic-result", type=Path, required=True)
    parser.add_argument("--cartoon-result", type=Path, required=True)
    args = parser.parse_args()
    destination = config.ROOT / "runtime" / "likeness-review"
    destination.mkdir(parents=True, exist_ok=True)
    imaging.U2NET_HOME = config.ROOT / "runtime" / "models"
    sheet = Image.new("RGB", (1024, 576), "#ede8f5")
    draw = ImageDraw.Draw(sheet)
    results = []
    captions = {"greeting": "Hi!", "laughter": "LOL", "surprise": "OMG!"}
    with zipfile.ZipFile(destination / "sticker-previews.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row, (style, path) in enumerate((("realistic", args.realistic_result), ("cartoon", args.cartoon_result))):
            record = json.loads(path.read_text())["results"][-1]
            with Image.open(Path(record["results"][0]["path"]).parent / "face.png") as face:
                sheet.paste(face.resize((256, 256)), (0, row * 288))
            draw.text((12, row * 288 + 263), f"Reference / {style}", fill="black")
            for index, item in enumerate(record["results"], 1):
                with Image.open(item["path"]) as source:
                    cutout = imaging.remove_background(source.convert("RGB"))
                sticker = imaging.compose_sticker(cutout, captions[item["intent"]], "en")
                assert sticker.size == (512, 512)
                assert sticker.getchannel("A").getextrema() == (0, 255)
                stem = f"{style}-{item['intent']}"
                png = destination / f"{stem}.png"
                imaging.save_png(sticker, png)
                webp = imaging.encode_webp(sticker, 100 * 1024)
                archive.write(png, f"{style}/{item['intent']}.png")
                archive.writestr(f"{style}/{item['intent']}.webp", webp)
                preview = sticker.resize((256, 256), Image.Resampling.LANCZOS)
                sheet.paste(preview, (index * 256, row * 288), preview)
                draw.text((index * 256 + 12, row * 288 + 263), item["intent"], fill="black")
                results.append({"style": style, "intent": item["intent"], "artwork_likeness_score": item["likeness_score"], "webp_bytes": len(webp), "png": str(png)})
        # The comparison sheet includes the source face and stays local. Only
        # the six derived sticker previews and this metadata enter the ZIP.
        archive.writestr("preview-metadata.json", json.dumps(results, indent=2))
    imaging.save_png(sheet, destination / "contact-sheet.png")
    (destination / "result.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"previews": len(results), "zip": str(destination / "sticker-previews.zip"), "contact_sheet": str(destination / "contact-sheet.png"), "max_webp_bytes": max(r["webp_bytes"] for r in results)}, indent=2))


if __name__ == "__main__":
    main()
