# Hyperliquid Copy Trader - 產品需求文件 (PRD) v1.2

## 1. 專案概述 (Overview)
本專案旨在開發一套生產級別 (Production-Grade) 的自動化跟單交易系統。核心邏輯為「鏈上監聽、中心化執行」。
- **訊號源**: Hyperliquid (Target Wallet)。
- **執行端**: Binance USDT-M Futures。
- **核心目標**: 在確保**資金安全**與**系統強健性**的前提下，實現低延遲跟單。

## 2. 核心功能需求 (Functional Requirements)

### 2.1 監控與訊號捕捉 (Input)
- **資料完整性與游標追蹤 (Cursor Tracking)**:
  - 系統需記錄最後處理的游標至持久化儲存 (SQLite)。現行資料源以 `timestamp_ms` 為主；`block_height` 僅保留為未來擴充欄位（不作為現行游標依據）。
  - **斷線恢復**: 重連時需檢查最新游標與最後記錄的差異 (Gap Detection)。
    - 預設游標模式為 **timestamp (毫秒)**，`BACKFILL_WINDOW` 預設 **900_000 ms (15 分鐘)**。
    - 若差距 ≤ `BACKFILL_WINDOW`，以 REST 抓取補齊，並透過 Dedup 流程再次檢查（此回補的主要目的為**資料完整性、游標推進與審計**）。
    - 若差距 > `BACKFILL_WINDOW`，立即進入「安全停機 (Halt)」並發送警報，避免在資料不完整時繼續交易。
  - **游標語意與回補邊界 (Cursor Semantics)**:
    - 系統必須定義回補查詢的邊界，避免「同毫秒多筆」或 API 回傳順序差異造成漏單。
    - 建議採用「重疊回補」：回補起點使用 `backfill_start_ms = last_processed_timestamp_ms - cursor_overlap_ms`，並依靠 Dedup 去重，確保不漏事件。
    - 游標只能在事件「成功落庫」後前推；重啟後必須能以 DB 的 `system_state` 恢復游標並安全重跑（最多重複、不得漏掉）。
  - **回補訊號的交易策略 (Replay Policy)**:
    - 系統必須區分「即時訊號」與「回補訊號」。
    - **預設策略：回補不追補開倉/加倉（不增加曝險）**。回補訊號僅用於游標/去重/審計；必要時僅允許降低曝險的動作（例如 reduce-only 平倉/減倉）。
  - **毒藥訊息處理 (Poison Message)**: 對於無法解析或驗證失敗的訊息，應隔離記錄並繼續處理下一筆，避免卡死整個 Pipeline。
- **標準化輸入：淨持倉變化事件 (Position Delta Event)**:
  - 跟單決策不得僅依「Long/Short」或「Buy/Sell」判斷，必須結合目標錢包的**事件前/後淨持倉**來推導意圖。
  - 系統需維護「目標錢包淨持倉狀態」：啟動時先抓取持倉快照，後續以事件序列逐筆更新（若快照過期或追蹤信心不足，必須降級到 `ARMED_SAFE`）。
  - 每筆原始 fill 事件需被標準化為 `PositionDeltaEvent`，至少包含：
    - `prev_target_net_position` / `next_target_net_position`（目標錢包事件前/後淨持倉；One-way 淨值）
    - `delta_target_net_position = next - prev`
    - `action_type`: `INCREASE`（加倉）、`DECREASE`（減倉）、`FLIP`（穿越 0）
    - `open_component` / `close_component`（僅 `FLIP` 需要：拆成「平舊方向」與「開新方向」兩部分）
    - `is_replay`（是否為回補事件，供 `replay_policy` 門禁）
- **冪等性 (Idempotency)**:
  - 嚴格的去重機制：基於 `transaction_hash` + `event_index` + `symbol` 進行唯一性檢查，避免跨交易對碰撞。
  - 去重資料保存於 SQLite，需設置 TTL（例如 24 小時）與定期清理；重複訊號應被靜默丟棄 (Silent Drop)，僅在 Debug 模式下記錄。

