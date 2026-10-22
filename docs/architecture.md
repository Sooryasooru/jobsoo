# Architecture

*Updated as implementation progresses; see git history for the evolving state.*

## Overview (Phase 1)

Phase 1 is a modular monolith:

```
React dashboard ──▶ FastAPI API ──▶ services ──▶ SQLAlchemy models ──▶ PostgreSQL
                                        │
                                        ├── connectors/  (job sources, e.g. Adzuna)
                                        ├── ai/          (Claude calls, validated by Pydantic)
                                        ├── cv/          (parsing + WeasyPrint export)
                                        └── scoring/     (deterministic match logic)
```

## Module responsibilities

| Module                | Responsibility                                                            |
| --------------------- | ------------------------------------------------------------------------- |
| `app/api/routes/`     | HTTP routes only: validation in, Pydantic out. No business logic.          |
| `app/services/`       | Business logic (ingestion pipelines, approval workflow, versioning).       |
| `app/db/`             | Declarative base, engine/session factory, dependency injection.            |
| `app/models/`         | SQLAlchemy 2.x ORM models — the single source of truth for persistence.    |
| `app/schemas/`        | Pydantic request/response schemas and AI structured-output schemas.        |
| `app/connectors/`     | Job source connectors. Each connector normalizes to the internal schema.   |
| `app/ai/`             | Claude API access. All outputs validated against Pydantic schemas.         |
| `app/cv/`             | CV parsing (pdfminer/docx) and HTML→PDF export (WeasyPrint/Jinja2).        |
| `app/scoring/`        | Deterministic job score computation (no AI in the scoring path).           |

## Design decisions

- **AI never validates itself.** LLM outputs are treated as untrusted; a
  deterministic validator cross-checks every factual claim against candidate
  evidence (see docs/ai-reliability.md).
- **Scores are computed in Python** from stored requirement/evidence data, so
  scoring is reproducible and unit-testable without network access.
- **Auth is deferred** for the local prototype (single dev user); see
  docs/security.md for the limitations and what must change before hosting.
