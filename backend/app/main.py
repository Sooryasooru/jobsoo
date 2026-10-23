"""FastAPI application entrypoint.

Phase 1 scope: job intake, CV ingestion/requirement analysis, scoring,
truthful tailoring with approval workflow, and PDF export.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import health
from app.api.routes.cvs import router as cvs_router
from app.api.routes.cvs import router_profiles as profile_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.tailored import router as tailored_router
from app.config import get_settings
from app.logging import configure_logging, get_logger

logger = get_logger(__name__)

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Log application lifecycle events."""
    logger.info("startup", version=__version__)
    yield
    logger.info("shutdown")


app = FastAPI(
    title="jobsoo API",
    description="Job Application Intelligence Platform (Phase 1). "
    "Job intake, CV tailoring with evidence checks, and PDF export.",
    version=__version__,
    lifespan=lifespan,
)

# Local prototype: allow the Vite dev server origins. Auth is deferred and
# documented in docs/security.md - do not expose this instance publicly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(jobs_router)
app.include_router(cvs_router)
app.include_router(profile_router)
app.include_router(tailored_router)
