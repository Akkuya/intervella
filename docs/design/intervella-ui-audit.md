# Intervella UI/UX audit and PR #16 specification

Audit: October 29, 2026. Baseline: merged main `fe70d68` (PRs #1–#13). Scope: student React application and separate private operator build. Resolved items below describe PR #14; proposed designs and larger interactions belong to PR #16 and are **not implemented here**.

## A. Current design assessment

Intervella answers which classrooms have complete published coverage and no scheduled conflict for a chosen interval. It cannot promise occupancy, an unlocked door, or permission to republish campus data. That distinction must survive a redesign.

### What works

- `index.css` has semantic light/dark surfaces, text, borders, information, success, warning and danger colors. Dark mode is deliberately tuned, rather than a simple inversion.
- React Aria supplies portaled selects, monthly calendars and split time pickers with focus handling and keyboard behavior. Preserve those primitives, five-minute choices, typed validation, Toronto DST occurrence selection, next-day endpoints and exact Free now instants.
- URL searches, calendar back links, saved IDs, cancellation styling and explicit stale/unknown states are valuable product behavior. The frontend consumes authoritative API results rather than calculating availability from empty event lists.
- The calendar aligns rooms to one server-provided window and contains horizontal scrolling. Unknown periods have hatching/text; cancellations have dashed boundaries. The accessible list remains a useful alternative to the visual timeline.
- Private operations has a separate build/service, review/comparison, explicit staging and identifier-confirmed publication. Its safeguards are appropriate even if the presentation can become calmer.

The interface is functional with strong data honesty and accessible foundations, but form-heavy. On mobile the long form and source context precede results; cards repeat caveats and zero counts; building navigation and time labels are repetitive. Typography, radius and density vary across student cards, controls, calendars and operations. A cohesive later pass should improve scan order, not replace working infrastructure.

### Method and evidence boundaries

Read the implemented `App`, `SearchForm`, `Results`, `SavedRooms`, `RoomCard`, `FavouriteButton`, `BuildingSchedules`, `Calendar`, `Controls`, `ThemeControl`, operator UI/API and their styles/tests. Inspect error/coverage contracts rather than inventing client-side availability or operating hours.

Exercise 360, 390, 430, 768, 1024 and 1440 CSS-pixel widths, in light and dark themes, under desktop Chromium and Pixel touch emulation. Height is 900px; a separate 1024×650 regression checks the tall search panel. Screenshots/overflow checks cover search, opened date/time pickers, room and building calendars, operator overview, import wizard, comparison and confirmation. Existing suites cover saved state, loading/empty/offline, stale/unknown coverage, API errors, request races, midnight/DST, expired sessions and publication safeguards.

All browser APIs and uploads are synthetic intercepted fixtures. Mocked publish clicks never write a database. No private HTML, manifests, credentials or campus records are screenshot evidence. The private local PostgreSQL database is not opened, migrated, seeded or imported for this audit; integration tests create/drop only their existing randomly named test databases. Representative screenshots are manually inspected, but automated axe and device emulation do not certify manual screen-reader or physical-phone behavior.

## B. Issue inventory

Severity indicates user impact. Critical would mean unsafe availability, data loss or a broken privilege boundary; none is established in this audit. Preserved constraints below are explicitly distinct from discovered defects.

| ID | Component/page | Evidence / user impact | Severity | Resolution / status |
| --- | --- | --- | --- | --- |
| B01 | Student/operator headers, page/API titles | Old visible name and Vite favicon split the identity. | Medium | **Resolved #14:** Intervella wordmark/interval favicon, student/operator titles/descriptions, public OG metadata, frontend package and project-check heading. |
| B02 | README/original scope | Old RoomFinder description promises emptiness, implies unverified library/source facts and lists nonexistent fetch/recommendation files. | Medium | **Resolved #14:** factual intro/current tree and milestone status; discovery scope explicitly historical and subordinate to TRD. No permission inferred. |
| S01 | Search sidebar | Sticky top with no height bound leaves a ~1008px custom form outside a 650px laptop viewport, hiding Find rooms while results continue scrolling. | High | **Resolved #14:** viewport-bounded scrollable existing column, action/keyboard reachability regression. Mobile remains normal document flow. Revisit nested scrolling in #16. |
| S02 | Mobile search / SearchForm | Intro, source and long form precede results; the synthetic two-card page exceeds 3000px. Changes remain drafts until Find rooms. | High | **Deferred #16:** coordinated reactive filters plus compact summary/expandable filters. Do not remove submit before replacing its semantics. |
| S03 | Search/navigation | Committed filters/URLs survive navigation; unsubmitted drafts intentionally do not. | Medium | **Deferred #16:** define draft/committed state and replacement-history rules; preserve URL contract. |
| R01 | FavouriteButton | Large full-width Save/Remove action competes with room identity/navigation. | Medium | **Resolved #14:** shared 44px bookmark control, saved fill/pressed state, unchanged accessible action names, tooltip and storage limits. |
| R02 | Room cards/details | Building code is present without a contextual route to its calendar. | Medium | **Resolved #14:** understated building link in both contexts, retaining filters/date and independent actions. |
| R03 | Room card hierarchy | Building code scans weakly; room/state, capacity and repeated booking explanations compete. | Medium | **Partly resolved #14:** header wraps safely and building link improves context. **Deferred #16:** building badge/grouping, concise metadata, useful timing hierarchy. |
| R04 | Results/source receipt | Correct but verbose counts include zeros; horizon/coverage caveats repeat across cards and collection. | Low | **Deferred #16:** nonzero counts with accessible full summary, consolidated caveats; never call mixed results available. |
| C01 | CalendarDate, room/building | Date selection already updates the URL automatically; Show schedule implies another required submit. | Medium | **Resolved #14:** redundant form removed, explicit Refresh schedule retained for intentional revalidation. Phone arrows share a row around the date; Refresh sits below. |
| C02 | Calendar event toggle | Hiding annotations shrinks a one-lane row from 100px to 60px, shifting everything below; multi-lane rows also collapse. | Medium | **Resolved #14:** same lane-derived height in both states; occupied/unknown periods stay visible. Explicit density changes can be designed later. |
| C03 | Interval dialog | No explicit centering after CSS reset, no height bound for short screens. | Medium | **Resolved #14:** auto margins, viewport height bound/internal overflow, Escape/focus/centering tests. **Deferred #16:** richer grouping of room, timing and status. |
| C04 | BuildingSchedules | Flat selector, saved buildings elsewhere, weak chosen-building identity. | Medium | **Deferred #16:** code/name heading, sensible saved-first navigation, easier room transitions; retain one batch request. |
| C05 | Current-time marker | Every calendar row repeats Now; 67 rooms render 67 labels. | Medium | **Deferred #16:** one labelled time-axis marker with quieter continuation lines; avoid event/room-label collisions. |
| C06 | Long/mobile calendars | Horizontal region scrolling is intentional, but the 140px sticky label axis consumes much of a phone. | Medium | **Deferred #16:** slimmer label column and clearer date/window context, preserving timeline/list alternatives. |
| D01 | Overnight/outside-hours searches | 2:00 AM is selectable. API exposes dataset/coverage bounds, not verified opening or teaching hours. Coverage codes have helpful messages under a generic error heading. | Medium | **Deferred #16:** coverage-information state separate from actual API failure. Do not invent a teaching-hours threshold, infer coverage or block covered overnight results. |
| D02 | Time/search safety | Five-minute UI steps differ from 5–240 elapsed-minute limits; DST repeats, exact Now seconds and expiration are safety constraints. | High constraint | **Preserved #14:** no search/time/API changes; mandatory #16 acceptance cases below. |
| V01 | Typography/radius/spacing | Trebuchet display/Segoe body, direct operator heading sizing, radii 4–16px and uneven densities. | Medium | **Deferred #16:** small semantic token set/component variants using the current stack. |
| V02 | Saved-building border | Undefined `--border` drops the declared outline. | Low | **Resolved #14:** existing `--line` token. |
| V03 | Disabled cursor | Global wait cursor incorrectly suggests loading for reached save limits/invalid actions. | Low | **Resolved #14:** not-allowed cursor; busy status remains explicit. |
| V04 | Motion/feedback | Popups animate but general interactive color changes are abrupt. | Low | **Resolved #14:** 140ms color/border transitions, disabled by existing reduced-motion rules. Larger filter/saved choreography deferred; no layout animation. |
| V05 | Touch density | Main inputs/bookmarks are at least 44px, but calendar cells/appearance controls include ~38px targets. | Low | **Deferred #16:** evaluate 44px coarse-pointer targets without overflowing the month grid; keep accessible primitives. |
| V06 | Student bundle | Existing production bundle exceeds Vite's 500kB advisory (about 567kB minified after this PR). | Medium | **Deferred #16:** measure route/control splitting and font payload; no new dependency added here. |
| O01 | Operator wizard/overview | Dense metrics, tables and manifest editor are long on phone; review progress is visually weak. | Medium | **Deferred #16:** operation-specific density, progress/review summary, structured manual-manifest guidance. No automatic inventory generation. |
| O02 | Operator errors/history | Underscore-replaced codes are technical; candidate/baseline IDs need clearer grouping. | Medium | **Deferred #16:** known-code actionable copy with safe reference disclosure and exact confirmation IDs. Never show private raw server exceptions. |
| O03 | Operator theme startup | ThemeControl applies saved theme after mounting; student HTML also applies it earlier. Operator can flash light. | Low | **Deferred #16:** CSP-compatible early theme application; do not weaken CSP for cosmetic convenience. |
| O04 | Privilege/publication boundary | Separate build/service, auth, trusted Origin, CSRF and confirmed IDs already exist. | High constraint | **Preserved #14:** operator UI branding only; security/publication tests remain. |
| P01 | Public provenance | Fresh timestamp does not establish source authorization; no verified provenance flag exists in UI contract. | High constraint | **Preserved #14:** unverified/demo notice everywhere, no new public-data certification. |

### Part 2A mapping

- Search-button visibility: S01 fixed. Live filtering/request pacing/sticky compact controls/draft persistence: S02/S03 deferred together.
- Building differentiation/card hierarchy: R02 small link fixed, R03/R04 deferred. Compact saves: R01 fixed; no whole-card click handlers containing secondary actions.
- Building menu: C04 deferred. Redundant Show schedule: C01 fixed. Repetitive Now: C05 deferred. Room transitions preserve existing links plus R02.
- Event layout shifts: C02 fixed. Popup positioning/focus: C03 fixed; richer hierarchy deferred. Text/hatching/dashes already distinguish statuses without color alone.
- Outside hours versus coverage versus application failure: D01 deferred with explicit missing-data limits; D02/P01 safety retained. No campus access hours are asserted from a timetable.
- Motion: V04 restrained change fixed; coordinated filter/loading/saved feedback deferred. Reduced motion and stable layout remain mandatory.

## Legacy-name classification

Tracked repository search: case-insensitive `utsc[ ]?vacant|roomfinder`, including docs, config, tests, assets and source. Classification determines edits; no global rename.

| Occurrences | Classification / action |
| --- | --- |
| UI headers/wordmarks, HTML titles/descriptions, API title, check summary, frontend package metadata | Display identity: rename to Intervella; replace unused starter favicon/icons. |
| README RoomFinder intro/tree; frontend/backend/operator headings; old scope title | Public documentation: update current identity and inaccurate descriptions. Mark discovery scope historical. |
| `utscvacant` schema/table qualifiers, migration history, FK names, SQL tests | Persistent compatibility: retain verbatim; no schema migration. |
| Existing DB/container/volume/role names, example URLs, `utscvacant_test_*`, seed hash namespace | Operational/audit compatibility: retain. Database names are not product branding. |
| `utscvacant.appearance`, `.favourites`, `.showEvents`, matching bootstrap/tests/docs | Browser preference compatibility: retain, preventing loss of saved choices. Regression restores existing appearance/favourites. |
| `UtscVacant.DevProcesses`, startup event names, `UTSCVACANT_START_GATE`, temporary test prefixes | Internal process coordination/cleanup contracts: retain both producer and consumer. |
| Historical `docs/superpowers/plans/*`, actual `C:\Dev\utscVacant` and existing private path examples | Historical records/real checkout paths: retain, not presented as the app name. Do not rename user folders. |
| Tests asserting old display names are absent | Regression evidence: retain legacy strings intentionally. |

Future internal renames need a separate compatibility/rollback proposal only if they solve a real problem. Existing API paths, environment keys, roles, IDs and storage formats are deliberately unchanged. No domain ownership, hosting or university affiliation is implied.

## C. Three cohesive visual directions

Proposals for #16 only. No domain purchase, hosted assets or university endorsement assumed.

| Attribute | Campus cadence — recommended | Quiet ledger | Studio signal |
| --- | --- | --- | --- |
| Palette | Ink `#163244`, canvas `#F3F6F8`, white `#FFFFFF`, blue `#285AC7`, green `#176148`, restrained copper `#8A4C20` | Graphite `#243638`, mist `#F0F5F3`, white `#FFFFFF`, pine `#256052`, teal-gray `#52736A`, amber `#805800` | Indigo `#252F56`, pale lavender-gray `#F3F4FA`, white `#FFFFFF`, iris `#5455BE`, slate `#61708C`, rose `#914C66` |
| Typography | Source Sans 3 body/controls; Manrope display 600/700; tabular times without another font | IBM Plex Sans body, restrained IBM Plex Mono time labels | Public Sans body; DM Sans display 600/700, tabular figures |
| Backgrounds/surfaces | Cool quiet canvas, solid cards, semantic ribbons; no blur | Pale green-gray page, rule-separated sections, fewer isolated panels | Nearly neutral lavender canvas, solid panels with occasional indigo edge |
| Cards | 12px radius, strong room identity, state at right, compact code badge/timing | 8px radius, dense aligned list rows and clear disclosure | 14px radius, more open space around room title |
| Border/shadow | Single slate outline; shadows only for overlays | Mostly rules, no card shadow, clear menu elevation | Cool thin border, one soft overlay elevation |
| Density | Balanced student controls, compact operator tables | Highest scan efficiency for many rooms | More approachable for occasional use, less dense |
| Dark mode | Canvas `#111F2A`, panel `#192D3B`, text `#EAF1F5`, accent `#8AB4FF`; independently tuned statuses | Canvas `#152320`, panel `#20332D`, text `#E5F1EB`, accent `#91CDB7` | Canvas `#171D31`, panel `#242E47`, text `#EDF0FA`, accent `#B0ADFF` |
| Signature | Interval mark and precise timeline ticks; one labelled current-time cursor | Building-grouped schedule ledger with strong alignment | Small section markers and confident text hierarchy |
| Strength | Builds on existing tokens; calm schedule-specific identity, lower migration cost | Excellent density/operations fit | Friendly student identity and clear hierarchy |
| Weakness | Needs disciplined grouping to avoid a generic blue dashboard; fonts must justify cost | Can feel administrative for students | More spacing/dual fonts increase page length/cost; iris cannot imply state |

Choose **Campus cadence**. Its distinguishing feature is the visual grammar of an interval, not a decorative hero or animated background. Preserve #14's simple mark and functioning primitives; prioritize a stable search experience and scan order. These are proposed font roles, not a new dependency decision: if licensed self-hosted subsets cannot fit the performance budget, retain system fonts and apply the same scale/weights.

## D. Recommended design system

### Proposed tokens

Define semantic CSS properties in `index.css`, keeping temporary aliases while converting current components. No hardcoded semantic state colors inside components. The following is a #16 specification, not #14's implemented palette.

| Token | Light | Dark | Purpose |
| --- | --- | --- | --- |
| `--canvas` | `#F3F6F8` | `#111F2A` | Page |
| `--surface` | `#FFFFFF` | `#192D3B` | Panels |
| `--surface-muted` | `#E9EFF3` | `#253B4A` | Secondary blocks |
| `--text` | `#163244` | `#EAF1F5` | Main text |
| `--text-muted` | `#4D6573` | `#B3C5D0` | Secondary text |
| `--border` | `#C6D3DC` | `#455E6F` | Rules |
| `--control-border` | `#748C9D` | `#839DAC` | Input boundary |
| `--accent` | `#285AC7` | `#8AB4FF` | Actions/focus, never availability |
| `--on-accent` | `#FFFFFF` | `#111F2A` | Primary action label |
| `--success-bg/text` | `#E6F3EC` / `#176148` | `#183C32` / `#A6E4C3` | Confirmed covered gap |
| `--warning-bg/text` | `#FFF3D8` / `#704A00` | `#3F331B` / `#F3D18A` | Stale/unknown |
| `--danger` | `#9D302B` | `#FFB7AC` | Actual errors |

Validate rendered combinations for WCAG AA contrast, including selected, hover, disabled and chart states; this proposal is not contrast certification. Unknown remains text/pattern differentiated from scheduled time. Building differentiation uses code/name/grouping, not availability colors assigned by building.

### Type, spacing and component rules

- Display 36/42 desktop, 28/34 phone, weight 600; section 24/30 at 600; room title 22/28 at 700; body/control 16/24; supporting 14/20; utility/time axis 12/16 only where adjacent context remains readable. Tabular times, not monospaced body copy.
- Space scale 4, 8, 12, 16, 24, 32, 48px. Card padding 20–24 desktop / 16 phone; field groups 16; label gap 8. Stop individually choosing 19/23/25px gaps.
- Radius 8px controls, 12px panels, 16px dialogs; pill radius only for small chips. One-pixel borders. Focus ring 3px with 2px offset. Shadows for overlays only; no shadowed nested cards.
- Proposed fonts require licensed self-hosted subsets, system fallbacks and `font-display: swap`; no external font request on private operations. Keep system fonts if payload or license cost outweighs benefit.
- Reuse `Button`, `Badge`, `RoomCard`, `FavouriteButton`, `Select`, `DatePicker`, `TimePicker`, `FreshnessNote` and calendar. Extract only actual repeated structure; no replacement UI framework.
- Button variants: primary, secondary, quiet, 44px pressed bookmark. Loading needs explicit status, not disabled appearance alone. Critical publication labels name the action and exact candidate.
- State variants: loading, empty, coverage information, stale, offline, expired session, actual failure. Each explains the next action. Safe request references remain available without raw exceptions.
- Cards: code/name, room title, server status, known capacity, confirmed-until or next-known opening, next booking. Separate room/building links and save button. Do not make a parent click handler swallow secondary actions. Saved collections may contain scheduled, unknown and inactive rooms.

### Responsive layout

- At ≥1024px, compact grouped search beside results. Keep submission reachable until the reactive redesign fully replaces it; avoid an unbounded sticky form.
- At 768–1023px, grouped full-width controls above results rather than a squeezed 280px sidebar and single card column.
- At ≤767px, compact current-window summary and expandable filters. Reduce permanent intro height while keeping provenance accessible. If a summary sticks, reserve its space, account for safe areas/header and never cover focused controls.
- Page must not scroll horizontally. Only labelled timeline/table regions may scroll sideways. Keep room labels and date/window context visible. Slim the phone room axis.
- Building view: chosen code/name and saved state, one date/window group, one labelled time cursor, consistent room rows. Saved-first selection only if ordering/typeahead remain predictable.
- Operator: same underlying tokens/controls, clearly labelled Private operations, denser tables, wrapped identifiers and a review summary. Preserve separate build/service/privileges.

### Interaction and correctness contracts

Reactive search is one coordinated change to `SearchForm`, `App`, `search.ts`, `navigation.ts` and tests, not unrelated per-field effects:

1. Separate raw editable draft from validated committed query. Debounce text edits about 300ms; discrete selections may commit immediately only once the whole interval is valid. Never send incomplete input, spring gaps, unresolved DST repeats, expired Now/until windows or intervals outside 5–240 elapsed minutes.
2. Reuse React Query keys and AbortSignals. Cancel superseded requests, reject late overwrite and avoid duplicate unchanged normalized queries. Automatic updates do not steal focus.
3. Replace history for routine filter edits; retain push entries for explicit room/view navigation. Preserve existing parameter names, reload restoration, saved state and Back/Forward behavior. Remove Find rooms only after the replacement is tested; explicit Refresh stays distinct.
4. Old results must not appear to match newly edited filters. During refresh, label the previous search window or show a stable pending shell. Expired/offline states hide old availability claims, as today.
5. Announce a concise settled result summary politely, not a live region around the whole grid. Avoid repeated loading announcements on minute polls. Timetable gaps never promise physical access.
6. Use existing `outside_dataset_coverage` / `coverage_unavailable` codes and room states as coverage information, separate from network/server failure. A covered overnight interval can be valid. Teaching/opening-hour warnings need a verified source/contract first; do not invent 08:00–22:00 campus hours from the display window. Preserve meaningful results with a general access caveat.
7. Keep React Aria primitives, Escape/focus return and touch behavior. Event modal groups room, time and status clearly. Course labels remain generic unless the existing API explicitly authorizes `approved_public`.
8. Motion: 120–160ms color/opacity, overlays at most 180ms; no calendar height animation or card reflow during polling. Reduced motion removes movement; forced colors preserves selected/focus cues. Save feedback uses pressed state and a short announcement.

Accessibility target: WCAG 2.2 AA; semantic headings/landmarks, visible focus, comfortable 44px controls (and applicable minimum target criterion), non-color status cues, no trap, focus restored to trigger, timeline/list alternatives, 200% zoom and narrow reflow. Manual NVDA/VoiceOver and physical-phone checks are required before claiming conformance.

## E. PR #16 implementation plan

Reviewable groups, with unchanged backend availability, parser, ingestion/publication and course-label permission rules:

1. **Tokens/shared states.** Convert `index.css`, `App.css`, `controls.css`, `calendar.css`, `operator.css`. Standardize only repeated values. Apply type/spacing/radius and check actual contrast. Update shared `ui.tsx`, `components.tsx`, `theme.tsx` variants. Capture loading/empty/coverage/error/offline in both themes; verify forced colors/reduced motion. Establish asset/bundle budget before adding fonts.
2. **Reactive search/navigation.** Coordinate `SearchForm`/`App` with existing URL/time helpers. Add tests for pacing/request counts, invalid intermediates, latest-response wins, deduplication, Back/Forward, reload, retained draft and focus. Keep exact Now/expiration. Remove Find rooms only when automatic behavior replaces it fully; keep explicit Refresh.
3. **Results/saved items.** Refine `Results`, `RoomCard`, `FavouriteButton`, `SavedRooms`: stronger building hierarchy, concise metadata/nonzero counts. Preserve inactive/missing removal, persistence limits, mixed-state wording, coverage and independent card actions. Test cross-view saves, blocked storage, long identifiers and 67 cards without per-room request fanout.
4. **Building/room calendars.** Refine `BuildingSchedules`, `Calendar`, `CalendarDate`, `IntervalDialog`: building heading, one Now label, slimmer mobile axis, grouped details. Preserve stable rows, cancellations, overlap lanes, unknown hatching, list alternative, scrolling and retained date. Test viewport-edge events, Escape/focus, 23/25-hour DST dates, midnight/next-day labels. No inferred off-hours.
5. **Operator presentation.** Refine `operator.tsx`/`operator.css` with progress/review hierarchy, safe known-code messages and history. Consider safe early theme application. Preserve manual approved manifests, actual capture timestamps, CSRF/session boundaries, baseline checks, staged candidate and exact confirmation. Add expired/failed-preview/publish-conflict/unknown-source screenshots. No auto-publication or automatic manifest generation.
6. **Whole-product gate.** Run both root check modes and CI. Repeat six-width/theme matrix, retain selected synthetic screenshots, check zoom/coarse-pointer/reduced-motion/forced-colors/keyboard. Inspect real renders and complete assistive-technology/device checks. Review private inputs, preference-key churn, provenance and label authorization. Open #16; do not auto-merge.

### Mandatory acceptance cases

- Free now sends exact seconds; five-minute choices never silently round a restored time.
- Incomplete/spring-gap inputs send no request; fall repeats require occurrence; next-day end remains selectable.
- Valid filters issue one normalized request after pacing; obsolete responses never replace it; invalid draft does not retain outdated availability.
- Fixed end under five minutes/past shows ending/expired and stops polls in Find/Saved after visibility return/reconnect.
- Unknown/missing coverage never becomes available; mixed Include-next/Saved headings stay neutral; null next booking never means unlimited availability.
- 2:00 AM is selectable. Complete coverage, outside coverage, stale, actual failure and physical-access caveat stay distinct without invented teaching hours.
- Filters/date survive room/building navigation/reload/Back. Saving never triggers navigation.
- Event toggle does not shift rows. One time label remains discoverable, statuses retain text/patterns, modal fits edges and restores focus.
- Operator keeps review/confirmation, expired-auth recovery, privilege separation and conflict handling; all browser data stays synthetic.

## Verification and evidence

Use the existing workflows, from a configured feature checkout:

```powershell
.\check.ps1 -Fast
.\check.ps1
# Focused synthetic audit:
npm.cmd --prefix frontend run test:e2e -- brand-audit.spec.ts operator.spec.ts
```

The full gate validates the local maintenance target and strips development/ingestion/migration/operator secrets from test subprocesses. Only random test databases are created/dropped; no command migrates/seeds/imports the private development database.

Final local results and reviewed screenshot links follow. Full per-case screenshots are in the existing `frontend-browser-results` CI artifact (seven-day retention); selected sanitized examples are retained under `evidence/` for review.

### Review notes

An independent reviewer inspected the working diff and connected search/results/saved/building/navigation/control flows, metadata, existing operator static mount and compatibility identifiers. No actionable code finding was reported. The reviewer requested final gate counts and retained visual evidence before completion; those are supplied below. Reviewer did not run competing browser/database tests while the primary gate was active.

Visual review found a phone date-navigation wrap after the first patch: Refresh occupied the space needed by Next day. The final narrow-screen grid keeps Previous/date/Next together, with Refresh on its own row. The width matrix now asserts arrow alignment. Other observed density issues are explicitly deferred rather than disguised by screenshot success.

### Retained screenshot review

These PNGs are unedited browser captures of the sanitized fixtures, not real campus data. Source tests and full width/theme captures remain in the CI artifact. Inspected for hierarchy, overflow, readable state distinctions, popup placement and private-operation separation:

| Evidence | Manual observations |
| --- | --- |
| [Student search, phone/light](evidence/student-search-mobile-light.png) | No horizontal overflow; code/state/save actions readable. Long form before results remains S02. |
| [Student search, desktop/dark](evidence/student-search-desktop-dark.png) | Shared identity/colors, room state hierarchy and source warning remain visible. Bounded sidebar retains its action. |
| [Building calendar, phone/dark](evidence/student-building-mobile-dark.png) | Corrected arrow row; horizontal scroll is confined to timeline. Unknown hatching remains visible. Repeated Now labels remain C05. |
| [Room calendar, desktop/light](evidence/student-room-desktop-light.png) | Separate building/save actions and day navigation; schedule/cancelled text and dashed cue retained. |
| [Opened date picker, phone/dark](evidence/opened-date-mobile-dark.png) | Popup stays within viewport with selected/today and month controls. |
| [Opened split time picker, desktop/light](evidence/opened-time-desktop-light.png) | Twelve minute choices, hour, AM/PM, preview and typed entry visible; popup clears viewport edges. |
| [Operator login, desktop/light](evidence/operator-login-desktop-light.png) | Private operations identity and empty secret field; no credential appears in capture. |
| [Operator expanded history, phone/dark](evidence/operator-history-mobile-dark.png) | Sanitized run, review reason, identifiers and aggregate counts fit the viewport; raw exports remain absent. |
| [Operator overview, phone/dark](evidence/operator-overview-mobile-dark.png) | Distinct operations context, wrapped IDs and table-region scroll; dense/long layout remains O01. |
| [Operator wizard, desktop/light](evidence/operator-wizard-desktop-light.png) | Approved manifest/capture timestamps/review and private files remain separate, clear validation action. |
| [Operator confirmation, phone/dark](evidence/operator-confirmation-mobile-dark.png) | Identifier/baseline and warnings visible; modal bounded with internal scrolling for lower actions. |

No physical-device, Safari/Firefox or manual screen-reader conformance is claimed. The existing student bundle-size advisory remains a performance follow-up, not a failing build. Full redesign, automated retrieval, source permission, deployment and database changes were outside scope.

### Local check results

- `check.ps1 -Fast`: passed all enabled checks; integration/browser skips explicitly reported as designed. Backend: 137 passed, 149 deselected. Frontend unit tests: 30 passed.
- `check.ps1`: **ALL CHECKS PASSED**. Backend: 286 passed, including 149 PostgreSQL-marked cases, with two existing dependency deprecation warnings. Frontend unit tests: 30 passed. Playwright: 164 passed on desktop/touch projects (2.9 minutes).
- Ruff lint/format, mypy, ESLint, Prettier, TypeScript, student and operator production builds, both PowerShell regression suites and dependency audit all passed. `npm audit`: zero vulnerabilities.
- Initial regression run before the fix: three expected failures proved the old title, 100→60px event-row collapse and ~1008px sidebar height. Focused corrected regressions: four passed. Synthetic student/operator audit: 60 passed before the final full gate.
- Independent code review: no actionable code findings; final evidence documentation completed as requested. `git diff --check` passed.

Known limits: Vite's pre-existing >500kB student-chunk advisory remains; fonts/lazy route splitting belong to #16. Physical devices, manual assistive technology and public source authorization are not verified. No private local database or snapshots were modified.

The built operator page, `/assets/intervella.svg`, and unauthenticated `/ops/health` boundary also passed a local TestClient smoke check without opening any database.
