import json
from datetime import date

import pytest
from ingestion_helpers import write_bundle
from test_weekly_ingestion import write_weekly
from test_weekly_parser import weekly_html

from app.ingest.local import IngestionError, load_directory


def analyze(path, start, profile=None):
    from app.operator.manifests import analyze_sources

    return analyze_sources(path, date.fromisoformat(start), profile)


def test_weekly_detection_never_invents_capture_or_source_ids(tmp_path):
    write_weekly(tmp_path)
    (tmp_path / "manifest.json").unlink()
    result = analyze(tmp_path, "2026-10-25")
    assert result["source_format"] == "weekly"
    assert result["missing_sources"] == []
    assert result["bootstrap_required"]
    assert result["draft"]["weeks"][0]["fetched_at"] == ""
    assert all(r["source_id"] is None for b in result["draft"]["buildings"] for r in b["rooms"])
    assert "Synthetic booking" not in json.dumps(result)
    assert result["summary"]["rooms"] == 2


def test_daily_preserves_arbitrary_original_names_and_requires_seven_dates(tmp_path):
    write_bundle(tmp_path)
    (tmp_path / "manifest.json").unlink()
    (tmp_path / "2026-10-14.html").rename(tmp_path / "export.html")
    result = analyze(tmp_path, "2026-10-14")
    assert result["source_format"] == "daily"
    assert result["draft"]["snapshots"][0]["file"] == "export.html"
    (tmp_path / "2026-10-20.html").unlink()
    assert analyze(tmp_path, "2026-10-14")["missing_sources"] == ["2026-10-20"]


@pytest.mark.parametrize(
    "start,weeks",
    [
        ("2026-10-25", ("2026-10-25",)),
        ("2026-10-28", ("2026-10-25", "2026-11-01")),
        ("2026-12-30", ("2026-12-27", "2027-01-03")),
    ],
)
def test_target_period_resolves_yearless_weekly_captions(tmp_path, start, weeks):
    write_weekly(tmp_path, start=start, weeks=weeks)
    result = analyze(tmp_path, start)
    assert result["missing_sources"] == []
    assert [w["week_start"] for w in result["draft"]["weeks"]] == list(weeks)


def test_missing_adjacent_week_and_individual_room_windows(tmp_path):
    write_weekly(tmp_path)
    source = tmp_path / "week-2026-10-25.html"
    source.write_text(weekly_html((("SYN-A-101", 20, 2), ("SYN-A-102", 40, 4))), encoding="utf-8")
    result = analyze(tmp_path, "2026-10-28")
    assert result["missing_sources"] == ["2026-11-01"]
    windows = [r["window"] for b in result["draft"]["buildings"] for r in b["rooms"]]
    assert windows == [{"start": "08:00", "end": "09:00"}, {"start": "08:00", "end": "10:00"}]


@pytest.mark.parametrize("mutation", ["malformed", "duplicate", "mixed", "unknown_class"])
def test_invalid_or_ambiguous_sources_fail_closed(tmp_path, mutation):
    write_weekly(tmp_path)
    source = tmp_path / "week-2026-10-25.html"
    if mutation == "malformed":
        source.write_text("<html>broken</html>", encoding="utf-8")
    elif mutation == "unknown_class":
        source.write_text(
            source.read_text(encoding="utf-8").replace("lastcell", "mystery"), encoding="utf-8"
        )
    elif mutation == "duplicate":
        (tmp_path / "other.html").write_bytes(source.read_bytes())
    else:
        from ingestion_helpers import snapshot

        (tmp_path / "day.html").write_text(snapshot("2026-10-28"), encoding="utf-8")
    with pytest.raises(IngestionError):
        analyze(tmp_path, "2026-10-28")


def approved(result):
    from app.operator.profiles import Profile

    return Profile(
        version=1,
        reviewed_at="2026-10-14T11:00:00Z",
        review_reason="independent-inventory",
        source_formats=[result["source_format"]],
        window=result["draft"]["window"],
        buildings=result["draft"]["buildings"],
    )


def test_exact_profile_mapping_reuse_and_inventory_change_reports(tmp_path):
    write_weekly(tmp_path)
    original = analyze(tmp_path, "2026-10-25")
    profile = approved(original)
    profile.buildings[0].code = "APPROVED"
    profile.buildings[0].rooms[0].room_number = "B101"
    reused = analyze(tmp_path, "2026-10-25", profile)
    assert reused["draft"]["buildings"][0]["code"] == "APPROVED"
    assert reused["draft"]["buildings"][0]["rooms"][0]["room_number"] == "B101"
    assert not reused["bootstrap_required"]
    source = tmp_path / "week-2026-10-25.html"
    source.write_text(weekly_html((("SYN-A-101", 21, 2), ("SYN-A-999", 40, 4))), encoding="utf-8")
    changed = analyze(tmp_path, "2026-10-25", profile)
    assert changed["differences"]["missing_rooms"] == ["SYN-A-102"]
    assert changed["differences"]["added_rooms"] == ["SYN-A-999"]
    assert changed["differences"]["capacity_changes"]
    assert changed["differences"]["window_changes"]
    assert changed["draft"]["buildings"][0]["rooms"][0]["capacity"] == 20


def test_in_memory_manifest_and_daily_filename_extension_use_existing_loader(tmp_path):
    manifest = write_bundle(tmp_path)
    source = tmp_path / "2026-10-14.html"
    source.rename(tmp_path / "chosen-export.html")
    manifest["snapshots"][0]["file"] = "chosen-export.html"
    bundle = load_directory(tmp_path, manifest_bytes=json.dumps(manifest).encode())
    assert len(bundle.dates) == 7 and len(bundle.coverage) == 14
    assert "chosen-export.html" in json.dumps(bundle.sources)
    manifest["snapshots"][0]["file"] = "../secret.html"
    with pytest.raises(IngestionError):
        load_directory(tmp_path, manifest_bytes=json.dumps(manifest).encode())


def test_daily_literal_building_code_and_bare_room_numbers_are_not_guessed(tmp_path):
    write_bundle(tmp_path)
    for path in tmp_path.glob("*.html"):
        path.write_text(
            path.read_text(encoding="utf-8")
            .replace("Synthetic A", "AA")
            .replace("SYN-A-101", "101")
            .replace("SYN-A-102", "102"),
            encoding="utf-8",
        )
    result = analyze(tmp_path, "2026-10-14")
    assert result["draft"]["buildings"][0]["code"] == "AA"
    assert [r["room_number"] for r in result["draft"]["buildings"][0]["rooms"]] == ["101", "102"]


def test_unmatched_labels_do_not_fabricate_building_or_room_identifiers(tmp_path):
    write_weekly(tmp_path)
    path = tmp_path / "week-2026-10-25.html"
    path.write_text(weekly_html((("Main Auditorium", 20, 4),)), encoding="utf-8")
    result = analyze(tmp_path, "2026-10-25")
    building = result["draft"]["buildings"][0]
    assert building["code"] == building["rooms"][0]["room_number"] == ""
    assert result["differences"]["unmatched_rooms"] == ["Main Auditorium"]


def test_overflowing_target_period_fails_closed(tmp_path):
    write_weekly(tmp_path)
    with pytest.raises(IngestionError, match="invalid_target_period"):
        analyze(tmp_path, "9999-12-31")
