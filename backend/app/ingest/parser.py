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


def parse_building(building):
    """Parse the rooms and scheduled events for one building."""
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


def parse_schedule(html: str) -> dict:
    """Convert a UTSC intranet HTML response into schedule data."""
    soup = BeautifulSoup(html, "html.parser")

    content = soup.find(id="contentwrapper")
    date_input = soup.find(id="labtime")

    if content is None or date_input is None:
        raise ValueError("Missing schedule content or date")

    date = date_input.get("value")

    if not date:
        raise ValueError("Schedule date is missing")

    schedules = content.find_all("table", class_="tableform")

    if not schedules:
        raise ValueError("No building schedules found")

    return {
        "date": date,
        "generated_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(timespec="seconds"),
        "buildings": [parse_building(building) for building in schedules],
    }