### 2.2 跨所執行與倉位管理 (Execution & Management)
- **訂單生命週期 (Order FSM)**:
  - 支援完整狀態流轉：`PENDING` -> `SUBMITTED` -> `PARTIALLY_FILLED` -> `FILLED` / `CANCELED` / `EXPIRED` / `REJECTED` / `UNKNOWN` (網路中斷或回報缺失)。
  - **超時處理**: 若訂單長時間未成交 (Time-in-Force)，需自動撤單。
  - **Idempotent clientOrderId**:
    - `clientOrderId = hl-{tx_hash}-{nonce}`（nonce 為本地單調遞增/隨機）。
    - 必須將「事件 -> clientOrderId」映射持久化（DB），重啟後同一事件需能重建出相同的 `clientOrderId`，避免重啟導致冪等性失效。
- **熔斷器 (Circuit Breaker)**: 連續下單/查單失敗達閾值時，暫停相關請求並進入冷卻；冷卻結束再自動恢復，避免錯誤風暴。
- **定期對帳 (Periodic Reconciliation)**:
  - 系統需有一個獨立的背景任務 (Loop)，定期 (e.g., 每 1 分鐘) 比對「本地資料庫記錄的倉位」與「Binance 實際倉位」。
  - **分級動作**：偏差 < `warn_threshold` 記錄並通知；偏差 ≥ `critical_threshold` 發出 Critical Alert 並進入安全模式（停開新倉）。
  - **預設不自動修復**；若要啟用自動修復，預設僅允許 reduce-only 平倉/減倉（禁止自動補倉/加倉）。
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
- **持倉模式與下單語意 (Position Mode & Semantics)**:
  - **本系統僅支援 One-way Mode（單向持倉）**；不支援 Hedge Mode（雙向持倉）。
  - 啟動時必須檢查交易所帳戶持倉模式；若非 One-way，必須 fail-fast（拒絕啟動）並告警提示人工修正。
  - 平倉/減倉路徑必須使用 `reduceOnly=true`（或等價語意）以避免「空倉時誤開反向倉」。
- **模擬模式 (Dry-Run)**:
  - **隔離副作用**: 在 Dry-Run 模式下，嚴格禁止任何對外的「寫入」操作 (POST/DELETE)，並於啟動時進行自檢，若發現可寫路徑未被攔截則拒絕啟動。
  - **狀態模擬**: 需在記憶體中維護虛擬餘額與倉位，確保模擬測試的連續性與真實性。

### 2.5 跟單一致性與倉位防護（新增）
- **啟動基線同步**: 程式啟動時必須先從 CEX 拉取當前實際倉位，作為本地倉位基線；後續平倉判斷與漂移計算都以此基線為準，避免重啟後誤判為空倉。
- **跟單決策以 `PositionDeltaEvent` 為準**:
  - `INCREASE`: 視為「新增曝險」的開倉/加倉意圖；在 `ARMED_LIVE` 下依 sizing 計算並下單（仍受風控與 Binance filters 限制）。
  - `DECREASE`: 視為「降低曝險」的減倉/平倉意圖；若本地/交易所存在可平倉量（`closable_qty > 0`），則必須允許送出 `reduceOnly=true` 的平倉/減倉單；若 `closable_qty == 0` 則跳過並告警。
  - `FLIP`: 必須拆成兩段處理：
    - `close_component`: 等同 `DECREASE`（reduce-only，且僅在 `closable_qty > 0` 時執行）
    - `open_component`: 等同 `INCREASE`（只在 `ARMED_LIVE` 下執行，且受 `replay_policy`/安全模式限制）
- **Delta 映射到本地下單量（Sizing on Deltas）**:
  - 系統以目標錢包的「淨倉位變化」作為跟單基準，而非僅依單筆 Long/Short。
  - 預設 `delta_sizing_mode=event_usd`：以 `PositionDeltaEvent` 的 `open_component/close_component` 名義（USD）映射成本地目標名義，再換算成下單量（並以 `closable_qty` 封頂）。
  - 若使用 `Proportional` / `Kelly` 等模式，需明確定義比例基準（例如以目標 delta USD 作輸入），避免混用「目標總倉位」與「目標 delta」造成誤判。
