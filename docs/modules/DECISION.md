# Decision / Strategy Spec

## Responsibilities
- Validate PositionDeltaEvent freshness
- Apply replay policy gates
- Apply risk checks (slippage, filters, blacklist)
- Compute sizing (fixed, proportional, kelly)
- Produce OrderIntent

## Inputs
- PositionDeltaEvent
- DecisionInputs (local state + providers)
- settings: max_stale_ms, replay_policy, filters config, sizing config

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

## DecisionInputs / Local State
Decision uses local state that is not part of PositionDeltaEvent. To avoid polluting
event contracts, the decision layer accepts a lightweight DecisionInputs/DecisionContext
object that includes local position and provider hooks.

Required fields:
- local_current_position: float (signed net position for the symbol)
- closable_qty: float (abs size available for reduce-only)
- safety_mode: str (ARMED_SAFE/HALT/NORMAL)

Provider hooks (for testability):
- now_ms_provider: Callable[[], int] for freshness checks
- price_provider: Callable[[str], PriceSnapshot] for mark/mid price + timestamp
- filters_provider: Callable[[str], SymbolFilters | None] for exchange filters

## Price Source / Fallback
- Primary price source for slippage checks is the execution adapter mark/mid price.
- If adapter price is unavailable, fallback to ingest price is allowed only if enabled in config.
- Fallback prices must pass a stricter staleness threshold and must attach a risk_note.

## Freshness Guard
- Events are rejected if timestamp is older than max_stale_ms or ahead of now_ms by more than max_future_ms.

## Filters
- Decision uses a common filter model (min_qty, step_size, min_notional, tick_size).
- Adapters map exchange-specific filters into the common model.
- Decision validates intents against the common filters before sizing output is accepted.
