# Deployment

## Environments
- Local
- Staging (optional)
- Production

## Configuration
- config/settings.yaml is required at startup and validated with schema rules.
- config_hash is computed from the full config/settings.yaml content.
- config_hash and config_version are persisted in system_state on startup.
- Secrets and sensitive identifiers must be provided via environment variables, not committed files.
  - BINANCE_API_KEY / BINANCE_API_SECRET
  - HYPERLIQUID_TARGET_WALLET (required for live ingest)
- .env is supported via python-dotenv (loaded at startup).

### Expected Commands (MVP)
These commands define the expected operator workflow. If a script does not exist yet, it
must be implemented before release.

- Validate config:
  - python tools/validate_config.py --config config/settings.yaml --schema config/schema.json
- Ops preflight (recommended):
  - PYTHONPATH=src python3 tools/ops_preflight.py --config config/settings.yaml --schema config/schema.json --exchange-time
- Ops validation bundle (recommended):
  - PYTHONPATH=src python3 tools/ops_validate_run.py --config config/settings.yaml --schema config/schema.json --exchange-time --metrics-tail 5 --output docs/ops_validation_run.txt
  - Note: add --allow-create-db only for first-time bootstrap when the DB does not exist.

- Compute config_hash (SHA-256 of config/settings.yaml UTF-8 bytes):
  - python tools/hash_config.py --config config/settings.yaml

## Build
- Python runtime with pinned dependency versions.
- Use a virtual environment for isolation.

### Expected Commands (MVP)
- python -m venv .venv
- . .venv/bin/activate
- pip install -r requirements.txt

## Run Commands
- Live: python src/hyperliquid/main.py --mode live --config config/settings.yaml
- Dry-run: python src/hyperliquid/main.py --mode dry-run --config config/settings.yaml
- Backfill-only: python src/hyperliquid/main.py --mode backfill-only --config config/settings.yaml

## Verify (Post-Deploy)
- Confirm safety mode and reason code in system_state.
- Confirm cursor and event ingestion advancing.
- Confirm reconciliation loop running and drift within thresholds.

### Expected Checks (MVP)
- Inspect SQLite system_state (db_path from settings.yaml):
  - sqlite3 <db_path> "select key, value from system_state where key like 'safety_%';"
  - sqlite3 <db_path> "select key, value from system_state where key like 'last_processed_%';"
  - Note: these queries are read-only.
- Ops post-start checks (recommended):
  - PYTHONPATH=src python3 tools/ops_poststart.py --config config/settings.yaml --schema config/schema.json --metrics-tail 5

- Inspect metrics/logs (from settings.yaml keys):
  - metrics_log_path
  - app_log_path
  - tail -n 50 <app_log_path>

## Ops Tracking Record (MVP)
Record each ops validation run (local/staging/prod) in a simple log file or ticket.
Minimum fields:
- date_utc
- operator
- environment
- mode (live/dry-run/backfill-only)
- config_hash
- config_version
- db_schema_version
- result (pass/fail)
- notes (e.g., failure reason, rollback performed)

Template:
```
date_utc:
operator:
environment:
mode:
config_hash:
config_version:
db_schema_version:
result:
notes:
```

## Rollback
- Stop process
- Restore previous config/settings.yaml
- Restart with previous config_hash
- Verify system_state reflects the restored config_hash

## Release Checklist
- config/settings.yaml schema validated
- config_hash recorded
- API keys loaded for selected environment
- time sync offset computed
- startup reconciliation completed
