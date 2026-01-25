# Safety / Reconciliation Spec

## Responsibilities
- Startup reconciliation
- Periodic drift checks between DB and exchange
- Enter ARMED_SAFE or HALT on critical mismatch

## Inputs
- Exchange positions
- DB positions
- settings: warn_threshold, critical_threshold, startup_policy, reconcile_interval_sec, snapshot_max_stale_ms

## Outputs
- Safety mode transitions
- Alerts

## Reconciliation Result (MVP)
- compute drift per symbol and return a reconciliation result with:
  - mode (ARMED_LIVE/ARMED_SAFE/HALT)
  - reason_code and reason_message
  - max drift and per-symbol drifts

## Drift Calculation
- Drift is computed per symbol as absolute position difference.
- Thresholds are evaluated per symbol (not a cross-symbol sum).
- If a total drift metric is used later, symbols must not offset each other.
- Reconciliation uses net position per symbol with normalized symbols (replace '-' with '_').
- Local positions are derived from order_intents + order_results (filled_qty with side sign).

## Cadence
- Startup reconciliation runs once at boot.
- Periodic reconciliation runs every reconcile_interval_sec.

## Key Rules
- Do not auto-increase exposure when fixing drift
- Allow reduce-only during ARMED_SAFE if enabled
- If exchange snapshot is stale, enter ARMED_SAFE with reason_code=SNAPSHOT_STALE.
- If either side is missing a symbol present on the other side, enter HALT with reason_code=RECONCILE_CRITICAL.

## Runtime Safety Modes (Continuous Operation)
- HALT: keep the process running for monitoring/reconcile/ingest, but block all trading.
- ARMED_SAFE: allow reduce-only intents; block exposure increases.
- ARMED_LIVE: normal trading behavior.

## Recovery Intent (MVP)
- Transitions to safer modes (ARMED_SAFE/HALT) can happen automatically via reconciliation.
- HALT -> ARMED_SAFE is allowed automatically, but only for reduce-only trading and only when recovery conditions are met.
- ARMED_SAFE -> ARMED_LIVE requires explicit operator action and evidence.

## HALT Auto-Recovery to ARMED_SAFE (Reduce-Only)
Auto-recovery is permitted only when all of the following conditions are satisfied:
- Reconcile results are non-critical for N consecutive runs (default N=3 until configurable).
- Snapshot is not stale (snapshot_max_stale_ms satisfied).
- Backfill window gap is not exceeded (or maintenance skip is explicitly applied with evidence).
- Execution adapter is healthy and responding (see definition below).
- HALT reason_code is in the allowlist (see below).

### Execution Adapter Healthy (Definition)
Treat the adapter as healthy when:
- The most recent adapter call succeeded within the last 60 seconds, and
- No adapter exception has been recorded in the last 60 seconds.
Success means a confirmed adapter response from either:
- an order lifecycle call (submit/cancel/query), or
- a position/price query (fetch_positions / fetch_mark_price).

### HALT Auto-Recovery Allowlist (Reason Codes)
Auto-recovery to ARMED_SAFE is only allowed for these reason codes:
- SNAPSHOT_STALE
- BACKFILL_WINDOW_EXCEEDED (only when maintenance skip has been explicitly applied with evidence)
- RECONCILE_CRITICAL (only after N consecutive non-critical reconciliations)

Auto-recovery is NOT allowed for:
- EXECUTION_ADAPTER_NOT_IMPLEMENTED
- SCHEMA_VERSION_MISMATCH
- CONTRACT_VERSION_MISMATCH
- STORAGE_UNAVAILABLE
- CONFIG_HASH_MISMATCH / CONFIG_HASH_CHANGED

When auto-recovery triggers:
- Record the transition with reason_code=HALT_RECOVERY_AUTO (or equivalent) and evidence.
- Trading remains reduce-only until operator promotes to ARMED_LIVE.

## Safety Mode Visibility
- Every transition into ARMED_SAFE or HALT must record:
  - reason code (enum)
  - human-readable message
  - timestamp
- The latest safety status is persisted in system_state for diagnostics.
- Alerts must include the reason code and timestamp.

## Reason Codes (MVP)
- BACKFILL_WINDOW_EXCEEDED: gap larger than backfill_window
- SNAPSHOT_STALE: snapshot age exceeds snapshot_max_stale_ms
- RECONCILE_CRITICAL: drift exceeds critical_threshold
- POSITION_MODE_INVALID: exchange is not in one-way mode
- STORAGE_UNAVAILABLE: DB unavailable or corrupted
- CONFIG_HASH_MISMATCH: config_hash differs from recorded value
- CONFIG_HASH_CHANGED: config_hash changed but allowed by operator policy
- CONTRACT_VERSION_MISMATCH: contract version differs from recorded value
- SCHEMA_VERSION_MISMATCH: DB schema version differs from expected value
- EXECUTION_ADAPTER_NOT_IMPLEMENTED: execution adapter not wired in live mode
