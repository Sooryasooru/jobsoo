"""Application tracking models (schema only; application *workflows* land in
Phase 2). Phase 1 creates/reads rows for prepared jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedUpdatedAtMixin, str_uuid


class Application(Base, CreatedUpdatedAtMixin):
    """A candidate's application for one job.

    Application status is deliberately separate from job availability
    (`jobs.is_active`/`jobs.is_expired`).

    Future compatibility: `attempt_no` is present from Phase 1 so contract-driven
    multiple applications can be inserted without a data migration; today all
    rows use the default 1, hence at most one record per (user, job).
    """

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="attempt_at_least_one"),
        UniqueConstraint(
            "user_id", "job_id", "attempt_no", name="uq_applications_user_job_attempt"
        ),
        Index("ix_applications_user_job", "user_id", "job_id"),
    )

    id: Mapped[str] = str_uuid()

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    attempt_no: Mapped[int] = mapped_column(nullable=False, default=1)
    tailored_resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("tailored_resumes.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="prepared")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationEvent(Base, CreatedUpdatedAtMixin):
    """Append-only audit event for an application (Phase 2 will extend)."""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint("length(event_type) > 0", name="event_type_not_empty"),
        Index("ix_application_events_application_id", "application_id"),
    )

    id: Mapped[str] = str_uuid()
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application] = relationship(back_populates="events")
