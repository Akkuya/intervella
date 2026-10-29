"""Synthetic weekly transport and PostgreSQL publication regressions."""

import json
from datetime import date, timedelta

import pytest
from ingestion_helpers import write_bundle
from sqlalchemy import select
from sqlmodel import Session
from test_weekly_parser import weekly_html

from app.ingest.local import IngestionError, load_directory
from app.ingest.pipeline import import_directory, publish_dataset
from app.models import DatasetState, Room


def write_weekly(
    path, *, start="2026-10-25", weeks=("2026-10-25",), fetched="2026-10-25T11:00:00Z"
):
    path.mkdir(exist_ok=True)
    manifest = {
        "version": 2,
        "source_format": "weekly",
        "inventory_scope": "complete",
        "inventory_review_reason": "inventory-reviewed",
        "start_date": start,
        "window": {"start": "08:00", "end": "10:00"},
        "buildings": [
            {
                "source_name": "Synthetic A",
                "code": "SYN-A",
                "name": "Synthetic A",
                "rooms": [
                    {"source_name": f"SYN-A-{n}", "room_number": str(n), "capacity": c}
                    for n, c in [(101, 20), (102, 40)]
                ],
            }
        ],
        "weeks": [],
    }
    for week in weeks:
        first = date.fromisoformat(week)
        last = first + timedelta(days=6)
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        caption = f"{months[first.month - 1]} {first.day} - {months[last.month - 1]} {last.day}"
        html = weekly_html((("SYN-A-101", 20, 4), ("SYN-A-102", 40, 4)), caption)
        html = html.replace('class="event rightcell">Synthetic booking', 'class="rightcell">')
        filename = f"week-{week}.html"
        (path / filename).write_text(html, encoding="utf8")
        manifest["weeks"].append({"week_start": week, "file": filename, "fetched_at": fetched})
    save(path, manifest)
    return manifest


def save(path, manifest):
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")


def test_weekly_matches_daily_without_fabricating_source_ids(tmp_path):
    write_bundle(
        tmp_path / "daily", first="2026-10-25", booking=False, fetched="2026-10-25T11:00:00Z"
    )
    write_weekly(tmp_path / "weekly")
    daily, weekly = load_directory(tmp_path / "daily"), load_directory(tmp_path / "weekly")
    assert daily.coverage == weekly.coverage
    assert daily.meetings == weekly.meetings == ()
    assert all(room.source_id is None for room in weekly.rooms)
    assert daily.source_fetched_at == weekly.source_fetched_at
    assert weekly.sources[0]["week_start"] == "2026-10-25"
    assert weekly.input_hash == load_directory(tmp_path / "weekly").input_hash


def test_two_weeks_select_target_dates_and_preserve_capture_age(tmp_path):
    write_weekly(tmp_path, start="2026-10-28", weeks=("2026-10-25", "2026-11-01"))
    bundle = load_directory(tmp_path)
    assert [str(d) for d in bundle.dates] == [f"2026-10-{d}" for d in range(28, 32)] + [
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ]
    assert len(bundle.coverage) == 14
    assert bundle.source_fetched_at.isoformat() == "2026-10-25T11:00:00+00:00"


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(inventory_scope="partial"),
        lambda m: m.pop("inventory_review_reason"),
        lambda m: m["weeks"].append(m["weeks"][0]),
        lambda m: m["weeks"][0].update(file="../secret.html"),
        lambda m: m["buildings"][0]["rooms"].pop(),
        lambda m: m["buildings"][0]["rooms"][0].update(capacity=99),
        lambda m: m.update(start_date="2026-10-28"),
    ],
)
def test_weekly_rejects_unreviewed_incomplete_or_ambiguous_inputs(tmp_path, change):
    manifest = write_weekly(tmp_path)
    change(manifest)
    save(tmp_path, manifest)
    with pytest.raises(IngestionError):
        load_directory(tmp_path)


