"""Job source connectors.

Each connector fetches raw listings from one provider and normalizes them
to `NormalizedJob` (the standard internal schema). New sources (e.g. company
ATS feeds later on) implement `JobConnector` the same way.
"""

from app.connectors.adzuna import AdzunaConnector
from app.connectors.base import (
    ConnectorError,
    JobConnector,
    MalformedResponseError,
    RateLimitError,
    SourceUnavailableError,
)

__all__ = [
    "AdzunaConnector",
    "ConnectorError",
    "JobConnector",
    "MalformedResponseError",
    "RateLimitError",
    "SourceUnavailableError",
]
