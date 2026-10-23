"""Tailored-CV workflow API routes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.tailoring import TailoredContent
from app.services.tailoring import (
    TailoringError,
    approve_tailored,
    create_tailored_draft,
    get_tailored,
    list_tailored,
    reject_tailored,
    submit_for_review,
)
from app.services.users import get_or_create_dev_user

router = APIRouter(prefix="/tailored", tags=["tailored"])


def _payload(tailored: Any) -> dict[str, Any]:
    return {
        "id": str(tailored.id),
        "resume_id": str(tailored.resume_id),
        "job_id": str(tailored.job_id),
        "version": tailored.version,
        "approval_status": tailored.approval_status,
        "content": TailoredContent.model_validate(tailored.content).model_dump(mode="json"),
        "unsupported_claims": tailored.unsupported_claims,
        "final_pdf_path": tailored.final_pdf_path,
        "approved_at": tailored.approved_at.isoformat() if tailored.approved_at else None,
        "created_at": tailored.created_at.isoformat()
        if isinstance(tailored.created_at, datetime)
        else tailored.created_at,
    }


@router.post("", status_code=201)
def create_draft(
    resume_id: str,
    job_id: str,
    use_ai: bool = True,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Generate a validated tailored-CV draft for one (resume, job)."""
    user = get_or_create_dev_user(db)
    try:
        draft = create_tailored_draft(db, user, resume_id, job_id, use_ai=use_ai)
    except TailoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _payload(draft)


@router.get("")
def list_all(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    user = get_or_create_dev_user(db)
    return [_payload(t) for t in list_tailored(db, user)]


@router.get("/{tailored_id}")
def get_one(tailored_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    user = get_or_create_dev_user(db)
    try:
        tailored = get_tailored(db, user, tailored_id)
    except TailoringError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _payload(tailored)


@router.post("/{tailored_id}/submit")
def submit(tailored_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Put a draft into review-state before the explicit approval step."""
    user = get_or_create_dev_user(db)
    try:
        return _payload(submit_for_review(db, user, tailored_id))
    except TailoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{tailored_id}/approve")
def approve(tailored_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Approve the draft; the PDF is generated only after approval."""
    user = get_or_create_dev_user(db)
    try:
        return _payload(approve_tailored(db, user, tailored_id))
    except TailoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{tailored_id}/reject")
def reject(tailored_id: str, db: Session = Depends(get_session)) -> dict[str, Any]:
    user = get_or_create_dev_user(db)
    try:
        return _payload(reject_tailored(db, user, tailored_id))
    except TailoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{tailored_id}/pdf")
def download_pdf(tailored_id: str, db: Session = Depends(get_session)) -> FileResponse:
    """Download the approved PDF; drafts have no PDF yet."""
    user = get_or_create_dev_user(db)
    try:
        tailored = get_tailored(db, user, tailored_id)
    except TailoringError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not tailored.final_pdf_path:
        raise HTTPException(status_code=404, detail="PDF not exported yet (not approved)")
    path = Path(tailored.final_pdf_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="stored PDF file is missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        headers={"Cache-Control": "private, no-store"},
    )
