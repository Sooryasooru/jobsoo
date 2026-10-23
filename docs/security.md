# Security notes (Phase 1 prototype)

Phase 1 is a **local, single-user prototype**. Known limitations, deliberately
documented rather than hidden:

## Authentication is deferred

- Every request operates on an auto-created development user
  (`JOBSOO_DEV_USER_EMAIL`, default `dev@example.com`). There is no sign-in.
- **Do not expose this instance publicly.** `app.main` configures CORS to allow
  only the local Vite dev server origin (`http://localhost:5173`), but there is
  no authentication, rate limiting, or IP filtering. Host it only on loopback
  or a trusted LAN.

Phase 2 is expected to introduce real auth (session/OAuth), at which point the
dev-user helpers (`app/services/users.py`) are replaced and every route gains
per-user scoping.

## Data handling

- Uploaded CVs are stored on local disk (`backend/data/uploads/`) with
  SHA-256 checksums recorded in the database; originals are never overwritten.
  There is no encryption at rest beyond OS file permissions.
- PDFs of approved tailored CVs are written to `backend/data/tailored_pdfs/`
  and served with `Cache-Control: private, no-store`.
- Job descriptions are untrusted third-party data. The LLM prompts wrap them
  in explicit `<job_description> … UNTRUSTED` markers and the system prompt
  forbids following instructions inside that content
  (see `app/ai/client.py SYSTEM_GUARDRAIL`). Prompt-injection resistance is
  prompt-level only — still, treat every extracted requirement as advisory.

## Credentials

- Secrets come exclusively from environment variables
  (`.env` at the repo root, git-ignored): `DATABASE_URL`, `ANTHROPIC_API_KEY`,
  `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`. No credentials live in the repository.
- API keys are never sent to the browser; all LLM calls happen server-side.

## Not included in Phase 1

Captcha/anti-abuse, request quotas, audit logging, multi-tenancy, HTTPS
termination (terminate at your local network edge), and application-event
retention policy (the `application_events` table exists but Phase 2 fills it).
