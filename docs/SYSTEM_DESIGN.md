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
    *   **Gap Detector**: 比對「最新游標」與 DB 中的 `cursor`（預設 timestamp 毫秒）。
        * 若落差 ≤ `BACKFILL_WINDOW`（預設 900_000 ms / 15 分鐘），以 REST 回補並經過 Dedup 流程。
        * 若落差 > `BACKFILL_WINDOW`，觸發安全停機 (Halt) + Alert，避免在資料缺口下繼續交易。
    *   **Dedup Gatekeeper**: 查詢 SQLite `processed_txs` 表 (含 `tx_hash`,`event_index`,`symbol`)；若存在 -> Drop；若無 -> Insert 並傳遞。

*   **Strategy (Processing Layer)**:
    *   執行 Symbol Mapping (Hyperliquid -> Binance)。
    *   執行 Risk Checks (Price Deviation：百分比+USD 絕對值、Blacklist、Binance Filters)。
    *   計算 Position Size。
    *   限價單定價：基準價使用 Binance Mark Price 或最佳買賣中點（預設 Mark Price）；多單掛 `基準價 * (1 + price_offset_pct)`、空單掛 `基準價 * (1 - price_offset_pct)`，`price_offset_pct` 預設 0%~0.05%；下單前以基準價檢查滑點上限，超標即拒單。

*   **Executor (Action Layer)**:
    *   **Order FSM**: 管理訂單狀態 (Submit -> Monitor -> Finalize)，完整狀態集合：`PENDING` → `SUBMITTED` → `PARTIALLY_FILLED` → `FILLED` / `CANCELED` / `EXPIRED` / `REJECTED` / `UNKNOWN`（網路中斷或回報缺失）；`STUCK` 可作內部診斷用。
    *   **Smart Retry**: 實作帶有 Jitter 的指數退避 (Exponential Backoff)，與 Status Poller/Query 共用同一組 Rate Limiter/Backoff。
    *   **Idempotency Key**: `clientOrderId = hl-{tx_hash}-{nonce}`（nonce 可為本地單調遞增或隨機），確保重試或斷線重送不會重複開倉。

*   **Reconciler (Safety Layer)**:
    *   **啟動對帳**：服務啟動後先執行一次對帳；若漂移達 critical，進入安全模式（停開新倉），待人工確認或明確修復指令後再放行。
    *   **非同步迴圈**: 每 X 秒執行一次（常態對帳）。
    *   **Drift Check**: `abs(Binance_Position - DB_Position) > Threshold`?
    *   分級動作：< `warn_threshold` 記錄+通知；≥ `critical_threshold` 觸發 Critical Alert，可依設定選擇 `Force Sync` (多退少補/平倉) 或進安全模式。
*   **冷啟缺口處理 / 基線策略**：若啟動時游標缺口超窗或初始對帳達 critical，保持安全模式；需決定是否 `trust_local`：\
    - `trust_local=false`（預設）：啟動快照本地/遠端持倉，任一非零則維持安全模式，不處理後續訊號。\
    - `trust_local=true`：接受本地現有倉位為基線繼續跟單，即使遠端有歷史持倉，後續平倉/加倉訊號照常執行，漂移交由 Reconciler 監測。\
    基線未決前不處理後續平倉訊號，避免反向開倉。
*   **目標錢包持倉快照**：啟動時呼叫 Hyperliquid info API（如 `clearinghouseState`）取得目標錢包即時持倉；若快照失敗/過期，或在 `trust_local=false` 下遠端持倉非零，保持安全模式並提示人工決策。

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
    *   用於儲存 `last_processed_timestamp`（預設游標）、`config_hash`, `config_version` 等游標/審計數據；`last_processed_block` 僅作未來若有區塊高度訊號時的可選項。

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
    *   啟動 `OrderMonitor` 輪詢成交狀態 (受同一 Rate Limiter 管控)：
        * 取得部分成交 -> 更新為 `PARTIALLY_FILLED`，累計已成交量；在 TIF 內持續輪詢，超時則自動撤未成交部分。
        * TIF 尾段可配置「先撤單、後兜底」策略：先發撤單並確認撤單完成，依剩餘量改市價/IOC 補單；兜底前需通過滑點/殘量門檻，兜底後若仍未全成則落終態並告警。
        * 全數成交 -> `FILLED`。
        * 交易所回報撤單 / 主動撤單 / IOC 剩餘未成交 -> `CANCELED` 或 `EXPIRED`（依交易所語意，預設 IOC/FOK 逾時記為 EXPIRED）。
        * 交易所拒單（風控、餘額、步進不符等）-> `REJECTED`。
        * 輪詢超時或無回報 -> `UNKNOWN`，交由 Reconciler 後續處理。
4.  **Notifier**: 根據狀態變更發送 Telegram (需經過 Rate Limiter)。

### 2.2 錯誤處理流程
*   **Rate Limit (429)**: 暫停所有 API 請求 X 秒 (Shared Backoff)；Status Poller 也受限，但 Reconciler 的只讀查詢可豁免。
*   **Network Error**: 標記訂單為 `UNKNOWN` -> 交由 `Reconciler` 確認最終狀態。
*   **Insuffient Balance**: 標記為 `FAILED` -> 停止開新倉 -> 發送 Alert。

