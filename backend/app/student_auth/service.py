"""Shared PostgreSQL-backed student sessions and abuse limits."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from threading import RLock

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db import create_db_engine
from app.errors import APIError
from app.student_auth.config import AuthConfig, parse_password_hash
from app.student_auth.tables import attempts, control, sessions
from app.student_auth.university import UniversityProvider


def password_hash(password: str):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a passcode of 12–256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024 * 1024, dklen=32
    )
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str):
    salt, digest = parse_password_hash(stored)
    actual = hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024 * 1024, dklen=32
    )
    return hmac.compare_digest(actual, digest)


def token_id(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


class StudentAuth:
    def __init__(self, config: AuthConfig | None = None, engine=None, provider=None, clock=None):
        try:
            self.config = config or AuthConfig.from_environment()
        except ValueError:
            self.config = None
        self._initialization = RLock()
        self.engine = engine
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))

    def configured(self):
        if self.config is None:
            raise APIError(503, "auth_unavailable", "Student sign-in is not configured.")
        return self.config

    def db(self):
        self.configured()
        with self._initialization:
            if self.engine is None:
                self.engine = create_db_engine("STUDENT_AUTH_DATABASE_URL")
        return self.engine

    def policy(self, conn, lock=False):
        stmt = select(control.c.policy).where(control.c.id == 1)
        if lock:
            stmt = stmt.with_for_update(read=True)
        if conn.scalar(stmt) != self.configured().fingerprint:
            raise APIError(
                503, "auth_unavailable", "Student sign-in policy is not active on this server."
            )

    def university(self):
        config = self.configured()
        if config.mode != "university":
            raise APIError(404, "not_found", "Sign-in method is unavailable.")
        with self._initialization:
            if self.provider is None:
                self.provider = UniversityProvider(config)
        return self.provider

    def transport(self, request):
        config = self.configured()
        if config.secure and request.url.scheme != "https":
            raise APIError(403, "https_required", "Use the HTTPS sign-in address.")
        if not config.secure and (
            not request.client or request.client.host not in {"127.0.0.1", "::1"}
        ):
            raise APIError(403, "local_only", "Local sign-in is limited to loopback access.")

    def origin(self, request):
        self.transport(request)
        config = self.configured()
        if (
            request.headers.get("origin") != config.origin
            or request.headers.get("sec-fetch-site") == "cross-site"
            or request.headers.get("x-student-request") != "1"
            or request.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            raise APIError(403, "csrf_rejected", "Reload Intervella and try again.")

    def limit(self, request, purpose: str, email: str = ""):
        config = self.configured()
        now = self.clock()
        window = int(now.timestamp()) // 900
        ip = request.client.host if request.client else "unknown"
        limits = [(f"{purpose}:ip:{ip}", 10), (f"{purpose}:global", 100)]
        if email:
            limits.append((f"{purpose}:email:{email.lower()}", 5))
        blocked = False
        with self.db().begin() as conn:
            self.policy(conn, lock=True)
            conn.execute(delete(attempts).where(attempts.c.window < window - 96))
            for raw, limit in limits:
                key = hmac.new(config.epoch.encode(), raw.encode(), hashlib.sha256).hexdigest()
                stmt = insert(attempts).values(key=key, window=window, count=1)
                count = conn.scalar(
                    stmt.on_conflict_do_update(
                        index_elements=[attempts.c.key, attempts.c.window],
                        set_={"count": attempts.c.count + 1},
                    ).returning(attempts.c.count)
                )
                blocked = blocked or count > limit
        if blocked:
            raise APIError(
                429, "rate_limited", "Too many sign-in attempts. Try again in 15 minutes."
            )

    def create(self, request, identity=None):
        config = self.configured()
        now = self.clock()
        identity = identity or {"subject": "beta"}
        end = now + timedelta(seconds=config.ttl_seconds)
        if config.mode == "beta":
            end = min(end, config.beta_ends_at)
            if end <= now:
                raise APIError(403, "beta_closed", "This private beta has ended.")
        token = secrets.token_urlsafe(32)
        with self.db().begin() as conn:
            self.policy(conn, lock=True)
            conn.execute(delete(sessions).where(sessions.c.expires_at <= now))
            # Rotate any existing browser session rather than accepting client-selected IDs.
            old = request.cookies.get(config.cookie)
            if old:
                conn.execute(delete(sessions).where(sessions.c.id == token_id(old)))
            conn.execute(
                insert(sessions).values(
                    id=token_id(token),
                    policy=config.fingerprint,
                    csrf=secrets.token_hex(32),
                    expires_at=end,
                    **identity,
                )
            )
        return token

    def lookup(self, request, *, conn=None, lock=False):
        self.transport(request)
        config = self.configured()
        token = request.cookies.get(config.cookie, "")
        if not token or len(token) > 128:
            raise APIError(401, "authentication_required", "Sign in to continue.")
        stmt = select(sessions).where(
            sessions.c.id == token_id(token),
            sessions.c.policy == config.fingerprint,
            sessions.c.expires_at > self.clock(),
        )
        if lock:
            stmt = stmt.with_for_update()
        if conn is not None:
            self.policy(conn, lock=True)
            row = conn.execute(stmt).mappings().first()
        else:
            with self.db().connect() as connection:
                self.policy(connection)
                row = connection.execute(stmt).mappings().first()
        if row is None:
            raise APIError(401, "authentication_required", "Your sign-in session has expired.")
        return row

    def require(self, request):
        row = self.lookup(request)
        if row["access_expires_at"] is not None and row["access_expires_at"] <= self.clock():
            raise APIError(401, "authentication_required", "Renew your sign-in session.")

    def state(self, row):
        config = self.configured()
        end = min(row["expires_at"], row["access_expires_at"] or row["expires_at"])
        return {
            "mode": config.mode,
            "authenticated": end > self.clock(),
            "expires_at": end.isoformat(),
            "csrf": row["csrf"],
            "needs_renewal": row["access_expires_at"] is not None
            and end < self.clock() + timedelta(seconds=60),
        }

    def csrf(self, request, row):
        self.origin(request)
        token = request.headers.get("x-csrf-token", "")
        if not re.fullmatch(r"[a-f0-9]{64}", token) or not hmac.compare_digest(token, row["csrf"]):
            raise APIError(403, "csrf_rejected", "Reload Intervella and try again.")

    def renew(self, request):
        try:
            with self.db().begin() as conn:
                row = self.lookup(request, conn=conn, lock=True)
                self.csrf(request, row)
                if self.configured().mode == "university" and row[
                    "access_expires_at"
                ] <= self.clock() + timedelta(seconds=60):
                    identity = self.university().renew(row["provider_tokens"])
                    if identity["subject"] != row["subject"]:
                        raise APIError(401, "invalid_signin", "Sign in again.")
                    conn.execute(
                        update(sessions).where(sessions.c.id == row["id"]).values(**identity)
                    )
                    row = self.lookup(request, conn=conn)
                return self.state(row)
        except APIError as error:
            if error.code in {"invalid_signin", "email_not_eligible", "email_not_verified"}:
                with self.db().begin() as conn:
                    conn.execute(
                        delete(sessions).where(
                            sessions.c.id
                            == token_id(request.cookies.get(self.configured().cookie, ""))
                        )
                    )
            raise

    def logout(self, request):
        self.origin(request)
        try:
            with self.db().begin() as conn:
                row = self.lookup(request, conn=conn, lock=True)
                self.csrf(request, row)
                conn.execute(delete(sessions).where(sessions.c.id == row["id"]))
        except APIError as error:
            if error.status_code == 401:
                return
            raise
        if row["provider_tokens"]:
            self.university().logout(row["provider_tokens"])

    def close(self):
        if self.provider:
            self.provider.close()
        if self.engine:
            self.engine.dispose()


def activate_policy(engine, config):
    """Explicit administrator operation; never invoked by application startup."""
    with engine.begin() as conn:
        conn.execute(select(control).where(control.c.id == 1).with_for_update()).one()
        conn.execute(update(control).where(control.c.id == 1).values(policy=config.fingerprint))
        conn.execute(delete(sessions))
