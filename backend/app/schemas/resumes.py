"""Resume and profile API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ResumeResponse(BaseModel):
    """API response for an uploaded original CV."""

    id: str
    kind: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    file_checksum_sha256: str
    parsed_content: dict[str, Any]
    parse_notes: list[str]
    created_at: datetime


class ProfileUpdate(BaseModel):
    """Editable candidate profile fields."""

    full_name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    headline: str | None = Field(default=None, max_length=255)
    professional_experience_years: float | None = Field(default=None, ge=0)
    skills: list[str] | None = None
    preferred_locations: list[str] | None = None
    remote_preference: str | None = None
    expected_salary_min: int | None = Field(default=None, ge=0)
    expected_salary_currency: str | None = Field(default=None, max_length=10)
    work_rights: str | None = Field(default=None, max_length=2000)
    career_start_date: str | None = None  # ISO date, validated on write


class ProfileResponse(BaseModel):
    """API response for the candidate profile."""

    full_name: str
    location: str
    headline: str
    professional_experience_years: float | None
    skills: list[str]
    preferred_locations: list[str]
    remote_preference: str
    expected_salary_min: int | None
    expected_salary_currency: str | None
    work_rights: str
    career_start_date: str | None
