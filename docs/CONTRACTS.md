# Cross-Module Contracts

## PositionDeltaEvent
Standardized input produced by Ingest and consumed by Decision.

Required fields:
- symbol: TEXT (e.g., BTCUSDT)
- timestamp_ms: INTEGER (UTC epoch milliseconds)
- tx_hash: TEXT
- event_index: INTEGER
- is_replay: INTEGER (0 or 1)
- prev_target_net_position: REAL (base asset qty, one-way)
- next_target_net_position: REAL (base asset qty, one-way)
- delta_target_net_position: REAL (next - prev)
- action_type: TEXT enum {INCREASE, DECREASE, FLIP}
- open_component: REAL (base asset qty; required only for FLIP; nullable otherwise)
- close_component: REAL (base asset qty; required only for FLIP; nullable otherwise)

Optional fields:
- expected_price: REAL (event-time expected execution price from ingest/leader)
- expected_price_timestamp_ms: INTEGER (UTC epoch milliseconds; defaults to event timestamp)

Rules:
- action_type is derived from prev/next net position
- FLIP must split into open_component and close_component
- is_replay is true for backfill events
- Event ordering uses (timestamp_ms, event_index, tx_hash, symbol)
- For partial closes, target_close_ratio = abs(delta) / abs(prev_target_net_position)
  - If prev_target_net_position == 0, target_close_ratio = 0
  - Clamp target_close_ratio to [0, 1]

## OrderIntent
Produced by Decision and consumed by Execution.

Required fields:
- correlation_id: TEXT (unique, stable per PositionDeltaEvent)
- strategy_version: TEXT (non-empty, from decision.strategy_version)
- symbol: TEXT
- side: TEXT enum {BUY, SELL}
- order_type: TEXT enum {LIMIT, MARKET}
- qty: REAL (base asset quantity; must be > 0)
- price: REAL (required for LIMIT; nullable for MARKET)
- reduce_only: INTEGER (0 or 1)
- time_in_force: TEXT (e.g., GTC, IOC)
- is_replay: INTEGER (0 or 1)
- risk_notes: TEXT (optional)

Rules:
- reduce_only must be true for DECREASE and close_component
- correlation_id must map back to PositionDeltaEvent
- strategy_version must be present and supported by the decision engine
- If order_type is MARKET, price may be null

## OrderResult
Produced by Execution and persisted by Storage.

Required fields:
- correlation_id: TEXT
- exchange_order_id: TEXT (nullable if order was rejected before submission)
- status: TEXT enum {PENDING, SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN}
- filled_qty: REAL (base asset quantity)
- avg_price: REAL (quote per base; nullable)
- error_code: TEXT (nullable)
- error_message: TEXT (nullable)

Rules:
- PARTIALLY_FILLED is a normal state; it must not by itself trigger a safety downgrade.
- Safety mode changes are driven by reconciliation drift or hard risk failures.
- Replay policy applies only to backfilled events (PositionDeltaEvent.is_replay).

## Correlation ID
- Format: hl-{tx_hash}-{event_index}-{symbol}[-{suffix}]
- symbol must not contain '-' (hyphen). If it does, replace with '_'.
- Must be unique and deterministic per PositionDeltaEvent
- For FLIP intents, append a suffix: "-close" for reduce-only close, "-open" for new exposure.
- Used across OrderIntent and OrderResult for traceability

## Safety Modes
- ARMED_LIVE: full operation
- ARMED_SAFE: no exposure increase; allow reduce-only if configured
- HALT: stop processing new events and orders

## Contract Versioning
- contract_version format: MAJOR.MINOR (e.g., 1.0)
- Compatibility rule: producer major must equal consumer major; producer minor must be <= consumer minor.
- On mismatch, the consumer must fail fast and enter HALT (reason: CONTRACT_VERSION_MISMATCH).
- Version policy is implemented in src/hyperliquid/common/models.py.

## Operator Policy Note
- This deployment opts to continue on config hash changes while recording a safety_reason_code of CONFIG_HASH_CHANGED.
- This is an operator choice for single-user deployments; stricter environments should HALT on config changes.
