# Multiweek timetable imports

Implementation status: code changed and reviewed by reading only. No tests,
builds, linters, formatters, type checks, servers, dependency installation,
database migrations, ingestion, publication or cloud deployment were run.

## Operator workflow

1. Open the private local operator dashboard and choose **Import timetable**.
2. Drop daily and/or weekly HTML files together. The queue accepts up to 84
   files (12 weeks), 10 MB per file and 100 MB total. A new drop replaces the
   private queue. Original filenames are recorded alongside safe storage names
   and SHA-256 hashes; they never establish dates or capture times.
3. Daily source dates come from the strict HTML parser. The existing weekly
   caption omits the year: enter the independently verified year of its Sunday
   start, with per-file overrides for files spanning different years. A source
   containing an explicit `timetable-week-start` meta tag can provide an ISO
   Sunday date. Conflicting evidence is rejected. December–January weeks use
   the year of their Sunday. No machine-clock or filename year is inferred.
4. Resolve metadata and detect again when necessary. Valid independent weeks
   remain reviewable even if another file fails. Exact duplicate bytes are
   identified and ignored with a notice; competing daily/weekly exports or
   different exports for the same period block that period. Daily weeks need
   all seven dates. Missing days never become empty calendars.
5. Supply every original export's actual offset-aware capture timestamp and an
   evidence reference, such as a recorded retrieval or capture log. If capture
   evidence is unavailable, leave the week unresolved. The application cannot
   independently attest to an operator's evidence reference. Upload, filesystem,
   filename and current time are not capture evidence.
6. Review the proposed coverage table. Only strict, continuous, completely
   observed grids with matching inventory can be bulk approved. Unknown cells,
   inconsistent inventories/windows, gaps, malformed sources, and unresolved
   local times remain blocked. Shorter approved windows leave omitted hours
   unknown. They never mark those hours free.
7. Choose the weeks, enter a review reason code, acknowledge the displayed
   evidence and click **Approve eligible windows & validate selected weeks**.
   Review the resulting comparisons and acknowledge them before **Stage reviewed
   weeks**. Staging is independent per week and can be retried after partial
   progress. It does not publish anything.
8. Optionally, BEFORE staging, use **Separately approve these windows for future
   imports** on a week. This saves a new private inventory profile with source
   hashes, analysis hash, reason, timestamp and before/after changes. It refreshes
   analyses while retaining capture entries. Ordinary approval applies only to
   the current week and never silently rewrites the baseline.
9. Select staged weeks and click **Review atomic publication**. Review the exact
   candidate IDs, dates, comparisons, warnings and publication baseline, then
   acknowledge and explicitly confirm. The entire selection commits together
   or rolls back. Other active periods and all historical datasets remain.

The existing inventory editor and single seven-day importer remain available
below the new queue. New generated manifests also require capture evidence in
that editor. Inventory corrections retain their existing independent approval.

## Database rollout (not performed)

Coordinate a maintenance window and a database backup with authorized access.
Do not publish actual UTSC intranet-derived data to a public cloud until its
authorization is verified. These code changes grant no republication rights.

1. Configure the existing migration-role environment (`MIGRATION_DATABASE_URL`)
   for the intended authorized database. From `backend`, apply migration 0004
   using the existing environment: `.\.venv\Scripts\python.exe -m alembic upgrade head`.
   This is a future operator step; it was not executed during implementation.
2. Apply `deploy/grants.sql` using the existing migration-role procedure. The
   reader gains SELECT on `active_periods` and `dataset_sources`; the ingestor
   gains DELETE only on the active-period registry, in addition to its existing
   rights. Private ingestion records remain inaccessible to the reader. Existing
   roles must be present; the migration does not create accounts or extensions.
3. Release matching API/operator code together. Rebuild the private operator
   frontend using the normal `build:operator` process only when builds and its
   included type check are permitted. Restart the local operator then. No
   deployment or server was started for this work.
4. Revalidate and restage candidates created before this change. Parser/hash
   version is now `local-grid-v3`; old published payloads remain immutable and
   readable. Existing v1 daily and v2 weekly manifest formats are retained.

Migration 0004 adds a nonoverlapping active-period registry, immutable per-date
capture projections, and source-date attribution on coverage. It backfills only
the previously active dataset into the registry, retaining all history. Old
payloads have no reconstructed source-date attribution; queries conservatively
retain their oldest recorded capture age rather than guess that attribution.
Failed migrations must roll back; do not ignore invalid legacy provenance.

