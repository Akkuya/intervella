import pytest
from test_parser import SAMPLE_HTML

from app.ingest.parser import parse_schedule


def test_strict_grid_proves_only_explicit_intervals_and_preserves_source_id():
    result = parse_schedule(SAMPLE_HTML, strict=True)
    room = result["buildings"][0]["rooms"][0]
    assert room["id"] == 307
    assert room["coverage"] == [
        {"start_minute": 540, "end_minute": 660, "completeness": "complete"}
    ]
    other = result["buildings"][0]["rooms"][1]
    assert other["coverage"][0]["completeness"] == "unknown"  # blocked is not free
    assert room["events"][0]["start_minute"] == 540


@pytest.mark.parametrize(
    "before,after",
    [
        ("10:30", "bad"),
        ("09:30", "10:00"),
        ('rowspan="2"', 'rowspan="9"'),
        ('rowspan="2"', 'colspan="2"'),
        ('class="blocked"', 'class="mystery"'),
        ('<td rowspan="1">&nbsp;</td>', '<td rowspan="1">Unrecognized booking</td>'),
        ("<caption>AA Building</caption>", ""),
        ("2026-10-14", "2026-02-30"),
        ("AA-207 (40)", "AA-112 (40)"),
        ("rfilter=1234", "rfilter=307"),
    ],
)
def test_strict_grid_rejects_malformed_or_ambiguous_source(before, after):
    with pytest.raises(ValueError):
        parse_schedule(SAMPLE_HTML.replace(before, after), strict=True)


def test_strict_grid_accepts_explicit_tbody():
    html = SAMPLE_HTML.replace("</thead>", "</thead><tbody>").replace(
        "</table>", "</tbody></table>"
    )
    assert len(parse_schedule(html, strict=True)["buildings"][0]["rooms"]) == 2


def test_strict_grid_empty_table_does_not_establish_coverage():
    html = (
        SAMPLE_HTML[: SAMPLE_HTML.index("            <tr>\n                <td")] + "</table></div>"
    )
    with pytest.raises(ValueError):
        parse_schedule(html, strict=True)


def test_midnight_rowspan_keeps_day_offset():
    html = SAMPLE_HTML.replace("09:00", "23:30").replace("09:30", "00:00")
    html = html.replace("10:00", "00:30").replace("10:30", "01:00")
    room = parse_schedule(html, strict=True)["buildings"][0]["rooms"][0]
    assert room["events"][0]["start_minute"] == 1410
    assert room["events"][0]["end_minute"] == 1470


@pytest.mark.parametrize(
    "before,after",
    [
        ('<td rowspan="1">&nbsp;</td>', '<td><img alt="Reserved"></td>'),
        ('<th id="blank"></th>', "<th>Unknown column</th><th></th>"),
        ("rfilter=307", "notrfilter=307"),
        ("rfilter=307", "rfilter=307&rfilter=900"),
        ('<th id="blank"></th>', '<th colspan="2"></th>'),
        ('<th id="blank"></th>', '<th rowspan="2"></th>'),
    ],
)
def test_strict_grid_rejects_unrecognized_markup_and_ambiguous_locators(before, after):
    with pytest.raises(ValueError):
        parse_schedule(SAMPLE_HTML.replace(before, after), strict=True)


@pytest.mark.parametrize("formatting", ["rightcell", "lastcell", "rightcell lastcell"])
def test_formatting_classes_preserve_empty_and_blocked_cell_semantics(formatting):
    html = SAMPLE_HTML.replace(
        '<td rowspan="1">', f'<td class="{formatting}" rowspan="1">'
    ).replace('class="blocked"', f'class="blocked {formatting}"')
    assert (
        parse_schedule(html, strict=True)["buildings"]
        == parse_schedule(SAMPLE_HTML, strict=True)["buildings"]
    )


@pytest.mark.parametrize(
    "classes", ["event rightcell", "lastcell event", "rightcell event lastcell"]
)
def test_formatted_event_remains_a_scheduled_booking(classes):
    html = SAMPLE_HTML.replace('class="event"', f'class="{classes}"')
    room = parse_schedule(html, strict=True)["buildings"][0]["rooms"][0]
    assert room["events"] == [
        {
            "start_time": "09:00",
            "end_time": "10:00",
            "start_minute": 540,
            "end_minute": 600,
            "status": "scheduled",
        }
    ]


@pytest.mark.parametrize(
    "before,after,error",
    [
        ('class="event"', 'class="event rightcell mystery"', "Unrecognized timetable cell"),
        (
            '<td rowspan="1">',
            '<td class="lastcell mystery" rowspan="1">',
            "Unrecognized timetable cell",
        ),
        (
            'class="event" rowspan="2"',
            'class="event rightcell" rowspan="0"',
            "Invalid timetable span",
        ),
        (
            'class="event" rowspan="2"',
            'class="event rightcell" rowspan="9"',
            "Rowspan exceeds timetable",
        ),
        (
            '<td rowspan="1">&nbsp;</td>',
            '<td class="lastcell">Unknown booking</td>',
            "Unrecognized booking cell",
        ),
        (
            '<td rowspan="1">&nbsp;</td>',
            '<td class="rightcell"><img alt="Reserved"></td>',
            "Unrecognized markup",
        ),
        ('<td rowspan="1">', '<td class="lastcell" colspan="2">', "Invalid timetable span"),
    ],
)
def test_formatting_classes_do_not_bypass_strict_validation(before, after, error):
    with pytest.raises(ValueError, match=error):
        parse_schedule(SAMPLE_HTML.replace(before, after), strict=True)
