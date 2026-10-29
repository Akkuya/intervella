"""Half-open interval operations shared by calendar and room-search read services."""

from collections.abc import Iterable
from datetime import datetime

from app.schemas import CoverageWindow, MeetingInfo

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    result: list[Interval] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = result[-1][0], max(result[-1][1], end)
        else:
            result.append((start, end))
    return result


def subtract_intervals(
    intervals: Iterable[Interval], excluded: Iterable[Interval]
) -> list[Interval]:
    result = []
    blocked = merge_intervals(excluded)
    for start, end in merge_intervals(intervals):
        cursor = start
        for left, right in blocked:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                result.append((cursor, left))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def complete_windows(coverage: Iterable[CoverageWindow]) -> list[Interval]:
    windows = list(coverage)
    return subtract_intervals(
        [(item.starts_at, item.ends_at) for item in windows if item.completeness == "complete"],
        [(item.starts_at, item.ends_at) for item in windows if item.completeness != "complete"],
    )


def free_windows(
    coverage: Iterable[CoverageWindow], meetings: Iterable[MeetingInfo]
) -> list[Interval]:
    return subtract_intervals(
        complete_windows(coverage),
        [(item.starts_at, item.ends_at) for item in meetings if item.status == "scheduled"],
    )
