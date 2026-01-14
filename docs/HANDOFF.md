# Hyperliquid Copy Trader - Handoff Notes (2026-01-13)

本文件供後續接手者快速了解尚未完成的重點工作。

## 1. 啟動/架構現況（截至 2026-01-14）
- `main.py`：啟動/關閉流程完成，傳遞 mode (live/dry-run/backfill-only)，監控任務崩潰，掛載 Monitor/Strategy/Executor/Reconciler。可選 REST backfill / WS ingest（失敗時警告並關閉）。
- `core/monitor.py`：WS/REST ingest、Gap 檢測（BACKFILL_WINDOW、游標模式 block/timestamp）、Dedup Gatekeeper 落 SQLite、TTL 清理、gap 超窗/游標單位不符會 halt。無 client 時發 heartbeat。WS adapter 已接（無重連/backoff）。
- `core/strategy.py`：映射 + sizing（fixed_amount/proportional），風控：capital limits、雙閾值價格偏差、資料新鮮度 `max_stale_ms`、Binance filters（min_qty/step_size/min_notional，使用目標下單量 `order_qty = size_usd/price`）。
- `core/executor.py`：FSM stub但具 clientOrderId、dry-run/backfill-only 處理；ccxt submit bounded retries/backoff；circuit breaker + FAILED 記錄；poll 超時→UNKNOWN；trade_history 落 `order_qty`/`client_order_id`；circuit 開啟時會記錄 FAILED。
- `core/reconciler.py`：warn/critical 漂移檢測（以 notional 比較），critical + auto-close 時用 base size（contracts/positionAmt/amount/size，或 notional/mark_price 推導）下市價平倉，無法推導則通知並跳過；目前無 alert cooldown。
- `utils/validations.py`：集中預設/檢查（monitor/backfill、WS ingest、strategy risk、binance_filters、REST backfill 需 cursor_mode=timestamp）。
- `utils/hyperliquid_rest.py` / `utils/hyperliquid_ws.py`：REST/WS adapter；WS 無重連/backoff，REST 無內建 rate limit（docstring 已註明）。
- `utils/db.py`：schema 包含 processed_txs/trade_history/system_state；trade_history 新增 `client_order_id`、`order_qty`，含向後相容 ALTER；有 dedup TTL 清理 helper。
- Notifier 仍為 stdout stub；logging/metrics 尚未實作。
- 測試：pytest 全通（34/34），涵蓋 monitor ws/backfill/dedup、strategy 風控、executor ccxt retry、reconciler auto-close、validations；pytest-asyncio fixture scope 警告未處理（可加 `asyncio_default_fixture_loop_scope=function`）。

## 2. 必須先做的事項（建議順序）
1) **Monitor 實作**：HL WebSocket + REST 回補；游標/gap detector（BACKFILL_WINDOW）、Dedup Gatekeeper（寫入 processed_txs）。
2) **Strategy**：符號映射、風控（價格偏差%+USD、Binance Filters、資金水位/最大倉位）、倉位計算（fixed/proportional/kelly，含 freshness check）。
3) **Executor**：FSM (`PENDING/SUBMITTED/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED/REJECTED/UNKNOWN`)，idempotent `clientOrderId = hl-{tx_hash}-{nonce}`，共享 Rate Limiter + CircuitBreaker，處理 429/網路錯誤、超時；狀態落盤。
4) **Reconciler**：週期對帳，分級動作（warn/critical + auto-resolve 可選），只讀查詢豁免 rate limit。
5) **Notifier/觀測**：Telegram + rate limit/circuit breaker；結構化日誌含 `correlation_id`；基本 metrics。
6) **Dry-run / backfill-only 模式**：dry-run 阻斷對外寫入（MockExchange）；backfill-only 只更新游標不下單。
7) **啟動自檢與回補**：啟動時 Schema 驗證/DB 初始化已完成，但仍需接上 Reconciliation + Gap 回補流程（順序控制）與日誌/告警。

## 3. 測試與驗證
- Unit：config schema（已有）、DB 初始化（已有）、接續加入 Kelly 計算、Dedup、價格偏差檢查、Binance filter 檢查。
- Integration（Binance testnet）：Happy path、429/backoff、WS 斷線重連+重播、部分成交+撤單、Reconciliation 偵測手動平倉。
- Smoke：`--mode dry-run` 啟動流程是否阻斷寫入；`backfill-only` 是否更新 cursor 而不下單；服務任務崩潰是否觸發停機（框架已支持）。

## 4. 待決策/開放議題
- Gap 回補 REST 來源與 `BACKFILL_WINDOW` 具體數值。
- Kelly 參數來源與「新鮮度」判斷（預設 1h？）是否可配置。
- Metrics 與日誌格式（JSON vs text）、上報管道（暫列本地）。
- run_id 是否需要（目前未實作，可後續加入）。
- 游標語義：HL user_fills 無 block_height 時，目前以 timestamp_ms 作為 `last_processed_cursor`；若未來需要嚴格按區塊，需改為取得高度或獨立存時間/高度兩個游標。
- Reconciler alert noise：尚無 cooldown，漂移持續會每輪提醒；可加冷卻/去重。
- WS：無重連/backoff/backpressure；低頻可接受，若上線建議補強。

## 7. 新增待辦/提醒（2026-01-14）
- Orchestrator mode handling：`mode` 預設應明確為 `live`；未知值應在設定驗證階段 fail-fast。backfill-only 停止條件目前以任務名稱判斷，可改為持有 monitor task handle 比對以避免名稱變動風險。
- Dry-run/backfill 自檢：啟動時驗證外部寫入是否全阻斷（dry-run），backfill-only 確保僅同步 cursor 不觸發 Strategy/Executor。
- Cursor/Backfill hardening：REST 回補結果的毒藥訊息隔離、TTL 清理驗證、游標單位一致性報表；WS 重播續接測試。
## 5. 檔案導覽
- 需求/設計：`docs/PRD.md`, `docs/SYSTEM_DESIGN.md`, 本檔 `docs/HANDOFF.md`
- 設定：`config/settings.yaml`（僅示例，未 schema 檢查）、`config/.env.example`
- 入口與模組骨架：`main.py`, `core/monitor.py`, `core/strategy.py`, `core/executor.py`, `core/reconciler.py`
- 工具：`utils/logger.py`, `utils/validations.py`, `utils/notifications.py`, `utils/mapper.py`, `utils/recorder.py`, `utils/security.py`, `utils/hyperliquid_rest.py`, `utils/hyperliquid_ws.py`
- 目錄佔位：`data/.gitkeep`, `logs/.gitkeep`

## 6. 推薦的下一步
- 完成 Monitor/Strategy/Executor 的真實資料流 Happy Path：WS ingest + mapping/風控 + 下單 FSM stub，確保 end-to-end 可在 dry-run 跑通。
- 之後再加上 backoff/circuit breaker、對帳、gap 回補等強健性功能。
- 待辦提醒（nice-to-have）：
  - Notifier 尚未啟動為長駐任務；實作告警時請掛入事件管線。
  - SQLite 目前單連線；若未來高併發/多進程，需考慮每任務獨立連線或集中寫入 queue。
  - 游標語義：HL user_fills 無 block_height 時，目前以 timestamp_ms 作為 `last_processed_cursor`；若未來需要嚴格按區塊，需改為取得高度或獨立存時間/高度兩個游標。
  - Hyperliquid REST 回補 adapter 已接好；若要跑實流量，建議在 adapter 內加入輕量 rate limiting/backoff，以免打爆公共端點。
