# Intervella branding and UI audit plan

**Goal:** Complete the public Intervella identity, correct verified small UX defects, and leave an actionable PR #16 design specification.

**Scope:** Existing React/TypeScript, CSS tokens, React Aria controls, Playwright synthetic API fixtures, documentation, and visible API/check titles. No new dependency or architecture change. No private database operations, parsing changes, imports, source authorization changes, or deployment.

## Tasks

- [x] Classify legacy names across tracked files. Rename display copy and package identity; preserve schemas, migrations, roles, environment variables, seed hashes, storage keys, process coordination, historical plans and actual local checkout paths. Record the classification in the audit.
- [x] Add regression checks for branding/metadata, compact favourites, contextual building navigation, reachable desktop search submission, stable calendar rows, centered keyboard-dismissable dialogs, and reactive date navigation with an accurately named refresh action. Run the checks against the old UI to establish failures.
- [x] Apply the smallest corrections using existing components and semantic theme tokens. Use a simple interval favicon/wordmark, no redesign or font dependency. Retain all coverage warnings and explicit search submission until PR #16.
- [x] Inspect student search/results, room/building calendars, saved rooms, selectors, and operator login/overview/import/history/errors using sanitized fixtures. Exercise 360/390/430/768/1024/1440px in light and dark themes. Record measured behavior and distinguish verified evidence from proposals.
- [x] Write docs/design/intervella-ui-audit.md: assessment, severity/status inventory including every Part 2A concern, three complete visual directions, recommended tokens/components/responsive/accessibility patterns, and grouped PR #16 tasks with acceptance tests.
- [x] Run .\check.ps1 -Fast and .\check.ps1. The full workflow may create/drop only random test databases via the existing maintenance connection, never modify the private development database. Inspect representative synthetic screenshots, review the diff, and push one focused PR to main. Do not merge.

## Review focus

Saved appearance/favourites and URLs must retain their current keys/formats. Building navigation must preserve search filters and use building codes rather than database/source IDs. Hidden event details must not remove schedule conflict/coverage periods. Compact buttons retain their accessible names and pressed state. Narrow layouts/popovers/dialogs must remain within the viewport; scrolling must not trap keyboard focus. No campus hours are invented and no unavailable coverage is promoted to availability.

Delivered as [PR #15](https://github.com/Akkuya/intervella/pull/15), targeting main; GitHub assigned the number. Local full gate: 286 backend, 30 unit, 164 browser cases passed. Final additional operator evidence gate: 28 passed. Remote CI is checked separately before completion; no automatic merge.
