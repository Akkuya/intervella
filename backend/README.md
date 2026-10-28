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
(October 14, 2026). Availability, endpoints, source normalization, production
publication, live fetching, frontend, and authentication remain outside this change.
The HTML parser stays independent of database models and configuration.

SQLModel entities live in `app/models.py`. Alembic owns DDL; application startup
must not use `metadata.create_all()`. Synchronous Psycopg 3 uses five connections
per engine, no overflow, UTC sessions, a 10-second connect timeout, and a 3-second
statement timeout. Importing database configuration opens no connections.

### Local setup: PowerShell and Docker Desktop

PostgreSQL 17 is tested. Start Docker Desktop first. This passwordless, disposable
container binds only to localhost. Never use trust authentication on shared or
production servers. The example URLs contain no password.

```powershell
Set-Location C:\Dev\utscVacant\.worktrees\postgresql-foundation\backend
uv sync --locked

# This machine's Docker installation is outside PATH; otherwise use 'docker'.
$docker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --detach --rm --name utscvacant-pg-local --publish 127.0.0.1:55433:5432 --env POSTGRES_HOST_AUTH_METHOD=trust postgres:17
& $docker exec utscvacant-pg-local pg_isready --username postgres
# Repeat pg_isready until it reports "accepting connections", then continue.
& $docker exec utscvacant-pg-local createdb --username postgres utscvacant_dev

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
uv run mypy --explicit-package-bases app/db.py app/models.py app/seed.py
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
Availability calculations and local-time ambiguity rejection are deferred.

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
