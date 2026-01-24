import argparse
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import init_db
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.safety import load_safety_state, set_safety_state


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset safety state with audit log entry.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--mode", required=True, help="Target safety mode (e.g., ARMED_SAFE)")
    parser.add_argument(
        "--reason-code",
        default="MANUAL_OVERRIDE",
        help="Reason code for safety reset (default: MANUAL_OVERRIDE).",
    )
    parser.add_argument(
        "--reason-message",
        default="Operator reset",
        help="Reason message for safety reset.",
    )
    parser.add_argument(
        "--allow-non-halt",
        action="store_true",
        help="Allow reset even if current mode is not HALT.",
    )
    args = parser.parse_args()

    settings = load_settings(Path(args.config), Path(args.schema))
    conn = init_db(settings.db_path)
    try:
        current = load_safety_state(conn)
        current_mode = current.mode if current else ""
        current_reason_code = current.reason_code if current else ""
        current_reason_message = current.reason_message if current else ""
        if not args.allow_non_halt and current_mode != "HALT":
            raise SystemExit("safety_mode_not_halt")
        if current_mode == args.mode:
            raise SystemExit("safety_mode_noop")
        persistence = DbPersistence(conn)
        set_safety_state(
            conn,
            mode=args.mode,
            reason_code=args.reason_code,
            reason_message=args.reason_message,
            audit_recorder=persistence.record_audit,
        )
    finally:
        conn.close()

    print(f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print(f"db_path={settings.db_path}")
    print(f"previous_mode={current_mode}")
    print(f"previous_reason_code={current_reason_code}")
    print(f"previous_reason_message={current_reason_message}")
    print(f"new_mode={args.mode}")
    print(f"new_reason_code={args.reason_code}")
    print(f"new_reason_message={args.reason_message}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
