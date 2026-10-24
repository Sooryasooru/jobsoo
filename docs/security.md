# Security notes

## Authentication model (Phase 2.3, implemented)

Local first-party auth with opaque bearer session tokens. **Accounts are
per-user; registration is open to anyone who can reach the backend** — the
following model is for a local/trusted-LAN deployment, not a public service
(limitations listed below).

### Passwords

- Hashed with **Argon2id** via `argon2-cffi` (library defaults: memory,
  parallelism, 3 iterations). Plaintext / recoverable passwords are never
  stored; there is no legacy password column.
- Policy: 8–128 characters, enforced in the Pydantic schema and again at the
  hashing layer. No composition rules (NIST SP 800-63B style guidance).
- Login compares against the stored hash in constant time (Argon2 verify);
  unknown accounts and wrong passwords return the **identical generic error**
  (`401 invalid email or password`) so accounts cannot be enumerated.
- Emails are validated with `email-validator` and normalized to a fully
  lowercase canonical form (local part included — an app-level decision, not
  RFC case-sensitivity). `users.email` is unique at the database level;
  duplicate registration returns `409`.

### Sessions (bearer tokens)

- `POST /auth/login` and `POST /auth/register` return an opaque token: 32
  random bytes (secrets.token_hex). **Only the SHA-256 hash of the token is
  stored** (`user_sessions.token_hash`); a database leak alone does not yield
  usable credentials.
- Lifetime: **7 days** (fixed, `SESSION_LIFETIME`). Expired rows are deleted
  lazily on the next resolution attempt. Tokens are not refreshed.
- Logout (`POST /auth/logout`) deletes the presented token's row —
  server-side revocation, idempotent, no client-side-only state.
- Storage on the browser side: `localStorage` (`frontend/src/api.ts`). This is
  the **documented trade-off**: cookie sessions would require cross-origin
  credential cookies plus CSRF tokens for no additional safety in this threat
  model (single user per browser, loopback API). `localStorage` is readable by
  any script on the page — there is no third-party JS, but XSS would expose
  the token. Tokens are cleared immediately on any 401 from a protected route.
- `localStorage` is not used for anything else, and passwords/tokens are never
  logged (structured logging covers user ids and event names only).

### Route protection

- `Authorization: Bearer <token>` is required for every router except the
  explicit public allowlist: `/health`, `/auth/register`, `/auth/login`,
  `/auth/logout`. Protection is applied at `app.include_router(...,
  dependencies=[Depends(get_current_user)])`, so a future route cannot
  silently skip the check.
- The acting user derives exclusively from the token's `user_id`
  (`app/api/deps.py`); no route accepts a client-supplied user identifier.

### Brute-force protection

- In-process sliding-window limiter (`LoginAttemptLimiter`): **10 failed
  logins per email in 10 minutes → 5-minute lockout for that principal**
  (`429 too many failed attempts`). Per-principal, so one account's lockout
  does not deny service to others.
- **Limitation:** the table is per uvicorn worker process. A multi-worker or
  multi-host deployment needs a shared store (e.g. Redis) before exposing a
  public endpoint. There is no captcha; registration rate limiting is
  equivalent and equally per-process.

### User isolation

- Data is scoped at the query level to `user_id` from the token: original CVs,
  candidate profiles, tailored CVs, applications, application events, and job
  matches. Foreign ids return `404` (existence not leaked).
- Jobs are **intentionally global** (shared marketplace listings: one row per
  source), while `job_requirements` extraction is job-global and evidence
  reports are computed per user at request time.
- Cross-user access is covered by integration tests
  (`tests/integration/test_auth.py`): CV reads, application reads/updates/
  events/availability/confirm-submit, tailored CV reads, and profile writes
  performed by a stranger all fail with 404/no-effect.
- Race-based cross-user tests and duplicate-application constraints live in
  `tests/integration/test_applications.py` (unique `(user_id, job_id,
  attempt_no)` + row locking).

### Database and migration

- Migration `c0c1c656a360` ("add user password hashes and sessions") adds
  `users.password_hash` (nullable) and the `user_sessions` table. The
  dev-downgrade path drops only these additions — no user-owned data is
  deleted. Existing Phase 1 rows keep their data; users registered before this
  migration have `password_hash = NULL` and cannot log in until they register
  (same email is accepted only if the row is deleted first; the migration does
  not rewrite addresses).

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

## Not included (remaining limitations)

- Registration is first-come; there is no invite/admin flow, email
  verification, password reset, or 2FA.
- Sessions cannot be listed or revoked client-by-client (single-token logout
  only); no automatic session expiry sweep (rows are deleted lazily).
- Brute-force limiter is per-process (see above); no captcha or global quotas.
- HTTPS termination is left to the local network edge; CORS is fixed to the
  Vite dev origins for the local single-user setup.
- Audit logging exists only at info level (structured logs), not tamper-evident.
