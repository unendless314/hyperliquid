# Ingest / Monitor Spec

## Responsibilities
- Maintain Hyperliquid WS connection
- Detect gaps and perform REST backfill
- Deduplicate events (tx_hash + event_index + symbol)
- Track target wallet net position
- Emit PositionDeltaEvent

## Inputs
- Hyperliquid user fills (WS + REST)
- settings: cursor_mode, backfill_window, cursor_overlap_ms, replay_policy

## Outputs
- PositionDeltaEvent to Decision queue
- Updated cursor in Storage

## Key Rules
- If gap > backfill_window: enter HALT
- Cursor moves only after event is persisted
- Backfill uses overlap window; rely on dedup
- Poison messages are isolated and skipped

## Replay Policy and Scope
- Replay refers only to backfilled events from Ingest (WS gap -> REST backfill).
- All backfill events are marked is_replay=true.
- Replay policy is enforced in the Decision layer and only applies to event-driven actions.

## Failure Handling
- WS reconnect with backoff
- Backfill failure -> alert + ARMED_SAFE or HALT depending on severity
- Parsing failure -> isolate and continue
