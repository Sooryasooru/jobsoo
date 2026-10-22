"""Shared pytest fixtures.

Integration tests requires a PostgreSQL test database. Configure it via
`JOBSOO_TEST_DATABASE_URL`; the default targets a socket-auth database
`jobsoo_test` on the local machine (see docs/testing.md). Tests that need the
database are marked `@pytest.mark.integration` and skip cleanly when no
database is reachable, so pure-unit tests always run anywhere.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "JOBSOO_TEST_DATABASE_URL", "postgresql+psycopg://soorya@/jobsoo_test?host=/var/run/postgresql"
)
os.environ.setdefault("DATABASE_URL", os.environ["JOBSOO_TEST_DATABASE_URL"])

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


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
def db(engine: Engine) -> Engine:
    """Provide an engine after resetting all tables for isolation."""
    from app.db.base import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
