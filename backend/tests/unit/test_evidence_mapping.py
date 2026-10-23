"""Unit tests for deterministic requirement-to-evidence mapping."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models.enums import EvidenceStatus
from app.schemas.requirements import ExtractedRequirementItem, ExtractedRequirements
from app.scoring.evidence import build_evidence_report, map_experience_requirement, map_skills


class FakeProfile:
    """Minimal stand-in for UserProfile (avoids DB in unit tests)."""

    def __init__(
        self, skills: list[str], years: Decimal | None, projects: list[dict[str, Any]]
    ) -> None:
        self.skills = skills
        self.professional_experience_years = years
        self.projects = projects


class FakeUser:
    def __init__(self, profile: FakeProfile | None) -> None:
        self.user_profile = profile


def test_exact_skill_match_supported() -> None:
    evidence, matched = map_skills([ExtractedRequirementItem(text="Python")], ["Python", "SQL"])
    assert len(evidence) == 1
    assert evidence[0].status == EvidenceStatus.SUPPORTED
    assert matched == ["Python"]


def test_case_insensitive_skill_match() -> None:
    evidence, matched = map_skills([ExtractedRequirementItem(text="python")], ["PYTHON"])
    assert evidence[0].status == EvidenceStatus.SUPPORTED
    assert matched == ["python"]


def test_missing_profile_skill_is_unknown_not_unsupported() -> None:
    evidence, matched = map_skills([ExtractedRequirementItem(text="Docker")], ["Python"])
    assert matched == []
    assert evidence[0].status == EvidenceStatus.UNKNOWN
    assert "unverified, not deficient" in evidence[0].explanation


def test_alias_match_postgres() -> None:
    evidence, matched = map_skills([ExtractedRequirementItem(text="PostgreSQL")], ["postgres"])
    assert evidence[0].status == EvidenceStatus.SUPPORTED
    assert matched


def test_experience_meets_requirement() -> None:
    evidence = map_experience_requirement(3.0, Decimal("3.5"))
    assert evidence.status == EvidenceStatus.SUPPORTED


def test_experience_gap_with_project_evidence_is_partial() -> None:
    evidence = map_experience_requirement(5.0, Decimal("3.5"), profile_projects_count=3)
    assert evidence.status == EvidenceStatus.PARTIALLY_SUPPORTED
    assert "Stretch" in evidence.explanation


def test_experience_below_without_projects_is_unsupported() -> None:
    evidence = map_experience_requirement(5.0, Decimal("2.0"), profile_projects_count=0)
    assert evidence.status == EvidenceStatus.UNSUPPORTED


def test_missing_data_on_either_side_is_unknown() -> None:
    assert map_experience_requirement(None, Decimal("2.0")).status == EvidenceStatus.UNKNOWN
    assert map_experience_requirement(3.0, None).status == EvidenceStatus.UNKNOWN


def test_build_evidence_report_flags_unknown_work_authorization() -> None:
    extraction = ExtractedRequirements(
        required_skills=[ExtractedRequirementItem(text="Python")],
        unknown_fields=["remote_policy"],
    )
    report = build_evidence_report(FakeUser(FakeProfile(["Python"], Decimal(1), [])), extraction)  # type: ignore[arg-type]
    assert "work_authorization" in report["unknown_fields"]
    assert any(e["status"] == EvidenceStatus.SUPPORTED.value for e in report["evidence"])
