# Hyperliquid Copy Trader - Handoff Notes (2026-01-13)

本文件供後續接手者快速了解尚未完成的重點工作。

## 1. 啟動/架構現況
- `main.py` 已完成啟動骨架：讀取設定、驗證、初始化 SQLite、啟動 async lifecycle（Monitor/Strategy/Executor/Reconciler 鏈），支援優雅關閉、任務崩潰監控與 mode 傳遞（live/dry-run/backfill-only）。
- `core/monitor.py`：可接 ws/rest 客戶端；具 backfill stub、dedup 寫入 processed_txs，無客戶端時發送 heartbeat。
- `core/strategy.py`：基本映射與 sizing（fixed_amount、proportional，可從 notional_usd 或 size*price 推導）；風控尚未實作。
- `core/executor.py`：簡易 rate limiter + backoff scaffold；mode: backfill-only 直接丟棄、dry-run 記錄 DRY_RUN、live 為 stub 下單並記錄 SUBMITTED→FILLED；重試循環支援停機退出。
- `core/reconciler.py`：stub 心跳；`utils/notifications.py`：stub 通知器（未接通道，尚未作為獨立任務啟動）。
- `utils/validations.py` 具設定驗證與 `config_version`/`config_hash` 生成；`utils/db.py` 具 SQLite schema 初始化與 WAL/timeout 設定。
- 已有單元/管線測試（pytest 11/11）。

## 2. 必須先做的事項（建議順序）
1) **Monitor 實作**：HL WebSocket + REST 回補；游標/gap detector（BACKFILL_WINDOW）、Dedup Gatekeeper（寫入 processed_txs）。
2) **Strategy**：符號映射、風控（價格偏差%+USD、Binance Filters、資金水位/最大倉位）、倉位計算（fixed/proportional/kelly，含 freshness check）。
3) **Executor**：FSM (`PENDING/SUBMITTED/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED/REJECTED/UNKNOWN`)，idempotent `clientOrderId = hl-{tx_hash}-{nonce}`，共享 Rate Limiter + CircuitBreaker，處理 429/網路錯誤、超時；狀態落盤。
4) **Reconciler**：週期對帳，分級動作（warn/critical + auto-resolve 可選），只讀查詢豁免 rate limit。
5) **Notifier/觀測**：Telegram + rate limit/circuit breaker；結構化日誌含 `correlation_id`；基本 metrics。
6) **Dry-run / backfill-only 模式**：dry-run 阻斷對外寫入（MockExchange）；backfill-only 只更新游標不下單。
7) **啟動自檢與回補**：啟動時的 Schema 驗證、DB 初始化已完成，但仍需接上 Reconciliation + Gap 回補流程。

## 3. 測試與驗證
- Unit：config schema（已有）、DB 初始化（已有）、接續加入 Kelly 計算、Dedup、價格偏差檢查、Binance filter 檢查。
- Integration（Binance testnet）：Happy path、429/backoff、WS 斷線重連+重播、部分成交+撤單、Reconciliation 偵測手動平倉。
- Smoke：`--mode dry-run` 啟動流程是否阻斷寫入；`backfill-only` 是否更新 cursor 而不下單；服務任務崩潰是否觸發停機（框架已支持）。

## 4. 待決策/開放議題
- Gap 回補 REST 來源與 `BACKFILL_WINDOW` 具體數值。
- Kelly 參數來源與「新鮮度」判斷（預設 1h？）是否可配置。
- Metrics 與日誌格式（JSON vs text）、上報管道（暫列本地）。
- run_id 是否需要（目前未實作，可後續加入）。

## 5. 檔案導覽
- 需求/設計：`docs/PRD.md`, `docs/SYSTEM_DESIGN.md`, 本檔 `docs/HANDOFF.md`
- 設定：`config/settings.yaml`（僅示例，未 schema 檢查）、`config/.env.example`
- 入口與模組骨架：`main.py`, `core/monitor.py`, `core/strategy.py`, `core/executor.py`
- 工具骨架：`utils/logger.py`, `utils/validations.py`, `utils/notifications.py`, `utils/mapper.py`, `utils/recorder.py`, `utils/security.py`
- 目錄佔位：`data/.gitkeep`, `logs/.gitkeep`

## 6. 推薦的下一步
- 完成 Monitor/Strategy/Executor 的真實資料流 Happy Path：WS ingest + mapping/風控 + 下單 FSM stub，確保 end-to-end 可在 dry-run 跑通。
- 之後再加上 backoff/circuit breaker、對帳、gap 回補等強健性功能。
- 待辦提醒（nice-to-have）：
  - Notifier 尚未啟動為長駐任務；實作告警時請掛入事件管線。
  - SQLite 目前單連線；若未來高併發/多進程，需考慮每任務獨立連線或集中寫入 queue。
