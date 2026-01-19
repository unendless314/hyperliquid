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
- execution.tif_seconds controls how long limit orders wait before cancel.
- execution.order_poll_interval_sec controls order status polling cadence.
- execution.retry_budget_max_attempts limits UNKNOWN recovery attempts per order.
- execution.retry_budget_window_sec bounds total UNKNOWN recovery time window.
- execution.unknown_poll_interval_sec controls UNKNOWN recovery polling cadence.
- execution.retry_budget_mode sets safety transition on retry budget exhaustion (ARMED_SAFE or HALT).
- execution.market_fallback_enabled controls whether to submit a market fallback after TIF.
- execution.market_fallback_threshold_pct limits fallback to small remaining qty (ratio).
- execution.market_slippage_cap_pct caps mark/limit slippage allowed before fallback.

## Outputs
- OrderResult
- Updates to Storage (orders, fills, status)

## Key Rules
- clientOrderId must be deterministic per event
- Partial fills must be persisted
- Unknown status is resolved via Reconciliation
- Order results persist contract_version for recovery verification.

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
- Fallback triggers only after the limit order is confirmed CANCELED/EXPIRED and remaining
  quantity is below market_fallback_threshold_pct.
- Fallback runs through the same safety pre-hooks as normal execution.
- Fallback results merge filled_qty and avg_price with the original limit order.

## Error Handling
- 429: shared backoff; suspend submit + polling
- Network errors: mark UNKNOWN and handoff to reconciliation
- Insufficient balance: mark REJECTED with error_code
- Rejected orders: record error_code and error_message
- Unknown status: record retry_count and use backoff before next poll
- Recovery short-circuits (existing SUBMITTED/UNKNOWN/FILLED) do not invoke post-execution hooks.

## UNKNOWN Recovery Policy
- UNKNOWN means the exchange status could not be confirmed.
- UNKNOWN orders are actively recovered by querying the exchange within a retry budget.
- Historical UNKNOWNs (loaded from persistence) are also recovered on execution.
- Retry budget is defined by max attempts and a time window; on exhaustion, safety transitions
  to execution.retry_budget_mode with reason_code EXECUTION_RETRY_BUDGET_EXCEEDED.

## Partial Fill Policy
- PARTIALLY_FILLED is a normal state and does not by itself restrict future orders.
- Persist filled_qty and avg_price to keep local position accurate.
- Safety mode changes are triggered by reconciliation drift or hard risk failures, not by partial fills alone.

## Replay vs Order Continuation
- Replay policy applies only to backfilled events from Ingest.
- Retrying or continuing an order (e.g., partial fills, unknown status, idempotent resend)
  is not considered replay and must remain allowed.
