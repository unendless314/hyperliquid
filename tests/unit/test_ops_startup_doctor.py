import sys
from pathlib import Path

import yaml


def test_ops_startup_doctor_reports_db_missing(tmp_path, monkeypatch, capsys) -> None:
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
            "ops_startup_doctor.py",
            "--config",
            str(config_path),
            "--schema",
            str(schema_path),
            "--audit-tail",
            "0",
        ],
    )

    from tools import ops_startup_doctor

    rc = ops_startup_doctor.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "status=fail" in out
    assert "blockers=db_missing" in out


def test_ops_startup_doctor_handles_empty_db(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "settings.yaml"
    db_path = tmp_path / "empty.db"
    db_path.write_bytes(b"")
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
            "ops_startup_doctor.py",
            "--config",
            str(config_path),
            "--schema",
            str(schema_path),
            "--audit-tail",
            "0",
        ],
    )

    from tools import ops_startup_doctor

    rc = ops_startup_doctor.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "status=fail" in out
    assert "blockers=db_schema_missing" in out
