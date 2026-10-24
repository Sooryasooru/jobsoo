"""String-based status/category constants.

Stored as constrained text columns (not native PostgreSQL enums) so schema
evolution does not require ALTER TYPE migrations.
"""

from __future__ import annotations

from enum import StrEnum


class ResumeApprovalStatus(StrEnum):
    """Approval lifecycle for tailored CVs."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class JobSource(StrEnum):
    """Known job sources."""

    ADZUNA = "adzuna"
    MANUAL = "manual"


class RequirementCategory(StrEnum):
    """Requirement categories for extraction and evidence mapping."""

    REQUIRED_SKILL = "required_skill"
    PREFERRED_SKILL = "preferred_skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    WORK_AUTHORIZATION = "work_authorization"
    RESPONSIBILITY = "responsibility"
    QUALIFICATION = "qualification"
    OTHER = "other"


class EvidenceStatus(StrEnum):
    """Evidence mapping status for a requirement versus candidate evidence."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class MatchTier(StrEnum):
    """Score tiers. Lower-scoring jobs stay visible."""

    STRONG = "strong"
    GOOD = "good"
    STRETCH = "stretch"
    LONG_SHOT = "long_shot"


class Recommendation(StrEnum):
    """Non-probabilistic recommendation labels."""

    APPLY_NOW = "apply_now"
    CONSIDER_APPLYING = "consider_applying"
    REQUIRES_CLOSING_GAPS = "requires_closing_gaps"
    LIKELY_REJECTED = "likely_rejected"


class ResumeKind(StrEnum):
    """Resume record kinds (originals vs tailored)."""

    ORIGINAL = "original"
    TAILORED = "tailored"


class ApplicationStatus(StrEnum):
    """Application status (kept separate from job availability).

    `prepared` is the "ready to apply" state (kept for Phase 1 compatibility);
    `queued` means created but not yet prepared. Terminal states are rejected,
    withdrawn and closed. Valid transitions are enforced by
    `app.services.applications.TRANSITIONS`.
    """

    QUEUED = "queued"
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    INTERVIEWING = "interviewing"
    ASSESSMENT = "assessment"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class FileType(StrEnum):
    """ParsedCV file types."""

    PDF = "pdf"
    DOCX = "docx"
    MD = "md"
    TXT = "txt"
