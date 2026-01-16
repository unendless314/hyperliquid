# Safety / Reconciliation Spec

## Responsibilities
- Startup reconciliation
- Periodic drift checks between DB and exchange
- Enter ARMED_SAFE or HALT on critical mismatch

## Inputs
- Exchange positions
- DB positions
- settings: warn_threshold, critical_threshold, startup_policy

## Outputs
- Safety mode transitions
- Alerts

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
