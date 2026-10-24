"""Pydantic schemas for application tracking (Phase 2 Step 2.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApplicationStatus

VALID_STATUSES = {s.value for s in ApplicationStatus}


class ApplicationCreate(BaseModel):
    """Request body for get-or-create of an application."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    tailored_resume_id: str | None = None


class ApplicationStatusUpdate(BaseModel):
    """Request body for a status change (validated against TRANSITIONS)."""

    model_config = ConfigDict(extra="forbid")

    status: str
    notes: str | None = None


class ConfirmSubmissionRequest(BaseModel):
    """Explicit "I applied" confirmation."""

    model_config = ConfigDict(extra="forbid")

    external_ref: str | None = None
    notes: str | None = None


class ApplicationResponse(BaseModel):
    """One application row enriched with joined job info."""

    id: str
    job_id: str
    status: str
    notes: str | None
    submitted_at: str | None
    tailored_resume_id: str | None
    created_at: str | None
    updated_at: str | None

    job_title: str | None
    job_company: str | None
    job_canonical_url: str | None
    job_is_active: bool | None
    job_is_expired: bool | None
    job_source: str | None
    allowed_transitions: list[str]


class ApplicationEventResponse(BaseModel):
    """One timeline event."""

    id: str
    event_type: str
    payload: dict[str, Any]
    occurred_at: str
    created_at: str | None


class AvailabilityResponse(BaseModel):
    """Availability verification outcome — deliberately not an application status."""

    outcome: str
    reason: str
