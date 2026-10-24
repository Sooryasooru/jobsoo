"""CV upload and candidate-profile routes."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentAuthenticatedUser
from app.db.session import get_session
from app.models import Resume, User
from app.schemas.resumes import ProfileResponse, ProfileUpdate, ResumeResponse
from app.services.resumes import CVUploadError, upload_resume

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/cvs", tags=["cvs"])
router_profiles = APIRouter(prefix="/profile", tags=["profile"])


def _resume_response(resume: Resume) -> ResumeResponse:
    return ResumeResponse(
        id=str(resume.id),
        kind=resume.kind,
        original_filename=resume.original_filename,
        file_type=resume.file_type,
        file_size_bytes=resume.file_size_bytes,
        file_checksum_sha256=resume.file_checksum_sha256,
        parsed_content=resume.parsed_content,
        parse_notes=resume.parse_notes,
        created_at=resume.created_at,
    )


@router.post("", response_model=ResumeResponse)
def upload_cv(
    user: CurrentAuthenticatedUser, file: UploadFile = File(...), db: Session = Depends(get_session)
) -> ResumeResponse:
    """Upload one original CV (pdf/docx/md/txt). Originals are immutable."""
    try:
        if file.filename is None:
            raise CVUploadError("file name is required")
        content = file.file.read()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="could not read upload") from exc
    try:
        resume = upload_resume(db, user, file.filename, content)
    except CVUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _resume_response(resume)


@router.get("", response_model=list[ResumeResponse])
def list_cvs(
    user: CurrentAuthenticatedUser, db: Session = Depends(get_session)
) -> list[ResumeResponse]:
    """List the user's original CVs."""
    rows = (
        db.execute(
            select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_resume_response(r) for r in rows]


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_cv(
    resume_id: str, user: CurrentAuthenticatedUser, db: Session = Depends(get_session)
) -> ResumeResponse:
    """Fetch one CV's parsed content by id."""
    try:
        resume = db.get(Resume, resume_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="cv not found") from None
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=404, detail="cv not found")
    return _resume_response(resume)


def _profile_response(user: User) -> ProfileResponse:
    profile = user.user_profile
    if profile is None:
        raise HTTPException(status_code=500, detail="user profile is missing")
    return ProfileResponse(
        full_name=profile.full_name,
        location=profile.location,
        headline=profile.headline,
        professional_experience_years=profile.professional_experience_years,
        skills=profile.skills,
        preferred_locations=profile.preferred_locations,
        remote_preference=profile.remote_preference,
        expected_salary_min=profile.expected_salary_min,
        expected_salary_currency=profile.expected_salary_currency,
        work_rights=profile.user_rights,
        career_start_date=profile.career_start_date.isoformat()
        if profile.career_start_date
        else None,
    )


@router_profiles.get("", response_model=ProfileResponse)
def get_profile(user: CurrentAuthenticatedUser) -> ProfileResponse:
    """Return the prototype user's profile."""
    return _profile_response(user)


@router_profiles.put("", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdate, user: CurrentAuthenticatedUser, db: Session = Depends(get_session)
) -> ProfileResponse:
    """Update editable profile fields."""
    profile = user.user_profile
    if profile is None:
        raise HTTPException(status_code=500, detail="user profile is missing")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "career_start_date" and value:
            from datetime import date

            profile.career_start_date = date.fromisoformat(value)
        elif value is not None:
            setattr(profile, field, value)
    db.add(profile)
    db.commit()
    logger.info("profile.updated", user_id=user.id)
    return _profile_response(user)
