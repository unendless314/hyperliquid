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

### Ops Validation Bundle (Recommended)
Single command to collect preflight + post-start evidence:
- PYTHONPATH=src python3 tools/ops_validate_run.py --config config/settings.yaml --schema config/schema.json --exchange-time --metrics-tail 5 --output docs/ops_validation_run.txt
- Note: add --allow-create-db only for first-time bootstrap when the DB does not exist.
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

## Production Readiness (Go/No-Go)
Checklist (record evidence using docs/OPS_VALIDATION.md; keep evidence in docs/ops_validation_run.txt):
- Config validated and config_hash recorded (Startup steps 1-2 completed).
- Scripted preflight + post-start checks completed with expected output.
- Ops validation bundle captured (docs/ops_validation_run.txt updated for this run).
- Runbook flow validated end-to-end in the target mode (live/dry-run/backfill-only).
- Decision strategy version set and documented (see docs/modules/DECISION.md acceptance).
- DB schema version confirmed:
  - sqlite3 <db_path> "select value from system_state where key='schema_version';"
  - If schema_version < 3, rebuild DB before live use (do not reuse old DBs).
- Key integration tests executed per docs/TEST_PLAN.md (record date + results).
- Rollback triggers and escalation path reviewed with operator on duty.

## Production Live Minimal Validation (Reduce-Only)
Use this checklist for the smallest possible production validation with lowest risk.

0) Preflight (required)
- Confirm filters_enabled=true.
- Confirm config/settings.yaml uses production endpoints, wallet, and risk limits.
- Run tools/validate_config.py + tools/hash_config.py and record the hash.

1) Go/No-Go (required)
- Complete the RUNBOOK Go/No-Go checklist (monitoring/alerting/rollback).

2) Minimal Live Validation (reduce-only)
- Choose a symbol with an existing position (e.g., BTCUSDT).
- Submit a reduce-only market order at the minimum notional (e.g., 10–50 USDT).

3) Evidence (required)
- Run tools/ops_validate_run.py to capture post-trade evidence.
- Record:
  - safety_mode / reason_code
  - order_result status=FILLED
  - exchange_order_id
  - audit_log_count
  - metrics_tail timestamps

4) Rollback readiness
- If any anomaly occurs, execute RUNBOOK rollback immediately.

5) Closeout
- Append evidence to docs/ops_validation_run.txt.
- Update docs/ROADMAP.md Epic 3 acceptance to completed (with date).

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
- Stop trading immediately (HALT blocks order placement).
- If continuous mode is enabled, keep the process running for monitoring/reconcile/heartbeat; ingest is paused unless isolation is required.
- Fix root cause (storage, config mismatch, position mode).
- Auto-recovery to ARMED_SAFE (reduce-only) is allowed only when HALT recovery conditions are satisfied (see docs/modules/SAFETY.md).
- Auto-recovery applies only to allowlist reason_code values (see docs/modules/SAFETY.md).
- When HALT is due to BACKFILL_WINDOW_EXCEEDED, auto-recovery requires the operator to apply maintenance skip so maintenance_skip_applied_ms is recorded; otherwise the system will remain in HALT.
- After verification, explicitly promote to ARMED_LIVE per RUNBOOK approval steps.

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
- Manually promote to ARMED_LIVE after verifying positions and open orders.
  - If you need to force promotion from ARMED_SAFE (not HALT), use:
    - PYTHONPATH=src python3 tools/ops_reset_safety.py --config config/settings.yaml --schema config/schema.json --mode ARMED_LIVE --reason-code MANUAL_PROMOTE --reason-message "Promote to ARMED_LIVE after verification" --allow-non-halt
- Note: maintenance skip only applies to gap-related HALT (reason_code=BACKFILL_WINDOW_EXCEEDED).

### Maintenance Skip Helper Script (Temporary)
`tools/start_live_with_maintenance_skip.sh` is a convenience helper added post‑MVP to speed up gap recovery.
It is not a fully hardened ops tool yet; treat it as temporary and use with care.

Intended use:
- Only when safety_mode=HALT with reason_code=BACKFILL_WINDOW_EXCEEDED.
- Operator is present and will verify positions before any promotion to ARMED_LIVE.
- Use for a single recovery event only; do not treat this as a normal startup path.

Risks/limitations:
- Uses simple text edits on the config file; YAML layout changes can break it.
- Does not write evidence by itself; you must record outputs in ops evidence.
- If the process is terminated abruptly (power loss), config restoration may not complete.

Operational requirements:
- Always run config validation + hash before/after.
- Capture evidence via tools/ops_validate_run.py and note maintenance_skip_gap toggles.
- Prefer manual promotion to ARMED_LIVE after verification.
If automation is desired later, convert this script into a Python tool with YAML parsing,
dry‑run support, and explicit evidence output.

## Long Downtime Recovery (Gap Exceeded)
Use this flow when the system has been offline long enough to exceed backfill_window_ms.
Goal: recover safely with auditable evidence and avoid silent cursor jumps.

Steps:
1. If safety_mode is HALT with BACKFILL_WINDOW_EXCEEDED, clear the HALT state first:
   - Preferred: rebuild DB if required by schema version (see docs/DATA_MODEL.md) or if cursor is stale beyond recovery.
   - Alternate: reset safety state with an auditable tool before proceeding:
     - PYTHONPATH=src python3 tools/ops_reset_safety.py --config config/settings.yaml --schema config/schema.json --mode ARMED_SAFE --reason-code MAINTENANCE_SKIP --reason-message "Maintenance skip reset"
     - Save tool output in docs/ops_validation_run.txt (or append to ops evidence).
2. Set `ingest.maintenance_skip_gap=true` in config/settings.yaml for a single controlled restart.
3. Start in dry-run mode to validate state without execution:
   - PYTHONPATH=src python3 src/hyperliquid/main.py --mode dry-run --config config/settings.yaml
4. Capture evidence:
   - PYTHONPATH=src python3 tools/ops_validate_run.py --config config/settings.yaml --schema config/schema.json --exchange-time --metrics-tail 5 --output docs/ops_validation_run.txt
5. Verify and record:
   - safety_mode=ARMED_SAFE and safety_reason_code indicates maintenance skip
   - last_processed_timestamp_ms updated to a recent value
   - metrics_tail shows current timestamps
6. Revert `ingest.maintenance_skip_gap=false` and restart in the target mode.

Evidence:
- Record the maintenance skip toggle, cursor update, and any manual checks in docs/OPS_VALIDATION.md (Go/No-Go evidence section).

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
