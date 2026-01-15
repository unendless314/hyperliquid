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
  - **斷線恢復**: 重連時需檢查最新游標與最後記錄的差異 (Gap Detection)。
    - 預設游標模式為 **timestamp (毫秒)**，`BACKFILL_WINDOW` 預設 **900_000 ms (15 分鐘)**。
    - 若差距 ≤ `BACKFILL_WINDOW`，以 REST 抓取補齊，並透過 Dedup 流程再次檢查。
    - 若差距 > `BACKFILL_WINDOW`，立即進入「安全停機 (Halt)」並發送警報，避免在資料不完整時繼續交易。
  - **毒藥訊息處理 (Poison Message)**: 對於無法解析或驗證失敗的訊息，應隔離記錄並繼續處理下一筆，避免卡死整個 Pipeline。
- **冪等性 (Idempotency)**:
  - 嚴格的去重機制：基於 `transaction_hash` + `event_index` + `symbol` 進行唯一性檢查，避免跨交易對碰撞。
  - 去重資料保存於 SQLite，需設置 TTL（例如 24 小時）與定期清理；重複訊號應被靜默丟棄 (Silent Drop)，僅在 Debug 模式下記錄。

### 2.2 跨所執行與倉位管理 (Execution & Management)
- **訂單生命週期 (Order FSM)**:
  - 支援完整狀態流轉：`PENDING` -> `SUBMITTED` -> `PARTIALLY_FILLED` -> `FILLED` / `CANCELED` / `EXPIRED` / `REJECTED` / `UNKNOWN` (網路中斷或回報缺失)。
  - **超時處理**: 若訂單長時間未成交 (Time-in-Force)，需自動撤單。
  - **Idempotent clientOrderId**: `clientOrderId = hl-{tx_hash}-{nonce}`（nonce 為本地單調遞增/隨機），確保重試或斷線重送不會重複開倉。
- **熔斷器 (Circuit Breaker)**: 連續下單/查單失敗達閾值時，暫停相關請求並進入冷卻；冷卻結束再自動恢復，避免錯誤風暴。
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
  - 若依賴外部數據（如大戶餘額 API），需檢查數據更新時間；若數據過期 (預設 Stale > 1 hour)，禁止開新倉。僅在有配置外部餘額/參數來源時啟用；若採靜態人工更新（週/月）可停用此檢查。
  - Kelly 參數可採「人工週/月更新」的靜態配置，程式僅驗證存在與範圍，不強制 1 小時內更新。
- **倉位計算模式**:
  - 支援 `Fixed Amount`, `Proportional`, `Kelly Criterion`。
  - **最大加倉限制 (Max Add-on)**: 針對單一幣種設定最大加倉次數或總金額，防止金字塔式加倉導致風險失控。

### 2.4 風險控制 (Risk Control)
- **價格滑點與保護**:
  - **價格基準**: 使用 Binance 的 **Mark Price (標記價格)** 進行比對。
  - **滑點限制**: 以百分比偏差為主檢（`Max_Slippage%`）；若超標則放棄交易並記錄。絕對偏差 (USD) 為可選項，若未設定則不檢查。
- **槓桿與保證金模式**:
  - 系統需明確指定並檢查每個幣種的模式（如：逐倉 Isolated 5x）。若設定不符，應嘗試調整或報錯。
- **模擬模式 (Dry-Run)**:
  - **隔離副作用**: 在 Dry-Run 模式下，嚴格禁止任何對外的「寫入」操作 (POST/DELETE)，並於啟動時進行自檢，若發現可寫路徑未被攔截則拒絕啟動。
  - **狀態模擬**: 需在記憶體中維護虛擬餘額與倉位，確保模擬測試的連續性與真實性。

### 2.5 跟單一致性與倉位防護（新增）
- **啟動基線同步**: 程式啟動時必須先從 CEX 拉取當前實際倉位，作為本地倉位基線；後續平倉判斷與漂移計算都以此基線為準，避免重啟後誤判為空倉。
- **開/平倉判斷與限額**:
  - 若事件方向與現有倉位相反，視為平倉；平倉下單量不得超過「可平倉量 = 目前實際倉位」。`order_qty = min(目標量, 可平倉量)`，若可平倉量為 0 則跳過並告警。
  - 若事件方向與現有倉位同向，視為開倉/加倉，照原規則計算。
