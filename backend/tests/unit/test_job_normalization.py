"""Unit tests for job normalization and URL canonicalization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.jobs import NormalizedJob, canonicalize_url, normalize_company_name


def sample_job(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "source": "adzuna",
        "source_job_id": "123",
        "title": "Backend Engineer",
        "original_url": "https://example.com/jobs/123?utm_source=x&id=123",
        "canonical_url": canonicalize_url("https://example.com/jobs/123"),
    }
    data.update(overrides)
    return data


def test_canonicalize_url_strips_tracking_and_fragment() -> None:
    url = "https://Example.com/path/jobs/1?utm_source=ga&id=42&b=2&a=1#section"
    assert canonicalize_url(url) == "https://example.com/path/jobs/1?id=42"


def test_canonicalize_url_drops_default_ports_and_trailing_slash() -> None:
    # Scheme is preserved; default ports and trailing slashes are not.
    assert canonicalize_url("http://example.com:80/x/") == "http://example.com/x"
    assert canonicalize_url("https://example.com:443/x/") == "https://example.com/x"


def test_canonicalize_url_links_common_postings() -> None:
    a = canonicalize_url("https://jobs.example.com/1?source=linkedin")
    b = canonicalize_url("https://jobs.example.com/1?source=indeed")
    assert a == b


def test_normalize_company_name_is_invariant_to_case_and_punctuation() -> None:
    assert normalize_company_name("ACME Ltd.") == normalize_company_name("acme-ltd")
    assert normalize_company_name(None) == ""


def test_normalized_job_strips_title() -> None:
    job = NormalizedJob.model_validate(sample_job(title="  Backend Engineer  "))
    assert job.title == "Backend Engineer"


def test_normalized_job_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        NormalizedJob.model_validate(sample_job(title="   "))


def test_normalized_job_rejects_salary_max_below_min() -> None:
    with pytest.raises(ValidationError):
        NormalizedJob.model_validate(sample_job(salary_min=5000, salary_max=4000))


def test_normalized_job_allows_missing_optional_fields() -> None:
    job = NormalizedJob.model_validate(sample_job())
    assert job.company is None
    assert job.description is None
    assert job.salary_min is None
    assert job.is_remote is None


def test_normalized_job_accepts_iso_posted_at_string() -> None:
    job = NormalizedJob.model_validate(sample_job(posted_at="2026-10-01T10:00:00Z"))
    assert job.posted_at is not None
    assert job.posted_at.year == 2026
