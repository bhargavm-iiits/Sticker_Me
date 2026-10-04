import json
import os
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
os.environ["STICKERME_DATA_DIR"] = str(ROOT / "runtime" / "gpu-smoke")

from PIL import Image, ImageDraw
from skimage.data import astronaut
from sqlalchemy.orm import Session

from backend.app import db
from backend.app.catalog import INTENTS, PREVIEW_INTENTS
from backend.app.comfy import ComfyEngine
from backend.app.config import pack_dir
from backend.app.imaging import save_png


def main():
    db.init_db()
    pack_id, job_id = str(uuid4()), str(uuid4())
    selected = [intent for intent in INTENTS if intent.key in PREVIEW_INTENTS]
    with Session(db.engine) as session:
        pack = db.Pack(id=pack_id, name="GPU reference-edit benchmark", language="en", mode="cartoon")
        pack.jobs.append(db.Job(id=job_id, kind="preview", total=3))
        for position, intent in enumerate(selected):
            pack.stickers.append(db.Sticker(id=str(uuid4()), position=position, intent=intent.key, emoji=intent.emoji, caption=intent.english, seed=20261003 + position))
        session.add(pack)
        session.commit()
        stickers = [(sticker.id, sticker.intent, sticker.seed) for sticker in pack.stickers]
    directory = pack_dir(pack_id)
    save_png(Image.fromarray(astronaut()), directory / "reference.png")
    adapter = ComfyEngine(db.engine)
    results = []
    for sticker_id, intent, seed in stickers:
        started = time.monotonic()
        image = adapter.generate(job_id, sticker_id, pack_id, intent, "cartoon", "playful", seed, lambda: True)
        save_png(image, directory / f"{intent}.png")
        result = {"intent": intent, "seconds": round(time.monotonic() - started, 2), "path": str(directory / f"{intent}.png")}
        results.append(result)
        print(json.dumps(result), flush=True)
    sheet = Image.new("RGB", (512 * 4, 560), "#ede8f5")
    sheet.paste(Image.fromarray(astronaut()), (0, 0))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 525), "REFERENCE", fill="black")
    for index, result in enumerate(results, 1):
        with Image.open(result["path"]) as image:
            sheet.paste(image, (512 * index, 0))
        draw.text((512 * index + 12, 525), result["intent"], fill="black")
    save_png(sheet, directory / "contact-sheet.png")
    (ROOT / "runtime" / "gpu-smoke" / "result.json").write_text(json.dumps({"pack_id": pack_id, "results": results, "contact_sheet": str(directory / "contact-sheet.png")}, indent=2), encoding="utf-8")
    adapter.close()


if __name__ == "__main__":
    main()
