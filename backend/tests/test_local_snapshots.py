import json
from datetime import UTC, datetime

import pytest
from ingestion_helpers import write_bundle

from app.ingest.local import IngestionError, load_directory


def test_seven_dates_normalize_explicit_identity_coverage_hashes_without_descriptions(tmp_path):
    write_bundle(tmp_path)
    bundle = load_directory(tmp_path)
    assert len(bundle.dates) == 7
    assert len(bundle.rooms) == 2
    assert len(bundle.coverage) == 14
    assert len(bundle.meetings) == 7
    assert bundle.meetings[0].starts_at == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    assert bundle.rooms[0].room_number == "101"
    assert bundle.rooms[0].source_id == 9001
    assert bundle.source_fetched_at == datetime(2026, 10, 14, 11, tzinfo=UTC)
    assert bundle.input_hash == load_directory(tmp_path).input_hash
    assert not hasattr(bundle.meetings[0], "description")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_day",
        "wrong_date",
        "missing_room",
        "missing_building",
        "extra_file",
        "truncated_rows",
        "duplicate_event",
        "naive_fetch",
    ],
)
def test_incomplete_local_exports_fail_closed(tmp_path, mutation):
    manifest = write_bundle(tmp_path)
    path = tmp_path / "2026-10-14.html"
    html = path.read_text(encoding="utf-8")
    if mutation == "missing_day":
        path.unlink()
    elif mutation == "extra_file":
        (tmp_path / "2026-10-22.html").write_text(html, encoding="utf-8")
    elif mutation == "wrong_date":
        path.write_text(html.replace("2026-10-14", "2026-10-13"), encoding="utf-8")
    elif mutation == "missing_room":
        path.write_text(html.replace("SYN-A-102 (40)", "SYN-A-103 (40)"), encoding="utf-8")
    elif mutation == "missing_building":
        path.write_text(html.replace("Synthetic A", "Unknown B"), encoding="utf-8")
    elif mutation == "truncated_rows":
        path.write_text(html[: html.rfind("<tr>")] + "</tbody></table></div>", encoding="utf-8")
    elif mutation == "duplicate_event":
        path.write_text(
            html.replace("<td>&nbsp;</td>", '<td class="event">Duplicate</td>', 1).replace(
                "rfilter=9002", "rfilter=9001"
            ),
            encoding="utf-8",
        )
    else:
        manifest["snapshots"][0]["fetched_at"] = "2026-10-14T11:00:00"
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(IngestionError):
        load_directory(tmp_path)


@pytest.mark.parametrize("first,expected_hour", [("2026-03-07", 13), ("2026-10-31", 12)])
def test_dst_is_local_calendar_based(tmp_path, first, expected_hour):
    write_bundle(tmp_path, first=first, fetched="2026-01-01T11:00:00Z")
    bundle = load_directory(tmp_path)
    assert bundle.coverage[0].starts_at.hour == expected_hour
    assert bundle.coverage[2].starts_at.hour == (12 if expected_hour == 13 else 13)


@pytest.mark.parametrize("first,start", [("2026-03-08", 120), ("2026-11-01", 60)])
def test_dst_unresolved_slots_are_rejected_even_without_events(tmp_path, first, start):
    write_bundle(
        tmp_path, first=first, fetched=f"{first}T00:00:00Z", start=start, slots=4, booking=False
    )
    with pytest.raises(IngestionError):
        load_directory(tmp_path)


def test_midnight_rowspan_converts_to_following_utc_day(tmp_path):
    write_bundle(tmp_path, start=1410, slots=4)
    bundle = load_directory(tmp_path)
    assert bundle.coverage[0].ends_at == datetime(2026, 10, 15, 5, 30, tzinfo=UTC)
