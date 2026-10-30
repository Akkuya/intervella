"""Only explicit window changes can be approved without changing room inventory."""

import copy

from app.ingest.local import IngestionError


def reviewed_windows(manifest, profile, analysis, acknowledged):
    expected = [b.model_dump(mode="json") for b in profile.buildings]
    supplied = [b.model_dump(mode="json") for b in manifest.buildings]
    changes = []
    if len(expected) != len(supplied) or manifest.window != profile.window:
        raise IngestionError("profile_review_required")
    observations = {(r["source_building"], r["source_name"]): r for r in analysis["observed_rooms"]}
    blocked = bool(analysis["missing_sources"] or any(i["severity"] == "blocking" for i in analysis["issues"]))
    for old_building, new_building in zip(expected, supplied):
        if len(old_building["rooms"]) != len(new_building["rooms"]):
            raise IngestionError("profile_review_required")
        for old, new in zip(old_building["rooms"], new_building["rooms"]):
            if old.get("window") == new.get("window"):
                continue
            key = (None if manifest.source_format == "weekly" else old_building["source_name"], old["source_name"])
            observed = observations.get(key)
            if (not acknowledged or blocked or not observed or not observed["bulk_eligible"]
                or new.get("window") != observed["window"] or new["capacity"] != observed["capacity"]
                or (manifest.source_format == "daily" and new["source_id"] != observed["source_id"])):
                raise IngestionError("coverage_window_not_eligible")
            changes.append({"building": old_building["code"], "room": old["room_number"],
                "expected": old.get("window") or profile.window.model_dump(),
                "observed": observed["window"]})
            old["window"] = copy.deepcopy(new["window"])
    if expected != supplied:
        raise IngestionError("profile_review_required")
    return changes
