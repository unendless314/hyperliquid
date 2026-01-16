# State / Storage Spec

## Responsibilities
- SQLite as SSOT
- Persist cursor, system_state, processed_txs, order history
- Provide queries for reconciliation and recovery

## Tables (Draft)
- processed_txs: tx_hash, event_index, symbol, timestamp
- trade_history: correlation_id, symbol, side, size, price, status, tx_hash
- system_state: key, value
- order_intents: correlation_id, intent_payload
- order_results: correlation_id, status, filled_qty, avg_price

## Recovery Guarantees
- Cursor advances only after successful persistence.
- Dedup table ensures at-least-once ingestion without duplicate execution.
- Order intents and results are persisted to allow restart recovery.

## Key Rules
- Enable WAL and busy_timeout
- One thread, one connection
- TTL cleanup for processed_txs
- Backups and restore verification
