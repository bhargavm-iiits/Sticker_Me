from PIL import Image, ImageDraw
from sqlalchemy import create_engine, inspect, text

from backend.app import db
from backend.app.imaging import remove_cartoon_background
from backend.app.migrations import upgrade


def test_migrate_legacy_database_preserves_ready_pack(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE packs (id VARCHAR(36) PRIMARY KEY, name VARCHAR(80), language VARCHAR(16), status VARCHAR(20), mode VARCHAR(20), error TEXT, created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("CREATE TABLE stickers (id VARCHAR(36) PRIMARY KEY, pack_id VARCHAR(36), position INTEGER, intent VARCHAR(32), emoji VARCHAR(16), caption VARCHAR(80))"))
        connection.execute(text("INSERT INTO packs VALUES ('old-pack','Old pack','en','ready','photo_cutout',NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO stickers VALUES ('old-sticker','old-pack',0,'greeting','wave','Hi!')"))
    upgrade(engine, db.Base.metadata)
    upgrade(engine, db.Base.metadata)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM packs WHERE id='old-pack'")) == "Old pack"
        assert connection.scalar(text("SELECT status FROM stickers WHERE id='old-sticker'")) == "ready"
        assert "job_attempts" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT cutout_path FROM stickers WHERE id='old-sticker'")) == "cutout.png"
        assert connection.scalar(text("SELECT count(*) FROM schema_migrations")) == 4
    engine.dispose()


def test_cartoon_mask_keeps_interior_white_and_all_hands():
    image = Image.new("RGB", (512, 512), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 80, 400, 450), fill="red", outline="black", width=4)
    draw.ellipse((140, 160, 220, 240), fill="white", outline="black", width=4)
    output = remove_cartoon_background(image)
    alpha = output.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0
    assert alpha.getpixel((180, 200)) == 255
    assert alpha.getpixel((110, 100)) == 255


def test_version_two_migration_preserves_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v2.sqlite3').as_posix()}")
    db.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, columns in {"stickers": ["likeness_score", "likeness_note"], "job_attempts": ["stage", "candidate", "likeness_score"]}.items():
            for column in columns:
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        connection.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO schema_migrations VALUES (1),(2)"))
        connection.execute(text("INSERT INTO packs (id,name,language,status,mode,style,tone,approved,created_at,updated_at) VALUES ('saved','Saved','en','ready','cartoon','cartoon','warm',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    upgrade(engine, db.Base.metadata)
    upgrade(engine, db.Base.metadata)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM packs WHERE id='saved'")) == "Saved"
        assert "likeness_score" in {c["name"] for c in inspect(connection).get_columns("stickers")}
        assert {"stage", "candidate"} <= {c["name"] for c in inspect(connection).get_columns("job_attempts")}
        assert connection.scalar(text("SELECT count(*) FROM schema_migrations")) == 4
    engine.dispose()


def test_engine_copy_cleanup_is_scoped_to_owned_pack_and_attempt(tmp_path, monkeypatch):
    from uuid import uuid4
    from backend.app import cleanup

    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    pack_id, attempt_id, unrelated = str(uuid4()), str(uuid4()), str(uuid4())
    directory = tmp_path / "runtime" / "comfyui"
    inputs, outputs = directory / "input" / "StickerMe", directory / "output" / "StickerMe"
    inputs.mkdir(parents=True)
    outputs.mkdir(parents=True)
    for name in (pack_id, unrelated):
        (inputs / f"{name}.png").write_bytes(b"reference")
        (inputs / f"{name}-face.png").write_bytes(b"face")
        (inputs / f"{name}-body.png").write_bytes(b"body")
    for name in (attempt_id, unrelated):
        (outputs / f"{name}_00001_.png").write_bytes(b"artwork")
        (inputs / f"{name}-crop.png").write_bytes(b"crop")
    cleanup.engine_assets(pack_id, [attempt_id])
    assert not (inputs / f"{pack_id}.png").exists()
    assert not (outputs / f"{attempt_id}_00001_.png").exists()
    assert (inputs / f"{unrelated}.png").exists()
    assert (outputs / f"{unrelated}_00001_.png").exists()
    assert not (inputs / f"{pack_id}-face.png").exists()
    assert not (inputs / f"{pack_id}-body.png").exists()
    assert not (inputs / f"{attempt_id}-crop.png").exists()
    assert (inputs / f"{unrelated}-face.png").exists()
    assert (inputs / f"{unrelated}-crop.png").exists()
