"""Original resume model.

Tailored resumes deliberately live in `tailored_resumes` so originals are
never overwritten or mutated (Phase 1 requirement B).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ResumeKind
from app.models.mixins import CreatedUpdatedAtMixin, str_uuid


class Resume(Base, CreatedUpdatedAtMixin):
    """An original uploaded CV document (immutable once created)."""

    __tablename__ = "resumes"
    __table_args__ = (
        CheckConstraint("kind = 'original'", name="original_kind_only"),
        CheckConstraint("file_size_bytes > 0", name="positive_file_size"),
    )

    id: Mapped[str] = str_uuid()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=ResumeKind.ORIGINAL.value)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf|docx|md|txt
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)  # storage ref, not public
    file_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    parsed_content: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        # Structured parse result: contact, sections, experiences, skills, ...
    )
    parse_notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    resumes_tailored: Mapped[list[TailoredResume]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class TailoredResume(Base, CreatedUpdatedAtMixin):
    """A tailored CV version for one job, with explicit approval status."""

    __tablename__ = "tailored_resumes"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_at_least_one"),
        CheckConstraint(
            "approval_status IN ('draft','pending_review','approved','rejected')",
            name="valid_approval_status",
        ),
        # The document is not final until explicitly approved.
        CheckConstraint(
            "(approval_status = 'approved') OR (final_pdf_path IS NULL)",
            name="pdf_only_after_approval",
        ),
        UniqueConstraint("resume_id", "job_id", "version", name="uq_tailored_resume_version"),
    )

    id: Mapped[str] = str_uuid()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[str] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Full proposed document content (headings, bullets with evidence refs).
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    change_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # list of changed sections/bullets, per docs
    unsupported_claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    final_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    resume: Mapped[Resume] = relationship(back_populates="resumes_tailored")
