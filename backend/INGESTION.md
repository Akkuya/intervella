# Seven-day local timetable ingestion

This command imports **locally supplied, authorized HTML exports**. It never fetches the intranet, opens a browser, logs in, reads cookies, or handles UTORid/MFA. A successful authenticated request proves neither automation permission nor public republication permission.

Use a private local database for real snapshots until the relevant authorization is verified. `publish` means atomically selecting a database dataset; it is not permission to expose it publicly. Ingestion does not deploy anything. Keep the frontend's unverified/demo notice. Do not point a public API at private imported data.

The current adapter supports the existing `contentwrapper` / `labtime` / `tableform` / `smallth` / `rfilter` / `event` structure, with a 30-minute grid. Strict mode deliberately rejects unrecognized markup rather than guessing that a room is free. Calibrate any additional source variants using authorized, sanitized examples before widening acceptance.

## 1. Prepare the local database

Use the existing [PostgreSQL setup](README.md#postgresql-foundation). No real snapshot is supplied or committed in this milestone. PostgreSQL 17 is tested; coverage unions require PostgreSQL 14 or later.

```powershell
Set-Location C:/Dev/utscVacant/backend
uv sync --locked

# Disposable loopback-only development database; use your actual local database name.
# This example contains no password. Keep real credentials in your secret store/environment.
$env:INGESTION_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev'
$env:MIGRATION_DATABASE_URL = $env:INGESTION_DATABASE_URL
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
```

For a fresh import database, create it with your local PostgreSQL administrator first. Alembic creates tables, not databases. Do not recreate or drop an existing database. The original fixed synthetic seed remains available and unchanged; a clean private database is simpler for real exports than mixing synthetic and real inventories. Importing against a seeded database may correctly flag inventory/count changes for review.

Use a distinct ingestion writer role in deployment. It needs the existing schema/table/sequence privileges plus access to the protected dataset state. The API should retain its read-only role. A transaction-scoped advisory lock works with pooled connections; do not substitute a session-level lock on an arbitrary pool connection.

## 2. Supply seven snapshots and an explicit manifest

Put input under ignored `backend/data/`, or outside the repository. `backend/data/` is already excluded from Git. Do not force-add exports, generated parsed JSON, cookies, tokens, or event descriptions.

```powershell
$snapshotRoot = Join-Path $PWD 'data/local-snapshots/week'
New-Item -ItemType Directory -Path $snapshotRoot -Force | Out-Null
```

Place exactly seven files named `YYYY-MM-DD.html` there, for seven consecutive calendar dates. The embedded `labtime` must match each filename. No extra `.html` files are accepted. Each file is limited to 10 MiB and must be UTF-8; a UTF-8 BOM is accepted. Symlink inputs are rejected. Record when each original export was actually captured, with an offset or `Z`. File modification times are never freshness evidence.

Add `manifest.json` in the same directory. The example below is **synthetic**. Replace the dates, capture times, expected grid bounds and complete inventory with your verified authorized scope. Do not derive an unquestioned expected inventory from a potentially truncated first page. The reported 10 tables / 67 headers are useful investigation evidence, not a hardcoded production inventory.

```json
{
  "version": 1,
  "start_date": "2026-10-14",
  "window": { "start": "08:00", "end": "22:00" },
  "snapshots": [
    { "date": "2026-10-14", "fetched_at": "2026-10-14T11:00:00Z" },
    { "date": "2026-10-15", "fetched_at": "2026-10-14T11:01:00Z" },
    { "date": "2026-10-16", "fetched_at": "2026-10-14T11:02:00Z" },
    { "date": "2026-10-17", "fetched_at": "2026-10-14T11:03:00Z" },
    { "date": "2026-10-18", "fetched_at": "2026-10-14T11:04:00Z" },
    { "date": "2026-10-19", "fetched_at": "2026-10-14T11:05:00Z" },
    { "date": "2026-10-20", "fetched_at": "2026-10-14T11:06:00Z" }
  ],
  "buildings": [
    {
      "source_name": "Synthetic A",
      "code": "SYN-A",
      "name": "Synthetic Building A",
      "rooms": [
        { "source_name": "SYN-A-101", "room_number": "101", "source_id": 9001 },
        { "source_name": "SYN-A-102", "room_number": "102", "source_id": 9002 }
      ]
    }
  ]
}
```

`source_name` matches the caption/header exactly after parser whitespace trimming. `source_id` is the numeric `rfilter` locator, never a database ID. Stable database room identity is `(building code, room number)`. Aliases are explicit; fuzzy matching is forbidden. Every page must contain exactly the declared buildings and rooms, with matching source IDs. Capacity must be positive and consistent across the seven exports. Changed identities or room counts require an intentional manifest update and review against the previous dataset.

The manifest window is the actual expected grid interval shared by the tables. Only that interval is covered; an 08:00–22:00 timetable never implies overnight coverage. End `24:00` is supported. An end earlier than or equal to the start denotes next-day rollover, with a maximum 24-hour grid. Rowspans may cross midnight when the following rows are explicitly present. Missing rows, shifted intervals, extra columns, truncated spans, duplicate headers, and unrecognized cells fail validation. An explicitly blocked cell is unknown, even if blank. Only a validated blank cell or recognized event establishes complete coverage. Explicit `event cancelled` cells are cancellation occurrences; text alone never implies cancellation.

Times use `America/Toronto` calendar dates and convert to UTC. A gap or repeated local time without enough offset information is rejected, including ambiguous empty-grid slots. This adapter does not invent offsets for DST-transition-hour pages. Ordinary daytime tables across DST changes work correctly.

## 3. Dry-run, stage, inspect, publish

```powershell
# No database connection or writes. Checks local structure, identity and unknown-rate anomalies.
uv run python -m app.ingest import $snapshotRoot --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Review the dry-run report before importing' }

# Repeats validation and compares the candidate to the active dataset; does not switch the pointer.
$stageJson = uv run python -m app.ingest import $snapshotRoot
if ($LASTEXITCODE -ne 0) { $stageJson; throw 'Import failed; last published dataset is unchanged' }
$stage = $stageJson | ConvertFrom-Json
$stage

uv run python -m app.ingest status

# Review the staged run, input hash, counts, timestamps and dataset UUID first.
uv run python -m app.ingest publish $stage.dataset_id
if ($LASTEXITCODE -ne 0) { throw 'Publication failed; inspect status and re-import if needed' }

uv run python -m app.ingest status
```

Exit status `0` means success (including an unchanged input); `2` means validation, review or operational failure. Dry-run explicitly reports `baseline_checked: false`: it does not certify that publication will pass database-baseline checks. Import checks that baseline; publication checks it again under the lock. `status` lists the latest ten audit runs, their hashes/counts/findings, and the active dataset. Status omits room metadata and source descriptions.

Booking count drops **above 20%**, inventory changes, and an unknown room rate **above 2%** require operator review. Booking rates compare scheduled occurrences per declared day; cancellations do not count as bookings. The unknown rate counts rooms with any unknown window. Thresholds are conservative anomaly signals, not proof of a bad export. All structural/scope/date errors remain fatal.

If an anomaly is legitimate and has been reviewed, re-run the import with a short non-sensitive review identifier:

```powershell
uv run python -m app.ingest import $snapshotRoot --review-reason reviewed-holiday-closure
```

Use only lowercase letters, digits, `_` and `-`, beginning with a letter, up to 64 characters. Keep any detailed rationale in private operational records; do not put names, credentials or tokens in a reason. The identifier and findings remain in the audit. An override never creates coverage, bypasses malformed input, or permits an older snapshot to replace a newer one. If the baseline changes between staging and publication, prior baseline-specific approval does not silently transfer; inspect the new findings and re-import or explicitly review the publish attempt.

Common error codes:

| Code | Action |
| --- | --- |
| `invalid_local_input` | Check manifest schema, encoding and strict HTML structure; the CLI does not echo raw input. |
| `unexpected_files` / `unexpected_dates` / `unexpected_page_date` | Supply exactly the seven expected dated snapshots. |
| `missing_buildings` / `missing_rooms` / `unexpected_room` | Reconcile the export with the explicit authorized inventory. |
| `incomplete_timetable_window` | Restore missing rows or correct the intentionally expected scope; do not claim missing hours. |
| `unresolved_local_time` | Obtain an unambiguous authorized export; do not guess an offset. |
| `review_required` | Inspect the reported anomalies; correct the source or record an explicit review identifier. |
| `candidate_changed` | Staged records changed after validation; investigate and re-import. |
| `older_source` | A newer/equal-age dataset or daily capture already exists; obtain a newer complete export. |
| `candidate_not_validated` | The run failed validation/publication; re-import after resolving the cause. |
| `audit_unavailable` | Audit storage failed (for example database outage); no successful publication is claimed. Check database health. |

## Atomicity, retention and migration safety

Runs contain the combined SHA-256 (exact manifest/file bytes plus parser version), per-date hashes and capture times, counts, candidate digest and sanitized error code. Event descriptions, instructor names, raw HTML, source URLs and credentials are not copied into database payloads or reports. Freshness uses the **oldest** capture in the seven-file bundle. Re-importing identical successful input reuses its dataset without refreshing source time or duplicating occurrences.

Staging is one transaction after a separately committed audit run. New stable identities are registered inactive; existing active metadata is not changed during staging. Candidate occurrences/coverage are invisible to the published availability queries. Inactive stable room metadata may still be returned by the existing room-by-ID endpoint, so staging real inputs also belongs in a private database.

Publication takes a transaction advisory lock, locks the singleton pointer and candidate, checks the stored payload/identity/source-metadata digest and current anomalies, rejects source-age regressions (including overlapping per-date capture regressions), updates room metadata, sets `published_at`, and switches the pointer in one commit. Existing PostgreSQL payload guards block edits racing publication. Failed stages roll back their records; failed publications roll back all publication writes and retain a failed audit run. Failure logging also locks/rechecks the candidate: if another publisher has already succeeded, a separate failed attempt links to that successful parent rather than overwriting it. Re-import after a failed run rather than editing its evidence. Abrupt process termination can leave a `running` audit row; it does not expose an uncommitted candidate or change the pointer.

All previous datasets are retained; this milestone does not prune data. A data rollback is a separate, deliberate operator transaction selecting a previously published UUID under the same advisory and pointer locks. Normal `publish` deliberately refuses age regression and does not serve as a rollback shortcut. Database backups and a restore exercise remain deployment requirements.

Migration `0002` expands the coverage primary key to `(dataset_id, room_id, starts_at)` without rewriting coverage or removing existing records. Coverage queries union adjacent complete half-open windows with PostgreSQL multiranges; gaps and conflicting partial/unknown windows exclude availability. The existing single coverage object in room-schedule responses conservatively summarizes just the requested day; partial bounds may enclose gaps and never imply complete coverage.

Deploy the migration before the updated backend, then restart API workers together. Old application readers assume one coverage row per room: **do not publish multi-window datasets while old workers remain**. Existing single-window data continues to work. The downgrade refuses to collapse multiple windows, preserving all records and the migration version. Prefer forward repair once multi-window datasets exist; do not delete windows to force a rollback.

## Verification

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy .
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55433/postgres'
uv run pytest --require-postgres -q
```

The existing backend CI already runs these checks with PostgreSQL 17, including all new tests. Tests create/drop only their random `utscvacant_test_*` databases. Fixtures are generated synthetic HTML, including a seven-day, ten-building, 67-room case. Tests cover strict malformed grids, rowspans, midnight, DST, scope, partial/unknown coverage, API responses, hashes, repeats/concurrency, candidate tampering, last-good preservation, publication failure rollback and lossless migration behavior. No authenticated source, live retrieval, public deployment or source permission is verified by these tests.

After a local publication, run FastAPI with the same private database and follow the existing frontend guide. Query within the imported table's actual coverage and the API's existing rolling search window. The API contracts, 36-hour stale threshold and browser data notice are unchanged.
