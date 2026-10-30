# Vercel and Supabase staging implementation plan

**Goal:** Prepare a synthetic-only, single-origin staging deployment without creating cloud resources or touching private data.
**Architecture:** Vercel Services (currently beta) builds the existing Vite student interface and FastAPI Python Function together. Supabase holds the unchanged timetable and student_auth schemas behind separate runtime roles. Migrations, synthetic import/publication and policy activation remain explicit administrator operations outside deployment.
**Spec:** PR #21 request and the user's Vercel/Supabase override. Execute inline using existing repository patterns.

## Compatibility assessment

- FastAPI requests are bounded; there are no public background jobs, uploads or persistent files. Authentication is PostgreSQL-backed and survives worker replacement. Python 3.13, binary Psycopg and cryptography are supported; the final function size needs platform build verification.
- Existing connections assume session pooling: startup options and prepared statements must not be used with Supabase's shared transaction pooler. Add an explicit transaction mode with NullPool, disabled prepares and transaction-local UTC/statement timeout. Keep local defaults unchanged and preserve read-only REPEATABLE READ snapshots.
- Hosted authentication needs a strict Vercel-only ingress adapter for HTTPS, canonical host and platform client IP. Generic forwarded headers must never enable a local bypass. All application authorization remains in the existing common boundary.
- Services provides one origin and atomic code releases, but is beta. No Railway fallback is justified yet. If platform build/runtime/pooler staging verification fails, explain the always-on Railway trade-off before implementing any fallback.
- Do not create resources, run a cloud deployment, change DNS, use private snapshots/database, expose operator routes, or perform migrations/publication automatically.

## Review focus

Unknown hosts/forwarded headers must fail closed; pooler settings must not leak across transactions; sessions must survive app replacement; synthetic tools must refuse overwrites/nonempty schedules; source/operator/secrets must be absent from public artifacts.

## Tasks

- [x] Connection compatibility: red/green unit and PostgreSQL tests in backend/tests/test_db.py and test_deployment_postgres.py; update only backend/app/db.py. Commit pooler support.
- [x] Hosting: backend/app/hosting.py and backend/vercel_app.py, vercel.json, .vercelignore, pinned supported runtime versions. Test ingress, fail-closed configuration, canonical host, static/public routing and operator exclusions. Commit hosting config.
- [x] Synthetic staging and smoke: generate seven explicitly scoped dated files using synthetic room names; validate/stage with the existing pipeline and publish only with the existing explicit command. Provide safe smoke checks using the existing auth/API. Test both on disposable PostgreSQL and mocked HTTPS. Commit tools and manual approval-gated staging workflow.
- [x] Documentation/review: DEPLOYMENT.md with exact environment/roles/migration/policy/domain steps, DNS values copied from Vercel rather than guessed, costs/quotas/backup/rollback/cleanup. Run both root checks, focused deployment tests, schema/build inspection, independent final review. Push feature branch, open PR main, verify CI. No merge/deploy.

## Verification record

Both root check modes passed. Full root run: 385 backend, 32 frontend unit and 246 browser tests passed. A subsequent complete backend run with the final empty-environment and restricted-role lock regressions: 386 passed, two existing dependency deprecations. Ruff/mypy/TypeScript/ESLint/Prettier/builds and zero-vulnerability frontend audit passed. Published Vercel schema and actionlint 1.7.12 validation passed; actionlint shellcheck/pyflakes integrations were not installed.

Independent review found the PostgreSQL FOR SHARE privilege requirement missed by the prior plain-SELECT role test. Reproduced the denial, then granted UPDATE(id) only on the id=1 control singleton and tested the lock plus continued denial of policy edits; existing auth documentation corrected. Windows empty pool-mode handling was also fixed/tested. Neither change grants policy activation to the runtime.

No frontend bundle growth: student 577.12 kB / 177.44 gzip; operator 530.50 / 163.20, unchanged from main. Public student output inspected and CSP exercised in desktop/mobile browser tests. Local Vercel build cannot be claimed verified without an authorized project link; a source-only offline fixture was removed after that check. No cloud resources or DNS were created/changed.

Cloud HTTPS, actual Supabase pooler, provider account configuration and Porkbun DNS verification require separately authorized staging access; local tests do not prove those operations.
