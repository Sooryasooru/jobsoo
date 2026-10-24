"""Integration tests for the auth API and cross-user isolation (PostgreSQL)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.main import app
from app.models import Job, Resume, TailoredResume, User, UserSession
from app.schemas.jobs import NormalizedJob
from app.services.ingestion import run_ingestion
from app.services.resumes import upload_resume

pytestmark = pytest.mark.integration

_CREDENTIAL = "valid-pass-123"


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


def api_register(
    client: TestClient, email: str, password: str = _CREDENTIAL, display_name: str = "T"
) -> dict[str, str]:
    """Register through the API; returns {"email", "user_id", "token"}.

    The `db` fixture recreates all tables per test, so fixed emails stay unique.
    """
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"email": body["user"]["email"], "user_id": body["user"]["id"], "token": body["token"]}


def client_for(token: str) -> TestClient:
    """TestClient authenticated as the given token's user."""
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_register_creates_account_and_session(api: TestClient) -> None:
    body = api_register(api, "alice@example.com")
    me = client_for(body["token"]).get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == body["email"]


def test_register_provisions_profile_and_rejects_duplicates(api: TestClient) -> None:
    first = api.post("/auth/register", json={"email": "dup@example.com", "password": _CREDENTIAL})
    assert first.status_code == 201
    profile = client_for(str(first.json()["token"])).get("/profile")
    assert profile.status_code == 200  # profile provisioned at registration

    duplicate = api.post(
        "/auth/register", json={"email": "DuP@Example.com", "password": _CREDENTIAL}
    )
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": _CREDENTIAL},
        {"email": "ok@example.com", "password": "short"},
    ],
)
def test_register_rejects_invalid_payloads(api: TestClient, payload: dict[str, str]) -> None:
    response = api.post("/auth/register", json=payload)
    assert response.status_code == 422


def test_login_success_and_failure_are_consistent(api: TestClient) -> None:
    api_register(api, "login@example.com")
    good = api.post("/auth/login", json={"email": "login@example.com", "password": _CREDENTIAL})
    assert good.status_code == 200
    assert good.json()["token"]

    wrong = api.post(
        "/auth/login", json={"email": "login@example.com", "password": "nope-nope-nope"}
    )
    unknown = api.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    # Identical error message for both (no account enumeration).
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_email_normalization_merges_case_variants(api: TestClient) -> None:
    api_register(api, "case@example.com")
    login = api.post("/auth/login", json={"email": "Case@Example.COM", "password": _CREDENTIAL})
    assert login.status_code == 200


def test_plaintext_password_never_stored(api: TestClient, db: Engine) -> None:
    api_register(api, "hash@example.com", password="plaintext-never-123")
    with Session(db) as session:
        row = session.execute(select(User).where(User.email == "hash@example.com")).scalar_one()
        assert row.password_hash is not None
        assert row.password_hash.startswith("$argon2")
        assert "plaintext-never-123" not in row.password_hash


def test_unauthenticated_access_to_protected_routes(api: TestClient) -> None:
    api_register(api, "anyone@example.com")
    anon = TestClient(app)
    assert anon.post("/applications", json={"job_id": "x"}).status_code == 401
    assert anon.get("/applications").status_code == 401
    assert anon.get("/cvs").status_code == 401
    assert anon.get("/tailored").status_code == 401
    assert anon.get("/profile").status_code == 401
    assert anon.get("/auth/me").status_code == 401
    assert anon.get("/jobs/matches/all").status_code == 401
    # Health stays public.
    assert anon.get("/health").status_code == 200


