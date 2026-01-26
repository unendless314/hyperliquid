# Hyperliquid Copy Trader

A production-grade, event-driven copy trading system designed to replicate trades from a Hyperliquid target wallet to a Binance USDT-M Futures account with strict safety guarantees.

## Project Overview

This project implements a "Chain-to-CEX" copy trading pipeline. It prioritizes data integrity, deterministic replay, and fund safety. The system is architected around decoupled modules coordinated by a central orchestrator, using SQLite as the Single Source of Truth (SSOT).

### Key Features
*   **Event-Driven:** Reacts to on-chain events from Hyperliquid (fills).
*   **Safety First:** strict risk gates, circuit breakers, and "Safe Mode" states.
*   **Deterministic Recovery:** Persists cursors and state in SQLite to ensure safe restarts.
*   **Reconciliation:** Periodically checks for drift between local state and the exchange.

## Architecture

The system is divided into core modules (see `docs/ARCHITECTURE.md`):
*   **Ingest:** Monitors Hyperliquid (WS/REST) and produces `PositionDeltaEvent`s.
*   **Decision:** Applies risk logic/strategy to generate `OrderIntent`s.
*   **Execution:** Handles order lifecycle on Binance, ensuring idempotency.
*   **Safety:** Monitors system health and reconciliation drift.
*   **Storage:** Manages SQLite persistence.
*   **Orchestrator:** Manages lifecycle and startup state machine.

## Setup & Installation

1.  **Environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Configuration:**
    *   Copy/Edit `config/settings.yaml`.
    *   Validate with: `python tools/validate_config.py --config config/settings.yaml --schema config/schema.json`

## Usage (CLI)

Entry point: `src/hyperliquid/main.py`.

### Modes
*   `--mode live`: Real trading on Binance.
*   `--mode dry-run`: Simulate execution without placing real orders.
*   `--mode backfill-only`: Process historical data only.

### Arguments
*   `--config <path>`: Path to settings YAML (Required).
*   `--run-loop`: Enter continuous run loop after startup.
*   `--emit-boot-event`: Emit a mock event on startup (Default: True).
*   `--loop-interval-sec <int>`: Idle sleep interval for run loop.

### Examples
```bash
# Run in Dry-Run mode
python -m src.hyperliquid.main --mode dry-run --config config/settings.yaml

# Run Live with continuous loop
python -m src.hyperliquid.main --mode live --config config/settings.prod.yaml --run-loop
```

## Development & Testing

*   **Unit Tests:** `pytest tests/unit`
*   **Integration Tests:** `pytest tests/integration` (may require env vars or testnet keys)
*   **Code Structure:**
    *   `src/hyperliquid/`: Source code.
    *   `tests/`: Test suite.
    *   `docs/`: Comprehensive documentation.
    *   `tools/`: Operational scripts (hash config, recovery, etc.).

## Key Documentation
*   `docs/README.md`: Main entry point.
*   `docs/ARCHITECTURE.md`: System design and state machine.
*   `docs/RUNBOOK.md`: Operational procedures.
*   `docs/QUICKSTART.md`: User guide (Traditional Chinese).
