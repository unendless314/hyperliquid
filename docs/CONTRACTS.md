# Cross-Module Contracts

## PositionDeltaEvent
Standardized input produced by Ingest and consumed by Decision.

Required fields:
- symbol
- timestamp_ms
- tx_hash
- event_index
- is_replay
- prev_target_net_position
- next_target_net_position
- delta_target_net_position
- action_type: INCREASE | DECREASE | FLIP
- open_component (for FLIP)
- close_component (for FLIP)

Rules:
- action_type is derived from prev/next net position
- FLIP must split into open_component and close_component
- is_replay is true for backfill events
- Event ordering uses (timestamp_ms, event_index, tx_hash, symbol)

## OrderIntent
Produced by Decision and consumed by Execution.

Required fields:
- correlation_id
- symbol
- side
- order_type: LIMIT | MARKET
- qty
- price (optional for MARKET)
- reduce_only
- time_in_force
- is_replay
- risk_notes (optional)

Rules:
- reduce_only must be true for DECREASE and close_component
- correlation_id must map back to PositionDeltaEvent

## OrderResult
Produced by Execution and persisted by Storage.

Required fields:
- correlation_id
- exchange_order_id
- status: PENDING | SUBMITTED | PARTIALLY_FILLED | FILLED | CANCELED | EXPIRED | REJECTED | UNKNOWN
- filled_qty
- avg_price
- error_code (optional)
- error_message (optional)

Rules:
- PARTIALLY_FILLED is a normal state; it must not by itself trigger a safety downgrade.
- Safety mode changes are driven by reconciliation drift or hard risk failures.
- Replay policy applies only to backfilled events (PositionDeltaEvent.is_replay).

## Safety Modes
- ARMED_LIVE: full operation
- ARMED_SAFE: no exposure increase; allow reduce-only if configured
- HALT: stop processing new events and orders
