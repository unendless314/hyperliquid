# Ops Validation Evidence Log

Use this template to capture minimal, replayable proof for A1–A3 runs.
Keep each run short and attach only the essential outputs.

## Run Metadata
- Date/Time (UTC):
- Operator:
- Environment (testnet/mainnet):
- Mode (dry-run / live / backfill-only):
- Config hash:
- DB path:

## A1 Preflight Evidence
- validate_config output:
- config_hash output:
- time sync output (local + exchange):
- schema_version check:

## A2 Mode-Specific Validation Evidence
- system_state (safety_*):
- system_state (last_processed_*):
- order_results count:
- audit_log count:
- metrics tail snippet:
- emit_boot_event behavior noted (yes/no, effect on order_results):

## A3 Failure Path Evidence
For each failure path, capture:
- Trigger steps used:
- Expected signal(s):
- Observed system_state:
- Observed audit_log row(s):
- Observed metrics/logs:

### SCHEMA_VERSION_MISMATCH
- Trigger steps:
- Expected:
- Observed:

### RECONCILE_CRITICAL
- Trigger steps:
- Expected:
- Observed:

### BACKFILL_WINDOW_EXCEEDED
- Trigger steps:
- Expected:
- Observed:

### EXECUTION_RETRY_BUDGET_EXCEEDED
- Trigger steps:
- Expected:
- Observed:
