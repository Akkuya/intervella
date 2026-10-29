import datetime as dt
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, field_validator

UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]


class AvailabilityParams(BaseModel):
    start: UTCDateTime
    duration_minutes: int = Field(default=60, ge=5, le=240)
    building: str | None = None
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("start", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
            if not isinstance(parsed, datetime) or parsed.utcoffset() is None:
                raise ValueError
            return parsed.astimezone(UTC)
        except (ValueError, OverflowError):
            raise ValueError("Use an ISO 8601 timestamp with an explicit offset or Z") from None


class ScheduleParams(BaseModel):
    date: dt.date

    @field_validator("date", mode="before")
    @classmethod
    def iso_date(cls, value):
        return dt.date.fromisoformat(value) if isinstance(value, str) else value


class TimeWindow(BaseModel):
    start: UTCDateTime
    end: UTCDateTime
    timezone: Literal["America/Toronto"] = "America/Toronto"


class Period(BaseModel):
    start: UTCDateTime
    end: UTCDateTime


class FreshnessMetadata(BaseModel):
    dataset_id: UUID
    source_fetched_at: UTCDateTime
    freshness: Literal["fresh", "stale"]
    generated_at: UTCDateTime
    warnings: list[str] = Field(default_factory=list)


class AvailabilityMetadata(FreshnessMetadata):
    coverage: Literal["complete", "partial"]
    unknown_room_count: int
    has_more: bool


class AvailableRoom(BaseModel):
    room_id: int
    building_code: str
    room_number: str
    capacity: int | None
    status: Literal["schedule_available"] = "schedule_available"
    next_booking: UTCDateTime | None


class AvailabilityResponse(BaseModel):
    query: TimeWindow
    data: list[AvailableRoom]
    meta: AvailabilityMetadata


class BuildingInfo(BaseModel):
    id: int
    code: str
    name: str


class BuildingsResponse(BaseModel):
    data: list[BuildingInfo]


class RoomInfo(BaseModel):
    room_id: int
    building_code: str
    room_number: str
    capacity: int | None
    active: bool


class RoomResponse(BaseModel):
    data: RoomInfo


class CoverageInfo(BaseModel):
    completeness: Literal["complete", "partial", "unknown"]
    starts_at: UTCDateTime | None = None
    ends_at: UTCDateTime | None = None


class ScheduleMetadata(FreshnessMetadata):
    coverage: CoverageInfo


class PublicEventLabel(BaseModel):
    text: str = Field(min_length=1, max_length=120)
    authorization: Literal["approved_public"]


class MeetingInfo(BaseModel):
    id: int
    starts_at: UTCDateTime
    ends_at: UTCDateTime
    status: Literal["scheduled", "cancelled"]
    # Reserved for an explicitly authorized future source; ingestion stores no descriptions.
    public_label: PublicEventLabel | None = None


class CoverageWindow(BaseModel):
    starts_at: UTCDateTime
    ends_at: UTCDateTime
    completeness: Literal["complete", "partial", "unknown"]


class CalendarPeriod(BaseModel):
    starts_at: UTCDateTime
    ends_at: UTCDateTime
    state: Literal["available", "scheduled", "unknown"]


class DayCalendar(BaseModel):
    window: TimeWindow
    coverage: list[CoverageWindow]
    periods: list[CalendarPeriod]


class ScheduleResponse(BaseModel):
    room: RoomInfo
    date: dt.date
    query: TimeWindow
    data: list[MeetingInfo]
    meta: ScheduleMetadata
    calendar: DayCalendar | None = None


class BuildingScheduleRoom(BaseModel):
    room: RoomInfo
    meetings: list[MeetingInfo]
    calendar: DayCalendar


class BuildingScheduleMetadata(FreshnessMetadata):
    unknown_room_count: int


class BuildingScheduleResponse(BaseModel):
    building: BuildingInfo
    date: dt.date
    query: TimeWindow
    display_window: TimeWindow
    data: list[BuildingScheduleRoom]
    meta: BuildingScheduleMetadata


class StatusResponse(FreshnessMetadata):
    age_seconds: float
    period: Period | None
    timezone: Literal["America/Toronto"] = "America/Toronto"
    degraded: bool
    usable: bool
    unknown_room_count: int


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"
    dataset_id: UUID
    freshness: Literal["fresh", "stale"]
    degraded: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail
