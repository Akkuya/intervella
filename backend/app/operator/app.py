"""Loopback-only operator service. Never mount this app in the public API."""

import hashlib
import hmac
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.db import create_db_engine
from app.ingest.local import MAX_HTML_BYTES, IngestionError, load_directory
from app.ingest.pipeline import import_directory, publish_dataset
from app.operator.service import compare, health


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_reason: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    review_acknowledged: bool = False


class PublicationInput(ReviewInput):
    confirm_dataset_id: str
    baseline_dataset_id: str | None


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
}

ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765"}
COOKIE = "utsc_operator_session"


def create_operator_app(*, engine=None, secret=None, storage=None):
    secret = secret or os.environ.get("OPERATOR_SECRET", "")
    if len(secret) < 32:
        raise ValueError("OPERATOR_SECRET must contain at least 32 characters")
    root = Path(storage or Path(__file__).resolve().parents[2] / "data" / "operator")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    sessions, batches = {}, {}
    attempts = []
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    def db():
        nonlocal engine
        if engine is None:
            engine = create_db_engine("INGESTION_DATABASE_URL")
        return engine

    def cleanup():
        now = time.time()
        for path in root.glob("ops-*"):
            if (
                re.fullmatch(r"ops-[0-9a-f]{32}", path.name)
                and not path.is_symlink()
                and path.is_dir()
                and now - path.stat().st_mtime > 3600
            ):
                shutil.rmtree(path)
                batches.pop(path.name[4:], None)
        for key in list(sessions):
            if sessions[key]["expires"] < now:
                sessions.pop(key)

    def error(code, status=400, report=None):
        return JSONResponse(
            {"error": {"code": code, "report": report}},
            status_code=status,
            headers=SECURITY_HEADERS,
        )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        cleanup()
        privileged = request.url.path.startswith("/ops/")
        login = request.url.path == "/ops/login"
        session = sessions.get(request.cookies.get(COOKIE, ""))
        if privileged and not login and session is None:
            return error("authentication_required", 401)
        if privileged and request.method not in {"GET", "HEAD"}:
            if request.headers.get("origin") not in ORIGINS:
                return error("untrusted_origin", 403)
            if not login and not hmac.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), session["csrf"].encode()
            ):
                return error("csrf_rejected", 403)
            limit = 4096 if login else MAX_HTML_BYTES
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return error("upload_too_large", 413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(IngestionError)
    async def ingestion_error(request, exc):
        return error(exc.code, 409, exc.report)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error("invalid_request")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error("database_unavailable", 503)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return error("invalid_request")

    @app.post("/ops/login")
    async def login(request: Request):
        now = time.time()
        attempts[:] = [t for t in attempts if now - t < 60]
        if len(attempts) >= 10:
            return error("login_rate_limited", 429)
        attempts.append(now)
        payload = await request.json()
        supplied = payload.get("secret", "") if isinstance(payload, dict) else ""
        if not isinstance(supplied, str) or not hmac.compare_digest(
            supplied.encode(), secret.encode()
        ):
            return error("authentication_required", 401)
        if len(sessions) >= 16:
            return error("session_limit", 429)
        token = secrets.token_urlsafe(32)
        sessions[token] = {"csrf": secrets.token_urlsafe(32), "expires": now + 8 * 3600}
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            COOKIE, token, httponly=True, samesite="strict", max_age=8 * 3600, path="/ops"
        )
        return response

    @app.get("/ops/session")
    def session(request: Request):
        return {"csrf": sessions[request.cookies[COOKIE]]["csrf"]}

    @app.post("/ops/logout")
    def logout(request: Request):
        sessions.pop(request.cookies[COOKIE], None)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/ops")
        return response

    @app.get("/ops/health")
    def data_health():
        return health(db())

    @app.post("/ops/batches")
    def new_batch():
        if len(list(root.glob("ops-*"))) >= 5:
            return error("upload_batch_limit", 429)
        key = uuid4().hex
        path = root / f"ops-{key}"
        path.mkdir(mode=0o700)
        batches[key] = {
            "path": path,
            "dataset_id": None,
            "preview_hash": None,
            "lock": RLock(),
        }
        return {"batch_id": key}

    def batch(key):
        if key not in batches or not batches[key]["path"].is_dir():
            raise IngestionError("batch_not_found")
        return batches[key]

    @app.put("/ops/batches/{key}/files/{name}")
    async def upload(key: str, name: str, request: Request):
        body = await request.body()
        item = batch(key)
        with item["lock"]:
            if item["dataset_id"]:
                raise IngestionError("candidate_inputs_locked")
            if name != "manifest.json" and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html", name
            ):
                return error("invalid_filename")
            files = list(item["path"].iterdir())
            if name not in {f.name for f in files} and len(files) >= 8:
                return error("too_many_files")
            if name == "manifest.json" and len(body) > 1024 * 1024:
                return error("manifest_too_large", 413)
            if b"\x00" in body:
                return error("invalid_file")
            target = item["path"] / name
            target.write_bytes(body)
            item["preview_hash"] = None
            return {"file": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    @app.delete("/ops/batches/{key}")
    def discard(key: str):
        item = batch(key)
        with item["lock"]:
            shutil.rmtree(item["path"])
            batches.pop(key)
            return {"discarded": True}

    @app.post("/ops/batches/{key}/preview")
    def preview(key: str):
        item = batch(key)
        with item["lock"]:
            bundle = load_directory(item["path"])
            item["preview_hash"] = bundle.input_hash
            return {
                "summary": bundle.report(),
                "sources": list(bundle.sources),
                "comparison": compare(db(), bundle),
                "candidate_id": item["dataset_id"],
            }

    @app.post("/ops/batches/{key}/stage")
    async def stage(key: str, request: Request):
        data = ReviewInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"]:
            bundle = load_directory(item["path"])
            if item["preview_hash"] != bundle.input_hash:
                raise IngestionError("preview_required")
            reason = data.review_reason
            if reason and data.review_acknowledged is not True:
                raise IngestionError("review_acknowledgment_required")
            result = import_directory(db(), item["path"], review_reason=reason)
            item["dataset_id"] = result["dataset_id"]
            return result

    @app.post("/ops/batches/{key}/publish")
    async def publish(key: str, request: Request):
        data = PublicationInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"]:
            if not item["dataset_id"] or data.confirm_dataset_id != item["dataset_id"]:
                raise IngestionError("candidate_confirmation_required")
            reason = data.review_reason
            if reason and data.review_acknowledged is not True:
                raise IngestionError("review_acknowledgment_required")
            result = publish_dataset(
                db(),
                UUID(item["dataset_id"]),
                review_reason=reason,
                expected_baseline=data.baseline_dataset_id or "",
            )
            current = health(db())
            if not current["active"] or current["active"]["dataset_id"] != item["dataset_id"]:
                raise IngestionError("publication_superseded")
            return {"publication": result, "health": current}

    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist-operator"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "operator.html").is_file():
            return error("operator_build_required", 503)
        return FileResponse(dist / "operator.html")

    return app
