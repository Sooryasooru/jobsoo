"""Deterministic, explainable job scoring.

Scores are computed only in this module (pure Python; no AI in the scoring
path) so every result is reproducible and unit-testable.

- Weights are documented in SCORING_RULES and stored in results.
- Missing information contributes its weight to `unknown_weight` which is
  renormalized away — a missing value is NEVER treated as a confirmed
  mismatch (Phase 1 spec §6E).
- Scores are NOT probabilities of being hired/interviewed; they express
  evidence coverage against the stated requirements.
- Tiers: strong >= 80, good >= 60, stretch >= 40, else long_shot. All tiers
  stay visible in the UI; no tier auto-hides or rejects a job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobMatch, User
from app.models.enums import EvidenceStatus, MatchTier, Recommendation
from app.schemas.requirements import ExtractedRequirementItem
from app.scoring.evidence import RequirementEvidence, map_skills

SCORING_RULES_VERSION = "scoring-v1"

SCORING_RULES: dict[str, dict[str, Any]] = {
    "required_skills": {"weight": 40, "description": "Coverage of required skills"},
    "preferred_skills": {"weight": 15, "description": "Coverage of preferred skills"},
    "experience": {"weight": 20, "description": "Professional experience vs stated years"},
    "projects": {"weight": 10, "description": "Project evidence"},
    "location_remote": {"weight": 10, "description": "Location and remote fit"},
    "work_authorization": {"weight": 5, "description": "Work authorization status"},
}

_TIER_THRESHOLDS: list[tuple[int, MatchTier]] = [
    (80, MatchTier.STRONG),
    (60, MatchTier.GOOD),
    (40, MatchTier.STRETCH),
    (0, MatchTier.LONG_SHOT),
]


@dataclass
class ScoreComponent:
    """One scored dimension with its weight accounting."""

    name: str
    weight: int
    earned: float
    unknown_weight: int  # portion of the weight treated as unknown
    detail: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "earned": round(self.earned, 1),
            "unknown_weight": self.unknown_weight,
            "detail": self.detail,
        }


@dataclass
class ScoreResult:
    """Full explainable scoring outcome for one (user, job)."""

    score: int
    tier: MatchTier
    recommendation: Recommendation
    explanation: str
    components: list[ScoreComponent] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    unknown_skills: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hard_blocker_warnings: list[dict[str, Any]] = field(default_factory=list)
    unknown_requirements: list[dict[str, Any]] = field(default_factory=list)
    experience_gap_years: float | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier.value,
            "recommendation": self.recommendation.value,
            "explanation": self.explanation,
            "score_components": [c.to_payload() for c in self.components],
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "unknown_skills": self.unknown_skills,
            "evidence": self.evidence,
            "hard_blocker_warnings": self.hard_blocker_warnings,
            "unknown_requirements": self.unknown_requirements,
            "experience_gap_years": self.experience_gap_years,
            "scoring_rules_version": SCORING_RULES_VERSION,
        }


def _tier_for(score: int) -> MatchTier:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return MatchTier.LONG_SHOT  # pragma: no cover - unreachable above


def _credential_token(skill_name: str) -> str:
    return skill_name.strip().lower().rstrip(".,;")


def score_job_against_profile(user: User, job: Job) -> ScoreResult:
    """Compute the deterministic score for one stored job and user profile."""
    profile = user.user_profile
    profile_skills = list(profile.skills) if profile else []
    project_count = len(profile.projects) if profile else 0

    req_rows = list(job.requirements)
    evidence_records: list[RequirementEvidence] = []
    matched: list[str] = []
    missing: list[str] = []
    unknown: list[str] = []
    hard_blockers: list[dict[str, Any]] = []
    experience_gap: float | None = None

    required = [r for r in req_rows if r.category == "required_skill"]
    preferred = [r for r in req_rows if r.category == "preferred_skill"]
    for row in required + preferred:
        ev, matched_texts = map_skills(
            [
                ExtractedRequirementItem(
                    text=row.text,
                    is_required=row.is_required,
                    is_hard_blocker=row.is_hard_blocker,
                )
            ],
            profile_skills,
        )
        rec = ev[0]
        evidence_records.append(rec)
        if rec.status is EvidenceStatus.SUPPORTED:
            matched.append(matched_texts[0])
        elif rec.status is EvidenceStatus.UNSUPPORTED:
            missing.append(rec.requirement_text)
        else:
            unknown.append(rec.requirement_text)
        if row.is_hard_blocker and rec.status is not EvidenceStatus.SUPPORTED:
            hard_blockers.append(
                {
                    "requirement": rec.requirement_text,
                    "status": rec.status.value,
                    "category": rec.category,
                    "explanation": rec.explanation,
                }
            )

    components: list[ScoreComponent] = []

    def evidence_for(texts: list[str]) -> list[RequirementEvidence]:
        """Evidence records for exactly these requirement texts (order preserved)."""
        wanted = set(texts)
        return [e for e in evidence_records if e.requirement_text in wanted]

    required_texts = [r.text for r in required]
    preferred_texts = [r.text for r in preferred]
    components.append(
        _skills_component("required_skills", required_texts, evidence_for(required_texts))
    )
    components.append(
        _skills_component("preferred_skills", preferred_texts, evidence_for(preferred_texts))
    )

    # Experience component
    exp_rows = [r for r in req_rows if r.category == "experience" and r.min_years is not None]
    first_min = exp_rows[0].min_years if exp_rows else None
    stated_years = float(first_min) if first_min is not None else None
    min_years = stated_years
    components.append(_experience_component(min_years, profile, project_count))
    if (
        stated_years is not None
        and profile is not None
        and profile.professional_experience_years is not None
    ):
        experience_gap = max(0.0, stated_years - float(profile.professional_experience_years))

    # Projects component
    if project_count >= 2:
        components.append(ScoreComponent("projects", 10, 10, 0, f"{project_count} projects"))
    elif project_count == 1:
        components.append(ScoreComponent("projects", 10, 5, 0, "1 project"))
    else:
        components.append(ScoreComponent("projects", 10, 0, 0, "0 projects"))

    # Location/remote component
    components.append(_location_component(job, profile))

    # Work authorization component
    wa_rows = [r for r in req_rows if r.category == "work_authorization"]
    components.append(_work_auth_component(wa_rows, profile))

    score = _renormalize_score(components)
    tier = _tier_for(score)
    unknown_requirements = [
        e.to_payload() for e in evidence_records if e.status is EvidenceStatus.UNKNOWN
    ]

    if hard_blockers:
        recommendation = Recommendation.REQUIRES_CLOSING_GAPS
    elif tier is MatchTier.STRONG:
        recommendation = Recommendation.APPLY_NOW
    elif tier is MatchTier.LONG_SHOT:
        recommendation = Recommendation.LIKELY_REJECTED
    else:
        recommendation = Recommendation.CONSIDER_APPLYING

    return ScoreResult(
        score=score,
        tier=tier,
        recommendation=recommendation,
        explanation=_explain(score, tier, components, hard_blockers, unknown),
        components=components,
        matched_skills=matched,
        missing_skills=missing,
        unknown_skills=unknown,
        evidence=[e.to_payload() for e in evidence_records],
        hard_blocker_warnings=hard_blockers,
        unknown_requirements=unknown_requirements,
        experience_gap_years=experience_gap,
    )


def _skills_component(
    name: str, texts: list[str], evidence: list[RequirementEvidence]
) -> ScoreComponent:
    """Score skill coverage: supported=full, unknown=unknown, else zero."""
    if not texts:
        return ScoreComponent(
            name,
            SCORING_RULES[name]["weight"],
            0,
            SCORING_RULES[name]["weight"] // 2,
            "No skill requirements on this side.",
        )
    total = float(SCORING_RULES[name]["weight"])
    per = total / len(texts)
    unknown_count = sum(1 for e in evidence if e.status is EvidenceStatus.UNKNOWN)
    supported = sum(1 for e in evidence if e.status is EvidenceStatus.SUPPORTED)
    # Partially-supported skills count half.
    partial = sum(1 for e in evidence if e.status is EvidenceStatus.PARTIALLY_SUPPORTED)
    earned = supported * per + 0.5 * partial * per
    unknown_weight = int(round(unknown_count * per))
    return ScoreComponent(
        name=name,
        weight=int(total),
        earned=earned,
        unknown_weight=unknown_weight,
        detail=f"{supported}/{len(texts)} supported"
        + (f", {unknown_count} unknown" if unknown_count else ""),
    )


def _experience_component(
    min_years: float | None,
    profile: Any,
    project_count: int,
) -> ScoreComponent:
    """Score professional experience against the stated requirement."""
    from app.models.enums import EvidenceStatus as _ES
    from app.scoring.evidence import map_experience_requirement

    experience = profile.professional_experience_years if profile else None
    ev = map_experience_requirement(min_years, experience, project_count)
    weight = SCORING_RULES["experience"]["weight"]
    if ev.status is _ES.SUPPORTED:
        return ScoreComponent("experience", weight, float(weight), 0, ev.explanation)
    if ev.status is _ES.PARTIALLY_SUPPORTED:
        return ScoreComponent("experience", weight, weight * 0.5, 0, ev.explanation)
    if ev.status is _ES.UNKNOWN:
        return ScoreComponent("experience", weight, 0, weight, ev.explanation)
    return ScoreComponent("experience", weight, 0, 0, ev.explanation)


def _location_component(job: Job, profile: Any) -> ScoreComponent:
    """Location/remote fit; unknown when either side lacks data."""

    weight = SCORING_RULES["location_remote"]["weight"]
    if profile is None:
        return ScoreComponent("location_remote", weight, 0, weight, "No profile data.")
    pref_remote = profile.remote_preference or "any"
    pref_locations = [str(x).lower() for x in (profile.preferred_locations or [])]
    job_is_remote = job.is_remote
    if job_is_remote is None and not job.location:
        return ScoreComponent("location_remote", weight, 0, weight, "Job location unknown.")
    if job_is_remote:
        if pref_remote == "onsite_only":
            return ScoreComponent(
                "location_remote", weight, 0, 0, "Remote job vs onsite-only preference."
            )
        return ScoreComponent(
            "location_remote", weight, float(weight), 0, "Remote job fits preference."
        )
    job_loc = (job.location or "").lower()
    if not pref_locations or not job_loc:
        return ScoreComponent(
            "location_remote",
            weight,
            0,
            weight // 2,
            "Insufficient data on one side (treated as partial fit).",
        )
    if any(loc in job_loc or job_loc in loc for loc in pref_locations):
        return ScoreComponent(
            "location_remote",
            weight,
            float(weight),
            0,
            f"Location '{job.location}' matches a preferred location.",
        )
    return ScoreComponent(
        "location_remote",
        weight,
        0,
        0,
        f"Location '{job.location}' differs from preferences (not a blocker).",
    )


def _work_auth_component(wa_rows: list[Any], profile: Any) -> ScoreComponent:
    """Work authorization: hard blocker only when clearly stated."""
    weight = SCORING_RULES["work_authorization"]["weight"]
    if not wa_rows:
        return ScoreComponent(
            "work_authorization", weight, 0, weight, "Job states no work-authorization requirement."
        )
    rights = (profile.user_rights or "").strip() if profile else ""
    if not rights:
        return ScoreComponent(
            "work_authorization",
            weight,
            0,
            weight,
            "Work authorization requirement, but candidate has not declared rights (unknown — review manually).",
        )
    return ScoreComponent(
        "work_authorization",
        weight,
        float(weight),
        0,
        "Candidate has declared work rights matching requirement presence.",
    )


def _renormalize_score(components: list[ScoreComponent]) -> int:
    """Compute the score, renormalizing away unknown weight.

    Known weight = total weight - unknown weight. Score = earned / known * 100.
    """
    total_known = sum(c.weight - c.unknown_weight for c in components)
    if total_known <= 0:
        return 0
    earned = sum(c.earned for c in components)
    return int(round(earned / total_known * 100))


def _explain(
    score: int,
    tier: MatchTier,
    components: list[ScoreComponent],
    hard_blockers: list[dict[str, Any]],
    unknown: list[str],
) -> str:
    """Build the human-readable score explanation."""
    parts = [
        f"Score {score} ({tier.value}): highest earned weight = "
        f"{max((c.earned for c in components), default=0):.0f}."
    ]
    strong_parts = [f"{c.name} ({c.detail})" for c in components if c.earned > 0]
    if strong_parts:
        parts.append("Strengths: " + "; ".join(strong_parts) + ".")
    if hard_blockers:
        parts.append(
            "Hard requirements to verify manually: "
            + "; ".join(b["requirement"] for b in hard_blockers)
            + "."
        )
    if unknown:
        parts.append(
            f"{len(unknown)} requirement(s) unknown from candidate data (not judged missing)."
        )
    return " ".join(parts)


def upsert_match(session: Session, user: User, job: Job) -> JobMatch:
    """Compute, store (or update) the JobMatch row; returns the row."""
    result = score_job_against_profile(user, job)
    existing = session.execute(
        select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id)
    ).scalar_one_or_none()

    payload = result.to_payload()
    if existing is None:
        match = JobMatch(
            user_id=user.id,
            job_id=job.id,
            score=payload["score"],
            tier=payload["tier"],
            recommendation=payload["recommendation"],
            explanation=payload["explanation"],
            score_components=payload["score_components"],
            matched_skills=payload["matched_skills"],
            missing_skills=payload["missing_skills"],
            unknown_skills=payload["unknown_skills"],
            evidence=payload["evidence"],
            hard_blocker_warnings=payload["hard_blocker_warnings"],
            unknown_requirements=payload["unknown_requirements"],
            experience_gap_years=payload["experience_gap_years"],
            scoring_rules_version=SCORING_RULES_VERSION,
        )
        session.add(match)
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.scoring_rules_version = SCORING_RULES_VERSION
        match = existing
    session.commit()
    return match
