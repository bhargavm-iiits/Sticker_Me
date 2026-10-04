import io
import json
import os
import time
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.environ["STICKERME_DATA_DIR"] = str(root / "runtime" / "smoke")

from fastapi.testclient import TestClient
from PIL import Image
from skimage.data import astronaut

from backend.app import imaging
from backend.app.main import app
from backend.app.worker import run_once
from backend.app import db
from sqlalchemy.orm import Session
from uuid import uuid4

imaging.U2NET_HOME = root / "runtime" / "models"


def main() -> None:
    photo = Image.fromarray(astronaut())
    upload = io.BytesIO()
    photo.save(upload, format="PNG")
    started = time.perf_counter()
    with TestClient(app) as client:
        from backend.app.catalog import INTENTS
        from backend.app.config import pack_dir

        pack_id = str(uuid4())
        imaging.save_png(photo, pack_dir(pack_id) / "reference.png")
        with Session(db.engine) as session:
            pack = db.Pack(id=pack_id, name="Legacy cutout smoke test", language="en", mode="photo_cutout", approved=True)
            for position, intent in enumerate(INTENTS):
                pack.stickers.append(db.Sticker(id=str(uuid4()), position=position, intent=intent.key, emoji=intent.emoji, caption=intent.english))
            pack.jobs.append(db.Job(id=str(uuid4()), kind="cutout_pack"))
            session.add(pack)
            session.commit()
        if not run_once():
            raise RuntimeError("Worker did not claim the smoke-test job")
        status = client.get(f"/api/packs/{pack_id}").json()
        if status["status"] != "ready":
            raise RuntimeError(status.get("error") or "Pack did not complete")
        export = client.get(f"/api/packs/{pack_id}/export")
        export.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            sticker_count = len([name for name in archive.namelist() if name.startswith("whatsapp/") and name.endswith(".webp")])
        print(json.dumps({"mode": "photo_cutout", "stickers": sticker_count, "zip_bytes": len(export.content), "elapsed_seconds": round(time.perf_counter() - started, 1), "pack_id": pack_id}, indent=2))


if __name__ == "__main__":
    main()
