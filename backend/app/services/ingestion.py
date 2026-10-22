"""Job ingestion pipeline: normalize, dedup, persist, reconcile.

Deduplication order (Phase 1 spec §6A):
  1. (source, source_job_id)        -> upsert (update last-seen etc.)
  2. canonical URL (across sources) -> upsert
  3. normalized (company, title, location) match -> reconcile into the first
     stored job, recording secondary candidates; description similarity beyond
     `DUPLICATE_FLAG_THRESHOLD` sets a *flag* for review (never auto-merge).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Job
from app.schemas.jobs import IngestResult, NormalizedJob, normalize_company_name

logger = get_logger(__name__)

# Two jobs with description similarity above this value are flagged, not merged.
DUPLICATE_FLAG_THRESHOLD = 0.92


def _similar_text(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower()[:5000], b.lower()[:5000]).ratio()


def _same_company_title_location(a: Job, candidate: NormalizedJob) -> bool:
    return (
        normalize_company_name(a.company) == normalize_company_name(candidate.company)
        and a.title.strip().lower() == candidate.title.strip().lower()
        and (a.location or "").strip().lower() == (candidate.location or "").strip().lower()
    ) and bool(candidate.company)


def _flag_duplicate(job: Job, candidate: NormalizedJob, similarity: float) -> None:
    job.duplicate_flags = (job.duplicate_flags or []) + [
        {
            "source": candidate.source,
            "source_job_id": candidate.source_job_id,
            "similarity": round(similarity, 3),
            "flagged_at": datetime.now(UTC).isoformat(),
        }
    ]


def ingest_job(session: Session, candidate: NormalizedJob) -> tuple[Job, str]:
    """Persist one normalized job.

    Returns (job_row, outcome) where outcome is one of
    "inserted" | "updated_same_source" | "updated_url" | "reconciled".
    """
    now = datetime.now(UTC)

    existing = session.execute(
        select(Job).where(
            Job.source == candidate.source, Job.source_job_id == candidate.source_job_id
        )
    ).scalar_one_or_none()

    if existing is not None:
        _update_fields(existing, candidate)
        existing.last_seen_at = now
        existing.last_verified_at = now
        existing.is_active = True
        existing.is_expired = False
        return existing, "updated_same_source"

    # Level 2: canonicalized URL known (possibly from another source).
    existing = session.execute(
        select(Job).where(Job.canonical_url == candidate.canonical_url)
    ).scalar_one_or_none()
    if existing is not None:
        _update_fields(existing, candidate)
        existing.last_seen_at = now
        existing.last_verified_at = now
        existing.is_active = True
        return existing, "updated_url"

    # Level 3/4: fuzzy match on (company, title, location), then description similarity.
    jobs_same_company_title = (
        session.execute(select(Job).where(Job.is_active.is_(True))).scalars().all()
    )
    for job in jobs_same_company_title:
        if not _same_company_title_location(job, candidate):
            continue
        similarity = _similar_text(job.description, candidate.description)
        if similarity >= DUPLICATE_FLAG_THRESHOLD:
            _flag_duplicate(job, candidate, similarity)
            return job, "reconciled"
        if candidate.description and job.description:
            # Persist a softer flag for manual review even below the threshold.
            job.possible_duplicate_source_ids = (job.possible_duplicate_source_ids or []) + [
                {
                    "source": candidate.source,
                    "source_job_id": candidate.source_job_id,
                    "reason": "company_title_location_match",
                    "similarity": round(similarity, 3),
                }
            ]
            return job, "reconciled"

    return _insert_job(session, candidate), "inserted"


def _update_fields(existing: Job, candidate: NormalizedJob) -> None:
    """Refresh mutable fields, keeping NULL unknowns unknown."""
    existing.title = candidate.title
    existing.company = candidate.company or existing.company
    existing.location = candidate.location or existing.location
    existing.description = candidate.description or existing.description
    existing.employment_type = candidate.employment_type
    existing.salary_min = candidate.salary_min
    existing.salary_max = candidate.salary_max
    existing.salary_currency = candidate.salary_currency
    existing.is_remote = candidate.is_remote
    existing.remote_policy = candidate.remote_policy
    existing.posted_at = candidate.posted_at
    if candidate.description:
        existing.description_hash = hashlib.sha256(
            candidate.description.encode("utf-8")
        ).hexdigest()


def _insert_job(session: Session, candidate: NormalizedJob) -> Job:
    job = Job(
        source=candidate.source,
        source_job_id=candidate.source_job_id,
        canonical_url=candidate.canonical_url,
        original_url=str(candidate.original_url),
        title=candidate.title,
        company=candidate.company,
        location=candidate.location,
        description=candidate.description,
        employment_type=candidate.employment_type,
        salary_min=candidate.salary_min,
        salary_max=candidate.salary_max,
        salary_currency=candidate.salary_currency,
        is_remote=candidate.is_remote,
        remote_policy=candidate.remote_policy,
        posted_at=candidate.posted_at,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        last_verified_at=datetime.now(UTC),
        is_active=True,
        is_expired=False,
    )
    if candidate.description:
        job.description_hash = hashlib.sha256(candidate.description.encode("utf-8")).hexdigest()
    session.add(job)
    session.flush()
    logger.info("job.inserted", source=job.source, source_job_id=job.source_job_id)
    return job


def ingest_many(session: Session, candidates: list[NormalizedJob]) -> IngestResult:
    """Ingest a batch; deduplicates within the batch as well as against the DB."""
    inserted = updated = reconciled = flagged = 0
    seen_keys: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()

    for candidate in candidates:
        key = (candidate.source, candidate.source_job_id)
        if key in seen_keys or candidate.canonical_url in seen_urls:
            logger.info("job.batch_duplicate_skipped", source_job_id=candidate.source_job_id)
            continue
        seen_keys.add(key)
        seen_urls.add(candidate.canonical_url)

        job, outcome = ingest_job(session, candidate)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "reconciled":
            reconciled += 1
            if job.duplicate_flags:
                flagged += 1
        else:
            updated += 1
    session.commit()

    return IngestResult(
        inserted=inserted,
        updated=updated,
        flagged_possible_duplicates=flagged,
        inactive_count=0,
        total_seen=len(candidates),
    )


def reconcile_availability(session: Session, seen_keys: set[tuple[str, str]]) -> int:
    """Mark stored active jobs as expired if not seen in a recent full sweep.

    Jobs missing from the latest listing sweep are flagged `is_expired=True`
    while remaining in the DB (never deleted), so history stays intact.
    """
    all_active = session.execute(select(Job).where(Job.is_active.is_(True))).scalars().all()
    expired_count = 0
    for job in all_active:
        if (job.source, job.source_job_id) not in seen_keys:
            job.is_expired = True
            job.is_active = False
            expired_count += 1
    session.commit()
    return expired_count


def run_ingestion(session: Session, jobs: list[NormalizedJob]) -> IngestResult:
    """Full ingestion: dedup batch, upsert each job, reconcile availability."""
    result = ingest_many(session, jobs)
    seen_keys = {(j.source, j.source_job_id) for j in jobs}
    result.inactive_count = reconcile_availability(session, seen_keys)
    return result