## 3. 安全與運維 (Security & Ops)

*   **密鑰管理**:
    *   支援從環境變數 (`OS Env`) 或加密的 `.env` 檔案讀取。
    *   日誌中不得輸出任何 API Key（即使遮罩也不輸出）；設定物件/錯誤訊息須過濾敏感欄位。
*   **Dry-Run Mode**:
    *   啟用時，Executor 攔截所有 `write` 操作並在啟動自檢時驗證「寫路徑全被阻擋」；否則拒絕啟動。
    *   `MockExchange` 類別模擬掛單與成交回報，更新虛擬餘額。
*   **Health Checks**:
    *   本系統統一採用本地 `heartbeat` 檔案：服務每隔 N 秒更新 `data/heartbeat`（timestamp），外部腳本或監控檢查檔案的更新時間是否在允許範圍內，超時即告警/重啟。若未來增加 Web 服務，可另行擴充 `/health` 端點，但現階段規格以 heartbeat 為準。

## 4. 測試策略 (Testing Strategy)
*   **Unit Tests**: Config Validation, Kelly Calculation, Deduplication Logic.
*   **Integration Tests (Binance Testnet)**:
    *   Happy Path: 完整下單成交流程。
    *   Chaos: 模擬網路斷線、模擬 429、模擬部分成交。
    *   Reconciliation: 手動在交易所平倉或開倉（與系統記錄方向/數量不符），驗證系統是否能偵測漂移並告警/觸發臨界動作。

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
- `cursor_mode`: **預設且建議使用 `timestamp`（毫秒）**；Hyperliquid userFills 僅提供時間戳，`block` 模式暫不支援現行資料源，僅作未來若有區塊高度訊號時的可選項。
- `backfill_window`: **預設 900_000 ms（15 分鐘）**；超出即 halt + alert。
- `dedup_ttl_seconds`: 去重快取保留時間（預設 24h）。
- `dedup_cleanup_interval_seconds`: 去重清理排程間隔（秒）。
- `enable_rest_backfill`: 是否啟用 REST 回補；啟用時 Monitor 會使用 Hyperliquid REST adapter。
- `hyperliquid_rest_base_url`: Hyperliquid info API base URL（預設 `https://api.hyperliquid.xyz/info`）。

### 6.2 Strategy / Risk 配置參數
- `max_stale_ms`: 最大可接受資料延遲（毫秒），超過即丟棄事件。
- `binance_filters`: 交易對風控設定，包含 `min_qty`, `step_size`, `min_notional`，下單前本地檢查以符合交易所限制。
  - 檢查對象為「實際下單的目標數量」(`order_qty = size_usd / price`)，避免因 Hyperliquid 原始成交量過小/過大造成誤判。
- Kelly sizing：可採用靜態配置（操作者週/月更新）；程式端僅檢查必要參數與範圍，不強制資料「新鮮度」。

### 6.3 WebSocket 配置參數
- `enable_ws_ingest`: 是否啟動 Hyperliquid WS 監控。
- `hyperliquid_ws_url`: WS 端點。
- `ws_retry_backoff_initial` / `ws_retry_backoff_max`: WS 重連 backoff（秒），預設 1 / 5。

### 6.4 Rate Limit / Circuit 配置參數
- `rate_limit_min_interval_sec`: 共享限速器的最小間隔（秒），用於下單提交與狀態輪詢，預設 0.1 秒。
- `circuit_failure_threshold`: 連續失敗達此次數即打開斷路器並進入冷卻，預設 3。
- `circuit_cooldown_seconds`: 斷路器冷卻時間（秒），預設 5 秒；冷卻期間提交與輪詢會被跳過或等待。

### 6.5 通知/觀測配置參數
- `telegram_enabled`, `telegram_bot_token`, `telegram_chat_id`, `telegram_base_url`, `telegram_dedup_cooldown_sec`: Telegram 告警設定與去重冷卻；未啟用時使用 stdout fallback。
- `metrics_dump_interval_sec`: 週期性將累積 metrics 以 stdout `[METRICS] {...}` 形式輸出，並同步 append 至 `logs/metrics.log`（滾動）；預設 60 秒。當前 metrics 包含 gap 超窗次數、backfill fetched 數量、WS error/recreate 次數，可後續接 Prometheus/OTLP。

### 6.6 Executor / TIF / 兜底配置參數
- `tif_seconds`: 限價單等待時間（預設 5–10 秒，可依市場/頻率調整）。
- `order_poll_interval_sec`: 輪詢成交狀態的間隔（預設 2–3 秒，與共享 Rate Limiter 協同）。
- `market_fallback_enabled`: 是否在 TIF 尾段改市價/IOC 兜底（預設開啟）。
- `market_fallback_threshold_pct`: 兜底觸發門檻，剩餘量低於原單多少百分比才改市價（例：10%）。
- `market_slippage_cap_pct`: 兜底前允許的最大滑點百分比（例：0.5%）；超過則不兜底，轉終態並告警。

---
*Last Updated: 2026-01-14 (v1.2.17 — trust_local 旗標預設 false；本地/遠端快照非零留安全模式；連續性模式交由 Reconciler 監測漂移)* 
