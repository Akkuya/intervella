"""Synthetic regressions for multiweek imports. Added without executing tests."""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from ingestion_helpers import snapshot, write_bundle
from sqlalchemy import select
from sqlmodel import Session
from test_manifest_generation import approved
from test_operator import authenticated
from test_operator_generation import approve, upload
from test_weekly_ingestion import write_weekly

from app.errors import APIError
from app.ingest.local import IngestionError, Window, local_instant
from app.ingest.pipeline import import_directory, publish_dataset, publish_datasets
from app.ingest.weekly_load import WeeklyManifest
from app.models import ActivePeriod, Dataset, DatasetSource, Room
from app.operator.app import create_operator_app
from app.operator.coverage import reviewed_windows
from app.operator.discovery import discover_sources
from app.operator.manifests import analyze_sources
from app.services.availability import find_available_rooms, room_schedule
from app.services.room_search import search_rooms
from app.services.calendar import building_schedule
from app.schemas import RoomSearchParams


def test_discovery_never_uses_filename_or_clock_for_year_or_capture(tmp_path):
    write_weekly(tmp_path)
    unresolved = discover_sources(tmp_path)
    assert not unresolved["groups"]
    assert unresolved["exceptions"][0]["code"] == "source_year_required"
    resolved = discover_sources(tmp_path, year=2026)
    assert resolved["groups"][0]["start_date"] == "2026-10-25"
    assert "fetched_at" not in json.dumps(resolved)


def test_discovery_groups_daily_weeks_and_does_not_fill_missing_days(tmp_path):
    for day in (date(2026, 10, 25), date(2026, 11, 1)):
        (tmp_path / f"{day}.html").write_text(snapshot(day, booking=False), encoding="utf8")
    found = discover_sources(tmp_path)
    assert [g["start_date"] for g in found["groups"]] == ["2026-10-25", "2026-11-01"]
    for group in found["groups"]:
        directory = tmp_path / group["start_date"]
        directory.mkdir()
        for source in group["files"]:
            (directory / source["file"]).write_bytes((tmp_path / source["file"]).read_bytes())
        analysis = analyze_sources(directory, date.fromisoformat(group["start_date"]))
        assert len(analysis["missing_sources"]) == 6


def test_discovery_rejects_competing_sources_and_retains_independent_weeks(tmp_path):
    write_weekly(tmp_path, weeks=("2026-10-25", "2026-11-01"))
    source = tmp_path / "week-2026-10-25.html"
    (tmp_path / "different.html").write_bytes(source.read_bytes() + b"\n")
    found = discover_sources(tmp_path, year=2026)
    assert found["groups"][0]["blocking"] == ["duplicate_source_period"]
    assert found["groups"][1]["blocking"] == []
    (tmp_path / "different.html").write_bytes(source.read_bytes())
    assert discover_sources(tmp_path, year=2026)["exceptions"][0]["code"] == "identical_duplicate_ignored"
    (tmp_path / "daily.html").write_text(snapshot("2026-11-01", booking=False), encoding="utf8")
    assert "competing_daily_weekly_sources" in discover_sources(tmp_path, year=2026)["groups"][1]["blocking"]


def test_year_rollover_and_truncated_document_fail_closed(tmp_path):
    write_weekly(tmp_path, start="2026-12-27", weeks=("2026-12-27",))
    assert discover_sources(tmp_path, year=2026)["groups"][0]["start_date"] == "2026-12-27"
    source = next(tmp_path.glob("*.html"))
    source.write_text(source.read_text().replace("</html>", ""))
    assert discover_sources(tmp_path, year=2026)["exceptions"][0]["code"] == "incomplete_source_document"


