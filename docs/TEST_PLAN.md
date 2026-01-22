# Test Plan

## Minimal Test Set (MVP Priority)

### 1) Gap and Backfill
Goal: validate backfill + dedup + cursor advancement.

Steps:
1. Start system in live or dry-run mode (WS enabled).
2. Trigger a WS disconnect:
   - Option A: temporarily disable network for the process
   - Option B: use mock/patch or a controlled WS proxy to close the connection
3. Restore network and allow REST backfill to run.

Checks (copy/paste):
- sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
- sqlite3 <db_path> "select count(*) from processed_txs;"
- sqlite3 <db_path> "select count(*) from processed_txs where is_replay=1;"
- tail -n 50 <metrics_log_path> | grep "dedup_drop_count"

Notes:
- <db_path> and <metrics_log_path> come from config/settings.yaml.

Expected:
- Cursor advances only after persistence.
- Dedup drops overlap events (dedup_drop_count increases).
- No duplicate correlation_id in order_intents (if order_intents are generated).

### 2) Restart Recovery
Goal: ensure restart is idempotent.

Steps:
1. Run system in dry-run mode.
2. Stop process mid-stream.
3. Restart and verify cursor resumes from last_processed_event_key.

Checks (copy/paste):
- sqlite3 <db_path> "select key, value from system_state where key='last_processed_event_key';"
- sqlite3 <db_path> "select correlation_id, count(*) from order_intents group by correlation_id having count(*) > 1;"

Notes:
- <db_path> comes from config/settings.yaml.

Expected:
- No duplicated order_intents.
- order_intents and order_results remain consistent after restart.

### 3) Partial Fill Handling
Goal: confirm partial fills do not block future increase.

Steps:
1. Submit a limit order with price slightly away from mark and qty large enough to partially fill.
2. Ensure qty/price satisfy min_qty and min_notional to avoid filter rejection.
3. Observe PARTIALLY_FILLED status.
4. Trigger a subsequent INCREASE intent.

Checks (copy/paste):
- sqlite3 <db_path> "select correlation_id, status, filled_qty from order_results order by updated_at_ms desc limit 5;"
- tail -n 50 <metrics_log_path> | grep "order_success_rate"

Notes:
- <db_path> and <metrics_log_path> come from config/settings.yaml.

Expected:
- Position updates match filled_qty.
- No automatic downgrade to ARMED_SAFE.
- Subsequent INCREASE intents are allowed.

### 4) A2 Live Testnet Validation (Small-Order)
Goal: validate live testnet flow with explicit, repeatable thresholds.

Parameters (record in evidence log before running):
- min_notional: <exchange_min_notional>
- slippage_cap_pct: <config_slippage_cap_pct>
- allowed_fill_deviation_pct: <manual_threshold_max_fill_deviation_pct>

Steps:
1. Start in live mode on testnet.
2. Place a single small order at or above min_notional.
3. Confirm order_result status and filled_qty.
4. Verify reconcile is non-stale and safety_mode can reach ARMED_LIVE (if enabled).

Checks (copy/paste):
- sqlite3 <db_path> "select key, value from system_state where key='safety_mode';"
- sqlite3 <db_path> "select status, filled_qty, error_code from order_results order by updated_at_ms desc limit 3;"
- tail -n 50 <metrics_log_path> | grep "reconcile"

Expected:
- Order status is FILLED or PARTIALLY_FILLED within allowed_fill_deviation_pct.
- No slippage violation beyond slippage_cap_pct.
- safety_mode is ARMED_SAFE or ARMED_LIVE (per config) and not HALT.

## Unit Tests
- tests/unit/test_config_validation.py (TODO)
- tests/unit/test_sizing_logic.py (TODO)
- tests/unit/test_dedup_logic.py (TODO)
- tests/unit/test_backfill_overlap.py (TODO)
- tests/unit/test_cursor_dedup_persistence.py (TODO)
- tests/unit/test_unknown_recovery.py (TODO)
- tests/unit/test_safety_promotion_conditions.py (TODO)
- tests/unit/test_hook_signatures.py
- tests/unit/test_ops_validate_run.py

