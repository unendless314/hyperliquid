"""
Hyperliquid Copy Trader entrypoint.

Bootstrap sequence:
1) Load YAML settings.
2) Validate + augment config (config_version/config_hash).
3) Initialize SQLite (schema + pragmas).
4) Placeholder async lifecycle: start service tasks, handle shutdown signals, and close resources.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from typing import Iterable

import yaml

from core.executor import Executor
from core.monitor import Monitor
from core.strategy import Strategy
from core.reconciler import Reconciler
from utils.db import init_sqlite
from utils.validations import SettingsValidationError, validate_settings
from utils.notifications import Notifier
from utils.hyperliquid_rest import HyperliquidRestAdapter


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


async def _run_services(settings, conn, stop_event: asyncio.Event):
    """
    Orchestrate Monitor -> Strategy -> Executor pipelines and support reconcilers/alerts.
    If any service task crashes, trigger stop_event to initiate shutdown.
    """
    monitor_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    exec_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    rest_client = None
    if settings.get("enable_rest_backfill"):
        rest_client = HyperliquidRestAdapter(
            wallet=settings["target_wallet"],
            base_url=settings["hyperliquid_rest_base_url"],
        )

    monitor = Monitor(
        monitor_queue,
        conn,
        settings,
        ws_client=None,
        rest_client=rest_client,
        backfill_window=settings["backfill_window"],
        cursor_mode=settings["cursor_mode"],
        dedup_ttl_seconds=settings["dedup_ttl_seconds"],
        cleanup_interval_seconds=settings["dedup_cleanup_interval_seconds"],
    )
    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn, mode=settings.get("mode", "live"))
    reconciler = Reconciler(conn)
    notifier = Notifier()

    tasks = [
        asyncio.create_task(monitor.run(), name="monitor"),
        asyncio.create_task(strategy.run(), name="strategy"),
        asyncio.create_task(executor.run(), name="executor"),
        asyncio.create_task(reconciler.run(), name="reconciler"),
    ]

    stop_waiter = asyncio.create_task(stop_event.wait(), name="stop_event_wait")

    try:
        while True:
            done, pending = await asyncio.wait(
                tasks + [stop_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_waiter in done:
                break

            crashed = [t for t in done if t is not stop_waiter and t.exception() is not None]
            if crashed:
                err = crashed[0].exception()
                print(f"[ERROR] service crashed: {crashed[0].get_name()} -> {err}", file=sys.stderr)
                stop_event.set()
                await stop_waiter  # ensure the wait task completes
                break
    finally:
        # Signal services to stop gracefully
        await monitor.stop()
        await strategy.stop()
        await executor.stop()
        await reconciler.stop()
        await notifier.stop()

        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        stop_waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_waiter


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event, signals: Iterable[int]) -> None:
    for sig in signals:
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # add_signal_handler not supported on some platforms (e.g., Windows)
            signal.signal(sig, lambda _sig, _frame: stop.set())


async def async_main():
    args = parse_args()

    try:
        raw_settings = load_settings(args.config)
        settings = validate_settings(raw_settings)
    except (FileNotFoundError, SettingsValidationError) as exc:
        print(f"[BOOT][FAIL] {exc}", file=sys.stderr)
        sys.exit(1)

    settings["mode"] = args.mode

    conn = init_sqlite(args.db)

    print("[BOOT][OK] config_version=", settings["config_version"])
    print("[BOOT][OK] config_hash=", settings["config_hash"])
    print("[BOOT][OK] db_path=", conn.execute("PRAGMA database_list").fetchone()[2])
    print(f"[BOOT][INFO] mode={args.mode} (services still stubbed)")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, stop_event, (signal.SIGINT, signal.SIGTERM))

    services = asyncio.create_task(_run_services(settings, conn, stop_event))

    await stop_event.wait()
    print("[SHUTDOWN] signal received, waiting for services to stop...")
    with contextlib.suppress(asyncio.CancelledError):
        await services

    conn.close()
    print("[SHUTDOWN] clean exit")


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("[SHUTDOWN] interrupted", file=sys.stderr)


if __name__ == "__main__":
    main()
