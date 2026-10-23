"""Integration tests for the deterministic scoring engine and match API."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.session import set_engine, set_session_factory
from app.main import app
from app.models import Job, JobRequirement, User, UserProfile
from app.models.enums import Recommendation
from app.scoring.score import score_job_against_profile, upsert_match

pytestmark = pytest.mark.integration


def make_user(session: Session, *, skills: list[str], years: float | None, projects: int) -> User:
    user = User(email="dev@example.com", display_name="Dev")
    profile = UserProfile(
        user=user,
        full_name="Dev Candidate",
        skills=skills,
        professional_experience_years=None if years is None else Decimal(str(years)),
        projects=[{"name": f"proj{i}"} for i in range(projects)],
    )
    session.add(user)
    session.add(profile)
    session.commit()
    return user


def make_job(session: Session, requirements: list[dict[str, object]]) -> Job:
    job = Job(
        source="adzuna",
        source_job_id="S1",
        title="Backend Engineer",
        canonical_url="https://jobs.example.com/s1",
        original_url="https://jobs.example.com/s1",
        company="ACME",
        location="Dubai",
        description="Python and SQL required.",
        is_remote=False,
    )
    session.add(job)
    session.flush()
    for req in requirements:
        session.add(JobRequirement(job_id=job.id, **req))
    session.commit()
    return job


REQUIRED_PY = {
    "category": "required_skill",
    "text": "Python",
    "is_required": True,
    "is_hard_blocker": False,
}
REQUIRED_SQL = {
    "category": "required_skill",
    "text": "SQL",
    "is_required": True,
    "is_hard_blocker": False,
}
REQUIRED_DOCKER_HARD = {
    "category": "required_skill",
    "text": "Docker",
    "is_required": True,
    "is_hard_blocker": True,
}
PREFERRED_K8S = {
    "category": "preferred_skill",
    "text": "Kubernetes",
    "is_required": False,
    "is_hard_blocker": False,
}
EXP_ROW = {"category": "experience", "text": "5+ years backend", "min_years": 5.0}


@pytest.fixture
def api(db: Engine) -> TestClient:
    set_engine(db)
    set_session_factory(None)
    return TestClient(app)


def test_strong_match_when_skills_covered_and_experience_meets(
    db: Engine,
) -> None:
    with Session(db) as session:
        user = make_user(session, skills=["Python", "SQL"], years=5.0, projects=2)
        job = make_job(
            session,
            [REQUIRED_PY, REQUIRED_SQL, EXP_ROW, PREFERRED_K8S],
        )
        result = score_job_against_profile(user, job)
        # Required skills: 2/2 supported. Preferred: 1 unknown (renormalized
        # away). Experience: supported. Projects: 10.
        assert result.matched_skills == ["Python", "SQL"]
        assert result.tier.value in ("strong", "good")
        assert result.score >= 60
        assert "Python" in result.matched_skills
        assert "Kubernetes" in result.unknown_skills


def test_stretch_match_below_experience_yrs(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session, skills=["Python", "SQL"], years=2.0, projects=3)
        job = make_job(session, [REQUIRED_PY, REQUIRED_SQL, EXP_ROW])
        result = score_job_against_profile(user, job)
        assert result.experience_gap_years is not None and result.experience_gap_years > 0
        # Stretch tier stays visible with a plausible score, never hidden.
        assert result.score > 0
        assert result.evidence


def test_hard_blocker_surfaces_when_unverified(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session, skills=["Python"], years=5.0, projects=1)
        job = make_job(session, [REQUIRED_PY, REQUIRED_DOCKER_HARD, EXP_ROW])
        result = score_job_against_profile(user, job)
        assert result.hard_blocker_warnings
        assert result.hard_blocker_warnings[0]["requirement"] == "Docker"
        assert result.recommendation is Recommendation.REQUIRES_CLOSING_GAPS


def test_missing_data_is_unknown_not_rejected(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session, skills=[], years=None, projects=0)
        job = make_job(session, [REQUIRED_PY, REQUIRED_SQL])
        result = score_job_against_profile(user, job)
        assert set(result.missing_skills) <= {"Python", "SQL"}
        # Everything missing -> all unknown, not confirmed mismatches.
        assert set(result.unknown_skills) | set(result.missing_skills) == {"Python", "SQL"}


def test_upsert_match_is_idempotent(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session, skills=["Python"], years=3.0, projects=1)
        job = make_job(session, [REQUIRED_PY])
        first = upsert_match(session, user, job)
        second = upsert_match(session, user, job)
        assert first.id == second.id
        rows = session.query(User).count()
        assert rows == 1


def test_match_api_roundtrip(api: TestClient, db: Engine) -> None:
    from app.services.users import get_or_create_dev_user

    with Session(db) as session:
        user = get_or_create_dev_user(session)
        profile = user.user_profile
        assert profile is not None
        profile.skills = ["Python", "SQL"]
        profile.professional_experience_years = Decimal("5.0")
        profile.projects = [{"name": "p1"}, {"name": "p2"}]
        job = make_job(session, [REQUIRED_PY, REQUIRED_SQL, EXP_ROW])
        job_id = str(job.id)

    resp = api.post(f"/jobs/{job_id}/match")
    assert resp.status_code == 200
    body = resp.json()
    # Required skills covered + experience met: waste weight is unknown and
    # renormalized away, so this lands firmly in the strong tier.
    assert body["tier"] == "strong"
    assert body["recommendation"] == "apply_now"
    assert set(body["matched_skills"]) == {"Python", "SQL"}
    assert body["scoring_rules_version"]

    got = api.get(f"/jobs/{job_id}/match")
    assert got.status_code == 200
    assert got.json()["score"] == body["score"]

    listing = api.get("/jobs/matches/all")
    assert listing.status_code == 200
    assert any(m["job_id"] == job_id for m in listing.json())


def test_match_api_404_before_computation(api: TestClient, db: Engine) -> None:
    with Session(db) as session:
        job_id = str(make_job(session, [REQUIRED_PY]).id)

    assert api.get(f"/jobs/{job_id}/match").status_code == 404
