from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

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
    parser.add_argument(
        "--emit-boot-event",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Emit a single mock event on startup",
    )
    parser.add_argument(
        "--run-loop",
        action="store_true",
        help="Enter placeholder run loop after startup",
    )
    parser.add_argument(
        "--loop-interval-sec",
        type=int,
        default=None,
        help="Idle sleep interval in seconds for continuous run loop (overrides config)",
    )
    args = parser.parse_args()
    if args.loop_interval_sec is not None and args.loop_interval_sec < 1:
        raise SystemExit("--loop-interval-sec must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    schema_path = Path("config/schema.json")

    load_dotenv()
    settings = load_settings(config_path, schema_path)
    orchestrator = Orchestrator(
        settings=settings,
        mode=args.mode,
        emit_boot_event=args.emit_boot_event,
        run_loop=args.run_loop,
        loop_interval_sec=args.loop_interval_sec,
    )
    orchestrator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
