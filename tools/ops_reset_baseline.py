import argparse
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.storage.baseline import load_active_baseline, reset_baseline
from hyperliquid.storage.db import assert_schema_version, init_db
from hyperliquid.storage.persistence import AuditLogEntry, DbPersistence


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_audit(
    persistence: DbPersistence,
    *,
    from_state: str,
    to_state: str,
    reason_code: str,
    reason_message: str,
) -> None:
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
    parser = argparse.ArgumentParser(description="Reset (deactivate) the active baseline snapshot.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--operator", default="", help="Operator name for audit log.")
    parser.add_argument(
        "--reason-message",
        default="Baseline reset",
        help="Reason message for audit trail.",
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

    conn = init_db(settings.db_path)
    try:
        assert_schema_version(conn)
        persistence = DbPersistence(conn)
        existing = load_active_baseline(conn)
        if args.dry_run:
            print(f"db_path={settings.db_path}")
            print(f"baseline_id={(existing.baseline_id if existing else '')}")
            print("status=dry_run")
            return 0
        if existing is None:
            raise SystemExit("baseline_not_found")
        reset_baseline(conn)
        _record_audit(
            persistence,
            from_state=existing.baseline_id,
            to_state="",
            reason_code="BASELINE_RESET",
            reason_message=args.reason_message,
        )
    finally:
        conn.close()

    print(f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print(f"db_path={settings.db_path}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
