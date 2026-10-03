from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from .config import DB_PATH, ensure_directories


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    mode: Mapped[str] = mapped_column(String(20), default="photo_cutout")
    style: Mapped[str] = mapped_column(String(20), default="cartoon")
    tone: Mapped[str] = mapped_column(String(20), default="playful")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    design_path: Mapped[str | None] = mapped_column(Text)
    request_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    stickers: Mapped[list["Sticker"]] = relationship(back_populates="pack", cascade="all, delete-orphan", order_by="Sticker.position")
    jobs: Mapped[list["Job"]] = relationship(back_populates="pack", cascade="all, delete-orphan")


class Sticker(Base):
    __tablename__ = "stickers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pack_id: Mapped[str] = mapped_column(ForeignKey("packs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    intent: Mapped[str] = mapped_column(String(32))
    emoji: Mapped[str] = mapped_column(String(16))
    caption: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    artwork_path: Mapped[str | None] = mapped_column(Text)
    cutout_path: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    likeness_score: Mapped[float | None] = mapped_column(Float)
    likeness_note: Mapped[str | None] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(String(20), default="needs_review")
    quality_report: Mapped[str] = mapped_column(Text, default="{}")
    expression_intensity: Mapped[float] = mapped_column(Float, default=1.0)
    pack: Mapped[Pack] = relationship(back_populates="stickers")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pack_id: Mapped[str] = mapped_column(ForeignKey("packs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=12)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    pack: Mapped[Pack] = relationship(back_populates="jobs")


class StickerVersion(Base):
    __tablename__ = "sticker_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sticker_id: Mapped[str] = mapped_column(ForeignKey("stickers.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sticker_id: Mapped[str] = mapped_column(ForeignKey("stickers.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(20), default="prepared")
    stage: Mapped[str] = mapped_column(String(16), default="pose")
    candidate: Mapped[int] = mapped_column(Integer, default=0)
    likeness_score: Mapped[float | None] = mapped_column(Float)
    prompt_id: Mapped[str] = mapped_column(String(36), unique=True)
    workflow: Mapped[str] = mapped_column(Text)
    reference_hash: Mapped[str] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


ensure_directories()
engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def configure_sqlite(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_db() -> None:
    from .migrations import upgrade

    upgrade(engine, Base.metadata)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
