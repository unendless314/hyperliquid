from pathlib import Path

import jsonschema

from hyperliquid.common.settings import validate_config


def _schema_path() -> Path:
    path = Path("config/schema.json")
    assert path.exists()
    return path


def _base_config() -> dict:
    return {
        "config_version": "0.1",
        "environment": "local",
        "db_path": "data/test.db",
        "metrics_log_path": "logs/metrics.log",
        "app_log_path": "logs/app.log",
        "log_level": "INFO",
    }


def test_validate_config_accepts_minimal_config() -> None:
    validate_config(_base_config(), _schema_path())


def test_validate_config_rejects_invalid_environment() -> None:
    config = _base_config()
    config["environment"] = "dev"
    try:
        validate_config(config, _schema_path())
    except jsonschema.ValidationError:
        return
    raise AssertionError("Expected ValidationError for invalid environment")


def test_validate_config_requires_strategy_version_when_decision_present() -> None:
    config = _base_config()
    config["decision"] = {"replay_policy": "close_only"}
    try:
        validate_config(config, _schema_path())
    except jsonschema.ValidationError:
        return
    raise AssertionError("Expected ValidationError for missing decision.strategy_version")


def test_validate_config_rejects_empty_strategy_version() -> None:
    config = _base_config()
    config["decision"] = {"strategy_version": "", "replay_policy": "close_only"}
    try:
        validate_config(config, _schema_path())
    except jsonschema.ValidationError:
        return
    raise AssertionError("Expected ValidationError for empty strategy_version")


def test_validate_config_rejects_unknown_top_level_key() -> None:
    config = _base_config()
    config["unexpected"] = True
    try:
        validate_config(config, _schema_path())
    except jsonschema.ValidationError:
        return
    raise AssertionError("Expected ValidationError for unknown top-level key")
