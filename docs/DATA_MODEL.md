# Data Model

## SQLite Tables (MVP)

### processed_txs
Stores processed upstream events for idempotency and dedup.

Columns:
- tx_hash TEXT NOT NULL
- event_index INTEGER NOT NULL
- symbol TEXT NOT NULL
- timestamp_ms INTEGER NOT NULL
- is_replay INTEGER NOT NULL DEFAULT 0
- created_at_ms INTEGER NOT NULL

Primary Key:
- (tx_hash, event_index, symbol)

Indexes:
- idx_processed_txs_created_at_ms (created_at_ms)
- idx_processed_txs_timestamp_ms (timestamp_ms)

Notes:
- TTL cleanup removes rows older than dedup_ttl_seconds.
- is_replay is a boolean stored as INTEGER (0 or 1).

### trade_history
Stores executed trades for audit and reconciliation.

Columns:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- correlation_id TEXT NOT NULL
- symbol TEXT NOT NULL
- side TEXT NOT NULL
- size REAL NOT NULL
- price REAL NOT NULL
- pnl REAL
- status TEXT NOT NULL
- exchange_order_id TEXT
- tx_hash TEXT
- created_at_ms INTEGER NOT NULL

Unique:
- correlation_id

Indexes:
- idx_trade_history_correlation_id (correlation_id)
- idx_trade_history_tx_hash (tx_hash)
- idx_trade_history_exchange_order_id (exchange_order_id)

Units and Precision:
- size: base asset quantity (exchange lot size precision)
- price: quote per base (exchange price tick precision)
- pnl: quote currency (e.g., USDT)

### system_state
Stores key/value runtime state.

Columns:
- key TEXT PRIMARY KEY
- value TEXT NOT NULL
- updated_at_ms INTEGER NOT NULL

Required Keys:
- last_processed_timestamp_ms
- last_processed_event_key (timestamp_ms|event_index|tx_hash|symbol)
- config_hash
- config_version
- contract_version
- safety_mode
- safety_reason_code
- safety_reason_message
- safety_changed_at_ms

### order_intents
Stores generated intents for deterministic recovery.

Columns:
- correlation_id TEXT PRIMARY KEY
- intent_payload TEXT NOT NULL
- created_at_ms INTEGER NOT NULL

### order_results
Stores execution results for recovery and audit.

Columns:
- correlation_id TEXT PRIMARY KEY
- exchange_order_id TEXT
- status TEXT NOT NULL
- filled_qty REAL NOT NULL
- avg_price REAL
- error_code TEXT
- error_message TEXT
- contract_version TEXT NOT NULL
- created_at_ms INTEGER NOT NULL
- updated_at_ms INTEGER NOT NULL

Indexes:
- idx_order_results_status (status)
- idx_order_results_exchange_order_id (exchange_order_id)

### audit_log
Stores state transition audit events for execution and safety.

Columns:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- timestamp_ms INTEGER NOT NULL
- category TEXT NOT NULL
- entity_id TEXT NOT NULL
- from_state TEXT
- to_state TEXT
- reason_code TEXT
- reason_message TEXT
- event_id TEXT
- metadata TEXT (JSON)

Indexes:
- idx_audit_log_category (category)
- idx_audit_log_entity_id (entity_id)
- idx_audit_log_timestamp_ms (timestamp_ms)

### baseline_snapshots
Stores operator-approved baseline snapshots for external/manual positions.

Columns:
- baseline_id TEXT PRIMARY KEY (UUID)
- created_at_ms INTEGER NOT NULL
- operator TEXT
- reason_message TEXT
- active INTEGER NOT NULL DEFAULT 1

Indexes:
- idx_baseline_snapshots_active (active, created_at_ms)

### baseline_positions
Stores per-symbol positions for a baseline snapshot.

Columns:
- baseline_id TEXT NOT NULL
- symbol TEXT NOT NULL
- qty REAL NOT NULL

Primary Key:
- (baseline_id, symbol)

Indexes:
- idx_baseline_positions_baseline_id (baseline_id)

## Correlation and Idempotency
- correlation_id must be stable and derived from PositionDeltaEvent.
- order_intents + order_results allow restart-safe recovery.

## Migrations
- MVP: manual migration scripts.
- Future: add versioned migration files and schema checks at startup.

## Retention
- processed_txs uses TTL cleanup.
- trade_history retained for audit by default.
- order_intents/order_results retained for recovery.
