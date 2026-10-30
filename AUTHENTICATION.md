# Student authentication: beta and university

Timetable APIs now require a student session. Authentication is server-side, including buildings, room search, availability, room details/schedules, building calendars, dataset status and readiness. Alternate paths do not bypass the boundary. `/health/live` is public and contains only process liveness; exact `/auth/*` login/session actions are designated non-sensitive resources. API documentation requires authentication too.

There is no public/disabled provider and no fallback between providers. Missing, invalid or inactive configuration leaves timetable access closed. The separate loopback operator service retains its existing authentication, cookies, CSRF and publication boundary. This change neither authorizes republication of campus data nor establishes enrollment or physical room access.

## Architecture and lifecycle

The browser holds an opaque HttpOnly cookie. Only its SHA-256 hash is stored in PostgreSQL's separate `student_auth` schema. Availability tables and read-only snapshot transactions are unchanged. Authentication can use a different PostgreSQL database through `STUDENT_AUTH_DATABASE_URL`; student browsers never connect to either database.

`session`, `attempt` and a singleton `control` table provide shared sessions, atomic rate limits and one active policy across processes/replicas. Runtime processes may read the control row but cannot activate it. Activation locks that row, waits for in-flight issuance/renewal transactions, changes its fingerprint and deletes all previous sessions in one transaction. Old replicas fail closed. Returning to an earlier mode cannot revive deleted sessions.

Beta passwords use a fixed-cost scrypt hash (N=32768, r=8, p=3) with a random salt and constant-time digest verification. Every beta session expires at the earlier of its TTL or the required beta closing timestamp. The maximum TTL is seven days. University sessions have a fixed application TTL and shorter provider access-token deadlines; renewal is serialized per session. Provider access/refresh tokens are Fernet-encrypted server-side. JWTs never enter URLs, browser storage or frontend configuration.

University login uses an email one-time code. The server verifies ES256/RS256 signatures, `kid`, issuer, audience, expiry, issued-at, subject, authenticated role and exact permitted email domain. A provider `/user` request independently checks email confirmation, subject/email binding and trusted eligibility metadata. Unverified emails and `user_metadata` assertions do not grant access. JWKS caching lasts 60 seconds locally, with an unknown-key refresh; Supabase's own edge cache can add delay. No symmetric-key or unsigned-token fallback exists.

A verified address does **not** prove current enrollment. `verified_email` permits only verified addresses from the configured exact domains. `approved_metadata` additionally requires `app_metadata.intervella_eligible` to be the boolean `true`, set through trusted administration. Select domains and eligibility only after the relevant IITS/owner approval; neither policy is selected by default in university mode. A future institution-issued SSO provider can replace the identity exchange behind the common session boundary without changing classroom schemas or availability endpoints.

The frontend restores the session before mounting timetable views, keeps the existing intended URL, and never follows a supplied external redirect. It polls session state, renews university access before expiry, removes protected results and clears/cancels React Query data on expiry, logout or authentication denial. Room/building navigation remains within the same session. Existing anonymous local favourites and appearance keys are unchanged; there is no account synchronization.

## Configuration

Keep runtime values in the ignored root `.env.student`, or inject them through the backend's environment/secret manager. They must never be `VITE_*` variables. Restrict private-file permissions to the application account/owner, and serve only frontend build directories, never the repository root. `dev.ps1` loads this file only into the backend worker; frontend, operator and test workers strip student secrets. The private-file parser rejects admin/operator keys, duplicates and unsupported entries. `check.ps1` does not inherit your runtime student credentials.

