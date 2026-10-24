"""SQLAlchemy ORM models (single source of truth for the schema)."""

from app.models.application import Application, ApplicationEvent
from app.models.enums import (
    ApplicationStatus,
    EvidenceStatus,
    FileType,
    JobSource,
    MatchTier,
    Recommendation,
    RequirementCategory,
    ResumeApprovalStatus,
    ResumeKind,
)
from app.models.job import Job, JobRequirement
from app.models.match import JobMatch
from app.models.mixins import CreatedAtMixin, CreatedUpdatedAtMixin, str_uuid
from app.models.resume import Resume, TailoredResume
from app.models.user import User, UserProfile, UserSession

__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationStatus",
    "CreatedAtMixin",
    "CreatedUpdatedAtMixin",
    "EvidenceStatus",
    "FileType",
    "Job",
    "JobMatch",
    "JobRequirement",
    "JobSource",
    "MatchTier",
    "Recommendation",
    "RequirementCategory",
    "Resume",
    "ResumeApprovalStatus",
    "ResumeKind",
    "TailoredResume",
    "User",
    "UserSession",
    "UserProfile",
    "str_uuid",
]
