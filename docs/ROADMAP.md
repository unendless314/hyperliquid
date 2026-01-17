# Roadmap

This document tracks delivery progress for the Hyperliquid Copy Trader.
It is intended to be short-lived and updated frequently. For stable specs,
see the technical docs referenced in docs/README.md.

## Conventions
- Status: [ ] planned, [~] in progress, [x] done
- Each task should have a concrete acceptance note or pointer to a doc
- Keep this file concise; move deeper details into issues or PRs

## Epic 0: Project bootstrap
- [ ] Story 0.1: Config and settings bootstrap
  - [ ] Task: Implement settings loader in src/hyperliquid/common/settings.py
  - [ ] Task: Wire schema validation hook (config/schema.json)
  - [ ] Task: Add config hash check via tools/hash_config.py
  - [ ] Task: Add minimal config smoke check in main.py
  - Acceptance: Running main.py reads config, validates schema, checks hash, and exits cleanly on valid config

- [ ] Story 0.2: Observability scaffolding
  - [ ] Task: Implement logging setup in src/hyperliquid/common/logging.py
  - [ ] Task: Implement metrics skeleton in src/hyperliquid/common/metrics.py
  - [ ] Task: Wire logging/metrics initialization in orchestrator
  - Acceptance: Startup logs and metrics emit with fields and names aligned to docs/OBSERVABILITY.md

- [ ] Story 0.3: Storage scaffolding
  - [ ] Task: Implement DB connection + schema init in src/hyperliquid/storage/db.py
  - [ ] Task: Add basic migration guard or schema check
  - Acceptance: DB initializes and version/schema check passes

- [ ] Story 0.4: Orchestrator + main entrypoint
  - [ ] Task: Implement orchestrator lifecycle in src/hyperliquid/orchestrator/service.py
  - [ ] Task: Implement main.py startup/shutdown flow
  - Acceptance: A single "boot" cycle runs end-to-end

- [ ] Story 0.5: Contracts & data model baseline
  - [ ] Task: Map docs/CONTRACTS.md structures into src/hyperliquid/common/models.py
  - [ ] Task: Add contract/schema version fields to shared models
  - [ ] Task: Define versioning policy and mismatch behavior (major/minor rules) and document it in docs/CONTRACTS.md
  - [ ] Task: Add contract version assertion in startup (orchestrator/main)
  - Acceptance: Common models reflect CONTRACTS and enforce version compatibility at startup

## Epic 1: Ingest pipeline (market/leader events)
- [ ] Story 1.1: Ingest service skeleton
  - [ ] Task: Implement ingest service interface in src/hyperliquid/ingest/service.py
  - [ ] Task: Define ingest event models in src/hyperliquid/common/models.py
  - Acceptance: Ingest can be instantiated and emit mock events using models from Story 0.5
  - Note: Initial pipeline runs in event-driven mode; raw ingest wiring is deferred until external adapters land.

- [ ] Story 1.2: External integration hooks
  - [ ] Task: Add integration adapter stubs based on docs/INTEGRATIONS.md
  - [ ] Task: Add rate limit + retry policy placeholders
  - [ ] Task: Add contract version assertion on ingest output
  - Acceptance: Adapters can be wired without hitting live APIs

## Epic 2: Decision engine
- [ ] Story 2.1: Decision rules skeleton
  - [ ] Task: Implement decision service interface in src/hyperliquid/decision/service.py
  - [ ] Task: Define decision request/response models
  - [ ] Task: Add contract version assertion on decision inputs/outputs
  - Acceptance: Decision service returns deterministic placeholder actions

- [ ] Story 2.2: Strategy constraints
  - [ ] Task: Implement sizing/risk constraints per docs/modules/DECISION.md
  - Acceptance: Inputs violating constraints are rejected

## Epic 3: Execution engine
- [ ] Story 3.1: Execution service skeleton
  - [ ] Task: Implement execution service interface in src/hyperliquid/execution/service.py
  - [ ] Task: Define execution order models
  - [ ] Task: Add safety hook placeholders for pre/post execution checks
  - [ ] Task: Add contract version assertion on execution requests
  - Acceptance: Execution service can accept and ack a mock order; pre/post safety hooks are invoked and can reject

- [ ] Story 3.2: Exchange adapter skeleton
  - [ ] Task: Implement adapter stubs per docs/INTEGRATIONS.md
  - [ ] Task: Add idempotency + dedup placeholders
  - Acceptance: Execution flow can be simulated end-to-end

## Epic 4: Safety + reconciliation
- [ ] Story 4.1: Safety service skeleton
  - [ ] Task: Implement safety service interface in src/hyperliquid/safety/service.py
  - [ ] Task: Define reconciliation models and checks
  - Acceptance: Safety service can validate a mock execution state

## Epic 5: Persistence + audit
- [ ] Story 5.1: Persistence pipeline
  - [ ] Task: Implement state persistence per docs/DATA_MODEL.md
  - [ ] Task: Add audit log entries for key state changes
  - Acceptance: Core state can be recovered after restart

## Epic 6: Testing + runbook alignment
- [ ] Story 6.1: Test scaffolding
  - [ ] Task: Add tests listed in docs/TEST_PLAN.md TODOs
  - [ ] Task: Add minimal unit tests for settings + DB init
  - Acceptance: Tests pass locally per docs/TEST_PLAN.md

- [ ] Story 6.2: Ops validation
  - [ ] Task: Validate operational flows per docs/RUNBOOK.md
  - Acceptance: Manual ops checklist is executable
