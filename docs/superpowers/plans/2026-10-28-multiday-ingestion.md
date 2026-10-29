# Multi-day local schedule ingestion

Base: latest merged main (`a5da9c3`). Branch: `feat/multiday-ingestion`.

## Design and scope

Use the existing parser, SQLModel records, PostgreSQL protection triggers and REST contracts. Local snapshots only: no intranet requests, login, cookies, raw HTML persistence, personal descriptions or public-source claims. Preserve the immutable synthetic seed and frontend notice.

- Require seven consecutive `YYYY-MM-DD.html` snapshots and a small operator-authored manifest with explicit building/room identities, expected room counts and capture timestamps. Do not infer scope from whatever the first page happens to contain. Source room IDs remain source locators, never database primary keys. Exact aliases only, no fuzzy matching.
- Keep legacy parser output compatible; ingestion uses a strict mode validating every 30-minute row, room column, rowspan, date and cell. Only structurally validated empty cells prove coverage. Unknown/blocked cells remain unknown; short but valid timetables cover only their actual interval. Reject unsupported malformed/ambiguous structures.
- Normalize local calendar boundaries in America/Toronto with round-trip DST validation; ambiguous/nonexistent times fail rather than guessing. Materialize UTC occurrences, never descriptions.
- Expand coverage primary key with `starts_at`; preserve all existing rows. Availability uses PostgreSQL multirange union of complete windows. Gaps never disappear. Day-schedule coverage remains conservative within the existing response schema. Downgrade refuses multiple windows rather than deleting data.
- Persist sanitized input hashes, counts, validation findings, scope and candidate digest in run audit metadata. Dry-run performs parsing/validation without database writes. Import writes one candidate transaction and never touches the active pointer. Failed attempts retain a failed audit run.
- Publish locks the singleton pointer and candidate, revalidates staged content and current-baseline anomalies, then marks the dataset published and changes the pointer in one transaction. Reject older/equal-age competing snapshots. Retain all prior datasets. Repeated identical input is a no-op; do not refresh provenance timestamps on re-import.
- Fail closed for missing dates/buildings/rooms, duplicate identities/meetings and invalid intervals. Flag booking drops above 20 percent and unknown room rate above 2 percent; explicit reviewed overrides require a safe reason identifier retained in audit metadata. Structural errors cannot be overridden.

## Implementation commits

1. Coverage migration and query readers, PostgreSQL regression tests for adjacent windows/gaps/day summaries and preservation/rollback.
2. Strict parser and typed local snapshot normalization with synthetic fixtures, DST/midnight/malformed/identity tests.
3. CLI dry-run/import/status/publish, audit hashes, candidate validation, atomic concurrency protection and PostgreSQL/API integration tests.
4. PowerShell guide, CI verification, independent review, regression fixes, push and PR against main; no merge.

## Verification / stop condition

Unchanged full PostgreSQL baseline first. Each nontrivial change has a failing regression before implementation. Run Ruff lint/format, mypy and complete `pytest --require-postgres`, including concurrent publishers and failed publication rollback. Verify API contracts and frontend source unchanged, original seed unchanged, no raw authenticated input committed. Independent review required; resolve correctness/security findings. Hosted CI must pass on final commit. Public deployment and source authorization are separate future work.

## Execution evidence

- Baseline: 134 tests passed on PostgreSQL 17, two existing Starlette/httpx deprecation warnings. Latest merged main was fetched; local main and its untracked PDFs were not changed. Managed worktree created on `feat/multiday-ingestion`.
- `6d431c0`: coverage migration/readers; multiple-row inserts first failed on the old key. Adjacent/gap tests and lossless upgrade/downgrade-refusal checks pass. Existing API/database/seed checks passed (96 focused tests).
- `6c2e358`: strict parser and local normalization; strict/normalization tests first failed before implementation. Original five parser tests preserved unchanged. Unknown cells, scope mismatch, impossible dates, DST gaps/folds and midnight are covered.
- `517bb62`: audited CLI, candidate digest, separate staging and locked atomic publication. Pipeline/CLI regressions first failed before implementation. Booking-drop findings survive failed staging; changed baselines are revalidated. Unknown windows cannot be masked by overlapping complete windows; unknown empty-cell markup and ambiguous source locators are rejected.
- Final pre-review suite: **190 passed, zero skipped**, two existing dependency deprecation warnings (35.55s). Ruff lint/format and mypy pass. Synthetic representative fixture: 10 building tables, 67 room headers, seven dates, 469 coverage windows and 469 occurrences; API limit and next booking checked. No real intranet payload was read or fetched for this milestone.
- Ruling: retain legacy parser behavior through an opt-in strict mode, require a seven-day operator manifest with explicit aliases and grid bounds, and fail closed on unknown structural variants. This preserves callers while preventing the old event-only extraction from certifying coverage. Real-source variants require authorized sanitized evidence before adapter expansion.
- Ruling: stable identity metadata follows the existing global Room/Building model. New staged rooms are inactive; schedule payload stays unpublished. Existing room-by-ID can expose inactive metadata, so real staging must use a private database until public access is authorized. Frontend notice and API contracts remain unchanged.
- PowerShell guide includes explicit local authorization boundary, manifest, dry-run/import/status/publish, review codes, migration order, retention, failure recovery and test commands. Independent review, hosted CI and PR publication remain pending.
- PR #4 opened against main; initial hosted push/PR CI passed. Independent review found delayed failure-audit corruption after concurrent successful publication, and unchecked blank/time-header spans. Both reproduced with deterministic failing regressions, then fixed. Failure auditing now serializes/rechecks candidate state and creates a separate failed attempt when the parent is already published. Header span validation covers every column. A self-review regression also exposed source-timestamp tampering outside the payload digest; candidate metadata is now included. Focused review-fix suite: 38 passed. Final local suite: **194 passed, zero skipped**, two existing dependency warnings (30.34s); Ruff lint/format and mypy passed. Hosted verification pending on this fix commit; no second review loop.
