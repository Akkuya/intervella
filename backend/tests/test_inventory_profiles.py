from concurrent.futures import ThreadPoolExecutor

import pytest
from test_weekly_ingestion import write_weekly

from app.ingest.local import IngestionError


def proposal(path):
    from datetime import date

    from app.operator.manifests import analyze_sources
    from app.operator.profiles import ProfileApproval

    result = analyze_sources(path, date(2026, 10, 25))
    return ProfileApproval(
        expected_version=0,
        review_reason="independent-inventory",
        review_acknowledged=True,
        expected_rooms=2,
        expected_buildings=1,
        source_formats=["weekly"],
        window=result["draft"]["window"],
        buildings=result["draft"]["buildings"],
    )


def test_profile_approval_is_private_durable_versioned_and_explicit(tmp_path):
    from app.operator.profiles import ProfileStore

    write_weekly(tmp_path / "source")
    store = ProfileStore(tmp_path / "private")
    assert store.current() is None
    draft = proposal(tmp_path / "source")
    draft.review_acknowledged = False
    with pytest.raises(IngestionError, match="inventory_acknowledgment_required"):
        store.save(draft)
    draft.review_acknowledged = True
    draft.expected_rooms = 3
    with pytest.raises(IngestionError, match="expected_inventory_count_mismatch"):
        store.save(draft)
    draft.expected_rooms = 2
    saved = store.save(draft)
    assert saved.version == 1
    assert ProfileStore(tmp_path / "private").current() == saved
    with pytest.raises(IngestionError, match="profile_changed"):
        store.save(draft)
    draft.expected_version = 1
    draft.buildings[0].rooms[0].capacity = 21
    assert store.save(draft).version == 2
    assert len(store.history()) == 2
    assert "Synthetic booking" not in (tmp_path / "private" / "current.json").read_text(
        encoding="utf-8"
    )


def test_concurrent_profile_approvals_cannot_overwrite_reviewed_version(tmp_path):
    from app.operator.profiles import ProfileStore

    write_weekly(tmp_path / "source")
    draft = proposal(tmp_path / "source")
    store = ProfileStore(tmp_path / "private")

    def save(_):
        try:
            return store.save(draft).version
        except IngestionError as e:
            return e.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results.count(1) == 1
    assert any(r in {"profile_changed", "profile_busy"} for r in results)
    assert store.current().version == 1


@pytest.mark.parametrize("change", ["duplicate", "source_id", "ambiguous", "window"])
def test_profile_rejects_duplicate_or_ambiguous_identities(tmp_path, change):
    from app.operator.profiles import ProfileStore

    write_weekly(tmp_path / "source")
    draft = proposal(tmp_path / "source")
    room = draft.buildings[0].rooms[0]
    if change == "duplicate":
        draft.buildings[0].rooms[1].room_number = room.room_number
    elif change == "source_id":
        room.source_id = draft.buildings[0].rooms[1].source_id = 12
    elif change == "ambiguous":
        draft.buildings[0].rooms[1].source_name = room.source_name
    else:
        room.window.start = "24:30"
    with pytest.raises((IngestionError, ValueError)):
        ProfileStore(tmp_path / "private").save(draft)
