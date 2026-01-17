# Decision / Strategy Spec

## Responsibilities
- Validate PositionDeltaEvent freshness
- Apply replay policy gates
- Apply risk checks (slippage, filters, blacklist)
- Compute sizing (fixed, proportional, kelly)
- Produce OrderIntent

## Inputs
- PositionDeltaEvent
- settings: max_stale_ms, replay_policy, binance_filters, sizing config

## Outputs
- OrderIntent
- Risk rejection logs

## Decision Order (Strict)
1. Event validation (schema, freshness)
2. Replay policy gate
3. Hard risk checks (slippage, filters, position mode, stale data)
4. Sizing (fixed / proportional / kelly)
5. Build OrderIntent

## Key Rules
- DECREASE and close_component must be reduce-only
- If closable_qty == 0: skip with warning (no reverse open)
- Replay policy defaults to close-only (no exposure increase)
- Use mark price or mid for slippage checks

## Partial Fill Policy
- Partial fills are treated as normal market behavior.
- Partial fills do not block or downgrade future INCREASE intents.
- The decision layer only blocks exposure increase when the system is in ARMED_SAFE or HALT.

## Safety Gate Conditions
Exposure-increasing intents are blocked only when:
- Safety mode is ARMED_SAFE or HALT
- Hard risk checks fail (slippage, filters, position mode, stale data)
- Replay policy forbids increase (backfill events)

## Replay Policy (MVP)
- Default replay policy is close-only: for is_replay=1, only reduce-only intents are allowed.
- Replay policy is enforced after safety gating.

## Sizing Notes
- Use delta sizing for PositionDeltaEvent.
- Open/increase sizing supports fixed amount, proportional, or Kelly.
- Close/decrease sizing uses proportional close by target ratio:
  - If prev_target_net_position == 0: target_close_ratio = 0
  - target_close_ratio = min(1, abs(delta_target_net_position) / abs(prev_target_net_position))
  - local_close_qty = abs(local_current_position) * target_close_ratio
  - Cap by closable_qty and apply reduce-only

## Closable Quantity
- closable_qty is the local position size available for reduce-only orders.
- If closable_qty == 0, skip the close intent with a warning.