| Variable | Requirement |
| --- | --- |
| `STUDENT_AUTH_MODE` | Exactly `beta` or `university`. |
| `STUDENT_AUTH_ORIGIN` | Exact browser origin, no path/trailing slash. HTTPS for hosted access. HTTP only for literal loopback development; requests from non-loopback clients are rejected in that mode. |
| `STUDENT_AUTH_DATABASE_URL` | PostgreSQL runtime role, restricted to the auth schema described below. No fallback to the schedule database credential. |
| `STUDENT_AUTH_EPOCH` | At least 32 characters of independently generated random secret. Change for global revocation. All replicas must agree. |
| `STUDENT_AUTH_TTL_SECONDS` | 300–604800; default 604800. Renewal does not extend the fixed application deadline. |
| `STUDENT_BETA_PASSWORD_HASH` | Required in beta; generate with the interactive command below. Never use a plaintext passcode here. |
| `STUDENT_BETA_ENDS_AT` | Required in beta; ISO timestamp with timezone, usually launch time plus seven days. |
| `STUDENT_SUPABASE_URL` | Required in university mode; HTTPS project base URL without a path. |
| `STUDENT_SUPABASE_PUBLISHABLE_KEY` | Required in university mode; `sb_publishable_…` key. No secret/service-role key or legacy shared JWT secret. |
| `STUDENT_AUTH_ENCRYPTION_KEY` | Required in university mode; Fernet key from `Fernet.generate_key()`. Keep separate from database backups. Rotation revokes sessions through activation. |
| `STUDENT_AUTH_EMAIL_DOMAINS` | Required comma-separated exact approved domains. No wildcard/subdomain inheritance. |
| `STUDENT_AUTH_ELIGIBILITY` | Required in university mode: `verified_email` or `approved_metadata`. |
| `STUDENT_SUPABASE_AUDIENCE` | Default `authenticated`; change only to the provider's actual approved audience. |
| `STUDENT_AUTH_ADMIN_DATABASE_URL` | Administrator job/shell only; never runtime/private-file/frontend configuration. Must target the same host, port, database and connection options as the runtime auth URL, using an administrator role. |

HTTPS cookies use `__Host-intervella_student`, `Secure`, HttpOnly, SameSite=Lax, Path=/ and no Domain. The separate HTTP loopback cookie has a different name and cannot be used to bypass hosted authentication. Mutation endpoints require exact Origin, JSON, a custom request header and, for existing sessions, the matching server-held CSRF token. Auth request bodies are bounded and request deadlines include body/auth work. Responses use `private, no-store`, vary by Cookie/Origin and do not contain raw provider errors. No bearer token supplied by the browser is accepted as a substitute for the opaque session.

Login/verification attempts are counted in PostgreSQL across replicas: 10 per client IP and 100 globally per action per 15-minute window; email-code actions also allow 5 per exact email per window. Counters include failed and successful attempts and are HMAC-pseudonymized. Multiple friends behind one campus NAT share its limit. This is abuse protection for a small beta, not DDoS protection; configure edge limits as well.

## Local setup without changing private development data

Run these from the repository root. Use a **new disposable/staging auth database**. Do not run migrations, policy activation or seeds against the existing private development database. The schedule `DATABASE_URL` may continue to use its existing read-only connection; a separate auth database is supported. The existing Alembic chain creates empty foundation tables in a new database as well as the auth schema; those empty tables are unused if schedule reads use a different database.

```powershell
uv --directory backend sync --locked
npm.cmd --prefix frontend ci

# Generate a hash interactively. The passcode is never a command-line argument.
$betaHash = uv --directory backend run --no-env-file python -m app.student_auth
$epoch = uv --directory backend run --no-env-file python -c "import secrets; print(secrets.token_urlsafe(32))"
$closing = [DateTimeOffset]::UtcNow.AddDays(7).ToString('o')

# Read URLs privately instead of putting passwords into shell history.
function Read-PrivateValue([string]$Prompt) {
    $privateValue = Read-Host $Prompt -AsSecureString
    [Net.NetworkCredential]::new('', $privateValue).Password
}
$runtimeUrl = Read-PrivateValue 'Runtime URL for the NEW auth database'
```

Have an administrator create the **new** database and roles using your existing PostgreSQL workflow. Apply the reviewed migration to that new database only:

```powershell
$env:MIGRATION_DATABASE_URL = Read-PrivateValue 'Migration URL for the NEW auth database'
try { uv --directory backend run --no-env-file alembic upgrade head }
finally { Remove-Item Env:MIGRATION_DATABASE_URL -ErrorAction SilentlyContinue }
```

The runtime role must be LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE and not own either schema or have broad inherited roles. For example, an administrator can create the role interactively with `CREATE ROLE intervella_student_auth LOGIN;` then `\password intervella_student_auth`. Grant only CONNECT on the chosen auth database and these schema/table privileges:

```sql
GRANT USAGE ON SCHEMA student_auth TO intervella_student_auth;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON student_auth.session, student_auth.attempt TO intervella_student_auth;
GRANT SELECT ON student_auth.control TO intervella_student_auth;
-- FOR SHARE requires UPDATE on a column; id is fixed to 1 by a CHECK constraint.
GRANT UPDATE (id) ON student_auth.control TO intervella_student_auth;
```

