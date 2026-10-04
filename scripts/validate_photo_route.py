"""Run the photo-edit route on one consented photo for every reaction, in an isolated data dir.

Example: python -m scripts.validate_photo_route --photo portrait.jpg --consent
Writes runtime/photo-route-check/<run>/: composed stickers, contact-sheet.png and result.json.
Ordinary packs are never touched. Submits only while the engine queue is idle.
"""
import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--consent", action="store_true", required=True)
    parser.add_argument("--style", default="realistic")
    parser.add_argument("--intents", nargs="+", default=None)
    args = parser.parse_args()
    run = ROOT / "runtime" / "photo-route-check" / uuid4().hex
    os.environ["STICKERME_DATA_DIR"] = str(run)
    # Import only after relocation, keeping application data untouched.
    from sqlalchemy.orm import Session
    from backend.app import config, db, imaging, likeness, worker
    from backend.app.catalog import INTENT_BY_KEY, INTENTS, PHOTO_ROUTE
    from backend.app.comfy import ComfyEngine

    imaging.U2NET_HOME = ROOT / "runtime" / "models"
    if args.style not in PHOTO_ROUTE:
        parser.error("Choose a photo-route style: " + ", ".join(sorted(PHOTO_ROUTE)))
    keys = args.intents or [intent.key for intent in INTENTS]
    db.init_db()
    adapter = ComfyEngine(db.engine)

    def wait_idle():
        while True:
            queue = adapter.request("GET", "/queue").json()
            if not queue.get("queue_running") and not queue.get("queue_pending"):
                return
            time.sleep(5)

    image = imaging.normalize_upload(args.photo.read_bytes())
    feature = likeness.embedding(image)
    if feature is None:
        raise ValueError("No usable face in the photo")
    canvas, face_clean = likeness.photo_references(image)
    pack_id, job_id = str(uuid4()), str(uuid4())
    with Session(db.engine) as session:
        pack = db.Pack(id=pack_id, name="Photo route check", language="en", mode="cartoon", style=args.style, tone="playful", status="processing")
        pack.jobs.append(db.Job(id=job_id, kind="benchmark", state="running", total=len(keys)))
        for index, key in enumerate(keys):
            intent = INTENT_BY_KEY[key]
            pack.stickers.append(db.Sticker(id=str(uuid4()), position=index, intent=key, emoji=intent.emoji, caption=intent.english, seed=20261003 + index))
        session.add(pack)
        session.commit()
        targets = [(s.id, s.intent, s.seed, s.caption) for s in pack.stickers]
    directory = config.pack_dir(pack_id)
    for name, source in (("reference.png", image), ("face.png", imaging.face_reference(image)), ("body.png", imaging.body_reference(image)), ("canvas.png", canvas), ("face-clean.png", face_clean)):
        imaging.save_png(source, directory / name)
    likeness.save_embedding(feature, directory / "face-embedding.npy")

    columns = 5
    sheet = Image.new("RGB", (256 * columns, 286 * ((len(targets) + columns) // columns)), "#ede8f5")
    draw = ImageDraw.Draw(sheet)
    sheet.paste(face_clean.resize((256, 256)), (0, 0))
    draw.text((10, 262), "YOUR PHOTO", fill="black")
    results, started = [], time.monotonic()
    try:
        for index, (sticker_id, key, seed, caption) in enumerate(targets, 1):
            wait_idle()
            began = time.monotonic()
            art, score, chosen, note = worker.generate_photo(adapter, job_id, sticker_id, pack_id, key, args.style, "playful", seed, 1)
            imaging.save_png(art, directory / f"{key}-art.png")
            sticker = imaging.compose_sticker(imaging.person_cutout(art), caption, "en")
            imaging.save_png(sticker, directory / f"{key}.png")
            tile = Image.new("RGB", sticker.size, "#d9d0ea")
            tile.paste(sticker, mask=sticker.getchannel("A"))
            x, y = index % columns * 256, index // columns * 286
            sheet.paste(tile.resize((256, 256), Image.Resampling.LANCZOS), (x, y))
            draw.text((x + 10, y + 262), f"{key}: {score:.2f}" if score is not None else f"{key}: check", fill="black")
            from backend.app import quality
            row = {"intent": key, "score": score, "note": note, "seconds": round(time.monotonic() - began, 1), "seed": chosen,
                   "route": "original-photo-face-v3" if config.PHOTO_ANIMATION else "coherent-photo-edit-v4", "renderer": "straight-alpha-border-v3", "tone": "playful",
                   "quality": quality.evaluate(art, score, key, args.style, note)}
            results.append(row)
            print(json.dumps(row), flush=True)
            imaging.save_png(sheet, run / "contact-sheet.png")
            (run / "result.json").write_text(json.dumps({"style": args.style, "results": results}, indent=2), encoding="utf-8")
    finally:
        adapter.close()
    print(json.dumps({"total_seconds": round(time.monotonic() - started, 1), "contact_sheet": str(run / "contact-sheet.png")}), flush=True)


if __name__ == "__main__":
    main()
