# Hyperliquid Copy Trader

## Project Overview
This project is an event-driven copy trading system designed to replicate trades from a target wallet on the Hyperliquid DEX to a Binance USDT-M Futures account. It emphasizes safety, data integrity, and auditability.

The system is built with a modular architecture in Python, ensuring clear separation of concerns between data ingestion, strategy decisioning, order execution, and state persistence.

### Key Features
*   **Event-Driven Pipeline:**  Fills -> Ingest -> PositionDeltaEvent -> Decision -> OrderIntent -> Execution -> OrderResult.
*   **Safety First:** Includes a dedicated Safety module for reconciliation and drift detection.
*   **State Persistence:** Uses SQLite as the Single Source of Truth (SSOT) for critical state and audit logs.
*   **Modes:** Supports `live`, `dry-run`, and `backfill-only` modes.
*   **Observability:** Comprehensive logging, metrics, and alerting integration.

## Architecture
The system is divided into the following core modules (located in `src/hyperliquid/`):

*   **Ingest (`ingest/`):** Connects to Hyperliquid (WebSocket + REST), tracks cursors, detects gaps, and deduplicates events.
*   **Decision (`decision/`):** Applies risk rules, sizing logic, and generates order intents.
*   **Execution (`execution/`):** Manages order lifecycle on Binance, including retries and idempotency.
*   **Storage (`storage/`):** Manages SQLite persistence for system state and history.
*   **Safety (`safety/`):** Performs reconciliation (startup & periodic) and guards against drift.
*   **Orchestrator (`orchestrator/`):** Manages the application lifecycle and startup state machine.
*   **Observability (`observability/`):** Handles logging and metrics.

Detailed architecture documentation can be found in `docs/ARCHITECTURE.md` and `docs/modules/*.md`.

## Building and Running

### Prerequisites
*   Python 3.10+
*   Virtual environment recommended.

### Setup
1.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuration:**
    *   Copy `config/settings.yaml` (or `settings.prod.yaml`) and configure it.
    *   Ensure `.env` contains necessary API keys.
    *   Validate config:
        ```bash
        PYTHONPATH=src python3 tools/validate_config.py --config config/settings.yaml --schema config/schema.json
        ```

### Running the Application
The main entry point is `src/hyperliquid/main.py`.

**Continuous Live Mode:**
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.yaml \
  --run-loop
```

**Dry-Run Mode:**
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode dry-run \
  --config config/settings.yaml \
  --run-loop
```

**Backfill Only:**
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode backfill-only \
  --config config/settings.yaml
```

### Operational Tools
Scripts in `tools/` assist with operations:
*   `tools/ops_startup_doctor.py`: Diagnostics before startup.
*   `tools/ops_check_target_wallet.py`: Verify target wallet activity.
*   `tools/hash_config.py`: Compute config consistency hash.

## Testing
The project uses `pytest` for testing.

**Run Unit Tests:**
```bash
PYTHONPATH=src pytest tests/unit/
```

**Run Integration Tests:**
```bash
PYTHONPATH=src pytest tests/integration/
```

**Run All Tests:**
```bash
PYTHONPATH=src pytest tests/
```

## Development Conventions

*   **Code Style:** Follows PEP 8.
*   **Naming:**
    *   Functions/Variables: `snake_case`
    *   Classes: `PascalCase`
    *   Modules: Reflect subsystem names (e.g., `ingest`, `execution`).
*   **Imports:** Absolute imports from `src` (e.g., `from hyperliquid.common.settings import ...`).
*   **Documentation:**
    *   Update `docs/` when changing architecture or behavior.
    *   Keep `docs/README.md` as the central index.
*   **Testing:** New features/fixes must include tests (`tests/unit` or `tests/integration`).