def test_bulk_window_review_requires_eligible_grid_and_preserves_inventory(tmp_path):
    write_weekly(tmp_path)
    original = analyze_sources(tmp_path, date(2026, 10, 25))
    profile = approved(original)
    profile.buildings[0].rooms[0].window = Window(start="08:00", end="11:00")
    analysis = analyze_sources(tmp_path, date(2026, 10, 25), profile)
    draft = analysis["draft"]
    draft["weeks"][0].update(fetched_at="2026-10-25T11:00:00Z", capture_evidence="Synthetic capture log")
    draft["inventory_review_reason"] = "observed-grid-review"
    draft["buildings"][0]["rooms"][0]["window"] = {"start": "08:00", "end": "10:00"}
    manifest = WeeklyManifest.model_validate(draft)
    with pytest.raises(IngestionError, match="coverage_window_not_eligible"):
        reviewed_windows(manifest, profile, analysis, False)
    changes = reviewed_windows(manifest, profile, analysis, True)
    assert changes[0]["expected"]["end"] == "11:00"
    assert changes[0]["observed"]["end"] == "10:00"
    assert profile.buildings[0].rooms[0].window.end == "11:00"
    invalid = copy.deepcopy(analysis)
    invalid["observed_rooms"][0]["bulk_eligible"] = False
    with pytest.raises(IngestionError, match="coverage_window_not_eligible"):
        reviewed_windows(manifest, profile, invalid, True)
    manifest.buildings[0].rooms[0].capacity = 999
    with pytest.raises(IngestionError):
        reviewed_windows(manifest, profile, analysis, True)


@pytest.mark.postgres
def test_atomic_multiweek_publish_replacement_and_date_queries(postgres_engine, tmp_path):
    ids = []
    for week in ("2026-10-25", "2026-11-01", "2026-11-08"):
        directory = tmp_path / week
        write_weekly(directory, start=week, weeks=(week,), fetched="2026-10-25T11:00:00Z")
        ids.append(import_directory(postgres_engine, directory)["dataset_id"])
    publish_datasets(postgres_engine, ids, expected_baseline="")
    with Session(postgres_engine) as session:
        assert len(session.scalars(select(ActivePeriod)).all()) == 3
        stable = {r.room_number: r.id for r in session.scalars(select(Room))}
        for day in (date(2026, 10, 25), date(2026, 11, 1), date(2026, 11, 8)):
            left = local_instant(day, 480)
            result = find_available_rooms(session, start=left, end=left+timedelta(minutes=30),
                                          now=local_instant(date(2026, 10, 25), 480))
            assert len(result.data) == 2
            assert result.meta.sources[0]["date"] == day
            room_schedule(session, result.data[0].room_id, day, left)
            building_schedule(session, "SYN-A", day, left)
            search_rooms(session, RoomSearchParams(start=left), left)
    directory = tmp_path / "replacement"
    write_weekly(directory, start="2026-11-01", weeks=("2026-11-01",), fetched="2026-10-25T12:00:00Z")
    replacement = import_directory(postgres_engine, directory)["dataset_id"]
    publish_dataset(postgres_engine, replacement)
    with Session(postgres_engine) as session:
        active = {str(p.dataset_id) for p in session.scalars(select(ActivePeriod))}
        assert active == {ids[0], replacement, ids[2]}
        assert session.get(Dataset, UUID(ids[1])).published_at is not None
        assert stable == {r.room_number: r.id for r in session.scalars(select(Room))}
        assert len(session.scalars(select(DatasetSource).where(DatasetSource.dataset_id == UUID(replacement))).all()) == 7


@pytest.mark.postgres
def test_older_snapshot_rolls_back_entire_publication_selection(postgres_engine, tmp_path):
    original = tmp_path / "original"
    write_weekly(original)
    first = import_directory(postgres_engine, original)["dataset_id"]
    publish_dataset(postgres_engine, first)
    future = tmp_path / "future"
    write_weekly(future, start="2026-11-01", weeks=("2026-11-01",))
    next_id = import_directory(postgres_engine, future)["dataset_id"]
    old = tmp_path / "older"
    write_weekly(old, fetched="2026-10-24T11:00:00Z")
    old_id = import_directory(postgres_engine, old)["dataset_id"]
    with pytest.raises(IngestionError, match="older_source"):
        publish_datasets(postgres_engine, [next_id, old_id])
    with Session(postgres_engine) as session:
        assert [str(p.dataset_id) for p in session.scalars(select(ActivePeriod))] == [first]
        assert session.get(Dataset, UUID(next_id)).published_at is None


@pytest.mark.postgres
def test_cross_week_union_never_bridges_missing_coverage(postgres_engine, tmp_path):
    ids = []
    for start, window_start, slots in (("2026-10-18", 1380, 2), ("2026-10-25", 0, 2)):
        directory = tmp_path / start
        write_bundle(directory, first=start, start=window_start, slots=slots, booking=False,
                     fetched="2026-10-18T11:00:00Z")
        ids.append(import_directory(postgres_engine, directory)["dataset_id"])
    publish_datasets(postgres_engine, ids)
    start = local_instant(date(2026, 10, 24), 1410)
    with Session(postgres_engine) as session:
        result = find_available_rooms(session, start=start, end=start+timedelta(hours=1), now=start)
        assert len(result.data) == 2 and len(result.meta.dataset_ids) == 2
        with pytest.raises(APIError):
            find_available_rooms(session, start=start, end=start+timedelta(hours=2), now=start)


