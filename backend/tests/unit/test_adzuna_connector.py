"""Unit tests for the Adzuna connector (all HTTP mocked, no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.connectors import (
    AdzunaConnector,
    MalformedResponseError,
    RateLimitError,
    SourceUnavailableError,
)


def raw_adzuna_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "id": "999",
        "title": "Data Engineer",
        "redirect_url": "https://jobs.example.com/999",
        "company": {"display_name": "ACME"},
        "location": {"display_name": "Dubai"},
        "description": "Build pipelines with Python and SQL.",
        "created": "2026-10-01T09:00:00Z",
        "salary_min": 10000.0,
        "salary_max": 20000.0,
        "contract_time": "full_time",
    }
    record.update(overrides)
    return record


def make_connector(*, max_retries: int | None = None) -> AdzunaConnector:
    return AdzunaConnector(
        app_id="i", app_key="k", max_retries=max_retries if max_retries is not None else 2
    )


def httpx_response(
    status_code: int = 200, json_data: Any = None, headers: dict[str, str] | None = None
) -> Any:
    response = type("R", (), {})()
    response.status_code = status_code
    response.headers = headers or {}
    response.text = "<body>"
    response.json = lambda: json_data  # type: ignore[method-assign]
    return response


@patch("app.connectors.adzuna.httpx.get")
def test_iterate_jobs_normalizes_records(mock_get: Any) -> None:
    mock_get.return_value = httpx_response(200, {"results": [raw_adzuna_record()], "count": 1})
    jobs = list(make_connector().iterate_jobs())
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "adzuna"
    assert job.source_job_id == "999"
    assert job.company == "ACME"
    assert job.location == "Dubai"
    assert job.salary_min == 10000.0
    assert job.employment_type == "full_time"
    assert job.posted_at is not None


@patch("app.connectors.adzuna.httpx.get")
def test_iterate_jobs_skips_malformed_single_record(mock_get: Any) -> None:
    records = [raw_adzuna_record(id="1", title=""), raw_adzuna_record(id="2")]
    mock_get.return_value = httpx_response(200, {"results": records, "count": 2})
    jobs = list(make_connector().iterate_jobs())
    assert [j.source_job_id for j in jobs] == ["2"]


@patch("app.connectors.adzuna.httpx.get")
def test_iterate_jobs_paginates_until_last_page(mock_get: Any) -> None:
    page1 = {"results": [raw_adzuna_record(id=str(i)) for i in range(3)], "count": 4}
    page2 = {"results": [raw_adzuna_record(id="9")], "count": 4}
    mock_get.side_effect = [httpx_response(200, page1), httpx_response(200, page2)]
    jobs = list(make_connector().iterate_jobs(page_size=3))
    assert {j.source_job_id for j in jobs} == {"0", "1", "2", "9"}


@patch("app.connectors.adzuna.httpx.get")
def test_missing_description_is_none_not_invented(mock_get: Any) -> None:
    mock_get.return_value = httpx_response(
        200, {"results": [raw_adzuna_record(description=None)], "count": 1}
    )
    (job,) = list(make_connector().iterate_jobs())
    assert job.description is None


@patch("app.connectors.adzuna.httpx.get")
def test_inverted_salary_range_is_clamped_not_dropped(mock_get: Any) -> None:
    mock_get.return_value = httpx_response(
        200, {"results": [raw_adzuna_record(salary_min=20000.0, salary_max=10000.0)], "count": 1}
    )
    (job,) = list(make_connector().iterate_jobs())
    assert job.salary_min == 10000.0
    assert job.salary_max == 20000.0


@patch("app.connectors.adzuna.httpx.get")
def test_rate_limit_429_raises_rate_limit_error(mock_get: Any) -> None:
    responses = [httpx_response(429, {}, {"retry-after": "0"}) for _ in range(5)]
    mock_get.side_effect = responses
    with pytest.raises(RateLimitError):
        list(make_connector(max_retries=0).iterate_jobs())


@patch("app.connectors.adzuna.httpx.get")
def test_server_error_becomes_source_unavailable(mock_get: Any) -> None:
    mock_get.side_effect = [httpx_response(500)] * 10
    with pytest.raises(SourceUnavailableError):
        list(make_connector().iterate_jobs())


@patch("app.connectors.adzuna.httpx.get")
def test_malformed_json_raises_malformed_response_error(mock_get: Any) -> None:
    mock_get.return_value = httpx_response(200, {"unexpected": "shape"})
    with pytest.raises(MalformedResponseError):
        list(make_connector().iterate_jobs())


@patch("app.connectors.adzuna.httpx.get")
def test_non_dict_record_is_skipped(mock_get: Any) -> None:
    mock_get.return_value = httpx_response(
        200, {"results": ["not-an-object", raw_adzuna_record(id="7")], "count": 2}
    )
    jobs = list(make_connector().iterate_jobs())
    assert [j.source_job_id for j in jobs] == ["7"]
