# Repository Guidelines

## Project Structure & Module Organization
- Primary docs live in `docs/`; treat `docs/README.md` as the system map before editing any other files.
- Core specifications are under `docs/{ARCHITECTURE,CONTRACTS,DATA_MODEL,INTEGRATIONS,RUNBOOK,TEST_PLAN,THREAT_MODEL,DEPLOYMENT,OBSERVABILITY,ADR}`—update both doc text and heading metadata when a spec changes.
- Module specs reside in `docs/modules/` (e.g., `modules/INGEST.md`, `modules/DECISION.md`); align headings/responsibilities with their code counterparts.
- Legacy artifacts stay in `docs/archive/`; reference them only for historical context, not active development.

## Build, Test, and Development Commands
- Refer to `docs/DEPLOYMENT.md` for the release flow (build → deploy → verify) and document any new scripts with sample invocations.
- Validate `settings.yaml` and `config_hash` each time you touch config; add new helper commands to the deployment doc so they’re discoverable.
- If you add local automation (shell, Docker, etc.), note the exact command, inputs, and target environment beside the relevant section in `DEPLOYMENT.md`.

## Coding Style & Naming Conventions
- Mirror the vocabulary from docs (e.g., `PositionDeltaEvent`, `cursor_mode`, `replay_policy`) and keep module folder names consistent with their spec files.
- Prefer the established conventional-commit prefixes (`feat`, `fix`, `docs`, `refactor`, etc.) to keep history machine-readable.
- Keep doc/code terminology aligned: structured headings, bullet lists, and repeated names help new contributors map prose to implementation.

## Testing Guidelines
- The strategy lives in `docs/TEST_PLAN.md`—unit checks for validation/dedupe, integration tests against Binance testnet and WebSocket reconnection, and chaos tests for throttling/network faults.
- Name test suites descriptively (`test_settings_validation`, `test_ws_reconnect_backfill`) and document the scope in the test plan for quick discovery.
- When adding tests, list the commands you ran (even if manual) within `docs/TEST_PLAN.md` so reviewers know how to reproduce failures.

## Commit & Pull Request Guidelines
- Use conventional commit syntax, keeping the subject short and scope-specific if helpful (e.g., `feat(ingest): improve backfill dedupe`).
- PR descriptions should cite touched docs/modules, list commands executed, and link to any related issue or ADR.
- Supply proof (logs, screenshots, metrics) when behavior needs verification so reviewers don’t have to reproduce everything themselves.

## Documentation & Knowledge Base
- Sync updates: when module behavior changes, edit both the module spec (`docs/modules/*.md`) and the overview map (`docs/README.md`).
- Drop operational notes (alerts, metrics, runbook steps) into `docs/OBSERVABILITY.md` or `docs/RUNBOOK.md`; avoid ad hoc notes outside the docs tree.
