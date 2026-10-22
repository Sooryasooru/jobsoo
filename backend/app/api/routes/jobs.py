"""Job API routes: search, detail, ingestion triggers.

Business logic lives in app.services ingestion; routes stay thin.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import DataError, StatementError
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.connectors.registry import get_connector
from app.db.session import get_session
from app.models import Job
from app.schemas.jobs import IngestionSourceStats, IngestResult, JobListingResponse
from app.services.ingestion import ingest_many, run_ingestion

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_response(job: Job) -> JobListingResponse:
    return JobListingResponse(
        id=str(job.id),
        source=job.source,
        source_job_id=job.source_job_id,
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description,
        employment_type=job.employment_type,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        is_remote=job.is_remote,
        remote_policy=job.remote_policy,
        canonical_url=job.canonical_url,
        original_url=job.original_url,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        last_verified_at=job.last_verified_at,
        is_active=job.is_active,
        is_expired=job.is_expired,
    )


@router.get("")
def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    company: str | None = Query(default=None, max_length=200),
    location: str | None = Query(default=None, max_length=200),
    is_active: bool | None = Query(default=None),
    include_expired: bool = Query(default=False),
    limit: int = Query(default=50, le=200, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> dict[str, object]:
    """List jobs with filters. Low-score jobs are never excluded anywhere."""
    stmt = select(Job)
    conditions: list[Any] = []
    if not include_expired:
        conditions.append(Job.is_expired.is_(False))
    if is_active is not None:
        conditions.append(Job.is_active.is_(is_active))
    if q:
        like = f"%{q.lower()}%"
        conditions.append(
            func.lower(Job.title).like(like)
            | func.lower(func.coalesce(Job.description, "")).like(like)
        )
    if company:
        conditions.append(func.lower(Job.company) == company.lower())
    if location:
        like = f"%{location.lower()}%"
        conditions.append(func.lower(func.coalesce(Job.location, "")).like(like))
    for condition in conditions:
        stmt = stmt.where(condition)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Job.posted_at.desc().nullslast(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return {"total": total, "items": [_to_response(j) for j in rows]}


@router.get("/stats")
def source_stats(db: Session = Depends(get_session)) -> IngestionSourceStats:
    """Aggregate statistics about stored jobs."""
    total = db.execute(select(func.count()).select_from(Job)).scalar_one()
    active = db.execute(
        select(func.count()).select_from(Job).where(Job.is_active.is_(True))
    ).scalar_one()
    expired = total - active
    by_source_rows = db.execute(select(Job.source, func.count()).group_by(Job.source)).all()
    return IngestionSourceStats(
        total=total,
        active=active,
        expired=expired,
        by_source=dict(by_source_rows),
    )


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_session)) -> JobListingResponse:
    """Fetch one job by id."""
    try:
        job = db.get(Job, job_id)
    except (DataError, StatementError):
        raise HTTPException(status_code=404, detail="job not found") from None
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_response(job)


@router.post("/ingest")
def ingest_jobs(
    max_pages: int = Query(default=2, ge=1, le=10),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_session),
) -> IngestResult:
    """Fetch from the configured connector and ingest (dedup + reconcile)."""
    try:
        connector = get_connector()
    except ConnectorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    jobs = list(connector.iterate_jobs(max_pages=max_pages, page_size=page_size))
    return run_ingestion(db, jobs)


@router.post("/import")
def import_jobs(jobs: list[dict[str, Any]], db: Session = Depends(get_session)) -> IngestResult:
    """Import pre-normalized job dicts (manual sources; validates via schema)."""
    from app.schemas.jobs import NormalizedJob

    normalized = [NormalizedJob.model_validate(j) for j in jobs]
    return ingest_many(db, normalized)
