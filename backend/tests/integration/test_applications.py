"""Integration tests for application tracking (requires PostgreSQL)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationEvent,
    Job,
    Resume,
    TailoredResume,
    User,
    UserProfile,
)
from app.schemas.jobs import NormalizedJob
from app.services.applications import (
    ApplicationError,
    check_availability,
    confirm_submitted,
    create_application,
    get_application,
    update_status,
)
from app.services.ingestion import run_ingestion

pytestmark = pytest.mark.integration


def normalized(**overrides: object) -> NormalizedJob:
    data: dict[str, object] = {
        "source": "adzuna",
        "source_job_id": "100",
        "title": "Backend Engineer",
        "original_url": "https://jobs.example.com/100",
        "canonical_url": "https://jobs.example.com/100",
        "company": "ACME",
        "location": "Dubai",
        "description": "Python and SQL required.",
        "posted_at": "2026-10-01T09:00:00Z",
    }
    data.update(overrides)
    return NormalizedJob.model_validate(data)


@pytest.fixture
def job(db: Engine) -> str:
    with Session(db) as session:
        run_ingestion(session, [normalized()])
        return str(session.query(Job).first().id)  # type: ignore[union-attr]


@pytest.fixture
def user(db: Engine) -> str:
    with Session(db) as session:
        u = User(email="appuser@example.com", display_name="App User")
        session.add(u)
        session.flush()
        session.add(UserProfile(user_id=u.id))
        session.commit()
        return str(u.id)


@pytest.fixture
def other_user(db: Engine) -> str:
    with Session(db) as session:
        u = User(email="other@example.com", display_name="Other User")
        session.add(u)
        session.flush()
        session.add(UserProfile(user_id=u.id))
        session.commit()
        return str(u.id)


def _user(session: Session, user_id: str) -> User:
    """Load the real User row so service calls are type-correct."""
    found = session.get(User, user_id)
    assert found is not None
    return found


def _original_resume(session: Session, user_id: str) -> Resume:
    """Insert a minimal valid original CV and return it."""
    row = Resume(
        user_id=user_id,
        original_filename="cv.pdf",
        file_type="pdf",
        file_size_bytes=64,
        file_path="test-uploads/cv.pdf",
        file_checksum_sha256="0" * 64,
        parsed_content={"skills": ["Python"]},
        parse_notes=[],
    )
    session.add(row)
    session.flush()
    return row


def _tailored(db: Engine, user_id: str, job_id: str) -> str:
    """Create an approved tailored resume for (user, job); return its id."""
    with Session(db) as session:
        resume = _original_resume(session, user_id)
        tailored = TailoredResume(
            user_id=user_id,
            resume_id=resume.id,
            job_id=job_id,
            approval_status="approved",
            content={"title": "Backend Engineer", "sections": []},
            unsupported_claims=[],
        )
        session.add(tailored)
        session.commit()
        return str(tailored.id)


def _app_id(db: Engine, user_id: str, job_id: str) -> str:
    with Session(db) as session:
        row = session.execute(
            select(Application).where(Application.user_id == user_id, Application.job_id == job_id)
        ).scalar_one()
        return str(row.id)


def _events(db: Engine, application_id: str) -> list[ApplicationEvent]:
    with Session(db) as session:
        return list(
            session.execute(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application_id)
                .order_by(ApplicationEvent.occurred_at.asc())
            ).scalars()
        )


def test_create_is_get_or_create_with_created_event(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        first = create_application(session, _user(session, user), job)
        second = create_application(session, _user(session, user), job)
        assert str(first.id) == str(second.id)
        assert session.query(Application).count() == 1
        assert second.status == "queued"
    events = _events(db, str(first.id))
    assert [e.event_type for e in events] == ["application_created"]


def test_duplicate_via_api_returns_same_application(api: TestClient, job: str) -> None:
    first = api.post("/applications", json={"job_id": job})
    assert first.status_code == 201
    second = api.post("/applications", json={"job_id": job})
    assert second.status_code in (200, 201)
    assert first.json()["id"] == second.json()["id"]
    board = api.get("/applications").json()
    assert len(board["items"]) == 1
    assert board["items"][0]["status"] == "queued"


def test_create_with_missing_job_is_404(api: TestClient) -> None:
    assert api.post("/applications", json={"job_id": str(uuid.uuid4())}).status_code == 404
    assert api.post("/applications", json={"job_id": "not-a-uuid"}).status_code == 404


def test_status_change_creates_exactly_one_event(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
    for target in ("prepared", "submitted"):
        with Session(db) as session:
            _, changed = update_status(session, _user(session, user), app_id, target)
            assert changed is True
    assert len(_events(db, app_id)) == 3  # created + 2 status changes

    # Idempotent repeat: same status, no new event, changed False.
    with Session(db) as session:
        _, changed = update_status(session, _user(session, user), app_id, "submitted")
        assert changed is False
    assert len(_events(db, app_id)) == 3

    with Session(db) as session:
        app_row = get_application(session, _user(session, user), app_id)
        assert app_row.status == "submitted"
    last = _events(db, app_id)[-1]
    assert last.event_type == "status_change"
    assert last.payload["previous_status"] == "prepared"
    assert last.payload["new_status"] == "submitted"
    assert last.payload["actor"] == "user"


def test_invalid_transition_rejected_without_event(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            update_status(session, _user(session, user), app_id, "offer")
        assert exc.value.code == "invalid_transition"
    with Session(db) as session:
        assert get_application(session, _user(session, user), app_id).status == "queued"
    assert len(_events(db, app_id)) == 1  # only the created event


def test_unknown_status_value_is_422(api: TestClient, job: str) -> None:
    resp = api.post("/applications", json={"job_id": job})
    app_id = resp.json()["id"]
    bad = api.post(f"/applications/{app_id}/status", json={"status": "hired"})
    assert bad.status_code == 422


def test_confirm_submitted_sets_timestamp_and_single_event(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        before = datetime.now(UTC)
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
        row, changed = confirm_submitted(
            session, _user(session, user), app_id, external_ref="ref-123"
        )
        assert changed is True
        assert row.status == "submitted"
        assert row.submitted_at is not None and row.submitted_at > before - timedelta(seconds=5)
        assert row.submitted_at.tzinfo is not None

    # Unknown UUID / fresh row safety: no double event on repeat.
    with Session(db) as session:
        _, changed = confirm_submitted(session, _user(session, user), app_id)
        assert changed is False
    events = _events(db, app_id)
    assert [e.event_type for e in events].count("submission_confirmed") == 1
    confirm = next(e for e in events if e.event_type == "submission_confirmed")
    assert confirm.payload["previous_status"] == "queued"
    assert confirm.payload["new_status"] == "submitted"
    assert confirm.payload["external_reference"] == "ref-123"


def test_confirm_submitted_invalid_from_later_states(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
        confirm_submitted(session, _user(session, user), app_id)
        update_status(session, _user(session, user), app_id, "interviewing")
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            confirm_submitted(session, _user(session, user), app_id)
        assert exc.value.code == "invalid_transition"
    with Session(db) as session:
        row = get_application(session, _user(session, user), app_id)
        first_submitted_at = row.submitted_at
        assert first_submitted_at is not None
        assert row.status == "interviewing"  # failed confirm changed nothing
    # No additional submission events.
    assert [e.event_type for e in _events(db, app_id)].count("submission_confirmed") == 1


def test_cross_user_access_is_not_found(db: Engine, user: str, other_user: str, job: str) -> None:
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            get_application(session, _user(session, other_user), app_id)
        assert exc.value.code == "not_found"
        with pytest.raises(ApplicationError):
            update_status(session, _user(session, other_user), app_id, "prepared")


def test_event_insert_failure_rolls_back_status(db: Engine, user: str, job: str) -> None:
    """If the event insert fails, the status update must roll back too."""
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
    with db.connect() as conn:
        conn.execute(text("ALTER TABLE application_events RENAME TO application_events_moved"))
        conn.commit()
    try:
        with Session(db) as session:
            with pytest.raises(Exception):  # noqa: B017 - any DB error is fine here
                update_status(session, _user(session, user), app_id, "prepared")
            session.rollback()
    finally:
        with db.connect() as conn:
            conn.execute(text("ALTER TABLE application_events_moved RENAME TO application_events"))
            conn.commit()
    with Session(db) as session:
        row = get_application(session, _user(session, user), app_id)
        assert row.status == "queued"  # rollback happened: no partial update
        assert len(_events(db, app_id)) == 1  # only the created event survives


def test_status_update_takes_row_lock(db: Engine, user: str, job: str) -> None:
    """A concurrent session holding the row lock must block update_status."""
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
    locked = Session(db)
    locked.execute(select(Application).where(Application.id == app_id).with_for_update())
    try:
        blocker = Session(db)
        blocker.execute(text("SET lock_timeout = '300ms'"))
        blocker.commit()
        with Session(db) as session:
            session.execute(text("SET lock_timeout = '300ms'"))
            session.commit()
            with pytest.raises(OperationalError):
                update_status(session, _user(session, user), app_id, "prepared")
    finally:
        locked.rollback()
        locked.close()
    # Lock released: now the update succeeds.
    with Session(db) as session:
        _, changed = update_status(session, _user(session, user), app_id, "prepared")
        assert changed is True


def test_availability_outcomes(db: Engine, user: str, job: str) -> None:
    with Session(db) as session:
        j = session.query(Job).first()
        assert j is not None
        assert check_availability(j)["outcome"] == "unknown"
        j.is_active = False
        j.is_expired = True
        assert check_availability(j)["outcome"] == "closed"
        j.source = "manual"
        assert check_availability(j)["outcome"] == "unknown"
        assert check_availability(None)["outcome"] == "unknown"

    # Availability is reported independently of the application status.
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
        row = get_application(session, _user(session, user), app_id)
        assert row.status == "queued"


def test_api_board_and_timeline_shape(api: TestClient, job: str) -> None:
    resp = api.post("/applications", json={"job_id": job})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["allowed_transitions"] == ["closed", "prepared", "withdrawn"]
    assert body["job_company"] == "ACME"
    app_id = body["id"]

    ev = api.get(f"/applications/{app_id}/events").json()
    assert ev and ev[0]["event_type"] == "application_created"
    assert ev[0]["payload"]["actor"] == "user"

    detail = api.get(f"/applications/{app_id}").json()
    assert detail["job_title"] == "Backend Engineer"

    missing = api.get(f"/applications/{uuid.uuid4()}/events")
    assert missing.status_code == 404

    # Foreign application id of another user must not leak data: dev user is
    # the only API user; direct service-level cross-user test covers others.
    foreign = api.get(f"/applications/{app_id}/availability")
    assert foreign.status_code == 200
    assert foreign.json()["outcome"] in ("open", "closed", "unknown")


# --- Phase 2.2: assisted apply — tailored resume validation -------------------


def test_create_with_matching_tailored_resume(db: Engine, user: str, job: str) -> None:
    tailored_id = _tailored(db, user, job)
    with Session(db) as session:
        app_row = create_application(
            session, _user(session, user), job, tailored_resume_id=tailored_id
        )
        assert str(app_row.tailored_resume_id) == tailored_id
        assert app_row.status == "queued"
    events = _events(db, str(app_row.id))
    assert [e.event_type for e in events] == ["application_created"]


def test_create_with_missing_or_malformed_resume_id(db: Engine, user: str, job: str) -> None:
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        with Session(db) as session:
            with pytest.raises(ApplicationError) as exc:
                create_application(session, _user(session, user), job, tailored_resume_id=bad)
            assert exc.value.code == "not_found"
    with Session(db) as session:
        assert session.query(Application).count() == 0


def test_create_with_foreign_resume_is_not_found(
    db: Engine, user: str, other_user: str, job: str
) -> None:
    foreign_tailored = _tailored(db, other_user, job)
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            create_application(
                session, _user(session, user), job, tailored_resume_id=foreign_tailored
            )
        assert exc.value.code == "not_found"  # existence of foreign rows is not leaked
    with Session(db) as session:
        assert session.query(Application).count() == 0


def test_create_with_resume_for_different_job_is_conflict(db: Engine, user: str, job: str) -> None:
    # A second job plus a tailored resume bound to that second job.
    with Session(db) as session:
        run_ingestion(
            session,
            [
                normalized(
                    source="linkedin",
                    source_job_id="200",
                    title="Senior Data Engineer",
                    canonical_url="https://jobs.example.com/200",
                    original_url="https://jobs.example.com/200",
                )
            ],
        )
        rows = session.execute(select(Job)).scalars().all()
        assert len(rows) == 2
        other_job = next(r for r in rows if str(r.id) != job)
        resume = _original_resume(session, user)
        tailored = TailoredResume(
            user_id=user,
            resume_id=resume.id,
            job_id=other_job.id,
            approval_status="approved",
            content={"sections": []},
            unsupported_claims=[],
        )
        session.add(tailored)
        session.commit()
        tailored_id = str(tailored.id)
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            create_application(session, _user(session, user), job, tailored_resume_id=tailored_id)
        assert exc.value.code == "conflict"
    with Session(db) as session:
        assert session.query(Application).count() == 0


def test_existing_application_does_not_bypass_resume_validation(
    db: Engine, user: str, other_user: str, job: str
) -> None:
    other_tailored = _tailored(db, other_user, job)
    with Session(db) as session:
        app_row = create_application(session, _user(session, user), job)
        app_id = str(app_row.id)
        assert app_row.tailored_resume_id is None
    # Repeated requests with an invalid resume must still be rejected.
    bad_cases = [
        (str(uuid.uuid4()), "not_found"),  # nonexistent resume
        ("zzz", "not_found"),  # malformed resume id
        (other_tailored, "not_found"),  # foreign resume for the same job
    ]
    for bad_id, expected_code in bad_cases:
        with Session(db) as session:
            with pytest.raises(ApplicationError) as exc:
                create_application(session, _user(session, user), job, tailored_resume_id=bad_id)
            assert exc.value.code == expected_code
    # A resume bound to a different job is rejected even for an existing row.
    with Session(db) as session:
        run_ingestion(
            session,
            [
                normalized(
                    source="linkedin",
                    source_job_id="200",
                    title="Senior Data Engineer",
                    canonical_url="https://jobs.example.com/200",
                    original_url="https://jobs.example.com/200",
                )
            ],
        )
        resume = _original_resume(session, user)
        other_job = session.execute(select(Job).where(Job.id != job)).scalars().first()
        assert other_job is not None
        tailored = TailoredResume(
            user_id=user,
            resume_id=resume.id,
            job_id=other_job.id,
            approval_status="approved",
            content={"sections": []},
            unsupported_claims=[],
        )
        session.add(tailored)
        session.commit()
        tailored_id = str(tailored.id)
    with Session(db) as session:
        with pytest.raises(ApplicationError) as exc:
            create_application(session, _user(session, user), job, tailored_resume_id=tailored_id)
        assert exc.value.code == "conflict"
    with Session(db) as session:
        row = session.get(Application, app_id)
        assert row is not None
        assert row.status == "queued"
        assert row.tailored_resume_id is None
    assert len(_events(db, app_id)) == 1  # no extra events from the rejected requests


def test_duplicate_creation_remains_idempotent_with_resume(db: Engine, user: str, job: str) -> None:
    tailored_id = _tailored(db, user, job)
    with Session(db) as session:
        first = create_application(
            session, _user(session, user), job, tailored_resume_id=tailored_id
        )
        second = create_application(
            session, _user(session, user), job, tailored_resume_id=tailored_id
        )
        assert str(first.id) == str(second.id)
        assert session.query(Application).count() == 1
    assert len(_events(db, str(first.id))) == 1


def test_status_flow_unchanged_with_tailored_resume(db: Engine, user: str, job: str) -> None:
    """Confirmed submission right still works when a resume was attached."""
    tailored_id = _tailored(db, user, job)
    with Session(db) as session:
        app_row = create_application(
            session, _user(session, user), job, tailored_resume_id=tailored_id
        )
        app_id = str(app_row.id)
        _, changed = update_status(session, _user(session, user), app_id, "prepared")
        assert changed is True
        row, changed = confirm_submitted(session, _user(session, user), app_id)
        assert changed is True and row.status == "submitted"
    assert len(_events(db, app_id)) == 3


def test_api_rejects_invalid_and_mismatched_tailored_resume(
    api: TestClient, db: Engine, job: str, api_user: str
) -> None:
    """Response codes through the API: 404 unknown/malformed, 409 mismatch."""
    with Session(db) as session:
        owner = session.execute(select(User).where(User.email == api_user)).scalar_one()
        assert owner is not None
        owner_id = str(owner.id)
        run_ingestion(
            session,
            [
                normalized(
                    source="linkedin",
                    source_job_id="300",
                    title="Senior Data Engineer",
                    canonical_url="https://jobs.example.com/300",
                    original_url="https://jobs.example.com/300",
                )
            ],
        )
        rows = session.execute(select(Job)).scalars().all()
        assert len(rows) >= 2
        other_job = next(r for r in rows if str(r.id) != job)
        resume = _original_resume(session, owner_id)
        matching = TailoredResume(
            user_id=owner_id,
            resume_id=resume.id,
            job_id=job,
            approval_status="approved",
            content={"sections": []},
            unsupported_claims=[],
        )
        mismatched = TailoredResume(
            user_id=owner_id,
            resume_id=resume.id,
            job_id=other_job.id,
            approval_status="approved",
            content={"sections": []},
            unsupported_claims=[],
        )
        session.add_all([matching, mismatched])
        session.commit()
        matching_id = str(matching.id)
        mismatched_id = str(mismatched.id)

    assert (
        api.post(
            "/applications", json={"job_id": job, "tailored_resume_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )
    assert (
        api.post(
            "/applications", json={"job_id": job, "tailored_resume_id": "not-a-uuid"}
        ).status_code
        == 404
    )
    resp = api.post("/applications", json={"job_id": job, "tailored_resume_id": mismatched_id})
    assert resp.status_code == 409
    assert "different job" in resp.json()["detail"]

    ok = api.post("/applications", json={"job_id": job, "tailored_resume_id": matching_id})
    assert ok.status_code == 201
    assert ok.json()["tailored_resume_id"] == matching_id
    assert ok.json()["status"] == "queued"

    # Duplicate creation via the API stays idempotent.
    again = api.post("/applications", json={"job_id": job, "tailored_resume_id": matching_id})
    assert again.json()["id"] == ok.json()["id"]
