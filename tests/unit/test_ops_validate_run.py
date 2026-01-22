import sys
from pathlib import Path

import yaml


def test_ops_validate_run_reports_db_missing(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "missing.db"
    config = {
        "config_version": "test",
        "environment": "local",
        "db_path": str(db_path),
        "metrics_log_path": str(tmp_path / "metrics.log"),
        "app_log_path": str(tmp_path / "app.log"),
        "log_level": "INFO",
    }
    config_path.write_text(yaml.safe_dump(config))
    schema_path = Path("config/schema.json")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ops_validate_run.py",
            "--config",
            str(config_path),
            "--schema",
            str(schema_path),
            "--metrics-tail",
            "0",
        ],
    )

    from tools import ops_validate_run

    rc = ops_validate_run.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "status=fail" in out
    assert "schema_version=db_missing" in out
    assert "post_start=db_missing" in out