- **開倉失敗標記**: 若開倉/加倉下單失敗（風控拒單、網路錯等），需標記該 correlation_id/tx 為「未建倉」。後續對應的平倉訊號應跳過或僅告警，避免因缺失開倉而反向開倉。
- **部分成交處理**: FSM 必須落庫「已成交量」，後續平倉與對帳均以實際成交倉位為基準，不以原始目標量為基準。
- **TIF 末段兜底**: 限價單在 TIF 內未全成時，TIF 尾段執行「先撤單、後兜底」流程：先送撤單並確認撤單完成，再依剩餘量改用市價/IOC 補單；補單前仍需通過滑點與殘量門檻（如剩餘 < 原單比例門檻）以控制風險。
- **冷啟缺口防護 / 基線對齊**:
  - 啟動時若發現游標缺口超出 `BACKFILL_WINDOW`，或初始對帳漂移達 critical，必須進入安全模式（停開新倉，不處理後續訊號），需人工確認後再放行。
  - 基線策略僅允許 `assume_flat`: 忽略目標錢包既有倉位，從零倉位開始，只跟後續新成交；已知漏掉的開倉/加倉期間，對應的平倉訊號必須跳過或只告警，避免反向開倉。未顯式選擇前不得解除安全模式。
  - **目標錢包持倉快照**: 啟動時呼叫 Hyperliquid info API（如 `clearinghouseState`）取得目標錢包即時持倉；若發現遠端已有持倉，預設保持安全模式並提示操作者「待遠端清倉後再啟動」或手動介入（人工下單同步）後再解除安全模式。快照失敗或過期，同樣保持安全模式。
  - **本地持倉一致性提醒與選項**:
    - 預設 `trust_local=false`（安全模式）：啟動時對「本地/交易所持倉」與「Hyperliquid 目標錢包持倉」都做快照；若任一方持倉非零，保持安全模式，不啟動跟單，提示用戶處置（平倉或改用 trust_local）。
    - `trust_local=true`（連續性模式）：接受當前本地持倉為基線並繼續跟單，無論遠端是否有歷史持倉；漂移風險交由 Reconciler 監測，後續訊號照單執行。

#### 配置補充（Execution / TIF / 兜底）
- `tif_seconds`: 單筆訂單的限價等待時間（預設建議 5–10 秒，依市場與頻率調整）。
- `order_poll_interval_sec`: 下單後輪詢成交狀態的間隔（預設 2–3 秒，納入共享 Rate Limiter）。
- `market_fallback_enabled`: 是否在 TIF 尾段啟用市價/IOC 兜底（預設建議開啟）。
- `market_fallback_threshold_pct`: 兜底觸發門檻，剩餘量低於原單多少百分比才改市價（例：10%）。
- `market_slippage_cap_pct`: 兜底前的滑點上限（例：0.5%），超過則不執行兜底、轉終態並告警。

### 配置補充（Startup / Baseline）
- `trust_local`: 默認 false。\
  - false：啟動時快照本地/遠端持倉，任一非零即留在安全模式，不啟動跟單。\
  - true：接受本地持倉為基線繼續跟單，即使遠端有歷史持倉，漂移交由 Reconciler 監測。
- `hl_position_snapshot_enabled`: 是否在啟動時抓取 Hyperliquid 目標錢包持倉快照（預設 True，用於判定是否停留安全模式）。
- `hl_position_source_url`: Hyperliquid info API 端點（預設官方）。
- `remote_position_stale_sec`: 目標錢包快照可接受的最大片延遲；超過則保持安全模式。
- **對帳策略分工**:
  - **啟動對帳**：啟動後立即對一次帳，若漂移達 critical_threshold，進安全模式（停開新倉），待人工確認或明確修復指令後再放行。
  - **常態對帳**：背景循環自動對帳（例：每 1 分鐘），漂移達 critical_threshold 可依設定自動修復（平倉/補單）或進安全模式；warn 只告警。

### 2.6 可觀測性與儲存 (Observability & Storage)
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

-### 配置補充（Monitor / Backfill）
- `cursor_mode`: **預設且建議使用 `timestamp`（毫秒）**；Hyperliquid userFills 僅提供時間戳，`block` 模式暫不支援現行資料源，僅作未來若有區塊高度訊號時的可選項。
- `backfill_window`: 建議 900_000 ms（15 分鐘）；游標差距超過即安全停機並告警。
- `dedup_ttl_seconds`: 去重快取保留時間（預設 24h）；`dedup_cleanup_interval_seconds`: 清理週期（秒）。
- `enable_rest_backfill`: 是否啟用 Hyperliquid REST 回補；`hyperliquid_rest_base_url`: 回補 API base URL（預設官方 info 端點）。

### 配置補充（Strategy / Risk）
- `max_stale_ms`: 事件資料最大片延遲，超過即丟棄。
- `binance_filters`: 依交易對設定 `min_qty`, `step_size`, `min_notional`，下單前本地檢查。
  - 檢查使用的是「預計下單的目標數量」(`order_qty = size_usd / price`)，而非 Hyperliquid 的原始成交數量，避免錯誤拒單。
- Kelly 參數可作為靜態設定（操作者週/月更新），程式僅驗證存在與範圍，不強制動態新鮮度。
- **限價單定價規則**:
  - 基準價：使用 Binance 即時行情的標記價 (Mark Price) 或最佳買賣中點（Mid）；預設為 Mark Price。
  - 定價：做多掛 `基準價 * (1 + price_offset_pct)`；做空掛 `基準價 * (1 - price_offset_pct)`；`price_offset_pct` 預設 0%~0.05%，以提高成交概率但仍受滑點上限約束。
  - 風控：下單前以基準價檢查 `Max_Slippage%`（若有設定絕對值則一併檢查）；超標即拒單。

### 配置補充（WebSocket Ingest）
- `enable_ws_ingest`: 是否啟用 Hyperliquid WS 監控。
- `hyperliquid_ws_url`: WS 端點（預設官方）。

---
*Last Updated: 2026-01-14 (v1.2.14 — trust_local 旗標預設 false；本地/遠端快照非零留安全模式；連續性模式交由 Reconciler 監測漂移)* 
