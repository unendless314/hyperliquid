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
- safety_mode: str (ARMED_SAFE/HALT/NORMAL)

Optional fields (injected by pipeline):
- local_current_position: float (signed net position for the symbol)
- closable_qty: float (abs size available for reduce-only)
- expected_price: PriceSnapshot (expected execution price from ingest/leader)

Missing behavior:
- For DECREASE/FLIP-close sizing, missing local_current_position or closable_qty must reject the event.
- For INCREASE sizing, missing local_current_position is allowed (treated as 0).

Provider hooks (for testability):
- now_ms_provider: Callable[[], int] for freshness checks
- price_provider: Callable[[str], PriceSnapshot] for mark/mid price + timestamp (reference)
- filters_provider: Callable[[str], SymbolFilters | None] for exchange filters

## Price Source / Fallback
- Primary price source for slippage checks is the execution adapter mark/mid price.
- If adapter price is unavailable, fallback to ingest price is allowed only if enabled in config.
- Fallback prices must pass a stricter staleness threshold and must attach a risk_note.

## Slippage (Market Orders Included)
Slippage compares an expected price to a reference price. Market orders MUST still
perform slippage checks when both prices are available.

Definitions:
- expected_price: price observed by ingest/leader/strategy (event-time expectation).
- reference_price: execution adapter mark/mid price.

Current default:
- expected_price is sourced from ingest/leader (DecisionInputs).
- reference_price is sourced from execution adapter (price_provider).
- price_source=ingest should remain off unless an ingest reference provider is implemented.

Computation:
- slippage = abs(reference_price - expected_price) / expected_price

Rules:
- If slippage_cap_pct <= 0, skip slippage checks.
- If either price is missing:
  - price_failure_policy = reject -> reject with missing_reference_price/stale_price.
  - price_failure_policy = allow_without_price -> allow and attach a risk_note.
- If slippage > slippage_cap_pct, reject with slippage_exceeded.

## Freshness Guard
- Events are rejected if timestamp is older than max_stale_ms or ahead of now_ms by more than max_future_ms.

## PriceSnapshot
- PriceSnapshot includes price, timestamp_ms, and source fields.
- price_max_stale_ms applies to the primary price source; price_fallback_max_stale_ms applies to fallback.
- expected_price_max_stale_ms applies to expected_price used in slippage checks.

## Failure Behavior
- If price or filters are unavailable, behavior is controlled by decision config:
  - price_failure_policy: reject | allow_without_price
  - filters_failure_policy: reject | allow_without_filters
- When allowing without price/filters, a risk_note is attached for observability.
- price_source controls which provider is primary; if the selected provider is unavailable,
  fallback applies only when price_fallback_enabled is true.

## Risk Reason Codes
Examples (non-exhaustive): stale_event, future_event, stale_price, missing_reference_price,
missing_expected_price, stale_expected_price, filters_unavailable, filter_min_qty,
filter_step_size, filter_tick_size, filter_min_notional, slippage_exceeded, sizing_invalid,
kelly_params_missing.

## Filters
- Decision uses a common filter model (min_qty, step_size, min_notional, tick_size).
- Adapters map exchange-specific filters into the common model.
- Decision validates intents against the common filters before sizing output is accepted.
- No rounding is performed: if qty/price is not a clean multiple of step_size/tick_size,
  the intent is rejected.
