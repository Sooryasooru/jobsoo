# Phase 2 integration readiness — Phase 1 close-out (Step 2.0)

Verified 2026-10-23 against `main` @ `6b925e2` (+ the Step 2.0 close-out commit).
This is a **measured** readiness record: every line below was actually run.

## 1. What was verified and how

| Check | Method | Result |
| ----------------------------- | ------------------------------------------------------------ | --------------------- |
| Git state | `git status`, `git log` | clean tree, 8 commits on `main` |
| Database ↔ migrations | `alembic upgrade head` on a fresh **empty** DB, then diffed `pg_dump -s` against the live `jobsoo_dev` schema | **identical** (only a pg_dump random token differed); scratch DB dropped |
| Backend liveness | `curl /health` | `{"status":"ok"}` |
| Frontend | `curl http://localhost:5173` | 200 |
| Unit/integration tests | `pytest` | **92 passed** |
| Lint/format/types | `ruff check`, `ruff format --check`, `mypy app` (strict) | all clean |
| Job import API | live POST `/jobs/import` (normalized payload) | inserted/updated counts OK |
| Match pipeline | live POST `/jobs/{id}/requirements/extract`, `/match`, `/evidence`, GET `/matches/all` | score+tier computed; evidence/match correctly 400 "extract requirements first" until requirements exist; `/matches/all` sorted, all tiers visible |
| Tailoring | GET `/tailored`, `/cvs`, `/profile` | approved tailored version with exported PDF present from the earlier live run |
| AI flows | live without `ANTHROPIC_API_KEY` | clean documented failure ("AI unavailable: …"), no silent crash |
| CI | `.github/workflows/ci.yml` | pipeline exists (lint/format/mypy/pytest + frontend build on Python 3.12/3.13). **Corrects an earlier Phase 1 note that claimed no CI existed.** |

## 2. Defect found and fixed in Step 2.0

- **`POST /jobs/import` with malformed payloads returned HTTP 500** (Pydantic
  `ValidationError` escaped the route as an unhandled exception).
  Fixed: the route now returns **422** with a client-readable detail
  (`app/api/routes/jobs.py`). Regression test added
  (`tests/integration/test_ingestion.py::test_api_import_invalid_payload_is_422`),
  suite re-run (92 passed) and the fix verified against the **live server**.

## 3. Operational notes for Phase 2

- The dev backend must be started with the real `DATABASE_URL`. The code default
  (`postgresql+psycopg://jobsoo:jobsoo@localhost:5433/jobsoo_dev`) targets the
  docker-compose Postgres, but the running environment's PostgreSQL lives on the
  Unix socket. Your local `.env` (git-ignored, not currently present in the
  repo) or the launcher's environment must carry the socket URL
  (`postgresql+psycopg://<user>@/jobsoo_dev?host=/var/run/postgresql`).
- Vite serves on 5173 and calls the backend directly at
  `http://127.0.0.1:8000` (`VITE_API_BASE` overridable). CORS in `app.main`
  allows only the local Vite origin.
- `uvicorn` was started **without `--reload`** for the live session; restart
  after code changes (Phase 2 should add a documented dev command that does
  include reload).
- `frontend/` ships a committed CI workflow but no frontend test suite yet —
  `npm test --if-present` is a no-op.

## 4. Known gaps / risks affecting Phase 2 design

1. **No authentication** in Phase 1 (single dev user, documented). Phase 2 must
   introduce per-user identity before multi-user-scoped tables
   (`applications`, `email_events`, `outreach_emails`, …) land.
2. **No audit trail** yet for API mutations.
3. **`applications` / `application_events` tables exist but hold no logic** —
   Phase 2 Step 2.1 fills them; statuses and transitions stay code-validated,
   not DB-enforced for the full graph (only basic CHECKs exist).
4. **AI and Adzuna remain unverified against live providers** (no credentials
   configured in this environment; mocked tests + graceful degradation only).
   Must not be reported otherwise.
5. **No token storage/encryption exists yet** — Phase 2's
   `TOKEN_ENCRYPTION_KEY`, Fernet envelope, and disconnect flows are greenfield.
6. Alembic revision `f3be9d289e68` is a **no-op steward revision** (`pass`)
   for `tailored_resumes` naming; harmless but noted for: any Phase 2 down-migrations
   must be authored carefully rather than auto-generated.

## 5. Gate 2.0 verdict

**PASS.** Existing Phase 1 features work, migrations are consistent with the
schema, 92/92 relevant tests pass, lint/types are clean, the one critical
correctness defect found during inspection was fixed and regression-tested, and
required configuration is documented in [`.env.example`](../.env.example).
Live Adzuna/Claude integrations remain **unverified** (no credentials) and are
recorded as such.
