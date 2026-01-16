# Orchestrator / Config Spec

## Responsibilities
- Load and validate settings
- Run startup state machine
- Start and supervise modules
- Provide mode switching (live, dry-run, backfill-only)

## Inputs
- settings.yaml
- CLI flags

## Outputs
- System mode and safety state
- Module lifecycle control

## Key Rules
- Fail fast on invalid config
- Dry-run must block all write paths
