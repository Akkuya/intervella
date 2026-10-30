"""Audited staging and serialized, atomic publication. No network transport."""

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from app.ingest.local import PARSER_VERSION, Bundle, IngestionError, load_directory, local_instant
from app.models import (
    Building,
    ActivePeriod,
    Dataset,
    DatasetSource,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)

# Same transaction lock for staging/publication; never use a pooled session advisory lock.
LOCK_KEY = 8506374104


def period_baseline(session, dates):
    start = date.fromisoformat(str(dates[0]))
    end = date.fromisoformat(str(dates[-1])) + timedelta(days=1)
    overlaps = session.scalars(select(ActivePeriod).where(
        col(ActivePeriod.start_date) < end, col(ActivePeriod.end_date) > start
    )).all()
    if any(p.start_date != start or p.end_date != end for p in overlaps):
        raise IngestionError("overlapping_active_period")
    return overlaps[0].dataset_id if overlaps else None


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
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        datasets = (
            session.execute(
                select(Dataset)
                .where(col(Dataset.run_id) == run_id)
                .order_by(col(Dataset.id))
                .with_for_update()
            )
            .scalars()
            .all()
            if run_id
            else []
        )
        published = any(dataset.published_at is not None for dataset in datasets)
        now = datetime.now(UTC)
        run = (
            session.execute(
                select(IngestionRun).where(col(IngestionRun.id) == run_id).with_for_update()
            ).scalar_one_or_none()
            if run_id and not published
            else None
        )
        if run is None:
            run = IngestionRun(started_at=now, input_hash=input_hash)
            if published:
                # A competing publisher committed after rollback; preserve its successful parent.
                run.counts = {
                    "phase": "publication",
                    "related_run_id": str(run_id),
                    "related_dataset_ids": [str(dataset.id) for dataset in datasets],
                }
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
    metadata = session.execute(
        select(
            col(Dataset.id),
            col(Dataset.run_id),
            col(Dataset.source_fetched_at),
            col(Dataset.timezone),
        ).where(col(Dataset.id) == dataset_id)
    ).one()
    coverage = session.execute(
        select(
            col(RoomCoverage.room_id),
            col(RoomCoverage.starts_at),
            col(RoomCoverage.ends_at),
            col(RoomCoverage.completeness),
            col(RoomCoverage.source_date),
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
    sources = session.execute(select(col(DatasetSource.date), col(DatasetSource.fetched_at))
        .where(col(DatasetSource.dataset_id) == dataset_id).order_by(col(DatasetSource.date))).all()
    payload = [[list(row) for row in rows] for rows in [[metadata], coverage, meetings, identities, sources]]
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
        baseline_id = period_baseline(session, bundle.dates)
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
        session.add_all([DatasetSource(dataset_id=dataset.id, date=date.fromisoformat(s["date"]),
            fetched_at=datetime.fromisoformat(s["fetched_at"])) for s in bundle.sources])
        period_start = local_instant(bundle.dates[0], 0)
        period_end = local_instant(bundle.dates[-1] + timedelta(days=1), 0)
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
                    starts_at=max(item.starts_at, period_start),
                    ends_at=min(item.ends_at, period_end),
                    completeness=item.completeness,
                    source_date=item.source_date,
                )
                for item in bundle.coverage if item.starts_at < period_end and item.ends_at > period_start
            ]
        )
        session.add_all(
            [
                MeetingOccurrence(
                    dataset_id=dataset.id,
                    room_id=room_ids[item.room_key],
                    starts_at=max(item.starts_at, period_start),
                    ends_at=min(item.ends_at, period_end),
                    status=item.status,
                    source_key=item.source_key,
                )
                for item in bundle.meetings if item.starts_at < period_end and item.ends_at > period_start
            ]
        )
        session.flush()
        counts = {
            **bundle.report(),
            "parser_version": PARSER_VERSION,
            "sources": list(bundle.sources),
            "review_audit": bundle.review_audit,
            "room_records": [asdict(room) for room in bundle.rooms],
            "baseline_dataset_id": str(state.active_dataset_id)
            if state.active_dataset_id
            else None,
        }
        anomalies = _anomalies(session, dataset, counts, baseline_id)
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


def publish_dataset(engine: Engine, dataset_id: str | UUID, *,
                    review_reason: str | None = None, expected_baseline: str | None = None) -> dict:
    return publish_datasets(engine, [dataset_id], review_reason=review_reason,
                            expected_baseline=expected_baseline)["publications"][0]


