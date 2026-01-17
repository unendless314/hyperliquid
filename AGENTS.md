# Repository Guidelines

## Project Structure & Module Organization
- `src/hyperliquid/` is the Python package root. Core modules are `ingest/`, `decision/`, `execution/`, `storage/`, `safety/`, `orchestrator/`, and `observability/`, with shared utilities in `common/`.
- `docs/` contains the system specs and operating docs (see `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, and `docs/modules/*`); treat `docs/README.md` as the system map before editing any other files.
- `tests/` is organized by scope: `unit/`, `integration/`, and `chaos/`.
- `config/` holds configuration files such as `config/settings.yaml` and `config/schema.json`.
- `tools/` contains operational scripts (e.g., config validation and hashing).

## Build, Test, and Development Commands
- Create a local venv and install dependencies:
  - `python -m venv .venv`
  - `. .venv/bin/activate`
  - `pip install -r requirements.txt`
- Validate configuration: `python tools/validate_config.py --config config/settings.yaml --schema config/schema.json`
- Compute config hash: `python tools/hash_config.py --config config/settings.yaml`
- Run modes:
  - `python src/hyperliquid/main.py --mode live --config config/settings.yaml`
  - `python src/hyperliquid/main.py --mode dry-run --config config/settings.yaml`
  - `python src/hyperliquid/main.py --mode backfill-only --config config/settings.yaml`
- Testing is currently defined by `docs/TEST_PLAN.md` (manual/ops checks); see that file for step-by-step verification.

## Coding Style & Naming Conventions
- Python 3.10+ (see `pyproject.toml`). Use 4-space indentation and standard PEP 8 naming.
- Prefer `snake_case` for functions/variables, `PascalCase` for classes, and module names that mirror the subsystem (e.g., `ingest/`, `execution/`).
- Keep module boundaries aligned with `docs/modules/*` and cross-module contracts in `docs/CONTRACTS.md`.

## Testing Guidelines
- Place unit tests under `tests/unit/`, integration tests under `tests/integration/`, and chaos tests under `tests/chaos/`.
- Use `test_*.py` naming (see TODOs listed in `docs/TEST_PLAN.md`).
- Runtime validation often involves SQLite and log inspection; examples are in `docs/TEST_PLAN.md` (e.g., `sqlite3 <db_path> ...`, `tail -n 50 <metrics_log_path>`).

## Commit & Pull Request Guidelines
- Commit history follows Conventional Commits, e.g., `docs: ...` and `chore: ...`.
- Keep messages short and scoped; include the subsystem when helpful (e.g., `docs: update execution idempotency notes`).
- PRs should include: a brief summary, how you tested (or why not), and any config/logging impacts (especially changes to `config/settings.yaml`).

## Configuration & Ops Notes
- `config/settings.yaml` is required at startup; validate it and record the hash before running.
- Operational checks and rollback guidance live in `docs/DEPLOYMENT.md` and `docs/RUNBOOK.md`.
