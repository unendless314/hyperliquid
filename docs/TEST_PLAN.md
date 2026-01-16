# Test Plan

## Minimal Test Set (MVP Priority)

### 1) Gap and Backfill
Goal: validate backfill + dedup + cursor advancement.

Steps:
1. Start system in backfill-only mode.
2. Trigger a WS disconnect:
   - Option A: temporarily disable network for the process
   - Option B: use a test flag to close WS connection
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
- No duplicate OrderIntent generated.

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

## Unit Tests
- tests/unit/test_config_validation.py (TODO)
- tests/unit/test_sizing_logic.py (TODO)
- tests/unit/test_dedup_logic.py (TODO)

## Integration Tests
- tests/integration/test_binance_submit_cancel.py (TODO)
- tests/integration/test_ws_backfill.py (TODO)

## Chaos Tests
- tests/chaos/test_network_errors.py (TODO)
- tests/chaos/test_rate_limit_429.py (TODO)

## Environment Prerequisites (MVP)
- Binance testnet API key and secret
- Hyperliquid target wallet address
- config/settings.yaml configured for testnet
- sqlite3 installed locally

## Suggested Commands (MVP)
- Live (testnet): python src/hyperliquid/main.py --mode live --config config/settings.yaml
- Dry-run: python src/hyperliquid/main.py --mode dry-run --config config/settings.yaml
- Backfill-only: python src/hyperliquid/main.py --mode backfill-only --config config/settings.yaml

