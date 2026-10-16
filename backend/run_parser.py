import json
from pathlib import Path

from app.ingest.parser import parse_schedule


def main():
    root = Path(__file__).resolve().parent

    input_path = root / "data" / "exampledata.html"
    output_path = root / "data" / "output.json"

    html = input_path.read_text(encoding="utf-8")

    schedule_data = parse_schedule(html)

    output_path.write_text(
        json.dumps(schedule_data, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    building_count = len(schedule_data["buildings"])
    room_count = sum(len(building["rooms"]) for building in schedule_data["buildings"])
    event_count = sum(
        len(room["events"]) for building in schedule_data["buildings"] for room in building["rooms"]
    )

    print(f"Parsed {building_count} buildings, {room_count} rooms, {event_count} events.")


if __name__ == "__main__":
    main()
