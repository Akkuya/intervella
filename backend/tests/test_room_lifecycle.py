import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from ingestion_helpers import write_bundle
from sqlalchemy import event, func, select, text
from sqlmodel import Session

from app import db
from app.ingest.local import IngestionError
from app.ingest.pipeline import import_directory, publish_dataset
from app.main import create_app, utc_now
from app.models import Dataset, DatasetState, MeetingOccurrence, Room, RoomCoverage
from app.settings import Settings

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("authenticated_student")]
NOW = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def inventory(directory, *, reduced=False, fetched="2026-10-14T11:00:00Z"):
    manifest = write_bundle(directory, fetched=fetched, booking=False)
    building = manifest["buildings"][0]
    if reduced:
        building["rooms"] = building["rooms"][:1]
    else:
        manifest["buildings"].append(
            {
                "source_name": "Synthetic B",
                "code": "SYN-B",
                "name": "Synthetic B",
                "rooms": [{"source_name": "SYN-B-201", "room_number": "201", "source_id": 9101}],
            }
        )
    for path in directory.glob("*.html"):
        tables = []
        for building in manifest["buildings"]:
            headers = "".join(
                f'<th class="smallth"><a href="?rfilter={room["source_id"]}">'
                f"{room['source_name']} (20)</a></th>"
                for room in building["rooms"]
            )
            rows = []
            for minute in [480, 510, 540, 570]:
                cells = "".join(
                    '<td class="event">Synthetic booking</td>'
                    if room["room_number"] == "102" and minute == 480
                    else "<td>&nbsp;</td>"
                    for room in building["rooms"]
                )
                rows.append(
                    f'<tr><td class="time">{minute // 60:02}:{minute % 60:02}</td>{cells}</tr>'
                )
            tables.append(
                f'<table class="tableform"><caption>{building["source_name"]}</caption>'
                f"<thead><tr><th></th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            )
        path.write_text(
            f'<input id="labtime" value="{path.stem}"><div id="contentwrapper">'
            f"{''.join(tables)}</div>",
            encoding="utf-8",
        )
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_reviewed_reduction_retires_rooms_preserves_history_and_can_reactivate(
    postgres_engine, tmp_path, monkeypatch
):
    inventory(tmp_path)
    first = import_directory(postgres_engine, tmp_path)["dataset_id"]
    publish_dataset(postgres_engine, first)
    with Session(postgres_engine) as session:
        ids = {room.room_number: room.id for room in session.scalars(select(Room))}
    inventory(tmp_path, reduced=True, fetched="2026-10-14T11:30:00Z")
    with pytest.raises(IngestionError, match="review_required"):
        import_directory(postgres_engine, tmp_path)
    second = import_directory(
        postgres_engine, tmp_path, review_reason="reviewed-inventory-reduction"
    )
    assert "room_inventory_changed" in second["anomalies"]
    with Session(postgres_engine) as session:
        assert all(room.active for room in session.scalars(select(Room)))
        assert str(session.get(DatasetState, 1).active_dataset_id) == first
    publish_dataset(postgres_engine, second["dataset_id"])
    with Session(postgres_engine) as session:
        assert {room.room_number: room.active for room in session.scalars(select(Room))} == {
            "101": True,
            "102": False,
            "201": False,
        }
        assert (
            session.scalar(
                select(func.count())
                .select_from(RoomCoverage)
                .where(RoomCoverage.dataset_id == first)
            )
            == 21
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MeetingOccurrence)
                .where(MeetingOccurrence.dataset_id == first)
            )
            == 7
        )
    monkeypatch.setattr(db, "get_engine", lambda: postgres_engine)
    app = create_app(Settings())
    app.dependency_overrides[utc_now] = lambda: NOW
    with TestClient(app) as client:
        assert [item["code"] for item in client.get("/api/v1/buildings").json()["data"]] == [
            "SYN-A"
        ]
        result = client.get(
            "/api/v1/availability", params={"start": NOW.isoformat(), "duration_minutes": 30}
        ).json()
        assert [room["room_id"] for room in result["data"]] == [ids["101"]]
        assert result["meta"]["unknown_room_count"] == 0
        status = client.get("/api/v1/status").json()
        assert status["unknown_room_count"] == 0 and status["degraded"] is False
        for retired in ["102", "201"]:
            response = client.get(f"/api/v1/rooms/{ids[retired]}")
            assert response.status_code == 200
            assert response.json()["data"]["active"] is False
            schedule = client.get(
                f"/api/v1/rooms/{ids[retired]}/schedule", params={"date": "2026-10-14"}
            ).json()
            assert schedule["room"]["active"] is False
            assert schedule["meta"]["coverage"]["completeness"] == "unknown"
    inventory(tmp_path, fetched="2026-10-14T11:45:00Z")
    restored = import_directory(postgres_engine, tmp_path, review_reason="reviewed-room-return")
    publish_dataset(postgres_engine, restored["dataset_id"])
    with Session(postgres_engine) as session:
        assert {room.room_number: room.id for room in session.scalars(select(Room))} == ids
        assert all(room.active for room in session.scalars(select(Room)))


def test_failed_reduction_rolls_back_room_retirement_and_pointer(postgres_engine, tmp_path):
    inventory(tmp_path)
    first = import_directory(postgres_engine, tmp_path)["dataset_id"]
    publish_dataset(postgres_engine, first)
    inventory(tmp_path, reduced=True, fetched="2026-10-14T11:30:00Z")
    second = import_directory(
        postgres_engine, tmp_path, review_reason="reviewed-inventory-reduction"
    )
    retired_before_rollback = []

    def fail_after_pointer(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE utscvacant.dataset_state"):
            retired_before_rollback.extend(
                connection.scalars(
                    text(
                        "SELECT room_number FROM utscvacant.rooms "
                        "WHERE NOT active ORDER BY room_number"
                    )
                )
            )
            raise RuntimeError("synthetic publication failure")

    event.listen(postgres_engine, "after_cursor_execute", fail_after_pointer)
    try:
        with pytest.raises(IngestionError):
            publish_dataset(postgres_engine, second["dataset_id"])
    finally:
        event.remove(postgres_engine, "after_cursor_execute", fail_after_pointer)
    assert retired_before_rollback == ["102", "201"]
    with Session(postgres_engine) as session:
        assert str(session.get(DatasetState, 1).active_dataset_id) == first
        assert all(room.active for room in session.scalars(select(Room)))
        assert session.get(Dataset, second["dataset_id"]).published_at is None
