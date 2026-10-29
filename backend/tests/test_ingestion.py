from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from ingestion_helpers import write_bundle
from sqlalchemy import event, func, select, text
from sqlmodel import Session

from app.ingest.local import IngestionError
from app.ingest.pipeline import import_directory, ingestion_status, publish_dataset
from app.models import Dataset, DatasetState, IngestionRun, MeetingOccurrence, Room, RoomCoverage
from app.services.availability import find_available_rooms, room_schedule

pytestmark = pytest.mark.postgres
NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


def active(engine):
    with Session(engine) as session:
        return session.get(DatasetState, 1).active_dataset_id


def test_import_stages_then_publishes_seven_days_without_source_id_confusion(
    postgres_engine, tmp_path
):
    write_bundle(tmp_path)
    report = import_directory(postgres_engine, tmp_path)
    dataset = report["dataset_id"]
    assert active(postgres_engine) is None
    with Session(postgres_engine) as session:
        assert session.scalar(select(func.count()).select_from(MeetingOccurrence)) == 7
        assert session.scalar(select(func.count()).select_from(RoomCoverage)) == 14
        assert session.scalar(select(Room.id).where(Room.room_number == "101")) != 9001
        assert not session.scalar(select(Room.active).limit(1))
    publish_dataset(postgres_engine, dataset)
    assert str(active(postgres_engine)) == dataset
    with Session(postgres_engine) as session:
        for day in range(7):
            start = NOW + timedelta(days=day)
            result = find_available_rooms(
                session, start=start, end=start + timedelta(minutes=30), now=NOW
            )
            assert len(result.data) == 2
            assert result.data[0].next_booking == start + timedelta(minutes=30)
            assert result.meta.dataset_id == active(postgres_engine)
            assert (
                room_schedule(
                    session, result.data[0].room_id, start.date(), NOW
                ).meta.coverage.completeness
                == "partial"
            )
        busy = find_available_rooms(
            session, start=NOW + timedelta(minutes=30), end=NOW + timedelta(hours=1), now=NOW
        )
        assert [room.room_number for room in busy.data] == ["102"]
    same = import_directory(postgres_engine, tmp_path)
    assert same["dataset_id"] == dataset
    assert same["status"] == "unchanged"
    assert publish_dataset(postgres_engine, dataset)["status"] == "unchanged"


