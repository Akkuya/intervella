# Automatic manifests and private inventory review

This feature branches from merged main `74e65c9` (including rebrand PR #15). It changes the private import experience, not student availability behavior or the PostgreSQL schema.

## Implementation decisions

- `backend/app/operator/manifests.py` runs the unchanged strict daily/weekly parsers. It resolves yearless weekly captions only against the reviewed target dates, detects adjacent weeks, rejects malformed/mixed/duplicate sources and reports description-free observations/differences. Literal label parts may become draft suggestions; ambiguous identifiers stay blank. Missing capture times remain blank.
- `backend/app/operator/profiles.py` stores private approved mapping versions under the existing ignored operator storage. Atomic replacement, OS file locks and expected-version checks protect approval. Initial approval requires independently entered expected counts, a reason and acknowledgment. No SQL migration or private development database write is needed.
- The existing operator app owns protected profile/analyze/review routes. A reviewed generated manifest must match the approved profile, source hash, file periods and target. Actual capture timestamps and target/year require distinct confirmation. Profile locking spans generated comparison, staging and publication; source or profile edits cannot silently reuse a stale reviewed hash.
- `load_directory` remains the sole normalization path. Its optional in-memory manifest argument validates drafts before saving. Optional daily `snapshots[].file` preserves safe original filenames while absent fields retain the legacy dated convention. No parser, coverage, source-ID or atomic publication rule is relaxed.
- `ManifestBuilder` and `InventoryEditor` replace manual-first entry with upload, analysis, grouped/searchable structured review, approved profiles, differences, exact source metadata and an optional raw JSON/export section. Existing comparison/stage/confirmation UI and API calls remain in control of publication. Hidden-tab drafts persist during a session; logout/expiry clears private state.
- The existing custom time picker gains a 30-minute metadata mode for expected timetable windows; its student default stays five minutes, and Free now remains exact. No frontend availability algorithm or new dependency was added.

## Review and regression findings

Independent review identified and verified corrections for a cross-process profile approval/publication race, stale profile versions on reanalysis, and legacy v1 daily JSON without `source_format`. The race regression was run with the lock temporarily removed: a superseding approval succeeded and the test failed; restoring the lock made it pass. Browser regressions cover the other two recovery paths without discarding selected files/capture values. Final independent review reported no remaining actionable findings.

Synthetic tests cover format detection, missing/adjacent weeks, Sunday/year rollover, source IDs versus canonical DB identities, unknown/unmatched/duplicate rooms, capacity/window changes, independently approved profile counts, OS-lock conflicts, private profile durability/expiry separation, real PostgreSQL staging/publication, source/profile invalidation, authentication/CSRF, raw JSON compatibility, session clearing and missing-file recovery. Existing strict parser, cancellation, coverage, anomaly, rollback and concurrent-publisher tests remain intact.

## Reviewed screenshots

All retained PNGs are unedited browser captures with synthetic intercepted responses and sanitized fixture uploads. No real timetable, profile or credential appears. Reviewed for layout, legible state/confirmation cues, narrow-screen overflow and visible custom metadata controls:

| Capture | What it shows |
| --- | --- |
| [Desktop/light generated review](evidence/generated-review-desktop-light.png) | Upload-first flow, detected format, source metadata, grouped mappings and optional JSON |
| [Phone/dark generated review](evidence/generated-review-mobile-dark.png) | Responsive stacking, date/capture review and compact folded inventory |
| [Independent bootstrap](evidence/bootstrap-independent-inventory.png) | Canonical correction, independently entered counts, explicit approval and disabled validation before approval |
| [Desktop/light comparison](evidence/comparison-desktop-light.png) | Aggregate candidate differences and separate staging |
| [Phone/dark comparison](evidence/comparison-mobile-dark.png) | Mobile warning and review presentation |
| [Desktop/light confirmation](evidence/confirmation-desktop-light.png) | Candidate ID, baseline, warnings and explicit publication |
| [Phone/dark confirmation](evidence/confirmation-mobile-dark.png) | Bounded dialog with scrolling and retained confirmation boundary |
| [Opened coverage picker](evidence/expected-window-picker-mobile.png) | Reused custom control with only 00/30 metadata minute choices |

The full browser suite captures six widths (360/390/430/768/1024/1440), both themes and desktop/touch emulation using existing CI artifacts. No physical-device, Safari/Firefox or manual screen-reader certification is claimed.

## Verification

Run `.\check.ps1 -Fast` and `.\check.ps1` from a configured checkout. Integration tests create/drop only randomly named disposable test databases using the safe maintenance connection. Synthetic browser publication calls are intercepted; they do not touch the private database. No private source snapshots, seed, migrations or campus publication were run by this task.

Measured local results: **319 backend tests, 30 frontend unit tests and 178 browser cases passed**; the clean Fast workflow passed. Current-head full-workflow and GitHub CI status are recorded in the pull request description. Known limits: the separate private operator and student bundles trigger Vite's non-failing 500kB advisory; dependency deprecation warnings are retained. Source permissions, physical access, unresolved DST intervals and independently expected inventory cannot be inferred automatically. Follow [OPERATOR.md](../../OPERATOR.md) for capture/profile review, rejection recovery and a synthetic example.
