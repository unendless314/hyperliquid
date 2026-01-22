# Runbook

## Startup

Prerequisites:
- config/settings.yaml validated
- config_hash computed and recorded
- API keys/target wallet available for selected environment (loaded via env vars)
- Time sync offset computed
- Missing required env vars in live mode will raise a startup error (not a safety-state transition). Current checks are enforced in:
  - src/hyperliquid/ingest/adapters/hyperliquid.py (HYPERLIQUID_TARGET_WALLET required for ingest live mode)
  - src/hyperliquid/execution/adapters/binance.py (BINANCE_API_KEY/BINANCE_API_SECRET required for execution live mode)

Steps:
1. Validate config:
   - python tools/validate_config.py --config config/settings.yaml --schema config/schema.json
   - Expected: exit code 0, no schema errors printed.
   - Failure/rollback: stop and fix config/settings.yaml (do not start service).
2. Compute config_hash:
   - python tools/hash_config.py --config config/settings.yaml
   - Expected: prints config_hash value (record it).
   - Failure/rollback: stop and fix config/settings.yaml or hash tool errors.
3. Start service (environment is selected by config/settings.yaml):
   - python src/hyperliquid/main.py --mode live --config config/settings.yaml
   - Expected: startup completes without HALT; safety_mode is ARMED_SAFE or ARMED_LIVE per config.
   - Failure/rollback: stop process, inspect logs, revert config/settings.yaml if needed, and restart after correction.

Verification:
- sqlite3 <db_path> "select key, value from system_state where key like 'safety_%';"
- sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
- tail -n 50 <metrics_log_path>

### Scripted Preflight (Recommended)
Copy/paste sequence:
- PYTHONPATH=src python3 tools/ops_preflight.py --config config/settings.yaml --schema config/schema.json --exchange-time
- python tools/validate_config.py --config config/settings.yaml --schema config/schema.json
- python tools/hash_config.py --config config/settings.yaml
- Ensure env vars are set (no output means unset):
  - echo "$BINANCE_API_KEY" | wc -c
  - echo "$BINANCE_API_SECRET" | wc -c
  - echo "$HYPERLIQUID_TARGET_WALLET" | wc -c
- Note: .env is loaded automatically at startup (python-dotenv).
- python - <<'PY'
import time
print(f"local_time_ms={int(time.time() * 1000)}")
PY
- If using Binance, capture exchange time offset (example):
  - python - <<'PY'
import json
from urllib import request
raw = request.urlopen("https://fapi.binance.com/fapi/v1/time", timeout=5).read()
server_time = json.loads(raw.decode("utf-8"))["serverTime"]
print(f"binance_server_time_ms={server_time}")
PY
- python - <<'PY'
from pathlib import Path
from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import init_db, assert_schema_version
settings = load_settings(Path("config/settings.yaml"), Path("config/schema.json"))
conn = init_db(settings.db_path)
assert_schema_version(conn)
conn.close()
print("preflight_ok")
PY
Expected:
- "preflight_ok" printed.
- Time sync offset noted (local vs exchange time).
- No missing env vars (wc -c outputs > 1).
Failure/rollback:
- Do not start service; fix config/env/time sync before proceeding.

### Scripted Post-Start Checks (Recommended)
Copy/paste sequence:
- PYTHONPATH=src python3 tools/ops_poststart.py --config config/settings.yaml --schema config/schema.json --metrics-tail 5
- sqlite3 <db_path> "select key, value from system_state where key in ('safety_mode','safety_reason_code','safety_reason_message');"
- sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
- sqlite3 <db_path> "select count(*) from audit_log;"
- tail -n 50 <metrics_log_path>
Expected:
- safety_mode populated in system_state.
- last_processed_* keys present after ingest starts.
- audit_log count increases over time.
Failure/rollback:
- Stop process and investigate logs/metrics; do not continue to live validation.

### Mode-Specific Validation (Recommended)
Dry-run:
- Expect no external order placement (adapter disabled). order_results may be written by local execution flow.
- sqlite3 <db_path> "select count(*) from order_results;"
- Note: emit_boot_event (default True) can create a row in order_results on startup.

Live:
- Expect execution adapter enabled and safety_mode != HALT after startup.
- sqlite3 <db_path> "select value from system_state where key='safety_mode';"
Failure/rollback:
- If safety_mode == HALT, stop process and follow incident response.

Backfill-only:
- Expect cursor advances and no external order placement (adapter disabled).
- sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
- sqlite3 <db_path> "select count(*) from order_results;"
Failure/rollback:
- If cursor does not advance or safety_mode == HALT, stop process and follow incident response.

## Incident Response

### 1) Entered ARMED_SAFE
Checklist:
- Read reason code and timestamp from system_state
- Check logs around the transition time
- If drift-related, inspect reconciliation output
- If gap-related, inspect backfill logs and cursor lag

