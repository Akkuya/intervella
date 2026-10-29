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

## Upload-first guided import

Ordinary imports no longer require writing JSON. Use only exports you are authorized to handle; parsing does not grant public redistribution permission.

1. **Overview:** check the active identifier, actual source age, daily coverage and recent findings. An import timestamp is not a source capture timestamp.
2. **Upload:** open Import timetable, review the seven-day start date/year and select or drop original HTML. Leave Source format on **Detect from HTML** unless correcting it. Strict parsers identify structure, not filenames. Sunday-start weekly targets need one Sunday–Saturday export; targets crossing Sunday need both enclosing weeks. Daily imports need seven dates. Mixed formats, duplicate periods and malformed grids are rejected.
3. **Analyze & generate draft:** review detected periods, source hashes, observed row sizes, each room's actual window, missing files and inventory changes. Add/replace files and analyze again if an enclosing week/date is missing. This writes no database records and never displays event descriptions.
4. **Review metadata:** explicitly confirm target dates/year and file mappings. Enter the actual capture timestamp with its UTC offset for each original export, then confirm it. File modification time, upload time, page date and the system clock are never capture evidence.
5. **Review inventory:** exact approved mappings are reused. Otherwise inspect searchable building groups and expandable rooms; correct canonical codes/numbers, source labels, actual source IDs (optional/null for weekly), capacities and expected windows. Use Add expected building/room, move rooms or remove mappings only after independently reviewing inventory changes. Enter independently expected room/building counts, a short review code and the independent-review acknowledgment before **Approve inventory profile**. Parsed rows alone do not prove full inventory. Missing rooms remain expected until explicitly reviewed. Saving a profile does not publish.
6. **Validate & compare:** the generated manifest must match the approved profile, actual files and target periods. The existing validator checks seven dates, per-room bounds, identities, capacities, DST and captures. Review changes against the active dataset, freshness, booking drops and unknown coverage. This writes no database records. Parser failures cannot be acknowledged away. Source, mapping or capture edits clear the old comparison; validate again.
7. **Stage:** acknowledge the comparison/warnings and choose **Stage reviewed candidate**. Audited candidate records are created; the active pointer remains unchanged. Staged inputs lock. Profile approval cannot race comparison/staging/publication: the service holds the profile's OS lock and checks its version. Corrections after staging require discarding uploads and starting a new batch; audited datasets remain retained.
8. **Publish:** choose **Review publication**, inspect the exact candidate and refreshed baseline/comparison, acknowledge confirmation and choose **Confirm publish dataset**. The existing publisher changes the active pointer atomically with a baseline guard. If the baseline changes, refresh/review before confirming again. A lost response does not prove failure: refresh Overview before retrying. Upload, generation, profile approval, validation and staging never publish automatically.

Returning between operator tabs preserves the draft. Logout/authentication expiry clears private browser state, including candidate references. After service restart, inspect Overview/history and upload again; in-memory batch/session handles do not survive.

### Automatic versus reviewed information

| Automatic from strict source/profile evidence | Administrator must supply or confirm |
| --- | --- |
| Daily/weekly structural detection; dates and enclosing weeks | Reviewed target dates/year; a yearless caption cannot prove its year |
| Room labels, capacities, actual source locators when present, row increments and observed windows | Canonical identities for ambiguous labels; source locators are not database room IDs |
| Exact approved aliases, stable canonical room numbers and expected windows | Independently expected inventory/windows and unfamiliar or destructive changes |
| Source hashes, inventory differences and active-dataset comparison | Actual capture timestamp/offset per original export, review acknowledgments, staging and publication |

Literal prefixes/numbers from labels are mapping suggestions requiring independent approval. Ambiguous labels leave identifiers blank. No building identifier, missing source ID, unobserved coverage or operating hour is invented. Approved windows remain expectations on later imports, including shorter-room windows. Missing meetings never establish coverage or availability. Review codes begin with a lowercase letter and contain at most 64 letters/digits/hyphens/underscores.

### Reusable private profiles

Approved profiles live in ignored **`backend/data/operator/inventory/`**, separate from expiring `ops-*` uploads. They contain mappings, expected capacities/windows, compatible formats, independently entered counts, version and actual review metadata. They contain no HTML, booking descriptions, credentials or capture timestamps. Saving one never changes PostgreSQL inventory. No database migration is required.

