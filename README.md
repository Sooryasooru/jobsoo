# jobsoo — Job Application Intelligence Platform

Phase 1: job intake (Adzuna + manual import), CV ingestion, requirement
analysis with Claude, explainable deterministic scoring, truthful CV tailoring
with an explicit approval workflow, and PDF export — plus a React dashboard.

> **Phasing.** Phase 2 (application tracking, email analysis, background jobs)
> and Phase 3 (LangGraph agent/chatbot) are deliberately **not implemented**.
> No Celery/Redis/Gmail/Telegram/LangGraph dependencies exist in this code.
> (`applications` / `application_events` tables exist but only as
> forward-compatible schema; no Phase 2 logic reads them.)

## Layout

| Path                 | Purpose                                            |
| -------------------- | -------------------------------------------------- |
| `backend/`           | FastAPI application (`app` package), Alembic, tests |
| `frontend/`          | React + TypeScript + Tailwind dashboard            |
| `docs/`              | [architecture](docs/architecture.md), [database](docs/database.md), [security](docs/security.md) |
| `docker-compose.yml` | Local PostgreSQL 16 (optional)                     |

## Quick start

### Backend

```bash
cp .env.example .env            # repo root; adjust DATABASE_URL if needed
cd backend
uv sync --extra dev             # or: pip install -e ".[dev]"
alembic upgrade head            # create the schema
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Environment variables (all optional in dev, see `backend/app/config.py`):

| Variable           | Purpose                                                     |
| ------------------ | ----------------------------------------------------------- |
| `DATABASE_URL`     | PostgreSQL DSN (required)                                   |
| `ANTHROPIC_API_KEY`| enables AI requirement extraction + AI tailoring            |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | enables the Adzuna ingest button            |

Without the AI key the app still works: extraction is refused with a clear
message and CV tailoring uses the deterministic (no-rewriting) fallback.

### Accounts (Phase 2.3)

The backend and dashboard require sign-in. Register at `http://localhost:5173`
(first visit shows the register/login screen) — accounts are locally-scoped,
per-user workspaces: CVs, profiles, tailored CVs, applications and their event
timelines are isolated per account, while job listings stay shared. Existing
Phase 1 development users keep their data but have no password; register a new
account for use. See [docs/security.md](docs/security.md) for the full model.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (CORS-allowed against the API)
```

### Tests and checks

```bash
cd backend
.venv/bin/pytest --cov=app         # 154 tests; integration tests need Postgres (JOBSOO_TEST_DATABASE_URL)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app tests
```

## Truthfulness guarantees (short form)

- Every tailored bullet must cite evidence refs into the original CV, and a
  deterministic validator (word overlap + verbatim numbers) rejects anything
  that cannot be traced back. Rejected claims are listed in the UI as
  "stripped claims".
- Scores are explainable Python: per-component earned/weight, unknown
  requirements recorded as unknown — never treated as "candidate lacks X".
- All tiers (strong/good/stretch/long_shot) stay visible; no job is hidden by
  a low score, and hard-blocker warnings are shown for manual review.

See [docs/architecture.md](docs/architecture.md) for module responsibilities
and the Phase 1 verification log.
