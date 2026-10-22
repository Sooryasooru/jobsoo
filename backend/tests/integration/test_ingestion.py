"""Integration tests for the ingestion pipeline (requires PostgreSQL)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.session import set_engine, set_session_factory
from app.main import app
from app.models import Job
from app.schemas.jobs import NormalizedJob
from app.services.ingestion import run_ingestion

pytestmark = pytest.mark.integration


def normalized(**overrides: object) -> NormalizedJob:
    data = {
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
def api(db: Engine) -> TestClient:
    """API client wired to the test database with tables created."""
    set_engine(db)
    set_session_factory(None)
    return TestClient(app)


def test_ingest_inserts_then_reconciles_same_source(db: Engine) -> None:
    with Session(db) as session:
        first = run_ingestion(session, [normalized()])
        assert first.inserted == 1

        second = run_ingestion(session, [normalized(posted_at="2026-10-05T09:00:00Z")])
        assert second.updated == 1
        assert second.inserted == 0
        rows = session.query(Job).all()
        assert len(rows) == 1
        assert rows[0].posted_at is not None


def test_canonical_url_dedup_across_sources(db: Engine) -> None:
    with Session(db) as session:
        run_ingestion(session, [normalized()])
        cross_source = run_ingestion(
            session,
            [
                normalized(
                    source="linkedin", source_job_id="li-77", description="Python and SQL required."
                )
            ],
        )
        assert cross_source.inserted == 0
        assert session.query(Job).count() == 1


def test_fuzzy_duplicate_is_reconciled_and_flagged_not_merged_away(db: Engine) -> None:
    with Session(db) as session:
        run_ingestion(
            session,
            [
                normalized(
                    description="We need Python, SQL, Docker. Senior backend engineer role at ACME Dubai."
                )
            ],
        )
        similar = run_ingestion(
            session,
            [
                normalized(
                    source_job_id="200",
                    canonical_url="https://jobs.example.com/200",
                    original_url="https://jobs.example.com/200",
                    description="We need Python, SQL, Docker. Senior backend engineer role at ACME Dubai. Apply now!",
                )
            ],
        )
        assert similar.inserted == 0
        job = session.query(Job).first()
        assert job is not None
        assert job.duplicate_flags
        assert job.duplicate_flags[0]["source_job_id"] == "200"


def test_distinct_jobs_not_flagged(db: Engine) -> None:
    with Session(db) as session:
        run_ingestion(session, [normalized()])
        other = run_ingestion(
            session,
            [
                normalized(
                    source_job_id="300",
                    canonical_url="https://jobs.example.com/300",
                    original_url="https://jobs.example.com/300",
                    company="Other Corp",
                    title="Data Scientist",
                )
            ],
        )
        assert other.inserted == 1
        job = session.query(Job).order_by(Job.source_job_id).first()  # type: ignore[union-attr]
        assert job is not None and job.duplicate_flags == []


def test_missing_sweep_expires_job(db: Engine) -> None:
    with Session(db) as session:
        run_ingestion(session, [normalized()])
        # Next sweep without the job marks it expired but keeps the row.
        result = run_ingestion(session, [])
        assert result.inactive_count == 1
        job = session.query(Job).first()
        assert job is not None
        assert job.is_expired is True
        assert job.is_active is False


def test_batch_internal_duplicates_skipped(db: Engine) -> None:
    with Session(db) as session:
        result = run_ingestion(
            session,
            [
                normalized(),
                normalized(source_job_id="999", canonical_url="https://other.example.com/999"),
            ],
        )
    # Same (source, source_job_id) twice -> one insert only.
    assert result.total_seen == 2 and result.inserted == 1


def test_api_list_get_and_import(api: TestClient) -> None:
    resp = api.post(
        "/jobs/import",
        json=[normalized().model_dump(mode="json")],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 1

    listing = api.get("/jobs")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    job = listing.json()["items"][0]
    detail = api.get(f"/jobs/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Backend Engineer"
    assert api.get("/jobs/nonexistent").status_code == 404


def test_api_stats(api: TestClient) -> None:
    api.post("/jobs/import", json=[normalized().model_dump(mode="json")])
    stats = api.get("/jobs/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] == 1
    assert body["active"] == 1
    assert body["by_source"].get("adzuna") == 1
