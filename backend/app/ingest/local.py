"""Bounded, local-only transport and normalization of explicitly scoped exports."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from app.ingest.parser import parse_schedule

ZONE = ZoneInfo("America/Toronto")
PARSER_VERSION = "local-grid-v3"
MAX_HTML_BYTES = 10 * 1024 * 1024


class IngestionError(ValueError):
    run_id: UUID | None = None

    def __init__(self, code: str, *, input_hash: str | None = None, report: dict | None = None):
        super().__init__(code)
        self.code = code
        self.input_hash = input_hash
        self.report = report


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceRoom(ManifestModel):
    source_name: str = Field(min_length=1, max_length=128)
    room_number: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    source_id: int | None = Field(default=None, gt=0, strict=True)
    capacity: int | None = Field(default=None, gt=0, strict=True)
    window: "Window | None" = None


class SourceBuilding(ManifestModel):
    source_name: str = Field(min_length=1, max_length=128)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{0,15}$")
    name: str = Field(min_length=1, max_length=128)
    rooms: list[SourceRoom] = Field(min_length=1, max_length=500)


class Snapshot(ManifestModel):
    date: date
    fetched_at: AwareDatetime
    capture_evidence: str | None = Field(default=None, min_length=1, max_length=500)
    file: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html$")


class Window(ManifestModel):
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[03]0$")
    end: str = Field(pattern=r"^(?:(?:[01]\d|2[0-3]):[03]0|24:00)$")


class Manifest(ManifestModel):
    version: Literal[1, 2]
    source_format: Literal["daily", "weekly"] = "daily"
    start_date: date
    window: Window
    snapshots: list[Snapshot] = Field(min_length=7, max_length=7)
    buildings: list[SourceBuilding] = Field(min_length=1, max_length=50)
    review_audit: dict | None = None


@dataclass(frozen=True)
class RoomRecord:
    building_code: str
    building_name: str
    room_number: str
    source_id: int | None
    capacity: int

    @property
    def key(self) -> tuple[str, str]:
        return self.building_code, self.room_number


@dataclass(frozen=True)
class CoverageRecord:
    room_key: tuple[str, str]
    starts_at: datetime
    ends_at: datetime
    completeness: str
    source_date: date | None = None


@dataclass(frozen=True)
class MeetingRecord:
    room_key: tuple[str, str]
    starts_at: datetime
    ends_at: datetime
    status: str
    source_key: str


@dataclass(frozen=True)
class Bundle:
    dates: tuple[date, ...]
    rooms: tuple[RoomRecord, ...]
    coverage: tuple[CoverageRecord, ...]
    meetings: tuple[MeetingRecord, ...]
    source_fetched_at: datetime
    input_hash: str
    sources: tuple[dict, ...]
    source_format: str = "daily"
    review_audit: dict | None = None

    def report(self) -> dict:
        unknown = {item.room_key for item in self.coverage if item.completeness != "complete"}
        return {
            "source_format": self.source_format,
            "dates": [day.isoformat() for day in self.dates],
            "rooms": len(self.rooms),
            "buildings": len({room.building_code for room in self.rooms}),
            "coverage": len(self.coverage),
            "occurrences": len(self.meetings),
            "unknown_rooms": len(unknown),
            "input_hash": self.input_hash,
            "source_fetched_at": self.source_fetched_at.isoformat(),
        }


def local_instant(day: date, minute: int) -> datetime:
    """Reject gaps/folds; a source without offsets cannot resolve repeated wall times."""
    wall = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
    instants = set()
    for fold in [0, 1]:
        instant = wall.replace(tzinfo=ZONE, fold=fold).astimezone(UTC)
        if instant.astimezone(ZONE).replace(tzinfo=None) == wall:
            instants.add(instant)
    if len(instants) != 1:
        raise IngestionError("unresolved_local_time")
    return instants.pop()


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise IngestionError("missing_input_file")
    with path.open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise IngestionError("input_too_large")
    return content


def load_directory(directory: Path, *, manifest_bytes: bytes | None = None) -> Bundle:
    """No database writes; hashes include exact input bytes and the parser version."""
    digest = hashlib.sha256(PARSER_VERSION.encode())
    try:
        raw = (
            _read(directory / "manifest.json", 1024 * 1024)
            if manifest_bytes is None
            else manifest_bytes
        )
        if len(raw) > 1024 * 1024:
            raise IngestionError("input_too_large")
        digest.update(raw)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise IngestionError("invalid_local_input")
        if payload.get("source_format") == "weekly":
            from app.ingest.weekly_load import load_weekly

            return load_weekly(directory, raw, digest)
        manifest = Manifest.model_validate_json(raw)
        if manifest.version != 1 or manifest.source_format != "daily":
            raise IngestionError("unsupported_manifest")
        dates = tuple(manifest.start_date + timedelta(days=i) for i in range(7))
        snapshots = {snapshot.date: snapshot for snapshot in manifest.snapshots}
        if len(snapshots) != 7 or set(snapshots) != set(dates):
            raise IngestionError("unexpected_dates")
        names = {day: snapshots[day].file or f"{day}.html" for day in dates}
        expected = set(names.values())
        if len(expected) != 7 or {path.name for path in directory.glob("*.html")} != expected:
            raise IngestionError("unexpected_files")
        files = {}
        for day in dates:
            content = _read(directory / names[day], MAX_HTML_BYTES)
            files[day] = content
            digest.update(day.isoformat().encode())
            digest.update(hashlib.sha256(content).digest())
        provenance = {day: {"file": snapshots[day].file} for day in dates if snapshots[day].file}
        return _normalize(manifest, dates, files, digest.hexdigest(), provenance=provenance)
    except IngestionError as exc:
        exc.input_hash = digest.hexdigest()
        raise
    except (OSError, UnicodeError, ValidationError, ValueError, OverflowError):
        raise IngestionError("invalid_local_input", input_hash=digest.hexdigest()) from None


def _normalize(
    manifest: Manifest,
    dates: tuple[date, ...],
    files: dict[date, bytes],
    input_hash: str,
    parsed_days: dict | None = None,
    provenance: dict | None = None,
) -> Bundle:
    buildings = {building.source_name: building for building in manifest.buildings}
    aliases = {
        (building.source_name, room.source_name): (building, room)
        for building in manifest.buildings
        for room in building.rooms
    }
    room_keys = [(building.code, room.room_number) for building, room in aliases.values()]
    all_rooms = [room for building in manifest.buildings for room in building.rooms]
    source_ids = [room.source_id for room in all_rooms if room.source_id is not None]
    if manifest.source_format == "daily" and any(room.source_id is None for room in all_rooms):
        raise IngestionError("missing_source_identity")
    if (
        len(buildings) != len(manifest.buildings)
        or len({building.code for building in manifest.buildings}) != len(buildings)
        or len(aliases) != len(all_rooms)
        or len(set(room_keys)) != len(room_keys)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise IngestionError("duplicate_identity")
    start = _minute(manifest.window.start)
    end = _minute(manifest.window.end)
    if end <= start:
        end += 1440
    if end - start > 1440:
        raise IngestionError("invalid_window")
    rooms: dict[tuple[str, str], RoomRecord] = {}
    coverage = []
    meetings = []
    sources = []
    for day in dates:
        parsed = (
            parsed_days[day]
            if parsed_days is not None
            else parse_schedule(files[day].decode("utf-8-sig"), strict=True)
        )
        if parsed["date"] != day.isoformat():
            raise IngestionError("unexpected_page_date")
        if {building["name"] for building in parsed["buildings"]} != set(buildings):
            raise IngestionError("missing_buildings")
        seen = set()
        for raw_building in parsed["buildings"]:
            for raw_room in raw_building["rooms"]:
                alias = (raw_building["name"], raw_room["name"])
                if alias not in aliases:
                    raise IngestionError("unexpected_room")
                building, source_room = aliases[alias]
                bounds = raw_room.get("row_minutes", raw_building.get("row_minutes"))
                expected_start, expected_end = start, end
                if source_room.window:
                    expected_start = _minute(source_room.window.start)
                    expected_end = _minute(source_room.window.end)
                    if expected_end <= expected_start:
                        expected_end += 1440
                if bounds[0] != expected_start or bounds[-1] != expected_end:
                    raise IngestionError("incomplete_timetable_window")
                for minute in bounds:
                    local_instant(day, minute)
                if (
                    source_room.capacity is not None
                    and raw_room["capacity"] != source_room.capacity
                ):
                    raise IngestionError("source_capacity_changed")
                if manifest.source_format == "daily" and raw_room["id"] != source_room.source_id:
                    raise IngestionError("source_identity_changed")
                room = RoomRecord(
                    building.code,
                    building.name,
                    source_room.room_number,
                    source_room.source_id,
                    raw_room["capacity"],
                )
                if room.key in rooms and rooms[room.key] != room:
                    raise IngestionError("room_metadata_changed")
                rooms[room.key] = room
                seen.add(alias)
                for window in raw_room["coverage"]:
                    coverage.append(
                        CoverageRecord(
                            room.key,
                            local_instant(day, window["start_minute"]),
                            local_instant(day, window["end_minute"]),
                            window["completeness"],
                            day,
                        )
                    )
                for event in raw_room["events"]:
                    starts_at = local_instant(day, event["start_minute"])
                    ends_at = local_instant(day, event["end_minute"])
                    if ends_at <= starts_at:
                        raise IngestionError("invalid_meeting_interval")
                    source_key = hashlib.sha256(
                        json.dumps(
                            [*room.key, starts_at.isoformat(), ends_at.isoformat(), event["status"]]
                        ).encode()
                    ).hexdigest()
                    meetings.append(
                        MeetingRecord(room.key, starts_at, ends_at, event["status"], source_key)
                    )
        if seen != set(aliases):
            raise IngestionError("missing_rooms")
    if len({meeting.source_key for meeting in meetings}) != len(meetings):
        raise IngestionError("duplicate_meeting")
    captures = {item.date: item.fetched_at.astimezone(UTC) for item in manifest.snapshots}
    if any(capture > datetime.now(UTC) + timedelta(minutes=5) for capture in captures.values()):
        raise IngestionError("future_capture_time")
    for day in dates:
        sources.append(
            {
                **(provenance.get(day, {}) if provenance else {}),
                "date": str(day),
                "sha256": hashlib.sha256(files[day]).hexdigest(),
                "fetched_at": captures[day].isoformat(),
                "capture_evidence": next(s.capture_evidence for s in manifest.snapshots if s.date == day),
            }
        )
    return Bundle(
        dates,
        tuple(sorted(rooms.values(), key=lambda room: room.key)),
        tuple(coverage),
        tuple(meetings),
        min(captures.values()),
        input_hash,
        tuple(sources),
        manifest.source_format,
        manifest.review_audit,
    )


def _minute(value: str) -> int:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]|24):[03]0", value):
        raise IngestionError("invalid_window")
    return int(value[:2]) * 60 + int(value[3:])