Open **Approved inventory profile** to inspect/export or edit the current profile. **Load reviewed profile or manifest** imports draft configuration, including legacy daily v1 manifests without `source_format`. Imported JSON is not proof of approval; review and save it explicitly. `version-N.json` files retain private review history; `current.json` changes atomically. OS locks and expected-version checks prevent conflicting approvals. The API reports the latest 20 review metadata entries; older version files remain available for private audit/backup. Keep this directory under private OS-account permissions and your private backup policy; never commit or publicly share it.

Reanalysis refreshes the current profile without losing selected files or entered capture values. If another session approves a newer version, review that version before validation. A changed profile after staging blocks the superseded review; discard uploads and prepare a new candidate. The last published dataset stays active.

### Rejection recovery and manual JSON fallback

- **Malformed/mixed source:** replace/remove the bad file or correct format, then analyze. Structural failures cannot be overridden.
- **Missing date/adjacent week:** supply the missing original export; never manufacture an empty schedule.
- **Missing expected room/building, changed capacity/hours or ambiguous rename:** obtain a complete export or explicitly review/edit the profile. Preserve the same canonical building code/room number for a stable room. Never substitute its source ID for its database ID.
- **Capture/DST failure:** supply actual aware timestamps. The pipeline rejects future captures and unresolved timetable gaps/folds rather than guessing.
- **Profile changed/busy:** let the other review/publication finish and analyze again; selected files remain available.
- **Source hash/review changed:** analyze and confirm metadata again. Old comparisons cannot be staged; staged inputs cannot be edited.
- **Expired session/restart/lost response:** sign in, inspect Overview/history and reupload if needed. Do not assume the active pointer stayed unchanged just because a response was lost.

Expand **Advanced: inspect, edit or download manifest JSON** when needed. Apply raw edits explicitly to the structured draft. Date/format changes require fresh analysis; mapping/window changes require profile approval. Downloaded manifests/profiles remain private. Daily `snapshots[].file` is optional and defaults to `YYYY-MM-DD.html`; generated drafts use safe uploaded names. An unsuitable filename receives a displayed `source-N.html` transport alias, never a fabricated room identity. Every path uses the same strict loader, staging and publisher; there is no parallel importer.

### Entirely synthetic example

This creates fixed sanitized test exports only, with no database connection or seed change:

```powershell
Push-Location backend
@"
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_weekly_ingestion import write_weekly
write_weekly(Path('data/operator-demo'), start='2026-10-28', weeks=('2026-10-25', '2026-11-01'))
print('Synthetic exports written under backend/data/operator-demo')
"@ | uv run --no-env-file python -
Pop-Location
```

In a separately configured disposable demo environment, choose **2026-10-28**, upload the two generated `.html` files and analyze. The fixture has one building, two rooms and an expected 08:00–10:00 window. Its `2026-10-25T11:00:00Z` capture value is synthetic, not evidence about real data. Review/approve those expectations, confirm metadata, validate and stage; publish explicitly only in the disposable environment if desired. Do not run this walkthrough against the private published development database. Verification for this feature used disposable test databases and intercepted synthetic browser requests only.

## Upload storage and cleanup

Uploads are copies stored in ignored `backend/data/operator/ops-<random-id>` directories, never in the static document root. HTML is at most 10 MB per file, manifests at most 1 MB, up to eight files per batch and five outstanding batch directories. Unsafe filenames, NUL bytes and oversize requests are rejected; structural/inventory checks run before staging. Batch operations are serialized, and stage checks the preview hash. Use **Discard uploads** to delete a batch immediately; this retains audited database candidates/datasets.

Batch directories expire one hour after directory creation/modification and are cleaned on subsequent requests, including the first request after a service restart. Sessions and batch handles are in memory; after a restart, upload again. A staged dataset remains in PostgreSQL and can still be inspected/published through the audited CLI. A stopped service does not run a background cleaner. Only this service's `ops-<32 hex>` directories are eligible for cleanup; source originals outside the upload store are untouched. Run under a private OS account/workspace with appropriate filesystem permissions. Do not place original snapshots in this managed upload directory.

## Verification

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

The weekly pipeline, operator dashboard and rebrand are merged into main. This feature builds on that architecture and targets main. Verification never migrates, seeds, imports into or publishes the private development database.

Implementation decisions, reviewed synthetic screenshots and exact results: [automatic manifest notes](docs/operator/automatic-manifests.md).
