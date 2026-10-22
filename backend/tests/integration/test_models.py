"""Database integration tests: constraints, relationships, cascades."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationEvent,
    Job,
    JobMatch,
    JobRequirement,
    Resume,
    TailoredResume,
    User,
    UserProfile,
)

pytestmark = pytest.mark.integration


def make_user(session: Session) -> User:
    user = User(email="cand@example.com", display_name="Candidate")
    session.add(user)
    session.commit()
    return user


def make_job(session: Session) -> Job:
    job = Job(
        source="adzuna",
        source_job_id="4445556667",
        canonical_url="https://example.com/job/1",
        original_url="https://example.com/job/1?tracking=1",
        title="Backend Engineer",
        company="ACME",
        location="Dubai",
        description="Python + SQL programming role",
    )
    session.add(job)
    session.commit()
    return job


def make_resume(session: Session, user: User) -> Resume:
    resume = Resume(
        user_id=user.id,
        kind="original",
        original_filename="cv.pdf",
        file_type="pdf",
        file_size_bytes=1024,
        file_path="data/uploads/test-cv.pdf",
        file_checksum_sha256="0" * 64,
    )
    session.add(resume)
    session.commit()
    return resume


def make_profile(session: Session, user: User) -> UserProfile:
    profile = UserProfile(user_id=user.id, professional_experience_years=Decimal("3.5"))
    session.add(profile)
    session.commit()
    return profile


def test_user_profile_one_to_one_with_unique_constraint(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session)
        profile = make_profile(session, user)
        assert profile.user_id == user.id
        # A second profile for the same user violates the unique constraint.
        session.add(UserProfile(user_id=user.id))
        with pytest.raises(IntegrityError):
            session.commit()


def test_jobs_unique_source_and_url(db: Engine) -> None:
    with Session(db) as session:
        make_job(session)
        dup = Job(
            source="adzuna",
            source_job_id="4445556667",
            canonical_url="https://example.com/job/1",
            original_url="https://example.com/job/1?tracking=1",
            title="Backend Engineer",
        )
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.commit()


def test_job_salary_check_constraint(db: Engine) -> None:
    with Session(db) as session:
        job = make_job(session)
        job.salary_min = 5000
        job.salary_max = 4000
        with pytest.raises(IntegrityError):
            session.commit()


def test_job_match_score_range_constraint(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session)
        job = make_job(session)
        match = JobMatch(
            user_id=user.id,
            job_id=job.id,
            score=101,
            tier="good",
            recommendation="consider_applying",
            scoring_rules_version="v1",
        )
        session.add(match)
        with pytest.raises(IntegrityError):
            session.commit()


def test_job_requirement_min_years_constraint(db: Engine) -> None:
    with Session(db) as session:
        job = make_job(session)
        session.add(
            JobRequirement(
                job_id=job.id,
                category="experience",
                text="3+ years backend",
                is_required=True,
                min_years=Decimal("-1"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_cascade_delete_job_removes_requirements(db: Engine) -> None:
    with Session(db) as session:
        job = make_job(session)
        session.add_all(
            [
                JobRequirement(job_id=job.id, category="required_skill", text="Python"),
                JobRequirement(job_id=job.id, category="preferred_skill", text="Docker"),
            ]
        )
        session.commit()
        assert len(job.requirements) == 2
        session.delete(job)
        session.commit()
        assert session.query(JobRequirement).count() == 0


def test_tailored_resume_pdf_requires_approval(db: Engine) -> None:
    """A tailored resume without approval must not carry a final PDF."""
    with Session(db) as session:
        user = make_user(session)
        resume = make_resume(session, user)
        job = make_job(session)
        tailored = TailoredResume(
            user_id=user.id,
            resume_id=resume.id,
            job_id=job.id,
            version=1,
            approval_status="draft",
            final_pdf_path="data/storage/unapproved.pdf",
        )
        session.add(tailored)
        with pytest.raises(IntegrityError):
            session.commit()


def test_application_unique_user_job_attempt(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session)
        job = make_job(session)
        session.add(Application(user_id=user.id, job_id=job.id))
        session.commit()
        session.add(Application(user_id=user.id, job_id=job.id))
        with pytest.raises(IntegrityError):
            session.commit()


def test_application_events_created(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session)
        job = make_job(session)
        app_ = Application(user_id=user.id, job_id=job.id, status="prepared")
        session.add(app_)
        session.flush()
        app_.events.append(
            ApplicationEvent(event_type="application.prepared", payload={"by": "ui"})
        )
        session.commit()
        assert len(app_.events) == 1
        assert app_.events[0].application_id == app_.id


def test_user_can_upload_multiple_original_resumes(db: Engine) -> None:
    with Session(db) as session:
        user = make_user(session)
        r1 = make_resume(session, user)
        r2 = Resume(
            user_id=user.id,
            kind="original",
            original_filename="cv2.pdf",
            file_type="pdf",
            file_size_bytes=2048,
            file_path="data/uploads/test-cv2.pdf",
            file_checksum_sha256="1" * 64,
        )
        session.add(r2)
        session.commit()
        assert r1.id != r2.id
