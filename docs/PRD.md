# Hyperliquid Copy Trader - 產品需求文件 (PRD) v1.2

## 1. 專案概述 (Overview)
本專案旨在開發一套生產級別 (Production-Grade) 的自動化跟單交易系統。核心邏輯為「鏈上監聽、中心化執行」。
- **訊號源**: Hyperliquid (Target Wallet)。
- **執行端**: Binance USDT-M Futures。
- **核心目標**: 在確保**資金安全**與**系統強健性**的前提下，實現低延遲跟單。

## 2. 核心功能需求 (Functional Requirements)

### 2.1 監控與訊號捕捉 (Input)
- **資料完整性與游標追蹤 (Cursor Tracking)**:
  - 系統需記錄最後處理的 `block_height` 或 `tx_time` 至持久化儲存 (SQLite)。
  - **斷線恢復**: 重連時需檢查當前區塊高度與最後記錄的差異 (Gap Detection)。
    - 若差距 ≤ `BACKFILL_WINDOW` (例如最近 200 區塊)，以 REST 抓取補齊，並透過 Dedup 流程再次檢查。
    - 若差距 > `BACKFILL_WINDOW`，立即進入「安全停機 (Halt)」並發送警報，避免在資料不完整時繼續交易。
  - **毒藥訊息處理 (Poison Message)**: 對於無法解析或驗證失敗的訊息，應隔離記錄並繼續處理下一筆，避免卡死整個 Pipeline。
- **冪等性 (Idempotency)**:
  - 嚴格的去重機制：基於 `transaction_hash` + `event_index` 進行唯一性檢查。
  - 去重資料保存於 SQLite，需設置 TTL（例如 24 小時）與定期清理；重複訊號應被靜默丟棄 (Silent Drop)，僅在 Debug 模式下記錄。

### 2.2 跨所執行與倉位管理 (Execution & Management)
- **訂單生命週期 (Order FSM)**:
  - 支援完整狀態流轉：`PENDING` -> `SUBMITTED` -> `PARTIALLY_FILLED` -> `FILLED` / `CANCELED` / `EXPIRED` / `REJECTED` / `UNKNOWN` (網路中斷或回報缺失)。
  - **超時處理**: 若訂單長時間未成交 (Time-in-Force)，需自動撤單。
  - **Idempotent clientOrderId**: `clientOrderId = hl-{tx_hash}-{nonce}`，確保重試或斷線重送不會重複開倉。
- **定期對帳 (Periodic Reconciliation)**:
  - 系統需有一個獨立的背景任務 (Loop)，定期 (e.g., 每 1 分鐘) 比對「本地資料庫記錄的倉位」與「Binance 實際倉位」。
  - **分級動作**：偏差 < `warn_threshold` 記錄並通知；偏差 ≥ `critical_threshold` 發出 Critical Alert，可選擇自動平倉或補單 (Auto-Resolve)。
- **交易規則檢查 (Binance Filters)**:
  - 在發送訂單前，必須檢查：
    - `MinQty` (最小下單數量)
    - `StepSize` (數量精度)
    - `MinNotional` (最小名義價值，如 5 USDT)
  - 未通過檢查的訂單應在本地直接拒絕，不發送至交易所。

### 2.3 資金管理 (Money Management)
- **輸入資料新鮮度 (Freshness Check)**:
  - 若依賴外部數據（如大戶餘額 API、凱利參數），需檢查數據更新時間。若數據過期 (Stale > 1 hour)，禁止開新倉。
- **倉位計算模式**:
  - 支援 `Fixed Amount`, `Proportional`, `Kelly Criterion`。
  - **最大加倉限制 (Max Add-on)**: 針對單一幣種設定最大加倉次數或總金額，防止金字塔式加倉導致風險失控。

### 2.4 風險控制 (Risk Control)
- **價格滑點與保護**:
  - **價格基準**: 使用 Binance 的 **Mark Price (標記價格)** 進行比對。
  - **滑點限制**: 同時檢查百分比偏差與絕對偏差 (USD)。若任一超標 (`Max_Slippage%` 或 `Max_Slippage_USD`)，則放棄交易並記錄。
