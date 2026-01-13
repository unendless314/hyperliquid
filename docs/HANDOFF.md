# Hyperliquid Copy Trader - Handoff Notes (2026-01-13)

本文件供後續接手者快速了解尚未完成的重點工作。

## 1. 啟動/架構現況
- `main.py` 及 `core/*`、`utils/*` 目前為骨架（stub）；尚未實作邏輯。
- 專案結構已與 PRD/System Design 對齊：`main -> monitor -> strategy -> executor -> notifier/reconciler`。
- SQLite、Reconciliation、Gap 回補、Dedup、FSM 等功能需按 docs/PRD.md 與 docs/SYSTEM_DESIGN.md 實作。

## 2. 必須先做的事項（建議順序）
1) **依據文件實作啟動流程**：在 `main.py` 中完成 Schema 驗證 → SQLite 初始化 → Reconciliation → Gap 回補 → 啟動 Monitor/Strategy/Executor/Notifier。
2) **Config 驗證**：在 `utils/validations.py` 用 pydantic/自訂 schema 驗證 `settings.yaml`；自動計算 `config_hash`，缺省 `config_version` 時用 timestamp 補。
3) **SQLite 初始化**：建立 `processed_txs`, `trade_history`, `system_state` 表，啟用 WAL、busy_timeout、索引與 TTL 清理工作。
4) **Monitor**：實作 HL WebSocket、Gap Detector（BACKFILL_WINDOW）、REST 回補、Dedup Gatekeeper（寫入 processed_txs）。
5) **Strategy**：符號映射、風控（價格偏差%+USD、Binance Filters、資金水位）、倉位計算（fixed/proportional/kelly，含 freshness check）。
6) **Executor**：FSM (`PENDING/SUBMITTED/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED/REJECTED/UNKNOWN`)，idempotent `clientOrderId = hl-{tx_hash}-{nonce}`，共享 Rate Limiter + CircuitBreaker，處理 429/網路錯誤、超時。
7) **Reconciler**：週期對帳，分級動作（warn/critical + auto-resolve 可選），與 rate-limit 豁免只讀查詢。
8) **Notifier**：Telegram + rate limit + circuit breaker；log/metrics 需攜帶 `correlation_id`。
9) **Dry-run 模式**：啟動自檢，確保所有對外寫入被阻斷；使用 MockExchange。

## 3. 測試與驗證
- Unit：config schema、Kelly 計算、Dedup、價格偏差檢查、Binance filter 檢查。
- Integration（Binance testnet）：Happy path、429/backoff、WS 斷線重連+重播、部分成交+撤單、Reconciliation 偵測手動平倉。
- Smoke：`--mode dry-run` 啟動流程是否阻斷寫入；`backfill-only` 是否更新 cursor 而不下單。

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
- 先完成 config schema + SQLite 初始化 + 基本監聽/下單 Happy path，確保 end-to-end 可在 dry-run 跑通。
- 之後再加上 backoff/circuit breaker、對帳、gap 回補等強健性功能。

