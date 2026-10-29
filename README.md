# Intervella (UTSC)

Find an empty classroom at UTSC, right now, near you.

## The problem

UTSC's only bookable study space is the library, and it's small and almost always full. Meanwhile most classrooms sit empty for huge chunks of the day. RoomFinder reads the campus classroom schedule and tells you which rooms have no class running right now, so you actually know where to go.

**This app does not book anything.** It only shows which rooms have no scheduled lecture at the current time. Booking is out of scope, on purpose.

## How it works

The HTML parser handles supplied classroom schedule snapshots. PostgreSQL stores versioned schedule data and explicit coverage. FastAPI provides validated availability and room schedules; the React application supports current/custom searches, bookmarks, room details, and honest freshness/coverage states. Live ingestion and source authorization remain future work. Every frontend view clearly labels data as unverified/demo.

A room being "free" here means **no class is scheduled there right now**. It doesn't mean the room is unlocked, unoccupied by a club or exam, or otherwise guaranteed empty — see [Data source and limitations](#data-source-and-limitations).

## Backend capabilities

- Public REST availability with complete coverage checks, cancellation handling, next scheduled booking, UTC timestamps, and freshness metadata.
- Building/room metadata, campus-date schedules, public status, liveness, and readiness.
- PostgreSQL integration tests and GitHub Actions backend checks.

## Frontend capabilities

- Free now or custom Toronto date/time, duration selection, and building filters.
- Room results with known capacity, next scheduled booking, freshness, and coverage exclusions.
- Bookmarkable searches, room details/day schedules, keyboard navigation, and responsive layouts.
- Explicit loading, empty, error, stale, offline, and incomplete-coverage states; no client-side availability calculation.
- See [frontend setup and verification](frontend/README.md). Maps, crowd reports, recommendations, and authentication remain outside this milestone.

## Tech stack

| Layer | Tech |
| --- | --- |
| Backend | Python, FastAPI, SQLModel, PostgreSQL, Alembic, Psycopg 3 |
| Ingestion | httpx, BeautifulSoup4, pandas |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Frontend tests | Node test runner, Playwright, axe |

## Project structure

```txt
roomfinder/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + routes
│   │   ├── models.py        # Stable rooms, datasets, coverage, occurrences
│   │   ├── db.py
│   │   ├── services/
│   │   │   ├── availability.py   # is a room free / free until when
│   │   │   └── recommend.py      # recommendation scoring
│   │   └── ingest/
│   │       ├── fetch.py     # pull raw schedule HTML
│   │       ├── parse.py     # HTML -> clean rows
│   │       └── load.py      # write to DB
│   ├── data/                 # cached raw snapshots (gitignored)
│   └── tests/
├── frontend/
│   └── src/ (api/, components/, pages/, hooks/)
└── docs/
```

## Data source and limitations

- Source: UTSC intranet classroom schedule (behind UTORid login).
- The schedule reflects **scheduled classes only**. It does not know about ad hoc bookings, exams, clubs already using a room, or locked doors. Treat "free" as "probably free," not a guarantee.
- Automated refresh and publication remain future work. The database foundation retains dataset versions and failed-run evidence.
- All times are `America/Toronto`.

## Getting started

### Windows / PowerShell quick start

Prerequisites: Windows 11, Windows PowerShell 5.1 or PowerShell 7, Docker Desktop
running Linux containers, uv with Python 3.13+, and Node.js 22.18+ with npm.
PostgreSQL 17 is tested. Docker may be on PATH or in Docker Desktop's standard
`%LOCALAPPDATA%/Programs/DockerDesktop/resources/bin` location. No global npm
packages, Pester, or orchestration framework is required.

One-time setup, from your checkout root:

```powershell
Set-Location C:\Dev\utscVacant
# Only copy if you do not already have .env.local; keep your existing values.
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
# Edit .env.local to identify your EXISTING database and container.
notepad .env.local
Push-Location backend
uv sync --locked --python 3.13
Pop-Location
Push-Location frontend
npm.cmd ci
npx.cmd playwright install chromium
Pop-Location
```

Then the everyday workflow is:

```powershell
git pull --ff-only
.\dev.ps1
# Ctrl+C stops the application servers. PostgreSQL remains running.
.\check.ps1
.\check.ps1 -Fast
```

You can run checks in a second terminal while development is running. Scripts
resolve paths relative to their own location, so invoking an absolute script path
also works from another directory. Existing PowerShell environment variables take
precedence over `.env.local`. This ignored file accepts only literal `DATABASE_URL`,
`TEST_DATABASE_URL`, and `POSTGRES_CONTAINER` entries, optionally quoted; it is never
executed as PowerShell. Do not commit credentials, private HTML, or manifests.
The scripts do not persist environment changes in your terminal.

