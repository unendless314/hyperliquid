# Ops Validation Evidence Log

Use this template to capture minimal, replayable proof for A1–A3 runs.
Keep each run short and attach only the essential outputs.
Example values below are placeholders; replace them for each run.

## Run Metadata
- Date/Time (UTC): 2026-01-22
- Operator: codex
- Environment (testnet/mainnet): testnet
- Mode (dry-run / live / backfill-only): dry-run, backfill-only, live
- Config hash: 6699688d33534a715a4bfcc969e1acd165e8a0d6ed6f9dc89615769adae3109a
- DB path: data/hyperliquid.db

## A1 Preflight Evidence
- validate_config output: OK
- config_hash output: 6699688d33534a715a4bfcc969e1acd165e8a0d6ed6f9dc89615769adae3109a
- time sync output (local + exchange):
  - local_time_ms=1769075626207
  - binance_server_time_ms=1769075631935
- schema_version check: schema_version_ok

## A2 Mode-Specific Validation Evidence
- system_state (safety_*):
  - safety_mode|ARMED_SAFE
  - safety_reason_code|BOOTSTRAP
  - safety_reason_message|Initial bootstrap state
- system_state (last_processed_*):
  - last_processed_timestamp_ms|1769075649037
  - last_processed_event_key|1769075649037|0|boot|BTCUSDT
- order_results count: 0
- audit_log count: 0
- metrics tail snippet:
  - [METRICS] {"name": "cursor_lag_ms", "value": 0}
- emit_boot_event behavior noted (yes/no, effect on order_results): yes, order_results stayed 0
 
### Live Mode (testnet)
- config: /tmp/ops_live.yaml (base_url=https://demo-fapi.binance.com)
- system_state (safety_*):
  - safety_mode|ARMED_SAFE
  - safety_reason_code|SNAPSHOT_STALE
  - safety_reason_message|Exchange snapshot is stale
- order_results count: 0
- audit_log count: 0
- metrics tail snippet:
  - [METRICS] {"name": "reconcile_max_drift", "value": 0.0, "tags": {"reason": "SNAPSHOT_STALE"}}
- ops_poststart (read-only) output:
  - safety_mode=ARMED_SAFE
  - safety_reason_code=SNAPSHOT_STALE
  - safety_reason_message=Exchange snapshot is stale
  - last_processed_timestamp_ms=0
  - last_processed_event_key=
  - order_results_count=0
  - audit_log_count=0

## A3 Failure Path Evidence
For each failure path, capture:
- Trigger steps used:
- Expected signal(s):
- Observed system_state:
- Observed audit_log row(s):
- Observed metrics/logs:

### SCHEMA_VERSION_MISMATCH
- Trigger steps:
  - Create temp config `/tmp/ops_schema.yaml` with db_path data/ops_schema.db
  - Boot once to create DB, then set schema_version=999
  - Run: PYTHONPATH=src python3 src/hyperliquid/main.py --mode dry-run --config /tmp/ops_schema.yaml --no-emit-boot-event
- Expected:
  - Startup error and safety_mode=HALT, safety_reason_code=SCHEMA_VERSION_MISMATCH
- Observed system_state:
  - safety_mode|HALT
  - safety_reason_code|SCHEMA_VERSION_MISMATCH
  - safety_reason_message|DB schema version mismatch
  - schema_version|999
- Observed audit_log row(s):
  - safety|safety_mode|ARMED_SAFE|HALT|SCHEMA_VERSION_MISMATCH
- Observed metrics/logs:
  - RuntimeError: SCHEMA_VERSION_MISMATCH (startup error)

### RECONCILE_CRITICAL
- Trigger steps:
  - Create temp config `/tmp/ops_reconcile.yaml` with db_path data/ops_reconcile.db
  - Set execution.binance.enabled=true, mode=live
  - Set safety.snapshot_max_stale_ms to large value (avoid SNAPSHOT_STALE)
  - Seed local position with symbol ZZZUSDT (filled order)
  - Run: PYTHONPATH=src python3 src/hyperliquid/main.py --mode live --config /tmp/ops_reconcile.yaml --no-emit-boot-event
- Expected:
  - safety_mode=HALT, safety_reason_code=RECONCILE_CRITICAL
- Observed system_state:
  - safety_mode|HALT
  - safety_reason_code|RECONCILE_CRITICAL
  - safety_reason_message|Missing symbols detected: missing_local=['ZZZUSDT'] missing_exchange=[]
- Observed audit_log row(s):
  - safety|safety_mode|ARMED_SAFE|HALT|RECONCILE_CRITICAL
- Observed metrics/logs:
  - reconcile_result mode=HALT reason=RECONCILE_CRITICAL

### BACKFILL_WINDOW_EXCEEDED
- Trigger steps:
  - Create temp config `/tmp/ops_backfill.yaml` with db_path data/ops_backfill.db
  - Set ingest.hyperliquid.enabled=true, mode=stub, backfill_window_ms=1000
  - Set system_state.last_processed_timestamp_ms to now-5000
  - Run: PYTHONPATH=src python3 src/hyperliquid/main.py --mode backfill-only --config /tmp/ops_backfill.yaml
- Expected:
  - safety_mode=HALT, safety_reason_code=BACKFILL_WINDOW_EXCEEDED
- Observed system_state:
  - safety_mode|HALT
  - safety_reason_code|BACKFILL_WINDOW_EXCEEDED
  - safety_reason_message|Gap exceeds backfill window
- Observed audit_log row(s):
  - safety|safety_mode|ARMED_SAFE|HALT|BACKFILL_WINDOW_EXCEEDED
- Observed metrics/logs:
  - ingest_gap_exceeded logged with backfill_window_ms=1000

### EXECUTION_RETRY_BUDGET_EXCEEDED
- Trigger steps:
  - Create temp config `/tmp/ops_retry.yaml` with db_path data/ops_retry.db
  - Set execution.binance.enabled=true, mode=live
  - Set retry_budget_max_attempts=1, retry_budget_window_sec=1
  - Seed UNKNOWN order_result for correlation_id ops-retry-1
  - Run Python snippet to call execution.execute(intent) with load_dotenv()
- Expected:
  - safety_reason_code=EXECUTION_RETRY_BUDGET_EXCEEDED, result UNKNOWN
- Observed system_state:
  - safety_mode|ARMED_SAFE
  - safety_reason_code|EXECUTION_RETRY_BUDGET_EXCEEDED
  - safety_reason_message|Execution retry budget exceeded; requires operator review
- Observed audit_log row(s):
  - count=0 (no row because safety_mode stayed ARMED_SAFE and status remained UNKNOWN)
- Observed metrics/logs:
  - result_status=UNKNOWN error_code=RETRY_BUDGET_EXCEEDED
