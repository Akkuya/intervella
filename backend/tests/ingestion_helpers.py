"""Generated, sanitized local exports. No authenticated source HTML."""

import json
from datetime import date, timedelta


def snapshot(day, *, start=8 * 60, slots=4, booking=True, blocked=False):
    rows = []
    for slot in range(slots):
        minute = (start + slot * 30) % 1440
        cells = []
        for room in [1, 2]:
            if room == 1 and booking and slot == 1:
                cells.append('<td class="event" rowspan="2">Synthetic event</td>')
            elif room == 1 and booking and slot == 2:
                continue
            else:
                cells.append('<td class="blocked">&nbsp;</td>' if blocked else "<td>&nbsp;</td>")
        rows.append(
            f'<tr><td class="time">{minute // 60:02}:{minute % 60:02}</td>{"".join(cells)}</tr>'
        )
    return f'''<html><input id="labtime" value="{day}"><div id="contentwrapper">
    <table class="tableform"><caption>Synthetic A</caption><thead><tr><th></th>
    <th class="smallth"><a href="/calendar?rfilter=9001">SYN-A-101 (20)</a></th>
    <th class="smallth"><a href="/calendar?rfilter=9002">SYN-A-102 (40)</a></th>
    </tr></thead><tbody>{"".join(rows)}</tbody></table></div></html>'''


def write_bundle(
    directory,
    *,
    first="2026-10-14",
    fetched="2026-10-14T11:00:00Z",
    start=480,
    slots=4,
    booking=True,
    blocked=False,
):
    directory.mkdir(exist_ok=True)
    first_day = date.fromisoformat(first)
    days = [first_day + timedelta(days=i) for i in range(7)]
    end = start + slots * 30
    manifest = {
        "version": 1,
        "start_date": first,
        "window": {
            "start": f"{start // 60:02}:{start % 60:02}",
            "end": "24:00" if end == 1440 else f"{end // 60 % 24:02}:{end % 60:02}",
        },
        "snapshots": [{"date": str(day), "fetched_at": fetched} for day in days],
        "buildings": [
            {
                "source_name": "Synthetic A",
                "code": "SYN-A",
                "name": "Synthetic A",
                "rooms": [
                    {
                        "source_name": f"SYN-A-{room}",
                        "room_number": str(room),
                        "source_id": 9000 + i,
                    }
                    for i, room in enumerate([101, 102], 1)
                ],
            }
        ],
    }
    for day in days:
        (directory / f"{day}.html").write_text(
            snapshot(day, start=start, slots=slots, booking=booking, blocked=blocked),
            encoding="utf-8",
        )
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest
