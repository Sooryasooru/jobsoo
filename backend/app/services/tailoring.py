"""Approval workflow service for tailored CVs.

Lifecycle: draft -> pending_review -> approved|rejected. Approval is an
explicit user action; PDF export happens only after approval. Originals are
never touched, and each (resume, job) gets numbered, append-only versions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobRequirement, Resume, TailoredResume, User
from app.schemas.tailoring import TailoredContent
from app.tailoring.generate import generate_tailored_content, next_version
from app.tailoring.pdf import export_pdf

logger = structlog.get_logger(__name__)


class TailoringError(ValueError):
    """User-safe error for tailoring workflow violations."""


def _safe_id(value: str) -> str | None:
    """Return the value unchanged when it is a valid UUID, else None.

    Keeps malformed ids from reaching Postgres as
    `invalid input syntax for type uuid` (an unhandled 500).
    """
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return str(value)


def _get_owned(session: Session, model: type, row_id: str, user: User) -> Any:
    safe_id = _safe_id(row_id)
    row = session.get(model, safe_id) if safe_id else None
    if row is None:
        raise TailoringError(f"{model.__name__} not found")
    # Ownership applies only to per-user models; jobs are shared listings.
    has_owner = "user_id" in model.__table__.columns
    if has_owner and row.user_id != user.id:
        raise TailoringError(f"{model.__name__} not found")
    return row


def create_tailored_draft(
    session: Session,
    user: User,
    resume_id: str,
    job_id: str,
    *,
    use_ai: bool = True,
) -> TailoredResume:
    """Generate a new validated draft version for one (resume, job)."""
    resume = _get_owned(session, Resume, resume_id, user)
    job = _get_owned(session, Job, job_id, user)
    requirements = (
        session.execute(select(JobRequirement).where(JobRequirement.job_id == job.id))
        .scalars()
        .all()
    )
    if not requirements:
        raise TailoringError("extract job requirements first")

    content, unsupported, used_ai = generate_tailored_content(
        resume, list(requirements), use_ai=use_ai
    )

    draft = TailoredResume(
        user_id=user.id,
        resume_id=resume.id,
        job_id=job.id,
        version=next_version(session, resume.id, job.id),
        approval_status="draft",
        content=content.model_dump(mode="json"),
        unsupported_claims=[c.model_dump(mode="json") for c in unsupported],
    )
    session.add(draft)
    session.commit()
    logger.info(
        "tailored.draft_created",
        tailored_id=draft.id,
        version=draft.version,
        used_ai=used_ai,
        unsupported_claims=len(unsupported),
    )
    return draft


def list_tailored(session: Session, user: User) -> list[TailoredResume]:
    return list(
        session.execute(
            select(TailoredResume)
            .where(TailoredResume.user_id == user.id)
            .order_by(TailoredResume.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_tailored(session: Session, user: User, tailored_id: str) -> TailoredResume:
    safe_id = _safe_id(tailored_id)
    tailored = session.get(TailoredResume, safe_id) if safe_id else None
    if tailored is None or tailored.user_id != user.id:
        raise TailoringError("tailored resume not found")
    return tailored


def submit_for_review(session: Session, user: User, tailored_id: str) -> TailoredResume:
    """Move a draft to pending_review (the state the UI presents for review)."""
    tailored = get_tailored(session, user, tailored_id)
    if tailored.approval_status not in ("draft", "rejected"):
        raise TailoringError("only drafts or rejected versions can be submitted for review")
    tailored.approval_status = "pending_review"
    session.commit()
    return tailored


def approve_tailored(session: Session, user: User, tailored_id: str) -> TailoredResume:
    """Explicitly approve a draft; exports the PDF afterwards."""
    tailored = get_tailored(session, user, tailored_id)
    if tailored.approval_status not in ("pending_review", "draft"):
        raise TailoringError("already approved or rejected")
    tailored.approval_status = "approved"
    tailored.approved_at = datetime.now(UTC)
    try:
        content = TailoredContent.model_validate(tailored.content)
        tailored.final_pdf_path = export_pdf(tailored, content)
    except ValueError as exc:
        raise TailoringError(str(exc)) from exc
    session.commit()
    logger.info("tailored.approved", tailored_id=tailored.id, version=tailored.version)
    return tailored


def reject_tailored(session: Session, user: User, tailored_id: str) -> TailoredResume:
    tailored = get_tailored(session, user, tailored_id)
    if tailored.approval_status == "approved":
        raise TailoringError("cannot reject an approved version; create a new version instead")
    tailored.approval_status = "rejected"
    session.commit()
    return tailored
