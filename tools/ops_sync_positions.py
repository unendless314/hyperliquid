import argparse
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.execution.adapters.binance import BinanceExecutionAdapter, BinanceExecutionConfig
from hyperliquid.storage.baseline import insert_baseline, load_active_baseline
from hyperliquid.storage.db import assert_schema_version, init_db
from hyperliquid.storage.persistence import AuditLogEntry, DbPersistence


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_audit(persistence: DbPersistence, *, from_state: str, to_state: str, reason_code: str, reason_message: str) -> None:
    persistence.record_audit(
        AuditLogEntry(
            timestamp_ms=_now_ms(),
            category="baseline",
            entity_id="baseline",
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            reason_message=reason_message,
            event_id="",
            metadata=None,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync exchange positions into a baseline snapshot.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--operator", default="", help="Operator name for audit log.")
    parser.add_argument(
        "--reason-message",
        default="Baseline sync",
        help="Reason message for audit trail.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace active baseline if present.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned action without writing changes.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    schema_path = Path(args.schema)
    settings = load_settings(config_path, schema_path)
    execution_config = BinanceExecutionConfig.from_settings(settings.raw)
    if not execution_config.enabled or execution_config.mode != "live":
        raise SystemExit("execution_binance_not_enabled_live")
    adapter = BinanceExecutionAdapter(execution_config)
    positions, _ = adapter.fetch_positions()
    active = positions or {}

    conn = init_db(settings.db_path)
    try:
        assert_schema_version(conn)
        persistence = DbPersistence(conn)
        existing = load_active_baseline(conn)
        if existing and not args.replace:
            raise SystemExit("baseline_active_exists_use_replace")
        if args.dry_run:
            print(f"db_path={settings.db_path}")
            print(f"positions_count={len(active)}")
            print(f"replace={args.replace}")
            print("status=dry_run")
            return 0
        snapshot = insert_baseline(
            conn,
            positions=active,
            operator=args.operator or "",
            reason_message=args.reason_message,
            replace=args.replace,
        )
        from_state = existing.baseline_id if existing else ""
        _record_audit(
            persistence,
            from_state=from_state,
            to_state=snapshot.baseline_id,
            reason_code="BASELINE_REPLACED" if existing else "BASELINE_SYNCED",
            reason_message=args.reason_message,
        )
    finally:
        conn.close()

    print(f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print(f"db_path={settings.db_path}")
    print(f"baseline_id={snapshot.baseline_id}")
    print(f"positions_count={len(snapshot.positions)}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
