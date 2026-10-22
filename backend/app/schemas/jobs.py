"""Job schemas: connector normalization output and API responses."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, HttpUrl, field_validator

_TRACKING_PARAM_WHITELIST = {"id", "ref", "apply", "redirect", "utm_source"}
_TRACKING_PREFIXES = ("utm_", "ga_", "mc_", "yclid", "gclid", "fbclid")


def canonicalize_url(url: str) -> str:
    """Produce a stable canonical form of a job posting URL.

    Lowercases scheme/host, drops default ports, fragments, and most
    tracking parameters, then sorts remaining query parameters.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    kept_params: list[tuple[str, str]] = []
    raw_pairs = parts.query.split("&") if parts.query else []
    for pair in raw_pairs:
        if not pair:
            continue
        key, _, value = pair.partition("=")
        normalized_key = key.lower()
        # Drop analytics/tracking params; keep only known functional params.
        if any(normalized_key.startswith(prefix) for prefix in _TRACKING_PREFIXES):
            continue
        if normalized_key not in _TRACKING_PARAM_WHITELIST:
            continue
        kept_params.append((key, value))
    kept_params.sort()
    query = "&".join(f"{k}={v}" for k, v in kept_params)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_company_name(value: str | None) -> str:
    """Lowercase a company name for fuzzy dedup comparisons."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class NormalizedJob(BaseModel):
    """Standard internal job schema produced by every connector."""

    model_config = {"extra": "ignore"}

    source: str
    source_job_id: str
    title: str = Field(min_length=1)

    original_url: HttpUrl
    canonical_url: str
    posted_at: datetime | None = None

    company: str | None = None
    location: str | None = None
    description: str | None = None
    employment_type: str | None = None
    contract_time: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    is_remote: bool | None = None
    remote_policy: str | None = None  # remote | hybrid | onsite | unknown

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()

    @field_validator("salary_max")
    @classmethod
    def _salary_max_gte_min(cls, v: float | None, info: Any) -> float | None:
        mn = info.data.get("salary_min")
        if v is not None and mn is not None and v < mn:
            raise ValueError("salary_max must be >= salary_min")
        return v


class JobListingResponse(BaseModel):
    """API response for a single stored job listing."""

    id: str
    source: str
    source_job_id: str
    title: str
    company: str | None
    location: str | None
    description: str | None
    employment_type: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    is_remote: bool | None
    remote_policy: str | None
    canonical_url: str
    original_url: str
    posted_at: datetime | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_verified_at: datetime | None
    is_active: bool
    is_expired: bool


class IngestResult(BaseModel):
    """Result of an ingestion run."""

    inserted: int
    updated: int
    flagged_possible_duplicates: int
    inactive_count: int
    total_seen: int


class IngestionSourceStats(BaseModel):
    """Aggregate stats about stored jobs."""

    total: int
    active: int
    expired: int
    by_source: dict[str, int]
