# Hyperliquid Copy Trader

## Project Overview
This project is an automated copy trading system designed to listen to on-chain signals from a target wallet (Smart Money) on **Hyperliquid** and execute corresponding trades on a centralized exchange (**Binance**).

The system follows a "Monitor -> Strategy -> Execute" architecture, emphasizing low latency, reliability (reconnection handling), and risk management (Kelly criterion, fixed amounts, etc.).

### Current Status
*   **Phase**: Concept/Initial Implementation
*   **Documentation**: Detailed PRD and System Design are available in `docs/`.
*   **Implementation**:
    *   **Reporting**: `analyze_trades.py` is implemented to generate HTML reports from trade history CSVs.
    *   **Core Logic**: The main trading bot (`main.py`, `core/monitor.py`, etc.) is currently **pending implementation**.

## Key Documentation
*   **[PRD.md](docs/PRD.md)**: Product Requirements Document. Defines functional requirements, money management modes (Fixed, Proportional, Kelly), and risk controls.
*   **[SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)**: Technical specifications. Outlines the modular architecture (Monitor, Strategy, Executor), data flow, and file structure.

## Architecture (Planned)
Based on `docs/SYSTEM_DESIGN.md`:
*   **`main.py`**: Entry point.
*   **`core/monitor.py`**: WebSocket listener for Hyperliquid `UserFills`.
*   **`core/strategy.py`**: Signal processing, symbol mapping, and position sizing.
*   **`core/executor.py`**: Execution on Binance via `CCXT`.
*   **`utils/`**: Logging, notifications, and helpers.

## Building and Running

### Prerequisites
*   Python 3.x
*   Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Configuration
*   **`config/settings.yaml`**: Main configuration file (strategy mode, risk limits, etc.).
*   **`.env`**: Environment variables for API keys (never commit this).

### Trade Analysis
The project currently includes a script to analyze trade history and generate a performance report.

**Usage:**
```bash
python analyze_trades.py
```
*   **Input**: `trade_history.csv` (Expected format: `time`, `px`, `dir`, `closedPnl`, etc.)
*   **Output**: `trade_report.html` (Interactive chart and metrics)

## Development Conventions
*   **Language**: Python
*   **Style**: Adhere to PEP 8.
*   **Logging**: All trading actions and errors must be logged to `logs/trading.log`.
*   **Data Persistence**: Trade history is saved to `trade_history.csv` for local analysis.
*   **Safety**: API keys are managed via `.env`. No hardcoded secrets.
