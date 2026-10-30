from datetime import UTC, date, datetime

import pytest

from app.ingest.local import IngestionError, load_directory
from staging import generate, validate_synthetic


def test_generated_week_is_explicit_complete_synthetic_and_dst_safe(tmp_path):
    path = tmp_path / "generated"
    generate(path, date(2026, 10, 30), datetime(2026, 10, 30, tzinfo=UTC))
    bundle = validate_synthetic(path)
    assert bundle == load_directory(path)
    assert len(bundle.dates) == 7 and len(bundle.rooms) == 2
    assert len(bundle.coverage) == 14 and len(bundle.meetings) == 14
    assert all(item.completeness == "complete" for item in bundle.coverage)
    assert bundle.coverage[0].starts_at.hour == 12
    assert bundle.coverage[4].starts_at.hour == 13
    assert all(room.building_code == "SYN-DEMO" for room in bundle.rooms)
    with pytest.raises(FileExistsError):
        generate(path, date(2026, 10, 30), datetime.now(UTC))


def test_modified_or_non_generated_source_is_never_staged(tmp_path):
    path = tmp_path / "generated"
    generate(path, date(2026, 10, 30), datetime(2026, 10, 30, tzinfo=UTC))
    source = path / "2026-10-30.html"
    source.write_text(source.read_text().replace("Synthetic demo booking", "Other booking"))
    with pytest.raises(IngestionError, match="not_generated_synthetic"):
        validate_synthetic(path)
