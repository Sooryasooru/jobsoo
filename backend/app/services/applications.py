"""Application tracking service (Phase 2 Step 2.1).

Business rules live here, never in API routes:

- Valid status transitions are enforced server-side via `TRANSITIONS`.
- Every successful status change appends exactly one `application_events`
  row in the same database transaction as the status update (atomicity).
- Repeated requests that do not change the status are idempotent no-ops and
  create no events.
- Explicit manual submission ("I applied") is required; nothing else marks an
  application as submitted, and repeated confirmations create no new events.
- Job availability is reported as open/closed/unknown and is deliberately
  separate from application status.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Application, ApplicationEvent, ApplicationStatus, Job, TailoredResume, User

# Table of valid transitions: source -> set of allowed target statuses.
# Adjusted from the initial proposal to keep the Phase 1 `prepared` (ready)
# and existing `interviewing` status names; graph semantics unchanged.
TRANSITIONS: dict[str, set[str]] = {
    "queued": {"prepared", "withdrawn", "closed"},
    "prepared": {"submitted", "withdrawn", "closed"},
    "submitted": {
        "interviewing",
        "assessment",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    },
    "interviewing": {
        "assessment",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    },
    "assessment": {"interviewing", "rejected", "offer", "withdrawn", "closed"},
    "offer": {"withdrawn", "closed"},
    # Terminal states have no outgoing transitions.
    "rejected": set(),
    "withdrawn": set(),
    "closed": set(),
}


def allowed_transitions(current: ApplicationStatus | str) -> set[str]:
    """Set of statuses reachable from `current`."""
    return set(TRANSITIONS.get(str(current), set()))


def _safe_id(value: str) -> str | None:
    """Return the string unchanged when it is a valid UUID, else None."""
    try:
        UUID(str(value))
    except (ValueError, AttributeError):
        return None
    return str(value)


class ApplicationError(Exception):
    """Application service error carrying an HTTP-ish code."""

    def __init__(self, code: str, message: str) -> None:
        """Store code and message."""
        self.code = code
        self.message = message
        super().__init__(message)


class AvailabilityOutcome(StrEnum):
    """Job availability verification outcomes (never inferred)."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


def _validate_tailored_resume(
    db: Session, user: User, job: Job, tailored_resume_id: str | None
) -> str | None:
    """Validate an optional tailored-resume reference before any DB changes.

    - Unknown or malformed id -> not_found (never leaks existence).
    - Another user's resume -> not_found.
    - A resume tailored for a different job -> conflict.
    """
    if not tailored_resume_id:
        return None
    resume_uuid = _safe_id(tailored_resume_id)
    row = db.get(TailoredResume, resume_uuid) if resume_uuid else None
    if row is None or str(row.user_id) != str(user.id):
        raise ApplicationError("not_found", "tailored resume not found")
    if str(row.job_id) != str(job.id):
        raise ApplicationError("conflict", "tailored resume is associated with a different job")
    return str(row.id)


def create_application(
    db: Session,
    user: User,
    job_id: str,
    tailored_resume_id: str | None = None,
) -> Application:
    """Get-or-create the single application for (user, job).

    Duplicate creation is prevented by the database unique constraint and by
    an upfront lookup, so concurrent creation is also safe.
    """
    job_uuid = _safe_id(job_id)
    job = db.get(Job, job_uuid) if job_uuid else None
    if job is None:
        raise ApplicationError("not_found", "job not found")
    # Validation deliberately runs before the duplicate lookup so a repeated
    # request can never bypass tailored-resume checks.
    validated_resume_id = _validate_tailored_resume(db, user, job, tailored_resume_id)
    existing = (
        db.execute(
            select(Application)
            .where(Application.user_id == user.id, Application.job_id == job.id)
            .order_by(Application.attempt_no.asc())
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    try:
        app_row = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.QUEUED,
            tailored_resume_id=validated_resume_id,
        )
        db.add(app_row)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=app_row.id,
                event_type="application_created",
                payload={"actor": "user", "source": "user", "status": ApplicationStatus.QUEUED},
            )
        )
        db.commit()
    except IntegrityError:
        # A racing request inserted it first; return the winner.
        db.rollback()
        found = (
            db.execute(
                select(Application).where(
                    Application.user_id == user.id, Application.job_id == job.id
                )
            )
            .scalars()
            .first()
        )
        if found is None:  # pragma: no cover - defensive
            raise
        return found
    return app_row


def get_application(db: Session, user: User, application_id: str) -> Application:
    """Fetch an application owned by `user` (404 on missing or foreign row)."""
    app_uuid = _safe_id(application_id)
    row = db.get(Application, app_uuid) if app_uuid else None
    if row is None or str(row.user_id) != str(user.id):
        raise ApplicationError("not_found", "application not found")
    return row


def get_event_rows(db: Session, user: User, application_id: str) -> Iterable[ApplicationEvent]:
    """Timeline for an application, oldest first (ownership enforced)."""
    application = get_application(db, user, application_id)
    return (
        db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application.id)
            .order_by(ApplicationEvent.occurred_at.asc(), ApplicationEvent.created_at.asc())
        )
        .scalars()
        .all()
    )


def list_applications(db: Session, user: User) -> list[dict[str, Any]]:
    """All applications for the user with joined job info for the board."""
    rows = db.execute(
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .where(Application.user_id == user.id)
        .order_by(Application.updated_at.desc())
    ).all()
    out: list[dict[str, Any]] = []
    for app_row, job in rows:
        out.append(_app_payload(app_row, job))
    return out


