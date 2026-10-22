# jobsoo — Job Application Intelligence Platform

Phase 1: job intake (Adzuna), CV ingestion, requirement analysis with Claude,
explainable deterministic scoring, truthful CV tailoring with an explicit
approval workflow, and PDF export.

> **Phasing.** Phase 2 (application tracking, email analysis, background jobs)
> and Phase 3 (LangGraph agent/chatbot) are deliberately **not implemented**.
> No Celery/Redis/Gmail/Telegram/LangGraph dependencies exist in this code.

## Layout

| Path                | Purpose                                      |
| ------------------- | -------------------------------------------- |
| `backend/`          | FastAPI application (`app` package), Alembic |
| `frontend/`         | React + TypeScript + Tailwind dashboard      |
| `docs/`             | Architecture, database, API, testing docs    |
| `docker-compose.yml`| Local PostgreSQL 16 (optional)               |

See [docs/architecture.md](docs/architecture.md) for module responsibilities.
