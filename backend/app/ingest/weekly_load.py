"""Weekly file transport adapter; publication remains owned by the existing pipeline."""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from app.ingest.local import (
    MAX_HTML_BYTES,
    IngestionError,
    Manifest,
    ManifestModel,
    Snapshot,
    SourceBuilding,
    Window,
    _normalize,
    _read,
)
from app.ingest.weekly import parse_weekly


class WeeklySource(ManifestModel):
    week_start: date
    file: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html$")
    fetched_at: AwareDatetime
    capture_evidence: str | None = Field(default=None, min_length=1, max_length=500)


class WeeklyManifest(ManifestModel):
    version: Literal[2]
    source_format: Literal["weekly"]
    inventory_scope: Literal["complete"]
    inventory_review_reason: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    start_date: date
    window: Window
    weeks: list[WeeklySource] = Field(min_length=1, max_length=2)
    buildings: list[SourceBuilding] = Field(min_length=1, max_length=50)
    review_audit: dict | None = None


def load_weekly(directory: Path, raw: bytes, digest):
    manifest = WeeklyManifest.model_validate_json(raw)
    dates = tuple(manifest.start_date + timedelta(days=i) for i in range(7))
    required = {day - timedelta(days=(day.weekday() + 1) % 7) for day in dates}
    weeks = {week.week_start: week for week in manifest.weeks}
    if len(weeks) != len(manifest.weeks) or set(weeks) != required:
        raise IngestionError("unexpected_weeks")
    files = {week.file for week in manifest.weeks}
    if len(files) != len(weeks) or {p.name for p in directory.glob("*.html")} != files:
        raise IngestionError("unexpected_files")
    aliases = {r.source_name: (b, r) for b in manifest.buildings for r in b.rooms}
    if len(aliases) != sum(len(b.rooms) for b in manifest.buildings):
        raise IngestionError("duplicate_identity")
    if any(r.capacity is None for b in manifest.buildings for r in b.rooms):
        raise IngestionError("missing_expected_capacity")
    parsed_days, data, provenance, snapshots = {}, {}, {}, []
    for week_start, source in sorted(weeks.items()):
        content = _read(directory / source.file, MAX_HTML_BYTES)
        digest.update(source.file.encode())
        digest.update(hashlib.sha256(content).digest())
        parsed = parse_weekly(content.decode("utf-8-sig"), week_start)
        raw_rooms = parsed[week_start]
        if {r["name"] for r in raw_rooms} != set(aliases):
            raise IngestionError("missing_or_unexpected_rooms")
        for day in dates:
            if day not in parsed:
                continue
            buildings: dict[str, dict] = {}
            for room in raw_rooms:
                b, r = aliases[room["name"]]
                building = buildings.setdefault(b.source_name, {"name": b.source_name, "rooms": []})
                column = room["days"][(day - week_start).days]
                building["rooms"].append(
                    {
                        "name": r.source_name,
                        "capacity": room["capacity"],
                        "row_minutes": room["row_minutes"],
                        **column,
                    }
                )
            parsed_days[day] = {"date": str(day), "buildings": list(buildings.values())}
            data[day] = content
            snapshots.append(Snapshot(date=day, fetched_at=source.fetched_at,
                                      capture_evidence=source.capture_evidence))
            provenance[day] = {
                "source_format": "weekly",
                "file": source.file,
                "week_start": str(week_start),
                "inventory_review_reason": manifest.inventory_review_reason,
            }
    compatible = Manifest(
        version=2,
        source_format="weekly",
        start_date=manifest.start_date,
        window=manifest.window,
        snapshots=snapshots,
        buildings=manifest.buildings,
        review_audit=manifest.review_audit,
    )
    return _normalize(compatible, dates, data, digest.hexdigest(), parsed_days, provenance)
