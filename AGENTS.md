# Repository Guidelines

## Project Structure & Module Organization
- `main.py`: single entrypoint; orchestrates loading `config/settings.yaml` and starting services (logic stubbed, follow `docs/SYSTEM_DESIGN.md`).
- `core/`: trading workflow primitives (`monitor.py`, `strategy.py`, `executor.py`, `reconciler.py` placeholder inside design doc). Keep cross-module contracts here.
- `utils/`: shared helpers (logging, validations, notifications, security, recorders). Add new cross-cutting utilities here, not in `core/`.
- `config/settings.yaml`: runtime configuration; treat as template—copy to environment-specific versions rather than editing in-place for deployments.
- `docs/`: product and system design references (`PRD.md`, `SYSTEM_DESIGN.md`, `HANDOFF.md`). Align code changes to these specs.
- `data/`, `logs/`, `other_stuff/`: working folders; keep generated artifacts out of version control.

## Setup, Build, and Run
- Create a virtualenv and install deps: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
- Run the orchestrator stub: `python main.py`. Planned modes (`--mode live|dry-run|backfill-only`) should be wired per `docs/SYSTEM_DESIGN.md` when implemented.
- Local config: duplicate `config/settings.yaml` to environment-specific copies and load via env var or CLI flag once implemented; never hardcode secrets.

## Coding Style & Naming Conventions
- Python 3.11+; 4-space indent; prefer type hints and explicit returns. Module-level functions over script-style code.
- Follow “one responsibility per module”; keep domain logic in `core/`, side-effects in `utils/`.
- Aim for Black + Ruff compatibility (even though not yet enforced); sort imports, use snake_case for functions/vars and PascalCase for classes.
- Log with structured fields (include `correlation_id`, masked secrets) as outlined in `utils/logger.py` docstring.

## Testing Guidelines
- Use `pytest`; place tests under a new `tests/` directory with files named `test_*.py` mirroring module paths.
- Cover config validation, deduplication, risk checks, and order FSM paths described in `docs/SYSTEM_DESIGN.md`. Include chaos cases (429, network drops) with fakes/mocks.
- Run tests via `pytest -q`; add `coverage` flags when feasible (target ≥80% for new code).

## Commit & Pull Request Guidelines
- Commit history uses concise prefixes (e.g., `docs: update PRD...`, `Initial commit`). Continue with Conventional-like scopes (`core:`, `utils:`, `docs:`) and imperative tense.
- Keep commits focused; include rationale and any config or schema changes in the message body.
- PRs should describe behavior changes, link issues or TODOs from the design docs, note testing performed, and attach logs/screenshots for operational changes.

## Security & Configuration Tips
- Keep API keys and wallet addresses in environment variables or encrypted `.env` files; never commit live secrets.
- Before enabling live trading, verify rate limits, circuit breakers, and dry-run guards align with `docs/SYSTEM_DESIGN.md`.
- Ensure SQLite files and log outputs stay under `data/`/`logs/` and are gitignored for safety.
