# academy-signup-eligibility

`enrollment_eligibility_service.check(session_id, viewer)` — academy course
signup eligibility service. Returns one of **12 signup states** plus reason
codes, shared by the course-detail interface and the registration interface so
that page display always matches actual signup results.

Python 3.11+ / FastAPI / SQLAlchemy 2 / PostgreSQL 16. Read-only service:
`check()` issues SELECT statements only, never INSERT/UPDATE/DELETE. Uses only
fictitious test data; no real personal or business information; no third-party
SDK that sends data overseas.

## Judging order (work-order spec, operationalized)

`session_id` = the academy course *session* id (`academy_course.id`). Result =
`(signup_state, reasons)`; HTTP 404 is an error path (exception → 404), not a
signup state.

| # | Condition (first match wins)                     | signup_state        | reasons                          |
|---|--------------------------------------------------|---------------------|----------------------------------|
| 0 | course missing / not visible / soft-deleted      | — (HTTP 404)        | — (`course_not_found`)           |
| 1 | course period finished (`now > period_end`)      | `finished`          | `period_finished`                |
| 2 | cancelled or signup_closed                       | `closed`            | `course_cancelled` / `signup_closed` |
| 3 | not signed up_open_at (`now < signup_open_at`)   | `not_open`          | `signup_not_open`                |
| 4 | delivery_mode = application                      | `application`       | `application_mode`               |
| 5 | current contact has a valid registration for this course (event-module status) | `signed_up` / `waitlisted` / `pending_review` | `existing_registration_*` |
| 6 | not logged in, or phone authorization not completed | `need_auth`      | `login_required` / `phone_auth_required` |
| 7 | audience = member_only and no valid membership (CRM status `active` or `about_to_expire`, `valid_until > now`) | `need_member` | `member_only_no_valid_membership` |
| 8 | fee_mode = entitlement, category within deductible range, equity balance = 0 | `no_entitlement` | `entitlement_balance_zero` |
| 9 | quota full and waitlist not full                 | `waitlist_available`| `quota_full_waitlist_open`       |
|10 | places and waitlist full                         | `closed`            | `quota_and_waitlist_full`        |
|11 | others                                           | `can_signup`        | (empty)                          |

Notes fixed by this implementation:

- A **cancelled** course resolves to state `closed` (step 2), not 404: 404 is
  reserved for missing / invisible / soft-deleted courses (step 0).
- A **cancelled registration** is not a valid registration (step 5 skips it).
- Membership `about_to_expire` counts as valid while `valid_until > now`;
  `valid_until == now` is already invalid (boundary tested).
- Non-members of public courses reach `can_signup` after phone authorization
  (steps 6–7 encode exactly this).
- Quota counting: confirmed = `registered` + `pending_review` (pending still
  occupies a seat); waitlist = `waitlisted`.
- All monetary amounts elsewhere in the platform are stored in minutes; the
  equity balance here is an integer count of equity units.

## Layout

```
app/
  service.py    # enrollment_eligibility_service.check(...) — judging order above
  models.py     # SQLAlchemy 2 models (UUID pk, org_id, site_id, created_at, deleted_at)
  schemas.py    # SignupState(12) / ViewerContext / EligibilityResult / CourseNotFoundError
  gateways.py   # interface files: CrmGateway (S2-CRM), EventGateway (S3-MINI) + DB-backed mocks
  api.py        # FastAPI router: GET /academy/sessions/{session_id}/signup-eligibility
  db.py         # engine/session factory (DATABASE_URL env)
tests/
  test_signup_states.py          # >= 1 case per signup state + boundary cases
  test_readonly_invariants.py    # determinism + zero INSERT/UPDATE assertion
  test_api.py                    # HTTP 404 mapping + response contract
```

## Integration points (mock-first, per work-order dependency note)

`app/gateways.py` defines the two read-only gateway Protocols; the DB-backed
mock adapters in the same file back tests and local runs:

- `CrmGateway` ← **S2-CRM** (membership status, entitlement balance):
  `get_membership(contact_id)`, `get_entitlement_balance(contact_id, category_id)`
- `EventGateway` ← **S3-MINI** (event-module registration records):
  `get_active_registration(course_id, contact_id)`,
  `count_confirmed_registrations(course_id)`, `count_waitlisted(course_id)`

At integration time pass real adapters into
`service.check(session_id, viewer, db, crm=..., events=...)` — the Protocol
signatures are the contract. No other change is required.

## Run & test

Requirements: Python 3.11+, PostgreSQL 16. Either `docker compose up -d
postgres` (uses `docker-compose.yml`) or point `DATABASE_URL` at any PG 16
instance.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
export DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5433/academy_test
pytest tests -v

