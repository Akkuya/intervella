"""Operator commands; reports contain codes/hashes/counts, never source HTML or secrets."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.db import create_db_engine
from app.ingest.local import IngestionError
from app.ingest.pipeline import import_directory, ingestion_status, publish_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import authorized local timetable HTML; no network access."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser(
        "import", help="Validate and stage exactly seven dated HTML snapshots."
    )
    load.add_argument("directory", type=Path)
    load.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate local inputs without database access or writes.",
    )
    load.add_argument(
        "--review-reason", help="Audited review identifier (lowercase letters, digits, _ or -)."
    )
    publish = commands.add_parser(
        "publish", help="Revalidate and atomically activate a staged candidate."
    )
    publish.add_argument("dataset_id", type=UUID)
    publish.add_argument(
        "--review-reason", help="Review anomalies against the current active dataset."
    )
    commands.add_parser("status", help="Show the active dataset and ten most recent audited runs.")
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.command != "import" or not args.dry_run:
            engine = create_db_engine("INGESTION_DATABASE_URL")
        if args.command == "import":
            report = import_directory(
                engine, args.directory, dry_run=args.dry_run, review_reason=args.review_reason
            )
        elif args.command == "publish":
            assert engine is not None
            report = publish_dataset(engine, args.dataset_id, review_reason=args.review_reason)
        else:
            assert engine is not None
            report = ingestion_status(engine)
        print(json.dumps(report, default=str, indent=2))
        return 2 if report.get("requires_review") else 0
    except IngestionError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": exc.code,
                    "run_id": str(exc.run_id) if exc.run_id else None,
                    "report": exc.report,
                },
                indent=2,
            )
        )
        return 2
    except ValueError:
        print(json.dumps({"status": "failed", "error_code": "invalid_database_configuration"}))
        return 2
    except SQLAlchemyError:
        print(json.dumps({"status": "failed", "error_code": "database_unavailable"}))
        return 2
    finally:
        if engine is not None:
            engine.dispose()
