from sqlalchemy import inspect, text


ADDITIONS = {
    "packs": {
        "style": "VARCHAR(20) NOT NULL DEFAULT 'cartoon'",
        "tone": "VARCHAR(20) NOT NULL DEFAULT 'playful'",
        "approved": "BOOLEAN NOT NULL DEFAULT 0",
        "request_key": "VARCHAR(64)",
        "request_hash": "VARCHAR(64)",
    },
    "stickers": {
        "status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
        "revision": "INTEGER NOT NULL DEFAULT 0",
        "artwork_path": "TEXT",
        "cutout_path": "TEXT",
        "seed": "INTEGER NOT NULL DEFAULT 0",
    },
    "jobs": {
        "total": "INTEGER NOT NULL DEFAULT 12",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "cancel_requested": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


def upgrade(engine, metadata) -> None:
    with engine.begin() as connection:
        connection.execute(text("BEGIN IMMEDIATE"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
        if not connection.scalar(text("SELECT 1 FROM schema_migrations WHERE version=1")):
            existing = set(inspect(connection).get_table_names())
            for table, additions in ADDITIONS.items():
                if table not in existing:
                    continue
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                for name, definition in additions.items():
                    if name not in columns:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            metadata.create_all(connection)
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS packs_request_key ON packs(request_key)"))
            connection.execute(text("UPDATE stickers SET status='ready' WHERE pack_id IN (SELECT id FROM packs WHERE status='ready')"))
            connection.execute(text("INSERT INTO schema_migrations(version) VALUES (1)"))
        if not connection.scalar(text("SELECT 1 FROM schema_migrations WHERE version=2")):
            connection.execute(text("UPDATE stickers SET cutout_path='cutout.png' WHERE cutout_path IS NULL AND pack_id IN (SELECT id FROM packs WHERE mode='photo_cutout' AND status='ready')"))
            connection.execute(text("INSERT INTO schema_migrations(version) VALUES (2)"))
        if not connection.scalar(text("SELECT 1 FROM schema_migrations WHERE version=3")):
            additions = {
                "stickers": {"likeness_score": "FLOAT", "likeness_note": "TEXT"},
                "job_attempts": {"stage": "VARCHAR(16) NOT NULL DEFAULT 'pose'", "candidate": "INTEGER NOT NULL DEFAULT 0", "likeness_score": "FLOAT"},
            }
            for table, fields in additions.items():
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                for name, definition in fields.items():
                    if name not in columns:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            connection.execute(text("INSERT INTO schema_migrations(version) VALUES (3)"))
        if not connection.scalar(text("SELECT 1 FROM schema_migrations WHERE version=4")):
            additions = {
                "packs": {"design_path": "TEXT"},
                "stickers": {
                    "quality_status": "VARCHAR(20) NOT NULL DEFAULT 'legacy'",
                    "quality_report": "TEXT NOT NULL DEFAULT '{}'",
                    "expression_intensity": "FLOAT NOT NULL DEFAULT 1.0",
                },
            }
            for table, fields in additions.items():
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                for name, definition in fields.items():
                    if name not in columns:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            metadata.create_all(connection)
            connection.execute(text("INSERT INTO schema_migrations(version) VALUES (4)"))