# HTTP service (optional smoke)
uvicorn app.api:router --app-dir . --port 8080   # then GET /academy/sessions/<uuid>/signup-eligibility
```

Environment variables:

| Variable       | Default                                                        | Meaning            |
|----------------|----------------------------------------------------------------|--------------------|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@127.0.0.1:5433/academy_test` | SQLAlchemy URL |

## Verification record

Environment: Windows x64, Python 3.13.14, PostgreSQL 16.9 (Visual C++ build
1943, 64-bit), SQLAlchemy 2.1.9, psycopg 3.3.9, FastAPI 0.163.2, pytest 9.2.0.
Database: real PostgreSQL 16.9 instance on `127.0.0.1:5433` (created via
`initdb` + `CREATE DATABASE academy_test`); tests run against it — no SQLite
fallbacks, no mocks for the database layer.

Command (full session log, first run of this exact tree):

```
$ DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5433/academy_test python -m pytest tests -v
```

Raw output (`pytest tests -v`, verbatim, 2026-11-18):

```
tests/test_api.py::test_http_404_for_missing_course PASSED               [  3%]
tests/test_api.py::test_http_404_for_invisible_course PASSED             [  6%]
tests/test_api.py::test_http_can_signup_contract PASSED                  [  9%]
tests/test_api.py::test_http_need_auth_anonymous PASSED                  [ 12%]
tests/test_readonly_invariants.py::test_check_is_readonly_and_deterministic PASSED [ 15%]
tests/test_readonly_invariants.py::test_check_readonly_across_all_states PASSED [ 18%]
tests/test_signup_states.py::test_state_finished PASSED                  [ 21%]
tests/test_signup_states.py::test_state_closed_cancelled_course PASSED   [ 25%]
tests/test_signup_states.py::test_state_closed_signup_switch PASSED      [ 28%]
tests/test_signup_states.py::test_state_closed_quota_and_waitlist_full PASSED [ 31%]
tests/test_signup_states.py::test_state_not_open_before_signup_window PASSED [ 34%]
tests/test_signup_states.py::test_state_application_delivery_mode PASSED [ 37%]
tests/test_signup_states.py::test_state_signed_up_existing_registration PASSED [ 40%]
tests/test_signup_states.py::test_state_waitlisted_existing_registration PASSED [ 43%]
tests/test_signup_states.py::test_state_pending_review_existing_registration PASSED [ 46%]
tests/test_signup_states.py::test_cancelled_registration_is_not_valid PASSED [ 50%]
tests/test_signup_states.py::test_state_need_auth_not_logged_in PASSED   [ 53%]
tests/test_signup_states.py::test_state_need_auth_phone_not_authorized PASSED [ 56%]
tests/test_signup_states.py::test_state_need_member_without_membership PASSED [ 59%]
tests/test_signup_states.py::test_state_need_member_expired_membership PASSED [ 62%]
tests/test_signup_states.py::test_state_need_member_about_to_expire_is_valid PASSED [ 65%]
tests/test_signup_states.py::test_state_need_auth_precedes_need_member PASSED [ 68%]
tests/test_signup_states.py::test_state_no_entitlement_zero_balance PASSED [ 71%]
tests/test_signup_states.py::test_no_entitlement_skipped_when_balance_positive PASSED [ 75%]
tests/test_signup_states.py::test_no_entitlement_skipped_when_category_not_deductible PASSED [ 78%]
tests/test_signup_states.py::test_state_waitlist_available_quota_full PASSED [ 81%]
tests/test_signup_states.py::test_state_can_signup_public_course_non_member PASSED [ 84%]
tests/test_signup_states.py::test_state_can_signup_member_only_with_active_membership PASSED [ 87%]
tests/test_signup_states.py::test_state_can_signup_member_only_membership_expiring_boundary PASSED [ 90%]
tests/test_signup_states.py::test_course_not_found_missing PASSED        [ 93%]
tests/test_signup_states.py::test_course_not_found_not_visible PASSED    [ 96%]
tests/test_signup_states.py::test_course_not_found_soft_deleted PASSED   [100%]

======================== 32 passed, 1 warning in 6.27s ========================
```

Read-only verification: `test_check_is_readonly_and_deterministic` and
`test_check_readonly_across_all_states` attach an `after_cursor_execute`
listener and mechanically assert that `check()` executes zero INSERT/UPDATE/
DELETE statements across every reachable state (the listener sanity-checks
that it did capture SELECT traffic, so the zero-write assertion cannot be
vacuously true). Determinism: three repeated calls with identical inputs
return identical results.