- **回補訊號處置（追補策略）**:
  - 系統需能辨識回補訊號（WS 斷線後的 REST backfill、或重啟後補齊）。
  - **預設：回補訊號不觸發開倉/加倉**（避免追高、避免順序重放缺陷造成多開）。
  - 回補訊號若被允許觸發交易，**預設僅允許 reduce-only 平倉/減倉**，且仍需滿足滑點、filters、可平倉量等風控。
- **開倉失敗標記（更明確的平倉規則）**:
  - 若開倉/加倉下單失敗（風控拒單、網路錯等），需標記該 correlation_id/tx 為「未建倉」以便告警與審計。
  - **此標記不得成為「禁止平倉」的理由**：只要本地/交易所仍存在可平倉量（`closable_qty > 0`），收到相反方向訊號時必須允許送出 reduce-only 的平倉/減倉單（仍受滑點、filters、可平倉量等風控）。
  - 僅在 `closable_qty == 0`（本地/交易所確實無倉位）且判定該訊號屬於「不應開反向倉」的平倉意圖時，才跳過並告警，避免誤把“平倉訊號”當成反向開倉。
- **部分成交處理**: FSM 必須落庫「已成交量」，後續平倉與對帳均以實際成交倉位為基準，不以原始目標量為基準。
- **TIF 末段兜底**: 限價單在 TIF 內未全成時，TIF 尾段執行「先撤單、後兜底」流程：先送撤單並確認撤單完成，再依剩餘量改用市價/IOC 補單；補單前仍需通過滑點與殘量門檻（如剩餘 < 原單比例門檻）以控制風險。
- **冷啟缺口防護 / 基線對齊**:
  - 啟動時若發現游標缺口超出 `BACKFILL_WINDOW`，或初始對帳漂移達 critical，必須進入安全模式（停開新倉，不處理後續訊號），需人工確認後再放行。
  - 啟動策略由 `startup_policy` 決定（見下方 Startup / Baseline 配置）。無論何種策略，若 `closable_qty > 0`，系統必須允許 reduce-only 平倉/減倉以收斂風險；僅在 `closable_qty == 0` 時才允許跳過以避免誤開反向倉。
  - **目標錢包持倉快照**: 啟動時呼叫 Hyperliquid info API（如 `clearinghouseState`）取得目標錢包即時持倉；若發現遠端已有持倉，預設保持安全模式並提示操作者「待遠端清倉後再啟動」或手動介入（人工下單同步）後再解除安全模式。快照失敗或過期，同樣保持安全模式。
- **本地持倉一致性提醒與選項**:
    - `startup_policy=manual_clear_required`（預設，安全模式）：啟動時對「本地/交易所持倉」與「Hyperliquid 目標錢包持倉」都做快照；若任一方持倉非零，保持安全狀態，不啟動跟單，提示用戶處置（平倉/對齊後再放行）。
    - `startup_policy=continuity`（連續性模式）：接受當前本地/交易所持倉為基線並放行，即使遠端有歷史持倉；漂移風險交由 Reconciler 監測，後續訊號照單執行（回補仍不得追補開倉/加倉）。

#### 配置補充（Execution / TIF / 兜底）
- `tif_seconds`: 單筆訂單的限價等待時間（預設建議 5–10 秒，依市場與頻率調整）。
- `order_poll_interval_sec`: 下單後輪詢成交狀態的間隔（預設 2–3 秒，納入共享 Rate Limiter）。
- `market_fallback_enabled`: 是否在 TIF 尾段啟用市價/IOC 兜底（預設建議開啟）。
- `market_fallback_threshold_pct`: 兜底觸發門檻，剩餘量低於原單多少百分比才改市價（例：10%）。
- `market_slippage_cap_pct`: 兜底前的滑點上限（例：0.5%），超過則不執行兜底、轉終態並告警。

