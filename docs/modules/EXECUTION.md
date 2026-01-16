# Execution Spec

## Responsibilities
- Submit orders to Binance
- Maintain order FSM
- Retry with exponential backoff
- Apply TIF and market fallback
- Persist idempotency mapping

## Inputs
- OrderIntent
- settings: tif_seconds, order_poll_interval_sec, market_fallback_enabled

## Outputs
- OrderResult
- Updates to Storage (orders, fills, status)

## Key Rules
- clientOrderId must be deterministic per event
- Partial fills must be persisted
- Unknown status is resolved via Reconciliation

## FSM States
PENDING -> SUBMITTED -> PARTIALLY_FILLED -> FILLED | CANCELED | EXPIRED | REJECTED | UNKNOWN

## Partial Fill Policy
- PARTIALLY_FILLED is a normal state and does not by itself restrict future orders.
- Persist filled_qty and avg_price to keep local position accurate.
- Safety mode changes are triggered by reconciliation drift or hard risk failures, not by partial fills alone.

## Replay vs Order Continuation
- Replay policy applies only to backfilled events from Ingest.
- Retrying or continuing an order (e.g., partial fills, unknown status, idempotent resend)
  is not considered replay and must remain allowed.
