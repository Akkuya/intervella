"""Local multi-file discovery. Filenames and machine time are never date evidence."""

import hashlib
import re
from collections import defaultdict
from datetime import date, timedelta

from bs4 import BeautifulSoup

from app.ingest.local import MAX_HTML_BYTES, IngestionError, _read
from app.ingest.parser import parse_schedule
from app.ingest.weekly import MONTHS, parse_weekly

MAX_FILES = 84
MAX_BATCH_BYTES = 100 * 1024 * 1024


def discover_sources(directory, *, year=None, years=None):
    paths = sorted(directory.glob("*.html"))
    if not paths or len(paths) > MAX_FILES:
        raise IngestionError("invalid_source_count")
    groups, exceptions, detected = defaultdict(list), [], []
    total = 0
    for path in paths:
        try:
            content = _read(path, MAX_HTML_BYTES)
            total += len(content)
            if total > MAX_BATCH_BYTES:
                raise IngestionError("input_too_large")
            html = content.decode("utf-8-sig")
            if b"\x00" in content or not re.search(r"</html\s*>", html, re.I):
                raise IngestionError("incomplete_source_document")
            soup = BeautifulSoup(html, "html.parser")
            # The two formats have disjoint structures; malformed daily pages must
            # not be retried as weekly schedules with a conveniently chosen year.
            weekly = any(re.search(r"\([A-Z][a-z]{2}\s+\d{1,2}\s*-\s*[A-Z][a-z]{2}\s+\d{1,2}\)$",
                                   caption.get_text(" ", strip=True))
                         for caption in soup.select("table.tableform > caption"))
            if weekly:
                captions = soup.select("table.tableform > caption")
                match = re.search(r"\(([A-Z][a-z]{2})\s+(\d{1,2})\s*-\s*[A-Z][a-z]{2}\s+\d{1,2}\)$",
                                  captions[0].get_text(" ", strip=True) if captions else "")
                if not match or match[1] not in MONTHS:
                    raise IngestionError("malformed_or_unexpected_source")
                markers = soup.find_all("meta", attrs={"name": "timetable-week-start"})
                supplied = (years or {}).get(path.name, year)
                if markers:
                    if len(markers) != 1:
                        raise IngestionError("ambiguous_source_year")
                    period = date.fromisoformat(markers[0].get("content", ""))
                    evidence = "html:timetable-week-start"
                    if supplied is not None and supplied != period.year:
                        raise IngestionError("source_year_conflict")
                elif supplied is not None:
                    period = date(supplied, MONTHS.index(match[1]) + 1, int(match[2]))
                    evidence = "operator-confirmed-start-year"
                else:
                    raise IngestionError("source_year_required")
                parse_weekly(html, period)
                kind = "weekly"
            else:
                parsed = parse_schedule(html, strict=True)
                period = date.fromisoformat(parsed["date"])
                kind, evidence = "daily", "html:daily-date"
            start = period - timedelta(days=(period.weekday() + 1) % 7)
            item = {"file": path.name, "format": kind, "period": str(period),
                    "week_start": str(start), "date_evidence": evidence,
                    "sha256": hashlib.sha256(content).hexdigest()}
            groups[start].append(item)
            detected.append(item)
        except (IngestionError, ValueError, TypeError, KeyError, OverflowError, UnicodeError) as exc:
            exceptions.append({"file": path.name,
                "code": exc.code if isinstance(exc, IngestionError) else "malformed_or_unexpected_source"})
    result = []
    for start, sources in sorted(groups.items()):
        periods, unique, conflicts = {}, [], []
        if len({s["format"] for s in sources}) != 1:
            conflicts.append("competing_daily_weekly_sources")
        for source in sources:
            key = (source["format"], source["period"])
            if key in periods:
                code = "identical_duplicate_ignored" if periods[key] == source["sha256"] else "duplicate_source_period"
                exceptions.append({"file": source["file"], "code": code})
                if code == "duplicate_source_period":
                    conflicts.append(code)
            else:
                unique.append(source)
                periods[key] = source["sha256"]
        result.append({"start_date": str(start), "files": unique, "blocking": sorted(set(conflicts))})
    if len(result) > 12:
        raise IngestionError("too_many_weeks")
    return {"groups": result, "exceptions": exceptions, "detected": detected}
