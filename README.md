# RoomFinder (UTSC)

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

### Backend

```bash
cd backend
uv sync
uv run pytest -m 'not postgres'
uv run uvicorn app.main:app --reload
```

### Frontend

For PostgreSQL setup, migrations, synthetic data, and integration tests, follow
[backend development instructions](backend/README.md#postgresql-foundation).

```bash
cd frontend
npm install
npm run dev
```

The frontend proxies `/api` requests to the backend during development (see `vite.config.ts`).

## Status

Milestones 1–4 implemented: PostgreSQL foundation, public API, React application, and [seven-day local ingestion with atomic publication](backend/INGESTION.md). See [API contracts](backend/README.md#milestone-2-public-rest-api), [frontend guide](frontend/README.md), and [`docs/scope.md`](docs/scope.md). The fixed synthetic seed is not current campus data. Source access/republication authorization and public deployment remain separate requirements.

## Disclaimer

This is an independent student project, not an official UTSC or University of Toronto tool. It is not affiliated with or endorsed by UTSC IT.
