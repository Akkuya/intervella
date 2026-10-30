"""Loopback-only operator service. Never mount this app in the public API."""

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from contextlib import nullcontext
from datetime import UTC, date, datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.db import create_db_engine
from app.ingest.local import MAX_HTML_BYTES, IngestionError, Manifest, ManifestModel, SourceBuilding, load_directory
from app.ingest.pipeline import import_directory, publish_dataset, publish_datasets
from app.ingest.weekly_load import WeeklyManifest
from app.operator.manifests import analyze_sources
from app.operator.discovery import MAX_BATCH_BYTES, MAX_FILES, discover_sources
from app.operator.coverage import reviewed_windows
from app.operator.profiles import ProfileApproval, ProfileStore, _exclusive
from app.operator.service import compare, health


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_reason: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    review_acknowledged: bool = False


class PublicationInput(ReviewInput):
    confirm_dataset_id: str
    baseline_dataset_id: str | None


class AnalysisInput(ManifestModel):
    start_date: date
    source_format: Literal["daily", "weekly"] | None = None


class ManifestReviewInput(ReviewInput):
    analysis_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_version: int = Field(ge=0, strict=True)
    manifest: dict
    capture_acknowledged: bool = False
    target_acknowledged: bool = False
    windows_acknowledged: bool = False


class DiscoveryInput(ManifestModel):
    year: int | None = Field(default=None, ge=1, le=9998, strict=True)
    years: dict[str, int] = Field(default_factory=dict, max_length=MAX_FILES)
    original_names: dict[str, str] = Field(default_factory=dict, max_length=MAX_FILES)


class MultiPublicationInput(ReviewInput):
    batch_ids: list[str] = Field(min_length=1, max_length=12)
    confirm_dataset_ids: list[str] = Field(min_length=1, max_length=12)
    baseline_dataset_id: str | None


