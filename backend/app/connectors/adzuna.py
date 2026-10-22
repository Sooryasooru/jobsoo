"""Adzuna job source connector (https://developer.adzuna.com/).

Respects pagination, validates each raw record into `NormalizedJob`, and
translates HTTP failures into a typed error hierarchy. A single malformed
record is skipped and logged; request-level failures abort the iteration.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.connectors.base import (
    JobConnector,
    MalformedResponseError,
    RateLimitError,
    SourceUnavailableError,
)
from app.schemas.jobs import NormalizedJob, canonicalize_url

logger = structlog.get_logger(__name__)

EMPLOYMENT_TYPE_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "contract": "contract",
    "permanent": "full_time",
    "temporary": "temporary",
    "internship": "internship",
    "apprenticeship": "apprenticeship",
}


class AdzunaConnector(JobConnector):
    """Connector for the Adzuna search API (v1)."""

    name = "adzuna"

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_key: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.app_id = app_id or settings.adzuna_app_id
        self.app_key = app_key or settings.adzuna_app_key
        self.country = settings.adzuna_country
        self.base_url = settings.adzuna_base_url
        self.timeout = timeout_seconds or settings.adzuna_timeout_seconds
        self.max_retries = settings.adzuna_max_retries if max_retries is None else max_retries
        if not self.app_id or not self.app_key:
            raise SourceUnavailableError(
                "Adzuna credentials missing: set ADZUNA_APP_ID / ADZUNA_APP_KEY"
            )

    def _search_url(self, page: int) -> str:
        return f"{self.base_url}/jobs/{self.country}/search/{page}"

    def _fetch_page(self, page: int, page_size: int) -> dict[str, Any]:
        params: dict[str, str] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": str(page_size),
            "content-type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.get(
                    self._search_url(page),
                    params=params,
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("adzuna.timeout", page=page, attempt=attempt)
                continue
            except httpx.RequestError as exc:
                raise SourceUnavailableError(f"network error: {exc}") from exc

            if response.status_code == 429:
                # Basic fixed backoff; Phase 2 will move periodic runs to a queue.
                retry_after = float(response.headers.get("retry-after", "2"))
                logger.warning("adzuna.rate_limited", page=page, retry_after=retry_after)
                if attempt < self.max_retries:
                    import time

                    time.sleep(min(retry_after, 30.0))
                    continue
                raise RateLimitError("Adzuna rate limit exhausted")

            if response.status_code in (500, 502, 503, 504) and attempt < self.max_retries:
                logger.warning("adzuna.server_error", page=page, status=response.status_code)
                continue

            if response.status_code != 200:
                raise SourceUnavailableError(
                    f"Adzuna returned HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                payload: dict[str, Any] = response.json()
            except (ValueError, TypeError) as exc:
                raise MalformedResponseError("Adzuna returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise MalformedResponseError("Adzuna JSON root is not an object")
            return payload

        raise SourceUnavailableError(f"Adzuna unreachable after retries: {last_error}")

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> NormalizedJob | None:
        """Convert one Adzuna record; returns None if it cannot be trusted."""
        try:
            source_job_id = str(raw["id"])
        except (KeyError, TypeError) as exc:
            logger.warning("adzuna.record_missing_id", exc_info=exc)
            return None

        title = raw.get("title") or ""
        if not str(title).strip():
            logger.warning("adzuna.record_missing_title", source_job_id=source_job_id)
            return None

        redirect_url = raw.get("redirect_url") or raw.get("adref") or ""
        if not redirect_url:
            logger.warning("adzuna.record_missing_url", source_job_id=source_job_id)
            return None

        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        contract_time = raw.get("contract_time")
        description = raw.get("description") or None

        if (
            isinstance(salary_min, (int, float))
            and isinstance(salary_max, (int, float))
            and salary_max < salary_min
        ):
            # Adzuna occasionally returns inverted ranges; clamp instead of dropping.
            salary_min, salary_max = salary_max, salary_min

        try:
            normalized = NormalizedJob(
                source="adzuna",
                source_job_id=source_job_id,
                title=str(title).strip(),
                original_url=str(redirect_url),
                canonical_url=canonicalize_url(str(redirect_url)),
                posted_at=raw.get("created") or None,
                company=raw.get("company", {}).get("display_name") or None
                if isinstance(raw.get("company"), dict)
                else raw.get("company"),
                location=raw.get("location", {}).get("display_name") or raw.get("location")
                if isinstance(raw.get("location"), dict)
                else raw.get("location"),
                description=description,
                employment_type=EMPLOYMENT_TYPE_MAP.get(
                    str(raw.get("contract_type") or raw.get("contract_time") or "").lower()
                ),
                contract_time=contract_time,
                salary_min=float(salary_min) if salary_min is not None else None,
                salary_max=float(salary_max) if salary_max is not None else None,
                salary_currency=raw.get("salary_currency") or None,
                is_remote="remote" in str(raw.get("title", "")).lower()
                or "remote" in str(description or "").lower()[:2000].lower()
                or raw.get("remote") is True,
                remote_policy="unknown",
            )
        except Exception as exc:
            logger.warning(
                "adzuna.record_invalid",
                source_job_id=source_job_id,
                error=str(exc),
            )
            return None
        return normalized

    def iterate_jobs(self, *, max_pages: int = 5, page_size: int = 50) -> Iterator[NormalizedJob]:
        """Yield normalized jobs from up to `max_pages` of Adzuna results."""
        for page in range(1, max_pages + 1):
            payload = self._fetch_page(page, page_size)
            results = payload.get("results")
            if not isinstance(results, list):
                raise MalformedResponseError("Adzuna response missing 'results' list")

            count = payload.get("count", 0)
            for record in results:
                if not isinstance(record, dict):
                    logger.warning("adzuna.record_not_object", index=results.index(record))
                    continue
                normalized = self._normalize(record)
                if normalized is not None:
                    yield normalized
            if len(results) < page_size or (isinstance(count, int) and page * page_size >= count):
                return
