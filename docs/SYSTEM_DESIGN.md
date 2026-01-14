# Hyperliquid Copy Trader - 系統設計規格書 (Technical Specification) v1.2

## 1. 系統架構 (System Architecture)

採用 **事件驅動 (Event-Driven)** 與 **狀態機 (State Machine)** 結合的架構，並引入 SQLite 作為單一事實來源 (SSOT)。

### 1.1 核心模組 (Core Modules)

*   **Main (Orchestrator)**:
    *   負責加載配置 (`settings.yaml`) 並執行 **Schema Validation** (fail-fast)。
    *   初始化 SQLite 資料庫連線。
    *   啟動並監控子線程/協程 (Monitor, Executor, Reconciler)。

*   **Monitor (Ingestion Layer)**:
    *   **WebSocket Client**: 維護與 Hyperliquid 的長連線。
    *   **Gap Detector**: 比對 `latest_block_height` 與 DB 中的 `cursor`。
        * 若落差 ≤ `BACKFILL_WINDOW` (例：200 區塊)，以 REST 回補並經過 Dedup 流程。
        * 若落差 > `BACKFILL_WINDOW`，觸發安全停機 (Halt) + Alert，避免在資料缺口下繼續交易。
    *   **Dedup Gatekeeper**: 查詢 SQLite `processed_txs` 表 (含 `tx_hash`,`event_index`,`symbol`)；若存在 -> Drop；若無 -> Insert 並傳遞。

*   **Strategy (Processing Layer)**:
    *   執行 Symbol Mapping (Hyperliquid -> Binance)。
    *   執行 Risk Checks (Price Deviation：百分比+USD 絕對值、Blacklist、Binance Filters)。
    *   計算 Position Size。

*   **Executor (Action Layer)**:
    *   **Order FSM**: 管理訂單狀態 (Submit -> Monitor -> Finalize)，包含 `UNKNOWN`/`STUCK` 狀態供 Reconciler 後續處理。
    *   **Smart Retry**: 實作帶有 Jitter 的指數退避 (Exponential Backoff)，與 Status Poller/Query 共用同一組 Rate Limiter/Backoff。
    *   **Idempotency Key**: `clientOrderId = hl-{tx_hash}-{nonce}`，確保重試或斷線重送不會重複開倉。

*   **Reconciler (Safety Layer)**:
    *   **非同步迴圈**: 每 X 秒執行一次。
    *   **Drift Check**: `abs(Binance_Position - DB_Position) > Threshold`?
    *   分級動作：< `warn_threshold` 記錄+通知；≥ `critical_threshold` 觸發 Critical Alert，並可選擇 `Force Sync` (多退少補/平倉)。

### 1.2 資料儲存 (Data Persistence - SQLite)

使用 SQLite，確保 ACID 特性。

**Table Schema (Draft):**
1.  `processed_txs`:
    *   `tx_hash` (PK), `event_index`, `symbol`, `block_height`, `timestamp`, `created_at`。
    *   索引：`tx_hash` 唯一、`created_at` 供 TTL 清理。
    *   用於冪等性檢查；保留 24h，背景任務定期清理。
2.  `trade_history`:
    *   `id` (PK), `correlation_id`, `symbol`, `side`, `size`, `price`, `pnl`, `status`, `exchange_order_id`, `tx_hash`。
    *   索引：`correlation_id`、`tx_hash`。
    *   用於報表與歷史回測。
3.  `system_state`:
    *   `key` (PK), `value`。
    *   用於儲存 `last_processed_block`, `config_hash`, `config_version` 等游標/審計數據。

**SQLite 操作守則**
- 啟用 WAL、設定 `busy_timeout`，單執行緒單連線；避免跨執行緒共享連線。
- 每日備份並驗證可還原；`processed_txs` 具備定期 vacuum/cleanup 任務。

## 2. 數據流與控制流 (Data & Control Flow)

### 2.1 正常交易流程
1.  **Monitor**: 收到 `UserFills` -> Hash Check (SQLite) -> 通過 -> 寫入 SQLite (Pending) -> Push to Queue；若 Gap 超過 `BACKFILL_WINDOW`，觸發 Halt。
2.  **Strategy**: Pull Queue -> 驗證數據新鮮度 -> 計算 Size -> 檢查 Binance Filters -> 產生 `OrderRequest`。
3.  **Executor**:
    *   檢查 `CircuitBreaker` (是否觸發熔斷)；`CircuitBreaker` 與 Rate Limiter 共用冷卻計數。
    *   呼叫 CCXT `create_order` (帶 `clientOrderId`)。
    *   收到 `order_id` -> 更新 SQLite 狀態為 `SUBMITTED`。
    *   啟動 `OrderMonitor` 輪詢成交狀態 (受同一 Rate Limiter 管控) -> 更新 SQLite 為 `FILLED` / `PARTIALLY_FILLED` / `EXPIRED`；若無回報超時，標記 `UNKNOWN`。
