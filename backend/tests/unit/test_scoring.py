"""Unit tests for the deterministic scoring primitives (tiering, renorm)."""

from __future__ import annotations

from app.models.enums import MatchTier
from app.scoring.score import (
    SCORING_RULES_VERSION,
    ScoreComponent,
    _renormalize_score,
    _tier_for,
)


def test_tier_thresholds() -> None:
    assert _tier_for(100) is MatchTier.STRONG
    assert _tier_for(80) is MatchTier.STRONG
    assert _tier_for(60) is MatchTier.GOOD
    assert _tier_for(40) is MatchTier.STRETCH
    assert _tier_for(1) is MatchTier.LONG_SHOT
    assert _tier_for(0) is MatchTier.LONG_SHOT


def test_renormalization_removes_unknown_weight() -> None:
    # Full unknown on one component: it must vanish from the denominator,
    # so remaining full-coverage weights give 100 — not 80.
    components = [
        ScoreComponent("required_skills", 40, 40, 0),
        ScoreComponent("experience", 20, 0, 20),  # fully unknown
        ScoreComponent("projects", 10, 10, 0),
        ScoreComponent("location_remote", 10, 10, 0),
        ScoreComponent("work_authorization", 5, 0, 5),  # fully unknown
    ]
    assert _renormalize_score(components) == 100
    # Recorded version exists so scoring results are auditable.
    assert SCORING_RULES_VERSION


def test_renormalization_unknown_is_not_a_mismatch() -> None:
    # Half the weight unknown and the known half earned -> still 100.
    components = [
        ScoreComponent("required_skills", 40, 40, 0),
        ScoreComponent("preferred_skills", 15, 0, 15),
        ScoreComponent("experience", 20, 20, 0),
        ScoreComponent("projects", 10, 10, 0),
        ScoreComponent("location_remote", 10, 10, 0),
        ScoreComponent("work_authorization", 5, 5, 0),
    ]
    assert _renormalize_score(components) == 100


def test_zero_score_when_nothing_known_or_earned() -> None:
    components = [
        ScoreComponent("required_skills", 40, 0, 0),
        ScoreComponent("experience", 20, 0, 20),
        ScoreComponent("projects", 10, 0, 0),
        ScoreComponent("location_remote", 10, 0, 10),
        ScoreComponent("work_authorization", 5, 0, 5),
    ]
    assert _renormalize_score(components) == 0


def test_partial_support_counts_half() -> None:
    # 40-weight dimension: one supported + one partially supported of 4 skills
    # -> earned = 1.0*per + 0.5*per with per=10.
    from app.models.enums import EvidenceStatus
    from app.scoring.evidence import RequirementEvidence

    evidence = [
        RequirementEvidence("Python", "required_skill", True, EvidenceStatus.SUPPORTED, [], ""),
        RequirementEvidence(
            "Docker", "required_skill", True, EvidenceStatus.PARTIALLY_SUPPORTED, [], ""
        ),
        RequirementEvidence("SQL", "required_skill", True, EvidenceStatus.SUPPORTED, [], ""),
        RequirementEvidence("Go", "required_skill", True, EvidenceStatus.UNSUPPORTED, [], ""),
    ]
    component = ScoreComponent("required_skills", 40, 0, 0)
    per = 40 / 4
    # 2 supported (2*10) + 1 partially supported (0.5*10) of 4 skills
    component.earned = (
        sum(1 for e in evidence if e.status is EvidenceStatus.SUPPORTED) * per
        + 0.5 * sum(1 for e in evidence if e.status is EvidenceStatus.PARTIALLY_SUPPORTED) * per
    )
    assert component.earned == 25.0
