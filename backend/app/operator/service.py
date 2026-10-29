"""Private, description-free health and candidate comparisons."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel import Session, col

from app.ingest.local import ZONE, Bundle
from app.ingest.pipeline import ingestion_status
from app.models import (
    Building,
    Dataset,
    DatasetState,
    IngestionRun,
    MeetingOccurrence,
    Room,
    RoomCoverage,
)
from app.services.availability import freshness


def _inventory(session, dataset_id):
    ids = select(col(RoomCoverage.room_id)).where(col(RoomCoverage.dataset_id) == dataset_id)
    return session.execute(
        select(Room, col(Building.code)).join(Building).where(col(Room.id).in_(ids))
    ).all()


def health(engine):
    history = ingestion_status(engine)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, session.begin():
            state = session.get_one(DatasetState, 1)
            dataset = (
                session.get(Dataset, state.active_dataset_id) if state.active_dataset_id else None
            )
            if dataset is None:
                return {"active": None, "history": history["runs"]}
            run = session.get_one(IngestionRun, dataset.run_id)
            counts = run.counts
            windows = session.scalars(
                select(RoomCoverage).where(RoomCoverage.dataset_id == dataset.id)
            ).all()
            inventory = _inventory(session, dataset.id)
            occurrences = session.scalars(
                select(MeetingOccurrence).where(col(MeetingOccurrence.dataset_id) == dataset.id)
            ).all()
            sources = {s["date"]: s for s in counts.get("sources", [])}
            days = []
            for day in counts.get(
                "dates", sorted({str(w.starts_at.astimezone(ZONE).date()) for w in windows})
            ):
                represented = {
                    w.room_id for w in windows if str(w.starts_at.astimezone(ZONE).date()) == day
                }
                unknown = {
                    w.room_id
                    for w in windows
                    if str(w.starts_at.astimezone(ZONE).date()) == day
                    and w.completeness != "complete"
                }
                days.append(
                    {
                        "date": day,
                        "fetched_at": sources.get(day, {}).get("fetched_at"),
                        "freshness": (
                            "stale"
                            if datetime.now(UTC)
                            - datetime.fromisoformat(sources[day]["fetched_at"])
                            > timedelta(hours=36)
                            else "fresh"
                        )
                        if day in sources
                        else "unknown",
                        "complete_rooms": len(represented - unknown),
                        "unknown_rooms": len(unknown),
                        "missing_rooms": max(
                            0, counts.get("rooms", len(represented)) - len(represented)
                        ),
                    }
                )
            return {
                "active": {
                    "dataset_id": str(dataset.id),
                    "published_at": dataset.published_at,
                    "imported_at": run.started_at,
                    "source_fetched_at": dataset.source_fetched_at,
                    "freshness": freshness(dataset, datetime.now(UTC)).freshness,
                    "source_format": counts.get(
                        "source_format", "daily" if sources else "synthetic"
                    ),
                    "parser_version": counts.get("parser_version", "synthetic"),
                    "rooms": counts.get("rooms", len({w.room_id for w in windows})),
                    "buildings": len({code for room, code in inventory}),
                    "occurrences": len(occurrences),
                    "days": days,
                },
                "history": history["runs"],
            }


def compare(engine, bundle: Bundle):
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(connection) as session, session.begin():
            state = session.get_one(DatasetState, 1)
            dataset = (
                session.get(Dataset, state.active_dataset_id) if state.active_dataset_id else None
            )
            previous = session.get_one(IngestionRun, dataset.run_id).counts if dataset else {}
            old = {
                (r["building_code"], r["room_number"]): r for r in previous.get("room_records", [])
            }
            inventory = _inventory(session, dataset.id) if dataset else []
            keys = {room.id: (code, room.room_number) for room, code in inventory}
            if not old:
                old = {
                    (code, room.room_number): {"capacity": room.capacity}
                    for room, code in inventory
                }
            new = {r.key: {"capacity": r.capacity} for r in bundle.rooms}
            existing = (
                session.scalars(
                    select(MeetingOccurrence).where(col(MeetingOccurrence.dataset_id) == dataset.id)
                ).all()
                if dataset
                else []
            )
            old_intervals = {(keys[m.room_id], m.starts_at, m.ends_at, m.status) for m in existing}
            new_intervals = {
                (m.room_key, m.starts_at, m.ends_at, m.status) for m in bundle.meetings
            }
            by_day = Counter(
                (m.room_key[0], str(m.starts_at.astimezone(ZONE).date()))
                for m in bundle.meetings
                if m.status == "scheduled"
            )
            old_by_day = Counter(
                (keys[m.room_id][0], str(m.starts_at.astimezone(ZONE).date()))
                for m in existing
                if m.status == "scheduled"
            )
            warnings = []
            if set(old) != set(new) and dataset:
                warnings.append("room_inventory_changed")
            old_scheduled = sum(m.status == "scheduled" for m in existing)
            if (
                dataset
                and len([m for m in bundle.meetings if m.status == "scheduled"]) / 7
                < old_scheduled / max(1, len(previous.get("dates", []))) * 0.8
            ):
                warnings.append("booking_drop")
            if bundle.report()["unknown_rooms"]:
                warnings.append("unknown_coverage")
            if datetime.now(UTC) - bundle.source_fetched_at > timedelta(hours=36):
                warnings.append("stale_source")
            if dataset and bundle.source_fetched_at <= dataset.source_fetched_at:
                warnings.append("older_source")
            old_sources = {s["date"]: s["fetched_at"] for s in previous.get("sources", [])}
            if any(
                s["date"] in old_sources
                and datetime.fromisoformat(s["fetched_at"])
                < datetime.fromisoformat(old_sources[s["date"]])
                for s in bundle.sources
            ):
                warnings.append("source_day_regression")
            return {
                "baseline_dataset_id": str(dataset.id) if dataset else None,
                "added_rooms": ["-".join(k) for k in sorted(new.keys() - old.keys())],
                "missing_rooms": ["-".join(k) for k in sorted(old.keys() - new.keys())],
                "capacity_changes": [
                    {
                        "room": "-".join(k),
                        "previous": old[k]["capacity"],
                        "candidate": new[k]["capacity"],
                    }
                    for k in sorted(old.keys() & new.keys())
                    if old[k]["capacity"] != new[k]["capacity"]
                ],
                "added_intervals": len(new_intervals - old_intervals),
                "removed_intervals": len(old_intervals - new_intervals),
                "previous_occurrences": len(existing),
                "candidate_occurrences": len(bundle.meetings),
                "previous_unknown_rooms": previous.get("unknown_rooms"),
                "candidate_unknown_rooms": bundle.report()["unknown_rooms"],
                "by_building_date": [
                    {
                        "building": b,
                        "date": d,
                        "bookings": by_day[b, d],
                        "previous": old_by_day[b, d],
                        "delta": by_day[b, d] - old_by_day[b, d],
                    }
                    for b, d in sorted(set(by_day) | set(old_by_day))
                ],
                "warnings": warnings,
            }