def _app_payload(app_row: Application, job: Job | None) -> dict[str, Any]:
    return {
        "id": str(app_row.id),
        "job_id": str(app_row.job_id),
        "status": app_row.status,
        "notes": app_row.notes,
        "submitted_at": app_row.submitted_at.isoformat() if app_row.submitted_at else None,
        "tailored_resume_id": str(app_row.tailored_resume_id)
        if app_row.tailored_resume_id
        else None,
        "created_at": app_row.created_at.isoformat() if app_row.created_at else None,
        "updated_at": app_row.updated_at.isoformat() if app_row.updated_at else None,
        "job_title": job.title if job else None,
        "job_company": job.company if job else None,
        "job_canonical_url": job.canonical_url if job else None,
        "job_is_active": job.is_active if job else None,
        "job_is_expired": job.is_expired if job else None,
        "job_source": job.source if job else None,
        "allowed_transitions": sorted(allowed_transitions(app_row.status)),
    }


def _event(
    db: Session,
    application: Application,
    event_type: str,
    *,
    prev_status: str | None,
    new_status: str | None,
    actor: str = "user",
    notes: str | None = None,
    external_ref: str | None = None,
) -> ApplicationEvent:
    payload: dict[str, Any] = {"actor": actor, "source": actor}
    if prev_status is not None:
        payload["previous_status"] = prev_status
    if new_status is not None:
        payload["new_status"] = new_status
    if notes is not None:
        payload["notes"] = notes
    if external_ref is not None:
        payload["external_reference"] = external_ref
    event = ApplicationEvent(
        application_id=application.id,
        event_type=event_type,
        payload=payload,
        occurred_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    return event


def update_status(
    db: Session,
    user: User,
    application_id: str,
    new_status: str,
    notes: str | None = None,
) -> tuple[Application, bool]:
    """Change an application status (server-validated transition).

    Returns (application, changed). `changed=False` for idempotent repeats,
    which create no events. The status update and the event are flushed in
    one transaction; `db.commit()` finalizes both or neither.
    """
    application = get_application(db, user, application_id)
    ApplicationStatus(new_status)  # validate value (raises ValueError)
    current = application.status
    if new_status == current:
        return application, False
    if new_status not in allowed_transitions(current):
        raise ApplicationError(
            "invalid_transition",
            f"invalid transition: {current} -> {new_status}",
        )
    row = (
        db.execute(select(Application).where(Application.id == application.id).with_for_update())
        .scalars()
        .one()
    )
    if row.status != current:  # raced with another transaction
        if row.status == new_status:
            db.rollback()
            return row, False
        raise ApplicationError(
            "conflict",
            f"status moved concurrently to {row.status}; reload and retry",
        )
    row.status = new_status
    _event(
        db,
        row,
        "status_change",
        prev_status=current,
        new_status=new_status,
        notes=notes,
    )
    db.commit()
    return row, True


def confirm_submitted(
    db: Session,
    user: User,
    application_id: str,
    external_ref: str | None = None,
    notes: str | None = None,
) -> tuple[Application, bool]:
    """Explicit "I applied" confirmation -> status `submitted`.

    Only meaningful from queued/prepared. Idempotent: confirming an already
    submitted application changes nothing and creates no extra event. Never
    called as a side effect of opening/download/preparation flows.
    """
    application = get_application(db, user, application_id)
    current = application.status
    if current == ApplicationStatus.SUBMITTED:
        return application, False
    if current not in (ApplicationStatus.QUEUED, ApplicationStatus.PREPARED):
        raise ApplicationError(
            "invalid_transition",
            f"submission can only be confirmed from queued/prepared (got {current})",
        )
    row = (
        db.execute(select(Application).where(Application.id == application.id).with_for_update())
        .scalars()
        .one()
    )
    if row.status == ApplicationStatus.SUBMITTED:  # raced confirmation
        db.rollback()
        return row, False
    row.status = ApplicationStatus.SUBMITTED
    row.submitted_at = datetime.now(UTC)
    _event(
        db,
        row,
        "submission_confirmed",
        prev_status=current,
        new_status=ApplicationStatus.SUBMITTED,
        external_ref=external_ref,
        notes=notes,
    )
    db.commit()
    return row, True


def check_availability(job: Job | None) -> dict[str, str]:
    """Verify listing availability — separate from any application status.

    `closed` is reported only on explicit source evidence (the reconcile sweep
    marked the listing inactive after checking the source). Everything else -
    source errors, manual listings, no evidence - stays `unknown`. We never
    claim `open` from a stale database record.
    """
    if job is None:
        return {"outcome": AvailabilityOutcome.UNKNOWN, "reason": "job not found"}
    if job.source == "manual":
        return {
            "outcome": AvailabilityOutcome.UNKNOWN,
            "reason": "manual source; availability cannot be verified",
        }
    if job.is_active is False:
        return {
            "outcome": AvailabilityOutcome.CLOSED,
            "reason": "listing no longer present at the source (reconcile sweep)",
        }
    return {
        "outcome": AvailabilityOutcome.UNKNOWN,
        "reason": "no fresh source verification available",
    }


def application_counts(db: Session, user: User) -> dict[str, int]:
    """Per-status counts for board summaries."""
    rows = db.execute(
        select(Application.status, func.count())
        .where(Application.user_id == user.id)
        .group_by(Application.status)
    ).all()
    return dict(rows)