def test_room_specific_bounds_never_extend_shorter_room(tmp_path):
    manifest = write_weekly(tmp_path)
    path = tmp_path / "week-2026-10-25.html"
    html = weekly_html((("SYN-A-101", 20, 2), ("SYN-A-102", 40, 4)))
    path.write_text(html, encoding="utf8")
    with pytest.raises(IngestionError, match="incomplete_timetable_window"):
        load_directory(tmp_path)
    manifest["buildings"][0]["rooms"][0]["window"] = {"start": "08:00", "end": "09:00"}
    save(tmp_path, manifest)
    bundle = load_directory(tmp_path)
    assert all(
        (c.ends_at - c.starts_at).total_seconds() == 3600
        for c in bundle.coverage
        if c.room_key[1] == "101"
    )


@pytest.mark.postgres
def test_weekly_stage_publish_idempotency_and_old_source_retention(postgres_engine, tmp_path):
    write_weekly(tmp_path)
    preview = import_directory(None, tmp_path, dry_run=True)
    assert preview["source_format"] == "weekly"
    staged = import_directory(postgres_engine, tmp_path)
    with Session(postgres_engine) as session:
        assert session.get_one(DatasetState, 1).active_dataset_id is None
    publish_dataset(postgres_engine, staged["dataset_id"])
    assert import_directory(postgres_engine, tmp_path)["status"] == "unchanged"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["weeks"][0]["fetched_at"] = "2026-10-24T11:00:00Z"
    save(tmp_path, manifest)
    candidate = import_directory(postgres_engine, tmp_path)
    with pytest.raises(IngestionError, match="older_source"):
        publish_dataset(postgres_engine, candidate["dataset_id"])
    with Session(postgres_engine) as session:
        assert str(session.get_one(DatasetState, 1).active_dataset_id) == staged["dataset_id"]
        assert len(session.exec(select(Room).where(Room.active)).all()) == 2


@pytest.mark.parametrize("week", ["2026-11-01", "2026-03-08"])
def test_weekly_never_guesses_dst_gap_or_fold(tmp_path, week):
    from bs4 import BeautifulSoup

    manifest = write_weekly(tmp_path, start=week, weeks=(week,))
    manifest["window"] = {"start": "01:00", "end": "03:00"}
    save(tmp_path, manifest)
    source = tmp_path / f"week-{week}.html"
    soup = BeautifulSoup(source.read_text(), "html.parser")
    for table in soup.select("table.tableform"):
        for index, row in enumerate(table.find_all("tr")[1:]):
            row.find("td").string = f"{1 + index // 2:02}:{index % 2 * 30:02}"
    source.write_text(str(soup), encoding="utf8")
    with pytest.raises(IngestionError, match="unresolved_local_time"):
        load_directory(tmp_path)


@pytest.mark.postgres
def test_weekly_inventory_reduction_requires_pipeline_review(postgres_engine, tmp_path):
    from bs4 import BeautifulSoup

    manifest = write_weekly(tmp_path)
    first = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, first["dataset_id"])
    manifest["buildings"][0]["rooms"].pop()
    manifest["weeks"][0]["fetched_at"] = "2026-10-25T12:00:00Z"
    save(tmp_path, manifest)
    source = tmp_path / "week-2026-10-25.html"
    soup = BeautifulSoup(source.read_text(), "html.parser")
    soup.select("table.tableform")[1].decompose()
    source.write_text(str(soup), encoding="utf8")
    with pytest.raises(IngestionError, match="review_required"):
        import_directory(postgres_engine, tmp_path)
    with Session(postgres_engine) as session:
        assert str(session.get_one(DatasetState, 1).active_dataset_id) == first["dataset_id"]
        assert len(session.exec(select(Room).where(Room.active)).all()) == 2
    candidate = import_directory(
        postgres_engine, tmp_path, review_reason="approved-inventory-change"
    )
    publish_dataset(postgres_engine, candidate["dataset_id"])
    with Session(postgres_engine) as session:
        assert len(session.exec(select(Room).where(Room.active)).all()) == 1
        assert len(session.exec(select(Room)).all()) == 2