def publish_datasets(engine: Engine, dataset_ids, *, review_reason=None, expected_baseline=None):
    """All selected periods commit together; unrelated active periods are retained."""
    reason = _reason(review_reason)
    ids = [UUID(str(value)) for value in dataset_ids]
    if not 1 <= len(ids) <= 12 or len(set(ids)) != len(ids):
        raise IngestionError("invalid_publication_selection")
    try:
        with Session(engine) as session, session.begin():
            state = _lock(session)
            current = str(state.active_dataset_id) if state.active_dataset_id else ""
            if expected_baseline is not None and expected_baseline != current:
                raise IngestionError("publication_baseline_changed")
            results = []
            selected_periods = []
            for dataset_id in ids:
                dataset = session.execute(select(Dataset).where(col(Dataset.id) == dataset_id)
                                          .with_for_update()).scalar_one_or_none()
                if dataset is None:
                    raise IngestionError("dataset_not_found")
                run = session.get_one(IngestionRun, dataset.run_id)
                counts = run.counts
                dates = counts.get("dates", [])
                if len(dates) != 7 or dates != [str(date.fromisoformat(dates[0]) + timedelta(days=i))
                                               for i in range(7)]:
                    raise IngestionError("candidate_period_invalid")
                start = date.fromisoformat(dates[0])
                end = date.fromisoformat(dates[-1]) + timedelta(days=1)
                if any(left < end and right > start for left, right in selected_periods):
                    raise IngestionError("overlapping_candidates")
                selected_periods.append((start, end))
                previous_id = period_baseline(session, dates)
                if previous_id == dataset.id:
                    results.append({"status": "unchanged", "dataset_id": str(dataset.id)})
                    continue
                if dataset.published_at is not None:
                    raise IngestionError("already_published")
                if run.status != "succeeded" or counts.get("parser_version") != PARSER_VERSION:
                    raise IngestionError("candidate_not_validated")
                if counts.get("candidate_digest") != _digest(session, dataset.id):
                    raise IngestionError("candidate_changed")
                previous = session.get_one(Dataset, previous_id) if previous_id else None
                if previous:
                    old_counts = session.get_one(IngestionRun, previous.run_id).counts
                    old_sources = {item["date"]: item for item in old_counts.get("sources", [])}
                    if not old_sources and dataset.source_fetched_at < previous.source_fetched_at:
                        raise IngestionError("older_source")
                    for source in counts["sources"]:
                        old = old_sources.get(source["date"])
                        if old:
                            captured = datetime.fromisoformat(source["fetched_at"])
                            prior = datetime.fromisoformat(old["fetched_at"])
                            if captured < prior or (captured == prior and source["sha256"] != old["sha256"]):
                                raise IngestionError("older_source")
                anomalies = _anomalies(session, dataset, counts, previous_id)
                baseline = str(state.active_dataset_id) if state.active_dataset_id else None
                saved_reason = counts.get("review_reason") if counts.get("baseline_dataset_id") == baseline else None
                if anomalies and not (reason or saved_reason):
                    raise IngestionError("review_required", report={"publication_anomalies": anomalies})
                # Shared room metadata must remain true for retained periods as well.
                retained = select(col(ActivePeriod.dataset_id)).where(col(ActivePeriod.dataset_id) != previous_id) if previous_id else select(col(ActivePeriod.dataset_id))
                for record in counts["room_records"]:
                    building = session.execute(select(Building).where(
                        col(Building.code) == record["building_code"])).scalar_one()
                    room = session.execute(select(Room).where(col(Room.building_id) == building.id,
                        col(Room.room_number) == record["room_number"])).scalar_one()
                    retained_room = session.scalar(select(col(RoomCoverage.room_id)).where(
                        col(RoomCoverage.dataset_id).in_(retained), col(RoomCoverage.room_id) == room.id).limit(1))
                    retained_building = session.scalar(select(col(RoomCoverage.room_id)).join(Room,
                        col(Room.id) == col(RoomCoverage.room_id)).where(
                        col(RoomCoverage.dataset_id).in_(retained), col(Room.building_id) == building.id).limit(1))
                    if ((retained_room and room.capacity != record["capacity"])
                        or (retained_building and building.name != record["building_name"])):
                        raise IngestionError("active_inventory_metadata_conflict")
                    building.name = record["building_name"]
                    room.capacity = record["capacity"]
                    session.add_all([building, room])
                run.counts = {**counts, "publication_anomalies": anomalies,
                    "publication_review_reason": reason or saved_reason,
                    "published_over": str(previous_id) if previous_id else None,
                    "publication_selection": [str(value) for value in ids]}
                session.add(run)
                dataset.published_at = datetime.now(UTC)
                session.add(dataset)
                session.flush()
                if previous_id:
                    session.execute(delete(ActivePeriod).where(col(ActivePeriod.dataset_id) == previous_id))
                session.add(ActivePeriod(start_date=start, end_date=end, dataset_id=dataset.id))
                session.flush()
                results.append({"status": "published", "dataset_id": str(dataset.id), "run_id": str(run.id)})
            inventory = select(col(RoomCoverage.room_id)).join(ActivePeriod,
                col(ActivePeriod.dataset_id) == col(RoomCoverage.dataset_id))
            session.execute(update(Room).values(active=col(Room.id).in_(inventory)))
            changed = [item for item in results if item["status"] == "published"]
            if changed:
                state.active_dataset_id = UUID(changed[-1]["dataset_id"])
                session.add(state)
            session.flush()
            return {"publications": results}
    except Exception as exc:
        failure = exc if isinstance(exc, IngestionError) else IngestionError("publication_failed")
        # Separate failed-attempt audit never invalidates otherwise reusable staged candidates.
        failure.report = {**(failure.report or {}), "phase": "publication",
                          "related_dataset_ids": [str(value) for value in ids]}
        raise _failure(engine, failure, hashlib.sha256(str(ids).encode()).hexdigest()) from None


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
