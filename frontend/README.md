# Intervella frontend

A mobile-first React application for the existing FastAPI availability API. The October 14, 2026 TRD governs coverage, freshness, timezone, and frontend behavior.

## Data notice

Every view displays **Unverified / demo data**. The current API has no source-provenance field, so this frontend never certifies current campus availability. The fixed synthetic seed is not live campus data. There is no hidden demo fallback, production clock override, database client, authentication, scraping, map, recommendation engine, or service worker.

A future ingestion/provenance milestone must establish authorized source coverage before this notice can be replaced. Empty meetings and unknown next bookings never establish availability.

## Local development (PowerShell)

Requirements: Node 22.18+ and npm. Backend/database setup remains in [backend/README.md](../backend/README.md#postgresql-foundation).

Start the existing backend in one terminal:

```powershell
$repoPath = git rev-parse --show-toplevel
Set-Location "$repoPath/backend"
uv sync --locked
$env:DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev'
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

This example uses the disposable local PostgreSQL container from the backend guide. Create/migrate the database first if necessary. Never put real database URLs or credentials in frontend variables.

Start the frontend in another terminal:

```powershell
$repoPath = git rev-parse --show-toplevel
Set-Location "$repoPath/frontend"
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

Appearance offers Light, Dark and System (default). Only the selected preference is stored under `utscvacant.appearance`; blocked storage still allows changes for the session. The small bootstrap in index.html applies the saved/OS choice before the application loads; a deployment CSP must permit that bootstrap using a hash or equivalent policy. Fonts remain local/system fonts; custom controls use the existing React Aria primitives.

Full room labels consistently combine the API's building code and room number, including basement identifiers. Friendly times always use America/Toronto, independent of device timezone; EDT/EST is shown when a repeated hour needs disambiguation. Source details remain available in an expandable disclosure. Milestone 5C adds server-proven free-until bounds; null next booking still never establishes unlimited availability.

Manual synthetic checks: run `npm.cmd run build` then `npm.cmd run test:e2e -- --project=desktop --headed`. Change Appearance through all options, reload, change the OS preference with System selected, open a room, and use browser Back. Check the full room label, compact source details, focus and midnight/repeated-hour labels. The mobile project exercises the same interactions at a narrow viewport. Playwright captures light search and dark search screenshots in test-results; the frontend CI uploads them in frontend-browser-results. Only synthetic fixtures are used. Physical-device and manual screen-reader verification are not claimed.

## Milestone 5B: calendars

Building schedules selects a building and Toronto date using one bounded batch request. Room details use the same server-derived periods. Available, scheduled and unknown states have text as well as color; coverage gaps stay unknown. Horizontal scrolling keeps room labels visible on mobile. The current-time marker appears on today's rows. The accessible schedule list remains available beneath the timeline.

Show scheduled events persists locally. Switching it off hides annotations without hiding occupied time. Select a block with mouse or keyboard to open its interval dialog; Escape closes it and returns focus. Current data supplies timing/status only: labels are Scheduled event or Cancelled event. Actual course names require a separately authorized source and are not implemented.

Manual synthetic checks: open a result, toggle event annotations, select a cancelled event and press Escape, change/step the date, then open Building schedules and follow a room/back link. Check unknown rows, narrow-screen horizontal scrolling and dark mode. Browser tests capture room-calendar.png, building-calendar.png and calendar-scale-dark.png under ignored test-results and CI artifacts. No private captures are used.

## Milestone 5C: search and favourites

Search length offers Duration or Available until with an explicit end date/time. Both ends use Toronto time and require occurrence selection during a repeated hour; windows remain 5–240 elapsed minutes. Room name matches normalized building/room identifiers (AA112 / AA-112), and sorting is performed by the API before limiting results. Include other rooms and next known openings shows scheduled/unknown listings without claiming they are currently available. Free-until and next-known-opening values are supplied by the API, never calculated from missing events in the browser. The 24-hour lookahead and unknown-gap limitations are stated in the UI.

Save rooms on cards or room details, and buildings on Building schedules. Saved rooms checks all IDs in one request using the current search time/duration, ignoring building/name filters. Choose Change search time to edit that window. Missing and inactive listings are explicit and can be removed; historical room details remain accessible. Only bounded IDs/codes are stored in `utscvacant.favourites` (100 rooms, 50 buildings). Availability is never persisted. Blocked storage permits session-only favourites; this is not cross-device sync.

Manual synthetic checks: choose a custom start, switch Search length to Available until, set the end, name and sort, submit and reload the bookmarked URL. Try midnight and both repeated-hour offsets. Enable next known openings and inspect unknown/conflicting rooms. Save two rooms and a building, open Saved rooms, reload, change the search time, and remove them. Go offline and ensure cached results stop claiming current availability. Inspect the same flows in dark mode and a narrow viewport. Browser tests generate smart-search.png and saved-rooms.png alongside the calendar screenshots in CI artifacts.

For the complete current gate from the frontend directory:

```powershell
npm.cmd ci
npm.cmd run lint
npm.cmd run format:check
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

Backend verification remains `uv run pytest --require-postgres`, Ruff and mypy using a disposable test database (see the backend guide). No development clock override or live-campus demo fallback was added. The immutable synthetic seed remains fixed in time; controlled test fixtures exercise the current API separately.

Calendar navigation remains valid when a retained Now/until search expires. The room back link retains the selected building-calendar day, and building controls keep focus during date/building changes. Saved Now checks refresh on visibility return and reconnect, matching Find a room; fixed-time checks refresh when the published dataset changes.

Mixed search results use Room status and explicit counts for available, scheduled-conflict, unknown and inactive listings; the per-room badges remain authoritative. Include-next never labels the whole collection available. Saved-room status counts apply only to returned saved listings.

Free now with a fixed Available until end stops being a valid request when fewer than five minutes remain. The app then hides earlier room claims, stops availability polling, and shows Session ending; at the selected end it shows Session expired. Exact boundary timers and visibility/focus checks update both Find and Saved views, even when background timers were suspended. Choose a later end or Duration to resume. Fixed custom-time searches and independent room/building calendars retain their existing behavior. Malformed dates, DST choices and windows over four hours still receive normal input validation.

## Custom controls

Selectors use React Aria listboxes, and dates use its monthly calendar with Toronto-based today highlighting. Popups are portaled, themed, keyboard navigable, touch friendly, and dismiss with Escape while restoring focus. Native page/calendar scrolling and sticky room labels are retained; reduced motion and forced colors are supported.

Start/end time popups have a 1–12 hour selector, twelve five-minute minute choices, AM/PM, a preview, and text entry (`2:30 PM`, `14:30`, `1430`). Typed off-grid times are rejected, never rounded. Existing bookmarked times remain unchanged until explicitly replaced. Starting a new custom search initializes at the nearest five-minute instant; **Free now always sends the exact current instant**. Missing spring DST times are disabled/rejected, and repeated fall times still require an explicit occurrence.

End shortcuts add elapsed time and carry the Toronto date/offset across midnight/DST. For a live start with seconds or off-grid minutes, shortcuts suggest the next five-minute endpoint and use `~` to mark the approximate duration. The API still enforces 5–240 elapsed minutes and all coverage rules.

`custom-controls.spec.ts` captures opened select, date, and time popups in both themes on desktop and mobile. Screenshots use disabled animations to capture the settled popup; exit animations are finished without advancing the controlled search clock. Automated accessibility checks do not replace manual assistive-technology testing.

The separate private operator build is `npm run build:operator`. Build both applications before Playwright: it starts the student preview on 4173 and private UI preview on 4174, with synthetic intercepted operator responses. The real authenticated operator service serves only `dist-operator` on loopback 8765; see `../OPERATOR.md`. The normal student build remains separate.

## Intervella identity and UI audit

The student and private operator builds share the interval mark at `/assets/intervella.svg`, under the existing static asset mount. Display names, metadata, and the frontend package are branded Intervella; `utscvacant.appearance`, `utscvacant.favourites`, and `utscvacant.showEvents` are deliberately unchanged.

Search still requires **Find rooms**. On desktop its existing sticky column scrolls within the viewport; on phones it stays in document flow. Calendar dates apply immediately; **Refresh schedule** explicitly rechecks the selected day. Hiding scheduled annotations preserves row heights and all scheduled/unknown coverage periods. Bookmark icons retain Save/Remove accessible labels, pressed state, and 44px targets. Building links preserve search parameters and selected Toronto dates.

See [the audit and PR #16 plan](../docs/design/intervella-ui-audit.md). `brand-audit.spec.ts` and `operator.spec.ts` exercise 360/390/430/768/1024/1440px in both themes with synthetic responses and screenshots in `test-results/`. Existing CI uploads these alongside its other browser artifacts.
