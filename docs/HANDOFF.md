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

## 4. 待決策/開放議題（更新 2026-01-14）
- 游標/回補：決定為 timestamp 主游標；`BACKFILL_WINDOW` 建議 900_000 ms（15 分鐘），超窗 halt + alert。
- Kelly：靜態手動更新，無過期告警。
- Metrics/日誌：維持 JSON stdout + metrics dump；健康指標為主，暫不導出。
- run_id：尚未實作（成本低，若需審計可後續加入）。
- Dry-run 外部寫阻斷：目前以禁 ccxt + MockExchange 為主，未做全局 HTTP/ccxt 攔截；若需更嚴格可後續加。

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

## 7. 狀態更新（2026-01-14）
- 已完成：WS ingest/REST 回補骨架、Dedup/TTL、毒藥訊息隔離+TTL、策略風控/filters、Executor FSM+重試+斷路器、Reconciler + auto-close + cooldown、模式護欄（dry-run/backfill-only 禁 ccxt）、Telegram/STDOUT Notifier（速率限制+去重+錯誤警示）、結構化日誌、輕量 metrics（gap/WS/backfill）+ 週期 stdout dump、WS 重連/backoff 可配置且有測試。
- 測試：pytest 43/43 綠（含 backfill-only smoke、poison handling、Telegram/notifier、WS 重連、dry-run guard 等）。

## 8. 待辦事項（按實用性）
### Must have（上線前）
1) Dry-run 外部寫入阻斷：實測/自檢確保所有對外 POST/DELETE（ccxt/http 客戶端）被攔截；新增 smoke test 覆蓋。
2) Metrics 充實：e2e latency、fill ratio、slippage、gap count、429/backoff、reconciliation drift；提供 Prometheus/OTLP 或更可用的輸出（現僅 stdout dump）。
3) Strategy 完整度：實作 Kelly sizing；滑點雙閾值行為/測試；binance filter 邊界案例。
4) Executor/Reconciler 韌性：新增 UNKNOWN/FAILED 原因分類、poll 專用 limiter（如需）、429/網路錯誤打點；Reconciler auto-close/漂移寫回 DB 或紀錄。
5) Cursor/Backfill 報表與修復：gap/游標單位異常的告警/報表；REST 回補缺口摘要；WS 重播續接的穩定測試。
6) CI/運維：移除 pytest-asyncio scope 警告；加 lint/format；模式未知值 fail-fast 已完成，保持。

### Nice to have
- Notifier 改用 message key（含 corr_id）去重，並支援更多管道。
- Metrics reset/多進程安全；週期 dump 可選寫檔/推送。
- 游標/回補可視化儀表（local dashboard）。
- run_id 寫入 system_state 以利審計/追蹤。
- Auto-close/修復動作的審計日誌與冷卻策略細化。

## 9. 文檔重大更新與暫停開發提示（2026-01-15）
- 規格更新：PRD/SYSTEM_DESIGN 已升級至 v1.2.17，核心變更：
  - 啟動基線只靠 `trust_local` 旗標（預設 false）。啟動會同時快照本地/CEX 持倉與 Hyperliquid 目標錢包持倉；任一非零且未設 `trust_local=true` 時，保持安全模式，不啟動跟單。
  - 移除自動 mirror 遠端倉位；`trust_local=true` 表示接受本地現有倉位為基線，漂移交由 Reconciler 監測。
  - 限價單定價：以 Binance Mark Price（或 Mid）為基準，加/減 `price_offset_pct`（預設 0~0.05%）；下單前必須做滑點檢查。
  - TIF 尾段兜底：先撤限價、確認撤單後，再依剩餘量市價/IOC 補單，受滑點與殘量門檻限制。
  - 部分成交與平倉防護：平倉量 clamp、缺失開倉/漏單時的平倉訊號需跳過，避免反向開倉。
  - 安全性：禁止日誌輸出 API Key（即便遮罩），強制 heartbeat 檔案存活探測，metrics dump 仍為 stdout+logs。
- 現有程式與新文檔有顯著差距（啟動流程、安全模式/快照、限價定價、兜底策略、trust_local 旗標等）。建議暫停新增功能與實盤操作，先依新規格整理重構計畫，再開發。
- 若需繼續開發，請先：對照新文檔列出差異 -> 訂定重構順序 -> 更新測試與 smoke -> 再放行。
