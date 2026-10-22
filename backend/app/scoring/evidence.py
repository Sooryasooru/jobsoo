"""Deterministic requirement-to-evidence mapping.

The LLM never asserts candidate competence here: this module is pure Python
and matches stored job requirements against stored candidate evidence.
Missing information produces `unknown`, never a negative conclusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models import User
from app.models.enums import EvidenceStatus
from app.schemas.requirements import ExtractedRequirementItem, ExtractedRequirements

# Tokens ignored when comparing requirement text to skill lists.
_STOP_TOKENS = {"and", "or", "the", "a", "an", "of", "in", "for", "with", "to"}
_SKILL_SPLIT = re.compile(r"[^a-zA-Z0-9+#./]+")

# Similar-but-not-identical tokens (e.g. "postgres" vs "postgresql").
_ALIAS_MAP: dict[str, str] = {
    "postgres": "postgresql",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "node": "nodejs",
    "node.js": "nodejs",
    "py": "python",
}


@dataclass
class RequirementEvidence:
    """One requirement matched against candidate evidence."""

    requirement_text: str
    category: str
    is_required: bool
    status: EvidenceStatus
    evidence_refs: list[str]
    explanation: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "requirement_text": self.requirement_text,
            "category": self.category,
            "is_required": self.is_required,
            "status": self.status.value,
            "evidence_refs": self.evidence_refs,
            "explanation": self.explanation,
        }


def _tokenize(name: str) -> str:
    """Normalize a skill name to a canonical token for comparison."""
    lowered = name.strip().lower()
    lowered = _ALIAS_MAP.get(lowered, lowered)
    tokens = [t for t in _SKILL_SPLIT.split(lowered) if t and t not in _STOP_TOKENS]
    return " ".join(tokens) or lowered


def map_skills(
    requirement_skills: list[ExtractedRequirementItem],
    profile_skills: list[str],
) -> tuple[list[RequirementEvidence], list[str]]:
    """Map skill requirements to profile skills.

    Returns (evidence_records, matched_requirement_texts). A skill the profile
    never mentions is `unknown` (profile incompleteness), not `unsupported`,
    unless the profile has skill data and still omits it.
    """
    evidence: list[RequirementEvidence] = []
    matched: list[str] = []

    for requirement in requirement_skills:
        req_token = _tokenize(requirement.text)
        refs = [
            skill
            for skill, token in ((s, _tokenize(s)) for s in profile_skills if s.strip())
            if token == req_token
        ]
        if refs:
            status = EvidenceStatus.SUPPORTED
            explanation = f"Evidence: candidate profile lists {', '.join(refs)}."
            matched.append(requirement.text)
        elif profile_skills:
            status = EvidenceStatus.UNKNOWN
            explanation = "Profile has no skills section tagged with this skill; treat as unverified, not deficient."
        else:
            status = EvidenceStatus.UNKNOWN
            explanation = "No candidate skill data available."
        evidence.append(
            RequirementEvidence(
                requirement_text=requirement.text,
                category="required_skill" if requirement.is_required else "preferred_skill",
                is_required=requirement.is_required,
                status=status,
                evidence_refs=refs,
                explanation=explanation,
            )
        )
    return evidence, matched


def map_experience_requirement(
    min_years: float | None,
    profile_experience: Decimal | None,
    profile_projects_count: int = 0,
) -> RequirementEvidence:
    """Compare a stated years requirement with candidate professional years.

    Insufficient data is UNKNOWN. A smaller-but-nonzero experience plus
    project evidence yields PARTIALLY_SUPPORTED (stretch, visible in UI).
    """
    requirement_text = (
        f"Minimum professional experience: {min_years} years"
        if min_years
        else "Professional experience"
    )
    if min_years is None or profile_experience is None:
        return RequirementEvidence(
            requirement_text=requirement_text,
            category="experience",
            is_required=True,
            status=EvidenceStatus.UNKNOWN,
            evidence_refs=[],
            explanation="Experience data is missing on one side; no claim either way.",
        )

    gap = float(profile_experience) - float(min_years)
    if gap >= 0:
        return RequirementEvidence(
            requirement_text=requirement_text,
            category="experience",
            is_required=True,
            status=EvidenceStatus.SUPPORTED,
            evidence_refs=[f"profile.professional_experience_years={profile_experience}"],
            explanation=f"Candidate's {profile_experience} years meets the {min_years}-year requirement.",
        )
    if float(profile_experience) > 0 and profile_projects_count > 0:
        return RequirementEvidence(
            requirement_text=requirement_text,
            category="experience",
            is_required=True,
            status=EvidenceStatus.PARTIALLY_SUPPORTED,
            evidence_refs=[f"profile.professional_experience_years={profile_experience}"],
            explanation=(
                f"{abs(gap):.1f} years short of the stated {min_years}; "
                f"{profile_projects_count} project(s) provide additional evidence. Stretch."
            ),
        )
    return RequirementEvidence(
        requirement_text=requirement_text,
        category="experience",
        is_required=True,
        status=EvidenceStatus.UNSUPPORTED,
        evidence_refs=[f"profile.professional_experience_years={profile_experience}"],
        explanation=(
            f"Candidate's {profile_experience} years is below the {min_years}-years requirement."
        ),
    )


def build_evidence_report(
    user: User,
    extraction: ExtractedRequirements,
) -> dict[str, Any]:
    """Plan requirement-to-evidence details for one user and extraction result."""
    profile = user.user_profile
    profile_skills = list(profile.skills) if profile else []
    evidence, matched_skills = map_skills(
        extraction.required_skills + extraction.preferred_skills, profile_skills
    )
    experience = map_experience_requirement(
        extraction.min_professional_years,
        profile.professional_experience_years if profile else None,
        len(profile.projects) if profile else 0,
    )
    evidence.append(experience)

    unknown_fields = list(extraction.unknown_fields)
    if extraction.work_authorization is None:
        unknown_fields.append("work_authorization")

    return {
        "evidence": [e.to_payload() for e in evidence],
        "matched_skills": matched_skills,
        "unknown_fields": unknown_fields,
        "project_count": len(profile.projects) if profile else 0,
        "preferred_skills_text": [s.text for s in extraction.preferred_skills],
    }
