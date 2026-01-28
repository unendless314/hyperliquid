# 故障排除與日常監控指南

**適用對象：** 日常運維人員  
**最後更新：** 2026-01-26

> 💡 **第一次使用？** 請先閱讀 [QUICKSTART.md](QUICKSTART.md)  
> 📚 **需要完整技術細節？** 請參考英文版 [RUNBOOK.md](RUNBOOK.md)
> 🔧 **配置檔提醒：** 本文以 `config/settings.prod.yaml` 為例，若使用 `config/settings.yaml` 請替換對應路徑。
> 🧭 **基準持倉提醒：** 若交易所帳戶已有外部/手動持倉，需先同步 baseline 才能避免 RECONCILE_CRITICAL。

---

## 📋 目錄

1. [日常監控清單](#日常監控清單)
2. [常見故障排除](#常見故障排除)
3. [安全模式升級](#安全模式升級)
4. [證據留存流程](#證據留存流程)

---

## 📊 日常監控清單

### 每日必做檢查（3 分鐘內）

目標：確保系統持續運行，沒有卡住、降級或異常。

#### 0) 啟動診斷（建議）
```bash
PYTHONPATH=src python3 tools/ops_startup_doctor.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json
```

#### 1) 確認安全狀態
```bash
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key IN ('safety_mode','safety_reason_code','safety_reason_message');"
```
**期望結果：**
- `safety_mode=ARMED_LIVE`（正常跟單狀態）
- 如果長期停在 `ARMED_SAFE`，代表無法加倉，需檢查原因

#### 2) 確認事件持續處理
```bash
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key IN ('last_ingest_success_ms','last_processed_timestamp_ms');"
```
**期望結果：**
- `last_ingest_success_ms` 接近當前時間（代表 ingest 正常拉取，即使沒有成交）
- `last_processed_timestamp_ms` 只在有成交事件時更新；低頻策略長時間不變是正常現象

#### 3) 檢查錯誤日誌
```bash
tail -n 80 logs/app.log | grep ERROR
tail -n 50 logs/metrics.log
```
**期望結果：**
- 沒有持續出現 ERROR / retry budget / rate limited

---

### 每週證據收集

```bash
PYTHONPATH=src python3 tools/ops_validate_run.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --exchange-time \
  --metrics-tail 5 \
  --output docs/ops_validation_run.txt
```

**用途：** 保留運行證據，用於審計和排錯

---

### 重要告警

⚠️ **立即處理的情況：**
- `safety_mode` 變成 `HALT` → 立刻停止並排查（見下方故障排除）
- `safety_reason_code` 持續是 `SNAPSHOT_STALE` → 快照過期問題未解決

---

## 🔧 常見故障排除

### 問題 1: 啟動後進入 ARMED_SAFE 狀態

**症狀：**
- 系統啟動成功，但 `safety_mode=ARMED_SAFE`
- 無法執行開倉操作

**診斷步驟：**
```bash
# 查看具體原因
sqlite3 data/hyperliquid_prod.db "SELECT value FROM system_state WHERE key='safety_reason_code';"
```

**常見原因與解決：**

| reason_code | 原因 | 解決方案 |
|-------------|------|---------|
| `SNAPSHOT_STALE` | 交易所快照過期 | 等待下次對賬，或檢查交易所 API |
| `RECONCILE_WARN` | 持倉偏差超過警告閾值 | 檢查實際持倉是否一致 |
| `BOOTSTRAP` | 系統剛啟動 | 手動升級到 ARMED_LIVE（見下節） |

---

### 問題 2: 系統進入 HALT 狀態（嚴重）

**症狀：**
- `safety_mode=HALT`
- 所有交易停止

**立即行動：**
1. **不要驚慌**，HALT 狀態下程式仍在運行，只是暫停交易
2. 查看 HALT 原因：
   ```bash
   sqlite3 data/hyperliquid_prod.db "SELECT value FROM system_state WHERE key='safety_reason_code';"
   ```

**根據原因處理：**
- `BACKFILL_WINDOW_EXCEEDED` → 見下方「問題 3」
- `RECONCILE_CRITICAL` → 嚴重持倉偏差，需人工核對
- `SCHEMA_VERSION_MISMATCH` → 資料庫版本不符，需重建 DB
- `EXECUTION_RETRY_BUDGET_EXCEEDED` → 訂單重試次數耗盡，檢查交易所連線

---

### 問題 3: BACKFILL_WINDOW_EXCEEDED（缺口超過回補窗口）

**症狀：**
- 日誌出現 `ingest_gap_exceeded`
- `safety_mode=HALT`, `reason_code=BACKFILL_WINDOW_EXCEEDED`

**原因：** ingest 拉取中斷超過回補窗口（以 last_ingest_success_ms 判定）
> 註：低頻策略「沒有成交」不會再因事件時間差而 HALT，事件時間差只會記錄 warning（log: ingest_event_gap_exceeded）。

**快速恢復流程：**

#### 手動詳細流程

**步驟 1：** 開啟 maintenance skip（暫時）
編輯 `config/settings.prod.yaml`：
```yaml
ingest:
  maintenance_skip_gap: true
```

**步驟 2：** 應用 maintenance skip
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action maintenance-skip \
  --reason-message "Maintenance skip applied"
```

**步驟 3：** Dry-run 驗證
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode dry-run \
  --config config/settings.prod.yaml \
  --run-loop
```
驗證後按 `Ctrl+C` 停止

**步驟 4：** 還原 maintenance skip
編輯 `config/settings.prod.yaml`：
```yaml
ingest:
  maintenance_skip_gap: false
```

**步驟 5：** 解除 HALT
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action unhalt \
  --reason-message "Manual unhalt after verification"
```

**步驟 6：** 重新啟動
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.prod.yaml \
  --run-loop
```

**風險提醒：**
- ⚠️ 缺口期間的事件不會被補齊
- 僅在您願意承擔缺口風險時使用
- 詳細技術說明請參考 [RUNBOOK.md](RUNBOOK.md#long-downtime-recovery-gap-exceeded)

---

## 🚀 安全模式升級

### 從 ARMED_SAFE 升級到 ARMED_LIVE

**前提條件（必須確認）：**
- ✅ Target wallet 持倉與預期一致
- ✅ 沒有未預期的掛單或未完成訂單
- ✅ 已確認快照不是 STALE 狀態

**升級命令：**
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action promote \
  --reason-message "Promote to ARMED_LIVE after verification" \
  --allow-non-halt
```

**注意事項：**
- 如果快照仍被判定過期（`SNAPSHOT_STALE`），系統可能在下次對賬時又降回 `ARMED_SAFE`
- 升級後不代表所有交易都允許，`replay_policy=close_only` 仍會限制 replay 事件只能平倉
- 允許加倉的條件：`safety_mode=ARMED_LIVE` **且** `is_replay=0`

---

## 📄 證據留存流程

### 升級後留存證據

每次手動升級安全模式後，建議留存證據：

```bash
PYTHONPATH=src python3 tools/ops_validate_run.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --exchange-time \
  --metrics-tail 5 \
  --output docs/ops_validation_run.txt
```

**證據包含：**
- 當前 `safety_mode` 和 `reason_code`
- 最後處理的事件時間戳
- Metrics 日誌尾部
- 交易所時間同步狀態

---

## 🔍 Replay Policy 重要提醒

即使系統升級到 `ARMED_LIVE`，仍需注意：

1. **Replay 事件限制：**
   - `decision.replay_policy=close_only` 會限制 replay 事件只能減倉
   - 這是為了防止歷史事件被重新處理時意外開倉

2. **允許加倉的條件：**
   - `safety_mode=ARMED_LIVE` **且**
   - `is_replay=0`（非 replay 事件）

3. **實際意義：**
   - 系統重啟後補齊的歷史事件只能平倉
   - 新的實時事件才能開倉

---

## 📞 需要更多幫助？

- **快速入門：** [QUICKSTART.md](QUICKSTART.md)
- **完整技術文檔：** [RUNBOOK.md](RUNBOOK.md)
- **運維驗證證據：** `docs/ops_validation_run.txt`
- **測試計劃：** [TEST_PLAN.md](TEST_PLAN.md)

---

**文檔版本：** 1.0  
**維護者：** 運維團隊
