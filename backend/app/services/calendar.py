"""Bounded building/day snapshots and conservative server-owned visual periods."""

from datetime import date, datetime
from typing import Literal

from sqlalchemy import select
from sqlmodel import Session, col

from app.errors import APIError
from app.models import Building, MeetingOccurrence, Room, RoomCoverage
from app.schemas import (
    BuildingInfo,
    BuildingScheduleMetadata,
    BuildingScheduleResponse,
    BuildingScheduleRoom,
    CalendarPeriod,
    CoverageWindow,
    DayCalendar,
    MeetingInfo,
    RoomInfo,
    TimeWindow,
)
from app.services.intervals import complete_windows, merge_intervals

MAX_ROOMS = 100
MAX_RECORDS = 5000


def display_window(
    start: datetime, end: datetime, coverage: list[CoverageWindow], meetings: list[MeetingInfo]
) -> TimeWindow:
    if not coverage:
        return TimeWindow(start=start, end=end)
    items: list[CoverageWindow | MeetingInfo] = [*coverage, *meetings]
    bounds = [
        (max(start, item.starts_at), min(end, item.ends_at))
        for item in items
        if item.starts_at < end and item.ends_at > start
    ]
    return (
        TimeWindow(start=min(left for left, _ in bounds), end=max(right for _, right in bounds))
        if bounds
        else TimeWindow(start=start, end=end)
    )


def day_calendar(
    start: datetime,
    end: datetime,
    coverage: list[CoverageWindow],
    meetings: list[MeetingInfo],
    window: TimeWindow | None = None,
) -> DayCalendar:
    window = window or display_window(start, end, coverage, meetings)
    clipped = [
        CoverageWindow(
            starts_at=max(start, item.starts_at),
            ends_at=min(end, item.ends_at),
            completeness=item.completeness,
        )
        for item in coverage
        if item.starts_at < end and item.ends_at > start
    ]
    complete = complete_windows(clipped)
    scheduled = merge_intervals(
        [(item.starts_at, item.ends_at) for item in meetings if item.status == "scheduled"]
    )
    boundaries = sorted(
        {
            window.start,
            window.end,
            *[
                value
                for interval in [*complete, *scheduled]
                for value in interval
                if window.start < value < window.end
            ],
        }
    )
    periods: list[CalendarPeriod] = []
    for left, right in zip(boundaries, boundaries[1:]):
        state: Literal["scheduled", "available", "unknown"] = (
            "scheduled"
            if any(a < right and b > left for a, b in scheduled)
            else "available"
            if any(a <= left and b >= right for a, b in complete)
            else "unknown"
        )
        if periods and periods[-1].state == state:
            periods[-1].ends_at = right
        else:
            periods.append(CalendarPeriod(starts_at=left, ends_at=right, state=state))
    return DayCalendar(window=window, coverage=clipped, periods=periods)


def building_schedule(
    session: Session, code: str, day: date, now: datetime, max_age_hours: float = 36
) -> BuildingScheduleResponse:
    from app.services.availability import active_dataset, campus_day_bounds, freshness

    dataset = active_dataset(session)
    building = session.execute(
        select(Building).where(col(Building.code) == code)
    ).scalar_one_or_none()
    if building is None:
        raise APIError(404, "building_not_found", "Building not found.")
    start, end = campus_day_bounds(day)
    rooms = session.scalars(
        select(Room)
        .where(col(Room.building_id) == building.id, col(Room.active).is_(True))
        .order_by(col(Room.room_number), col(Room.id))
        .limit(MAX_ROOMS + 1)
    ).all()
    if len(rooms) > MAX_ROOMS:
        raise APIError(422, "schedule_too_large", "Building inventory exceeds the calendar limit.")
    room_ids = [room.id for room in rooms]
    windows = session.scalars(
        select(RoomCoverage)
        .where(
            col(RoomCoverage.dataset_id) == dataset.id,
            col(RoomCoverage.room_id).in_(room_ids),
            col(RoomCoverage.starts_at) < end,
            col(RoomCoverage.ends_at) > start,
        )
        .order_by(col(RoomCoverage.room_id), col(RoomCoverage.starts_at))
        .limit(MAX_RECORDS + 1)
    ).all()
    meetings = session.scalars(
        select(MeetingOccurrence)
        .where(
            col(MeetingOccurrence.dataset_id) == dataset.id,
            col(MeetingOccurrence.room_id).in_(room_ids),
            col(MeetingOccurrence.starts_at) < end,
            col(MeetingOccurrence.ends_at) > start,
        )
        .order_by(col(MeetingOccurrence.starts_at), col(MeetingOccurrence.id))
        .limit(MAX_RECORDS + 1)
    ).all()
    if len(windows) > MAX_RECORDS or len(meetings) > MAX_RECORDS:
        raise APIError(422, "schedule_too_large", "Calendar payload exceeds the safe limit.")
    if rooms and not windows and not meetings:
        # Use the published period only to distinguish an unsupported date from an unknown room.
        from app.services.availability import dataset_period

        period = dataset_period(session, dataset)
        if period is not None and (end <= period.start or start >= period.end):
            raise APIError(
                422,
                "outside_dataset_coverage",
                "Choose a date within the published schedule.",
                ["date"],
            )
    coverage = [CoverageWindow.model_validate(item, from_attributes=True) for item in windows]
    events = [MeetingInfo.model_validate(item, from_attributes=True) for item in meetings]
    shared = display_window(start, end, coverage, events)
    data = []
    unknown = 0
    for room in rooms:
        assert room.id is not None
        room_windows = [
            CoverageWindow.model_validate(item, from_attributes=True)
            for item in windows
            if item.room_id == room.id
        ]
        room_events = [
            MeetingInfo.model_validate(item, from_attributes=True)
            for item in meetings
            if item.room_id == room.id
        ]
        calendar = day_calendar(start, end, room_windows, room_events, shared)
        if not any(
            left <= shared.start and right >= shared.end
            for left, right in complete_windows(room_windows)
        ):
            unknown += 1
        data.append(
            BuildingScheduleRoom(
                room=RoomInfo(
                    room_id=room.id,
                    building_code=building.code,
                    room_number=room.room_number,
                    capacity=room.capacity,
                    active=room.active,
                ),
                meetings=room_events,
                calendar=calendar,
            )
        )
    return BuildingScheduleResponse(
        building=BuildingInfo.model_validate(building, from_attributes=True),
        date=day,
        query=TimeWindow(start=start, end=end),
        display_window=shared,
        data=data,
        meta=BuildingScheduleMetadata(
            **freshness(dataset, now, max_age_hours).model_dump(), unknown_room_count=unknown
        ),
    )
