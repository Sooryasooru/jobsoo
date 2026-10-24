# 0001 — Application status lifecycle and transition rules (Step 2.1)

**Status:** accepted · **Date:** 2026-10-23 · **Code:** `app/services/applications.py`

## Decision

Application lifecycle uses these statuses (`app.models.enums.ApplicationStatus`):

`queued → prepared(=ready) → submitted → interviewing/assessment → rejected/offer`,
with `withdrawn` and `closed` reachable from any stage; `rejected`, `withdrawn`
and `closed` are terminal.

Names deliberately overlap the Phase 1 schema (`prepared`, `interviewing`,
`offer`, `submitted`, `rejected`, `closed` already existed as column values and
enum members) to avoid a data migration; `queued`, `assessment`,
`withdrawn` are new values on the same unconstrained `String(30)` column.

## Valid transitions (enforced server-side only)

| From | To |
| --- | --- |
| queued | prepared, withdrawn, closed |
| prepared | submitted, withdrawn, closed |
| submitted | interviewing, assessment, rejected, offer, withdrawn, closed |
| interviewing | assessment, rejected, offer, withdrawn, closed |
| assessment | interviewing, rejected, offer, withdrawn, closed |
| offer | withdrawn, closed |
| rejected / withdrawn / closed | *none (terminal)* |

Repeated requests to set the *current* status are idempotent no-ops: no event,
HTTP 200, always.

## Semantics we never conflate

- **Job availability** (`open`/`closed`/`unknown`, from the source via the
  reconcile sweep or `unknown`) — an expired listing never translates
  automatically into an application status.
- **Preparation** (creating the application row) — never implies anything was
  sent.
- **Submission** — only the explicit `POST /applications/{id}/confirm-submit`
  ("I applied") changes status to `submitted` and only from
  `queued`/`prepared`; re-confirming is a no-op. Repeated confirmation yields
  exactly one `submission_confirmed` event and one `submitted_at` timestamp.
- **Employer response / outcome** — `interview`, `assessment`, `offer`,
  `rejected` are *user recorded reports* of employer actions, never
  observations by this system.

## Integrity mechanics

- Status change: `SELECT ... FOR UPDATE` on the application row, status update
  and `application_events` insert flushed in one transaction, single commit —
  both roll back on failure.
- Duplicate applications: unique `(user_id, job_id, attempt_no)` from Phase 1;
  get-or-create semantics handle insert races by returning the winner.
- Events carry `event_type` plus a JSONB payload with `previous_status`,
  `new_status`, `actor`, `notes`, `external_reference`.
