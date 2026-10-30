"""Private reviewed inventory versions; never a publication or room-ID allocator."""

import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from app.ingest.local import IngestionError, ManifestModel, SourceBuilding, Window, _minute, _read


class Inventory(ManifestModel):
    source_formats: list[Literal["daily", "weekly"]] = Field(min_length=1, max_length=2)
    window: Window
    buildings: list[SourceBuilding] = Field(min_length=1, max_length=50)


class Profile(Inventory):
    version: int = Field(gt=0)
    reviewed_at: AwareDatetime
    review_reason: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    expected_rooms: int = 0
    expected_buildings: int = 0
    window_review_audit: dict | None = None


class ProfileApproval(Inventory):
    expected_version: int = Field(ge=0, strict=True)
    expected_rooms: int = Field(gt=0, le=25000, strict=True)
    expected_buildings: int = Field(gt=0, le=50, strict=True)
    review_reason: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    review_acknowledged: bool = Field(strict=True)
    window_review_audit: dict | None = None


def inventory_value(value: Inventory) -> dict:
    return value.model_dump(mode="json", include={"source_formats", "window", "buildings"})


def validate_inventory(value: Inventory):
    # Revalidate mutable editor models as well as freshly deserialized input.
    value = Inventory.model_validate(inventory_value(value))
    buildings = value.buildings
    rooms = [(b, r) for b in buildings for r in b.rooms]
    keys = [(b.code, r.room_number) for b, r in rooms]
    aliases = [(b.source_name, r.source_name) for b, r in rooms]
    ids = [r.source_id for _, r in rooms if r.source_id is not None]
    if (
        len(set(value.source_formats)) != len(value.source_formats)
        or len({b.code for b in buildings}) != len(buildings)
        or len({b.source_name for b in buildings}) != len(buildings)
        or len(set(keys)) != len(keys)
        or len(set(aliases)) != len(aliases)
        or len(set(ids)) != len(ids)
        or (
            "weekly" in value.source_formats
            and len({r.source_name for _, r in rooms}) != len(rooms)
        )
    ):
        raise IngestionError("duplicate_identity")
    if "daily" in value.source_formats and any(r.source_id is None for _, r in rooms):
        raise IngestionError("missing_source_identity")
    if "weekly" in value.source_formats and any(r.capacity is None for _, r in rooms):
        raise IngestionError("missing_expected_capacity")
    for window in [value.window, *(r.window for _, r in rooms if r.window)]:
        start, end = _minute(window.start), _minute(window.end)
        if end <= start:
            end += 1440
        if end - start > 1440:
            raise IngestionError("invalid_window")


@contextmanager
def _exclusive(path: Path):
    # OS locks release on process exit; unlike a sentinel file they cannot go stale.
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise IngestionError("profile_busy") from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ProfileStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise IngestionError("invalid_profile_storage")

    def current(self) -> Profile | None:
        path = self.root / "current.json"
        if not path.exists():
            return None
        try:
            result = Profile.model_validate_json(_read(path, 1024 * 1024))
            validate_inventory(result)
            return result
        except (ValueError, OSError):
            raise IngestionError("invalid_profile_storage") from None

    def history(self):
        current = self.current()
        if not current:
            return []
        result = []
        for version in range(current.version, max(0, current.version - 20), -1):
            path = self.root / f"version-{version}.json"
            profile = Profile.model_validate_json(_read(path, 1024 * 1024))
            result.append(
                {
                    "version": version,
                    "reviewed_at": profile.reviewed_at.isoformat(),
                    "review_reason": profile.review_reason,
                }
            )
        return result

    def save(self, approval: ProfileApproval) -> Profile:
        if not approval.review_acknowledged:
            raise IngestionError("inventory_acknowledgment_required")
        validate_inventory(approval)
        if approval.expected_buildings != len(approval.buildings) or approval.expected_rooms != sum(
            len(b.rooms) for b in approval.buildings
        ):
            raise IngestionError("expected_inventory_count_mismatch")
        with _exclusive(self.root / ".lock"):
            previous = self.current()
            if approval.expected_version != (previous.version if previous else 0):
                raise IngestionError("profile_changed")
            profile = Profile(
                **inventory_value(approval),
                version=approval.expected_version + 1,
                reviewed_at=datetime.now(UTC),
                review_reason=approval.review_reason,
                expected_rooms=approval.expected_rooms,
                expected_buildings=approval.expected_buildings,
                window_review_audit=approval.window_review_audit,
            )
            body = json.dumps(profile.model_dump(mode="json"), sort_keys=True, indent=2).encode()
            if len(body) > 1024 * 1024:
                raise IngestionError("profile_too_large")
            temp = self.root / f".profile-{uuid4().hex}.tmp"
            try:
                with temp.open("xb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                # History first. The current pointer is the sole approval commit point.
                history = self.root / f"version-{profile.version}.json"
                with history.open("wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.root / "current.json")
            finally:
                temp.unlink(missing_ok=True)
            return profile
