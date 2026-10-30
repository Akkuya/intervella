"""Explicit student-auth configuration. No disabled or fallback provider."""

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    origin: str
    epoch: str = field(repr=False)
    password_hash: str = field(default="", repr=False)
    beta_ends_at: datetime | None = None
    ttl_seconds: int = 604800
    supabase_url: str = ""
    supabase_key: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)
    domains: tuple[str, ...] = ()
    eligibility: str = ""
    audience: str = "authenticated"

    def __post_init__(self):
        p = urlsplit(self.origin)
        if p.port is not None and not 1 <= p.port <= 65535:
            raise ValueError("Invalid student origin port")
        if (
            self.mode not in {"beta", "university"}
            or len(self.epoch) < 32
            or not 300 <= self.ttl_seconds <= 604800
            or not p.hostname
            or p.path
            or p.query
            or p.fragment
            or p.username is not None
            or p.password is not None
            or self.origin != f"{p.scheme}://{p.netloc.lower()}"
            or "*" in self.origin
            or any(c.isspace() for c in self.origin)
            or p.scheme not in {"http", "https"}
            or (p.scheme == "http" and p.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("Invalid student authentication configuration")
        if self.mode == "beta":
            parse_password_hash(self.password_hash)
            if self.beta_ends_at is None or self.beta_ends_at.utcoffset() is None:
                raise ValueError("STUDENT_BETA_ENDS_AT must be a timezone-aware timestamp")
        else:
            u = urlsplit(self.supabase_url)
            if (
                u.scheme != "https"
                or not u.hostname
                or u.path
                or u.query
                or u.fragment
                or u.username
                or u.password
                or not self.supabase_key
                or not self.supabase_key.startswith("sb_publishable_")
                or not self.domains
                or any(
                    not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}", d)
                    for d in self.domains
                )
                or self.eligibility not in {"verified_email", "approved_metadata"}
                or not self.audience
            ):
                raise ValueError("Invalid university authentication configuration")
            try:
                if len(base64.urlsafe_b64decode(self.encryption_key)) != 32:
                    raise ValueError
            except Exception:
                raise ValueError("Invalid university encryption key") from None

    @property
    def secure(self):
        return urlsplit(self.origin).scheme == "https"

    @property
    def cookie(self):
        return "__Host-intervella_student" if self.secure else "intervella_student_local"

    @property
    def fingerprint(self):
        return hashlib.sha256(
            json.dumps(self.__dict__, sort_keys=True, default=str).encode()
        ).hexdigest()

    @classmethod
    def from_environment(cls):
        return cls(
            beta_ends_at=datetime.fromisoformat(os.environ["STUDENT_BETA_ENDS_AT"])
            if os.getenv("STUDENT_BETA_ENDS_AT")
            else None,
            mode=os.getenv("STUDENT_AUTH_MODE", ""),
            origin=os.getenv("STUDENT_AUTH_ORIGIN", ""),
            epoch=os.getenv("STUDENT_AUTH_EPOCH", ""),
            password_hash=os.getenv("STUDENT_BETA_PASSWORD_HASH", ""),
            ttl_seconds=int(os.getenv("STUDENT_AUTH_TTL_SECONDS", "604800")),
            supabase_url=os.getenv("STUDENT_SUPABASE_URL", "").rstrip("/"),
            supabase_key=os.getenv("STUDENT_SUPABASE_PUBLISHABLE_KEY", ""),
            encryption_key=os.getenv("STUDENT_AUTH_ENCRYPTION_KEY", ""),
            domains=tuple(
                d.strip().lower()
                for d in os.getenv("STUDENT_AUTH_EMAIL_DOMAINS", "").split(",")
                if d.strip()
            ),
            eligibility=os.getenv("STUDENT_AUTH_ELIGIBILITY", ""),
            audience=os.getenv("STUDENT_SUPABASE_AUDIENCE", "authenticated"),
        )


def parse_password_hash(value: str):
    try:
        algorithm, salt, digest = value.split("$")
        if algorithm != "scrypt-v1":
            raise ValueError
        salt_bytes, digest_bytes = bytes.fromhex(salt), bytes.fromhex(digest)
        if len(salt_bytes) != 16 or len(digest_bytes) != 32:
            raise ValueError
        return salt_bytes, digest_bytes
    except (ValueError, TypeError):
        raise ValueError("STUDENT_BETA_PASSWORD_HASH must be a generated scrypt-v1 hash") from None