4.  **Notifier**: 根據狀態變更發送 Telegram (需經過 Rate Limiter)。

### 2.2 錯誤處理流程
*   **Rate Limit (429)**: 暫停所有 API 請求 X 秒 (Shared Backoff)；Status Poller 也受限，但 Reconciler 的只讀查詢可豁免。
*   **Network Error**: 標記訂單為 `UNKNOWN` -> 交由 `Reconciler` 確認最終狀態。
*   **Insuffient Balance**: 標記為 `FAILED` -> 停止開新倉 -> 發送 Alert。

## 3. 安全與運維 (Security & Ops)

*   **密鑰管理**:
    *   支援從環境變數 (`OS Env`) 或加密的 `.env` 檔案讀取。
    *   程式碼中僅保存 `API_KEY` 的 Masked Version (e.g., `***abcd`) 用於日誌。
*   **Dry-Run Mode**:
    *   啟用時，Executor 攔截所有 `write` 操作並在啟動自檢時驗證「寫路徑全被阻擋」；否則拒絕啟動。
    *   `MockExchange` 類別模擬掛單與成交回報，更新虛擬餘額。
*   **Health Checks**:
    *   提供 `/health` 端點 (若有 Web Server) 或本地 `heartbeat` 文件，供外部監控工具 (如 K8s probe) 檢測。

## 4. 測試策略 (Testing Strategy)
*   **Unit Tests**: Config Validation, Kelly Calculation, Deduplication Logic.
*   **Integration Tests (Binance Testnet)**:
    *   Happy Path: 完整下單成交流程。
    *   Chaos: 模擬網路斷線、模擬 429、模擬部分成交。
    *   Reconciliation: 手動在交易所平倉，驗證系統是否能偵測並報警。

## 5. 配置與版本治理 (Config & Versioning)
- `settings.yaml` 必須包含 `config_version` 與 `config_hash`；對未知欄位 fail-fast。
- 部署時將 `config_hash` 寫入 `system_state` 以供審計與回溯。

## 6. 啟動與運行流程 (Startup & Runbook)
- **單一入口指令**: 例如 `python main.py --mode {live|dry-run|backfill-only}`，由 Orchestrator 依序啟動各模組；禁止人工逐檔啟動。
- **順序與責任**:
  1. `Main` 載入配置並做 Schema 驗證；記錄 `config_hash`/`config_version` 至 `system_state`。
  2. 初始化 SQLite（WAL、busy_timeout、TTL 清理與索引確認）。
  3. 立即執行 Reconciliation；若達 critical 閾值，進入安全模式（停開新倉，僅允許手動或自動修復）。
  4. Gap 回補：以 `cursor` + `BACKFILL_WINDOW` 抓歷史，經 Dedup 後入隊列；若超窗則安全停機並告警。
  5. 啟動 Monitor / Strategy / Executor / Notifier / Telemetry；綁定共享 Rate Limiter + CircuitBreaker。
  6. 進入主迴圈；關閉流程需先停止接收新訊號、刷新隊列、更新 `system_state`（cursor、config_hash）。
- **模式旗標**:
  - `live`: 實盤，允許對外寫入。
  - `dry-run`: 禁止對外寫入，使用 `MockExchange`，啟動時需驗證「寫路徑全阻斷」。
  - `backfill-only`: 僅做 Gap 回補與 Dedup，同步游標，不觸發下單，適用冷啟/修復。

### 6.1 Monitor / Backfill 配置參數
- `cursor_mode`: `block` (優先使用區塊高度) 或 `timestamp`（毫秒）；避免混用單位導致誤判 Gap。
- `backfill_window`: 允許的最大游標差距（超出即安全停機）。
- `dedup_ttl_seconds`: 去重快取保留時間（預設 24h）。
- `dedup_cleanup_interval_seconds`: 去重清理排程間隔（秒）。
- `enable_rest_backfill`: 是否啟用 REST 回補；啟用時 Monitor 會使用 Hyperliquid REST adapter。
- `hyperliquid_rest_base_url`: Hyperliquid info API base URL（預設 `https://api.hyperliquid.xyz/info`）。

### 6.2 Strategy / Risk 配置參數
- `max_stale_ms`: 最大可接受資料延遲（毫秒），超過即丟棄事件。
- `binance_filters`: 交易對風控設定，包含 `min_qty`, `step_size`, `min_notional`，下單前本地檢查以符合交易所限制。
  - 檢查對象為「實際下單的目標數量」(`order_qty = size_usd / price`)，避免因 Hyperliquid 原始成交量過小/過大造成誤判。

### 6.3 WebSocket 配置參數
- `enable_ws_ingest`: 是否啟動 Hyperliquid WS 監控。
- `hyperliquid_ws_url`: WS 端點。

---
*Last Updated: 2026-01-13 (v1.2)*
