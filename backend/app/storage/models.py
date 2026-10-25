from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, String, Text
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