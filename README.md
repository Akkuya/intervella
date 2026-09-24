# RoomFinder (UTSC)

Find an empty classroom at UTSC, right now, near you.

## The problem

UTSC's only bookable study space is the library, and it's small and almost always full. Meanwhile most classrooms sit empty for huge chunks of the day. RoomFinder reads the campus classroom schedule and tells you which rooms have no class running right now, so you actually know where to go.

**This app does not book anything.** It only shows which rooms have no scheduled lecture at the current time. Booking is out of scope, on purpose.

## How it works

UTSC's intranet publishes a read-only classroom schedule per building and day (`classroomreadonly.action`). It lists every room, its capacity, and every scheduled class as a block of 30-minute slots. RoomFinder ingests that schedule, stores it, and computes "free now" / "free until X" on top of it.

A room being "free" here means **no class is scheduled there right now**. It doesn't mean the room is unlocked, unoccupied by a club or exam, or otherwise guaranteed empty — see [Data source and limitations](#data-source-and-limitations).

## Features

- **Free now**: list of rooms with no class currently running, filterable by building
- **Free until**: how long a room stays free, so you're not walking into a room 5 minutes before a 300-person lecture
- **Capacity + room type**: filter by group size
- Planned: location-based recommendations, a 2D campus map, and a crowd-reported "actually empty" signal (see [scope document](docs/scope.md))

## Tech stack

| Layer | Tech |
| --- | --- |
| Backend | Python, FastAPI, SQLModel, SQLite |
| Ingestion | httpx, BeautifulSoup4, pandas |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| PWA | vite-plugin-pwa |

## Project structure

```txt
roomfinder/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + routes
│   │   ├── models.py        # SQLModel tables (Building, Room, Meeting)
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
- Data is refreshed periodically and cached locally so the app still works if a refresh fails.
- All times are `America/Toronto`.

## Getting started

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend proxies `/api` requests to the backend during development (see `vite.config.ts`).

## Status

Early development. See [`docs/scope.md`](docs/scope.md) for the full phased roadmap (MVP → recommendations → 2D map → 3D map → university collaboration).

## Disclaimer

This is an independent student project, not an official UTSC or University of Toronto tool. It is not affiliated with or endorsed by UTSC IT.
