"""Audited staging and serialized, atomic publication. No network transport."""

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from app.ingest.local import PARSER_VERSION, Bundle, IngestionError, load_directory
from app.models import (
    Building,
    Dataset,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)

# Same transaction lock for staging/publication; never use a pooled session advisory lock.
LOCK_KEY = 8506374104


def _reason(value: str | None) -> str | None:
    if value is not None and not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise IngestionError("invalid_review_reason")
    return value


def _lock(session: Session) -> DatasetState:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
    return session.execute(
        select(DatasetState).where(col(DatasetState.id) == 1).with_for_update()
    ).scalar_one()


def _failed(
    engine: Engine,
    code: str,
    input_hash: str,
    run_id: UUID | None = None,
    report: dict | None = None,
) -> UUID:
    with Session(engine) as session, session.begin():
        now = datetime.now(UTC)
        run = session.get(IngestionRun, run_id) if run_id else None
        if run is None:
            run = IngestionRun(started_at=now, input_hash=input_hash)
        run.status = "failed"
        run.finished_at = max(now, run.started_at)
        run.error_code = code
        if report:
            run.counts = {**run.counts, **report}
        session.add(run)
        session.flush()
        return run.id


def _failure(
    engine: Engine, exc: Exception, input_hash: str, run_id: UUID | None = None
) -> IngestionError:
    failure = exc if isinstance(exc, IngestionError) else IngestionError("ingestion_failed")
    try:
        failure.run_id = _failed(engine, failure.code, input_hash, run_id, failure.report)
    except Exception:
        return IngestionError("audit_unavailable")
    return failure


