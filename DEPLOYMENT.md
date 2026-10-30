# Intervella staging on Vercel and Supabase

This is a deployment-ready configuration, not an existing hosted environment. No cloud project, database, DNS record, deployment or real account was created by this PR. Your existing private PostgreSQL database and timetable exports are not used. The owned domain is **intervella.ca**; the planned synthetic staging origin is **https://staging.intervella.ca**.

**Approval boundary:** obtain explicit owner approval before provisioning accounts/resources, changing Porkbun DNS, or deploying. Do not run the manual release workflow until that approval and the project/environment checks below are complete. No production environment is configured. Never upload real campus schedules without separate authorization.

## 1. Compatibility decision

Use one Vercel project with two Services: the existing Vite student build and the existing FastAPI Python Function. Services is currently **beta**, available on all plans; confirm availability on the chosen account before provisioning. Top-level routing preserves `/api`, `/auth` and `/health` paths. SPA deep links fall back to the student index. `/ops` and `/operator.html` reach the protected student backend, which has no operator routes; they cannot serve the private dashboard. No separate public backend hostname is needed. See [Services](https://vercel.com/docs/services) and [FastAPI support](https://vercel.com/docs/frameworks/backend/fastapi).

| Concern | Assessment and implementation |
| --- | --- |
| Worker replacement / multiple instances | Sessions, abuse limits and active policy are PostgreSQL-backed; no filesystem or process-local session store. A regression signs in, replaces the application, restores the same cookie and signs out. |
| Request duration | Existing 15-second application deadline and 3-second SQL statement timeout fit the configured 30-second Function. Public API does not run imports, jobs or uploads. |
| Python / dependencies | Existing `.python-version` selects 3.13. Binary Psycopg/cryptography are supported. Vercel allows a 500 MB uncompressed Python function; actual Linux function size/cold start must be checked in the authorized platform build. Existing parser dependencies remain unchanged. |
| Supabase pooler | Runtime uses shared **transaction** pooling on port 6543, TLS, NullPool and disabled Psycopg prepares. UTC and statement timeout are transaction-local. Read-only REPEATABLE READ snapshots are preserved. Local session-mode defaults are unchanged. |
| Connection budget | NullPool leaves no idle client sockets on frozen workers; Supavisor pools database backends. Concurrent invocations still consume pooler clients. Check the project's actual limits, monitor saturation and apply edge request limits before expanding the beta. This is not an unlimited-concurrency claim. |
| HTTPS / rate limits | Only the Vercel entry point trusts platform-overwritten HTTPS/client-IP headers, and only with `VERCEL=1`. Missing/invalid forwarding or a different canonical host is rejected. Ordinary local/operator entry points do not acquire this trust. |
| Same-origin auth | Browser requests stay relative; secure host-only HttpOnly cookies and exact-origin CSRF remain. No frontend Supabase SDK or direct PostgreSQL access. |
| Private material | `.vercelignore` defaults to deny, allowing the student build and public API sources. Backend ingestion/operator directories, migrations, tests, local data and env files are excluded. Existing frontend operator TypeScript is available only to the unchanged shared type-check/build step; its HTML entry point is excluded and none of its modules are emitted by the student bundle. Public output inspection rejects operator artifacts, source maps and private configuration markers. |

Sources: [pooler behavior and custom-role usernames](https://supabase.com/docs/guides/database/connecting-to-postgres), [Psycopg prepare setting](https://supabase.com/kb/troubleshooting/disabling-prepared-statements-qL8lEL), [Vercel forwarding](https://vercel.com/docs/headers/request-headers), [Function limits](https://vercel.com/docs/functions/limitations).

**Railway fallback:** not implemented because no incompatible public workload was found. If Services access, packaging, cold starts or pooler limits fail staging verification, propose Vercel frontend plus an always-on Railway FastAPI service before making that change. Railway offers predictable process lifecycle and bounded local pools, but adds recurring compute, a second release surface and a backend-origin/proxy trust boundary. It must retain the same server-side authentication and a same-origin Vercel `/api`/`/auth` proxy. Do not use a fallback to expose the operator or bypass authentication.

## 2. Costs and account setup (manual, approval required)

Prices checked October 30, 2026; USD before tax/FX. This is an estimate, not a spending cap.

- Vercel Hobby: $0 for an eligible personal/non-commercial project within quotas. Pro starts at $20/month with usage credit; additional usage/seats/features can cost more. [Current pricing](https://vercel.com/pricing).
- Supabase Free: $0 within limits (500 MB database); projects can pause after a week of inactivity. Free has no paid backup guarantees. Pro starts at $25/month with included compute credit; extra projects/compute/egress/add-ons may add charges. [Current pricing](https://supabase.com/pricing).
- A small eligible synthetic beta can start at $0 incremental hosting, excluding the already purchased domain. Vercel Pro plus a single Supabase Pro Micro project is approximately $45/month before overages/tax. No paid plan is required by this configuration; do not enable upgrades, IPv4 add-ons, PITR or SMTP billing without approval.

After approval, create a **fresh** Supabase staging project and a dedicated Vercel project named `intervella-staging` (or a unique name starting with it). Do not link an existing production or private-data database. Prefer Supabase US East/North Virginia with the configured Vercel `iad1`; if choosing a different geography, change the Function region to a nearby supported region and reassess data-residency requirements before real data.

Use MFA on hosting/registrar accounts. Configure budgets/alerts and review quotas. A shared beta passcode can be forwarded and does not identify individual people.

## 3. Fresh Supabase database and roles

Install PostgreSQL 17 client tools (`psql`, `pg_dump`) for the manual admin operations. Copy the actual shared-pooler hostname/project reference from **Supabase > Connect**; do not derive the cluster index from its region.

| Connection | Use |
| --- | --- |
| Shared pooler, port 6543 | Vercel runtime: `intervella_reader.PROJECT_REF` and `intervella_student_auth.PROJECT_REF`. |
| Shared pooler, port 5432 | Controlled migrations, initial role/password setup, ingestion and backups over IPv4. |
| Direct `db.PROJECT_REF.supabase.co:5432` | Alternative admin connection if IPv6 is available. Not required; no IPv4 add-on purchase. |

All database URLs use `postgresql+psycopg://ROLE.PROJECT_REF:URL_ENCODED_PASSWORD@EXACT_POOLER_HOST:PORT/postgres?sslmode=require` (use the role without `.PROJECT_REF` for a direct connection). Runtime roles must differ and must not own schemas. Never use `postgres`, migrator, ingestor, activation-admin or a Supabase service-role credential in Vercel runtime.

Keep **Data API disabled** if it is not needed, or leave only its required existing schemas exposed. Never add `utscvacant` or `student_auth` to exposed schemas. Supabase Auth can still be configured independently later; browsers do not use its Data API for schedules. Custom schemas and table/sequence privileges are revoked from `PUBLIC`, `anon`, `authenticated` and `service_role` by the grant script.

From the repository root, open a fresh PowerShell session. These helpers keep credentials out of command arguments/history:

```powershell
function Read-PrivateValue([string]$Prompt) {
    $value = Read-Host $Prompt -AsSecureString
    [Net.NetworkCredential]::new('', $value).Password
}
$poolerHost = Read-Host 'Exact NEW staging shared-pooler hostname from Supabase Connect'
$projectRef = Read-Host 'NEW staging project reference'
$env:PGPASSWORD = Read-PrivateValue 'NEW staging project administrator password'
$env:PGSSLMODE = 'require'
try {
    psql --host=$poolerHost --port=5432 --username="postgres.$projectRef" --dbname=postgres --set=ON_ERROR_STOP=1 --file=deploy/roles.sql
    if ($LASTEXITCODE -ne 0) { throw 'Role setup failed; review before proceeding.' }
    psql --host=$poolerHost --port=5432 --username="postgres.$projectRef" --dbname=postgres
    # In psql, set five different generated passwords interactively:
    # \password intervella_migrator
    # \password intervella_reader
    # \password intervella_student_auth
    # \password intervella_ingestor
    # \password intervella_auth_admin
    # \q
} finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
```

`roles.sql` deliberately fails if roles already exist. Do not make it silently overwrite role configuration. Copy the generated passwords into your password manager, not source files. The migrator alone receives schema creation privileges; the public processes never receive them.

Apply the **existing, unchanged Alembic chain** to this new project only:

```powershell
uv --directory backend sync --locked
$env:DATABASE_POOL_MODE = 'transaction' # Also avoids startup options on the admin pooler.
$env:MIGRATION_DATABASE_URL = Read-PrivateValue 'NEW staging migrator URL, pooler port 5432, sslmode=require'
try {
    uv --directory backend run --no-env-file alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed; stop and investigate.' }
} finally { Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue }

$env:PGPASSWORD = Read-PrivateValue 'NEW staging migrator password'
try {
    psql --host=$poolerHost --port=5432 --username="intervella_migrator.$projectRef" --dbname=postgres --set=ON_ERROR_STOP=1 --file=deploy/grants.sql
    if ($LASTEXITCODE -ne 0) { throw 'Grants failed; stop and investigate.' }
} finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
```

The reader gets SELECT on the six query tables, with no ingestion-run/auth access or writes. Auth runtime gets session/attempt CRUD, control SELECT and UPDATE on its fixed `id` column only (required for PostgreSQL row locks). It cannot modify the policy, insert/delete control rows or activate a policy. Ingestor and activation administrator are separate offline credentials. Inspect grants after every future migration; new tables do not automatically gain runtime grants. No migration runs during build, startup or deployment.

## 4. Generate, validate, stage and explicitly publish synthetic data

This uses the existing strict local HTML ingestion and atomic publication pipeline. The deterministic development seed is unchanged. Generated files contain only `SYN-DEMO`, two synthetic rooms, explicit 08:00–22:00 daily grids and synthetic bookings. Outside that verified interval remains unknown; it is not a claim about campus access hours. Generation records its true generation timestamp.

```powershell
$firstDate = uv --directory backend run --no-env-file python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('America/Toronto')).date())"
$stagingSources = Join-Path (Get-Location) ("backend/data/cloud-staging-" + (Get-Date).ToString('yyyyMMdd-HHmmss'))
uv --directory backend run --no-env-file python staging.py generate "$stagingSources" --start-date $firstDate
if ($LASTEXITCODE -ne 0) { throw 'Synthetic generation failed.' }
uv --directory backend run --no-env-file python -m app.ingest import "$stagingSources" --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Synthetic validation failed.' }

$env:INGESTION_DATABASE_URL = Read-PrivateValue 'NEW staging ingestor URL, pooler port 5432, sslmode=require'
try {
    $result = uv --directory backend run --no-env-file python staging.py stage "$stagingSources" --confirm-empty-staging
    if ($LASTEXITCODE -ne 0) { throw 'Staging failed; nothing will be published.' }
    $candidate = $result | ConvertFrom-Json
    $candidate | Format-List # Review seven dates, counts and candidate ID before continuing.

    # Separate, explicit publication action after reviewing the report:
    uv --directory backend run --no-env-file python -m app.ingest publish $candidate.dataset_id
    if ($LASTEXITCODE -ne 0) { throw 'Publication failed; stop and investigate.' }
    uv --directory backend run --no-env-file python -m app.ingest status
} finally { Remove-Item Env:INGESTION_DATABASE_URL -ErrorAction SilentlyContinue }
```

The staging helper rejects existing output directories, changed/non-generated input bytes and nonempty schedule tables. Do not run concurrent initialization jobs. Later refreshes require a newly generated directory and an explicit normal `app.ingest import`/review/`publish`; the initial empty-database helper intentionally refuses reuse. Keep real exports away from this workflow. Do not reset timestamps or extend freshness to make old demo data appear current. After 36 hours it is honestly stale; regenerate/review synthetic data if a fresh demonstration is needed.

## 5. Private runtime configuration and beta activation

Copy `.env.staging.example` to the ignored `.env.staging` **only if the destination does not exist**. Fill in the two runtime URLs, hash, epoch and closing time privately. Never commit this file, put it in `frontend`, or prefix secrets with `VITE_`. Restrict local permissions to your account.

Generate values without putting a passcode on the command line:

```powershell
$betaHash = uv --directory backend run --no-env-file python -m app.student_auth
$epoch = uv --directory backend run --no-env-file python -c "import secrets; print(secrets.token_urlsafe(32))"
$closing = [DateTimeOffset]::UtcNow.AddDays(7).ToString('o')
```

| Vercel server variable | Value |
| --- | --- |
| `DATABASE_URL` | `intervella_reader` URL through shared pooler 6543 with TLS. |
| `STUDENT_AUTH_DATABASE_URL` | Different `intervella_student_auth` URL to the same staging project through 6543 with TLS. |
| `DATABASE_POOL_MODE` | `transaction`. |
| `STUDENT_AUTH_MODE` | `beta`. |
| `STUDENT_AUTH_ORIGIN` | Exact canonical origin: initially your dedicated staging `.vercel.app` URL, later `https://staging.intervella.ca`. No trailing slash. |
| `STUDENT_BETA_PASSWORD_HASH` | Entire generated scrypt hash, including dollar signs. |
| `STUDENT_AUTH_EPOCH` | Generated random secret, same value for activation and every replica. |
| `STUDENT_BETA_ENDS_AT` | Generated `$closing` ISO timestamp, with timezone; choose the actual launch window. |
| `STUDENT_AUTH_TTL_SECONDS` | `604800`; fixed beta closing overrides a longer remaining session. |
| `FRESHNESS_MAX_AGE_HOURS` | `36`, not extended for demos. |
| `MAX_AVAILABILITY_LIMIT` | `100`. |
| `API_REQUEST_TIMEOUT_SECONDS` | `15`. |
| `ALLOWED_ORIGINS` | Leave unset for this same-origin deployment; auth origin is added exactly. Never `*`. |
| `VERCEL` | Platform-provided `1`; do not spoof it for an ordinary/local server. |

Store sensitive values in Vercel's server environment for the dedicated **staging project**, in its Production slot (that is Vercel's stable-slot name, not permission to deploy the real production service). Do not reuse a real production project or its secrets. Do not inject admin/ingestor/operator credentials, Supabase secret/service-role keys or `VITE_*` credentials. The hosted entry point fails closed if privileged connection variables are present, TLS is missing, auth is invalid or transaction mode is absent. System environment variables must be available to the Function.

In dotenv files, single-quote hashes/URLs so `$` is literal. Vercel dashboard values themselves are pasted **without** surrounding shell quotes. For manual local activation, `.env.staging` contains the exact same runtime values as Vercel:

```powershell
$authFile = (Join-Path (Get-Location) '.env.staging').Replace('\', '/')
# The admin URL MUST use the same host, port 6543, database and sslmode options as auth runtime.
$env:STUDENT_AUTH_ADMIN_DATABASE_URL = Read-PrivateValue 'NEW staging intervella_auth_admin URL, same pooler target/options as auth runtime'
try {
    uv --directory backend run --env-file $authFile python -m app.student_auth activate
    if ($LASTEXITCODE -ne 0) { throw 'Activation failed; do not launch.' }
} finally { Remove-Item Env:STUDENT_AUTH_ADMIN_DATABASE_URL -ErrorAction SilentlyContinue }
```

Activation revokes all previous student sessions in that auth store. Code deploys do not activate/revoke automatically. Credential/mode/origin/epoch changes require coordinated redeployment and explicit activation; stale replicas fail closed. See [AUTHENTICATION.md](AUTHENTICATION.md) for renewal, revocation and full university setup. University mode additionally requires `STUDENT_SUPABASE_URL`, `STUDENT_SUPABASE_PUBLISHABLE_KEY`, `STUDENT_AUTH_ENCRYPTION_KEY`, `STUDENT_AUTH_EMAIL_DOMAINS`, `STUDENT_AUTH_ELIGIBILITY` and optionally `STUDENT_SUPABASE_AUDIENCE`. Verified email does not certify enrollment; institutional policy remains pending approval. No fallback to beta is allowed.

## 6. Vercel project and controlled release

Use Vercel CLI **65.8.0**, Node 22 (22.18+), Python 3.13. Root Directory is the **repository root**, not `frontend`. `vercel.json` owns the two service roots and routing; do not override it with a frontend-only framework preset. Student build runs `npm ci` and `npm run build`; Python install uses `uv sync --locked --no-dev`. There is no operator service or build in the public configuration. CI still builds/tests the separate local operator to preserve it.

Git-triggered Vercel deployments are disabled in versioned configuration. Never enable automatic deployment with production secrets. After resource/deployment approval, authenticate the CLI and link **the existing dedicated staging project**; decline prompts to create a different project. Inspect `.vercel/project.json` locally (ignored) to confirm project/org IDs.

```powershell
npx.cmd --yes vercel@65.8.0 login
npx.cmd --yes vercel@65.8.0 link
npx.cmd --yes vercel@65.8.0 pull --environment=production
npx.cmd --yes vercel@65.8.0 build --prod
# STOP if build fails or the Function exceeds the published Python size limit.
# After explicit deployment approval, and only in the dedicated staging project:
npx.cmd --yes vercel@65.8.0 deploy --prebuilt --prod
```

Do not run these commands against an unreviewed link. `--prod` here selects the stable slot of the **synthetic staging project**. It is not a production rollout. The deployment serves the student login before any schedule request; the backend independently rejects anonymous access. Alternate generated deployment aliases cannot sign in unless they are the configured origin. Keep a stable origin for the beta so cookies, CSRF and policy fingerprints agree.

The runtime does not trust arbitrary generic proxy headers; do not add `--forwarded-allow-ips=*` or another proxy in front of Vercel. HTTPS, HSTS, restrictive same-origin CSP, framing denial, no-referrer and permissions headers are configured. API/auth responses remain private/no-store; never override that with CDN caching or cache a successful authenticated response. Keep platform logs/tracing free of request bodies, cookies, provider tokens, credentials and query strings. Use sanitized application request IDs for diagnosis.

For repeatable releases after merging, configure GitHub **Environment `staging`** with protected `main` and required reviewer approval (where supported by the repository's plan). Add environment secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `INTERVELLA_SMOKE_PASSCODE`; add environment variable `INTERVELLA_STAGING_ORIGIN=https://staging.intervella.ca` (or the dedicated `intervella-staging*.vercel.app` origin during setup). Scope the token to the staging team/project as narrowly as the account permits, and expire/rotate it after use. If environment reviewers are unavailable, leave the workflow disabled until an equivalent owner-controlled release gate is established.

The **Deploy synthetic staging** workflow is manual-only, accepts confirmation `synthetic-staging`, and runs only reviewed `main`. It runs backend/PostgreSQL and complete frontend/browser checks before reaching the protected deployment job. It pulls settings for the existing project, builds a prebuilt release, deploys it to the staging slot and smoke-tests the canonical origin. There are no database/migration/import/publication steps and no push-triggered deploy. Post-deployment smoke failure fails the job; use the explicit rollback below. Never substitute production project IDs or real-data secrets.

## 7. Porkbun DNS and HTTPS (manual, separate approval required)

Keep Porkbun authoritative DNS; no nameserver transfer or domain purchase is needed. First add `staging.intervella.ca` to the dedicated staging Vercel project under **Settings > Domains**. Copy the exact project-specific DNS target and any ownership verification record Vercel displays. These values do not exist in the repository and cannot be guessed before the approved project/domain setup.

In **Porkbun > Domain Management > intervella.ca > DNS**, add:

| Type | Porkbun Host | Answer / Value | TTL |
| --- | --- | --- | --- |
| CNAME | `staging` | **Exact project-specific hostname from Vercel**, without scheme/path. | 600, or Porkbun's permitted default. |
| TXT, only if Vercel requests it | Exact host shown by Vercel (often `_vercel` or a scoped variant). | Exact ownership token shown by Vercel. | Default. |

Do not use a guessed generic CNAME or a remembered Vercel IP. Remove only conflicting records for the **same `staging` host**, after reviewing them. Preserve apex/www, email MX/TXT, SPF/DKIM/DMARC and unrelated DNS. Do not change `intervella.ca` or `www` in this PR.

```powershell
Resolve-DnsName staging.intervella.ca -Type CNAME
Invoke-WebRequest https://staging.intervella.ca/health/live
# Should return sanitized {"status":"ok"}; then run the authenticated smoke below.
```

Wait for Vercel's domain screen to report valid configuration and a valid HTTPS certificate. If existing CAA restricts certificate issuance, follow the exact Vercel diagnostic rather than adding broad records. Change `STUDENT_AUTH_ORIGIN` in staging/private activation configuration to `https://staging.intervella.ca`, redeploy and explicitly activate it; old-origin sessions are intentionally revoked. The student app, `/api` and `/auth` now share that HTTPS origin. Verify plain HTTP redirects to HTTPS and cookies have Secure/HttpOnly/SameSite/Path=/ with no Domain.

A later separately approved `intervella.ca` rollout requires its own project/database/access review. Porkbun apex Host is blank with Vercel's **current project-specific A record**; `www` uses Vercel's displayed CNAME/redirect configuration. Do not apply those future records now. Sources: [Vercel domain setup](https://vercel.com/docs/domains/set-up-custom-domain), [Porkbun DNS editor](https://kb.porkbun.com/article/68-how-to-edit-dns-records).

## 8. Verification and staging acceptance

From the repository root:

```powershell
.\check.ps1 -Fast
.\check.ps1
uv --directory backend run --no-env-file python verify_public_build.py ../frontend/dist
# After authorized staging deployment, prompts privately for the passcode:
uv --directory backend run --no-env-file python deployment_smoke.py https://staging.intervella.ca
```

The smoke performs liveness, anonymous denials across every protected timetable route and malformed paths, no-store, rejected wrong passcode, secure cookie, session restoration, synthetic inventory, date-bounded availability, snapshot ID, room/building schedules, room search, operator exclusion and logout/revocation. It does not import/publish data. Each run uses two login attempts; repeated runs can correctly hit the shared limit. CI provides its passcode through the protected environment, never an argument. Smoke outputs no raw responses, credentials or cookies. Keep browser traces/screenshots disabled for real credential tests.

Before inviting friends, manually verify in staging: mobile/desktop login, date/time filters including seconds/DST, room/building calendar, favourites after reload, deep links, demo/unknown/stale messages, keyboard focus, logout and session expiry. Redeploy the **same** policy/config and confirm the existing session survives. Confirm missing DB connectivity/configuration closes access without leaking details. Do not change a healthy staging DB to test outages; use a separate disposable test deployment. Local synthetic tests cover these failure modes but do not prove live TLS/DNS/pooler/provider configuration.

`/health/live` is public and does not query PostgreSQL. `/health/ready` is authenticated and can return 503 outside complete published coverage; that is a coverage limitation, not necessarily a broken Function. Never weaken readiness or infer overnight availability to make a monitor green.

## 9. Rollback, backup and cleanup

Record the last known good staging deployment URL/commit and policy configuration before a release. If smoke fails, use Vercel's rollback action for that **staging project** or, after approval, `npx.cmd --yes vercel@65.8.0 rollback <KNOWN_GOOD_DEPLOYMENT_URL>`. Re-run smoke. A rollback restores application code, not database state or the active auth policy. Never roll back publicly to a pre-authentication build. Schema changes use a separate reviewed expand/contract operation; do not automatically run Alembic downgrade or restore data during code rollback.

For synthetic staging, regeneration is the simplest data recovery. If retaining snapshots, use `pg_dump` through the admin session/direct connection with `--schema=utscvacant --schema=student_auth --no-owner --no-privileges`, write only to private ignored/encrypted storage and verify restoration on a **new disposable project**. Never dump your private development DB for cloud staging. Free-tier backups are your responsibility; review paid backup retention/PITR and costs before approving them. Protect encrypted provider-token backups and keep the encryption key separately. Restoring auth data requires a new epoch and explicit policy activation to invalidate restored sessions. Reapply reviewed role grants, migrations and configuration before reconnecting runtime. No database restoration against an existing good environment is automated.

To end the beta: retain its hard closing timestamp, rotate epoch/activate to revoke sessions if ending early, remove deployment tokens, and disable the manual workflow. After approval, remove only the staging DNS records before detaching/deleting that project's domain to avoid dangling records. Delete/pause unused staging projects and paid add-ons deliberately; check both billing dashboards for residual compute/egress/storage charges. Keep the domain registration and unrelated DNS.

## 10. Troubleshooting and verification limits

| Symptom | Check |
| --- | --- |
| 421 on API/auth | Browser host differs from `STUDENT_AUTH_ORIGIN`; use canonical staging URL. Do not add wildcard origins. |
| 403 invalid ingress | Vercel system marker/overwritten HTTPS/IP headers missing or malformed; do not spoof them or enable universal proxy trust. |
| 503 sign-in unavailable | Missing/invalid auth settings, TLS/pool mode, forbidden admin secret, inactive policy, permissions or pooler connectivity. Use sanitized request ID. |
| Password always rejected | Dashboard hash must include all `$` sections without shell quotes; private dotenv file must single-quote it. |
| Pooler authentication fails | Copy exact host; custom-role username is `ROLE.PROJECT_REF`; verify role password, port and project pause state. |
| Prepared statement / startup options error | Ensure `DATABASE_POOL_MODE=transaction`, new code deployed, no prepare overrides/startup options. |
| HTML instead of API JSON | Repository root/services/routing misconfigured; do not set Vercel root to frontend only. |
| Calendar empty / readiness 503 | Inspect authenticated status period/freshness and actual 08:00–22:00 coverage; do not invent campus hours or free rooms. |
| CLI build asks for a project | Link the already approved staging project and pull settings. No actual Vercel project credentials are needed for repository tests, but platform builds require an authorized account/link. |
| TLS/domain pending | Verify Porkbun CNAME/optional TXT against Vercel's current instructions, propagation and existing CAA. |
| Valid cookie lost after code release | Config/policy changed, expiry elapsed or wrong auth store; code-only releases do not revoke sessions. |

Actual Vercel Linux packaging/size, Supabase transaction-pooler TLS/limits, public HTTPS smoke, SMTP delivery, DNS/TLS issuance, billing and physical-device testing remain owner-authorized staging checks. Passing local mocks/schema/browser tests is not a claim that cloud infrastructure exists or is production verified. The operator stays on its existing private loopback service and is not part of this deployment.