def test_dry_run_writes_nothing(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    report = import_directory(postgres_engine, tmp_path, dry_run=True)
    assert report["status"] == "dry_run"
    assert report["baseline_checked"] is False
    with Session(postgres_engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0
        assert session.scalar(select(func.count()).select_from(Room)) == 0


def test_bad_snapshot_records_failed_audit_and_keeps_last_good(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    first = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, first["dataset_id"])
    (tmp_path / "2026-10-15.html").write_text("<html>Not a timetable</html>", encoding="utf-8")
    with pytest.raises(IngestionError):
        import_directory(postgres_engine, tmp_path)
    assert str(active(postgres_engine)) == first["dataset_id"]
    with Session(postgres_engine) as session:
        failed = session.execute(
            select(IngestionRun).where(IngestionRun.status == "failed")
        ).scalar_one()
        assert len(failed.input_hash) == 64
        assert failed.error_code == "invalid_local_input"
        assert "Not a timetable" not in str(failed.counts)
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1


def test_booking_drop_requires_explicit_audited_review(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    first = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, first["dataset_id"])
    write_bundle(tmp_path, booking=False, fetched="2026-10-14T11:30:00Z")
    with pytest.raises(IngestionError, match="review_required"):
        import_directory(postgres_engine, tmp_path)
    assert str(active(postgres_engine)) == first["dataset_id"]
    second = import_directory(postgres_engine, tmp_path, review_reason="reviewed-holiday")
    publish_dataset(postgres_engine, second["dataset_id"])
    with Session(postgres_engine) as session:
        run = session.get(IngestionRun, session.get(Dataset, second["dataset_id"]).run_id)
        assert "booking_drop" in run.counts["anomalies"]
        assert run.counts["review_reason"] == "reviewed-holiday"


def test_unknown_cells_are_never_false_availability(postgres_engine, tmp_path):
    write_bundle(tmp_path, blocked=True, booking=False)
    with pytest.raises(IngestionError, match="review_required"):
        import_directory(postgres_engine, tmp_path)
    report = import_directory(postgres_engine, tmp_path, review_reason="reviewed-closed-rooms")
    publish_dataset(postgres_engine, report["dataset_id"])
    from app.errors import APIError

    with Session(postgres_engine) as session, pytest.raises(APIError, match="No trustworthy"):
        find_available_rooms(session, start=NOW, end=NOW + timedelta(minutes=30), now=NOW)


def test_staged_payload_tampering_cannot_be_published(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    report = import_directory(postgres_engine, tmp_path)
    with postgres_engine.begin() as connection:
        connection.execute(text("DELETE FROM utscvacant.meeting_occurrences"))
    with pytest.raises(IngestionError, match="candidate_changed"):
        publish_dataset(postgres_engine, report["dataset_id"])
    assert active(postgres_engine) is None


def test_publication_failure_rolls_back_every_write_and_keeps_audit(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    first = import_directory(postgres_engine, tmp_path)
    publish_dataset(postgres_engine, first["dataset_id"])
    write_bundle(tmp_path, fetched="2026-10-14T11:30:00Z")
    second = import_directory(postgres_engine, tmp_path)

    def fail_after_pointer(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE utscvacant.dataset_state"):
            raise RuntimeError("synthetic failure")

    event.listen(postgres_engine, "after_cursor_execute", fail_after_pointer)
    try:
        with pytest.raises(IngestionError):
            publish_dataset(postgres_engine, second["dataset_id"])
    finally:
        event.remove(postgres_engine, "after_cursor_execute", fail_after_pointer)
    assert str(active(postgres_engine)) == first["dataset_id"]
    with Session(postgres_engine) as session:
        dataset = session.get(Dataset, second["dataset_id"])
        assert dataset.published_at is None
        assert session.get(IngestionRun, dataset.run_id).status == "failed"


def test_concurrent_publishers_never_regress_source_time(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    older = import_directory(postgres_engine, tmp_path)["dataset_id"]
    write_bundle(tmp_path, fetched="2026-10-14T11:30:00Z")
    newer = import_directory(postgres_engine, tmp_path)["dataset_id"]

    def publish(dataset):
        try:
            return publish_dataset(postgres_engine, dataset)["status"]
        except IngestionError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(publish, [newer, older]))
    assert str(active(postgres_engine)) == newer
    assert set(results) <= {"published", "older_source"}
    assert ingestion_status(postgres_engine)["active_dataset_id"] == newer


def test_status_never_includes_raw_input_or_database_url(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    import_directory(postgres_engine, tmp_path)
    output = ingestion_status(postgres_engine)
    assert len(output["runs"]) == 1
    assert "postgresql" not in str(output)
    assert "Synthetic event" not in str(output)


def test_same_input_concurrent_imports_share_one_candidate(postgres_engine, tmp_path):
    from threading import Barrier

    write_bundle(tmp_path)
    ready = Barrier(2)

    def stage(_):
        ready.wait(timeout=5)
        return import_directory(postgres_engine, tmp_path)["dataset_id"]

    with ThreadPoolExecutor(max_workers=2) as workers:
        datasets = list(workers.map(stage, range(2)))
    assert len(set(datasets)) == 1
    with Session(postgres_engine) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 1
        assert session.scalar(select(func.count()).select_from(MeetingOccurrence)) == 7


def test_publish_rechecks_anomalies_against_new_active_baseline(postgres_engine, tmp_path):
    write_bundle(tmp_path, fetched="2026-10-14T11:30:00Z")
    for path in tmp_path.glob("*.html"):
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "<td>&nbsp;</td>", '<td class="event">Synthetic extra event</td>'
            ),
            encoding="utf-8",
        )
    busy = import_directory(postgres_engine, tmp_path)["dataset_id"]
    write_bundle(tmp_path, fetched="2026-10-14T11:45:00Z")
    quiet = import_directory(postgres_engine, tmp_path)["dataset_id"]
    publish_dataset(postgres_engine, busy)
    with pytest.raises(IngestionError, match="review_required"):
        publish_dataset(postgres_engine, quiet)
    assert str(active(postgres_engine)) == busy
    with Session(postgres_engine) as session:
        run = session.get(IngestionRun, session.get(Dataset, quiet).run_id)
        assert run.counts["publication_anomalies"] == ["booking_drop"]


def test_one_older_daily_capture_cannot_hide_behind_newer_aggregate_age(postgres_engine, tmp_path):
    import json

    manifest = write_bundle(tmp_path, fetched="2026-10-14T12:00:00Z")
    manifest["snapshots"][0]["fetched_at"] = "2026-10-14T11:00:00Z"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    first = import_directory(postgres_engine, tmp_path)["dataset_id"]
    publish_dataset(postgres_engine, first)
    manifest = write_bundle(tmp_path, fetched="2026-10-14T12:30:00Z")
    manifest["snapshots"][1]["fetched_at"] = "2026-10-14T11:30:00Z"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    second = import_directory(postgres_engine, tmp_path)["dataset_id"]
    with pytest.raises(IngestionError, match="older_source"):
        publish_dataset(postgres_engine, second)
    assert str(active(postgres_engine)) == first


@pytest.mark.parametrize("day,utc_hour", [("2026-03-07", 13), ("2026-10-31", 12)])
def test_ingested_dst_week_through_existing_fastapi(
    postgres_engine, tmp_path, monkeypatch, day, utc_hour
):
    from fastapi.testclient import TestClient

    from app import db
    from app.main import create_app, utc_now
    from app.settings import Settings

    write_bundle(tmp_path, first=day, fetched="2026-01-01T11:00:00Z")
    dataset = import_directory(postgres_engine, tmp_path)["dataset_id"]
    publish_dataset(postgres_engine, dataset)
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    now = datetime.fromisoformat(day).replace(hour=utc_hour, tzinfo=UTC)
    app = create_app(Settings())
    app.dependency_overrides[utc_now] = lambda: now
    with TestClient(app) as client:
        for offset in [0, 1]:
            start = (now + timedelta(days=offset)).replace(
                hour=utc_hour if offset == 0 else (12 if utc_hour == 13 else 13)
            )
            result = client.get(
                "/api/v1/availability", params={"start": start.isoformat(), "duration_minutes": 30}
            )
            assert result.status_code == 200
            body = result.json()
            assert len(body["data"]) == 2
            assert body["meta"]["dataset_id"] == dataset
            assert body["meta"]["freshness"] == "stale"
            schedule = client.get(
                f"/api/v1/rooms/{body['data'][0]['room_id']}/schedule",
                params={"date": str(start.date())},
            ).json()
            assert schedule["data"][0]["starts_at"].endswith(f"{start.hour:02}:30:00Z")
        assert client.get("/api/v1/buildings").json()["data"][0]["code"] == "SYN-A"
        assert client.get("/api/v1/status").json()["dataset_id"] == dataset


def test_synthetic_ten_building_sixty_seven_room_week(postgres_engine, tmp_path):
    from ingestion_helpers import write_large_bundle

    write_large_bundle(tmp_path)
    report = import_directory(postgres_engine, tmp_path)
    assert report["rooms"] == 67
    assert report["buildings"] == 10
    assert report["coverage"] == report["occurrences"] == 469
    publish_dataset(postgres_engine, report["dataset_id"])
    with Session(postgres_engine) as session:
        result = find_available_rooms(
            session, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2), now=NOW
        )
        assert len(result.data) == 50
        assert result.meta.has_more is True
        assert result.meta.unknown_room_count == 0
        assert result.data[0].next_booking == NOW + timedelta(days=1)


def test_partial_local_source_excludes_only_uncertain_window(postgres_engine, tmp_path):
    write_bundle(tmp_path)
    path = tmp_path / "2026-10-14.html"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "<td>&nbsp;</td>", '<td class="blocked">&nbsp;</td>', 1
        ),
        encoding="utf-8",
    )
    report = import_directory(postgres_engine, tmp_path, review_reason="reviewed-unknown-slot")
    publish_dataset(postgres_engine, report["dataset_id"])
    with Session(postgres_engine) as session:
        uncertain = find_available_rooms(
            session, start=NOW, end=NOW + timedelta(minutes=30), now=NOW
        )
        assert [room.room_number for room in uncertain.data] == ["102"]
        assert uncertain.meta.unknown_room_count == 1
        covered = find_available_rooms(
            session, start=NOW + timedelta(minutes=90), end=NOW + timedelta(minutes=120), now=NOW
        )
        assert len(covered.data) == 2
        from app.errors import APIError

        with pytest.raises(APIError) as failure:
            find_available_rooms(
                session, start=NOW + timedelta(hours=12), end=NOW + timedelta(hours=13), now=NOW
            )
        assert failure.value.code == "coverage_unavailable"
