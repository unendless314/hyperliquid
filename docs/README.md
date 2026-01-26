# Hyperliquid Copy Trader - Technical Docs

This is the primary documentation set for the refactored, modular system.

## Quick Navigation

**New to the project?** Start here:
- 🚀 [QUICKSTART.md](QUICKSTART.md) - First-time user guide (Traditional Chinese)
- 🔧 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Daily operations and troubleshooting (Traditional Chinese)

**For engineers:**
- 📚 [RUNBOOK.md](RUNBOOK.md) - Complete operational runbook
- 🏗️ [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- 📊 [CODE_REVIEW.md](CODE_REVIEW.md) - Code quality assessment (8.5/10)

---

## Development Approach
Documentation is created up front but filled in progressively. During MVP, only the most
critical documents are fully specified. Other documents may contain placeholders or partial
content and will be completed as the system stabilizes.

## Document Map

### User Documentation (Traditional Chinese)
- **QUICKSTART.md**: Quick start guide for first-time users
- **TROUBLESHOOTING.md**: Daily operations, monitoring, and troubleshooting guide

### Progress
- ROADMAP.md: Epic/story/task tracking for delivery progress

### Core Technical Documentation
- ARCHITECTURE.md: System overview, module boundaries, data flow, state machine
- CONTRACTS.md: Cross-module data contracts and shared terminology
- DATA_MODEL.md: Database schema and persistence rules
- INTEGRATIONS.md: External API integration details
- RUNBOOK.md: Operations and incident response (complete technical reference)
- TEST_PLAN.md: Test strategy and coverage
- THREAT_MODEL.md: Risk analysis and mitigations
- DEPLOYMENT.md: Build, release, and configuration strategy
- ADR.md: Architecture decision records
- OBSERVABILITY.md: Metrics, logging, alerting, SLO/SLA targets
- CODE_REVIEW.md: Code quality assessment and improvement roadmap (8.5/10)

### Modules
- modules/INGEST.md: Ingest/monitoring module spec
- modules/DECISION.md: Decision/strategy module spec
- modules/EXECUTION.md: Execution (order) module spec
- modules/STORAGE.md: State and persistence module spec
- modules/SAFETY.md: Reconciliation and safety module spec
- modules/ORCHESTRATOR.md: Startup and lifecycle control spec
- modules/OBSERVABILITY.md: Logging, metrics, alerting spec

### Archive
- archive/: Legacy PRD and system design docs

## MVP Readiness
Minimum viable docs to start coding:
- ARCHITECTURE.md
- CONTRACTS.md
- DATA_MODEL.md
- INTEGRATIONS.md
- DEPLOYMENT.md
- RUNBOOK.md
- TEST_PLAN.md
- OBSERVABILITY.md
- modules/INGEST.md
- modules/DECISION.md
- modules/EXECUTION.md
- modules/STORAGE.md
- modules/SAFETY.md
- modules/ORCHESTRATOR.md
- modules/OBSERVABILITY.md

## Principles
- Separate responsibilities by module boundary
- Persist all critical state needed for safe restart
- Fail fast on unsafe or inconsistent conditions
- Prefer deterministic, auditable behavior over speed

## Naming Conventions
- CLI flags and mode values use kebab-case (e.g., dry-run, backfill-only).
- Config enum values use snake_case (e.g., close_only, allow_without_price).

## Future Work / Out of Scope (MVP)
- Capital exposure limits (daily/weekly loss caps, per-leader allocation caps) are user-managed and not enforced by the system yet.
- Strategy effectiveness monitoring (leader performance drift, auto-disable rules) is intentionally deferred.
- Operator-level emergency stop procedures are documented in RUNBOOK but not automated.

## Local Testing Notes
- If running tests without installing the package, set PYTHONPATH=src (e.g., PYTHONPATH=src python3 -m pytest tests/unit/test_decision_flip.py)

## Runtime Notes
- main.py supports an ingest-driven continuous loop via --run-loop; safety modes gate trading while the process remains running.
