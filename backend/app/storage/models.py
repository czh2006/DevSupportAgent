from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text,Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base


def generate_session_id() -> str:
    return str(uuid4())


def current_utc_time() -> datetime:
    return datetime.now(timezone.utc)


class TroubleshootingSession(Base):
    __tablename__ = "troubleshooting_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_session_id,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    problem_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="created",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=current_utc_time,
    )

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("troubleshooting_sessions.id"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=current_utc_time,
    )

class TroubleshootingContext(Base):
    __tablename__ = "troubleshooting_contexts"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("troubleshooting_sessions.id"),
        primary_key=True,
    )

    api_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    environment: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    http_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=current_utc_time,
        onupdate=current_utc_time,
    )