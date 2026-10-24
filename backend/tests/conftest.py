"""Shared pytest fixtures.

Integration tests requires a PostgreSQL test database. Configure it via
`JOBSOO_TEST_DATABASE_URL`; the default targets a socket-auth database
`jobsoo_test` on the local machine (see docs/testing.md). Tests that need the
database are marked `@pytest.mark.integration` and skip cleanly when no
database is reachable, so pure-unit tests always run anywhere.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import TYPE_CHECKING

os.environ.setdefault(
    "JOBSOO_TEST_DATABASE_URL", "postgresql+psycopg://soorya@/jobsoo_test?host=/var/run/postgresql"
)
os.environ.setdefault("DATABASE_URL", os.environ["JOBSOO_TEST_DATABASE_URL"])

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from collections.abc import Generator

    from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def db_url() -> str:
    """Return the test database URL from the environment."""
    return os.environ["JOBSOO_TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def engine(db_url: str) -> Engine:
    """Create an engine for the test database, skipping if unreachable."""
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"test PostgreSQL not reachable: {exc}")
    return engine


@pytest.fixture
def db(engine: Engine) -> Generator[Engine, None, None]:
    """Provide an engine after resetting all tables for isolation."""
    from app.db.base import Base

    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.commit()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def _api_identity(db: Engine) -> dict[str, str]:
    """Register a fresh user per test; returns token/id/email for API fixtures."""
    import uuid

    from sqlalchemy.orm import Session as OrmSession

    from app.db.session import set_engine, set_session_factory
    from app.services import auth

    set_engine(db)
    set_session_factory(None)
    email = f"api-{uuid.uuid4().hex[:10]}@example.com"
    with OrmSession(db) as session:
        user, token = auth.register_user(
            session, email=email, password="test-password-1", display_name="API User"
        )
        user_id = user.id
    return {"token": token, "user_id": user_id, "email": email}


@pytest.fixture
def api(_api_identity: dict[str, str]) -> TestClient:
    """Authorized TestClient acting as the per-test registered user."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, headers={"Authorization": f"Bearer {_api_identity['token']}"})


@pytest.fixture
def api_user(_api_identity: dict[str, str]) -> str:
    """Email of the user behind the `api` client fixture."""
    return _api_identity["email"]
