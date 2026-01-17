from __future__ import annotations

import argparse
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.orchestrator.service import Orchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hyperliquid copy trader")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["live", "dry-run", "backfill-only"],
        help="Run mode",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to config/settings.yaml",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    schema_path = Path("config/schema.json")

    settings = load_settings(config_path, schema_path)
    orchestrator = Orchestrator(settings=settings, mode=args.mode)
    orchestrator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
