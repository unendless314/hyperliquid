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

## Configuration Notes
- execution.binance.* configures the exchange adapter (enabled, mode, endpoints, rate limit, retry).

## Outputs
- OrderResult
- Updates to Storage (orders, fills, status)

## Key Rules
- clientOrderId must be deterministic per event
- Partial fills must be persisted
- Unknown status is resolved via Reconciliation

## Idempotency and clientOrderId
- Format: hl-{tx_hash}-{event_index}-{symbol}-{nonce}
- symbol must be normalized (replace '-' with '_')
- Nonce is generated once on first submission and persisted in DB
- On retry or reconnect, reuse the same clientOrderId
- If exchange returns duplicate, treat as success and query status
- clientOrderId must comply with Binance constraints (length/charset); validate and trim if needed.

## FSM States
PENDING -> SUBMITTED -> PARTIALLY_FILLED -> FILLED | CANCELED | EXPIRED | REJECTED | UNKNOWN

## TIF and Fallback
- Limit orders wait up to tif_seconds
- On timeout: cancel and confirm cancellation
- If market_fallback_enabled, submit IOC/market for remaining qty only
- Fallback uses a new clientOrderId (new nonce)
- Fallback must pass slippage and min_notional checks

## Error Handling
- 429: shared backoff; suspend submit + polling
- Network errors: mark UNKNOWN and handoff to reconciliation
- Insufficient balance: mark REJECTED with error_code
- Rejected orders: record error_code and error_message
- Unknown status: record retry_count and use backoff before next poll

## Partial Fill Policy
- PARTIALLY_FILLED is a normal state and does not by itself restrict future orders.
- Persist filled_qty and avg_price to keep local position accurate.
- Safety mode changes are triggered by reconciliation drift or hard risk failures, not by partial fills alone.

## Replay vs Order Continuation
- Replay policy applies only to backfilled events from Ingest.
- Retrying or continuing an order (e.g., partial fills, unknown status, idempotent resend)
  is not considered replay and must remain allowed.
