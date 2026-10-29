"""Strict weekly export parsing. No network access or source descriptions returned."""

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from app.ingest.parser import _strict_grid

DAYS = ("SUN.", "MON.", "TUE.", "WED.", "THU.", "FRI.", "SAT.")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_weekly(html: str, week_start: date) -> dict:
    """Require a complete document; week_start supplies the caption's missing year."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find_all(id="contentwrapper")
    if (
        week_start.weekday() != 6
        or len(soup.find_all("html")) != 1
        or len(soup.find_all("body")) != 1
        or len(soup.find_all("head")) != 1
        or len(content) != 1
        or content[0].find_parent("body") is None
    ):
        raise ValueError("Incomplete weekly document or invalid Sunday week start")
    tables = content[0].find_all("table", class_="tableform")
    if not tables or len(soup.find_all("table", class_="tableform")) != len(tables):
        raise ValueError("Missing or misplaced weekly tables")
    result = []
    names = set()
    end = week_start + timedelta(days=6)
    for table in tables:
        caption = table.find("caption", recursive=False)
        head = table.find("thead", recursive=False)
        match = re.fullmatch(
            r"(.+?)\s+\(([1-9]\d*)\)\s+\(([A-Z][a-z]{2})\s+(\d{1,2})\s*-\s*([A-Z][a-z]{2})\s+(\d{1,2})\)",
            caption.get_text(" ", strip=True) if caption else "",
        )
        if (
            not match
            or head is None
            or table.find("table") is not None
            or len(head.find_all("tr")) != 1
        ):
            raise ValueError("Invalid weekly room caption or header")
        name, capacity, m1, d1, m2, d2 = match.groups()
        if name in names or (m1, int(d1), m2, int(d2)) != (
            MONTHS[week_start.month - 1],
            week_start.day,
            MONTHS[end.month - 1],
            end.day,
        ):
            raise ValueError("Duplicate room or week caption mismatch")
        names.add(name)
        header_row = head.find("tr")
        assert header_row is not None
        headers = header_row.find_all(["th", "td"], recursive=False)
        if (
            len(headers) != 8
            or headers[0].get_text(strip=True)
            or tuple(h.get_text(strip=True) for h in headers[1:]) != DAYS
            or any(
                h.name != "th" or h.get("rowspan", "1") != "1" or h.get("colspan", "1") != "1"
                for h in headers
            )
        ):
            raise ValueError("Invalid weekly day columns")
        grid = _strict_grid(table, [{"events": []} for _ in DAYS])
        result.append(
            {
                "name": name,
                "capacity": int(capacity),
                "row_minutes": grid["row_minutes"],
                "days": grid["rooms"],
            }
        )
    return {week_start + timedelta(days=i): result for i in range(7)}
