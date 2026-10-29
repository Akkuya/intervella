# Backend development

Run backend commands from this directory:

```powershell
uv sync
uv run python -m pytest
```

The application import root is `app`. The parser is `app.ingest.parser`,
so use `from app.ingest.parser import parse_schedule`.
From the repository root, tests can also run with:
`backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests`.

When opening the repository root in VS Code, the workspace settings configure
backend test discovery and import analysis. Select `backend/.venv/Scripts/python.exe`
with Python: Select Interpreter if VS Code already remembers another interpreter.

## Parser samples and output

- `tests/fixtures/`: commit small sanitized HTML examples and stable expected JSON
  used by tests. Preserve the table structure, classes, rowspans, and time formats;
  replace personal names, identifiers, event details, tokens, and login markup.
  The current tests already contain a small synthetic HTML example inline.
- `data/`: ignored local HTML snapshots and generated JSON. Keep raw intranet
  captures here, outside committed fixtures.
- `run_parser.py`: a manual smoke-test helper; committing it is reasonable.
  Place a local snapshot at `data/exampledata.html`, then run
  `uv run python run_parser.py`. It writes `data/output.json`.
  Automated tests do not need this helper.

The legacy repository-root `exampledata.html` and `output.json` have been
removed from tracked branch history and are ignored to prevent accidental re-addition.

## PostgreSQL foundation

Implements the database foundation from the Technical Requirements Document v1.0
(October 14, 2026). Milestone 2 adds the availability service and REST endpoints
described below; Milestone 3 supplies the React frontend. Live fetching,
recommendations, authentication, and public deployment remain outside this milestone.
The HTML parser stays independent of database models and configuration.

Milestone 4 adds [seven-day local snapshot ingestion](INGESTION.md): strict parsing,
scope validation, audited staging, anomaly reports and atomic publication. It extends
coverage to multiple intervals while preserving the API contracts and original seed.
Live fetching and authorization for public republication remain unresolved.

SQLModel entities live in `app/models.py`. Alembic owns DDL; application startup
must not use `metadata.create_all()`. Synchronous Psycopg 3 uses five connections
per engine, no overflow, UTC sessions, a 10-second connect timeout, and a 3-second
statement timeout. Importing database configuration opens no connections.

### Local setup: PowerShell and Docker Desktop

PostgreSQL 17 is tested. Start Docker Desktop first. This passwordless, disposable
container binds only to localhost. Never use trust authentication on shared or
production servers. The example URLs contain no password.

```powershell
Set-Location C:\Dev\utscVacant\.worktrees\availability-api\backend
uv sync --locked

# This machine's Docker installation is outside PATH; otherwise use 'docker'.
$docker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --detach --rm --name utscvacant-pg-local --publish 127.0.0.1:55433:5432 --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=utscvacant_dev postgres:17
& $docker exec utscvacant-pg-local pg_isready --username postgres
# Repeat pg_isready until it reports "accepting connections", then continue.

# Sharing the superuser is only for this disposable development container.
$env:DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev'
$env:INGESTION_DATABASE_URL = $env:DATABASE_URL
$env:MIGRATION_DATABASE_URL = $env:DATABASE_URL
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/postgres'

uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run python -m app.seed --synthetic
uv run python -m app.seed --synthetic
```

`DATABASE_URL`, `INGESTION_DATABASE_URL`, and `MIGRATION_DATABASE_URL` are required
by their respective consumers. No role fallback or SQLite fallback exists.
`postgresql://` and `postgresql+psycopg://` both select Psycopg 3. `.env.example`
lists names only; the application does not load environment files automatically.

### Verification

```powershell
uv run pytest --require-postgres
uv run pytest -m postgres --require-postgres
uv run pytest -m 'not postgres'
uv run ruff check .
uv run ruff format --check app/db.py app/models.py app/seed.py migrations tests/test_db.py tests/conftest.py tests/test_postgres.py tests/test_seed.py
uv run mypy .
& $docker exec utscvacant-pg-local psql --username postgres --dbname utscvacant_dev --command 'SELECT id, active_dataset_id FROM utscvacant.dataset_state;'
& $docker exec utscvacant-pg-local psql --username postgres --dbname utscvacant_dev --command 'SELECT dataset_id, room_id, completeness FROM utscvacant.room_coverage ORDER BY dataset_id, room_id;'
```

