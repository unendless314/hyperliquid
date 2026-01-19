# Runbook

## Startup

Prerequisites:
- config/settings.yaml validated
- config_hash computed and recorded
- API keys available for selected environment
- Time sync offset computed

Steps:
1. Validate config:
   - python tools/validate_config.py --config config/settings.yaml --schema config/schema.json
2. Compute config_hash:
   - python tools/hash_config.py --config config/settings.yaml
3. Start service (environment is selected by config/settings.yaml):
   - python src/hyperliquid/main.py --mode live --config config/settings.yaml

Verification:
- sqlite3 <db_path> "select key, value from system_state where key like 'safety_%';"
- sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
- tail -n 50 <metrics_log_path>

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

### 3) Repeated Order Failures
Checklist:
- Inspect error_code and error_message in order_results
- Check rate limit logs and backoff state
- Verify API keys and permissions
- Check exchange status

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

## Maintenance

### Backups
- Daily SQLite backup
- Backup path uses db_path from settings.yaml
- Suggested filename pattern: backup-YYYYMMDD-HHMM.db
- Verify restore by reading system_state

### Schema Updates
- Apply migration scripts manually during MVP
- Verify schema version and system_state
- DB_SCHEMA_VERSION=2 adds order_results.contract_version (TEXT NOT NULL).
  - For existing DBs: `ALTER TABLE order_results ADD COLUMN contract_version TEXT NOT NULL DEFAULT '1.0';`
  - Update system_state.schema_version to "2" after migration.
