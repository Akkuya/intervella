import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


def parse_room(room):
    """Extract a room's name, capacity, and internal ID."""
    anchor = room.find("a")

    if anchor is None:
        raise ValueError("Room header has no link")

    text = anchor.get_text(strip=True)

    capacity_match = re.search(r"\((\d+)\)$", text)
    id_match = re.search(r"rfilter=(\d+)", anchor.get("href", ""))

    if not capacity_match or not id_match:
        raise ValueError(f"Invalid room header: {text}")

    return {
        "name": text[: capacity_match.start()].strip(),
        "capacity": int(capacity_match.group(1)),
        "id": int(id_match.group(1)),
        "events": [],
    }


def parse_building(building, *, strict=False):
    """Parse the rooms and scheduled events for one building."""
    if strict:
        return _strict_building(building)
    building_name = building.caption.get_text(strip=True)

    headers = building.find_all("th", class_="smallth")
    room_data = [parse_room(room) for room in headers]

    remaining_spans = [0] * len(room_data)
    rows = building.thead.find_next_siblings("tr")

    for row in rows:
        entries = row.find_all("td", recursive=False)

        if not entries:
            raise ValueError(f"Empty schedule row in {building_name}")

        start_time = entries[0].get_text(strip=True)
        cells = entries[1:]

        cell_index = 0

        for room_index in range(len(room_data)):
            # Previous cell still spans this room's column
            if remaining_spans[room_index] > 0:
                continue

            if cell_index >= len(cells):
                raise ValueError(f"Missing cell in {building_name} at {start_time}")

            cell = cells[cell_index]
            cell_index += 1

            span = int(cell.get("rowspan", 1))

            if span < 1:
                raise ValueError(f"Invalid rowspan in {building_name} at {start_time}")

            remaining_spans[room_index] = span

            # Only store actual events
            if "event" in cell.get("class", []):
                try:
                    start = datetime.strptime(start_time, "%H:%M")
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid event time '{start_time}' "
                        f"in {building_name}, "
                        f"{room_data[room_index]['name']}"
                    ) from exc

                end = start + timedelta(minutes=span * 30)

                room_data[room_index]["events"].append(
                    {
                        "start_time": start_time,
                        "end_time": end.strftime("%H:%M"),
                        "description": cell.get_text(" ", strip=True),
                    }
                )

        # Every new HTML cell should have been assigned
        if cell_index != len(cells):
            raise ValueError(f"Unassigned cells in {building_name} at {start_time}")

        # Advance to the next 30-minute interval
        remaining_spans = [max(0, span - 1) for span in remaining_spans]

    if any(remaining_spans):
        raise ValueError(f"Rowspans exceed schedule in {building_name}")

    return {"name": building_name, "rooms": room_data}


def parse_schedule(html: str, *, strict: bool = False) -> dict:
    """Convert a UTSC intranet HTML response into schedule data."""
    soup = BeautifulSoup(html, "html.parser")

    content = soup.find(id="contentwrapper")
    date_input = soup.find(id="labtime")

    if content is None or date_input is None:
        raise ValueError("Missing schedule content or date")

    date = date_input.get("value")

    if not isinstance(date, str) or not date:
        raise ValueError("Schedule date is missing")
    if strict:
        try:
            if datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date:
                raise ValueError
        except ValueError:
            raise ValueError("Invalid schedule date") from None
        if len(soup.find_all(id="labtime")) != 1 or len(soup.find_all(id="contentwrapper")) != 1:
            raise ValueError("Duplicate schedule content or date")

    schedules = content.find_all("table", class_="tableform")

    if not schedules:
        raise ValueError("No building schedules found")

    buildings = [parse_building(building, strict=strict) for building in schedules]
    if strict:
        names = [building["name"] for building in buildings]
        ids = [room["id"] for building in buildings for room in building["rooms"]]
        if len(set(names)) != len(names) or len(set(ids)) != len(ids):
            raise ValueError("Duplicate building or source room identity")
    return {
        "date": date,
        "generated_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(timespec="seconds"),
        "buildings": buildings,
    }


