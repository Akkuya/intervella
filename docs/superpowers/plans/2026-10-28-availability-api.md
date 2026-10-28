# Milestone 2: Availability Engine and REST API

**Goal:** Serve validated, snapshot-consistent schedule availability through FastAPI.
**Authority:** PRD September 28, 2026; TRD October 14, 2026 (especially pages 5, 7-8, 10-13). The newer TRD wins.
**Base:** `origin/main` at `6f9b034`; PostgreSQL foundation merged through PR #1. Work in `feat/availability-api`, isolated under `.worktrees/availability-api`. Preserve original dirty checkout.
**Execution:** Inline using planning, lean-build, TDD, and final independent code-review skills. User explicitly authorized routine decisions, commits, push, and PR without further design approval.

## Design and scope

- Keep SQLModel schema, migration, HTML parser, and deterministic seed unchanged.
- Use synchronous SQLAlchemy expressions and SQLModel sessions. API sessions are read-only, repeatable-read transactions. Capture the published dataset once per request; all schedule, coverage, and freshness reads use it.
- Availability uses `[start,end)`: conflict iff scheduled start < requested end AND scheduled end > requested start. Require one complete coverage row containing the entire interval. Return next scheduled start >= requested end, ordered by building code, room number, room ID; fetch limit+1 for has_more.
- Explicitly count eligible active rooms lacking full complete coverage. Exclude them from results. A valid covered search with all rooms busy returns an empty list; no trustworthy room coverage returns 503. A query outside the published coverage envelope returns 422 `outside_dataset_coverage`. The envelope never certifies individual-room coverage or fills gaps.
- Require offset-aware ISO timestamps, normalize to UTC, enforce start between now-5 minutes and now+30 days, duration 5..240 (default 60), limit 1..100 (default 50), and recognized building codes.
- Campus schedule dates use local midnight to next local midnight in America/Toronto, converted separately to UTC (23/25-hour DST days). Explicit request offsets identify instants; naive timestamps are rejected.
- Fresh <=36 hours; stale >36 hours. Freshness is evaluated at request time and is independent of coverage. Stale covered data remains searchable with a warning.
- Readiness requires complete coverage for a usable five-minute window now. Status may report an existing but degraded dataset. Stable building/room metadata does not require an active schedule dataset.
- Seven public GET endpoints only. Structured Pydantic responses and safe errors with request IDs, no SQL/source/credential leakage, no-cache responses, exact CORS allowlist, configurable freshness/result cap and request timeout. No server cache, auth, recommendations, scraping, frontend, or schema redesign.
- Existing seed remains fixed on October 14. Integration tests control the clock instead of changing production time or mutating the seed.

## Tasks / commit boundaries

1. **Availability service** — `app/services/availability.py`, response/query schemas in `app/schemas.py`, service errors in `app/errors.py`, read-only dependency in `app/db.py`; tests in `tests/test_availability.py`, `tests/test_time.py`, and synthetic fixture helper. Write failing tests first; prove overlaps, adjacency, cancellation, coverage, next bookings, ordering, limits, stale threshold, and snapshot races.
2. **REST API** — `app/main.py`, `app/settings.py`, remaining service metadata functions and schemas; `tests/test_api.py`, configuration/unit checks. Exercise all seven routes, error schemas, offset/date validation, limits, DB outages, no dataset, CORS, timeout, redaction, liveness isolation, readiness, DST, and original seeded data with a controlled clock.
3. **CI and docs** — GitHub Actions PostgreSQL 17 service, locked uv dependencies, full pytest with mandatory PostgreSQL, Ruff formatting/lint, and mypy. Repair relevant baseline tooling failures. Document environment variables, local setup, actual API schemas, synthetic-seed demo tests, and deployment boundaries.
4. **Review and publish** — full checks, real HTTP smoke check, preservation checks, independent security/correctness review, fixes with regression tests, small commits, push feature branch and create PR against `main`. Observe CI and fix failures; no automatic merge.

## Review focus

- Missing/partial coverage, gaps between different room windows, and unpublished candidate data never become availability.
- Requests racing publication keep meetings, coverage, room metadata, and freshness in one PostgreSQL snapshot.
- Exact boundaries and DST use instants correctly, including 23/25-hour schedule days.
- Errors and logs never reflect query values, SQL, credentials, or source payloads; DB failures return 503.
- Test and CI databases remain isolated; no destructive operation touches user data.

## Evidence and decisions

- Initial repository and both PDFs inspected. No schema migration is needed.
- Foundation branch is already merged; PR target is `main`, per user instruction.
- Task 1 complete: `baa85fb`; 94 tests passed, including read-only MVCC transaction behavior and a publication race that also changes stable room metadata. Ruff and mypy passed.
- Task 2 complete: `e3606e6`; seven endpoints, exact-origin CORS, safe errors, request IDs, timeout, freshness and readiness. Configured-cap regression observed failing and fixed; omitted limit now respects a smaller server cap.
- Task 3 complete: pinned minimal-permission PostgreSQL 17 CI, default mypy package-root fix, actual uvicorn HTTP integration test, local setup and API documentation. No new dependency, schema migration, parser edit, or seed edit.
- Full local gate: `uv run pytest --require-postgres` -> 134 passed, 2 upstream TestClient deprecation warnings; `ruff check .`, `ruff format --check .` (29 files), and `mypy .` (28 files) passed. Workflow YAML and mandatory PostgreSQL step checked.
- Preservation: zero diff from `6f9b034` for parser, schema, seed, migrations, original parser/seed/PostgreSQL tests, and frontend. Existing user container and original dirty checkout remain untouched.
- Remaining: independent final review, branch push, PR creation, and hosted CI results.
