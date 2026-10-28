# Milestone 3: React Frontend and API Integration

**Base:** latest `origin/main`, `c517523` (Milestones 1 and 2 merged). Isolated branch `feat/react-frontend`, worktree `.worktrees/react-frontend`. Original untracked PDFs remain untouched.
**Authority:** PRD and October 14, 2026 TRD; especially frontend contracts on TRD page 8 and coverage/freshness rules. User authorizes autonomous routine decisions, commits, push, and PR; no merge.

## Design

- A mobile-first campus timetable: cool paper `#f0f5fa`, white `#ffffff`, navy `#142c45`, blue `#155abb`, muted ink `#52667b`, amber `#9c5800`. Georgia display headings, Segoe UI/body system stack, monospace times. Desktop search column plus room grid; mobile search followed by results. Signature is a clear time-window strip, not decorative graphics or animation.
- Permanent **Unverified / demo data** notice on every view. The API has no provenance flag, so this milestone never certifies current campus data and never silently falls back to mocks. Synthetic fixtures are test-only. No backend, parser, seed, database, or API-contract changes.
- Reuse installed React and TanStack Query. Use native controls, History/URLSearchParams, Intl timezone formatting, and Fetch/AbortSignal. Add only Playwright and axe development tooling; Node's native test runner covers pure TypeScript utilities. No router, date library, icon package, auth, service worker, maps, recommendations, or scraping.
- Typed client for availability, buildings, rooms, schedules, and status. Credentials stay out of browser code. Same-origin `/api` with Vite development proxy; production host must reverse-proxy `/api` to FastAPI. Errors display safe client copy and optional request IDs, not raw backend payloads.
- URL holds mode, custom date/time/offset, duration, building, selected room, and schedule date. Now bookmarks intentionally mean the current instant; custom bookmarks preserve Toronto wall time and DST choice. Back/forward restores views. Dates are campus-local regardless of device timezone.
- Convert Toronto wall times using Intl-derived offsets and round-trip candidate validation. Reject nonexistent DST times; ambiguous times require explicit occurrence/offset selection. This conversion only creates request instants, never calculates availability.
- Only API responses establish availability. Show next booking, nullable capacity, API freshness, coverage exclusions, query window, and last-check time. Missing meetings/unknown next booking never mean unlimited availability. Room schedule includes cancelled meetings and explicit coverage caveats.
- Query cancellation and isolated keys prevent old searches flashing into new results. Visible Now queries refresh every 60 seconds; fixed queries refresh manually or after status detects a dataset change. Offline/errors hide unsupported current-availability claims. Status freshness may update only for the same dataset.
- Accessible radio/select/date/time controls, visible focus, skip link, status announcements, understandable non-color labels, and normal page-style room views with focus restoration. Respect reduced motion; no unnecessary animation.

## Commit plan / acceptance

1. **Client, time, and URL foundation:** write failing Node tests, implement typed API client and Toronto/URL utilities; set strict TypeScript/test commands and dev proxy.
2. **Application:** replace starter with search, result/coverage/freshness states, room details/schedule, URL navigation, offline handling, and functional responsive styling. Add failing Playwright flows before implementation; inspect desktop/mobile screenshots and axe results.
3. **Coverage and delivery:** browser tests for URL restore/back, keyboard, DST, invalid requests, superseded responses, stale/missing coverage, offline, auto-refresh and dataset changes; production build, lint, type checks, local guide, pinned least-privilege GitHub Actions.
4. **Review and publish:** independent final correctness/security/accessibility review, regression-test fixes, full checks, verify backend is unchanged, push and create PR to main, observe hosted CI. Leave branch/worktree and user data intact.

## Stop condition

Core flows and states work against existing typed API; production build, unit/browser/a11y checks, lint and types pass; desktop/mobile UI inspected; independent review addressed; PR open with hosted checks passing. Deployment/source provenance and ingestion remain later milestones.