Do not grant classroom access to this role, schema CREATE, policy-column UPDATE, control INSERT/DELETE, ownership or administrative roles. The schedule connection retains its existing read-only privileges. The activation administrator needs auth-schema USAGE, control SELECT/UPDATE and session DELETE; it is not needed by the web server. PostgreSQL regression tests exercise these documented minimum runtime grants.

Create private runtime configuration only if it does not already exist. Single-quote secret values in the dotenv file so `$` in scrypt hashes or URLs remains literal; URL-encode database-password special characters:

```powershell
if (Test-Path -LiteralPath .env.student) { throw 'Review existing .env.student; do not overwrite it.' }
$lines = @(
    'STUDENT_AUTH_MODE=beta',
    'STUDENT_AUTH_ORIGIN=http://127.0.0.1:5173',
    "STUDENT_AUTH_DATABASE_URL='$runtimeUrl'",
    "STUDENT_AUTH_EPOCH='$epoch'",
    "STUDENT_BETA_PASSWORD_HASH='$betaHash'",
    "STUDENT_BETA_ENDS_AT=$closing",
    'STUDENT_AUTH_TTL_SECONDS=604800'
)
[IO.File]::WriteAllLines((Join-Path (Get-Location) '.env.student'), $lines, [Text.UTF8Encoding]::new($false))
```

Activate the policy explicitly. This clears **all student sessions in that auth store**, not timetable data. Administrator and runtime connection targets must match:

```powershell
$env:STUDENT_AUTH_ADMIN_DATABASE_URL = Read-PrivateValue 'Activation administrator URL for the NEW auth database'
$authFile = (Join-Path (Get-Location) '.env.student').Replace('\', '/')
try { uv --directory backend run --env-file $authFile python -m app.student_auth activate }
finally { Remove-Item Env:STUDENT_AUTH_ADMIN_DATABASE_URL -ErrorAction SilentlyContinue }
.\dev.ps1
```

The absolute auth-file path uses forward slashes for Windows uv compatibility and avoids working-directory ambiguity. The student website is at `http://127.0.0.1:5173`; the separate dashboard remains at `http://127.0.0.1:8765/operator.html` through the existing operator startup workflow. Local tests never need a real passcode, provider account or production credential.

## University setup and mode switching

