from datetime import date

import pytest

from app.ingest.weekly import parse_weekly


def weekly_html(rooms=(("SYN-A-101", 20, 2),), week="Oct 25 - Oct 31"):
    tables = []
    for name, capacity, length in rooms:
        head = (
            "<thead><tr><th></th>"
            + "".join(
                f"<th>{day}</th>"
                for day in ["SUN.", "MON.", "TUE.", "WED.", "THU.", "FRI.", "SAT."]
            )
            + "</tr></thead>"
        )
        rows = "".join(
            "<tr><td>"
            + f"{8 + i // 2:02}:{i % 2 * 30:02}"
            + "</td>"
            + "".join(
                '<td class="event rightcell">Synthetic booking</td>'
                if i == 0 and day == 1
                else '<td class="lastcell"></td>'
                for day in range(7)
            )
            + "</tr>"
            for i in range(length)
        )
        tables.append(
            f'<table class="tableform"><caption>{name} ({capacity}) ({week})</caption>'
            f"{head}{rows}</table>"
        )
    return (
        '<html><head><title>Synthetic timetable</title></head><body><div id="contentwrapper">'
        + "".join(tables)
        + "</div></body></html>"
    )


def test_weekly_days_and_actual_room_bounds():
    parsed = parse_weekly(
        weekly_html((("SYN-A-101", 20, 2), ("SYN-A-102", 30, 4))), date(2026, 10, 25)
    )
    assert len(parsed) == 7
    assert parsed[date(2026, 10, 26)][0]["days"][1]["events"][0]["start_minute"] == 480
    assert parsed[date(2026, 10, 25)][0]["row_minutes"][-1] == 540
    assert parsed[date(2026, 10, 25)][1]["row_minutes"][-1] == 600


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("MON.", "SUN."),
        lambda s: s.replace("Oct 31", "Oct 30"),
        lambda s: s.replace("08:30", "09:00"),
        lambda s: s.replace("event rightcell", "mystery"),
        lambda s: s.replace('<td class="lastcell"></td>', "", 1),
        lambda s: s.replace("<html>", "").replace("</html>", ""),
        lambda s: s.replace('id="contentwrapper"', 'id="fragment"'),
    ],
)
def test_weekly_rejects_invalid_structure(change):
    with pytest.raises(ValueError):
        parse_weekly(change(weekly_html()), date(2026, 10, 25))


def test_explicit_week_start_and_year_rollover():
    with pytest.raises(ValueError):
        parse_weekly(weekly_html(), date(2026, 10, 26))
    assert date(2027, 1, 2) in parse_weekly(weekly_html(week="Dec 27 - Jan 2"), date(2026, 12, 27))


@pytest.mark.parametrize("span", [2, 3, 4])
def test_weekly_rowspans_align_independent_weekday_columns(span):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(weekly_html((("SYN-A-101", 20, 4),)), "html.parser")
    rows = soup.select("table tr")[1:]
    rows[0].find_all("td", recursive=False)[2]["rowspan"] = str(span)
    for row in rows[1:span]:
        row.find_all("td", recursive=False)[2].decompose()
    parsed = parse_weekly(str(soup), date(2026, 10, 25))
    columns = parsed[date(2026, 10, 25)][0]["days"]
    assert columns[1]["events"][0]["end_minute"] == 480 + span * 30
    assert columns[2]["events"] == []
    assert columns[2]["coverage"][0]["end_minute"] == 600


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace('class="event rightcell"', 'class="cancelled"'),
        lambda s: s.replace("(20)", "(0)"),
        lambda s: s.replace("<th>MON.</th>", '<th colspan="2">MON.</th>'),
    ],
)
def test_weekly_rejects_invalid_capacities_or_states(change):
    with pytest.raises(ValueError):
        parse_weekly(change(weekly_html()), date(2026, 10, 25))
