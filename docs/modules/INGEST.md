# Ingest / Monitor Spec

## Responsibilities
- Maintain Hyperliquid WS connection
- Detect gaps and perform REST backfill
- Deduplicate events (tx_hash + event_index + symbol)
- Track target wallet net position
- Emit PositionDeltaEvent
- Populate expected_price when available (optional; used for decision slippage)

## Adapter Status (MVP)
- REST backfill and polling are wired for live mode (polling uses userFillsByTime to avoid 2000-row limits).
- WebSocket streaming is wired when ws_url is configured; REST polling is the fallback if WS is stale or unavailable.

## Inputs
- Hyperliquid user fills (WS + REST)
- settings: cursor_mode, backfill_window, cursor_overlap_ms, replay_policy

## Configuration Notes
- ingest.backfill_window_ms and ingest.cursor_overlap_ms control backfill gap handling.
- ingest.hyperliquid.* configures the adapter (enabled, mode, endpoints, rate limit, retry).
- ingest.hyperliquid.symbol_map maps Hyperliquid coin symbols to execution symbols (e.g., BTC -> BTCUSDT).
- Unmapped coins (or spot-style @ symbols) are skipped with a warning to avoid trading the wrong market.
- Coins not listed in symbol_map are not tracked for performance and will never generate orders.
- Stub events can be injected via ingest.hyperliquid.stub_events for local runs without live APIs.

## Outputs
- PositionDeltaEvent to Decision queue
- Updated cursor in Storage

## Key Rules
- If ingest success gap > backfill_window: enter HALT
- Event-time gap > backfill_window emits warning only (no HALT)
- In HALT, stop ingesting and do not advance cursor until manual action clears the gap
- Cursor moves only after event is persisted
- Backfill uses overlap window; rely on dedup
- Poison messages are isolated and skipped

## Health Signals
- last_ingest_success_ms: updated on successful ingest poll/backfill (REST/WS returns a response, even if 0 events). Used for HALT gap checks.
- last_processed_timestamp_ms: updated only when events are ingested. Used as the cursor and for event-time gap warnings.

## Replay Policy and Scope
- Replay refers only to backfilled events from Ingest (WS gap -> REST backfill).
- All backfill events are marked is_replay=true.
- Replay policy is enforced in the Decision layer and only applies to event-driven actions.

## Failure Handling
- WS reconnect with backoff
- Backfill failure -> alert + ARMED_SAFE or HALT depending on severity
- Parsing failure -> isolate and continue

## Maintenance Restart
- For planned downtime, use an explicit maintenance flag (config: ingest.maintenance_skip_gap=true) to skip gap enforcement on restart.
- When maintenance skip is used:
  - Set cursor to now and record maintenance_skip_applied_ms (evidence only).
  - safety_mode remains HALT until auto-recovery or manual unhalt.
  - After unhalt, trading resumes in ARMED_SAFE (reduce-only), then manual promotion to ARMED_LIVE is required.
- This flow transfers gap reconciliation risk to the operator and does not guarantee backfill consistency.
- Maintenance skip only applies to gap-related HALT (reason_code=BACKFILL_WINDOW_EXCEEDED); other HALT reasons must not be bypassed.
