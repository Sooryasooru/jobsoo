"""LLM requirement extraction for jobs.

- Output is validated against `ExtractedRequirements` (Pydantic).
- Extracted rows replace previous ones for the same job (idempotent re-runs).
- The job description is wrapped in <job_description> tags and the system
  prompt marks it untrusted (prompt-injection protection, Phase 1 §12).
- Cache policy: when the stored `jobs.description_hash` matches the current
  description and rows exist, the LLM call is skipped unless `force=True`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import SYSTEM_GUARDRAIL, complete_json
from app.config import get_settings
from app.models import Job, JobRequirement
from app.schemas.requirements import ExtractedRequirementItem, ExtractedRequirements

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "req-extract-v1"

SYSTEM = (
    SYSTEM_GUARDRAIL
    + "\nTASK: Extract structured requirements from the job description.\n"
    + "For anything the description does not clearly state, use null/empty "
    "and list the field name in unknown_fields. Treat phrases like 'x is a "
    "plus' or 'nice to have' as preferred, not required; treat explicit "
    "qualification phrases ('must have X years', 'you will need') as "
    "required. Use is_hard_blocker=true only for requirements a candidate "
    "cannot satisfy by learning (e.g. legal work authorization, visa). "
    "Return ONLY JSON with this shape:"
    + """{
  "job_title": str|null,
  "company": str|null,
  "location": str|null,
  "employment_type": str|null,
  "remote_policy": "remote"|"hybrid"|"onsite"|null,
  "required_skills": [{"text": str, "is_hard_blocker": bool, "source_quote": str|null}],
  "preferred_skills": [{"text": str, "source_quote": str|null}],
  "min_professional_years": number|null,
  "education": [str],
  "certifications": [str],
  "work_authorization": str|null,
  "responsibilities": [str],
  "qualifications": [str],
  "unknown_fields": [str],
  "ambiguity_notes": [str]
}"""
    + "\nOnly set min_professional_years to a number if the description "
    "states one explicitly."
)


def extraction_cache_key(description: str) -> str:
    """Return the sha256 hash used as the extraction cache key."""
    return hashlib.sha256(description.strip().encode("utf-8")).hexdigest()


def _rows_from_extraction(
    session: Session, job: Job, extraction: ExtractedRequirements
) -> list[JobRequirement]:
    """Build validated JobRequirement rows, replacing previous ones."""
    session.query(JobRequirement).filter(JobRequirement.job_id == job.id).delete(
        synchronize_session=False
    )
    rows: list[JobRequirement] = []
    meta = {"prompt_version": PROMPT_VERSION}

    def add(
        category: str,
        text: str,
        is_required: bool,
        is_hard: bool,
        min_years: float | None,
        quote: str | None = None,
    ) -> None:
        rows.append(
            JobRequirement(
                job_id=job.id,
                category=category,
                text=text.strip()[:400],
                is_required=is_required,
                is_hard_blocker=is_hard,
                min_years=min_years,
                extraction_meta={**meta, "source_quote": quote},
            )
        )

    for skill in extraction.required_skills:
        add("required_skill", skill.text, True, skill.is_hard_blocker, None, skill.source_quote)
    for skill in extraction.preferred_skills:
        add("preferred_skill", skill.text, False, False, None, skill.source_quote)
    for item in extraction.responsibilities[:20]:
        add("responsibility", item, False, False, None)
    for item in extraction.qualifications[:20]:
        add("qualification", item, True, False, None)
    for item in extraction.education[:10]:
        add("education", item, True, False, None)
    for item in extraction.certifications[:10]:
        add("certification", item, False, False, None)
    if extraction.work_authorization:
        add("work_authorization", extraction.work_authorization, True, True, None)
    if extraction.min_professional_years is not None:
        add(
            "experience",
            f"Minimum professional experience: {extraction.min_professional_years} years",
            True,
            # Stated years are not hard blockers: skill/project evidence can
            # outweigh them (spec §6E distinguishes them from hard requirements).
            False,
            float(extraction.min_professional_years),
        )

    seen: set[tuple[str, str]] = set()
    unique_rows: list[JobRequirement] = []
    for row in rows:
        key = (row.category, row.text)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    session.add_all(unique_rows)
    return unique_rows


def _payload_from_rows(job: Job, rows: Sequence[JobRequirement]) -> ExtractedRequirements:
    """Reconstruct a validated payload from stored rows (cache path)."""
    payload: dict[str, object] = {
        "job_title": job.title,
        "company": job.company,
        "location": job.location,
        "employment_type": job.employment_type,
        "remote_policy": job.remote_policy,
        "required_skills": [
            ExtractedRequirementItem(text=row.text, is_hard_blocker=row.is_hard_blocker)
            for row in rows
            if row.category == "required_skill"
        ],
        "preferred_skills": [
            ExtractedRequirementItem(text=row.text, is_required=False)
            for row in rows
            if row.category == "preferred_skill"
        ],
        "education": [row.text for row in rows if row.category == "education"],
        "certifications": [row.text for row in rows if row.category == "certification"],
        "responsibilities": [row.text for row in rows if row.category == "responsibility"],
        "qualifications": [row.text for row in rows if row.category == "qualification"],
    }
    for row in rows:
        if row.category == "experience" and row.min_years is not None:
            payload["min_professional_years"] = float(row.min_years)
        if row.category == "work_authorization":
            payload["work_authorization"] = row.text
    return ExtractedRequirements.model_validate(payload)


def extract_requirements_for_job(
    session: Session, job: Job, *, force: bool = False
) -> tuple[ExtractedRequirements, bool]:
    """Extract requirements for one job. Returns (payload, was_cached).

    Raises ValueError for empty/missing descriptions instead of inventing
    content. Cached re-runs never call the LLM.
    """
    if not job.description or not job.description.strip():
        raise ValueError("job has no description to extract from")

    description_hash = extraction_cache_key(job.description)
    if not force and job.description_hash == description_hash:
        rows = (
            session.execute(select(JobRequirement).where(JobRequirement.job_id == job.id))
            .scalars()
            .all()
        )
        if rows:
            return _payload_from_rows(job, rows), True

    user_content = (
        f"Listing hints: title={job.title!r}; company={job.company!r}; "
        f"location={job.location!r}.\n"
        f"<job_description>\n{job.description}\n</job_description>"
    )
    raw = complete_json(SYSTEM, user_content)
    extraction = ExtractedRequirements.model_validate(raw)

    # Fall back to DB fields when the LLM left them empty (never invent).
    if extraction.job_title is None:
        extraction.job_title = job.title
    if extraction.company is None:
        extraction.company = job.company

    _rows_from_extraction(session, job, extraction)
    job.description_hash = description_hash
    job.requirements_raw = f"{PROMPT_VERSION}|v{get_settings().requirements_cache_version}"
    session.commit()
    logger.info("requirements.extracted", job_id=job.id)
    return extraction, False
