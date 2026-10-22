"""Job listing and extracted requirement models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import JobSource
from app.models.mixins import CreatedUpdatedAtMixin, str_uuid


class Job(Base, CreatedUpdatedAtMixin):
    """A normalized job listing from any connector.

    - Availability (`is_active`, `is_expired`) is tracked here, separate from
      application state (which lives in `applications`).
    - Deduplication keys: (source, source_job_id), then canonical URL.
    - Missing optional data is stored as SQL NULL, never invented values.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="non_negative_salary_min"),
        CheckConstraint(
            "salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min",
            name="salary_max_gte_min",
        ),
        CheckConstraint("is_remote IN (true, false)", name="valid_is_remote"),
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_source_job_id"),
        Index("ix_jobs_canonical_url", "canonical_url", unique=True),
        Index("ix_jobs_source_posted_at", "source", "posted_at"),
        Index(
            "ix_jobs_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_jobs_company_trgm",
            "company",
            postgresql_using="gin",
            postgresql_ops={"company": "gin_trgm_ops"},
        ),
        Index("ix_jobs_is_active", "is_active"),
    )

    id: Mapped[str] = str_uuid()

    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default=JobSource.ADZUNA.value, index=True
    )
    source_job_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Ingestion bookkeeping
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(nullable=True, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(nullable=True, server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Availability (separate from application status)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_expired: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Content (all optional — never invented)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. full_time
    salary_min: Mapped[float | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_remote: Mapped[bool | None] = mapped_column(nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # remote | hybrid | onsite | unknown

    # Description-similarity duplicate *flags* (not auto-merged):
    # [{source, source_job_id, similarity: 0..1, flagged_at}]
    duplicate_flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    requirements_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    possible_duplicate_source_ids: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobRequirement(Base, CreatedUpdatedAtMixin):
    """A structured requirement extracted from a job description.

    Rows are produced by the AI extraction service, but each row is fully
    validated before persistence. Every field allows NULL/unknown: extraction
    records what the description states, nothing more.
    """

    __tablename__ = "job_requirements"
    __table_args__ = (
        CheckConstraint("min_years IS NULL OR min_years >= 0", name="non_negative_min_years"),
        CheckConstraint(
            "is_required IN (true,false) AND is_hard_blocker IN (true,false)",
            name="requirement_flags_present",
        ),
        UniqueConstraint("job_id", "category", "text", name="uq_job_requirement_text"),
        Index("ix_job_requirements_job_id", "job_id"),
    )

    id: Mapped[str] = str_uuid()
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_required: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_hard_blocker: Mapped[bool] = mapped_column(nullable=False, default=False)
    min_years: Mapped[float | None] = mapped_column(Numeric(precision=4, scale=1), nullable=True)

    # Extra provenance: extraction model version, confidence, source quote.
    extraction_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    job: Mapped[Job] = relationship(back_populates="requirements")