`TEST_DATABASE_URL` must target a disposable local server with `CREATEDB`
permission. Each integration test creates a random `utscvacant_test_*` database,
migrates it, then drops only that database. The supplied database is not dropped
or truncated. Without this variable PostgreSQL tests skip; `--require-postgres`
turns missing configuration into an error. Do not use a production server.

Tests cover constraints, indexes, migration/model consistency, downgrade and
re-upgrade, SQLModel writes, UTC instant storage, stable room identities, coverage,
singleton state, publication prerequisites, immutable published payloads,
concurrent publication/payload locking, rollback, and seed repeatability.
Availability calculations and offset-aware API validation are covered. Source
wall-clock ambiguity rejection belongs to the future normalization worker; this
milestone does not change the HTML parser.

### Entities and integrity

- `buildings`: bigint identity; unique nonempty code and nonempty name.
- `rooms`: bigint identity; building FK; unique building/room number; nullable
  positive capacity; active flag. Parser room IDs are not database IDs.
- `ingestion_runs`: UUID; timestamptz start/finish; `running|succeeded|failed`;
  lowercase SHA-256 input hash; JSONB counts object; optional short error code.
  Finished runs require a finish timestamp no earlier than their start.
- `datasets`: UUID; run FK; source-fetch and publication timestamps;
  explicit `America/Toronto` zone name, stored separately from instants.
- `dataset_state`: exactly one row (`id = 1`); nullable active dataset FK.
  Migration starts with no active dataset; deletion/truncation is rejected.
- `room_coverage`: dataset/room composite PK; positive interval;
  `complete|partial|unknown`. No completeness default or implicit coverage rows.
- `meeting_occurrences`: bigint identity; dataset/room FKs; nonempty source key;
  positive interval; `scheduled|cancelled`; unique dataset/source key;
  B-tree index `(dataset_id, room_id, starts_at)`.

Foreign keys are restrictive, with no cascading deletion. Publication requires
a run marked `succeeded`. Published dataset metadata, occurrences, and coverage
are immutable. Child writes lock parent datasets before checking publication,
including moving rows between versions. Occurrence/coverage truncation is blocked.
Published datasets cannot currently be deleted; controlled retention is future work.

These guards enforce structure, not source validation. The future ingestion command
must validate coverage, anomalies, source permissions, and timezone/exception rules
before marking a run successful. It must serialize publishers, prevent source-age
regression, and set publication time and pointer in one transaction. This change
provides no production publisher. Explicit pointer rollback to an older published
dataset remains possible. Database owners can bypass guards; application roles
must not own tables.

### Synthetic seed

The seed uses fixed IDs, UTC timestamps, and hashes. It creates two synthetic
buildings, five rooms, two published dataset versions, three runs (one failed),
eight coverage rows, and four occurrences (including cancellation and adjacency).
Both versions reference the same stable rooms. Current coverage includes two
complete rows, one partial row, one unknown row, and one room with no coverage.
No meetings never implies complete coverage. The fixed schedule date is
October 14, 2026; this is not current campus data.

Seed writes commit together. Repeating seed is a no-op if its fixed current
dataset exists; it does not reset the pointer or repair modified seed data.
Otherwise it refuses a nonempty application schema. Identity sequences are
reconciled after explicit synthetic IDs. It never fetches a source.

### Deployment boundary

Tables/functions use private schema `utscvacant`. Migration revokes PUBLIC access
to schema, tables, sequences, and functions. Keep this schema out of Supabase's
exposed schemas. Verify actual `anon` and `authenticated` roles before deployment;
local tests do not establish Supabase Data API isolation.

