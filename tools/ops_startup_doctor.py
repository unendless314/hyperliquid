import argparse
import sqlite3
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import DB_SCHEMA_VERSION


def _print_kv(lines: list[str], label: str, value) -> None:
    lines.append(f"{label}={value}")


def _read_system_state(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


def _load_schema_version(conn: sqlite3.Connection) -> str:
    return _read_system_state(conn, "schema_version")


def _format_audit_row(row: tuple) -> str:
    timestamp_ms, category, entity_id, reason_code, reason_message = row
    return (
        f"timestamp_ms={timestamp_ms} category={category} entity_id={entity_id} "
        f"reason_code={reason_code} reason_message={reason_message}"
    )


def _suggest_for_halt(reason_code: str, *, config_path: Path, schema_path: Path) -> list[str]:
    suggestions: list[str] = []
    if reason_code == "BACKFILL_WINDOW_EXCEEDED":
        suggestions.append(
            "Set ingest.maintenance_skip_gap=true, then run ops_recovery maintenance-skip."
        )
        suggestions.append(
            "Run dry-run to verify state, then unhalt and promote after verification."
        )
        suggestions.append(
            f"Example: PYTHONPATH=src python3 tools/ops_recovery.py --config {config_path} "
            f"--schema {schema_path} --action maintenance-skip --reason-message "
            '"Maintenance skip applied"'
        )
    elif reason_code == "RECONCILE_CRITICAL":
        suggestions.append("Verify positions and symbol coverage before unhalt.")
    elif reason_code == "SCHEMA_VERSION_MISMATCH":
        suggestions.append("Rebuild DB or migrate schema to the current version.")
    elif reason_code == "EXECUTION_RETRY_BUDGET_EXCEEDED":
        suggestions.append("Check exchange connectivity, rate limits, and API credentials.")
    else:
        suggestions.append("Check logs for the root cause and resolve before unhalt.")
    return suggestions


def _suggest_for_safe(reason_code: str, *, config_path: Path, schema_path: Path) -> list[str]:
    suggestions: list[str] = []
    if reason_code == "SNAPSHOT_STALE":
        suggestions.append(
            "Snapshot is stale; verify exchange snapshot timing and adapter timestamp logic."
        )
        suggestions.append(
            "If testing, consider increasing safety.snapshot_max_stale_ms temporarily."
        )
    elif reason_code == "RECONCILE_WARN":
        suggestions.append("Verify positions match expected state before promotion.")
    elif reason_code == "EXECUTION_RETRY_BUDGET_EXCEEDED":
        suggestions.append("Inspect execution errors and connectivity before promotion.")
    else:
        suggestions.append("Verify state, then promote if safe.")
    suggestions.append(
        f"Example: PYTHONPATH=src python3 tools/ops_recovery.py --config {config_path} "
        f"--schema {schema_path} --action promote --reason-message "
        '"Promote to ARMED_LIVE after verification" --allow-non-halt'
    )
    return suggestions


def main() -> int:
    parser = argparse.ArgumentParser(description="Startup doctor (diagnose safety blockers).")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--audit-tail", type=int, default=5, help="Tail N audit log entries.")
    parser.add_argument("--output", help="Write report to file (prints to stdout too).")
    args = parser.parse_args()

    config_path = Path(args.config)
    schema_path = Path(args.schema)
    settings = load_settings(config_path, schema_path)

    lines: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []
    status = "ok"

    lines.append("# Startup Doctor")
    _print_kv(lines, "date_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    _print_kv(lines, "environment", settings.environment)
    _print_kv(lines, "config_path", str(config_path))
    _print_kv(lines, "db_path", settings.db_path)
    _print_kv(lines, "status", status)
    lines.append("")

    db_path = Path(settings.db_path)
    if not db_path.exists():
        blockers.append("db_missing")
        suggestions.append("DB file missing; run a dry-run start to initialize.")
        lines.append("## System State")
        _print_kv(lines, "schema_version", "db_missing")
        _print_kv(lines, "safety_mode", "")
        _print_kv(lines, "safety_reason_code", "")
        _print_kv(lines, "safety_reason_message", "")
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            try:
                schema_version = _load_schema_version(conn)
                lines.append("## System State")
                _print_kv(lines, "schema_version", schema_version or "missing")
                safety_mode = _read_system_state(conn, "safety_mode")
                reason_code = _read_system_state(conn, "safety_reason_code")
                reason_message = _read_system_state(conn, "safety_reason_message")
                _print_kv(lines, "safety_mode", safety_mode)
                _print_kv(lines, "safety_reason_code", reason_code)
                _print_kv(lines, "safety_reason_message", reason_message)
                _print_kv(lines, "safety_changed_at_ms", _read_system_state(conn, "safety_changed_at_ms"))
                _print_kv(lines, "last_processed_timestamp_ms", _read_system_state(conn, "last_processed_timestamp_ms"))
                _print_kv(lines, "last_processed_event_key", _read_system_state(conn, "last_processed_event_key"))
                _print_kv(lines, "maintenance_skip_applied_ms", _read_system_state(conn, "maintenance_skip_applied_ms"))
                _print_kv(lines, "adapter_last_success_ms", _read_system_state(conn, "adapter_last_success_ms"))
                _print_kv(lines, "adapter_last_error_ms", _read_system_state(conn, "adapter_last_error_ms"))

                if schema_version and schema_version != DB_SCHEMA_VERSION:
                    blockers.append("schema_version_mismatch")
                    suggestions.append("Schema version mismatch; rebuild DB or migrate.")

                if not safety_mode:
                    blockers.append("safety_state_missing")
                    suggestions.append("Safety state missing; start once to initialize.")
                elif safety_mode == "HALT":
                    blockers.append("HALT")
                    suggestions.extend(
                        _suggest_for_halt(
                            reason_code, config_path=config_path, schema_path=schema_path
                        )
                    )
                elif safety_mode == "ARMED_SAFE":
                    warnings.append("ARMED_SAFE")
                    suggestions.extend(
                        _suggest_for_safe(
                            reason_code, config_path=config_path, schema_path=schema_path
                        )
                    )

                lines.append("")
                lines.append("## Audit Log Tail")
                if args.audit_tail <= 0:
                    lines.append("audit_tail: (disabled)")
                else:
                    try:
                        rows = conn.execute(
                            "SELECT timestamp_ms, category, entity_id, reason_code, reason_message "
                            "FROM audit_log ORDER BY id DESC LIMIT ?",
                            (args.audit_tail,),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        warnings.append("audit_log_missing")
                        lines.append("audit_tail: (missing)")
                    else:
                        if not rows:
                            lines.append("audit_tail: (empty)")
                        else:
                            lines.append("audit_tail:")
                            for row in rows:
                                lines.append(f"- {_format_audit_row(row)}")
            except sqlite3.OperationalError:
                blockers.append("db_schema_missing")
                suggestions.append("DB schema missing or invalid; run a dry-run start to initialize.")
                lines.append("## System State")
                _print_kv(lines, "schema_version", "missing")
                _print_kv(lines, "safety_mode", "")
                _print_kv(lines, "safety_reason_code", "")
                _print_kv(lines, "safety_reason_message", "")
        finally:
            conn.close()

    if blockers:
        status = "fail"
    elif warnings:
        status = "warn"
    lines.append("")
    _print_kv(lines, "blockers", ",".join(blockers) if blockers else "none")
    _print_kv(lines, "warnings", ",".join(warnings) if warnings else "none")
    _print_kv(lines, "suggested_actions", " | ".join(suggestions) if suggestions else "none")
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
