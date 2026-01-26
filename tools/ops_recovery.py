import argparse
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import init_db, set_system_state, update_cursor, get_system_state
from hyperliquid.storage.persistence import AuditLogEntry, DbPersistence
from hyperliquid.storage.safety import load_safety_state, set_safety_state


ALLOWLIST_REASONS = {
    "SNAPSHOT_STALE",
    "BACKFILL_WINDOW_EXCEEDED",
    "RECONCILE_CRITICAL",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_audit(persistence: DbPersistence, *, from_state: str, to_state: str, reason_code: str, reason_message: str) -> None:
    persistence.record_audit(
        AuditLogEntry(
            timestamp_ms=_now_ms(),
            category="safety",
            entity_id="safety_mode",
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            reason_message=reason_message,
            event_id="",
            metadata=None,
        )
    )


def _maintenance_skip(
    conn,
    persistence: DbPersistence,
    *,
    reason_message: str,
    allow_non_halt: bool,
    ingest_config: dict,
) -> None:
    current = load_safety_state(conn)
    current_mode = current.mode if current else ""
    current_reason = current.reason_code if current else ""
    if not allow_non_halt and current_mode != "HALT":
        raise SystemExit("safety_mode_not_halt")
    if current_reason != "BACKFILL_WINDOW_EXCEEDED":
        raise SystemExit("safety_reason_not_backfill")
    if not ingest_config.get("maintenance_skip_gap", False):
        raise SystemExit("maintenance_skip_gap_disabled")
    if get_system_state(conn, "maintenance_skip_applied_ms") is not None:
        raise SystemExit("maintenance_skip_already_applied")

    now_ms = _now_ms()
    update_cursor(
        conn,
        timestamp_ms=now_ms,
        event_index=0,
        tx_hash="maintenance",
        symbol="MAINTENANCE",
        commit=False,
    )
    set_system_state(conn, "maintenance_skip_applied_ms", str(now_ms), commit=False)
    conn.commit()
    _record_audit(
        persistence,
        from_state=current_mode,
        to_state=current_mode,
        reason_code="MAINTENANCE_SKIP_APPLIED",
        reason_message=reason_message,
    )


def _set_mode(
    conn,
    persistence: DbPersistence,
    *,
    target_mode: str,
    reason_code: str,
    reason_message: str,
    allow_non_halt: bool,
) -> None:
    current = load_safety_state(conn)
    current_mode = current.mode if current else ""
    if not allow_non_halt and current_mode != "HALT":
        raise SystemExit("safety_mode_not_halt")
    if current_mode == target_mode:
        raise SystemExit("safety_mode_noop")
    set_safety_state(
        conn,
        mode=target_mode,
        reason_code=reason_code,
        reason_message=reason_message,
        audit_recorder=persistence.record_audit,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ops recovery tool (maintenance skip / unhalt / promote).")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--action",
        required=True,
        choices=["maintenance-skip", "unhalt", "promote"],
        help="Recovery action to perform.",
    )
    parser.add_argument(
        "--reason-message",
        default="Operator recovery",
        help="Reason message for audit trail.",
    )
    parser.add_argument(
        "--allow-non-halt",
        action="store_true",
        help="Allow action even if current mode is not HALT.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned action without writing changes.",
    )
    args = parser.parse_args()

    settings = load_settings(Path(args.config), Path(args.schema))
    conn = init_db(settings.db_path)
    try:
        current = load_safety_state(conn)
        current_mode = current.mode if current else ""
        current_reason = current.reason_code if current else ""
        persistence = DbPersistence(conn)
        if args.dry_run:
            print(f"action={args.action}")
            print(f"db_path={settings.db_path}")
            print(f"current_mode={current_mode}")
            print(f"current_reason_code={current_reason}")
            print(f"allowlist_reason_codes={sorted(ALLOWLIST_REASONS)}")
            print("status=dry_run")
            return 0

        if args.action == "maintenance-skip":
            _maintenance_skip(
                conn,
                persistence,
                reason_message=args.reason_message,
                allow_non_halt=args.allow_non_halt,
                ingest_config=settings.raw.get("ingest", {}),
            )
            new_mode = current_mode
            new_reason = current_reason
        elif args.action == "unhalt":
            _set_mode(
                conn,
                persistence,
                target_mode="ARMED_SAFE",
                reason_code="MANUAL_UNHALT",
                reason_message=args.reason_message,
                allow_non_halt=args.allow_non_halt,
            )
            new_mode = "ARMED_SAFE"
            new_reason = "MANUAL_UNHALT"
        else:
            _set_mode(
                conn,
                persistence,
                target_mode="ARMED_LIVE",
                reason_code="MANUAL_PROMOTE",
                reason_message=args.reason_message,
                allow_non_halt=args.allow_non_halt,
            )
            new_mode = "ARMED_LIVE"
            new_reason = "MANUAL_PROMOTE"
    finally:
        conn.close()

    print(f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print(f"db_path={settings.db_path}")
    print(f"action={args.action}")
    print(f"previous_mode={current_mode}")
    print(f"previous_reason_code={current_reason}")
    print(f"new_mode={new_mode}")
    print(f"new_reason_code={new_reason}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
