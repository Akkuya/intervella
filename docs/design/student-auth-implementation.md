# Student access implementation and review evidence

Branch: `codex/student-auth`, based on merged Carbon Lavender main. The private development database and private timetable snapshots were not modified. No Supabase project or deployment was created.

## Completed checklist

- [x] Shared PostgreSQL sessions, atomic rate counters and an explicit active-policy control row.
- [x] Fail-closed beta/university configuration, HTTPS-only hosted sessions and loopback-only HTTP development.
- [x] Fixed-cost scrypt beta verification, global beta deadline, CSRF, logout and revocation.
- [x] Supabase email OTP, asymmetric JWT/JWKS validation, authoritative confirmation/eligibility checks and encrypted serialized renewal.
- [x] Common Carbon Lavender frontend session gate, intended URL preservation, cache clearing and separate logout control.
- [x] Existing anonymous favourites and all schedule/calendar/control contracts preserved; operator auth remains independent.
- [x] Security/unit/real-HTTP/PostgreSQL/browser regressions; Windows configuration and secret-isolation checks.
- [x] Private configuration template, exact PowerShell setup and activation commands, least-privilege grants and deployment checklist in [AUTHENTICATION.md](../../AUTHENTICATION.md).
- [x] Both local root check modes and final security/correctness review. Final PR CI status is recorded in the PR; no automatic merge.

## Decisions and review

Authentication is a shared request boundary, not a frontend visibility flag. All timetable-bearing endpoints and readiness are protected before their existing data/validation work. Public liveness is static; designated auth routes expose only sign-in/session actions. Errors and responses use safe, non-cacheable contracts. Malformed route forms and student-cookie attempts against the operator service are tested.

Authentication lives in its own schema and connection, with no classroom-table changes. The migration freezes its DDL rather than importing live application metadata, and metadata agreement, roundtrip and lossy-downgrade protection are exercised on disposable databases. Runtime database grants exclude schedule reads, schema creation and policy writes; administration is an explicit separate job.

A policy fingerprint alone would allow an old beta cookie to return when an earlier mode was restored. Explicit activation instead locks the shared control row, replaces its policy and deletes old sessions transactionally. In-flight issuances serialize with activation; stale replicas fail closed. Changing mode/credentials never implicitly activates a policy or falls back to another provider.

University verification pins asymmetric algorithms, project issuer/audience and signing-key identity. Trusted `/user` confirmation and `app_metadata` checks are separate from user-editable metadata. Tokens remain encrypted in PostgreSQL and are absent from frontend responses/storage. Renewal locks prevent concurrent token reuse across replicas/tabs. Eligibility is explicitly configured and does not certify enrollment.

The frontend keeps the current URL through login and does not follow external redirect parameters. Session denial/expiry unmounts timetable views and cancels/clears query data while retaining existing favourites. Existing synthetic schedule tests explicitly mock authenticated session restoration; the new backend and browser auth suites test unauthenticated access, lifecycle and failures independently. No runtime authentication bypass exists.

Review also checked bounded sign-in bodies/deadlines, Unicode/malformed CSRF headers, mode switching back to beta, passcode rotation, fixed beta closing, cookie flags, shared abuse limits, logout-before-provider failure behavior, JWT forgery/claims, JWKS rotation, and rejection of a mismatched administrator connection target. A synthetic smoke check verified quoted scrypt hashes and the absolute forward-slash Windows uv env-file command. The full tests and final execution totals are recorded in the PR.

## Local verification

- Both `check.ps1 -Fast` and `check.ps1` passed. Full local browser run: 244 passed; frontend unit tests: 32 passed. Full backend head run: 360 passed, with two existing dependency deprecation warnings.
- Ruff lint/format, mypy, ESLint, Prettier, TypeScript, both production builds, PowerShell regressions and dependency audit passed. Audit: zero vulnerabilities.
- The full root run preceded the last administrator-CLI-only regression; that regression and the subsequent complete 360-test backend run also passed. Frozen migration DDL then passed all three focused metadata/roundtrip/preservation checks.
- Browser tests cover both modes, desktop/touch, light/dark, refresh/navigation, expiry while searching, provider renewal, logout, favourites, malformed session metadata and axe checks. The existing six-width application/operator suite remains.
- Student JavaScript: 577.12 kB (gzip 177.44), versus 569.58 kB (gzip 175.16) before auth. Operator JavaScript is unchanged at 530.50 kB (gzip 163.20). No frontend authentication SDK dependency was added; JWT/cryptography is server-side.

## Synthetic screenshot review

These are unedited browser captures from intercepted synthetic fixtures, with empty credential fields. Mobile denotes a 360px viewport; desktop is 1440px. Representative captures were visually inspected for layout, hierarchy, readable feedback, touch targets, theme consistency and absence of protected timetable content.

| Mode | Light | Dark |
| --- | --- | --- |
| Beta, desktop | [Screenshot](student-auth/beta-light-desktop.png) | [Screenshot](student-auth/beta-dark-desktop.png) |
| Beta, mobile | [Screenshot](student-auth/beta-light-mobile.png) | [Screenshot](student-auth/beta-dark-mobile.png) |
| University, desktop | [Screenshot](student-auth/university-light-desktop.png) | [Screenshot](student-auth/university-dark-desktop.png) |
| University, mobile | [Screenshot](student-auth/university-light-mobile.png) | [Screenshot](student-auth/university-dark-mobile.png) |

## Not verified by mocks

Real Supabase SMTP delivery, production credentials, IITS eligibility approval, institutional SSO, reverse-proxy/TLS deployment, manual screen-reader operation and physical phones require authorized staging/operational checks. No cloud deployment, private-data import/publication, real account creation or private database migration was performed. A shared beta passcode cannot identify individuals or prevent an authorized friend sharing it. Existing bundle-size advisories remain.