def _strict_building(building):
    """Prove each column's interval; legacy extraction alone never proves coverage."""
    caption = building.find("caption", recursive=False)
    head = building.find("thead", recursive=False)
    if caption is None or not caption.get_text(strip=True) or head is None:
        raise ValueError("Missing building caption or timetable header")
    if building.find("table") is not None or len(head.find_all("tr")) != 1:
        raise ValueError("Nested or ambiguous timetable")
    headers = head.find_all("th", class_="smallth")
    rooms = [parse_room(header) for header in headers]
    if not rooms or any(room["capacity"] <= 0 or not room["name"] for room in rooms):
        raise ValueError("Invalid room inventory")
    if len({room["name"] for room in rooms}) != len(rooms):
        raise ValueError("Duplicate room header")
    if any(
        header.get("rowspan", "1") != "1" or header.get("colspan", "1") != "1" for header in headers
    ):
        raise ValueError("Ambiguous room columns")
    rows = [row for row in building.find_all("tr") if row.find_parent("thead") is None]
    if not rows or len(rows) > 48:
        raise ValueError("Empty or oversized timetable")
    minutes = []
    day_offset = 0
    for row in rows:
        entries = row.find_all("td", recursive=False)
        if not entries or row.find_all("th", recursive=False):
            raise ValueError("Missing timetable row")
        label = entries[0].get_text(strip=True)
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[03]0", label):
            raise ValueError("Invalid 30-minute row time")
        minute = int(label[:2]) * 60 + int(label[3:])
        if minutes and minutes[-1] % 1440 == 1410 and minute == 0:
            day_offset += 1440
        minute += day_offset
        if minutes and minute != minutes[-1] + 30:
            raise ValueError("Nonconsecutive timetable rows")
        if entries[0].get("rowspan", "1") != "1" or entries[0].get("colspan", "1") != "1":
            raise ValueError("Ambiguous time column")
        minutes.append(minute)
    remaining = [0] * len(rooms)
    for room in rooms:
        room["coverage"] = []
    for index, row in enumerate(rows):
        cells = row.find_all("td", recursive=False)[1:]
        cell_index = 0
        for number, room in enumerate(rooms):
            if remaining[number]:
                remaining[number] -= 1
                continue
            if cell_index >= len(cells):
                raise ValueError("Missing room cell")
            cell = cells[cell_index]
            cell_index += 1
            raw_span = cell.get("rowspan", "1")
            if not re.fullmatch(r"[1-9]\d?", raw_span) or cell.get("colspan", "1") != "1":
                raise ValueError("Invalid timetable span")
            span = int(raw_span)
            if index + span > len(rows):
                raise ValueError("Rowspan exceeds timetable")
            remaining[number] = span - 1
            classes = set(cell.get("class", []))
            if classes - {"event", "cancelled", "blocked"} or cell.find("table"):
                raise ValueError("Unrecognized timetable cell")
            event = "event" in classes
            if ("cancelled" in classes and not event) or (not event and cell.get_text(strip=True)):
                raise ValueError("Unrecognized booking cell")
            start, end = minutes[index], minutes[index] + span * 30
            completeness = "unknown" if "blocked" in classes else "complete"
            coverage = room["coverage"]
            if (
                coverage
                and coverage[-1]["end_minute"] == start
                and coverage[-1]["completeness"] == completeness
            ):
                coverage[-1]["end_minute"] = end
            else:
                coverage.append(
                    {"start_minute": start, "end_minute": end, "completeness": completeness}
                )
            if event:
                room["events"].append(
                    {
                        "start_time": f"{start // 60 % 24:02}:{start % 60:02}",
                        "end_time": f"{end // 60 % 24:02}:{end % 60:02}",
                        "start_minute": start,
                        "end_minute": end,
                        "status": "cancelled" if "cancelled" in classes else "scheduled",
                    }
                )
        if cell_index != len(cells):
            raise ValueError("Unassigned room cells")
    return {
        "name": caption.get_text(strip=True),
        "rooms": rooms,
        "row_minutes": [*minutes, minutes[-1] + 30],
    }
