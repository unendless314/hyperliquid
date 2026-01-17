# Documentation Review Notes (MVP Focus)

## Scope
This document records review observations for the initial docs draft, with a focus on MVP-critical gaps and concrete next steps.

## Priority Findings
1. DATA_MODEL is underspecified
   - Needs table schemas, primary keys, unique constraints, indexes, and data types.
   - processed_txs unique key should be explicit (e.g., tx_hash + event_index + symbol).
   - order_intents/order_results need correlation_id rules and idempotency guarantees.

2. INTEGRATIONS lacks actionable API detail
   - Specify endpoints, auth, rate limits, error handling, and time sync.
   - Add testnet details and any environment-specific constraints.

3. DEPLOYMENT is not runnable
   - Provide concrete build/deploy/verify commands.
   - Define how settings.yaml validation and config_hash are generated/verified.

## Secondary Findings
4. CONTRACTS need concrete field definitions
   - Add types, units, nullable rules, and enum ranges.
   - Define correlation_id format, uniqueness, and source mapping.

5. ARCHITECTURE state machine lacks transition rules
   - Define explicit triggers/conditions for state transitions.
   - Clarify ARMED_SAFE -> ARMED_LIVE conditions and manual overrides.

6. EXECUTION needs deterministic clientOrderId spec
   - Define exact composition and versioning strategy.
   - Ensure replay/resume behavior is explicitly allowed for order continuation.

7. SAFETY drift rules are unclear
   - Define drift calculation method, sampling cadence, and thresholds with units.
   - Record reason codes and persistence rules for safety mode changes.

8. TEST_PLAN is missing reproducible steps
   - Include test commands, inputs, and environment prerequisites (e.g., testnet creds).

9. OBSERVABILITY metrics/alerts lack definitions
   - Define calculation windows, dimensions, and thresholds for alerts.

10. RUNBOOK is a skeleton
   - Add concrete recovery checklists and decision trees for common incidents.

## MVP Alignment Suggestions
- Narrow scope to a single symbol and single account for MVP.
- Fix a single sizing strategy (e.g., proportional or fixed) to reduce branching.
- Consider running in ARMED_SAFE by default with explicit manual promotion to ARMED_LIVE.

## Recommended Next Edits (Order)
1. docs/DATA_MODEL.md
2. docs/INTEGRATIONS.md
3. docs/DEPLOYMENT.md
4. docs/CONTRACTS.md
5. docs/ARCHITECTURE.md

## Notes
These observations are intentionally MVP-focused and should prioritize correctness, safety, and reproducibility over completeness.