Provision distinct credentials outside the repository: API gets schema USAGE
and SELECT; ingestion gets narrowly scoped SELECT/INSERT/UPDATE, sequence usage,
and function execution; migration owns DDL. Do not grant ingestion ownership,
TRUNCATE, or trigger-disabling privileges. Do not grant browser roles access.
Alembic's version table remains in the default schema under migration ownership.

Production URLs require verified TLS (`sslmode=verify-full` and appropriate CA).
Use direct/session-pooler connections and the provider's migration endpoint.
Transaction-pooler compatibility, real role grants, TLS, and connection budgets
need deployment checks. Never put database URLs in frontend variables, persist
credentials here, or log raw source errors. Error-code format does not replace
sanitization by the future worker.

### Rollback and cleanup

Only for unused, disposable development data:

```powershell
uv run alembic downgrade base
uv run alembic upgrade head
```

Downgrade deletes all seven tables and data, functions, and private schema.
This change does not convert SQLite data or assume a timezone for naive timestamps.
Before a production cutover, back up the source, reconcile IDs/counts/timezones,
and test restore. Prefer forward repair after writes; keep code/config compatible.

Stop the disposable container when finished; its data and anonymous volume disappear:

```powershell
& $docker stop utscvacant-pg-local
Remove-Item Env:DATABASE_URL, Env:INGESTION_DATABASE_URL, Env:MIGRATION_DATABASE_URL, Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

## Milestone 2: public REST API

After local migration/seed setup above, start the API from `backend`:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev'
$env:ALLOWED_ORIGINS = 'http://localhost:5173'
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Reuse an existing `utscvacant-pg-local` container instead of starting it again.
For an older container created without `POSTGRES_DB`, create the missing database
once with `docker exec utscvacant-pg-local createdb -U postgres utscvacant_dev`.
Alembic creates tables inside an existing database, not the PostgreSQL database itself.
Docker Desktop must already be running; use the `$docker` path above if needed.

OpenAPI at <http://127.0.0.1:8000/docs> defines the actual schemas. Every endpoint
is public and read-only. The browser calls FastAPI; it never receives database
credentials or reads PostgreSQL directly.

| GET endpoint | Contract |
| --- | --- |
| `/api/v1/availability` | Required offset-aware `start`; `duration_minutes` 5..240, default 60; recognized `building` optional; `limit` 1..100, default 50. Returns `query`, `data`, and `meta`. |
| `/api/v1/buildings` | `data` contains buildings with active rooms, ordered by code then ID. No dataset is required for stable metadata. |
| `/api/v1/rooms/{room_id}` | `data` contains room ID, building code, room number, nullable capacity, and active flag. Unknown room: 404. |
| `/api/v1/rooms/{room_id}/schedule?date=YYYY-MM-DD` | Meetings overlapping one campus local date, including cancellations; room metadata, UTC day bounds, coverage, and freshness. |
| `/api/v1/status` | Active dataset ID, source timestamp, age, period, freshness, usability, degraded flag, and unknown-room count. No source URLs, hashes, run errors, or credentials. |
| `/health/live` | 200 while the process responds; never opens a database connection. |
| `/health/ready` | 200 with usable complete coverage for the next five minutes; otherwise 503. Covered stale data can remain ready and is explicitly degraded. |

Availability uses `[start,end)`. A scheduled meeting conflicts exactly when
`meeting.starts_at < end AND meeting.ends_at > start`. Cancellation does not block
a room. Complete coverage must contain the entire requested interval. Results
exclude inactive rooms and rooms with partial, unknown, missing, or too-short
coverage. `unknown_room_count` counts excluded active rooms within the building
filter, independent of result limit. Metadata coverage is `partial` if this count
is nonzero; otherwise `complete`.

Results order by building code, room number, then room ID. `has_more` comes from
fetching at most `limit + 1` rows. `next_booking` is the earliest scheduled start
at or after the requested end in the same dataset. Null means no later booking
is known, not unlimited availability. Schedule availability does not establish
physical vacancy, access, permission to study, closures, or unscheduled use.

Each API database dependency opens one read-only `REPEATABLE READ` transaction.
The service captures the published active dataset once. Meetings, coverage,
freshness, room state, and metadata stay in that snapshot even if publication
races the request. The foundation's original writable session dependency remains
available to non-HTTP commands. No HTTP path fetches or publishes schedule data.

Start must lie between now minus five minutes and now plus thirty days, inclusive.
Incoming `start` must be an ISO timestamp with `Z` or an explicit offset; numeric
epoch strings and naive local times are rejected. All output instants use UTC.
An explicit DST offset identifies an instant. Calendar schedule dates use separate
campus midnights, so DST days span 23 or 25 hours rather than a fixed 24 hours.

Published period is the min/max coverage envelope of active rooms. This envelope
does not certify coverage between disjoint room intervals. Searches outside it
return 422 `outside_dataset_coverage`. A query inside it with no fully covered
eligible rooms returns 503 `coverage_unavailable`. A fully covered query where all
rooms are busy returns a valid empty result. Schedule endpoints expose partial
day coverage rather than calling the whole day complete; entirely unsupported
dates return 422. No active published dataset returns 503 `dataset_unavailable`.

Every API error has this shape, without reflecting raw input or exception text:

```json
{"error":{"code":"invalid_request","message":"Check request fields.","request_id":"generated-uuid","fields":["start"]}}
```

`X-Request-ID` is server-generated on all responses. Responses use `Cache-Control:
no-cache`. Database failures return a safe 503; unexpected errors return a safe
500; request timeout returns 504. Logs use route templates, request ID, duration,
status, and dataset ID rather than raw query strings or exception details.
Application lifespan disables Uvicorn's raw access logger. Safe request records use
Uvicorn's configured server logger, so the documented default startup emits them.
CORS wraps the error boundary; allowed origins can read structured 500/504 errors,
and preflight responses also retain server-generated request IDs.

### API configuration and verification

| Variable | Default | Meaning |
| --- | --- | --- |
| `FRESHNESS_MAX_AGE_HOURS` | `36` | Positive finite source-age threshold. Exactly 36 hours is fresh; older data is stale. |
| `MAX_AVAILABILITY_LIMIT` | `100` | Server cap, 1..100. Explicit requests exceeding it return 422; omitted limit uses the smaller of 50 and this cap. |
| `API_REQUEST_TIMEOUT_SECONDS` | `15` | Finite timeout above the existing 3-second PostgreSQL statement timeout. |
| `ALLOWED_ORIGINS` | empty | Exact comma-separated HTTP(S) origins; no wildcard, credentials, paths, or cookies. Empty means no cross-origin browser access. |

Freshness is calculated at request time, with `freshness: stale` and
`warnings: ["stale_dataset"]` when necessary. Staleness does not erase valid
coverage or certify missing coverage. There is no server cache or production
clock override. TLS, read-only database login grants, external proxy rate limits,
representative load tests, and Supabase exposure checks remain deployment gates.

The deterministic seed intentionally stays on October 14, 2026. A real request
for that date eventually fails the rolling start window, and readiness fails
after its coverage expires. This is expected; do not change the seed or production
clock to hide expired data. Run the original seed through FastAPI with a controlled
test clock, or exercise a separate current-time fixture over actual HTTP:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/postgres'
uv run pytest tests/test_api.py::test_original_seed_through_api_with_controlled_clock --require-postgres
uv run pytest tests/test_http.py --require-postgres
uv run pytest --require-postgres
uv run ruff check .
uv run ruff format --check .
uv run mypy .
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/v1/buildings
```

The CI workflow runs these checks on Ubuntu with PostgreSQL 17, Python 3.13,
locked dependencies, read-only repository permissions, and pinned action commits.
Integration tests cannot silently skip because CI uses `--require-postgres`.
Two current upstream TestClient deprecations (HTTPX and AnyIO) may be reported;
they do not affect API requests or test results. No new dependency is added for
this milestone.