- **槓桿與保證金模式**:
  - 系統需明確指定並檢查每個幣種的模式（如：逐倉 Isolated 5x）。若設定不符，應嘗試調整或報錯。
- **模擬模式 (Dry-Run)**:
  - **隔離副作用**: 在 Dry-Run 模式下，嚴格禁止任何對外的「寫入」操作 (POST/DELETE)，並於啟動時進行自檢，若發現可寫路徑未被攔截則拒絕啟動。
  - **狀態模擬**: 需在記憶體中維護虛擬餘額與倉位，確保模擬測試的連續性與真實性。

### 2.5 可觀測性與儲存 (Observability & Storage)
- **資料庫 (SQLite)**:
  - 使用 SQLite 儲存交易歷史 (`trade_history`)、去重快取 (`processed_hashes`) 與系統狀態 (`system_state`)。
  - 啟用 WAL、設定 `busy_timeout`，採一執行緒一連線；索引：`processed_hashes(tx_hash)`、`trade_history(correlation_id)`；`processed_hashes` 需有 TTL 清理任務；每日備份並驗證可還原性。
- **關鍵指標 (Metrics)**:
  - 記錄 `E2E Latency` (鏈上成交 -> CEX 上鏈)、`Fill Ratio` (成交率)、`Slippage` (實際滑點)、`Gap Count`、`Replay Drops`、`Reconciliation Drift`、`429 Cooldown 次數`。
- **日誌與追蹤**:
  - 全鏈路 `correlation_id` 追蹤。
  - **敏感資料遮蔽 (Redaction)**: 日誌中嚴禁出現 API Key 或完整私鑰。

## 3. 配置與版本治理 (Config & Versioning)
- `settings.yaml` 必須包含 `config_version` 與 `config_hash`；對未知欄位應 fail-fast，避免拼字錯誤。
- 部署變更需記錄 `config_hash` 至 `system_state`，以利審計。

## 4. 啟動與運行流程 (Startup & Runbook)
- **單一入口指令**: 以單一指令啟動全流程，例如 `python main.py --mode {live|dry-run|backfill-only}`；禁止人工逐檔啟動以避免順序錯誤。
- **執行順序 (必須序列化)**:
  1. 載入 `settings.yaml` 並進行 Schema 驗證；記錄 `config_hash`。
  2. 初始化 SQLite（WAL、busy_timeout、TTL 清理排程）。
  3. 啟動即跑一次 Reconciliation；若偏差達 critical 閾值，進入安全模式（停開新倉）。
  4. Gap 回補：依 `cursor` + `BACKFILL_WINDOW` 抓歷史，經 Dedup 後入隊列；若超窗則安全停機 + 警報。
  5. 啟動 Monitor / Strategy / Executor（共用 Rate Limiter）與 Notifier/Telemetry。
  6. 進入主循環；關閉時刷新隊列並更新 `cursor`/`system_state`。
- **模式旗標**:
  - `live`: 正常實盤。
  - `dry-run`: 禁止任何對外寫入，使用虛擬餘額/倉位。
  - `backfill-only`: 僅執行 Gap 回補與 Dedup，不下單，用於冷啟或資料修復。

### 配置補充（Monitor / Backfill）
- `cursor_mode`: `block` 或 `timestamp`（毫秒）；避免混用單位導致錯誤 Gap 判斷。
- `backfill_window`: 允許的最大游標差距（超窗則安全停機）。
- `dedup_ttl_seconds`: 去重快取保留時間（預設 24h）；`dedup_cleanup_interval_seconds`: 清理週期（秒）。
- `enable_rest_backfill`: 是否啟用 Hyperliquid REST 回補；`hyperliquid_rest_base_url`: 回補 API base URL（預設官方 info 端點）。

### 配置補充（Strategy / Risk）
- `max_stale_ms`: 事件資料最大片延遲，超過即丟棄。
- `binance_filters`: 依交易對設定 `min_qty`, `step_size`, `min_notional`，下單前本地檢查。
  - 檢查使用的是「預計下單的目標數量」(`order_qty = size_usd / price`)，而非 Hyperliquid 的原始成交數量，避免錯誤拒單。

---
*Last Updated: 2026-01-13 (v1.2)*
