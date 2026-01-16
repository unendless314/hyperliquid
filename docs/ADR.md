# Architecture Decision Records

This file tracks major architectural decisions and their rationale.

## ADR-001: SQLite as Single Source of Truth
- Date: 2026-01-16
- Status: Accepted
- Context: Need a lightweight, reliable persistence layer for cursor, idempotency, and recovery.
- Decision: Use SQLite (WAL, single-connection) as SSOT.
- Alternatives Considered: Postgres, Redis + files.
- Consequences: Simpler deployment; requires careful concurrency control.

## ADR-002: One-way Position Mode Only
- Date: 2026-01-16
- Status: Accepted
- Context: Hedge mode complicates position tracking and reduce-only safety rules.
- Decision: Support one-way mode only; fail fast if exchange is in hedge mode.
- Alternatives Considered: Dual support with branching logic.
- Consequences: Safer and simpler; users must configure exchange mode correctly.

## ADR-003: Testnet-first Live Validation
- Date: 2026-01-16
- Status: Accepted
- Context: Need reproducible validation without risking real capital.
- Decision: Require Binance testnet for initial live-mode validation.
- Alternatives Considered: Paper trading only; mainnet guarded rollout.
- Consequences: Requires testnet API keys; closer to real exchange behavior.

