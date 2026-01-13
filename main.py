"""
Hyperliquid Copy Trader entrypoint.

Bootstrap sequence:
1) Load YAML settings.
2) Validate + augment config (config_version/config_hash).
3) Initialize SQLite (schema + pragmas).
4) Placeholder hooks for reconciliation, gap backfill, and service startup.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from utils.db import init_sqlite
from utils.validations import SettingsValidationError, validate_settings


def parse_args():
    parser = argparse.ArgumentParser(description="Hyperliquid Copy Trader orchestrator")
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to settings YAML (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path (default: data/hyperliquid.db)",
    )
    parser.add_argument(
        "--mode",
        default="live",
        choices=["live", "dry-run", "backfill-only"],
        help="Runtime mode (logic stubbed; see docs/SYSTEM_DESIGN.md)",
    )
    return parser.parse_args()


def load_settings(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    args = parse_args()

    try:
        raw_settings = load_settings(args.config)
        settings = validate_settings(raw_settings)
    except (FileNotFoundError, SettingsValidationError) as exc:
        print(f"[BOOT][FAIL] {exc}", file=sys.stderr)
        sys.exit(1)

    conn = init_sqlite(args.db)

    print("[BOOT][OK] config_version=", settings["config_version"])
    print("[BOOT][OK] config_hash=", settings["config_hash"])
    print("[BOOT][OK] db_path=", conn.execute("PRAGMA database_list").fetchone()[2])
    print(f"[BOOT][INFO] mode={args.mode} (service wiring is still stubbed)")

    # TODO: reconciliation, gap backfill, start Monitor/Strategy/Executor/Notifier coroutines.
    # Keep connection open for now; production code should manage lifecycle and graceful shutdown.


if __name__ == "__main__":
    main()
