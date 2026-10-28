from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas import AvailabilityParams, ScheduleParams
from app.services.availability import campus_day_bounds


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-14T12:00:00",
        "2026-10-14",
        "1700000000",
        1700000000,
        "bad",
        "0001-01-01T00:00:00+14:00",
    ],
)
def test_start_requires_explicit_iso_offset(value):
    with pytest.raises(ValidationError):
        AvailabilityParams(start=value)


@pytest.mark.parametrize(
    "value,hour", [("2026-11-01T01:30:00-04:00", 5), ("2026-11-01T01:30:00-05:00", 6)]
)
def test_dst_offset_identifies_instant(value, hour):
    assert AvailabilityParams(start=value).start == datetime(2026, 11, 1, hour, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25), (date(2026, 10, 14), 24)]
)
def test_campus_day_uses_local_midnights(day, hours):
    start, end = campus_day_bounds(day)
    assert (end - start).total_seconds() == hours * 3600
    assert start.tzinfo is UTC and end.tzinfo is UTC


@pytest.mark.parametrize("value", ["0", "2026-10-14T00:00:00Z", "2026-02-30"])
def test_schedule_date_requires_iso_calendar_date(value):
    with pytest.raises(ValidationError):
        ScheduleParams(date=value)
