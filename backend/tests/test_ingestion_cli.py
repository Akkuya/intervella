import json

import pytest
from ingestion_helpers import write_bundle

from app.ingest import cli


def test_cli_dry_run_needs_no_database_and_reports_validation(tmp_path, capsys):
    write_bundle(tmp_path)
    assert cli.main(["import", str(tmp_path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "dry_run"
    assert report["occurrences"] == 7
    assert report["baseline_checked"] is False


def test_cli_malformed_source_never_echoes_input(tmp_path, capsys):
    (tmp_path / "manifest.json").write_text("private source token here", encoding="utf-8")
    assert cli.main(["import", str(tmp_path), "--dry-run"]) == 2
    report = capsys.readouterr()
    assert json.loads(report.out)["error_code"] == "invalid_local_input"
    assert "private source token" not in report.out + report.err


@pytest.mark.postgres
def test_cli_import_publish_status_workflow(postgres_engine, tmp_path, monkeypatch, capsys):
    write_bundle(tmp_path)
    monkeypatch.setattr(cli, "create_db_engine", lambda variable: postgres_engine)
    assert cli.main(["import", str(tmp_path)]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["active_dataset_id"] is None
    assert cli.main(["publish", staged["dataset_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "published"
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["active_dataset_id"] == staged["dataset_id"]
