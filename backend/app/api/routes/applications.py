"""Application tracking API routes (Phase 2 Step 2.1). Routes stay thin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import Job
from app.schemas.applications import (
    ApplicationCreate,
    ApplicationEventResponse,
    ApplicationResponse,
    ApplicationStatusUpdate,
    AvailabilityResponse,
    ConfirmSubmissionRequest,
)
from app.services.applications import (
    ApplicationError,
    allowed_transitions,
    application_counts,
    check_availability,
    confirm_submitted,
    create_application,
    get_application,
    get_event_rows,
    list_applications,
    update_status,
)
from app.services.users import get_or_create_dev_user

router = APIRouter(prefix="/applications", tags=["applications"])


def _row_payload(app_row: Any, job: Any) -> dict[str, Any]:
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


def _http_error(exc: ApplicationError) -> HTTPException:
    status_map = {
        "not_found": 404,
        "invalid_transition": 409,
        "conflict": 409,
    }
    return HTTPException(status_code=status_map.get(exc.code, 400), detail=exc.message)


@router.get("")
def list_all(db: Session = Depends(get_session)) -> dict[str, Any]:
    """Board data: applications with job info plus per-status counts."""
    user = get_or_create_dev_user(db)
    return {
        "items": list_applications(db, user),
        "counts": application_counts(db, user),
    }


@router.post("", status_code=201, response_model=ApplicationResponse)
def create_app(payload: ApplicationCreate, db: Session = Depends(get_session)) -> Any:
    """Prepare an application (get-or-create; duplicates are prevented)."""
    user = get_or_create_dev_user(db)
    try:
        app_row = create_application(db, user, payload.job_id, payload.tailored_resume_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc

    return _row_payload(app_row, db.get(Job, app_row.job_id))


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_one(application_id: str, db: Session = Depends(get_session)) -> Any:
    """Application detail (ownership enforced)."""
    user = get_or_create_dev_user(db)
    try:
        app_row = get_application(db, user, application_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc

    return _row_payload(app_row, db.get(Job, app_row.job_id))


@router.get("/{application_id}/events", response_model=list[ApplicationEventResponse])
def events(application_id: str, db: Session = Depends(get_session)) -> Any:
    """Full event timeline for one application."""
    user = get_or_create_dev_user(db)
    try:
        rows = list(get_event_rows(db, user, application_id))
    except ApplicationError as exc:
        raise _http_error(exc) from exc
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "payload": e.payload,
            "occurred_at": e.occurred_at.isoformat(),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.post("/{application_id}/status", response_model=ApplicationResponse)
def change_status(
    application_id: str,
    body: ApplicationStatusUpdate,
    db: Session = Depends(get_session),
) -> Any:
    """Validate and apply a server-side status transition."""
    user = get_or_create_dev_user(db)
    try:
        app_row, _changed = update_status(db, user, application_id, body.status, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown status: {body.status}") from exc
    except ApplicationError as exc:
        raise _http_error(exc) from exc

    return _row_payload(app_row, db.get(Job, app_row.job_id))


@router.post("/{application_id}/confirm-submit", response_model=ApplicationResponse)
def confirm_submit(
    application_id: str,
    body: ConfirmSubmissionRequest,
    db: Session = Depends(get_session),
) -> Any:
    """Explicit "I applied" — the only path that marks an application submitted."""
    user = get_or_create_dev_user(db)
    try:
        app_row, _changed = confirm_submitted(
            db, user, application_id, external_ref=body.external_ref, notes=body.notes
        )
    except ApplicationError as exc:
        raise _http_error(exc) from exc

    return _row_payload(app_row, db.get(Job, app_row.job_id))


@router.get("/{application_id}/availability", response_model=AvailabilityResponse)
def availability(application_id: str, db: Session = Depends(get_session)) -> Any:
    """Recheck the listing's availability (open/closed/unknown)."""
    user = get_or_create_dev_user(db)
    try:
        app_row = get_application(db, user, application_id)
    except ApplicationError as exc:
        raise _http_error(exc) from exc

    return check_availability(db.get(Job, app_row.job_id))
