# UTSCVacant frontend

A mobile-first React application for the existing FastAPI availability API. The October 14, 2026 TRD governs coverage, freshness, timezone, and frontend behavior.

## Data notice

Every view displays **Unverified / demo data**. The current API has no source-provenance field, so this frontend never certifies current campus availability. The fixed synthetic seed is not live campus data. There is no hidden demo fallback, production clock override, database client, authentication, scraping, map, recommendation engine, or service worker.

A future ingestion/provenance milestone must establish authorized source coverage before this notice can be replaced. Empty meetings and unknown next bookings never establish availability.

## Local development (PowerShell)

Requirements: Node 22.18+ and npm. Backend/database setup remains in [backend/README.md](../backend/README.md#postgresql-foundation).

Start the existing backend in one terminal:

```powershell
Set-Location C:/Dev/utscVacant/.worktrees/react-frontend/backend
uv sync --locked
$env:DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev'
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

This example uses the disposable local PostgreSQL container from the backend guide. Create/migrate the database first if necessary. Never put real database URLs or credentials in frontend variables.

Start the frontend in another terminal:

```powershell
Set-Location C:/Dev/utscVacant/.worktrees/react-frontend/frontend
npm.cmd ci
npm.cmd run dev -- --port 5173
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` to `http://127.0.0.1:8000`; the browser uses same-origin public REST calls with credentials omitted. No CORS workaround, privileged browser key, or direct PostgreSQL connection is needed.

On macOS/Linux, use `npm` instead of `npm.cmd` and adjust the checkout path.

## Search and navigation

- **Free now** sends the current UTC instant and refreshes every 60 seconds while the tab is visible. Returning to the tab can refresh a Now query.
- **Choose a time** interprets date/time in `America/Toronto`, independently of device timezone. Nonexistent DST times are rejected; repeated times require choosing the first/second occurrence and explicit offset.
- Displayed times use friendly 12-hour Toronto labels. Repeated DST hours include EDT/EST to distinguish occurrences, and overnight windows include the end date. Input/API timestamps retain explicit offsets.
- Duration is 5..240 minutes; building is optional. Availability, filtering, ordering, limits, coverage, and next booking are decided by FastAPI, not the browser.
- Results show the API's search window, room, nullable capacity, next scheduled booking, freshness, last-check time, and count excluded for incomplete coverage. A null next booking means no later booking is known, not unlimited availability.
- Room links open room details and a Toronto calendar-day schedule, including cancellations and explicit partial/unknown coverage warnings. An empty schedule is never labelled available.
- Search parameters are bookmarkable: `mode`, custom `date`, `time`, optional DST `offset`, `duration`, and `building`. `room` and `schedule_date` identify room views. Back/forward restores URL state and room-link focus. A Now bookmark intentionally means now when reopened; it does not freeze a timestamp.
- Fixed searches refresh only on explicit action or a detected dataset change. Status is checked every 60 seconds while visible; dataset IDs form query keys. Freshness labels use newer server metadata only for the same dataset.
- Fetch cancellation and query keys prevent old responses replacing newer searches. Offline/errors suppress current availability claims. Loading, valid empty results, unavailable coverage, stale results, malformed links, service errors, and offline state have distinct messages.

Example fixed-time URL (the API still enforces its rolling 30-day window):

```text
/?mode=custom&date=2026-11-01&time=01%3A30&offset=-05%3A00&duration=90&building=SYN-A
```

## Tests and production build

```powershell
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd test
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:e2e
npm.cmd audit --audit-level=high
```

Build before E2E tests: Playwright launches Vite preview of the production build on loopback port 4173. Tests run on desktop Chromium and mobile Chromium emulation with a device timezone different from Toronto. Node's native TypeScript runner covers conversion, bookmarks, endpoint identity, cancellation, safe errors, and malformed responses. Browser checks cover real UI actions, race handling, offline recovery, source freshness, coverage, keyboard/focus, URL navigation, and DST selection. Axe scans check search and room views; screenshots are captured for visual review.

Browser fixtures in `tests/e2e` are explicitly synthetic and never imported by production code. The fixed backend seed deliberately remains on October 14, 2026. Once that date is outside the rolling search window, a real request against that seed returns an honest API error; the frontend does not fake a current response. Fixture tests provide repeatable UI coverage without changing production time. A separate manual full-stack smoke check also verified the built React application through the same-origin proxy against real FastAPI, migrated PostgreSQL, and the original synthetic seed using isolated test clocks/data.

To inspect the synthetic browser flow locally:

```powershell
npm.cmd run build
npm.cmd run test:e2e -- --project=desktop --headed
```

The CI workflow runs locked install, lint, formatting, strict TypeScript, unit tests, build, audit, and desktop/mobile browser checks. Screenshot/trace artifacts are retained for seven days. Pixel comparisons, physical devices, and manual screen-reader verification are not claimed.

## Production hosting and implementation notes

Serve `dist/` at the site root and reverse-proxy `/api` to FastAPI on the same origin. Vite preview is a local verification server, not the deployment solution. Use HTTPS in deployment and keep all database credentials in backend secret storage. Do not use a `VITE_` variable for a secret.

The client in `src/api.ts` mirrors the public Pydantic responses in `backend/app/schemas.py` and validates network payload shapes. Room responses must match the requested room/date. React escapes text; the UI never injects backend HTML or reflects raw backend errors. Requests use AbortSignal, no-cache, and omitted credentials. There is no persisted availability cache or offline service worker.

Installed React/TanStack Query and Tailwind are reused. Native History/URLSearchParams and Intl handle navigation and Toronto time. No router or date-library dependency is introduced. Playwright, axe, and Prettier are development tools. Unused PWA tooling was removed to avoid an unimplemented caching surface; scoped non-breaking patches resolved the original development-tool advisories.

Authorized ingestion, provenance, production deployment/TLS/role checks, and broader real-device/browser testing remain future work.

## Milestone 5A: appearance and presentation

Appearance offers Light, Dark and System (default). Only the selected preference is stored under `utscvacant.appearance`; blocked storage still allows changes for the session. The small bootstrap in index.html applies the saved/OS choice before the application loads; a deployment CSP must permit that bootstrap using a hash or equivalent policy. No third-party fonts or UI framework were added.

Full room labels consistently combine the API's building code and room number, including basement identifiers. Friendly times always use America/Toronto, independent of device timezone; EDT/EST is shown when a repeated hour needs disambiguation. Source details remain available in an expandable disclosure. The current API does not prove a free-until bound, so these cards continue to show only the next known booking.

Manual synthetic checks: run `npm.cmd run build` then `npm.cmd run test:e2e -- --project=desktop --headed`. Change Appearance through all options, reload, change the OS preference with System selected, open a room, and use browser Back. Check the full room label, compact source details, focus and midnight/repeated-hour labels. The mobile project exercises the same interactions at a narrow viewport. Playwright captures light search and dark search screenshots in test-results; the frontend CI uploads them in frontend-browser-results. Only synthetic fixtures are used. Physical-device and manual screen-reader verification are not claimed.
