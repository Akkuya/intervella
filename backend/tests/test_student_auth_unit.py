from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from app.errors import APIError
from app.student_auth.config import AuthConfig
from app.student_auth.service import password_hash, verify_password
from app.student_auth.university import UniversityProvider

PASSWORD = "synthetic-only-beta-passcode"
EPOCH = "synthetic-test-revocation-epoch-0001"


def beta_config(**changes):
    values = dict(
        mode="beta",
        origin="https://student.test",
        epoch=EPOCH,
        password_hash=password_hash(PASSWORD),
        beta_ends_at=datetime.now(UTC) + timedelta(days=7),
    )
    return AuthConfig(**(values | changes))


def university_config(**changes):
    values = dict(
        mode="university",
        origin="https://student.test",
        epoch=EPOCH,
        supabase_url="https://provider.test",
        supabase_key="sb_publishable_synthetic",
        encryption_key=Fernet.generate_key().decode(),
        domains=("university.test",),
        eligibility="verified_email",
    )
    return AuthConfig(**(values | changes))


def test_password_configuration_and_no_public_mode():
    value = password_hash(PASSWORD)
    assert PASSWORD not in value and verify_password(PASSWORD, value)
    assert not verify_password("wrong", value)
    for config in [
        dict(mode="public"),
        dict(origin="http://student.test"),
        dict(epoch="short"),
        dict(password_hash=PASSWORD),
        dict(beta_ends_at=None),
    ]:
        with pytest.raises(ValueError):
            beta_config(**config)
    assert not beta_config(origin="http://127.0.0.1:5173").secure
    for config in [
        dict(domains=()),
        dict(eligibility=""),
        dict(supabase_url="http://provider.test"),
        dict(supabase_key="sb_secret_never-use-this"),
        dict(encryption_key="bad"),
    ]:
        with pytest.raises(ValueError):
            university_config(**config)


@pytest.fixture
def signed_provider():
    config = university_config()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(datetime.now(UTC).timestamp())
    claims = dict(
        sub="synthetic-user",
        role="authenticated",
        email="friend@university.test",
        iss="https://provider.test/auth/v1",
        aud="authenticated",
        iat=now,
        exp=now + 600,
    )
    calls = []
    user = dict(
        id="synthetic-user",
        email="friend@university.test",
        email_confirmed_at="2026-10-01T00:00:00Z",
        app_metadata={},
    )

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=user)

    provider = UniversityProvider(config, httpx.Client(transport=httpx.MockTransport(respond)))
    provider.keys = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-key"})
    yield provider, key, claims, token, user, calls
    provider.close()


@pytest.mark.parametrize(
    "change",
    [
        dict(iss="https://evil.test"),
        dict(aud="other"),
        dict(exp=1),
        dict(iat=4102444800),
        dict(role="service_role"),
        dict(sub=""),
        dict(email="friend@evil.test"),
    ],
)
def test_provider_rejects_invalid_claims(signed_provider, change):
    provider, key, claims, _, _, _ = signed_provider
    token = jwt.encode(claims | change, key, algorithm="RS256", headers={"kid": "synthetic-key"})
    with pytest.raises(APIError):
        provider.verify_token(token)


def test_provider_rejects_forgery_and_unsigned_tokens(signed_provider):
    provider, _, claims, _, _, _ = signed_provider
    bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in [
        "malformed",
        jwt.encode(claims, bad_key, algorithm="RS256", headers={"kid": "synthetic-key"}),
        jwt.encode(
            claims,
            "synthetic-attacker-shared-secret-0000000000000000",
            algorithm="HS256",
            headers={"kid": "synthetic-key"},
        ),
        jwt.encode(claims, "", algorithm="none"),
    ]:
        with pytest.raises(APIError):
            provider.verify_token(token)


