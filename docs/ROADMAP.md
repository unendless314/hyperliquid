# Roadmap

This document tracks delivery progress for the Hyperliquid Copy Trader.
It is intended to be short-lived and updated frequently. For stable specs,
see the technical docs referenced in docs/README.md.

## Conventions
- Status: [ ] planned, [~] in progress, [x] done
- Each task should have a concrete acceptance note or pointer to a doc
- Keep this file concise; move deeper details into issues or PRs

## Epic 0: Project bootstrap
- [x] Story 0.1: Config and settings bootstrap
  - [x] Task: Implement settings loader in src/hyperliquid/common/settings.py
  - [x] Task: Wire schema validation hook (config/schema.json)
  - [x] Task: Add config hash check via tools/hash_config.py
  - [x] Task: Add minimal config smoke check in main.py
  - Acceptance: Running main.py reads config, validates schema, checks hash, and exits cleanly on valid config

- [x] Story 0.2: Observability scaffolding
  - [x] Task: Implement logging setup in src/hyperliquid/common/logging.py
  - [x] Task: Implement metrics skeleton in src/hyperliquid/common/metrics.py
  - [x] Task: Wire logging/metrics initialization in orchestrator
  - Acceptance: Startup logs and metrics emit with fields and names aligned to docs/OBSERVABILITY.md

- [x] Story 0.3: Storage scaffolding
  - [x] Task: Implement DB connection + schema init in src/hyperliquid/storage/db.py
  - [x] Task: Add basic migration guard or schema check
  - Acceptance: DB initializes and version/schema check passes

- [x] Story 0.4: Orchestrator + main entrypoint
  - [x] Task: Implement orchestrator lifecycle in src/hyperliquid/orchestrator/service.py
  - [x] Task: Implement main.py startup/shutdown flow
  - Acceptance: A single "boot" cycle runs end-to-end
  - Note: Continuous run loop is a placeholder; real ingest-driven loops will replace it.

- [x] Story 0.5: Contracts & data model baseline
  - [x] Task: Map docs/CONTRACTS.md structures into src/hyperliquid/common/models.py
  - [x] Task: Add contract/schema version fields to shared models
  - [x] Task: Define versioning policy and mismatch behavior (major/minor rules) and document it in docs/CONTRACTS.md
  - [x] Task: Add contract version assertion in startup (orchestrator/main)
  - Acceptance: Common models reflect CONTRACTS and enforce version compatibility at startup

## Epic 1: Ingest pipeline (market/leader events)
- [x] Story 1.1: Ingest service skeleton
  - [x] Task: Implement ingest service interface in src/hyperliquid/ingest/service.py
  - [x] Task: Define ingest event models in src/hyperliquid/common/models.py
  - [x] Task: Add raw ingest stub with dedup + cursor update
  - [x] Task: Connect raw ingest to external adapters (WS/REST)
  - Acceptance: Ingest can be instantiated and emit mock events using models from Story 0.5
  - Note: Initial pipeline runs in event-driven mode; raw ingest wiring is deferred until external adapters land.

- [x] Story 1.2: External integration hooks
  - [x] Task: Add integration adapter stubs based on docs/INTEGRATIONS.md
  - [x] Task: Add rate limit + retry policy placeholders
  - [x] Task: Add contract version assertion on ingest output
  - [~] Task: Wire REST backfill/live polling adapter for Hyperliquid
  - Acceptance: Adapters can be wired without hitting live APIs

## Epic 2: Decision engine
- [~] Story 2.1: Decision rules skeleton
  - [x] Task: Implement decision service interface in src/hyperliquid/decision/service.py
  - [x] Task: Define decision request/response models
  - [x] Task: Add contract version assertion on decision inputs/outputs
  - [x] Task: Add replay policy gate (close-only)
  - Acceptance: Decision service returns deterministic placeholder actions

- [ ] Story 2.2: Strategy constraints
  - [ ] Task: Implement sizing/risk constraints per docs/modules/DECISION.md
  - Acceptance: Inputs violating constraints are rejected

## Epic 3: Execution engine
- [~] Story 3.1: Execution service skeleton
  - [x] Task: Implement execution service interface in src/hyperliquid/execution/service.py
  - [x] Task: Define execution order models
  - [x] Task: Add safety hook placeholders for pre/post execution checks
  - [x] Task: Add contract version assertion on execution requests/results
  - Acceptance: Execution service can accept and ack a mock order; pre/post safety hooks are invoked and can reject

- [ ] Story 3.2: Exchange adapter skeleton
  - [x] Task: Implement adapter stubs per docs/INTEGRATIONS.md
  - [~] Task: Add idempotency + dedup placeholders
  - Acceptance: Execution flow can be simulated end-to-end

## Epic 4: Safety + reconciliation
- [~] Story 4.1: Safety service skeleton
  - [x] Task: Implement safety service interface in src/hyperliquid/safety/service.py
  - [~] Task: Define reconciliation models and checks
  - Acceptance: Safety service can validate a mock execution state

## Epic 5: Persistence + audit
- [~] Story 5.1: Persistence pipeline
  - [x] Task: Implement state persistence per docs/DATA_MODEL.md (order_intents/order_results)
  - [x] Task: Add cursor + processed_txs persistence
  - [ ] Task: Add audit log entries for key state changes
  - Acceptance: Core state can be recovered after restart

## Epic 6: Testing + runbook alignment
- [~] Story 6.1: Test scaffolding
  - [~] Task: Add tests listed in docs/TEST_PLAN.md TODOs (partial)
  - [x] Task: Add minimal unit tests for settings + DB init (added multiple unit tests)
  - Acceptance: Tests pass locally per docs/TEST_PLAN.md

- [ ] Story 6.2: Ops validation
  - [ ] Task: Validate operational flows per docs/RUNBOOK.md
  - Acceptance: Manual ops checklist is executable

## Handoff Notes (2026/01/17)
- Pipeline is event-driven; raw ingest adapters are still deferred (see Epic 1.2).
- Dedup + cursor updates are atomic; cursor only advances when event ordering is newer.
- Decision replay policy defaults to close-only; tests added for replay/flip/pipeline/persistence.
- Boot cycle emits a mock raw event; disable with --no-emit-boot-event if needed.
- DB persistence uses order_intents immutable (INSERT OR IGNORE) and order_results mutable (ON CONFLICT UPDATE).
