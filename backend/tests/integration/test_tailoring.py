"""Integration tests: tailored-CV draft/approve/reject workflow and PDF."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.main import app
from app.models import Job, JobRequirement, Resume, User, UserProfile
from app.services.tailoring import (
    TailoringError,
    approve_tailored,
    create_tailored_draft,
    reject_tailored,
    submit_for_review,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def workflow_data(db: Engine, api_user: str) -> dict[str, str]:
    """Persist the API user, an original resume, and a job with requirements."""
    with Session(db) as session:
        user = session.execute(select(User).where(User.email == api_user)).scalar_one()
        assert user is not None
        if user.user_profile is None:
            from app.models import UserSession  # noqa: F401  (keep models loaded)

            session.add(UserProfile(user_id=user.id, skills=["Python", "SQL", "Docker"]))
        resume = Resume(
            user_id=user.id,
            kind="original",
            original_filename="cv.txt",
            file_type="txt",
            file_size_bytes=100,
            file_path="stored-uploads/cv.txt",
            file_checksum_sha256="0" * 64,
            parsed_content={
                "experiences": [
                    {
                        "title": "Backend Engineer",
                        "company": "ACME",
                        "bullets": [
                            "Built 3 REST APIs in Python with Django",
                            "Reduced query time by 40% via SQL indexing",
                        ],
                    }
                ],
                "skills": ["Python", "SQL", "Docker"],
                "projects": ["Buildtool: open-source packaging tool in Python"],
                "certifications": ["AWS Cloud Practitioner"],
                "education": [
                    {"degree": "BSc Computer Science", "institution": "XYZ", "year": "2021"}
                ],
            },
            parse_notes=[],
        )
        session.add(resume)
        job = Job(
            source="adzuna",
            source_job_id="T1",
            title="Backend Engineer",
            canonical_url="https://jobs.example.com/t1",
            original_url="https://jobs.example.com/t1",
            description="Python, SQL, Docker required.",
            is_remote=False,
        )
        session.add(job)
        session.flush()
        session.add(
            JobRequirement(
                job_id=job.id, category="required_skill", text="Python", is_required=True
            )
        )
        session.add(
            JobRequirement(job_id=job.id, category="required_skill", text="SQL", is_required=True)
        )
        session.commit()
        return {"user_id": user.id, "resume_id": resume.id, "job_id": job.id}


def draft_content_pool() -> set[str]:
    """Verbatim texts the deterministic fallback is allowed to emit."""
    skills = ["Python", "SQL", "Docker"]
    project = "Buildtool: open-source packaging tool in Python"
    cert = "AWS Cloud Practitioner"
    education = "BSc Computer Science | XYZ"
    exp_bullets = [
        "Built 3 REST APIs in Python with Django",
        "Reduced query time by 40% via SQL indexing",
    ]
    return set(skills + [project, cert, education] + exp_bullets)


def test_full_approval_flow_produces_pdf(db: Engine, workflow_data) -> None:  # type: ignore[no-untyped-def]
    with Session(db) as session:
        user = session.get(User, workflow_data["user_id"])
        assert user is not None
        draft = create_tailored_draft(
            session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
        )
        assert draft.approval_status == "draft"
        assert draft.version == 1
        # Deterministic fallback: every bullet must be verbatim original text.
        bullets = [
            item["text"] for section in draft.content["sections"] for item in section["items"]
        ]
        parsed = draft_content_pool()
        assert bullets, "fallback must keep original content"
        assert set(bullets) <= parsed
        assert draft.unsupported_claims == []

        submitted = submit_for_review(session, user, draft.id)
        assert submitted.approval_status == "pending_review"
        assert submitted.final_pdf_path is None  # not exported before approval

        approved = approve_tailored(session, user, draft.id)
        assert approved.approval_status == "approved"
        assert approved.approved_at is not None
        assert approved.final_pdf_path is not None
        from pathlib import Path

        assert Path(str(approved.final_pdf_path)).is_file()
        assert Path(str(approved.final_pdf_path)).read_bytes().startswith(b"%PDF")


def test_second_draft_increments_version(db: Engine, workflow_data) -> None:  # type: ignore[no-untyped-def]
    with Session(db) as session:
        user = session.get(User, workflow_data["user_id"])
        assert user is not None
        first = create_tailored_draft(
            session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
        )
        second = create_tailored_draft(
            session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
        )
        assert second.version == first.version + 1
        # Original row untouched (same file refs).
        resume = session.get(Resume, workflow_data["resume_id"])
        assert resume is not None and resume.parsed_content


def test_pdf_export_blocked_for_drafts(db: Engine, workflow_data) -> None:  # type: ignore[no-untyped-def]
    from app.schemas.tailoring import TailoredContent
    from app.tailoring.pdf import export_pdf

    with Session(db) as session:
        user = session.get(User, workflow_data["user_id"])
        assert user is not None
        draft = create_tailored_draft(
            session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
        )
        with pytest.raises(ValueError, match="approved"):
            export_pdf(draft, TailoredContent.model_validate(draft.content))


def test_reject_and_re_submit(db: Engine, workflow_data) -> None:  # type: ignore[no-untyped-def]
    with Session(db) as session:
        user = session.get(User, workflow_data["user_id"])
        assert user is not None
        draft = create_tailored_draft(
            session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
        )
        rejected = reject_tailored(session, user, draft.id)
        assert rejected.approval_status == "rejected"
        resubmitted = submit_for_review(session, user, draft.id)
        assert resubmitted.approval_status == "pending_review"


def test_missing_requirements_rejected(db: Engine, workflow_data) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import delete

    with Session(db) as session:
        session.execute(delete(JobRequirement))
        session.commit()
        user = session.get(User, workflow_data["user_id"])
        assert user is not None
        with pytest.raises(TailoringError, match="extract job requirements"):
            create_tailored_draft(
                session, user, workflow_data["resume_id"], workflow_data["job_id"], use_ai=False
            )


def test_api_workflow_roundtrip(api: TestClient, workflow_data) -> None:  # type: ignore[no-untyped-def]
    tok = workflow_data
    created = api.post(
        f"/tailored?resume_id={tok['resume_id']}&job_id={tok['job_id']}&use_ai=false"
    )
    assert created.status_code == 201
    drafted = created.json()
    tid = drafted["id"]

    assert api.post(f"/tailored/{tid}/submit").status_code == 200
    approved = api.post(f"/tailored/{tid}/approve")
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"

    pdf = api.get(f"/tailored/{tid}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"

    listed = api.get("/tailored")
    assert any(row["id"] == tid for row in listed.json())

    rejected = api.post(f"/tailored/{tid}/reject")
    assert rejected.status_code == 400  # cannot reject an approved version


def test_api_pdf_404_for_draft(api: TestClient, workflow_data) -> None:  # type: ignore[no-untyped-def]
    tok = workflow_data
    created = api.post(
        f"/tailored?resume_id={tok['resume_id']}&job_id={tok['job_id']}&use_ai=false"
    )
    tid = created.json()["id"]
    assert api.get(f"/tailored/{tid}/pdf").status_code == 404


def test_pdf_and_tailored_isolation_for_foreign_user(
    api: TestClient, workflow_data: dict[str, str]
) -> None:
    """A second account cannot read or download another user's tailored CV."""
    tok = workflow_data
    created = api.post(
        f"/tailored?resume_id={tok['resume_id']}&job_id={tok['job_id']}&use_ai=false"
    )
    assert created.status_code == 201
    tid = created.json()["id"]
    assert api.post(f"/tailored/{tid}/approve").status_code == 200
    # Owner can fetch the exported PDF (proves the file path is real).
    assert api.get(f"/tailored/{tid}/pdf").status_code == 200

    reg = TestClient(app).post(
        "/auth/register",
        json={"email": "pdf-stranger@example.com", "password": "stranger-pass-1"},
    )
    assert reg.status_code == 201
    stranger = TestClient(app, headers={"Authorization": f"Bearer {reg.json()['token']}"})

    # Listing empty, detail 404, and the file-serving route 404s too —
    # no bytes of the owner's PDF leave the server.
    assert stranger.get("/tailored").json() == []
    assert stranger.get(f"/tailored/{tid}").status_code == 404
    foreign_pdf = stranger.get(f"/tailored/{tid}/pdf")
    assert foreign_pdf.status_code == 404