### 2) Entered HALT
Checklist:
- Identify reason code (e.g., BACKFILL_WINDOW_EXCEEDED, STORAGE_UNAVAILABLE, EXECUTION_ADAPTER_NOT_IMPLEMENTED)
- Stop trading immediately (switch to HALT / stop the process)
- Fix root cause (storage, config mismatch, position mode)
- Restart after manual approval

### 3) Execution Retry Budget Exceeded
Checklist:
- Inspect system_state.safety_reason_code == EXECUTION_RETRY_BUDGET_EXCEEDED
- Review order_results for UNKNOWN and RETRY_BUDGET_EXCEEDED errors
- Verify exchange connectivity and API health
- Consider increasing retry_budget_window_sec or retry_budget_max_attempts only if
  exchange availability is the root cause

Maintenance restart:
- Use an explicit maintenance flag (config: ingest.maintenance_skip_gap=true) to skip gap enforcement on restart.
- When enabled, cursor is set to now, safety_reason_code records the bypass, and the system starts in ARMED_SAFE.
- Before promotion, manually verify:
  - Target wallet position matches expected state.
  - No unexpected pending intents exist.
  - Recent fills align with the intended restart window.
- Manually promote to ARMED_LIVE after verifying positions.
- Note: maintenance skip only applies to gap-related HALT (reason_code=BACKFILL_WINDOW_EXCEEDED).

### 4) Repeated Order Failures
Checklist:
- Inspect error_code and error_message in order_results
- Check rate limit logs and backoff state
- Verify API keys and permissions
- Check exchange status

### Failure Triggers and Expected Signals (Ops Validation Aid)
- SCHEMA_VERSION_MISMATCH
  - Trigger: set system_state.schema_version to a different value before boot.
  - Expected: safety_mode=HALT, safety_reason_code=SCHEMA_VERSION_MISMATCH.
- EXECUTION_RETRY_BUDGET_EXCEEDED
  - Trigger: force adapter query to fail for UNKNOWN orders repeatedly.
  - Expected: safety_mode transitions to ARMED_SAFE or HALT per config.
- RECONCILE_CRITICAL
  - Trigger: exchange snapshot missing symbols or large drift.
  - Expected: safety_mode=HALT, safety_reason_code=RECONCILE_CRITICAL.
- BACKFILL_WINDOW_EXCEEDED
  - Trigger: enforce gap beyond backfill window.
  - Expected: safety_mode=HALT, safety_reason_code=BACKFILL_WINDOW_EXCEEDED.

### Rollback Triggers (Operational)
Initiate rollback or disable trading when any of the following are observed:
- system_state.safety_mode == HALT (reason_code indicates critical fault)
- system_state.safety_reason_code in
  - SCHEMA_VERSION_MISMATCH
  - EXECUTION_ADAPTER_NOT_IMPLEMENTED
  - EXECUTION_RETRY_BUDGET_EXCEEDED
  - RECONCILE_CRITICAL
  - BACKFILL_WINDOW_EXCEEDED
- audit_log shows repeated execution transitions to UNKNOWN with error_code=RATE_LIMITED
  or TIMEOUT over a short window (rate limit outage or connectivity issue)

## Recovery Procedures

### Cursor Recovery
- Verify last_processed_event_key in system_state
- Confirm processed_txs exists for the cursor event
- If missing, enter backfill-only mode before live

### Order State Recovery
- For UNKNOWN orders, query exchange by clientOrderId
- Update order_results based on actual status
- UNKNOWNs are retried automatically up to the configured retry budget; after that,
  safety transitions to ARMED_SAFE or HALT per execution.retry_budget_mode.

### Post-Recovery Checks
- Confirm safety_reason_code remains accurate after restart.
- Confirm audit_log includes the last transition.
- Confirm last_processed_event_key matches expected cursor.

## Maintenance

### Backups
- Daily SQLite backup
- Backup path uses db_path from settings.yaml
- Suggested filename pattern: backup-YYYYMMDD-HHMM.db (e.g., backup-20260122-2330.db)
- Verify restore by reading system_state

### Schema Updates
- Apply migration scripts manually during MVP (preferred: rebuild DB if possible).
- Verify schema version and system_state.
- DB_SCHEMA_VERSION=3 adds audit_log (and requires order_results.contract_version).
- If rebuilding:
  1. Stop the service.
  2. Backup existing DB: `cp <db_path> <db_path>.bak-YYYYMMDD-HHMM`
     - Or use: `PYTHONPATH=src python3 tools/ops_rebuild_db.py --config config/settings.yaml --schema config/schema.json --backup --force`
  3. Recreate empty DB:
     - python - <<'PY'
from pathlib import Path
from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import init_db, assert_schema_version
settings = load_settings(Path("config/settings.yaml"), Path("config/schema.json"))
conn = init_db(settings.db_path)
assert_schema_version(conn)
conn.close()
print("db_rebuilt")
PY
  4. Post-check:
     - sqlite3 <db_path> "select value from system_state where key='schema_version';"
     - sqlite3 <db_path> "select count(*) from audit_log;"
     - sqlite3 <db_path> "select count(*) from order_intents;"
     - sqlite3 <db_path> "select count(*) from order_results;"
