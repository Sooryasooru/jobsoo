"""Database engine and session management.

Sessions are provided to route handlers via FastAPI dependency
injection (`get_session`) so application code never creates
engine-level state directly.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the given URL (defaults to settings)."""
    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True)


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine (created on first use)."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def set_engine(engine: Engine) -> None:
    """Replace the process-wide engine (used by tests)."""
    global _engine
    _engine = engine


_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory (created on first use)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def set_session_factory(factory: sessionmaker[Session] | None) -> None:
    """Replace the process-wide session factory (used by tests)."""
    global _session_factory
    _session_factory = factory


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
