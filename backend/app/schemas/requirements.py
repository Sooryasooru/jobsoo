"""Structured-output schemas for AI requirement extraction.

Every field is optional/nullable: a sparse or ambiguous job description must
yield `unknown` values, never invented facts.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractedRequirementItem(BaseModel):
    """One requirement category item extracted from the description."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=400)
    is_required: bool = True
    min_years: float | None = Field(default=None, ge=0)
    is_hard_blocker: bool = False
    source_quote: str | None = Field(default=None, max_length=600)

    @field_validator("text", "source_quote")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v else v


class ExtractedRequirements(BaseModel):
    """Full extraction payload produced by the LLM and validated here."""

    model_config = ConfigDict(extra="ignore")

    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    remote_policy: str | None = None  # remote | hybrid | onsite | unknown
    required_skills: list[ExtractedRequirementItem] = Field(default_factory=list)
    preferred_skills: list[ExtractedRequirementItem] = Field(default_factory=list)
    min_professional_years: float | None = Field(default=None, ge=0)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    work_authorization: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    ambiguity_notes: list[str] = Field(default_factory=list)


class ExtractionRequest(BaseModel):
    """Inputs for one extraction call."""

    job_description: str = Field(min_length=1, max_length=20000)
    job_title_hint: str | None = None
    company_hint: str | None = None
