import argparse
import json
import sqlite3
import time
from pathlib import Path
from urllib import request

from hyperliquid.common.settings import compute_config_hash, load_settings
from hyperliquid.storage.db import DB_SCHEMA_VERSION, ensure_schema_version, init_db


def _print_kv(lines: list[str], label: str, value) -> None:
    lines.append(f"{label}={value}")


def _fetch_exchange_time(base_url: str) -> int:
    url = base_url.rstrip("/") + "/fapi/v1/time"
    raw = request.urlopen(url, timeout=5).read()
    payload = json.loads(raw.decode("utf-8"))
    return int(payload.get("serverTime", 0))


def _tail_lines(path: Path, count: int) -> list[str]:
    if count <= 0:
        return []
    if not path.exists():
        return ["metrics_log_missing"]
    return path.read_text().splitlines()[-count:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ops validation bundle (preflight + post-start).")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--output", help="Write report to file (prints to stdout too).")
    parser.add_argument("--metrics-tail", type=int, default=5, help="Tail N metric lines.")
    parser.add_argument(
        "--exchange-time",
        action="store_true",
        help="Fetch exchange server time using execution.binance.base_url.",
    )
    parser.add_argument(
        "--allow-create-db",
        action="store_true",
        help="Allow creating the DB during preflight if missing.",
    )
    parser.add_argument("--operator", default="", help="Operator name (optional).")
    parser.add_argument("--mode", default="", help="Run mode (live/dry-run/backfill-only).")
    args = parser.parse_args()

    config_path = Path(args.config)
    schema_path = Path(args.schema)
    settings = load_settings(config_path, schema_path)

    lines: list[str] = []
    status = "ok"
    lines.append("# Ops Validation Run")
    _print_kv(lines, "date_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    _print_kv(lines, "operator", args.operator or "unknown")
    _print_kv(lines, "environment", settings.environment)
    _print_kv(lines, "mode", args.mode or "unspecified")
    _print_kv(lines, "db_path", settings.db_path)
    _print_kv(lines, "status", status)
    lines.append("")

    lines.append("## Preflight")
    _print_kv(lines, "config_schema", "ok")
    _print_kv(lines, "config_hash", compute_config_hash(config_path))
    _print_kv(lines, "local_time_ms", int(time.time() * 1000))

    if args.exchange_time:
        base_url = str(
            settings.raw.get("execution", {})
            .get("binance", {})
            .get("base_url", "https://fapi.binance.com")
        )
        _print_kv(lines, "exchange_time_ms", _fetch_exchange_time(base_url))

    db_path = Path(settings.db_path)
    if not db_path.exists():
        if args.allow_create_db:
            conn = init_db(settings.db_path)
            try:
                ensure_schema_version(conn)
            finally:
                conn.close()
            _print_kv(lines, "schema_version", "created")
        else:
            _print_kv(lines, "schema_version", "db_missing")
            status = "fail"
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM system_state WHERE key = ?",
                ("schema_version",),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            _print_kv(lines, "schema_version", "missing")
            status = "fail"
        elif str(row[0]) != DB_SCHEMA_VERSION:
            _print_kv(lines, "schema_version", f"mismatch({row[0]})")
            status = "fail"
        else:
            _print_kv(lines, "schema_version", "ok")
    lines.append("")

    lines.append("## Post-Start")
    if not db_path.exists():
        _print_kv(lines, "post_start", "db_missing")
        status = "fail"
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for key in ("safety_mode", "safety_reason_code", "safety_reason_message"):
                row = conn.execute(
                    "SELECT value FROM system_state WHERE key = ?", (key,)
                ).fetchone()
                _print_kv(lines, key, row[0] if row else "")
            for key in ("last_processed_timestamp_ms", "last_processed_event_key"):
                row = conn.execute(
                    "SELECT value FROM system_state WHERE key = ?", (key,)
                ).fetchone()
                _print_kv(lines, key, row[0] if row else "")
            row = conn.execute("SELECT count(*) FROM order_results").fetchone()
            _print_kv(lines, "order_results_count", row[0] if row else 0)
            row = conn.execute("SELECT count(*) FROM audit_log").fetchone()
            _print_kv(lines, "audit_log_count", row[0] if row else 0)
        finally:
            conn.close()

    metrics_lines = _tail_lines(Path(settings.metrics_log_path), args.metrics_tail)
    if metrics_lines:
        lines.append("metrics_tail:")
        for line in metrics_lines:
            lines.append(f"- {line}")

    for idx, line in enumerate(lines):
        if line.startswith("status="):
            lines[idx] = f"status={status}"
            break
    output = "\n".join(lines)
    print(output)
    if args.output:
        Path(args.output).write_text(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
