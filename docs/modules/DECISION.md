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

## Sizing Notes
- Use delta sizing for PositionDeltaEvent
- Clamp to available balance and max add-on rules
