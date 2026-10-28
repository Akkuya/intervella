# PostgreSQL Foundation Implementation Plan

> Execute inline with the executing-plans skill. The user approved this design on October 28, 2026.

**Goal:** Add a reviewable PostgreSQL foundation without connecting live ingestion or availability.

**Architecture:** Seven SQLModel entities in the private `utscvacant` schema. Alembic owns DDL and database guards. Synchronous Psycopg 3 connections read credentials only from environment variables.

**Tech stack:** Existing Python 3.13+, uv, SQLModel, PostgreSQL, Psycopg 3, Alembic, pytest.

**Spec:** Technical Requirements Document v1.0, October 14, 2026, pages 3-6, 9, 11-14. The supplied PDF remains in the original checkout at `docs/utscVacant_Technical_Requirements_Document.pdf` (untracked).

## Constraints and approved design

- Preserve the HTML parser and all existing worktree edits.
- Replace unused prototype Building/Room/Meeting models with buildings, stable rooms, ingestion runs, datasets, singleton dataset state, room coverage, and materialized meeting occurrences.
- Use bigint identities, UUIDs, JSONB, timestamptz, positive nullable capacity, nonempty labels, unique room/source keys, checked statuses, restrictive foreign keys, and the `(dataset_id, room_id, starts_at)` index.
- Dataset state starts with one row (`id = 1`, null pointer). Published payloads are immutable; only published datasets may be active.
- Coverage is explicit: complete, partial, unknown, or absent. Never derive coverage from meeting counts.
- No availability algorithm, endpoints, frontend, auth, scraping, production source assumptions, or persisted credentials.

## Review focus

- Missing configuration must fail without printing a URL or falling back to SQLite.
- Published occurrence/coverage writes must fail, including moving rows between datasets and concurrent publication.
- Empty meetings with missing coverage must remain distinguishable from explicit complete coverage.
- Migration downgrade destroys this foundation's schema; use only on disposable databases or after backup.
- Test cleanup must affect only the dedicated test database created by the suite.

## Tasks and commits

### 1. Configuration

Files: `backend/app/db.py`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/tests/test_db.py`.

- [x] Write tests for required environment URLs, PostgreSQL/Psycopg validation, redacted failures, pool limits, and session lifecycle; observe failures.
- [x] Implement `database_url(variable: str = "DATABASE_URL") -> URL`, `create_db_engine(variable: str = "DATABASE_URL") -> Engine`, and `get_session()` without import-time connections. No credential fallback between roles.
- [x] Add Alembic/Psycopg dependencies, lock and sync; run configuration and parser tests; commit.

### 2. Schema and migrations

Files: `backend/app/models.py`, `backend/alembic.ini`, `backend/migrations/`, `backend/tests/test_postgres.py`.

- [x] Write real PostgreSQL tests for constraints, singleton initialization, dataset isolation, published payload guards, and migration roundtrip; observe failures.
- [x] Implement seven models and explicit migration DDL. Use `MIGRATION_DATABASE_URL`; never call metadata.create_all in application startup.
- [x] Run PostgreSQL tests and `alembic check`; commit.

### 3. Seed and delivery

Files: `backend/app/seed.py`, `backend/tests/test_postgres.py`, `backend/README.md`, `README.md`, `backend/.env.example`.

- [x] Write seed tests for deterministic data, repeatability, missing coverage, cancellations, failed runs, and safe rejection of nonempty unrelated databases; observe failures.
- [x] Implement `seed_synthetic(engine: Engine) -> None`, CLI `python -m app.seed --synthetic`, with fixed IDs and timestamps and an empty-database requirement. Use `INGESTION_DATABASE_URL`.
- [x] Document exact setup/verification commands, privilege/TLS requirements, rollback limits, and deferred publication validation.
- [x] Run full backend suite, Ruff, migration consistency, and review diff; commit. Leave branch isolated, no merge or push.

## Execution notes

- Baseline at `848218d`: five parser tests pass using installed Python outside the sandbox.
- Original checkout has uncommitted user edits; they are excluded from this branch.
- Worktree at `.worktrees/postgresql-foundation`; directory is already ignored.
- Full source normalization/validation and production publication command are deferred. Database guards enforce structural publication prerequisites, not source completeness.
- Task 1 complete: `f9d4c76`, configuration/parser tests 12 passed; Ruff passed.
- Task 2 complete: `f98b7b8`, full backend suite 55 passed on PostgreSQL 17; migration/model consistency and roundtrip passed.
- Task 3 complete: `41827b0`, seed tests observed missing-module failure, then four passed. Final full suite: 60 passed on PostgreSQL 17. Ruff passed for the entire backend; changed-module formatting and mypy with explicit namespace roots passed.
- Ruling: completed runs use `running`, `succeeded`, and `failed`; input hashes use lowercase SHA-256. These specify checked sets/formats left open by the TRD. Future adapters must use these contracts.
- Ruling: private application schema is fixed at `utscvacant`; campus timezone is fixed at `America/Toronto`. Multi-campus configuration is outside this project.
- Ruling: use a local Git exclude instead of editing the user's dirty `.gitignore`; the isolated worktree is now ignored without adding user edits to commits.
- CLI smoke checks passed against a separate disposable development database: `alembic upgrade head`, `alembic current` (`0001`), `alembic check` (no drift), and synthetic seed twice. Tests create and drop their own random databases.
- Final review: independent read-only review of `848218d..41827b0` found no actionable findings. Reviewer checked migration locks, singleton/pointer guards, seed safety, cleanup scope, configuration, and documentation; it did not independently rerun tests.
- Review boundary: production validation/publication ordering, controlled retention, SQLite conversion, availability, Supabase browser roles, and verified TLS remain deferred and are documented in `backend/README.md`. These require future implementation or deployment evidence; this branch does not claim them.
- Preservation checks: parser SHA-256 matches original checkout. No branch changes to parser tests, availability service, or frontend. Original uncommitted edits remain outside this branch.
