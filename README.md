# RoomFinder (UTSC)

Find an empty classroom at UTSC, right now, near you.

## The problem

UTSC's only bookable study space is the library, and it's small and almost always full. Meanwhile most classrooms sit empty for huge chunks of the day. RoomFinder reads the campus classroom schedule and tells you which rooms have no class running right now, so you actually know where to go.

**This app does not book anything.** It only shows which rooms have no scheduled lecture at the current time. Booking is out of scope, on purpose.

## How it works

The existing HTML parser handles supplied classroom schedule snapshots. PostgreSQL stores stable rooms, versioned occurrences, ingestion evidence, and explicit coverage. The FastAPI backend now exposes validated, snapshot-consistent availability, room schedules, metadata, and health endpoints. Live ingestion, source authorization, and the frontend remain future work.

A room being "free" here means **no class is scheduled there right now**. It doesn't mean the room is unlocked, unoccupied by a club or exam, or otherwise guaranteed empty — see [Data source and limitations](#data-source-and-limitations).

## Backend capabilities

- Public REST availability with complete coverage checks, cancellation handling, next scheduled booking, UTC timestamps, and freshness metadata.
- Building/room metadata, campus-date schedules, public status, liveness, and readiness.
- PostgreSQL integration tests and GitHub Actions backend checks.

## Planned frontend features

- **Free now**: list of rooms with no class currently running, filterable by building
- **Free until**: how long a room stays free, so you're not walking into a room 5 minutes before a 300-person lecture
- **Capacity + room type**: filter by group size
- Planned: location-based recommendations, a 2D campus map, and a crowd-reported "actually empty" signal (see [scope document](docs/scope.md))

## Tech stack

| Layer | Tech |
| --- | --- |
| Backend | Python, FastAPI, SQLModel, PostgreSQL, Alembic, Psycopg 3 |
| Ingestion | httpx, BeautifulSoup4, pandas |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| PWA | vite-plugin-pwa |

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

Milestone 2 backend implemented. See [API setup and contracts](backend/README.md#milestone-2-public-rest-api) and [`docs/scope.md`](docs/scope.md) for the wider roadmap. The fixed synthetic seed is not current campus data.

## Disclaimer

This is an independent student project, not an official UTSC or University of Toronto tool. It is not affiliated with or endorsed by UTSC IT.
