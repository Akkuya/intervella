"""Supabase email-code exchange; provider credentials never reach browser storage."""

import json
from datetime import UTC, datetime

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.errors import APIError
from app.student_auth.config import AuthConfig


class UniversityProvider:
    def __init__(self, config: AuthConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=5, follow_redirects=False)
        self.keys = jwt.PyJWKClient(
            f"{config.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_jwk_set=True,
            cache_keys=False,
            lifespan=60,
            timeout=5,
        )
        self.cipher = Fernet(config.encryption_key.encode())

    def call(self, method: str, path: str, *, body=None, token=None):
        headers = {"apikey": self.config.supabase_key}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.client.request(
                method, f"{self.config.supabase_url}/auth/v1/{path}", headers=headers, json=body
            )
            if response.status_code >= 500 or response.status_code == 429:
                raise APIError(
                    503, "auth_unavailable", "Sign-in service is temporarily unavailable."
                )
            if not response.is_success:
                raise APIError(
                    401, "invalid_signin", "Sign-in was not accepted. Request a new code."
                )
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise APIError(
                503, "auth_unavailable", "Sign-in service is temporarily unavailable."
            ) from None

    def email(self, email: str):
        if not isinstance(email, str):
            raise APIError(403, "email_not_eligible", "Use an approved university email address.")
        value = email.strip().lower()
        if (
            len(value) > 254
            or value.count("@") != 1
            or not value.split("@")[0]
            or any(c.isspace() or ord(c) < 33 for c in value)
            or value.split("@")[1] not in self.config.domains
        ):
            raise APIError(
                403,
                "email_not_eligible",
                "Use an address from an approved university email domain.",
            )
        return value

    def send(self, email: str):
        self.call("POST", "otp", body={"email": self.email(email), "create_user": True})

    def verify_token(self, token: str):
        try:
            if len(token) > 16384:
                raise ValueError
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") not in {"ES256", "RS256"}
                or not isinstance(header.get("kid"), str)
                or not header["kid"]
                or len(header["kid"]) > 128
            ):
                raise ValueError
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["ES256", "RS256"],
                issuer=f"{self.config.supabase_url}/auth/v1",
                audience=self.config.audience,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "email", "role"]},
            )
            if (
                claims["role"] != "authenticated"
                or not isinstance(claims["sub"], str)
                or not claims["sub"]
                or len(claims["sub"]) > 256
            ):
                raise ValueError
            self.email(claims["email"])
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise APIError(
                401, "invalid_signin", "The sign-in token is invalid or expired."
            ) from None

    def accept(self, bundle, expected_email=None):
        try:
            token, refresh = bundle["access_token"], bundle["refresh_token"]
            if (
                not isinstance(token, str)
                or not isinstance(refresh, str)
                or not 1 <= len(refresh) <= 4096
            ):
                raise ValueError
            claims = self.verify_token(token)
            if expected_email is not None and claims["email"].lower() != expected_email:
                raise APIError(401, "invalid_signin", "Sign-in was not accepted.")
            # getUser is authoritative for confirmation/eligibility; user_metadata is user-writable.
            user = self.call("GET", "user", token=token)
            if (
                not user.get("email_confirmed_at")
                or user.get("id") != claims["sub"]
                or user.get("email", "").lower() != claims["email"].lower()
            ):
                raise APIError(
                    403, "email_not_verified", "A verified university email is required."
                )
            self.email(user["email"])
            if (
                self.config.eligibility == "approved_metadata"
                and user.get("app_metadata", {}).get("intervella_eligible") is not True
            ):
                raise APIError(
                    403, "email_not_eligible", "This account is not approved for Intervella access."
                )
            encrypted = self.cipher.encrypt(
                json.dumps({"access": token, "refresh": refresh}).encode()
            ).decode()
            return {
                "subject": claims["sub"],
                "access_expires_at": datetime.fromtimestamp(claims["exp"], UTC),
                "provider_tokens": encrypted,
            }
        except (KeyError, TypeError, ValueError):
            raise APIError(401, "invalid_signin", "Sign-in was not accepted.") from None

    def verify(self, email: str, code: str):
        email = self.email(email)
        return self.accept(
            self.call("POST", "verify", body={"email": email, "token": code, "type": "email"}),
            expected_email=email,
        )

    def renew(self, encrypted: str):
        try:
            tokens = json.loads(self.cipher.decrypt(encrypted.encode()))
            return self.accept(
                self.call(
                    "POST",
                    "token?grant_type=refresh_token",
                    body={"refresh_token": tokens["refresh"]},
                )
            )
        except (ValueError, KeyError, TypeError, InvalidToken):
            raise APIError(401, "invalid_signin", "Your sign-in session has expired.") from None

    def logout(self, encrypted: str):
        try:
            tokens = json.loads(self.cipher.decrypt(encrypted.encode()))
            self.call("POST", "logout?scope=local", token=tokens["access"])
        except Exception:
            # Local revocation happens first and remains authoritative if the provider is down.
            pass

    def close(self):
        self.client.close()
