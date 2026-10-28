"""Public read-only REST boundary. No request fetches or publishes schedule data."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.db import get_read_session
from app.errors import APIError
from app.schemas import (
    AvailabilityParams,
    AvailabilityResponse,
    BuildingsResponse,
    ErrorDetail,
    ErrorResponse,
    LiveResponse,
    ReadyResponse,
    RoomResponse,
    ScheduleParams,
    ScheduleResponse,
    StatusResponse,
)
from app.services import availability
from app.settings import Settings

logger = logging.getLogger("uvicorn.error")
ReadSession = Annotated[Session, Depends(get_read_session)]
RoomID = Annotated[int, Path(gt=0, le=2**63 - 1)]


def utc_now() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Uvicorn's default access log includes untrusted query values; use safe route records below.
    logging.getLogger("uvicorn.access").disabled = True
    yield


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def error_response(request: Request, error: APIError) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=error.code,
            message=error.message,
            fields=error.fields,
            request_id=request.state.request_id,
        )
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(
        title="UTSCVacant API",
        version="0.2.0",
        lifespan=lifespan,
        description=(
            "Public schedule availability. Schedule available does not guarantee a room "
            "is empty, unlocked, or permitted for study. Null next_booking means no later "
            "scheduled booking is known in this dataset, not unlimited availability."
        ),
        responses={code: {"model": ErrorResponse} for code in (404, 405, 422, 500, 503, 504)},
    )
    app.state.settings = settings

    @app.middleware("http")
    async def error_boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=settings.request_timeout_seconds
            )
        except TimeoutError:
            response = error_response(
                request, APIError(504, "request_timeout", "Request timed out. Try again.")
            )
        except Exception as error:
            logger.error(
                "request_id=%s error_type=%s", request.state.request_id, type(error).__name__
            )
            response = error_response(
                request, APIError(500, "internal_error", "Unable to complete request.")
            )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-cache"
        route = request.scope.get("route")
        logger.info(
            "request_id=%s route=%s status=%s duration_ms=%.2f dataset_id=%s",
            request.state.request_id,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (perf_counter() - started) * 1000,
            getattr(request.state, "dataset_id", None),
        )
        return response

    @app.exception_handler(APIError)
    async def public_error(request: Request, error: APIError) -> JSONResponse:
        return error_response(request, error)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return error_response(
            request, APIError(503, "database_unavailable", "Schedule database is unavailable.")
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = sorted({str(item["loc"][1]) for item in error.errors() if len(item["loc"]) > 1})
        return error_response(
            request, APIError(422, "invalid_request", "Check request fields.", fields)
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
        message = {404: "Resource not found.", 405: "Method not allowed."}.get(
            error.status_code, "Request failed."
        )
        response = error_response(request, APIError(error.status_code, code, message))
        if error.headers:
            response.headers.update(error.headers)
        return response

    @app.get("/health/live", response_model=LiveResponse)
    def live() -> LiveResponse:
        return LiveResponse()

    @app.get("/api/v1/availability", response_model=AvailabilityResponse)
    def search(
        request: Request,
        query: Annotated[AvailabilityParams, Query()],
        session: ReadSession,
        now: Annotated[datetime, Depends(utc_now)],
        config: Annotated[Settings, Depends(get_settings)],
    ) -> AvailabilityResponse:
        limit = query.limit
        if "limit" not in request.query_params:
            limit = min(limit, config.max_availability_limit)
        if limit > config.max_availability_limit:
            raise APIError(422, "invalid_request", "Result limit exceeds server limit.", ["limit"])
        try:
            end = query.start + timedelta(minutes=query.duration_minutes)
        except OverflowError:
            raise APIError(
                422, "unsupported_window", "Choose a supported start time.", ["start"]
            ) from None
        result = availability.find_available_rooms(
            session,
            start=query.start,
            end=end,
            now=now,
            building=query.building,
            limit=limit,
            max_age_hours=config.freshness_max_age_hours,
        )
        request.state.dataset_id = str(result.meta.dataset_id)
        return result

    @app.get("/api/v1/buildings", response_model=BuildingsResponse)
    def buildings(session: ReadSession) -> BuildingsResponse:
        return availability.list_buildings(session)

    @app.get("/api/v1/rooms/{room_id}", response_model=RoomResponse)
    def room(room_id: RoomID, session: ReadSession) -> RoomResponse:
        return RoomResponse(data=availability.room_details(session, room_id))

    @app.get("/api/v1/rooms/{room_id}/schedule", response_model=ScheduleResponse)
    def schedule(
        request: Request,
        room_id: RoomID,
        query: Annotated[ScheduleParams, Query()],
        session: ReadSession,
        now: Annotated[datetime, Depends(utc_now)],
        config: Annotated[Settings, Depends(get_settings)],
    ) -> ScheduleResponse:
        result = availability.room_schedule(
            session, room_id, query.date, now, config.freshness_max_age_hours
        )
        request.state.dataset_id = str(result.meta.dataset_id)
        return result

    @app.get("/api/v1/status", response_model=StatusResponse)
    def status(
        request: Request,
        session: ReadSession,
        now: Annotated[datetime, Depends(utc_now)],
        config: Annotated[Settings, Depends(get_settings)],
    ) -> StatusResponse:
        result = availability.dataset_status(session, now, config.freshness_max_age_hours)
        request.state.dataset_id = str(result.dataset_id)
        return result

    @app.get("/health/ready", response_model=ReadyResponse)
    def ready(
        request: Request,
        session: ReadSession,
        now: Annotated[datetime, Depends(utc_now)],
        config: Annotated[Settings, Depends(get_settings)],
    ) -> ReadyResponse:
        result = availability.dataset_status(session, now, config.freshness_max_age_hours)
        request.state.dataset_id = str(result.dataset_id)
        if not result.usable:
            raise APIError(
                503, "coverage_unavailable", "No complete schedule coverage is usable now."
            )
        return ReadyResponse(
            dataset_id=result.dataset_id, freshness=result.freshness, degraded=result.degraded
        )

    return app


app = create_app()
