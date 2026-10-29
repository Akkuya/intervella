# Intervella private data operations

Start the private operator dashboard separately from the student application:

```powershell
# Once per checkout:
uv sync --project backend --locked
npm.cmd --prefix frontend ci
# Configure .env.local for the existing student database (see README.md).
# Configure the ignored .env.operator as described below, then:
.\operator.ps1
```

Open **http://127.0.0.1:8765** and enter the operator secret. The launcher builds the separate `frontend/dist-operator` application and starts only the loopback operator service. Ctrl+C stops its process tree; it does not stop PostgreSQL or alter the database. Existing `.\dev.ps1`, `.\check.ps1`, and `.\check.ps1 -Fast` retain their roles. Full checks now build both applications and test both; Fast explicitly skips PostgreSQL/browser tests.

## Private configuration and database roles

Create `.env.operator` locally, outside version control:

```dotenv
OPERATOR_SECRET=YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
INGESTION_DATABASE_URL=postgresql+psycopg://DEDICATED_OPERATOR_ROLE:PRIVATE_PASSWORD@127.0.0.1:55433/EXISTING_DATABASE
```

Generate a secret with `uv run --project backend python -c "import secrets; print(secrets.token_urlsafe(32))"`. Enter it only in this private configuration and the dashboard login. Do not use a Vite variable, put it in a URL, or save it in browser storage. Login uses an HttpOnly, SameSite=Strict session cookie and a per-session CSRF token held in memory. Sessions last eight hours; login attempts are limited. Logout revokes the session.

Use a database role distinct from the public API role. The launcher rejects equal usernames and passes privileged configuration only to its operator worker; public dev workers clear ingestion/migration/operator credentials. The application never creates a database or changes role grants. A database administrator must provision/review appropriate privileges manually against the existing database. Suggested scope (adapt role/database names; these are **not** automatically executed):

```sql
GRANT CONNECT ON DATABASE EXISTING_DATABASE TO OPERATOR_ROLE;
GRANT USAGE ON SCHEMA utscvacant TO OPERATOR_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA utscvacant TO OPERATOR_ROLE;
GRANT INSERT, UPDATE ON utscvacant.buildings, utscvacant.rooms,
    utscvacant.ingestion_runs, utscvacant.datasets TO OPERATOR_ROLE;
GRANT INSERT ON utscvacant.room_coverage, utscvacant.meeting_occurrences TO OPERATOR_ROLE;
GRANT UPDATE ON utscvacant.dataset_state TO OPERATOR_ROLE;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA utscvacant TO OPERATOR_ROLE;
```

The public API role should remain read-only, without ingestion/publication privileges or browser database access. Do not give the operator role table ownership, superuser, TRUNCATE, schema modification, or trigger-disabling privileges. Existing migration guards remain authoritative. Actual role provisioning and deployment permission audits require administrator review; tests use isolated fixture databases, not production grants.

The supported service is deliberately loopback-only on port 8765. Do not reverse-proxy it into the public student origin. Every operator API call requires a session; writes additionally require the exact loopback Origin and CSRF token. Trusted-host checks, no CORS allowance, no-store responses, CSP, and framing protection are enabled. The student FastAPI app has no operator routes, and the normal frontend build does not contain the operator entry page. Remote access needs a separately reviewed HTTPS/authentication deployment; do not forward this HTTP port.

## Guided import

1. Inspect Overview for the active identifier, actual source age, publication/import times, room/building/booking counts, daily provenance, unknown/missing coverage, and parser format.
2. Choose Weekly or Daily and the seven-day target start date. Weekly windows crossing Sunday require both adjacent enclosing-week exports; Daily requires seven exports.
3. Load the **approved private manifest JSON** (existing daily v1 or weekly v2) to supply exact building/room mappings, capacities and expected windows. You can edit it in the dashboard. Missing source IDs are never invented. See `backend/README.md` for the manifest schema. The GUI reuses inventory/windows, explicitly maps file dates, and never substitutes upload time for capture time.
4. Select or drop each authorized local HTML export. Enter its true capture timestamp with a UTC offset. Review and acknowledge the complete inventory, metadata and any findings, using a structured reason such as `reviewed-november-inventory`.
5. Validate & compare: strict parsing and aggregate comparisons perform **no database writes**. Inspect added/missing rooms, capacity changes, interval counts, unknown coverage, per-building/day booking changes, source captures, and critical errors versus reviewable warnings. A parser failure cannot be overridden by an anomaly reason.
6. Stage the reviewed candidate. Staging creates audited candidate records and leaves the active pointer unchanged. Inputs are locked against modification once staged; corrections require discarding uploaded inputs and starting a new batch.
7. Review publication. The dialog displays the candidate, target dates, refreshed baseline/comparison, and warnings. Confirming calls the existing atomic publisher with a baseline guard under the publication lock. If another publisher changes the active dataset, refresh the comparison and confirm again. The dashboard re-fetches active health before showing success. A lost response is not evidence that publication failed; refresh health before retrying.
8. Inspect audited Import history. Failures show sanitized codes; reports never contain HTML or booking descriptions. Previous datasets and historical room identities remain retained.

Publication is a deliberate action. Upload, validation and staging do not publish. Authorization to retrieve a source does not establish permission to republish campus data. The service performs no intranet fetching, UTORid/MFA/cookie handling, or scheduled refreshes.

## Upload storage and cleanup

Uploads are copies stored in ignored `backend/data/operator/ops-<random-id>` directories, never in the static document root. HTML is at most 10 MB per file, manifests at most 1 MB, up to eight files per batch and five outstanding batch directories. Unsafe filenames, NUL bytes and oversize requests are rejected; structural/inventory checks run before staging. Batch operations are serialized, and stage checks the preview hash. Use **Discard uploads** to delete a batch immediately; this retains audited database candidates/datasets.

Batch directories expire one hour after directory creation/modification and are cleaned on subsequent requests, including the first request after a service restart. Sessions and batch handles are in memory; after a restart, upload again. A staged dataset remains in PostgreSQL and can still be inspected/published through the audited CLI. A stopped service does not run a background cleaner. Only this service's `ops-<32 hex>` directories are eligible for cleanup; source originals outside the upload store are untouched. Run under a private OS account/workspace with appropriate filesystem permissions. Do not place original snapshots in this managed upload directory.

## Verification and stacked PRs

```powershell
.\check.ps1 -Fast
.\check.ps1
# Individual backend gate (TEST_DATABASE_URL must be the safe local /postgres maintenance URL):
uv run --directory backend ruff check .
uv run --directory backend ruff format --check .
uv run --directory backend mypy .
uv run --directory backend pytest --require-postgres
# Frontend:
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run build:operator
npm.cmd --prefix frontend run test:e2e
```

PostgreSQL tests create/drop only random `utscvacant_test_*` databases. Browser fixtures/screenshots are synthetic; they do not load private source exports. Screenshots cover overview, wizard, comparison and publication confirmation in both themes on desktop/mobile. CI retains browser artifacts seven days. Physical devices and manual screen-reader behavior are not certified by automated checks.

PR 1: weekly ingestion, targeting main. PR 2: private operations, targeting `feat/weekly-timetable-ingestion` while PR 1 remains unmerged. Merge PR 1 to main only after review; then rebase/retarget PR 2 onto main and re-run its diff/CI checks before merging it. Do not merge only into an intermediate branch and assume the dashboard is on main. Neither PR is automatically merged.
