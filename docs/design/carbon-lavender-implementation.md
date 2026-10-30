# Carbon Lavender implementation

Implementation branch: `codex/carbon-lavender-overhaul`, based on merged PR #18. This implements the audit direction rather than proposing another redesign. Final execution totals and CI links are recorded in the review PR.

## Completed behavior

- Centralized light/dark surfaces, text, borders and accent, with compatibility aliases for existing components. Neutral building chips, semantic availability badges, disciplined typography, comfortable controls and restrained existing reduced-motion-aware transitions.
- Collapsible search summary replaces the tall sticky sidebar. Expanded filters stay in document flow; the compact summary remains reachable on desktop. The summary distinguishes duration from actual end/date, including overnight searches.
- Valid discrete filters commit automatically; room text waits 300 ms. URL edits use replacement history, while room/building navigation retains push history. Identical normalized filters do not create a new query. Existing React Query keys and AbortSignals preserve cancellation and response isolation.
- Incomplete/invalid drafts suppress earlier availability claims and pause requests. Navigation clears draft-pending state. Stable URL signatures prevent moving Now defaults from overwriting edits across midnight. Exact Now seconds, restored off-grid times, five-minute picker choices, Toronto DST choices, expiration and 5–240-minute validation retain their existing owners.
- Compact bookmarks remain separate semantic controls; storage keys are unchanged. Cards prioritize room identity and known timing, with neutral building labels and contextual building navigation. Nonzero collection counts retain per-room state badges. Repeated horizon caveats are consolidated below the collection.
- Building headings include code/full name and shortcuts for saved buildings. The existing batch API remains unchanged. Room labels narrow on phones; one labelled Now marker replaces repeated row labels. Unknown hatching, cancellation dashes, overlap lanes, stable annotation heights and schedule-list alternatives remain.
- Interval dialogs group event status, room, elapsed duration and Toronto endpoints. Existing native dialog focus/Escape handling and API-authorized label rules remain intact.
- Coverage errors explain the published-window limitation without claiming opening hours or physical access. Offline, stale, unknown, empty and actual failure remain separate states.
- Operator surfaces, navigation, progress, uploads, mapping review, history and publication confirmation share the product tokens. The existing guided manifest/profile workflow, acknowledgments and explicit publication are preserved. A shared self-hosted appearance bootstrap runs before rendering under the existing operator CSP.

## Verification

```powershell
.\check.ps1 -Fast
.\check.ps1
```

Browser regressions cover six widths (360, 390, 430, 768, 1024, 1440), light/dark and desktop/touch projects, automatic query updates, text debounce, focus preservation, invalid drafts, midnight, DST, response races, URL restoration, saved state, one Now label, dialog focus restoration, 200% zoom, reduced motion, forced colors and axe checks of rendered states. The existing full backend suite exercises disposable PostgreSQL databases, not the private development database.

Review found and corrected a moving-clock draft-reset race and obsolete submission assumptions in old tests. One local Chromium asset-load failure was traced to `ERR_NO_BUFFER_SPACE`; final local/CI results are reported separately, without treating infrastructure retries as application proof.

Final local results: both root workflows pass. Backend: 319 tests (two existing dependency deprecation warnings); frontend unit tests: 30; Playwright: 216 passed with no failures or flaky results. Lint, formatting, types, both builds, workflow regressions and dependency audit pass; audit reports zero vulnerabilities.

## Representative synthetic evidence

All images are unedited browser captures from intercepted synthetic fixtures. No university HTML, private profile, capture or credential is included.

| View | Evidence |
| --- | --- |
| Search/results | [Desktop light](carbon-lavender/search-desktop-light.png), [mobile dark](carbon-lavender/search-mobile-dark.png) |
| Expanded filters | [Desktop light](carbon-lavender/filters-desktop-light.png), [mobile dark](carbon-lavender/filters-mobile-dark.png) |
| Room/building | [Room desktop light](carbon-lavender/room-desktop-light.png), [building mobile dark](carbon-lavender/building-mobile-dark.png) |
| Saved rooms | [Mobile](carbon-lavender/saved-mobile.png) |
| Empty/unknown/stale | [Empty light](carbon-lavender/empty-desktop-light.png), [unknown dark](carbon-lavender/unknown-mobile-dark.png), [stale dark](carbon-lavender/stale-mobile-dark.png) |
| Event dialog | [Desktop light](carbon-lavender/event-desktop-light.png), [mobile dark](carbon-lavender/event-mobile-dark.png) |
| Private overview | [Desktop light](carbon-lavender/operator-desktop-light.png), [mobile dark](carbon-lavender/operator-mobile-dark.png) |
| Manifest generator/review | [Desktop light](carbon-lavender/manifest-desktop-light.png), [mobile dark](carbon-lavender/manifest-mobile-dark.png) |
| Publication | [Mobile dark](carbon-lavender/publication-mobile-dark.png) |

Manual visual review checks scan order, surface distinction, clipping/overflow, popup placement and retained non-color status cues. Automated accessibility checks do not certify manual screen-reader or physical-device conformance.

## Performance and boundaries

No dependency or font download was added. Previous minified JavaScript: student 567.34 kB (gzip 174.54), operator 530.50 kB (gzip 163.20). Final student JavaScript is 569.58 kB (gzip 175.16), an increase of 2.24 kB (gzip 0.62); operator JavaScript is unchanged at 530.50 kB (gzip 163.20). The shared cacheable appearance asset is 417 bytes uncompressed. The existing 500 kB bundle advisories remain a follow-up.

Backend availability, API contracts, authentication, parsing, ingestion/publication and course-label authorization are unchanged. No private database migration/reset/seed/import/publication or live retrieval was performed. No deployment or automatic merge. Physical phones, manual NVDA/VoiceOver and Safari/Firefox remain unverified.