`dev.ps1` verifies dependencies/configuration, starts the named existing container
if stopped, and makes a read-only connection/schema probe. It never creates a
container/database, runs migrations, seeds, imports, or changes the active dataset.
It checks both services before reporting READY:

- App: <http://127.0.0.1:5173>
- API documentation: <http://127.0.0.1:8000/docs>
- Liveness: <http://127.0.0.1:8000/health/live>
- Dataset readiness: <http://127.0.0.1:8000/health/ready>

Logs have `[backend]` / `[frontend]` prefixes. Ctrl+C, startup failure, or closing
the owning PowerShell process cleans up its worker/reloader trees using a Windows
job. Only these application processes are owned; PostgreSQL and unrelated servers
are left alone. Starting again while ports 8000/5173 are occupied fails with an
explanation instead of killing or silently reusing the existing servers. No
separate status/stop scripts are needed. READY means reachable services, not that
published coverage is current or complete.

### Database safety and initial provisioning

For the existing privately imported database, keep its current name, port, volume,
and container. **Do not recreate, reseed, reset, or truncate it.** Local URLs must
use a loopback TCP host, explicit user/database, and no query parameters. The
configured port must match the named container's fixed loopback port binding.
No connection values are printed by the launchers.

Only on a **new machine with no existing container/data**, you may explicitly
provision a new persistent local database (never run this to replace existing data):

```powershell
docker run --detach --name utscvacant-pg-local `
  --publish 127.0.0.1:55433:5432 `
  --volume utscvacant-pg-data:/var/lib/postgresql/data `
  --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=utscvacant_dev postgres:17
```

Loopback-only trust authentication is for local development, not shared hosting.
Before any manual migration on existing data, take a verified backup and review
the migration. In `backend`, set `MIGRATION_DATABASE_URL` explicitly in that
terminal, then inspect `uv run alembic current` and `uv run alembic history`.
Run `uv run alembic upgrade head` only after that review, or against a newly
provisioned empty database. Startup never does this for you. Do not run the seed
against the privately imported database. See the [backend guide](backend/README.md)
for separate database/ingestion roles and synthetic-only fixtures.

### Checks and troubleshooting

Full `check.ps1` runs the native workflow regressions and existing CI commands: Ruff lint/format, mypy, pytest with
`--require-postgres`, ESLint, Prettier, TypeScript, unit tests, production build,
Playwright desktop/mobile, and `npm audit --audit-level=high`. Its summary retains
all independent failures and returns a nonzero exit code on failure. A failed
build skips browsers rather than testing stale assets. Browser tests require port
4173 free and the Chromium installation above; a fresh preview server is required.
Existing backend/frontend CI workflows are unchanged. A small Windows workflow
tests these scripts with both PowerShell versions.

For full checks, `TEST_DATABASE_URL` must use the selected local server's
maintenance database **`/postgres`**, distinct from `DATABASE_URL`. The test role
needs CREATEDB. The existing fixtures create/migrate/drop only random
`utscvacant_test_*` databases. Development/ingestion/migration URLs are removed
from the test process environment and restored afterward. An unsafe test target
aborts before database access. Fast mode needs no Docker/database connection;
it clears test database configuration, selects non-PostgreSQL tests, skips
integration and browser tests explicitly, and still runs audit/build/static checks.

- **Missing configuration/schema:** edit `.env.local`, confirm the existing
  database name, and review migration status. Nothing is silently initialized.
- **Docker unavailable/container missing:** start Docker Desktop or check the
  configured container name. A missing container is not recreated automatically.
- **Port in use:** use Ctrl+C in the existing launcher or close the conflicting
  service yourself. No process is stopped merely because it uses a port.
- **Missing packages/browser:** rerun the locked setup commands above.
- **PowerShell blocks scripts:** for trusted repository code, use a one-process
  policy, e.g. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\dev.ps1`
  (or `check.ps1 -Fast`). This does not change machine/user policy. Organization
  policies may still require administrator guidance.

Individual debugging commands from `backend`: `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy .`, and
`uv run pytest --require-postgres` with the safe maintenance test URL.
From `frontend`: `npm.cmd run lint`, `npm.cmd run format:check`,
`npm.cmd run typecheck`, `npm.cmd test`, `npm.cmd run build`,
`npm.cmd run test:e2e`, and `npm.cmd audit --audit-level=high`.
Workflow-only regression tests: `.\scripts\tests\workflow.tests.ps1`.

## Status

Milestones 1–4 implemented: PostgreSQL foundation, public API, React application, and [seven-day local ingestion with atomic publication](backend/INGESTION.md). See [API contracts](backend/README.md#milestone-2-public-rest-api), [frontend guide](frontend/README.md), and [`docs/scope.md`](docs/scope.md). The fixed synthetic seed is not current campus data. Source access/republication authorization and public deployment remain separate requirements.

## Disclaimer

This is an independent student project, not an official UTSC or University of Toronto tool. It is not affiliated with or endorsed by UTSC IT.
