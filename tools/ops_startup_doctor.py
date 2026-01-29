import argparse
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env file to ensure environment variables are available
load_dotenv()

from hyperliquid.common.settings import load_settings
from hyperliquid.execution.adapters.binance import BinanceExecutionAdapter, BinanceExecutionConfig
from hyperliquid.safety.reconcile import compute_drift, find_missing_symbols, normalize_positions
from hyperliquid.storage.db import DB_SCHEMA_VERSION
from hyperliquid.storage.baseline import load_active_baseline


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


def _append_reconcile_diagnosis(
    lines: list[str],
    *,
    settings,
    baseline,
    config_path: Path,
    schema_path: Path,
    no_exchange_fetch: bool,
) -> None:
    lines.append("")
    lines.append("## Reconciliation Diagnosis (Verbose)")
    lines.append(
        "note=requires_network_and_binance_api_permissions use --no-exchange-fetch to skip"
    )
    if baseline is None:
        local_positions = {}
    else:
        local_positions = baseline.positions

    execution_config = BinanceExecutionConfig.from_settings(settings.raw)
    if not execution_config.enabled or execution_config.mode != "live":
        lines.append("status=skipped reason=execution_adapter_not_enabled")
        return
    if no_exchange_fetch:
        lines.append("status=skipped reason=exchange_fetch_disabled")
        return

    try:
        adapter = BinanceExecutionAdapter(execution_config)
        exchange_positions, _ = adapter.fetch_positions()
    except Exception as exc:
        lines.append(f"status=error reason=fetch_positions_failed error={exc}")
        return

    local_norm = normalize_positions(local_positions)
    exchange_norm = normalize_positions(exchange_positions)
    missing_local, missing_exchange = find_missing_symbols(
        local_symbols=local_norm.keys(),
        exchange_symbols=exchange_norm.keys(),
    )
    drift_report = compute_drift(local_norm, exchange_norm)

    lines.append(f"baseline_positions={local_positions}")
    lines.append(f"exchange_positions={exchange_positions}")
    lines.append(f"local_normalized={local_norm}")
    lines.append(f"exchange_normalized={exchange_norm}")
    lines.append(f"missing_local={missing_local}")
    lines.append(f"missing_exchange={missing_exchange}")
    lines.append(f"max_drift={drift_report.max_drift}")
    for symbol, drift in sorted(drift_report.drifts.items()):
        local_qty = local_norm.get(symbol, 0.0)
        exchange_qty = exchange_norm.get(symbol, 0.0)
        lines.append(
            f"drift symbol={symbol} local={local_qty} exchange={exchange_qty} value={drift}"
        )

    critical_threshold = settings.raw.get("safety", {}).get("critical_threshold", 0.01)
    warn_threshold = settings.raw.get("safety", {}).get("warn_threshold", 0.001)
    if missing_local or missing_exchange:
        conclusion = "RECONCILE_CRITICAL missing_symbol"
    elif drift_report.max_drift >= critical_threshold:
        conclusion = "RECONCILE_CRITICAL drift_exceeds_threshold"
    elif drift_report.max_drift >= warn_threshold:
        conclusion = "ARMED_SAFE drift_warn_threshold"
    else:
        conclusion = "ARMED_LIVE drift_within_thresholds"
    lines.append(f"conclusion={conclusion}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Startup doctor (diagnose safety blockers).")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--audit-tail", type=int, default=5, help="Tail N audit log entries.")
    parser.add_argument("--output", help="Write report to file (prints to stdout too).")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed reconciliation diagnosis when HALT/RECONCILE_CRITICAL.",
    )
    parser.add_argument(
        "--no-exchange-fetch",
        action="store_true",
        help="Skip exchange fetch for verbose reconciliation diagnosis.",
    )
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
    safety_mode = ""
    reason_code = ""
    baseline = None
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
                baseline = load_active_baseline(conn)
                _print_kv(lines, "baseline_id", baseline.baseline_id if baseline else "")
                _print_kv(lines, "baseline_created_at_ms", baseline.created_at_ms if baseline else "")

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
                    if (
                        reason_code == "RECONCILE_CRITICAL"
                        and "missing_exchange" in (reason_message or "")
                        and baseline is None
                    ):
                        suggestions.append("Exchange-only positions detected; sync baseline positions.")
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

        if (
            args.verbose
            and safety_mode == "HALT"
            and reason_code == "RECONCILE_CRITICAL"
        ):
            _append_reconcile_diagnosis(
                lines,
                settings=settings,
                baseline=baseline,
                config_path=config_path,
                schema_path=schema_path,
                no_exchange_fetch=args.no_exchange_fetch,
            )

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