1. Create/configure a Supabase project manually when authorized; this PR does not provision one. Enable email authentication and configure production SMTP. Modify the Magic Link email template to include `{{ .Token }}` so users receive a code. Set appropriate OTP expiry and delivery rate limits; configure Site URL/allowed redirects to exact trusted app origins even though this flow uses typed codes, not link redirects.
2. Use an asymmetric ES256 or RS256 signing key. Publish standby keys before rotation, allowing Supabase's discovery caches to update. Legacy HS256-only projects are deliberately unsupported. Keep the issuer/project URL and audience consistent.
3. Choose approved exact domains and an explicit eligibility policy. For `approved_metadata`, provision trusted `app_metadata.intervella_eligible=true` through administration; users cannot self-approve via profile metadata. Do not claim current enrollment based on email possession.
4. Generate a server-side Fernet key: `uv --directory backend run --no-env-file python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Capture it directly into a secret manager/private configuration; do not commit, log or send it to the frontend. Set university variables from the table above, `STUDENT_AUTH_MODE=university`, and a newly generated epoch on **all** replacement replicas.
5. Prepare new replicas and enter a maintenance/cutover window. Activate the new policy with the isolated administrator command; this revokes every prior-mode session. Drain stale replicas and route traffic to replicas carrying the new identical configuration. Stale configuration fails closed; there is no university-to-beta fallback. Everyone signs in again.
6. To rotate a beta passcode, generate a new hash/epoch, update replicas and activate. To end/revoke a beta immediately, activate a changed epoch (or enforce a past beta deadline). The explicit activation command also revokes all sessions when run with the same policy. Rolling back to a prior mode still requires activation and a fresh sign-in; deleted sessions do not return.

Supabase refresh tokens are rotated under a PostgreSQL row lock, preventing competing replicas/tabs from renewing the same local session concurrently. Logout revokes the local row first, then attempts provider-local logout; provider downtime cannot restore local access. Rejected provider renewal invalidates the local row. Successful verification is never inferred merely from a decoded JWT or a client-supplied email.

## Deployment checklist

- Confirm IITS/source-owner access and republication authorization separately. Authentication does not make private timetable exports public-authorized.
- Deploy only the secured build. Do not roll back to a pre-authentication public API; use maintenance/network denial while repairing it.
- Serve the student app and `/auth`/`/api` through one HTTPS origin. Set `STUDENT_AUTH_ORIGIN` to that exact origin. Do not enable HTTP loopback configuration on a hosted ingress.
- Terminate TLS at a trusted proxy, block direct public access to the backend, overwrite forwarded headers and configure Uvicorn `--proxy-headers --forwarded-allow-ips` with only actual proxy addresses. Never trust `*`. The app requires HTTPS request scope for hosted sessions; a misconfigured proxy fails closed. Forward the real client IP from trusted proxies for rate limiting, not arbitrary client-supplied headers.
- Enforce request/body/concurrency limits at the edge. For a small beta, start with a bounded Uvicorn worker/concurrency configuration (for example `--limit-concurrency 8` per worker) and monitor safe aggregate failures. Scrypt verification intentionally consumes CPU/memory. Maintain synchronized server clocks.
- Bypass CDN/proxy caching for **both** `/api` and `/auth`, respecting `private, no-store`. Forward cookies and CSRF headers. Keep CORS exact; prefer same-origin with no additional origins.
- Apply a suitable frontend CSP (`script-src 'self'`, trusted styles/assets only, `connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'self'`), HSTS at the HTTPS edge, no referrers on auth pages and no request-body/token logging. Keep Uvicorn access logs disabled as in the existing application lifespan. Do not log passcodes, OTPs, cookies, authorization headers or provider payloads at any intermediary.
- Keep the operator service loopback-only and separately authenticated; never proxy `/ops` onto the public student origin. Keep operator/migration/admin credentials out of student and frontend workers.
- Activate the intended policy before sending traffic. Verify unauthenticated requests to every timetable endpoint are rejected and a valid beta/university session works. Public health checks use `/health/live`; dataset readiness is authenticated.
- Back up auth state privately and keep the encryption key separate. Expired sessions are cleaned on subsequent login; old rate windows are pruned. Operational backups also need retention/deletion rules. After any old backup restore, change epoch and activate before traffic so revoked sessions cannot be resurrected.
- Verify real email delivery, domain/eligibility policy and key-rotation behavior with authorized staging accounts before enabling university mode. These require real configuration and were not performed by automated mocks.

## Tests and known limits

```powershell
.\check.ps1 -Fast
.\check.ps1
uv --directory backend run --no-env-file pytest tests/test_student_auth_unit.py -q
# PostgreSQL focus: TEST_DATABASE_URL must be the existing safe maintenance target.
uv --directory backend run --no-env-file pytest tests/test_student_auth_postgres.py tests/test_http.py --require-postgres -q
npm.cmd --prefix frontend run test:e2e -- student-auth.spec.ts
```

The existing schedule-contract tests explicitly authenticate through a named test fixture; security tests exercise real session storage and the real guard. There is no runtime test/disabled-auth setting. Provider tests use synthetic RSA keys, mocked HTTPS and JWKS, and disposable PostgreSQL databases. Browser tests use intercepted synthetic API responses, with no actual account or email delivery. Existing operator tests run independently. See PR results for final execution totals and screenshots.

A shared beta passcode does not identify individuals and cannot revoke just one friend without retaining a per-session administrative identifier. Rotate it when leaked; revoke all sessions at the end. Friends can share it, and authenticated users can retain screenshots/data they already received. HttpOnly cookies do not eliminate XSS risk. Provider-side revocation/eligibility changes are rechecked at verification and renewal, with access-token expiry bounding ordinary propagation; local policy activation provides immediate new-request revocation across replicas. A request authorized before revocation may already be in flight. Client session checks run every 30 seconds and on focus/visibility, with exact expiry timers and immediate handling of API authentication denial. This is not an institutional enrollment certification or a third-party penetration-test certification.

Password work factors follow an [OWASP-recommended scrypt combination](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt).

Official integration references: [Supabase email OTP](https://supabase.com/docs/guides/auth/auth-email-passwordless), [signing keys and discovery caching](https://supabase.com/docs/guides/auth/signing-keys), [JWT claim reference](https://supabase.com/docs/guides/auth/jwt-fields).
