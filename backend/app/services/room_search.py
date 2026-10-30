"""Bounded, snapshot-consistent room search. Unknown intervals never become free."""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.errors import APIError
from app.models import Building, MeetingOccurrence, Room, RoomCoverage
from app.schemas import (
    CoverageWindow,
    MeetingInfo,
    RoomSearchMetadata,
    RoomSearchParams,
    RoomSearchResponse,
    SearchRoom,
    TimeWindow,
)
from app.services.availability import active_dataset, dataset_period, freshness, require_period
from app.services.published import clip_payload, dataset_ids
from app.services.intervals import complete_windows, free_windows

MAX_ROOMS = 1000
MAX_RECORDS = 20000


def normalize_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def search_rooms(
    session: Session, query: RoomSearchParams, now: datetime, max_age_hours: float = 36
) -> RoomSearchResponse:
    start = query.start
    end = query.end or start + timedelta(minutes=query.duration_minutes or 60)
    if start < now - timedelta(minutes=5) or start > now + timedelta(days=30):
        raise APIError(422, "unsupported_window", "Choose a supported start time.", ["start"])
    horizon = start + timedelta(hours=24)
    dataset = active_dataset(session, start, horizon)
    require_period(dataset_period(session, dataset), start, end)
    name = normalize_name(query.room_name or "")
    if query.room_name is not None and not name:
        raise APIError(422, "invalid_request", "Enter a room identifier.", ["room_name"])
    if (
        query.building
        and session.scalar(select(col(Building.id)).where(col(Building.code) == query.building))
        is None
    ):
        raise APIError(422, "invalid_building", "Choose a recognized building.", ["building"])
    statement = select(Room, Building).join(Building)
    if query.room_ids:
        statement = statement.where(col(Room.id).in_(query.room_ids))
    else:
        statement = statement.where(col(Room.active).is_(True))
    if query.building:
        statement = statement.where(col(Building.code) == query.building)
    # Parameterized SQL normalization matches AA112, AA-112 and basement identifiers.
    if name:
        statement = statement.where(
            func.regexp_replace(
                func.upper(col(Building.code) + col(Room.room_number)), "[^A-Z0-9]", "", "g"
            ).contains(name, autoescape=True)
        )
    rooms = session.execute(statement.order_by(col(Room.id)).limit(MAX_ROOMS + 1)).all()
    if len(rooms) > MAX_ROOMS:
        raise APIError(422, "search_too_large", "Narrow the building or room filter.")
    ids = [room.id for room, _ in rooms]
    coverage = session.scalars(
        select(RoomCoverage)
        .where(
            col(RoomCoverage.dataset_id).in_(dataset_ids(dataset)),
            col(RoomCoverage.room_id).in_(ids),
            col(RoomCoverage.starts_at) < horizon,
            col(RoomCoverage.ends_at) > start,
        )
        .limit(MAX_RECORDS + 1)
    ).all()
    meetings = session.scalars(
        select(MeetingOccurrence)
        .where(
            col(MeetingOccurrence.dataset_id).in_(dataset_ids(dataset)),
            col(MeetingOccurrence.room_id).in_(ids),
            col(MeetingOccurrence.starts_at) < horizon,
            col(MeetingOccurrence.ends_at) > start,
        )
        .limit(MAX_RECORDS + 1)
    ).all()
    if len(coverage) > MAX_RECORDS or len(meetings) > MAX_RECORDS:
        raise APIError(422, "search_too_large", "Search schedule exceeds the safe limit.")
    next_bookings: dict[int, datetime] = {
        room_id: value
        for room_id, value in session.execute(
            select(col(MeetingOccurrence.room_id), func.min(col(MeetingOccurrence.starts_at)))
            .where(
                col(MeetingOccurrence.dataset_id).in_(dataset_ids(dataset)),
                col(MeetingOccurrence.room_id).in_(ids),
                col(MeetingOccurrence.status) == "scheduled",
                col(MeetingOccurrence.starts_at) >= end,
            )
            .group_by(col(MeetingOccurrence.room_id))
        ).all()
    }
    windows: dict[int, list[CoverageWindow]] = defaultdict(list)
    events: dict[int, list[MeetingInfo]] = defaultdict(list)
    for item in coverage:
        window = clip_payload(dataset, item, CoverageWindow.model_validate(item, from_attributes=True))
        window.starts_at = max(start, window.starts_at)
        window.ends_at = min(horizon, window.ends_at)
        if window.starts_at < window.ends_at:
            windows[item.room_id].append(window)
    for meeting in meetings:
        event = clip_payload(dataset, meeting, MeetingInfo.model_validate(meeting, from_attributes=True))
        if event.starts_at < event.ends_at:
            events[meeting.room_id].append(event)
    data = []
    unknown = 0
    for room, building in rooms:
        assert room.id is not None
        covered = any(a <= start and b >= end for a, b in complete_windows(windows[room.id]))
        free = free_windows(windows[room.id], events[room.id])
        current = next((b for a, b in free if a <= start and b >= end), None)
        state: Literal["available", "scheduled", "unknown", "inactive"] = (
            "inactive"
            if not room.active
            else "unknown"
            if not covered
            else "available"
            if current
            else "scheduled"
        )
        if state == "unknown":
            unknown += 1
        opening = (
            next((max(start, a) for a, b in free if b - max(start, a) >= end - start), None)
            if room.active
            else None
        )
        if query.room_ids or query.include_next or state == "available":
            data.append(
                SearchRoom(
                    room_id=room.id,
                    building_code=building.code,
                    room_number=room.room_number,
                    capacity=room.capacity,
                    active=room.active,
                    state=state,
                    available_until=current if room.active else None,
                    next_available_start=opening,
                    next_booking=next_bookings.get(room.id),
                )
            )
    if query.sort == "duration":
        data.sort(
            key=lambda item: (
                -(item.available_until - start).total_seconds()
                if item.available_until
                else float("inf"),
                item.building_code,
                item.room_number,
                item.room_id,
            )
        )
    elif query.sort == "room":
        data.sort(key=lambda item: (item.room_number, item.building_code, item.room_id))
    else:
        data.sort(key=lambda item: (item.building_code, item.room_number, item.room_id))
    return RoomSearchResponse(
        query=TimeWindow(start=start, end=end),
        data=data[: query.limit],
        meta=RoomSearchMetadata(
            **freshness(dataset, now, max_age_hours).model_dump(),
            coverage="partial" if unknown else "complete",
            unknown_room_count=unknown,
            has_more=len(data) > query.limit,
            missing_room_ids=sorted(set(query.room_ids) - set(ids)),
            lookahead_end=horizon,
        ),
    )