class CoverageProfileInput(ReviewInput):
    analysis_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_version: int = Field(ge=1, strict=True)
    buildings: list[SourceBuilding] = Field(min_length=1, max_length=50)


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
    profiles = ProfileStore(root / "inventory")
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

    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return error("private_storage_unavailable", 503)

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
        if len(list(root.glob("ops-*"))) >= 20:
            return error("upload_batch_limit", 429)
        key = uuid4().hex
        path = root / f"ops-{key}"
        path.mkdir(mode=0o700)
        batches[key] = {
            "path": path,
            "dataset_id": None,
            "preview_hash": None,
            "analysis": None,
            "generation_started": False,
            "generated_hash": None,
            "profile_version": None,
            "children": [],
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
            if item["dataset_id"] or item["children"]:
                raise IngestionError("candidate_inputs_locked")
            if name != "manifest.json" and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html", name
            ):
                return error("invalid_filename")
            files = list(item["path"].iterdir())
            if name not in {f.name for f in files} and len(files) >= MAX_FILES + 1:
                return error("too_many_files")
            if sum(f.stat().st_size for f in files if f.name != name) + len(body) > MAX_BATCH_BYTES:
                return error("upload_too_large", 413)
            if name == "manifest.json" and len(body) > 1024 * 1024:
                return error("manifest_too_large", 413)
            if b"\x00" in body:
                return error("invalid_file")
            target = item["path"] / name
            target.write_bytes(body)
            item["preview_hash"] = None
            item["analysis"] = None
            item["generated_hash"] = None
            return {"file": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    @app.delete("/ops/batches/{key}")
    def discard(key: str):
        item = batch(key)
        with item["lock"]:
            for child in item["children"]:
                if child in batches:
                    discard(child)
            shutil.rmtree(item["path"])
            batches.pop(key)
            return {"discarded": True}

    @app.post("/ops/batches/{key}/discover")
    async def discover(key: str, request: Request):
        data = DiscoveryInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"]:
            if item["dataset_id"] or any(batches.get(k, {}).get("dataset_id") for k in item["children"]):
                raise IngestionError("candidate_inputs_locked")
            for child in item["children"]:
                if child in batches:
                    discard(child)
            item["children"] = []
            result = discover_sources(item["path"], year=data.year, years=data.years)
            for source in result["detected"]:
                original = data.original_names.get(source["file"], source["file"])
                if not original or len(original) > 255 or any(ord(c) < 32 for c in original):
                    raise IngestionError("invalid_filename")
                source["original_file"] = original
            if len(list(root.glob("ops-*"))) + len(result["groups"]) > 20:
                raise IngestionError("upload_batch_limit")
            profile = profiles.current()
            for group in result["groups"]:
                if group["blocking"]:
                    continue
                child_key = new_batch()["batch_id"]
                child = batch(child_key)
                item["children"].append(child_key)
                for source in group["files"]:
                    shutil.copyfile(item["path"] / source["file"], child["path"] / source["file"])
                child["generation_started"] = True
                try:
                    analysis = analyze_sources(child["path"], date.fromisoformat(group["start_date"]), profile)
                    child["analysis"] = analysis
                    child["date_evidence"] = group["files"]
                    group.update(batch_id=child_key, analysis=analysis)
                except IngestionError as exc:
                    group["blocking"].append(exc.code)
            return {**result, "profile": profile.model_dump(mode="json") if profile else None}

    @app.get("/ops/inventory-profile")
    def inventory_profile():
        profile = profiles.current()
        return {
            "profile": profile.model_dump(mode="json") if profile else None,
            "history": profiles.history(),
        }

    @app.put("/ops/inventory-profile")
    async def approve_inventory(request: Request):
        approval = ProfileApproval.model_validate(await request.json())
        profile = profiles.save(approval)
        return {"profile": profile.model_dump(mode="json"), "history": profiles.history()}

    @app.post("/ops/batches/{key}/analyze")
    async def analyze(key: str, request: Request):
        data = AnalysisInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"]:
            if item["dataset_id"]:
                raise IngestionError("candidate_inputs_locked")
            item["analysis"] = None
            item["preview_hash"] = None
            item["generation_started"] = True
            item["generated_hash"] = None
            result = analyze_sources(
                item["path"], data.start_date, profiles.current(), data.source_format
            )
            item["analysis"] = result
            return result

    @app.post("/ops/batches/{key}/manifest")
    async def review_manifest(key: str, request: Request):
        data = ManifestReviewInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"], _exclusive(profiles.root / ".lock"):
            if item["dataset_id"]:
                raise IngestionError("candidate_inputs_locked")
            item["preview_hash"] = None
            saved_analysis = item["analysis"]
            if not saved_analysis:
                raise IngestionError("analysis_required")
            profile = profiles.current()
            if not profile:
                raise IngestionError("approved_inventory_required")
            if data.profile_version != profile.version:
                raise IngestionError("profile_changed")
            if not data.target_acknowledged:
                raise IngestionError("target_confirmation_required")
            if not data.capture_acknowledged:
                raise IngestionError("capture_confirmation_required")
            if not data.review_acknowledged or not data.review_reason:
                raise IngestionError("inventory_acknowledgment_required")
            analysis = analyze_sources(
                item["path"], date.fromisoformat(saved_analysis["start_date"]), profile
            )
            if analysis["analysis_hash"] != data.analysis_hash:
                raise IngestionError("source_inputs_changed")
            if analysis["missing_sources"]:
                raise IngestionError(
                    "missing_source_files", report={"missing": analysis["missing_sources"]}
                )
            if analysis["source_format"] not in profile.source_formats:
                raise IngestionError("profile_format_not_approved")
            cls = WeeklyManifest if analysis["source_format"] == "weekly" else Manifest
            manifest = cls.model_validate(data.manifest)
            if (
                manifest.source_format != analysis["source_format"]
                or str(manifest.start_date) != analysis["start_date"]
            ):
                raise IngestionError("source_period_changed")
            changes = reviewed_windows(manifest, profile, analysis, data.windows_acknowledged)
            if isinstance(manifest, WeeklyManifest):
                source_map = {(str(w.week_start), w.file) for w in manifest.weeks}
                if manifest.inventory_review_reason != data.review_reason:
                    raise IngestionError("review_reason_mismatch")
            else:
                source_map = {(str(s.date), s.file or f"{s.date}.html") for s in manifest.snapshots}
            if source_map != {(f["period"], f["file"]) for f in analysis["files"]}:
                raise IngestionError("source_file_mapping_changed")
            sources = manifest.weeks if isinstance(manifest, WeeklyManifest) else manifest.snapshots
            if any(not s.capture_evidence or not s.capture_evidence.strip() for s in sources):
                raise IngestionError("capture_evidence_required")
            manifest.review_audit = {
                "reviewed_at": datetime.now(UTC).isoformat(), "review_reason": data.review_reason,
                "profile_version": profile.version, "analysis_hash": analysis["analysis_hash"],
                "coverage_changes": changes, "coverage_scope": "this_period",
                "capture_acknowledged": True, "target_acknowledged": True,
                "date_evidence": item.get("date_evidence", []),
            }
            encoded = json.dumps(
                manifest.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2
            ).encode()
            bundle = load_directory(item["path"], manifest_bytes=encoded)
            temp = item["path"] / ".manifest-review.tmp"
            try:
                temp.write_bytes(encoded)
                os.replace(temp, item["path"] / "manifest.json")
            finally:
                temp.unlink(missing_ok=True)
            item["generated_hash"] = bundle.input_hash
            item["profile_version"] = profile.version
            return {
                "manifest": json.loads(encoded),
                "summary": bundle.report(),
                "profile_version": profile.version,
            }

    @app.post("/ops/batches/{key}/coverage-profile")
    async def remember_windows(key: str, request: Request):
        from types import SimpleNamespace

        data = CoverageProfileInput.model_validate(await request.json())
        item = batch(key)
        with item["lock"]:
            if item["dataset_id"]:
                raise IngestionError("candidate_inputs_locked")
            profile = profiles.current()
            saved = item["analysis"]
            if not profile or profile.version != data.profile_version:
                raise IngestionError("profile_changed")
            if not saved:
                raise IngestionError("analysis_required")
            if not data.review_acknowledged or not data.review_reason:
                raise IngestionError("review_acknowledgment_required")
            analysis = analyze_sources(item["path"], date.fromisoformat(saved["start_date"]), profile)
            if analysis["analysis_hash"] != data.analysis_hash:
                raise IngestionError("source_inputs_changed")
            candidate = SimpleNamespace(window=profile.window, buildings=data.buildings,
                                        source_format=analysis["source_format"])
            changes = reviewed_windows(candidate, profile, analysis, True)
            approval = ProfileApproval(
                source_formats=profile.source_formats, window=profile.window, buildings=data.buildings,
                expected_version=profile.version, expected_rooms=profile.expected_rooms,
                expected_buildings=profile.expected_buildings, review_reason=data.review_reason,
                review_acknowledged=True, window_review_audit={
                    "scope": "future_imports", "analysis_hash": analysis["analysis_hash"],
                    "start_date": analysis["start_date"], "coverage_changes": changes,
                    "sources": [{"file": f["file"], "sha256": f["sha256"]} for f in analysis["files"]],
                })
            return {"profile": profiles.save(approval).model_dump(mode="json")}

    def checked_bundle(item):
        if item["generation_started"] and not item["generated_hash"]:
            raise IngestionError("manifest_review_required")
        bundle = load_directory(item["path"])
        if item["generation_started"]:
            profile = profiles.current()
            if not profile or item["profile_version"] != profile.version:
                raise IngestionError("profile_changed")
            if bundle.input_hash != item["generated_hash"]:
                raise IngestionError("manifest_review_required")
        return bundle

    @app.post("/ops/batches/{key}/preview")
    def preview(key: str):
        item = batch(key)
        with (
            item["lock"],
            _exclusive(profiles.root / ".lock") if item["generation_started"] else nullcontext(),
        ):
            bundle = checked_bundle(item)
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
        with (
            item["lock"],
            _exclusive(profiles.root / ".lock") if item["generation_started"] else nullcontext(),
        ):
            bundle = checked_bundle(item)
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
        with (
            item["lock"],
            _exclusive(profiles.root / ".lock") if item["generation_started"] else nullcontext(),
        ):
            if not item["dataset_id"] or data.confirm_dataset_id != item["dataset_id"]:
                raise IngestionError("candidate_confirmation_required")
            reason = data.review_reason
            if reason and data.review_acknowledged is not True:
                raise IngestionError("review_acknowledgment_required")
            if item["generation_started"]:
                checked_bundle(item)
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

    @app.post("/ops/publications")
    async def publish_selection(request: Request):
        from contextlib import ExitStack

        data = MultiPublicationInput.model_validate(await request.json())
        if not data.review_acknowledged or not data.review_reason:
            raise IngestionError("review_acknowledgment_required")
        if len(set(data.batch_ids)) != len(data.batch_ids):
            raise IngestionError("invalid_publication_selection")
        with ExitStack() as stack:
            items = [batch(key) for key in sorted(data.batch_ids)]
            for item in items:
                stack.enter_context(item["lock"])
            stack.enter_context(_exclusive(profiles.root / ".lock"))
            ids = [item["dataset_id"] for item in items]
            if not all(ids) or sorted(ids) != sorted(data.confirm_dataset_ids):
                raise IngestionError("candidate_confirmation_required")
            for item in items:
                checked_bundle(item)
            result = publish_datasets(db(), ids, review_reason=data.review_reason,
                                     expected_baseline=data.baseline_dataset_id or "")
            return {**result, "health": health(db())}

    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist-operator"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "operator.html").is_file():
            return error("operator_build_required", 503)
        return FileResponse(dist / "operator.html")

    return app
