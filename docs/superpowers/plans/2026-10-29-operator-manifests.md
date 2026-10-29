# Automatic operator manifests implementation plan

**Goal:** Upload authorized daily/weekly HTML, review an automatically populated manifest and reusable private inventory, then validate/stage/publish through the existing audited pipeline.

**Base:** main 74e65c9; rebrand PR #15 is merged. Feature branch: codex/operator-manifest-generation. No student redesign or private PostgreSQL operations.

**Architecture:** Strict existing parsers generate description-free observations. Explicit target dates resolve yearless weekly captions. An operator-only generator combines observations with exact approved mappings; unknown identities and actual capture times remain review obligations. Versioned approved profiles are private JSON files under operator storage, with atomic replacement, process-safe file locking and expected-version checks. No database migration. Existing load_directory/compare/import/publish remain the only ingestion path.

**Compatibility:** Optional daily snapshots[].file defaults to the existing dated filename. load_directory gains an optional in-memory manifest parameter for validation before saving a generated draft. Strict grid, source IDs versus database IDs, room windows, coverage, source freshness, baseline and immutable publication rules stay unchanged.

## Tasks

- [x] Add failing generation/profile tests: format detection from HTML; seven dates/adjacent weeks/Sunday/year rollover; malformed/mixed/duplicate sources; per-room windows; exact approved mapping reuse; unknown/missing/capacity/hours changes; independently acknowledged bootstrap; version conflicts and no invented capture times or IDs.
- [x] Implement description-free analysis, profile validation/version storage, and protected analyze/profile/review-manifest routes. Validate generated manifests with the existing loader before atomic save; invalidate review on source edits. Test auth/CSRF, limits, cleanup, missing timestamps and changed profiles/sources.
- [x] Extend daily filename compatibility and write PostgreSQL integration tests for generated weekly/daily stage/publication, stable canonical room IDs, rejected/partial inputs, last-good preservation, and baseline races. Never connect to the private development DB.
- [x] Replace manual-first import UI with a dedicated upload-first ImportWizard, structured inventory/profile/coverage editor and source metadata. Keep the existing overview/history and publication safety. Provide advanced inspect/edit/download JSON. Preserve drafts while moving operator tabs; clear private state on session expiration.
- [x] Add synthetic Playwright tests for bootstrap/reuse, daily/weekly uploads, editing, errors, invalidation, staged confirmation, keyboard, desktop/mobile and both themes; inspect captured complete-flow screenshots.
- [ ] Update OPERATOR.md with guided workflow, profile privacy/backup, capture confirmation, boundaries, rejection recovery and synthetic example. Run both check.ps1 modes, independent review, final checks and CI; push one focused PR against main without merging.

## Review focus

Observed rows alone never approve inventory. Initial bootstrap requires independently entered expected room/building counts and explicit review reason/acknowledgment. Capture timestamps are never sourced from upload/file/system time. Different room windows stay distinct; incomplete HTML does not become available. Source/profile edits invalidate old previews; candidate inputs remain locked after staging. File names and hashes are bounded/private and never become routes to arbitrary paths. No raw event descriptions are returned. Profiles never change published inventory by themselves.
