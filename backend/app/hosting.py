"""Vercel-only ingress; local and operator entry points never trust these headers."""

import os
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.db import database_url
from app.main import create_app
from app.schemas import ErrorDetail, ErrorResponse


class VercelIngress(BaseHTTPMiddleware):
    def __init__(self, app, *, host: str | None, platform: bool):
        super().__init__(app)
        self.host = host
        self.platform = platform

    async def dispatch(self, request: Request, call_next):
        try:
            if not self.platform:
                raise ValueError
            for name in ("host", "x-forwarded-proto", "x-vercel-forwarded-for"):
                if len(request.headers.getlist(name)) != 1:
                    raise ValueError
            if request.headers["x-forwarded-proto"] != "https":
                raise ValueError
            client = str(ip_address(request.headers["x-vercel-forwarded-for"]))
        except ValueError:
            return self.reject(403, "invalid_ingress", "Use the configured HTTPS address.")
        if self.host and request.headers["host"].lower() != self.host:
            return self.reject(421, "wrong_origin", "Use the configured Intervella address.")
        # These headers are overwritten by Vercel; no general-purpose proxy trust is enabled.
        request.scope["scheme"] = "https"
        request.scope["client"] = (client, 0)
        return await call_next(request)

    @staticmethod
    def reject(status, code, message):
        request_id = str(uuid4())
        body = ErrorResponse(error=ErrorDetail(code=code, message=message, request_id=request_id))
        return JSONResponse(
            status_code=status,
            content=body.model_dump(mode="json"),
            headers={
                "Cache-Control": "private, no-store",
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )


def create_vercel_app():
    app = create_app()
    config = app.state.student_auth.config
    host = urlsplit(config.origin).netloc if config and config.secure else None
    try:
        if not config or not config.secure or os.getenv("DATABASE_POOL_MODE") != "transaction":
            raise ValueError
        if any(
            os.getenv(key)
            for key in (
                "MIGRATION_DATABASE_URL",
                "INGESTION_DATABASE_URL",
                "STUDENT_AUTH_ADMIN_DATABASE_URL",
                "OPERATOR_SECRET",
                "SUPABASE_SERVICE_ROLE_KEY",
                "SUPABASE_SECRET_KEY",
            )
        ):
            raise ValueError
        for variable in ("DATABASE_URL", "STUDENT_AUTH_DATABASE_URL"):
            if database_url(variable).query.get("sslmode") not in {"require", "verify-full"}:
                raise ValueError
    except ValueError:
        # Keep sanitized liveness, but prevent sign-in and timetable reads with unsafe config.
        app.state.student_auth.config = None
    app.add_middleware(VercelIngress, host=host, platform=os.getenv("VERCEL") == "1")
    return app
