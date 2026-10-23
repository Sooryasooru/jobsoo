# Architecture

*Updated for Phase 1 completion; see git history for the evolving state.*

## Overview (Phase 1)

Phase 1 is a modular monolith:

```
React dashboard ──▶ FastAPI API ──▶ services ──▶ SQLAlchemy models ──▶ PostgreSQL
                                        │
                                        ├── connectors/  (job sources, e.g. Adzuna)
                                        ├── ai/          (Claude calls, validated by Pydantic)
                                        ├── cv/          (CV parsing: pdfminer/docx)
                                        ├── tailoring/   (generation + validation + PDF export)
                                        └── scoring/     (deterministic match logic)
```

## Module responsibilities

| Module                | Responsibility                                                            |
| --------------------- | ------------------------------------------------------------------------- |
| `app/api/routes/`     | HTTP routes only: validation in, Pydantic out. No business logic.          |
| `app/services/`       | Business logic (ingestion pipelines, CV uploads, approval workflow).        |
| `app/db/`             | Declarative base, engine/session factory, dependency injection.            |
| `app/models/`         | SQLAlchemy 2.x ORM models — the single source of truth for persistence.    |
| `app/schemas/`        | Pydantic request/response schemas and AI structured-output schemas.        |
| `app/connectors/`     | Job source connectors. Each connector normalizes to the internal schema.   |
| `app/ai/`             | Claude API access. All outputs validated against Pydantic schemas.         |
| `app/cv/`             | CV parsing (pdfminer for PDF, python-docx for DOCX).                       |
| `app/tailoring/`      | Tailored-CV generation (AI prompt + deterministic fallback), deterministic claim validation against the original CV, and WeasyPrint PDF export for approved versions. |
| `app/scoring/`        | Deterministic job score computation (no AI in the scoring path).           |

## Design decisions

- **AI never validates itself.** LLM outputs are treated as untrusted;
  deterministic Python code validates requirement extractions against a strict
  Pydantic schema and validates every tailored-CV claim against the original
  CV's parsed content (word-overlap plus verbatim number checks). Claims that
  fail validation are stripped and stored in `unsupported_claims` for user
  review — they never reach the approved CV.
- **Scores are computed in Python** from stored requirement/evidence data, so
  scoring is reproducible and unit-testable without network access. Missing
  data scores as `unknown` (unknown portions are reported, never penalized).
- **Every tier stays visible.** No code path hides, filters out, or rejects a
  job because of a low score; stretch and long-shot matches are first-class.
- **Approval is an explicit user action.** Tailored CVs move
  draft → pending_review → approved/rejected; PDF export is possible only for
  approved versions (service check plus a DB CHECK constraint).
- **Auth is deferred** for the local prototype (single dev user); see
  [security.md](security.md) for the limitations and what must change before
  hosting.

## Verification (2026-10-23)

- `pytest`: 91 passed (unit + API + PostgreSQL integration), 87% line coverage on `app`.
- `ruff check` / `ruff format --check`: clean. `mypy --strict` (`app` + `tests`): clean.
- `alembic upgrade head` on an empty database creates all 9 application tables.
- End-to-end exercised against the running API + dashboard: CV upload/parse,
  deterministic match computation, draft → submit → approve → valid PDF download.
- AI-dependent flows (requirement extraction, AI tailoring) are covered by
  mocked-LLM tests and degrade gracefully (explicit "AI unavailable" responses,
  deterministic tailoring fallback) but were not exercised against the live
  Anthropic API — no API key was configured.
