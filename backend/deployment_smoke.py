"""Read-only timetable smoke checks plus a disposable beta session; no imports/publication."""

import argparse
import getpass
import os
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx


class SmokeError(ValueError):
    pass


def check(condition, code):
    if not condition:
        raise SmokeError(code)


def run_smoke(client: httpx.Client, passcode: str):
    check(client.base_url.scheme == "https", "https_required")
    page = client.get("/")
    check(page.status_code == 200 and "Intervella" in page.text, "student_page")
    check(
        "frame-ancestors 'none'" in page.headers.get("content-security-policy", ""),
        "security_headers",
    )
    check(client.get("/health/live").status_code == 200, "liveness")
    paths = [
        "/api/v1/status",
        "/api/v1/buildings",
        "/api/v1/availability",
        "/api/v1/room-search",
        "/api/v1/rooms/1",
        "/api/v1/rooms/1/schedule",
        "/api/v1/buildings/SYN-DEMO/schedule",
        "/health/ready",
        "/api//v1/status",
        "/ops/health",
        "/operator.html",
    ]
    for path in paths:
        response = client.get(path)
        check(response.status_code == 401, "anonymous_boundary")
        check("no-store" in response.headers.get("cache-control", ""), "private_cache")
    state = client.get("/auth/session")
    check(state.status_code == 200 and state.json().get("mode") == "beta", "beta_mode")
    check(state.json().get("authenticated") is False, "anonymous_session")
    headers = {"Origin": str(client.base_url).rstrip("/"), "X-Student-Request": "1"}
    check(
        client.post(
            "/auth/beta", json={"passcode": "incorrect-smoke-passcode"}, headers=headers
        ).status_code
        == 401,
        "wrong_passcode",
    )
    response = client.post("/auth/beta", json={"passcode": passcode}, headers=headers)
    check(response.status_code == 200, "beta_login")
    cookie = response.headers.get("set-cookie", "")
    check(
        all(
            part in cookie
            for part in [
                "__Host-intervella_student=",
                "Secure",
                "HttpOnly",
                "SameSite=lax",
                "Path=/",
            ]
        ),
        "secure_cookie",
    )
    try:
        state = client.get("/auth/session").json()
        check(state.get("authenticated") is True and bool(state.get("csrf")), "session_restore")
        buildings = client.get("/api/v1/buildings").json()["data"]
        check(
            bool(buildings) and all(b["code"] == "SYN-DEMO" for b in buildings),
            "synthetic_inventory",
        )
        status = client.get("/api/v1/status").json()
        start = datetime.fromisoformat(status["period"]["start"].replace("Z", "+00:00"))
        day = start.astimezone(ZoneInfo("America/Toronto")).date().isoformat()
        check(status["freshness"] in {"fresh", "stale"}, "freshness_metadata")
        search = client.get(
            "/api/v1/availability", params={"start": start.isoformat(), "duration_minutes": 30}
        )
        check(search.status_code == 200 and bool(search.json()["data"]), "availability")
        check(search.json()["meta"]["dataset_id"] == status["dataset_id"], "dataset_consistency")
        room = search.json()["data"][0]["room_id"]
        workflows: list[tuple[str, dict[str, str]]] = [
            (f"/api/v1/rooms/{room}", {}),
            (f"/api/v1/rooms/{room}/schedule", {"date": day}),
            ("/api/v1/buildings/SYN-DEMO/schedule", {"date": day}),
            ("/api/v1/room-search", {"start": start.isoformat(), "duration_minutes": "30"}),
        ]
        for path, params in workflows:
            check(client.get(path, params=params).status_code == 200, "authenticated_workflow")
        check(client.get("/ops/health").status_code == 404, "operator_excluded")
    finally:
        state_response = client.get("/auth/session")
        if state_response.status_code == 200 and state_response.json().get("csrf"):
            csrf = state_response.json()["csrf"]
            check(
                client.post(
                    "/auth/logout", json={}, headers=headers | {"X-CSRF-Token": csrf}
                ).status_code
                == 200,
                "logout",
            )
    check(client.get("/api/v1/status").status_code == 401, "logout_revocation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    args = parser.parse_args()
    parsed = urlsplit(args.origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        parser.error(
            "Use an exact HTTPS staging origin without credentials, path or trailing slash"
        )
    passcode = os.getenv("INTERVELLA_SMOKE_PASSCODE") or getpass.getpass("Staging beta passcode: ")
    try:
        with httpx.Client(base_url=args.origin, timeout=20, follow_redirects=False) as client:
            run_smoke(client, passcode)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        print("Staging smoke FAILED. Check configuration, publication and server request IDs.")
        return 1
    print(
        "Staging smoke passed: HTTPS, private APIs, beta login, synthetic search/calendars, logout."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
