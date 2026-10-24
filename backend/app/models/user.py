"""User and candidate profile models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedUpdatedAtMixin, str_uuid


class User(Base, CreatedUpdatedAtMixin):
    """Application user.

    `password_hash` is an Argon2id hash (never plaintext). It is nullable so
    that Phase 1 development rows (e.g. `dev@example.com`) keep loading; such
    users simply cannot log in until they register again.
    """

    __tablename__ = "users"

    id: Mapped[str] = str_uuid()
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user_profile: Mapped[UserProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base, CreatedUpdatedAtMixin):
    """Opaque bearer session token for a user.

    Only the SHA-256 hash of the token is stored; the raw token exists solely
    in the client. Sessions expire after a fixed lifetime and are deleted on
    logout (single-token revocation scope).
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = str_uuid()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    user: Mapped[User] = relationship(back_populates="sessions")


class UserProfile(Base, CreatedUpdatedAtMixin):
    """Candidate profile: skills, experience, education, projects, preferences.

    Annex collections are JSONB (justified: heterogeneous, regularly extended
    candidate-provided data). Missing information is never treated as a
    negative signal by business logic; see docs/architecture.md.
    """

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint("professional_experience_years >= 0", name="non_negative_experience"),
        CheckConstraint(
            "expected_salary_min IS NULL OR expected_salary_min >= 0", name="non_negative_salary"
        ),
        UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    id: Mapped[str] = str_uuid()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    headline: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Self-declared professional experience (years). Supplemented by evidence
    # from parsed CVs (user_profiles does not invent experience).
    professional_experience_years: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=4, scale=1), nullable=True
    )

    skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    skill_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        # Map of skill name -> evidence source refs (resume section, project id, ...)
    )
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    certifications: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    projects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    experiences: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # Preferences
    preferred_locations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    remote_preference: Mapped[str] = mapped_column(
        String(20), nullable=False, default="any"
    )  # any | remote_only | onsite_only | hybrid
    expected_salary_min: Mapped[int | None] = mapped_column(nullable=True)
    expected_salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    user_rights: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )  # work authorization notes

    # Career dates used for contradiction checks (earliest known employment).
    career_start_date: Mapped[date | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="user_profile")