def test_garbage_and_expired_tokens_are_rejected(api: TestClient, db: Engine) -> None:
    api_register(api, "expiry@example.com")
    garbage = TestClient(app, headers={"Authorization": "Bearer not-a-real-token"})
    assert garbage.get("/applications").status_code == 401
    malformed = TestClient(app, headers={"Authorization": "Basic abc"})
    assert malformed.get("/applications").status_code == 401

    raw = "e" * 64
    with Session(db) as session:
        row = session.execute(select(User)).scalars().first()
        assert row is not None
        session.add(
            UserSession(
                user_id=row.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        session.commit()
    expired = client_for(raw)
    assert expired.get("/applications").status_code == 401


def test_me_logout_and_session_invalidation(api: TestClient) -> None:
    user = api_register(api, "session@example.com")
    me = client_for(user["token"]).get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == user["email"]

    logout = client_for(user["token"]).post("/auth/logout")
    assert logout.status_code == 204
    assert client_for(user["token"]).get("/auth/me").status_code == 401
    # Second logout is idempotent and a 401-free no-op for missing token.
    assert client_for(user["token"]).post("/auth/logout").status_code == 204


def test_login_rejected_for_legacy_hashless_user(api: TestClient, db: Engine) -> None:
    with Session(db) as session:
        legacy = User(email="legacy-nohash@example.com", display_name="Legacy")
        session.add(legacy)
        session.commit()
    response = api.post(
        "/auth/login", json={"email": "legacy-nohash@example.com", "password": "whatever-123"}
    )
    assert response.status_code == 401


def test_bruteforce_login_lockout(api: TestClient) -> None:
    from app.services.auth import limiter

    user = api_register(api, "lock@example.com")
    assert limiter.max_attempts >= 3
    for _ in range(limiter.max_attempts):
        response = api.post(
            "/auth/login", json={"email": user["email"], "password": "nope-nope-nope"}
        )
        assert response.status_code == 401
    locked = api.post("/auth/login", json={"email": user["email"], "password": _CREDENTIAL})
    assert locked.status_code == 429
    limiter.reset(user["email"])


def test_cross_user_cv_isolation(api: TestClient, db: Engine) -> None:
    owner = api_register(api, "owner@example.com")
    stranger = api_register(api, "stranger@example.com")

    with Session(db) as session:
        owner_row = session.get(User, owner["user_id"])
        assert owner_row is not None
        upload_resume(session, owner_row, "cv.md", b"# CV\nsecret-stuff")
        cv_ids = [str(r.id) for r in session.execute(select(Resume)).scalars().all()]
        assert cv_ids

    stranger_client = client_for(stranger["token"])
    listing = stranger_client.get("/cvs")
    assert listing.status_code == 200
    assert listing.json() == []
    single = stranger_client.get(f"/cvs/{cv_ids[0]}")
    assert single.status_code == 404  # existence not leaked

    owner_client = client_for(owner["token"])
    assert owner_client.get("/cvs").status_code == 200
    assert len(owner_client.get("/cvs").json()) == 1


def _job_and_application(db: Engine, owner: dict[str, str]) -> tuple[str, str]:
    """Create a job and an application owned by `owner`; returns (job_id, app_id)."""
    with Session(db) as session:
        run_ingestion(session, [normalized()])
        job_row = session.execute(select(Job)).scalar_one()
    response = client_for(owner["token"]).post("/applications", json={"job_id": str(job_row.id)})
    assert response.status_code == 201, response.text
    return str(job_row.id), str(response.json()["id"])


def test_cross_user_application_isolation(api: TestClient, db: Engine) -> None:
    owner = api_register(api, "appowner@example.com")
    stranger = api_register(api, "appstranger@example.com")
    _, app_id = _job_and_application(db, owner)

    owner_client = client_for(owner["token"])
    events_before = owner_client.get(f"/applications/{app_id}/events").json()

    stranger_client = client_for(stranger["token"])
    assert stranger_client.get("/applications").json()["items"] == []
    assert stranger_client.get(f"/applications/{app_id}").status_code == 404
    assert stranger_client.get(f"/applications/{app_id}/events").status_code == 404
    assert stranger_client.get(f"/applications/{app_id}/availability").status_code == 404
    assert (
        stranger_client.post(
            f"/applications/{app_id}/status", json={"status": "submitted", "notes": None}
        ).status_code
        == 404
    )
    # Foreign "I applied" confirmation is also rejected.
    assert (
        stranger_client.post(
            f"/applications/{app_id}/confirm-submit", json={"external_ref": None}
        ).status_code
        == 404
    )

    owner_client = client_for(owner["token"])
    assert owner_client.get(f"/applications/{app_id}").status_code == 200
    # Stranger attempts (even 404s) must not have created history.
    events_after = owner_client.get(f"/applications/{app_id}/events").json()
    assert [e["id"] for e in events_after] == [e["id"] for e in events_before]


def test_cross_user_tailored_and_profile_isolation(api: TestClient, db: Engine) -> None:
    owner = api_register(api, "towner@example.com")
    stranger = api_register(api, "tstranger@example.com")

    with Session(db) as session:
        run_ingestion(session, [normalized()])
        job = session.execute(select(Job)).scalar_one()
        resume = Resume(
            user_id=owner["user_id"],
            kind="original",
            original_filename="cv.md",
            file_type="md",
            file_size_bytes=10,
            file_path="stored-uploads/x.md",
            file_checksum_sha256=hashlib.sha256(b"x").hexdigest(),
            parsed_content={"skills": ["Python"]},
            parse_notes=[],
        )
        session.add(resume)
        session.flush()
        tailored = TailoredResume(
            user_id=owner["user_id"],
            resume_id=resume.id,
            job_id=job.id,
            approval_status="approved",
            content={"sections": []},
            unsupported_claims=[],
        )
        session.add(tailored)
        session.commit()
        tailored_id = str(tailored.id)

    stranger_client = client_for(stranger["token"])
    assert stranger_client.get("/tailored").json() == []
    assert stranger_client.get(f"/tailored/{tailored_id}").status_code == 404

    # Profile isolation: stranger's PUT must not touch the owner's profile.
    put = stranger_client.put("/profile", json={"location": "Hacked"})
    assert put.status_code == 200
    owner_profile = client_for(owner["token"]).get("/profile").json()
    assert owner_profile["location"] == ""
