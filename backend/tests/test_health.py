"""Integration test for the health endpoint (requires PostgreSQL)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db.session import set_engine, set_session_factory
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(engine: Engine) -> TestClient:
    """TestClient wired to the test database."""
    set_engine(engine)
    set_session_factory(None)  # recreate factory bound to the test engine

    return TestClient(app)


def test_health_reports_ok(client: TestClient) -> None:
    """Health endpoint reaches the database and returns version info."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
