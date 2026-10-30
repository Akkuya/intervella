import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_routes_preserve_api_paths_and_exclude_operator_build():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert set(config["services"]) == {"student", "api"}
    assert config["git"]["deploymentEnabled"] is False
    student = config["services"]["student"]
    assert student["buildCommand"] == "npm run build"
    assert student["outputDirectory"] == "dist"
    assert student["rewrites"][-1]["destination"] == "/index.html"
    assert config["services"]["api"]["entrypoint"] == "vercel_app:app"
    routes = {item["source"]: item["destination"]["service"] for item in config["rewrites"]}
    assert all(
        routes[prefix + "/:path*"] == "api" for prefix in ["/api", "/auth", "/health", "/ops"]
    )
    assert routes["/operator.html"] == "api"
    assert config["rewrites"][-1] == {"source": "/(.*)", "destination": {"service": "student"}}
    assert "migrat" not in json.dumps(config).lower()
    headers = {h["key"]: h["value"] for h in config["headers"][0]["headers"]}
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_upload_is_default_deny_and_never_allows_private_operations():
    rules = (ROOT / ".vercelignore").read_text().splitlines()
    assert "*" in rules
    allowed = [line for line in rules if line.startswith("!")]
    assert "!backend/app/*.py" in allowed
    assert "!frontend/src/**" in allowed
    assert not any(
        term in line
        for line in allowed
        for term in [
            "operator/",
            "ingest/",
            "data/",
            "migrations",
            "tests/",
            ".env",
            "operator.html",
        ]
    )
    assert "**/.env*" in rules


def test_upload_rules_exclude_synthetic_private_paths(tmp_path):
    import subprocess

    paths = [
        "backend/app/main.py",
        "backend/app/services/availability.py",
        "backend/vercel_app.py",
        "frontend/index.html",
        "frontend/src/App.tsx",
        "frontend/public/assets/intervella.svg",
        "backend/app/operator/main.py",
        "backend/app/ingest/parser.py",
        "backend/data/private.html",
        "backend/migrations/env.py",
        "frontend/operator.html",
        ".env.student",
        "private-manifest.json",
        "frontend/.env.production",
        "backend/app/__pycache__/main.pyc",
    ]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text((ROOT / ".vercelignore").read_text())
    result = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "--no-index", "--stdin", "-z"],
        input="\0".join(paths).encode(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert {name.decode() for name in result.stdout.split(b"\0") if name} == set(paths[6:])


def test_public_build_rejects_operator_and_private_artifacts(tmp_path):
    import pytest

    from verify_public_build import verify_public_build

    (tmp_path / "index.html").write_text("Intervella")
    verify_public_build(tmp_path)
    (tmp_path / "operator.html").write_text("Private operator")
    with pytest.raises(ValueError):
        verify_public_build(tmp_path)
