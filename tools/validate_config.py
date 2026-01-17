import argparse
import json
from pathlib import Path

import jsonschema
import yaml


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    return data or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate settings.yaml against schema.json")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    schema_path = Path(args.schema)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")
    if not schema_path.exists():
        raise SystemExit(f"Schema file not found: {schema_path}")

    config = load_yaml(config_path)
    schema = json.loads(schema_path.read_text())

    jsonschema.validate(instance=config, schema=schema)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
