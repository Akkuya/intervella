"""Read-only schedule queries. All reads share the caller's PostgreSQL snapshot."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlmodel import Session, col

from app.errors import APIError
from app.models import Building, Dataset, DatasetState, MeetingOccurrence, Room, RoomCoverage
from app.schemas import (
    AvailabilityMetadata,
    AvailabilityResponse,
    AvailableRoom,
    BuildingInfo,
    BuildingsResponse,
    CoverageInfo,
    CoverageWindow,
    FreshnessMetadata,
    MeetingInfo,
    Period,
    RoomInfo,
    ScheduleMetadata,
    ScheduleResponse,
    StatusResponse,
    TimeWindow,
)

CAMPUS_ZONE = ZoneInfo("America/Toronto")


def campus_day_bounds(day: date) -> tuple[datetime, datetime]:
    try:
        start = datetime.combine(day, time.min, CAMPUS_ZONE).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, CAMPUS_ZONE).astimezone(UTC)
        return start, end
    except (OverflowError, ValueError):
        raise APIError(
            422, "invalid_request", "Choose a supported calendar date.", ["date"]
        ) from None


def active_dataset(session: Session) -> Dataset:
    dataset = session.execute(
        select(Dataset)
        .join(DatasetState, col(DatasetState.active_dataset_id) == col(Dataset.id))
        .where(col(DatasetState.id) == 1, col(Dataset.published_at).is_not(None))
    ).scalar_one_or_none()
    if dataset is None:
        raise APIError(503, "dataset_unavailable", "No published schedule is available.")
    return dataset


def freshness(dataset: Dataset, now: datetime, max_age_hours: float = 36) -> FreshnessMetadata:
    stale = now - dataset.source_fetched_at > timedelta(hours=max_age_hours)
    return FreshnessMetadata(
        dataset_id=dataset.id,
        source_fetched_at=dataset.source_fetched_at,
        freshness="stale" if stale else "fresh",
        generated_at=now,
        warnings=["stale_dataset"] if stale else [],
    )


def dataset_period(session: Session, dataset: Dataset) -> Period | None:
    start, end = session.execute(
        select(func.min(col(RoomCoverage.starts_at)), func.max(col(RoomCoverage.ends_at)))
        .join(Room, col(Room.id) == col(RoomCoverage.room_id))
        .where(col(RoomCoverage.dataset_id) == dataset.id, col(Room.active).is_(True))
    ).one()
    return Period(start=start, end=end) if start is not None and end is not None else None


def complete_coverage(dataset: Dataset, start: datetime, end: datetime):
    covered = (
        select(
            func.range_agg(
                func.tstzrange(col(RoomCoverage.starts_at), col(RoomCoverage.ends_at), "[)")
            )
        )
        .where(
            col(RoomCoverage.dataset_id) == dataset.id,
            col(RoomCoverage.room_id) == col(Room.id),
            col(RoomCoverage.completeness) == "complete",
        )
        .correlate(Room)
        .scalar_subquery()
    )
    uncertain = (
        select(col(RoomCoverage.room_id))
        .where(
            col(RoomCoverage.dataset_id) == dataset.id,
            col(RoomCoverage.room_id) == col(Room.id),
            col(RoomCoverage.completeness) != "complete",
            col(RoomCoverage.starts_at) < end,
            col(RoomCoverage.ends_at) > start,
        )
        .correlate(Room)
        .exists()
    )
    return func.coalesce(covered.op("@>")(func.tstzrange(start, end, "[)")), False) & ~uncertain


def coverage_counts(
    session: Session, dataset: Dataset, start: datetime, end: datetime, building: str | None = None
) -> tuple[int, int]:
    eligible = select(col(Room.id)).join(Building).where(col(Room.active).is_(True))
    if building is not None:
        eligible = eligible.where(col(Building.code) == building)
    total = session.scalar(select(func.count()).select_from(eligible.subquery()))
    unknown = session.scalar(
        select(func.count()).select_from(
            eligible.where(~complete_coverage(dataset, start, end)).subquery()
        )
    )
    return total or 0, unknown or 0


def require_period(period: Period | None, start: datetime, end: datetime) -> None:
    if period is None:
        raise APIError(
            503, "coverage_unavailable", "No trustworthy schedule coverage is available."
        )
    if start < period.start or end > period.end:
        raise APIError(
            422,
            "outside_dataset_coverage",
            "Choose a time within the published schedule.",
            ["start"],
        )


def find_available_rooms(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    building: str | None = None,
    limit: int = 50,
    max_age_hours: float = 36,
) -> AvailabilityResponse:
    if start.utcoffset() is None or end.utcoffset() is None or now.utcoffset() is None:
        raise APIError(422, "invalid_request", "Use timestamps with an offset or Z.", ["start"])
    if start < now - timedelta(minutes=5) or start > now + timedelta(days=30):
        raise APIError(
            422,
            "unsupported_window",
            "Start must be between five minutes ago and thirty days ahead.",
            ["start"],
        )
    if not timedelta(minutes=5) <= end - start <= timedelta(minutes=240) or not 1 <= limit <= 100:
        raise APIError(
            422,
            "invalid_request",
            "Check duration and result limit.",
            ["duration_minutes", "limit"],
        )
    dataset = active_dataset(session)
    if (
        building is not None
        and session.scalar(select(col(Building.id)).where(col(Building.code) == building)) is None
    ):
        raise APIError(422, "invalid_building", "Choose a recognized building code.", ["building"])
    require_period(dataset_period(session, dataset), start, end)
    total, unknown = coverage_counts(session, dataset, start, end, building)
    if total and total == unknown:
        raise APIError(
            503,
            "coverage_unavailable",
            "No trustworthy schedule coverage is available for this query.",
        )
    conflict = (
        select(col(MeetingOccurrence.id))
        .where(
            col(MeetingOccurrence.dataset_id) == dataset.id,
            col(MeetingOccurrence.room_id) == col(Room.id),
            col(MeetingOccurrence.status) == "scheduled",
            col(MeetingOccurrence.starts_at) < end,
            col(MeetingOccurrence.ends_at) > start,
        )
        .correlate(Room)
        .exists()
    )
    next_booking = (
        select(func.min(col(MeetingOccurrence.starts_at)))
        .where(
            col(MeetingOccurrence.dataset_id) == dataset.id,
            col(MeetingOccurrence.room_id) == col(Room.id),
            col(MeetingOccurrence.status) == "scheduled",
            col(MeetingOccurrence.starts_at) >= end,
        )
        .correlate(Room)
        .scalar_subquery()
    )
    query: Select = (
        select(
            col(Room.id).label("room_id"),
            col(Building.code).label("building_code"),
            col(Room.room_number),
            col(Room.capacity),
            next_booking.label("next_booking"),
        )
        .join(Building)
        .where(col(Room.active).is_(True), complete_coverage(dataset, start, end), ~conflict)
    )
    if building is not None:
        query = query.where(col(Building.code) == building)
    rows = (
        session.execute(
            query.order_by(col(Building.code), col(Room.room_number), col(Room.id)).limit(limit + 1)
        )
        .mappings()
        .all()
    )
    return AvailabilityResponse(
        query=TimeWindow(start=start, end=end),
        data=[AvailableRoom.model_validate(row) for row in rows[:limit]],
        meta=AvailabilityMetadata(
            **freshness(dataset, now, max_age_hours).model_dump(),
            coverage="partial" if unknown else "complete",
            unknown_room_count=unknown,
            has_more=len(rows) > limit,
        ),
    )


def list_buildings(session: Session) -> BuildingsResponse:
    active_room = (
        select(col(Room.id))
        .where(col(Room.building_id) == col(Building.id), col(Room.active).is_(True))
        .exists()
    )
    rows = session.execute(
        select(col(Building.id), col(Building.code), col(Building.name))
        .where(active_room)
        .order_by(col(Building.code), col(Building.id))
    ).mappings()
    return BuildingsResponse(data=[BuildingInfo.model_validate(row) for row in rows])


def room_details(session: Session, room_id: int) -> RoomInfo:
    row = (
        session.execute(
            select(
                col(Room.id).label("room_id"),
                col(Building.code).label("building_code"),
                col(Room.room_number),
                col(Room.capacity),
                col(Room.active),
            )
            .join(Building)
            .where(col(Room.id) == room_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise APIError(404, "room_not_found", "Room not found.")
    return RoomInfo.model_validate(row)


def room_schedule(
    session: Session, room_id: int, day: date, now: datetime, max_age_hours: float = 36
) -> ScheduleResponse:
    room = room_details(session, room_id)
    dataset = active_dataset(session)
    start, end = campus_day_bounds(day)
    period = dataset_period(session, dataset)
    if period is None:
        raise APIError(
            503, "coverage_unavailable", "No trustworthy schedule coverage is available."
        )
    if end <= period.start or start >= period.end:
        raise APIError(
            422,
            "outside_dataset_coverage",
            "Choose a date within the published schedule.",
            ["date"],
        )
    windows = (
        session.execute(
            select(RoomCoverage).where(
                col(RoomCoverage.dataset_id) == dataset.id,
                col(RoomCoverage.room_id) == room_id,
                col(RoomCoverage.starts_at) < end,
                col(RoomCoverage.ends_at) > start,
            )
        )
        .scalars()
        .all()
    )
    full_day = session.scalar(
        select(complete_coverage(dataset, start, end))
        .select_from(Room)
        .where(col(Room.id) == room_id)
    )
    info = CoverageInfo(completeness="unknown")
    if windows:
        info = CoverageInfo(
            completeness="complete"
            if full_day
            else "partial"
            if any(w.completeness != "unknown" for w in windows)
            else "unknown",
            starts_at=max(start, min(w.starts_at for w in windows)),
            ends_at=min(end, max(w.ends_at for w in windows)),
        )
    rows = session.execute(
        select(
            col(MeetingOccurrence.id),
            col(MeetingOccurrence.starts_at),
            col(MeetingOccurrence.ends_at),
            col(MeetingOccurrence.status),
        )
        .where(
            col(MeetingOccurrence.dataset_id) == dataset.id,
            col(MeetingOccurrence.room_id) == room_id,
            col(MeetingOccurrence.starts_at) < end,
            col(MeetingOccurrence.ends_at) > start,
        )
        .order_by(col(MeetingOccurrence.starts_at), col(MeetingOccurrence.id))
    ).mappings()
    from app.services.calendar import day_calendar

    meetings = [MeetingInfo.model_validate(row) for row in rows]
    calendar = day_calendar(
        start,
        end,
        [CoverageWindow.model_validate(item, from_attributes=True) for item in windows],
        meetings,
    )
    if not room.active:
        for segment in calendar.periods:
            if segment.state == "available":
                segment.state = "unknown"
    return ScheduleResponse(
        room=room,
        date=day,
        query=TimeWindow(start=start, end=end),
        data=meetings,
        calendar=calendar,
        meta=ScheduleMetadata(
            **freshness(dataset, now, max_age_hours).model_dump(),
            coverage=info,
        ),
    )


def dataset_status(session: Session, now: datetime, max_age_hours: float = 36) -> StatusResponse:
    dataset = active_dataset(session)
    meta = freshness(dataset, now, max_age_hours)
    total, unknown = coverage_counts(session, dataset, now, now + timedelta(minutes=5))
    usable = total > unknown
    return StatusResponse(
        **meta.model_dump(),
        age_seconds=max(0, (now - dataset.source_fetched_at).total_seconds()),
        period=dataset_period(session, dataset),
        usable=usable,
        degraded=meta.freshness == "stale" or unknown > 0 or not usable,
        unknown_room_count=unknown,
    )