### 配置補充（Startup / Baseline）
- `startup_policy`: 啟動策略（預設 `manual_clear_required`，保守模式）。
  - `manual_clear_required`（保守預設）：啟動時快照本地/交易所持倉與目標錢包持倉；若任一非零、快照失敗/過期、游標缺口超窗、或啟動對帳達 critical，則停在安全狀態（停開新倉），必須人工處置後才能放行。
  - `continuity`（連續性，跟後續 delta）：接受本地/交易所現有倉位為基線並放行；不追補目標錢包既有倉位，但會依後續 `PositionDeltaEvent` 跟隨淨持倉變化：
    - `DECREASE`（目標減倉）若本地為空倉可忽略；`FLIP` 只跟隨其 `open_component`（例如目標從多翻空，會跟到翻空後新增的空倉部分）。
    - 回補事件仍受 `replay_policy` 限制（預設不追補開倉/加倉）。
  - `follow_only_new`（只跟新建倉）：不追跟目標錢包既有倉位，且在偵測到目標當前持倉非零時維持 `ARMED_SAFE`；待目標回到零倉位（清倉）後才允許進入 `ARMED_LIVE` 開始跟單。
- `hl_position_snapshot_enabled`: 是否在啟動時抓取 Hyperliquid 目標錢包持倉快照（預設 True，用於判定是否停留安全模式）。
- `hl_position_source_url`: Hyperliquid info API 端點（預設官方）。
- `remote_position_stale_sec`: 目標錢包快照可接受的最大片延遲；超過則保持安全模式。
- **啟動狀態機（Startup State Machine）**:
  - 狀態：`BOOTSTRAP` → `SNAPSHOT_CHECK` → `RECONCILE_ON_START` → `BACKFILL_CATCHUP` → `ARMED_SAFE` / `ARMED_LIVE` / `HALT`。
  - `ARMED_SAFE`（安全就緒但受限）：禁止任何增加曝險的動作（開倉/加倉）；僅允許只讀查詢、撤單、以及可選的 reduce-only 平倉/減倉（降低曝險）。
  - `ARMED_LIVE`（正常跟單）：允許即時訊號觸發開/平倉；回補訊號仍受 `replay_policy` 限制（預設不追補開倉/加倉）。
  - `HALT`（硬停機）：例如游標缺口超窗、資料源不可用、或關鍵風控/帳戶狀態不符（如非 One-way），停止自動交易並告警。
- **對帳策略分工**:
  - **啟動對帳**：啟動後立即對一次帳，若漂移達 critical_threshold，進安全模式（停開新倉），待人工確認或明確修復指令後再放行。
  - **常態對帳**：背景循環自動對帳（例：每 1 分鐘），漂移達 critical_threshold 預設進安全模式；若顯式啟用自動修復，預設僅允許 reduce-only 平倉/減倉（禁止自動補倉/加倉）；warn 只告警。

### 2.6 可觀測性與儲存 (Observability & Storage)
- **資料庫 (SQLite)**:
  - 使用 SQLite 儲存交易歷史 (`trade_history`)、去重快取 (`processed_txs`) 與系統狀態 (`system_state`)。
  - 啟用 WAL、設定 `busy_timeout`，採一執行緒一連線；索引：`processed_txs(tx_hash)`、`trade_history(correlation_id)`；`processed_txs` 需有 TTL 清理任務；每日備份並驗證可還原性。
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
  3. 進入 `SNAPSHOT_CHECK`：取得本地/交易所持倉與目標錢包持倉快照（依 `startup_policy` 決定是否放行）。
  4. 進入 `RECONCILE_ON_START`：啟動即跑一次對帳；若偏差達 critical 閾值，進入 `ARMED_SAFE`（停開新倉；僅允許撤單、查詢、以及可選的 reduce-only 平倉/減倉）。
  5. 進入 `BACKFILL_CATCHUP`：依 `cursor` + `BACKFILL_WINDOW` 抓歷史，經 Dedup 後補齊游標/狀態並入隊列；回補訊號的下單行為由 `replay_policy` 控制（預設不追補開倉/加倉）。
  6. 啟動 Monitor / Strategy / Executor（共用 Rate Limiter）與 Notifier/Telemetry。
  7. 進入 `ARMED_SAFE` 或 `ARMED_LIVE` 主循環；關閉時刷新隊列並更新 `cursor`/`system_state`。