## Integration Tests
- tests/integration/test_binance_submit_cancel.py (rate limit, timeout, duplicate handling)
- tests/integration/test_ws_backfill.py (reconcile path: missing symbol -> HALT)
- tests/integration/test_ws_reconnect.py (disconnect + resume + backfill overlap) (TODO)
- tests/integration/test_ws_reconnect_backfill.py
- tests/integration/test_ingest_pipeline_dedup.py
- tests/integration/test_execution_retry_budget.py
- tests/integration/test_safety_mode_gating.py
- tests/integration/test_partial_fill_handling.py
- tests/integration/test_reconcile_snapshot_stale.py
- tests/integration/test_reconcile_drift_thresholds.py

### Key Integration Set (2026-01-22)
Status: pass (10 tests)
Included:
- tests/integration/test_ws_reconnect_backfill.py
- tests/integration/test_ingest_pipeline_dedup.py
- tests/integration/test_execution_retry_budget.py
- tests/integration/test_safety_mode_gating.py
- tests/integration/test_partial_fill_handling.py
- tests/integration/test_reconcile_snapshot_stale.py
- tests/integration/test_reconcile_drift_thresholds.py

## Chaos Tests
- tests/chaos/test_network_errors.py (TODO)
- tests/chaos/test_rate_limit_429.py (TODO)
- tests/chaos/test_partial_fills.py (TODO)
- tests/chaos/test_delayed_reports.py (TODO)

## Failure Taxonomy (for Chaos/Backfill)
Use these categories to decide coverage and expected recovery behavior:
- network interruption (WS disconnect, REST timeout)
- duplicate events (replay / backfill overlap)
- partial fills (position drift vs expected)
- delayed reports (late fills / stale snapshots)
- price dislocation (sudden mark/reference gaps)
- unknown order state (query failures, retry budget)

## Ops Validation
Reference: docs/RUNBOOK.md (use the scripted preflight/post-start commands).
Evidence log template: docs/OPS_VALIDATION.md

Checklist:
- Validate config + schema + config_hash.
- Confirm time sync offset captured (local time vs exchange time).
- Run mode-specific checks:
  - dry-run: no external order placement (adapter disabled); order_results may be written.
  - live: safety_mode != HALT after startup.
  - backfill-only: cursor advances; no external order placement (adapter disabled); order_results may be written.
- Trigger failure paths and verify expected system_state/log outcomes:
  - SCHEMA_VERSION_MISMATCH
  - EXECUTION_RETRY_BUDGET_EXCEEDED
  - RECONCILE_CRITICAL
  - BACKFILL_WINDOW_EXCEEDED
- After recovery, confirm audit_log and safety_reason_code remain accurate.

## Environment Prerequisites (MVP)
- Binance testnet API key and secret
- Hyperliquid target wallet address (via HYPERLIQUID_TARGET_WALLET env)
- config/settings.yaml configured for testnet
- sqlite3 installed locally

## Suggested Commands (MVP)
- Live (testnet): python src/hyperliquid/main.py --mode live --config config/settings.yaml
- Dry-run: python src/hyperliquid/main.py --mode dry-run --config config/settings.yaml
- Backfill-only: python src/hyperliquid/main.py --mode backfill-only --config config/settings.yaml
- Unit (single test file): PYTHONPATH=src python3 -m pytest tests/unit/test_decision_flip.py
- Unit (pipeline test): PYTHONPATH=src python3 -m pytest tests/unit/test_pipeline.py
- Unit (db persistence test): PYTHONPATH=src python3 -m pytest tests/unit/test_db_persistence.py
- Unit (dedup/cursor test): PYTHONPATH=src python3 -m pytest tests/unit/test_dedup_logic.py
- Unit (cursor order test): PYTHONPATH=src python3 -m pytest tests/unit/test_ingest_cursor_order.py
- Unit (ingest+pipeline test): PYTHONPATH=src python3 -m pytest tests/unit/test_ingest_pipeline_integration.py
- Unit (processed_txs TTL cleanup): PYTHONPATH=src python3 -m pytest tests/unit/test_processed_txs_ttl.py
- Unit (replay policy): PYTHONPATH=src python3 -m pytest tests/unit/test_replay_policy.py
