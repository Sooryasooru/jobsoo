"""Connector interface and error taxonomy."""

from __future__ import annotations

from collections.abc import Iterator

from app.schemas.jobs import NormalizedJob


class ConnectorError(Exception):
    """Base class for connector failures."""


class SourceUnavailableError(ConnectorError):
    """The source API could not be reached or returned a server error."""


class RateLimitError(ConnectorError):
    """The source API signaled rate limiting."""


class MalformedResponseError(ConnectorError):
    """The source API responded with unexpected/invalid data."""


class JobConnector:
    """Contract every job source connector must satisfy.

    Connectors are the only component allowed to talk to external job
    APIs; persistence lives in `app.services.ingestion`.
    """

    name: str

    def iterate_jobs(self, *, max_pages: int = 5, page_size: int = 50) -> Iterator[NormalizedJob]:
        """Yield normalized jobs, handling pagination internally."""
        raise NotImplementedError
