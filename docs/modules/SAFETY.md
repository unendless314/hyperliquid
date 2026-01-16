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

## Drift Calculation
- Drift is computed per symbol as absolute position difference.
- Thresholds are evaluated per symbol (not a cross-symbol sum).
- If a total drift metric is used later, symbols must not offset each other.

## Cadence
- Startup reconciliation runs once at boot.
- Periodic reconciliation runs every reconcile_interval_sec.

## Key Rules
- Do not auto-increase exposure when fixing drift
- Allow reduce-only during ARMED_SAFE if enabled

## Safety Mode Visibility
- Every transition into ARMED_SAFE or HALT must record:
  - reason code (enum)
  - human-readable message
  - timestamp
- The latest safety status is persisted in system_state for diagnostics.
- Alerts must include the reason code and timestamp.

## Reason Codes (MVP)
- GAP_EXCEEDED: gap larger than backfill_window
- SNAPSHOT_STALE: snapshot age exceeds snapshot_max_stale_ms
- RECONCILE_CRITICAL: drift exceeds critical_threshold
- POSITION_MODE_INVALID: exchange is not in one-way mode
- STORAGE_UNAVAILABLE: DB unavailable or corrupted
- CONFIG_HASH_MISMATCH: config_hash differs from recorded value

