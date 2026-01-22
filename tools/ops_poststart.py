import argparse
import sqlite3
from pathlib import Path
from typing import Optional

from hyperliquid.common.settings import load_settings


def _fetch_one(conn: sqlite3.Connection, query: str, params: tuple = ()) -> Optional[tuple]:
    return conn.execute(query, params).fetchone()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ops post-start checks.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--metrics-tail",
        type=int,
        default=0,
        help="Tail N lines from metrics log (0 to skip).",
    )
    args = parser.parse_args()

    settings = load_settings(Path(args.config), Path(args.schema))
    db_path = Path(settings.db_path)
    if not db_path.exists():
        raise SystemExit(f"db_missing={db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for key in ("safety_mode", "safety_reason_code", "safety_reason_message"):
            row = _fetch_one(conn, "SELECT value FROM system_state WHERE key = ?", (key,))
            print(f"{key}={row[0] if row else ''}")

        for key in ("last_processed_timestamp_ms", "last_processed_event_key"):
            row = _fetch_one(conn, "SELECT value FROM system_state WHERE key = ?", (key,))
            print(f"{key}={row[0] if row else ''}")

        row = _fetch_one(conn, "SELECT count(*) FROM order_results")
        print(f"order_results_count={row[0] if row else 0}")
        row = _fetch_one(conn, "SELECT count(*) FROM audit_log")
        print(f"audit_log_count={row[0] if row else 0}")
    finally:
        conn.close()

    if args.metrics_tail > 0:
        path = Path(settings.metrics_log_path)
        if path.exists():
            lines = path.read_text().splitlines()[-args.metrics_tail :]
            for line in lines:
                print(line)
        else:
            print("metrics_log_missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
