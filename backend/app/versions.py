"""Immutable snapshots for generation, caption/mask edits and restore."""
import json
import shutil
from uuid import uuid4

from sqlalchemy import select

from . import config
from .db import StickerVersion

FIELDS = ("artwork_path", "cutout_path", "caption", "seed", "likeness_score", "likeness_note",
          "quality_status", "quality_report", "expression_intensity")


def snapshot(session, sticker):
    directory = config.pack_dir(sticker.pack_id)
    image = directory / f"{sticker.id}.png"
    if not image.is_file():
        return
    existing = session.scalar(select(StickerVersion).where(
        StickerVersion.sticker_id == sticker.id, StickerVersion.revision == sticker.revision))
    if existing:
        return
    filename = f"{sticker.id}-version-{sticker.revision}-{uuid4().hex}.png"
    shutil.copyfile(image, directory / filename)
    session.add(StickerVersion(id=str(uuid4()), sticker_id=sticker.id, revision=sticker.revision,
                              image_path=filename, snapshot=json.dumps({key: getattr(sticker, key) for key in FIELDS})))
