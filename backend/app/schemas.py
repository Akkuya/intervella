import datetime as dt
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

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


class RoomSearchParams(BaseModel):
    start: UTCDateTime
    building: str | None = Field(default=None, max_length=32)
    duration_minutes: int | None = Field(default=None, ge=5, le=240)
    end: UTCDateTime | None = None
    room_name: str | None = Field(default=None, max_length=64)
    sort: Literal["building", "room", "duration"] = "building"
    include_next: bool = False
    room_ids: list[Annotated[int, Field(gt=0, le=2**63 - 1)]] = Field(
        default_factory=list, max_length=100
    )
    limit: int = Field(default=100, ge=1, le=100)

    @field_validator("start", "end", mode="before")
    @classmethod
    def end_timestamp(cls, value):
        return AvailabilityParams.iso_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def interval(self):
        if self.room_ids and self.limit != 100:
            raise ValueError("Saved ID batches always return the entire bounded batch")
        if self.room_ids and (self.building or self.room_name):
            raise ValueError("Saved room batches cannot also filter inventory")
        if self.end is not None and self.duration_minutes is not None:
            raise ValueError("Choose duration or end, not both")
        try:
            end = self.end or self.start + dt.timedelta(minutes=self.duration_minutes or 60)
            if not dt.timedelta(minutes=5) <= end - self.start <= dt.timedelta(minutes=240):
                raise ValueError("Choose a 5 to 240 minute window")
        except OverflowError:
            raise ValueError("Choose a supported timestamp") from None
        return self


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


class SearchRoom(RoomInfo):
    state: Literal["available", "scheduled", "unknown", "inactive"]
    available_until: UTCDateTime | None = None
    next_available_start: UTCDateTime | None = None
    next_booking: UTCDateTime | None = None


class RoomSearchMetadata(AvailabilityMetadata):
    missing_room_ids: list[int] = Field(default_factory=list)
    lookahead_end: UTCDateTime


class RoomSearchResponse(BaseModel):
    query: TimeWindow
    data: list[SearchRoom]
    meta: RoomSearchMetadata


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
