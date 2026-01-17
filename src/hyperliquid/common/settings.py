from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import jsonschema
import yaml


@dataclass(frozen=True)
class Settings:
    config_version: str
    environment: str
    db_path: str
    metrics_log_path: str
    app_log_path: str
    log_level: str
    config_path: Path
    raw: Dict[str, Any]


def compute_config_hash(config_path: Path) -> str:
    data = config_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    return data or {}


def validate_config(config: Dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(instance=config, schema=schema)


def load_settings(config_path: Path, schema_path: Path) -> Settings:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    config = load_yaml(config_path)
    validate_config(config, schema_path)

    return Settings(
        config_version=str(config["config_version"]),
        environment=str(config["environment"]),
        db_path=str(config["db_path"]),
        metrics_log_path=str(config["metrics_log_path"]),
        app_log_path=str(config["app_log_path"]),
        log_level=str(config["log_level"]),
        config_path=config_path,
        raw=config,
    )