- **模式旗標**:
  - `live`: 正常實盤。
  - `dry-run`: 禁止任何對外寫入，使用虛擬餘額/倉位。
  - `backfill-only`: 僅執行 Gap 回補與 Dedup，不下單，用於冷啟或資料修復。

### 配置補充（Monitor / Backfill）
- `cursor_mode`: **預設且建議使用 `timestamp`（毫秒）**；Hyperliquid userFills 僅提供時間戳，`block` 模式暫不支援現行資料源，僅作未來若有區塊高度訊號時的可選項。
- `backfill_window`: 建議 900_000 ms（15 分鐘）；游標差距超過即安全停機並告警。
- `cursor_overlap_ms`: 回補重疊窗口（毫秒）。回補起點使用 `last_processed_timestamp_ms - cursor_overlap_ms`，並依靠 Dedup 去重以避免漏單（建議 1_000–5_000 ms）。
- `dedup_ttl_seconds`: 去重快取保留時間（預設 24h）；`dedup_cleanup_interval_seconds`: 清理週期（秒）。
- `enable_rest_backfill`: 是否啟用 Hyperliquid REST 回補；`hyperliquid_rest_base_url`: 回補 API base URL（預設官方 info 端點）。
- `replay_policy`: 回補訊號處置策略（預設 `close_only`）。
  - `close_only`: 僅允許 reduce-only 的平倉/減倉；禁止回補開倉/加倉。
  - `off`: 回補訊號完全不觸發交易（僅游標/審計）。

### 配置補充（Strategy / Risk）
- `max_stale_ms`: 事件資料最大片延遲，超過即丟棄。
- `binance_filters`: 依交易對設定 `min_qty`, `step_size`, `min_notional`，下單前本地檢查。
  - 檢查使用的是「預計下單的目標數量」(`order_qty = size_usd / price`)，而非 Hyperliquid 的原始成交數量，避免錯誤拒單。
- `position_mode`: Binance 持倉模式。本系統僅支援 `one_way`；若不符需拒絕啟動並提示人工修正。
- `follow_model`: 跟單模型（預設 `position_delta`）。
  - `position_delta`: 以目標錢包淨持倉的變化事件 `PositionDeltaEvent` 作為交易決策依據（避免僅依 Long/Short 誤判）。
- `delta_sizing_mode`: Delta 映射策略（預設 `event_usd`）。
  - `event_usd`: 以目標 `open_component/close_component` 的名義（USD）作為輸入，套用本地 sizing 後換算下單量；平倉/減倉必須 `reduceOnly=true` 且以 `closable_qty` 封頂。
- Kelly 參數可作為靜態設定（操作者週/月更新），程式僅驗證存在與範圍，不強制動態新鮮度。
- **限價單定價規則**:
  - 基準價：使用 Binance 即時行情的標記價 (Mark Price) 或最佳買賣中點（Mid）；預設為 Mark Price。
  - 定價：做多掛 `基準價 * (1 + price_offset_pct)`；做空掛 `基準價 * (1 - price_offset_pct)`；`price_offset_pct` 預設 0%~0.05%，以提高成交概率但仍受滑點上限約束。
  - 風控：下單前以基準價檢查 `Max_Slippage%`（若有設定絕對值則一併檢查）；超標即拒單。

### 配置補充（WebSocket Ingest）
- `enable_ws_ingest`: 是否啟用 Hyperliquid WS 監控。
- `hyperliquid_ws_url`: WS 端點（預設官方）。

---
*Last Updated: 2026-01-15 (v1.2.19 — 引入 PositionDeltaEvent 作為標準化輸入；continuity 以淨持倉變化（含 flip 拆分）跟隨後續訊號；以 follow_model/delta_sizing_mode 取代舊的 close_on_opposite_mode)* 
