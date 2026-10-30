"""Date-aware active schedule selection, without exposing private ingestion records."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlmodel import col

from app.errors import APIError
from app.models import ActivePeriod, Dataset, DatasetSource, DatasetState, RoomCoverage

ZONE = ZoneInfo("America/Toronto")


@dataclass(frozen=True)
class PublishedSchedule:
    datasets: tuple[Dataset, ...]
    source_days: tuple[dict, ...]
    periods: tuple[ActivePeriod, ...]
    publication_id: UUID | None

    @property
    def id(self):
        return self.datasets[0].id

    @property
    def ids(self):
        return [item.id for item in self.datasets]

    @property
    def source_fetched_at(self):
        return min(item["fetched_at"] for item in self.source_days)


def dataset_ids(dataset):
    return dataset.ids if isinstance(dataset, PublishedSchedule) else [dataset.id]


def payload_bounds(dataset, starts_at, ends_at, dataset_id):
    if not isinstance(dataset, PublishedSchedule):
        return starts_at, ends_at
    left = {p.dataset_id: datetime.combine(p.start_date, time.min, ZONE) for p in dataset.periods}
    right = {p.dataset_id: datetime.combine(p.end_date, time.min, ZONE) for p in dataset.periods}
    return (func.greatest(starts_at, case(left, value=dataset_id)),
            func.least(ends_at, case(right, value=dataset_id)))


def clip_payload(dataset, row, value):
    if isinstance(dataset, PublishedSchedule):
        period = next(p for p in dataset.periods if p.dataset_id == row.dataset_id)
        value.starts_at = max(value.starts_at, datetime.combine(period.start_date, time.min, ZONE))
        value.ends_at = min(value.ends_at, datetime.combine(period.end_date, time.min, ZONE))
    return value


def published_schedule(session, start=None, end=None):
    query = select(Dataset).join(ActivePeriod, col(ActivePeriod.dataset_id) == col(Dataset.id))
    if start is not None and end is not None:
        first = start.astimezone(ZONE).date()
        last = (end - timedelta(microseconds=1)).astimezone(ZONE).date()
        query = query.where(col(ActivePeriod.start_date) <= last, col(ActivePeriod.end_date) > first)
    datasets = tuple(session.scalars(query.where(col(Dataset.published_at).is_not(None))
        .order_by(col(ActivePeriod.start_date))).all())
    if not datasets:
        any_active = session.scalar(select(col(ActivePeriod.dataset_id)).limit(1))
        if any_active and start is not None:
            raise APIError(422, "outside_dataset_coverage", "Choose a date within an active schedule.")
        raise APIError(503, "dataset_unavailable", "No published schedule is available.")
    ids = [d.id for d in datasets]
    sources = select(DatasetSource).where(col(DatasetSource.dataset_id).in_(ids))
    if start is not None:
        relevant_days = select(col(RoomCoverage.source_date)).where(
            col(RoomCoverage.dataset_id).in_(ids), col(RoomCoverage.starts_at) < end,
            col(RoomCoverage.ends_at) > start, col(RoomCoverage.source_date).is_not(None))
        sources = sources.where(col(DatasetSource.date).in_(relevant_days))
    rows = session.scalars(sources.order_by(col(DatasetSource.date))).all()
    days = [{"dataset_id": row.dataset_id, "date": row.date, "fetched_at": row.fetched_at}
            for row in rows]
    # Legacy/synthetic payloads can lack source-day provenance: retain conservative age.
    represented = {row.dataset_id for row in rows}
    days.extend({"dataset_id": d.id, "date": None, "fetched_at": d.source_fetched_at}
                for d in datasets if d.id not in represented)
    periods = tuple(session.scalars(select(ActivePeriod).where(col(ActivePeriod.dataset_id).in_(ids))
                                   .order_by(col(ActivePeriod.start_date))).all())
    return PublishedSchedule(datasets, tuple(days), periods,
                             session.get_one(DatasetState, 1).active_dataset_id)
