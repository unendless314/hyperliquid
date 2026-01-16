# Hyperliquid Copy Trader

A production-grade, event-driven copy trading system designed to replicate trades from a Hyperliquid target wallet to a Binance USDT-M Futures account with strict safety guarantees.

## Project Overview

This project implements a robust "Chain-to-CEX" copy trading pipeline. It prioritizes data integrity, deterministic replay, and fund safety over pure speed. The system is architected around a set of decoupled modules coordinated by a central orchestrator, using SQLite as the Single Source of Truth (SSOT).

### Key Features
*   **Event-Driven Architecture:** Reacts to on-chain events from Hyperliquid.
*   **Safety First:** Includes strict risk gates, circuit breakers, and "Safe Mode" states to prevent unauthorized exposure.
*   **Deterministic Recovery:** Uses SQLite to persist cursors and state, ensuring safe restarts without double-execution.
*   **Reconciliation:** Periodically checks for drift between local state and the exchange.

### Architecture
The system is divided into the following core modules (see `docs/ARCHITECTURE.md`):
*   **Ingest:** Monitors Hyperliquid (WS/REST) and produces standardized `PositionDeltaEvent`s.
*   **Decision:** Applies risk logic and strategy to generate `OrderIntent`s.
*   **Execution:** Handles order lifecycle on Binance, ensuring idempotency.
*   **Safety:** Monitors system health and reconciliation drift.
*   **Storage:** Manages SQLite persistence.

## Building and Running

### Prerequisites
*   Python 3.10+
*   Dependencies installed via `pip` (see `requirements.txt`)

### Setup
1.  **Environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```
2.  **Configuration:**
    *   Create a `settings.yaml` file (schema validation available).
    *   Compute config hash: `python tools/hash_config.py --config settings.yaml`

### Execution Commands
*   **Live Mode:**
    ```bash
    python main.py --mode live --config settings.yaml
    ```
*   **Dry-Run Mode (Safe Testing):**
    ```bash
    python main.py --mode dry-run --config settings.yaml
    ```
*   **Backfill Only:**
    ```bash
    python main.py --mode backfill-only --config settings.yaml
    ```

### Utilities
*   **Validate Config:**
    ```bash
    python tools/validate_config.py --config settings.yaml --schema config/schema.json
    ```

## Development Conventions

*   **Documentation-Driven:** Major architectural decisions and specs are documented in `docs/` before implementation.
*   **Modular Design:** Code should be strictly separated into modules (`Ingest`, `Decision`, `Execution`, etc.) with clear contracts (`docs/CONTRACTS.md`).
*   **SQLite as SSOT:** All critical state (cursors, orders, alerts) must be persisted to SQLite.
*   **Safety Gates:** Changes that increase risk exposure must pass through rigorous checks.
*   **Testing:** Requires unit tests for logic and integration tests (Binance Testnet) for execution flows.

## Key Documentation
*   `docs/README.md`: Entry point for all documentation.
*   `docs/ARCHITECTURE.md`: High-level system design and state machine.
*   `docs/RUNBOOK.md`: Operational procedures and incident response.
*   `docs/DEPLOYMENT.md`: Detailed deployment steps.