@pytest.mark.parametrize("day,minute", [(date(2026, 11, 1), 90), (date(2026, 3, 8), 150)])
def test_ambiguous_or_missing_dst_hour_stays_unresolved(day, minute):
    with pytest.raises(IngestionError, match="unresolved_local_time"):
        local_instant(day, minute)


def test_discovery_review_requires_capture_evidence_and_records_window_audit(tmp_path):
    source = tmp_path / "source"
    write_weekly(source)
    with TestClient(create_operator_app(secret="s"*40, storage=tmp_path / "private"),
                    base_url="http://localhost:8765") as client:
        headers = authenticated(client)
        key = upload(client, headers, source)
        first = client.post(f"/ops/batches/{key}/analyze", headers=headers,
                            json={"start_date": "2026-10-25"}).json()
        first["draft"]["buildings"][0]["rooms"][0]["window"] = {"start": "08:00", "end": "11:00"}
        approve(client, headers, first)
        grouped = client.post(f"/ops/batches/{key}/discover", headers=headers, json={"year": 2026}).json()
        group = grouped["groups"][0]
        analysis = group["analysis"]
        manifest = analysis["draft"]
        manifest["inventory_review_reason"] = "source-review"
        manifest["buildings"][0]["rooms"][0]["window"] = {"start": "08:00", "end": "10:00"}
        manifest["weeks"][0]["fetched_at"] = "2026-10-25T11:00:00Z"
        body = {"analysis_hash": analysis["analysis_hash"], "profile_version": 1,
                "manifest": manifest, "review_reason": "source-review", "review_acknowledged": True,
                "windows_acknowledged": True, "target_acknowledged": True, "capture_acknowledged": True}
        endpoint = f"/ops/batches/{group['batch_id']}/manifest"
        rejected = client.post(endpoint, headers=headers, json=body)
        assert rejected.json()["error"]["code"] == "capture_evidence_required"
        manifest["weeks"][0]["capture_evidence"] = "Synthetic recorded retrieval"
        accepted = client.post(endpoint, headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        audit = accepted.json()["manifest"]["review_audit"]
        assert audit["date_evidence"][0]["date_evidence"] == "operator-confirmed-start-year"
        assert audit["coverage_scope"] == "this_period"
        assert audit["coverage_changes"][0]["expected"]["end"] == "11:00"
        persistent = client.post(f"/ops/batches/{group['batch_id']}/coverage-profile", headers=headers,
            json={"analysis_hash": analysis["analysis_hash"], "profile_version": 1,
                  "buildings": manifest["buildings"], "review_reason": "future-window-review",
                  "review_acknowledged": True})
        assert persistent.status_code == 200, persistent.text
        saved = persistent.json()["profile"]
        assert saved["version"] == 2
        assert saved["window_review_audit"]["scope"] == "future_imports"
        assert saved["window_review_audit"]["sources"][0]["sha256"]


@pytest.mark.postgres
def test_freshness_uses_queried_source_day_and_overlap_is_rejected(postgres_engine, tmp_path):
    source = tmp_path / "daily"
    manifest = write_bundle(source, first="2026-10-25", booking=False, fetched="2026-10-20T11:00:00Z")
    manifest["snapshots"][-1]["fetched_at"] = "2026-10-30T11:00:00Z"
    (source / "manifest.json").write_text(json.dumps(manifest))
    candidate = import_directory(postgres_engine, source)["dataset_id"]
    publish_dataset(postgres_engine, candidate)
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    start = local_instant(date(2026, 10, 31), 480)
    with Session(postgres_engine) as session:
        result = find_available_rooms(session, start=start, end=start+timedelta(minutes=30), now=now)
        assert result.meta.freshness == "fresh"
        assert result.meta.source_fetched_at == datetime(2026, 10, 30, 11, tzinfo=UTC)
    rolling = tmp_path / "rolling"
    write_weekly(rolling, start="2026-10-28", weeks=("2026-10-25", "2026-11-01"))
    with pytest.raises(IngestionError, match="overlapping_active_period"):
        import_directory(postgres_engine, rolling)