def _digest(session: Session, dataset_id: UUID) -> str:
    coverage = session.execute(
        select(
            col(RoomCoverage.room_id),
            col(RoomCoverage.starts_at),
            col(RoomCoverage.ends_at),
            col(RoomCoverage.completeness),
        )
        .where(col(RoomCoverage.dataset_id) == dataset_id)
        .order_by(col(RoomCoverage.room_id), col(RoomCoverage.starts_at))
    ).all()
    meetings = session.execute(
        select(
            col(MeetingOccurrence.room_id),
            col(MeetingOccurrence.source_key),
            col(MeetingOccurrence.starts_at),
            col(MeetingOccurrence.ends_at),
            col(MeetingOccurrence.status),
        )
        .where(col(MeetingOccurrence.dataset_id) == dataset_id)
        .order_by(col(MeetingOccurrence.source_key))
    ).all()
    identities = session.execute(
        select(col(Room.id), col(Building.code), col(Room.room_number))
        .join(Building)
        .where(col(Room.id).in_({row.room_id for row in coverage}))
        .order_by(col(Room.id))
    ).all()
    payload = [[list(row) for row in rows] for rows in [coverage, meetings, identities]]
    return hashlib.sha256(
        json.dumps(payload, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _anomalies(
    session: Session, dataset: Dataset, counts: dict, active_id: UUID | None
) -> list[str]:
    anomalies = []
    if counts["unknown_rooms"] > counts["rooms"] * 0.02:
        anomalies.append("unknown_room_rate")
    if active_id is None:
        return anomalies
    previous_rooms = set(
        session.scalars(
            select(col(RoomCoverage.room_id))
            .where(col(RoomCoverage.dataset_id) == active_id)
            .distinct()
        )
    )
    rooms = set(
        session.scalars(
            select(col(RoomCoverage.room_id))
            .where(col(RoomCoverage.dataset_id) == dataset.id)
            .distinct()
        )
    )
    if previous_rooms != rooms:
        anomalies.append("room_inventory_changed")
    previous = session.get_one(Dataset, active_id)
    previous_counts = session.get_one(IngestionRun, previous.run_id).counts
    previous_meetings = (
        session.scalar(
            select(func.count())
            .select_from(MeetingOccurrence)
            .where(
                col(MeetingOccurrence.dataset_id) == active_id,
                col(MeetingOccurrence.status) == "scheduled",
            )
        )
        or 0
    )
    candidate_meetings = (
        session.scalar(
            select(func.count())
            .select_from(MeetingOccurrence)
            .where(
                col(MeetingOccurrence.dataset_id) == dataset.id,
                col(MeetingOccurrence.status) == "scheduled",
            )
        )
        or 0
    )
    old_days = max(1, len(previous_counts.get("dates", [])))
    new_days = len(counts["dates"])
    if candidate_meetings / new_days < (previous_meetings / old_days) * 0.8:
        anomalies.append("booking_drop")
    return anomalies


def import_directory(
    engine: Engine | None,
    directory: Path,
    *,
    dry_run: bool = False,
    review_reason: str | None = None,
) -> dict:
    """Parse and validate before writing; commit a candidate, never the active pointer."""
    run_id = None
    input_hash = hashlib.sha256(b"unreadable-local-input").hexdigest()
    try:
        bundle = load_directory(directory)
        input_hash = bundle.input_hash
        reason = _reason(review_reason)
        if dry_run:
            report = bundle.report()
            anomalies = (
                ["unknown_room_rate"] if report["unknown_rooms"] > report["rooms"] * 0.02 else []
            )
            return {
                **report,
                "status": "dry_run",
                "baseline_checked": False,
                "anomalies": anomalies,
                "requires_review": bool(anomalies and not reason),
            }
        if engine is None:
            raise IngestionError("database_required")
        with Session(engine) as session, session.begin():
            run = IngestionRun(started_at=datetime.now(UTC), input_hash=input_hash)
            session.add(run)
            session.flush()
            run_id = run.id
        return _stage(engine, bundle, run_id, reason)
    except Exception as exc:
        if isinstance(exc, IngestionError) and exc.input_hash:
            input_hash = exc.input_hash
        if dry_run or engine is None:
            raise (
                exc if isinstance(exc, IngestionError) else IngestionError("invalid_local_input")
            ) from None
        raise _failure(engine, exc, input_hash, run_id) from None


def _stage(engine: Engine, bundle: Bundle, run_id: UUID, reason: str | None) -> dict:
    with Session(engine) as session, session.begin():
        state = _lock(session)
        run = session.get_one(IngestionRun, run_id)
        existing = session.execute(
            select(Dataset)
            .join(IngestionRun)
            .where(
                col(IngestionRun.input_hash) == bundle.input_hash,
                col(IngestionRun.status) == "succeeded",
            )
            .order_by(col(Dataset.source_fetched_at).desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing:
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            run.counts = {"reused_dataset_id": str(existing.id)}
            session.add(run)
            return {"status": "unchanged", "dataset_id": str(existing.id), "run_id": str(run.id)}
        dataset = Dataset(run_id=run.id, source_fetched_at=bundle.source_fetched_at)
        session.add(dataset)
        session.flush()
        room_ids: dict[tuple[str, str], int] = {}
        for room in bundle.rooms:
            session.execute(
                insert(Building)
                .values(code=room.building_code, name=room.building_name)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            building_id = session.scalar(
                select(col(Building.id)).where(col(Building.code) == room.building_code)
            )
            session.execute(
                insert(Room)
                .values(
                    building_id=building_id,
                    room_number=room.room_number,
                    capacity=room.capacity,
                    active=False,
                )
                .on_conflict_do_nothing(index_elements=["building_id", "room_number"])
            )
            room_id = session.scalar(
                select(col(Room.id)).where(
                    col(Room.building_id) == building_id, col(Room.room_number) == room.room_number
                )
            )
            assert room_id is not None
            room_ids[room.key] = room_id
        session.add_all(
            [
                RoomCoverage(
                    dataset_id=dataset.id,
                    room_id=room_ids[item.room_key],
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    completeness=item.completeness,
                )
                for item in bundle.coverage
            ]
        )
        session.add_all(
            [
                MeetingOccurrence(
                    dataset_id=dataset.id,
                    room_id=room_ids[item.room_key],
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    status=item.status,
                    source_key=item.source_key,
                )
                for item in bundle.meetings
            ]
        )
        session.flush()
        counts = {
            **bundle.report(),
            "parser_version": PARSER_VERSION,
            "sources": list(bundle.sources),
            "room_records": [asdict(room) for room in bundle.rooms],
            "baseline_dataset_id": str(state.active_dataset_id)
            if state.active_dataset_id
            else None,
        }
        anomalies = _anomalies(session, dataset, counts, state.active_dataset_id)
        if anomalies and reason is None:
            raise IngestionError(
                "review_required", report={**bundle.report(), "anomalies": anomalies}
            )
        counts.update(
            anomalies=anomalies, review_reason=reason, candidate_digest=_digest(session, dataset.id)
        )
        run.counts = counts
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        session.add(run)
        return {
            "status": "staged",
            "dataset_id": str(dataset.id),
            "run_id": str(run.id),
            **bundle.report(),
            "anomalies": anomalies,
        }


def publish_dataset(
    engine: Engine, dataset_id: str | UUID, *, review_reason: str | None = None
) -> dict:
    run_id = None
    input_hash = hashlib.sha256(b"unknown-candidate").hexdigest()
    try:
        reason = _reason(review_reason)
        dataset_id = UUID(str(dataset_id))
        with Session(engine) as session, session.begin():
            state = _lock(session)
            dataset = session.execute(
                select(Dataset).where(col(Dataset.id) == dataset_id).with_for_update()
            ).scalar_one_or_none()
            if dataset is None:
                raise IngestionError("dataset_not_found")
            if state.active_dataset_id == dataset.id:
                return {"status": "unchanged", "dataset_id": str(dataset.id)}
            if dataset.published_at is not None:
                raise IngestionError("already_published")
            run_id = dataset.run_id
            run = session.execute(
                select(IngestionRun).where(col(IngestionRun.id) == run_id).with_for_update()
            ).scalar_one()
            input_hash = run.input_hash
            counts = run.counts
            if run.status != "succeeded" or counts.get("parser_version") != PARSER_VERSION:
                raise IngestionError("candidate_not_validated")
            if counts.get("candidate_digest") != _digest(session, dataset.id):
                raise IngestionError("candidate_changed")
            previous = (
                session.get_one(Dataset, state.active_dataset_id)
                if state.active_dataset_id
                else None
            )
            if previous and dataset.source_fetched_at <= previous.source_fetched_at:
                raise IngestionError("older_source")
            if previous:
                previous_run = session.get_one(IngestionRun, previous.run_id)
                old_sources = {
                    item["date"]: item for item in previous_run.counts.get("sources", [])
                }
                for source in counts["sources"]:
                    old = old_sources.get(source["date"])
                    if old and (
                        source["fetched_at"] < old["fetched_at"]
                        or (
                            source["fetched_at"] == old["fetched_at"]
                            and source["sha256"] != old["sha256"]
                        )
                    ):
                        raise IngestionError("older_source")
            anomalies = _anomalies(session, dataset, counts, state.active_dataset_id)
            baseline = str(state.active_dataset_id) if state.active_dataset_id else None
            saved_reason = (
                counts.get("review_reason") if counts["baseline_dataset_id"] == baseline else None
            )
            if anomalies and not (reason or saved_reason):
                raise IngestionError("review_required", report={"publication_anomalies": anomalies})
            for room_record in counts["room_records"]:
                building = session.execute(
                    select(Building).where(col(Building.code) == room_record["building_code"])
                ).scalar_one()
                building.name = room_record["building_name"]
                room = session.execute(
                    select(Room).where(
                        col(Room.building_id) == building.id,
                        col(Room.room_number) == room_record["room_number"],
                    )
                ).scalar_one()
                room.capacity = room_record["capacity"]
                room.active = True
                session.add_all([building, room])
            run.counts = {
                **counts,
                "publication_anomalies": anomalies,
                "publication_review_reason": reason or saved_reason,
                "published_over": baseline,
            }
            session.add(run)
            session.flush()
            dataset.published_at = datetime.now(UTC)
            session.add(dataset)
            session.flush()
            state.active_dataset_id = dataset.id
            session.add(state)
            session.flush()
            return {"status": "published", "dataset_id": str(dataset.id), "run_id": str(run.id)}
    except Exception as exc:
        # Never invalidate the successful run of an already-published historical dataset.
        if run_id is None:
            raise (
                exc if isinstance(exc, IngestionError) else IngestionError("publication_failed")
            ) from None
        raise _failure(engine, exc, input_hash, run_id) from None


def ingestion_status(engine: Engine) -> dict:
    with Session(engine) as session:
        state = session.get_one(DatasetState, 1)
        runs = (
            session.execute(
                select(IngestionRun).order_by(col(IngestionRun.started_at).desc()).limit(10)
            )
            .scalars()
            .all()
        )
        datasets = {
            item.run_id: item
            for item in session.scalars(
                select(Dataset).where(col(Dataset.run_id).in_([run.id for run in runs]))
            )
        }
        return {
            "active_dataset_id": str(state.active_dataset_id) if state.active_dataset_id else None,
            "runs": [
                {
                    "run_id": str(run.id),
                    "status": run.status,
                    "dataset_id": str(datasets[run.id].id) if run.id in datasets else None,
                    "published_at": datasets[run.id].published_at if run.id in datasets else None,
                    "input_hash": run.input_hash,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "error_code": run.error_code,
                    "counts": {
                        key: value for key, value in run.counts.items() if key != "room_records"
                    },
                }
                for run in runs
            ],
        }
