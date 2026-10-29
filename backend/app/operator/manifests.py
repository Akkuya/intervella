"""Description-free draft generation over the existing strict timetable parsers."""

import copy
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from app.ingest.local import MAX_HTML_BYTES, IngestionError, _read
from app.ingest.parser import parse_schedule
from app.ingest.weekly import parse_weekly
from app.operator.profiles import Profile


def _clock(minute):
    return "24:00" if minute == 1440 else f"{minute % 1440 // 60:02}:{minute % 60:02}"


def _window(bounds):
    return {"start": _clock(bounds[0]), "end": _clock(bounds[-1])}


def _label_parts(label):
    # These are literal source-label parts, only suggestions until inventory review.
    match = re.fullmatch(r"([A-Z][A-Z0-9-]{0,15})[- ]([A-Za-z0-9][A-Za-z0-9._-]{0,31})", label)
    if not match:
        match = re.fullmatch(r"([A-Z]{1,8})(\d[A-Za-z0-9._-]{0,31})", label)
    if match:
        return match.groups()
    return ("", label) if re.fullmatch(r"[0-9][A-Za-z0-9._-]{0,31}", label) else ("", "")


def analyze_sources(
    directory: Path, start: date, profile: Profile | None = None, source_format=None
):
    try:
        dates = [start + timedelta(days=i) for i in range(7)]
        required_weeks = sorted({d - timedelta(days=(d.weekday() + 1) % 7) for d in dates})
    except OverflowError:
        raise IngestionError("invalid_target_period") from None
    paths = sorted(directory.glob("*.html"))
    if not paths:
        raise IngestionError("missing_source_files")
    if len(paths) > 7:
        raise IngestionError("too_many_files")
    observations: dict[tuple[str | None, str], dict] = {}
    files, formats, periods, issues = [], set(), set(), []
    occurrences = 0
    per_file = []
    for path in paths:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.html", path.name):
            raise IngestionError("invalid_filename")
        content = _read(path, MAX_HTML_BYTES)
        if b"\x00" in content:
            raise IngestionError("invalid_file")
        try:
            html = content.decode("utf-8-sig")
        except UnicodeError:
            raise IngestionError("invalid_source_encoding") from None
        matches = []
        try:
            daily = parse_schedule(html, strict=True)
            day = date.fromisoformat(daily["date"])
            matches.append(("daily", day, daily))
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
        for week in required_weeks:
            try:
                weekly = parse_weekly(html, week)
                matches.append(("weekly", week, weekly))
            except (ValueError, TypeError, KeyError, OverflowError):
                pass
        if len(matches) != 1:
            raise IngestionError(
                "ambiguous_source" if matches else "malformed_or_unexpected_source",
                report={"file": path.name},
            )
        kind, period, parsed = matches[0]
        if kind == "daily" and period not in dates:
            raise IngestionError("unexpected_source_period", report={"file": path.name})
        if (kind, period) in periods:
            raise IngestionError("duplicate_source_period", report={"file": path.name})
        periods.add((kind, period))
        formats.add(kind)
        if len(formats) != 1:
            raise IngestionError("mixed_source_formats")
        current = []
        if kind == "weekly":
            for room in parsed[period]:
                current.append(
                    {
                        "source_building": None,
                        "source_name": room["name"],
                        "source_id": None,
                        "capacity": room["capacity"],
                        "window": _window(room["row_minutes"]),
                        "row_minutes": room["row_minutes"],
                    }
                )
                occurrences += sum(
                    len(room["days"][(d - period).days]["events"]) for d in dates if d in parsed
                )
        else:
            for building in parsed["buildings"]:
                for room in building["rooms"]:
                    current.append(
                        {
                            "source_building": building["name"],
                            "source_name": room["name"],
                            "source_id": room["id"],
                            "capacity": room["capacity"],
                            "window": _window(building["row_minutes"]),
                            "row_minutes": building["row_minutes"],
                        }
                    )
                    occurrences += len(room["events"])
        keys = set()
        for room in current:
            key = (room["source_building"], room["source_name"])
            if key in keys:
                raise IngestionError("duplicate_identity")
            keys.add(key)
            if key in observations and observations[key] != room:
                issues.append(
                    {
                        "code": "inconsistent_source_room",
                        "room": room["source_name"],
                        "file": path.name,
                        "severity": "blocking",
                    }
                )
            observations.setdefault(key, room)
        per_file.append((path.name, keys))
        files.append(
            {
                "file": path.name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "format": kind,
                "period": period.isoformat(),
                "rooms": len(current),
                "dates": [
                    str(d) for d in dates if d == period or (kind == "weekly" and d in parsed)
                ],
                "row_steps": sorted(
                    {b - a for r in current for a, b in zip(r["row_minutes"], r["row_minutes"][1:])}
                ),
            }
        )
    files.sort(key=lambda f: (f["period"], f["file"]))
    kind = next(iter(formats))
    if source_format and source_format != kind:
        raise IngestionError("source_format_mismatch")
    if profile and kind not in profile.source_formats:
        issues.append({"code": "profile_format_not_approved", "severity": "blocking"})
    required = required_weeks if kind == "weekly" else dates
    missing = [str(p) for p in required if (kind, p) not in periods]
    union = set(observations)
    for filename, keys in per_file:
        if keys != union:
            issues.append(
                {"code": "partial_source_inventory", "file": filename, "severity": "blocking"}
            )
    buildings = [b.model_dump(mode="json") for b in profile.buildings] if profile else []
    approved = [(b, r) for b in buildings for r in b["rooms"]]
    seen = set()
    differences: dict[str, list] = {
        k: []
        for k in (
            "added_rooms",
            "missing_rooms",
            "capacity_changes",
            "window_changes",
            "source_id_changes",
            "unmatched_rooms",
        )
    }
    for (raw_building, name), room in observations.items():
        candidates = [
            (b, r)
            for b, r in approved
            if r["source_name"] == name and (kind == "weekly" or b["source_name"] == raw_building)
        ]
        if len(candidates) > 1:
            raise IngestionError("ambiguous_room_mapping")
        if candidates:
            assert profile is not None
            b, r = candidates[0]
            seen.add((b["source_name"], name))
            for field, changed in [
                ("capacity", "capacity_changes"),
                ("window", "window_changes"),
                ("source_id", "source_id_changes"),
            ]:
                expected = (
                    (r.get("window") or profile.window.model_dump())
                    if field == "window"
                    else r.get(field)
                )
                if (
                    (field != "source_id" or kind == "daily")
                    and expected is not None
                    and expected != room[field]
                ):
                    differences[changed].append(
                        {"room": name, "expected": expected, "observed": room[field]}
                    )
            continue
        prefix, number = _label_parts(name)
        if not prefix and raw_building and re.fullmatch(r"[A-Z][A-Z0-9-]{0,15}", raw_building):
            prefix = raw_building
        group_key = raw_building or prefix
        group = next((b for b in buildings if group_key and b["source_name"] == group_key), None)
        if group is None:
            group = {
                "source_name": group_key or "",
                "code": prefix,
                "name": raw_building or prefix,
                "rooms": [],
            }
            buildings.append(group)
        group["rooms"].append(
            {
                "source_name": name,
                "room_number": number,
                "source_id": room["source_id"],
                "capacity": room["capacity"],
                "window": room["window"],
            }
        )
        differences["added_rooms"].append(name)
        if not prefix or not number:
            differences["unmatched_rooms"].append(name)
        issues.append({"code": "mapping_requires_review", "room": name, "severity": "confirmation"})
    for b, r in approved:
        if (b["source_name"], r["source_name"]) not in seen:
            differences["missing_rooms"].append(r["source_name"])
    window = profile.window.model_dump() if profile else next(iter(observations.values()))["window"]
    draft = {
        "version": 2 if kind == "weekly" else 1,
        "source_format": kind,
        "start_date": str(start),
        "window": window,
        "buildings": buildings,
    }
    if kind == "weekly":
        draft.update(
            inventory_scope="complete",
            inventory_review_reason="",
            weeks=[{"week_start": f["period"], "file": f["file"], "fetched_at": ""} for f in files],
        )
    else:
        draft["snapshots"] = [
            {"date": f["period"], "file": f["file"], "fetched_at": ""} for f in files
        ]
    digest = hashlib.sha256(
        json.dumps([str(start), [(f["file"], f["sha256"]) for f in files]], sort_keys=True).encode()
    ).hexdigest()
    return {
        "analysis_hash": digest,
        "source_format": kind,
        "start_date": str(start),
        "profile_version": profile.version if profile else 0,
        "bootstrap_required": profile is None,
        "missing_sources": missing,
        "files": files,
        "observed_rooms": list(observations.values()),
        "draft": copy.deepcopy(draft),
        "differences": differences,
        "issues": issues,
        "summary": {
            "rooms": len(observations),
            "buildings": len(
                {
                    r["source_building"] or _label_parts(r["source_name"])[0]
                    for r in observations.values()
                }
            ),
            "occurrences": occurrences,
            "dates": [str(d) for d in dates],
        },
    }
