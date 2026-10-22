"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check(db: Session = Depends(get_session)) -> dict[str, str]:
    """Report application and database liveness."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}
