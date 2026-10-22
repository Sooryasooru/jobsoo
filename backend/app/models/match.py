"""JobMatch model: deterministic per-user job match results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import str_uuid


class JobMatch(Base):
    """Explainable match between one user and one job.

    Scores are computed by deterministic Python (app/scoring) and stored with
    components, so every result is auditable. Scores are never hired/interview
    probabilities. Missing data is represented with `unknown_requirements`
    rather than as a confirmed mismatch, and no tier automatically hides jobs.
    """

    __tablename__ = "job_matches"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="score_in_range"),
        CheckConstraint("tier IN ('strong','good','stretch','long_shot')", name="valid_tier"),
        CheckConstraint(
            "experience_gap_years IS NULL OR experience_gap_years >= 0",
            name="non_negative_experience_gap",
        ),
        UniqueConstraint("user_id", "job_id", name="uq_job_matches_user_job"),
        Index("ix_job_matches_user_score", "user_id", "score"),
    )

    id: Mapped[str] = str_uuid()

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    score: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(40), nullable=False)
    explanation: Mapped[str] = mapped_column(String(2000), nullable=False, default="")

    score_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    matched_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unknown_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    hard_blocker_warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    unknown_requirements: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    experience_gap_years: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=5, scale=1), nullable=True
    )
    scoring_rules_version: Mapped[str] = mapped_column(String(30), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