Downgrade refuses multiple active periods or a retained period that disagrees
with the compatibility pointer. An administrator must first select the intended
single period and align the pointer in a reviewed transaction. No history needs
to be deleted. Forward repair is preferred.

## Publication and query behavior

- Each dataset still represents seven consecutive calendar dates. New queue
  groups use Sunday–Saturday; the legacy path retains arbitrary seven-day starts.
  Replacement must match an active period's exact dates. Partial overlaps are
  rejected, including a transition from a non-Sunday legacy range to overlapping
  Sunday weeks; an administrator must explicitly review that range transition.
- The singleton dataset pointer remains the publication concurrency token and
  latest-publication compatibility identifier. All active periods, rather than
  that pointer alone, own date-aware schedule selection. A stale publication
  baseline requires a new review. An already-active candidate is idempotent.
- Availability, room search/lookahead, room calendars and building calendars
  select data by Toronto dates. Cross-week requests union only actual complete
  coverage, clip payloads at active-period boundaries, honor scheduled conflicts,
  and preserve gaps/unknown periods. No free time is inferred outside source grids.
- Public metadata adds `dataset_ids`, `publication_id` and source-day freshness.
  The student UI uses the publication token to refresh cached results when any
  week is replaced, and matches freshness to the queried sources. Aggregate
  schedule status can still be stale because another retained week is stale.
- Per-source timestamps are compared as instants. An older capture cannot
  replace the same source date; different content at an equal capture time is
  also blocked. A different week's older capture does not block an independent
  week. Freshness remains 36 hours by default, unaffected by import/publication.
- Toronto day boundaries honor 23/25-hour DST days. Source wall times touching
  a gap or repeated hour remain unresolved when the HTML cannot disambiguate
  them. Offset-aware queries use real instants. Overnight payloads are clipped
  at the dataset boundary; coverage beyond it requires the adjacent active week.
- Room IDs and historical datasets are retained. Active room flags reflect the
  union of all active inventories. Conflicting capacities or building names
  across retained active periods block publication because inventory metadata
  is shared; this change does not invent versioned room metadata.

## Remaining validation and limits

All behavior, migrations, PostgreSQL range expressions/triggers/permissions,
concurrency, API responses, TypeScript compatibility, accessibility and visual
layout remain untested at runtime. Regression cases were added but not run.
The UI is not visually verified. Use synthetic data for the first authorized
validation, including both DST transitions and a replacement racing another
publication/profile approval.

The queue and sessions retain the existing process-local lifetime and one-hour
private upload cleanup. An operator restart requires uploading/reviewing again;
staged datasets and audit records remain in PostgreSQL. Publication is atomic;
uploading, analysis and staging across several weeks are intentionally separate
steps with independent progress. No dependencies or automatic publishing were added.

The existing availability/search limits (5–240 minutes and a start within 30
days) remain; date-based room and building calendars can read other active dates.

## Files changed

- `backend/app/ingest/local.py`
- `backend/app/ingest/pipeline.py`
- `backend/app/ingest/weekly_load.py`
- `backend/app/models.py`
- `backend/app/operator/app.py`
- `backend/app/operator/coverage.py`
- `backend/app/operator/discovery.py`
- `backend/app/operator/manifests.py`
- `backend/app/operator/profiles.py`
- `backend/app/operator/service.py`
- `backend/app/schemas.py`
- `backend/app/seed.py`
- `backend/app/services/availability.py`
- `backend/app/services/calendar.py`
- `backend/app/services/published.py`
- `backend/app/services/room_search.py`
- `backend/migrations/versions/0004_active_periods.py`
- `backend/tests/schedule_helpers.py`
- `backend/tests/test_availability.py`
- `backend/tests/test_calendar.py`
- `backend/tests/test_multiday_coverage.py`
- `backend/tests/test_multiweek_import.py`
- `backend/tests/test_operator.py`
- `backend/tests/test_operator_generation.py`
- `backend/tests/test_room_search.py`
- `deploy/grants.sql`
- `docs/operator/multiweek-imports.md`
- `docs/superpowers/plans/2026-10-30-multiweek-import.md`
- `frontend/src/App.tsx`
- `frontend/src/BuildingSchedules.tsx`
- `frontend/src/ManifestBuilder.tsx`
- `frontend/src/MultiweekImporter.tsx`
- `frontend/src/SavedRooms.tsx`
- `frontend/src/api.ts`
- `frontend/src/components.tsx`
- `frontend/src/operator-api.ts`
- `frontend/src/operator.tsx`
- `frontend/tests/e2e/operator.spec.ts`
- `frontend/tests/unit/api.test.ts`
