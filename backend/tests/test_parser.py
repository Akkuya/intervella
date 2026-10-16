import json
from datetime import datetime

import pytest

from app.ingest.parser import parse_schedule

SAMPLE_HTML = """
<html>
<body>
    <input id="labtime" value="2026-10-14">

    <div id="contentwrapper">
        <table class="tableform">
            <caption>AA Building</caption>

            <thead>
                <tr>
                    <th id="blank"></th>
                    <th class="smallth">
                        <a href="/calendar?rfilter=307">
                            AA-112 (300)
                        </a>
                    </th>
                    <th class="smallth">
                        <a href="/calendar?rfilter=1234">
                            AA-207 (40)
                        </a>
                    </th>
                </tr>
            </thead>

            <tr>
                <td class="time"><div>09:00</div></td>
                <td class="event" rowspan="2">Lecture</td>
                <td class="blocked" rowspan="1">&nbsp;</td>
            </tr>

            <tr>
                <td class="time"><div>09:30</div></td>
                <td class="event" rowspan="2">Tutorial</td>
            </tr>

            <tr>
                <td class="time"><div>10:00</div></td>
                <td rowspan="1">&nbsp;</td>
            </tr>

            <tr>
                <td class="time"><div>10:30</div></td>
                <td rowspan="1">&nbsp;</td>
                <td rowspan="1">&nbsp;</td>
            </tr>
        </table>
    </div>
</body>
</html>
"""


def test_room_metadata():
    data = parse_schedule(SAMPLE_HTML)
    rooms = data["buildings"][0]["rooms"]

    assert rooms[0]["name"] == "AA-112"
    assert rooms[0]["capacity"] == 300
    assert rooms[0]["id"] == 307

    assert rooms[1]["name"] == "AA-207"
    assert rooms[1]["capacity"] == 40
    assert rooms[1]["id"] == 1234


def test_rowspan_mapping():
    data = parse_schedule(SAMPLE_HTML)
    rooms = data["buildings"][0]["rooms"]

    assert rooms[0]["events"] == [
        {"start_time": "09:00", "end_time": "10:00", "description": "Lecture"}
    ]

    assert rooms[1]["events"] == [
        {"start_time": "09:30", "end_time": "10:30", "description": "Tutorial"}
    ]


def test_json_structure():
    data = parse_schedule(SAMPLE_HTML)

    assert data["date"] == "2026-10-14"
    assert len(data["buildings"]) == 1
    assert len(data["buildings"][0]["rooms"]) == 2

    # Must be serializable to JSON
    json.dumps(data)

    # Generated timestamp must include timezone information
    timestamp = datetime.fromisoformat(data["generated_at"])
    assert timestamp.tzinfo is not None


def test_malformed_event_time():
    html = SAMPLE_HTML.replace("09:00", "20P:30")

    with pytest.raises(ValueError, match="Invalid event time"):
        parse_schedule(html)


def test_malformed_non_event_time():
    # Invalid source time in an empty row should not
    # prevent extraction of valid events.
    html = SAMPLE_HTML.replace("10:30", "20P:30")

    data = parse_schedule(html)

    assert len(data["buildings"][0]["rooms"][0]["events"]) == 1
    assert len(data["buildings"][0]["rooms"][1]["events"]) == 1