def test_provider_confirmation_and_server_controlled_eligibility(signed_provider):
    provider, _, _, token, user, calls = signed_provider
    bundle = {"access_token": token, "refresh_token": "synthetic-refresh-not-a-real-token"}
    result = provider.accept(bundle)
    assert result["subject"] == "synthetic-user"
    assert token not in result["provider_tokens"]
    assert calls[-1].url.path == "/auth/v1/user"
    user["email_confirmed_at"] = None
    with pytest.raises(APIError, match="verified"):
        provider.accept(bundle)
    user["email_confirmed_at"] = "2026-10-01T00:00:00Z"
    provider.config = replace(provider.config, eligibility="approved_metadata")
    user["user_metadata"] = {"intervella_eligible": True}
    with pytest.raises(APIError):
        provider.accept(bundle)
    user["app_metadata"]["intervella_eligible"] = True
    assert provider.accept(bundle)["subject"] == "synthetic-user"


def test_jwks_cache_refreshes_for_new_signing_key(monkeypatch):
    import json

    config = university_config()
    provider = UniversityProvider(config)
    keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]
    jwks = {
        "keys": [
            json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys[0].public_key()))
            | {"kid": "old", "use": "sig", "alg": "RS256"}
        ]
    }
    fetched = []

    def fetch():
        fetched.append(True)
        provider.keys.jwk_set_cache.put(jwks)
        return jwks

    monkeypatch.setattr(provider.keys, "fetch_data", fetch)
    now = int(datetime.now(UTC).timestamp())
    claims = dict(
        sub="synthetic",
        role="authenticated",
        email="a@university.test",
        iss="https://provider.test/auth/v1",
        aud="authenticated",
        iat=now,
        exp=now + 600,
    )
    old = jwt.encode(claims, keys[0], algorithm="RS256", headers={"kid": "old"})
    provider.verify_token(old)
    provider.verify_token(old)
    assert len(fetched) == 1
    jwks = {
        "keys": [
            json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys[1].public_key()))
            | {"kid": "new", "use": "sig", "alg": "RS256"}
        ]
    }
    new = jwt.encode(claims, keys[1], algorithm="RS256", headers={"kid": "new"})
    provider.verify_token(new)
    assert len(fetched) == 2
    with pytest.raises(APIError):
        provider.verify_token(old)
    provider.close()


def test_unconfigured_api_fails_closed_and_liveness_is_sanitized(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.student_auth.service import StudentAuth

    for name in list(__import__("os").environ):
        if name.startswith("STUDENT_"):
            monkeypatch.delenv(name)
    app = create_app()
    assert app.state.student_auth.config is None
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        for path in ["/api/v1/status", "/api/v1/rooms/1", "/health/ready", "/auth/session"]:
            response = client.get(path)
            assert response.status_code == 503
            assert "dataset_id" not in response.text
    app = create_app()
    app.state.student_auth = StudentAuth(beta_config())
    with TestClient(app, base_url="https://student.test") as client:
        assert client.get("/api/v1/rooms/1").status_code == 401
    with TestClient(app) as client:
        assert client.get("/api/v1/status").status_code == 403
    app.state.student_auth = StudentAuth(beta_config(origin="http://127.0.0.1:5173"))
    with TestClient(app, base_url="http://127.0.0.1:5173", client=("192.0.2.1", 1234)) as client:
        assert client.get("/api/v1/status").status_code == 403


def test_csrf_header_is_validated_before_constant_time_comparison():
    from starlette.requests import Request

    from app.student_auth.service import StudentAuth

    auth = StudentAuth(beta_config())
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("student.test", 443),
            "path": "/auth/logout",
            "client": ("192.0.2.1", 1234),
            "headers": [
                (b"origin", b"https://student.test"),
                (b"x-student-request", b"1"),
                (b"content-type", b"application/json"),
                (b"x-csrf-token", b"\xe9" * 64),
            ],
        }
    )
    with pytest.raises(APIError) as error:
        auth.csrf(request, {"csrf": "a" * 64})
    assert error.value.status_code == 403


def test_verified_token_must_match_requested_email(signed_provider):
    provider, _, _, token, _, _ = signed_provider
    with pytest.raises(APIError):
        provider.accept(
            {"access_token": token, "refresh_token": "synthetic"},
            expected_email="other@university.test",
        )


def test_student_cookie_does_not_authenticate_operator(tmp_path):
    from fastapi.testclient import TestClient

    from app.operator.app import create_operator_app

    app = create_operator_app(secret="synthetic-operator-secret-value-000000", storage=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get(
            "/ops/health", headers={"Cookie": "intervella_student_local=synthetic-student-cookie"}
        )
        assert response.status_code == 401
