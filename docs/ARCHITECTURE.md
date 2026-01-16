# System Architecture

## Overview
This system is an event-driven copy trading pipeline with strict safety and restart guarantees.
It monitors a target wallet on Hyperliquid, standardizes events, applies risk-aware decision
logic, and executes orders on Binance USDT-M Futures.

Core goals:
- Data integrity with deterministic replay and dedup
- Safety-first behavior under uncertainty
- Auditability and recoverability via a single source of truth (SQLite)

## Module Boundaries
1. Ingest/Monitor
   - Connects to Hyperliquid (WS + REST backfill)
   - Cursor tracking, gap detection, dedup
   - Produces PositionDeltaEvent

2. Decision/Strategy
   - Risk gates (slippage, filters, replay policy)
   - Sizing and intent generation
   - Produces OrderIntent

3. Execution
   - Order FSM, retries, TIF, fallback
   - Idempotent clientOrderId persistence
   - Produces OrderResult

4. State/Storage
   - SQLite as SSOT
   - Cursor, processed_txs, order history, system_state

5. Safety/Reconciliation
   - Startup reconciliation
   - Periodic drift checks
   - Enters ARMED_SAFE or HALT on critical issues

6. Orchestrator/Config
   - Loads settings and validates schema
   - Runs startup state machine
   - Starts and supervises modules

7. Observability/Alert
   - Logs, metrics, alerts
   - Correlation IDs for tracing

## Data Flow (High Level)
Raw fills -> Ingest -> PositionDeltaEvent -> Decision -> OrderIntent -> Execution -> OrderResult
All critical state is persisted in State/Storage.
Safety/Reconciliation runs alongside Execution to guard drift and unsafe conditions.

## Event Ordering and Cursor Semantics
- Event ordering uses a deterministic composite key:
  - timestamp_ms, event_index, tx_hash, symbol
- Cursor advances only after event persistence succeeds.
- Backfill uses an overlap window; dedup resolves duplicates.

## Startup State Machine
BOOTSTRAP -> SNAPSHOT_CHECK -> RECONCILE_ON_START -> BACKFILL_CATCHUP -> ARMED_SAFE | ARMED_LIVE | HALT

- ARMED_SAFE: no exposure increase; allow reduce-only as configured
- ARMED_LIVE: normal operation
- HALT: hard stop, manual intervention required

## Failure Domains
- Data integrity: gaps, duplicate events, cursor errors
- Execution: order failures, partial fills, unknown status
- Risk control: slippage, wrong position mode, stale data

## Non-Goals
- Hedge mode support
- Automatic risk-increasing repairs
- Dependence on best-effort external data without freshness checks
