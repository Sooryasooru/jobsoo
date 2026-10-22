"""Connector registry: maps source names to connector implementations.

Phase 1 ships Adzuna only; later sources register additional implementations.
"""

from __future__ import annotations

from app.connectors.adzuna import AdzunaConnector
from app.connectors.base import JobConnector

_registry: dict[str, type[JobConnector]] = {
    "adzuna": AdzunaConnector,
}


def register_connector(name: str, connector_cls: type[JobConnector]) -> None:
    """Register a connector implementation (intended for tests/new sources)."""
    _registry[name] = connector_cls


def get_connector(name: str = "adzuna") -> JobConnector:
    """Instantiate a connector by name."""
    if name not in _registry:
        raise KeyError(f"unknown job source: {name}")
    return _registry[name]()
