# Hyperliquid 跟單交易程式 - 快速啟動指南

**最後更新：** 2026-01-26  
**版本狀態：** Epic 7.1/7.2 完成（持續運行功能已實現）

---

## ✅ 重要變更提醒

**持續運行功能已完成！**
- Epic 7.1（連續運行循環）於 2026-01-26 完成
- 必須使用 `--run-loop` 參數才能持續運行
- 舊版命令會導致「執行一次就退出」的問題

**配置檔提醒：**
- 本文以 `config/settings.prod.yaml` 為例，若使用 `config/settings.yaml` 請替換對應路徑。

**基準持倉提醒：**
- 若交易所帳戶已有外部/手動持倉，需先同步 baseline 才能避免 HALT。
- 建議使用 `tools/ops_sync_positions.py` 同步（詳見 RUNBOOK）。

---

## 🚀 標準啟動流程

### 步驟 1：驗證配置

```bash
# 驗證配置文件格式
PYTHONPATH=src python3 tools/validate_config.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json

# 計算配置哈希（用於驗證配置一致性）
PYTHONPATH=src python3 tools/hash_config.py \
  --config config/settings.prod.yaml
```

**輸出預期：** 
- 第一個命令應輸出 `OK`
- 第二個命令會輸出配置哈希值（請記錄下來）

---

### 步驟 2：啟動持續運行模式

```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.prod.yaml \
  --run-loop
```

**重要參數說明：**
- `--mode live`：實盤交易模式
- `--config config/settings.prod.yaml`：使用生產配置
- `--run-loop`：**啟用持續運行（必須添加！）**

**可選參數：**
```bash
# 自定義循環間隔（秒）
--loop-interval-sec 10

# 停用啟動測試事件
--no-emit-boot-event
```

---

### 步驟 3：啟動後檢查

```bash
# 0. 啟動診斷（建議）
PYTHONPATH=src python3 tools/ops_startup_doctor.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json

# 1. 檢查安全狀態
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key IN ('safety_mode','safety_reason_code','safety_reason_message');"

# 2. 檢查游標位置（確認事件持續處理）
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key LIKE 'last_processed_%';"

# 3. 檢查 metrics 日誌
tail -n 50 logs/metrics.log
```

**預期輸出：**
- `safety_mode` = `ARMED_SAFE` 或 `ARMED_LIVE`
- `last_processed_timestamp_ms` 持續更新（接近當前時間）
- Metrics 日誌顯示 `loop_heartbeat` 持續心跳

---

## 🔄 持續運行特性

### 運行模式
- ✅ **事件驅動**：持續監聽 Hyperliquid 鏈上事件
- ✅ **自動重連**：WebSocket 斷線後自動使用 REST 補齊缺口
- ✅ **安全閘門**：依照 safety_mode 自動控制交易行為
- ✅ **優雅關閉**：按 `Ctrl+C` 觸發優雅退出

### 安全模式說明
| 模式 | 行為 | 說明 |
|------|------|------|
| `ARMED_LIVE` | 允許開倉 + 平倉 | 正常跟單狀態 |
| `ARMED_SAFE` | 僅允許平倉 | 檢測到風險，降級保護 |
| `HALT` | 停止交易 | 嚴重錯誤，需人工介入 |

---

## 🛠️ 常見問題處理

### Q1: 程式執行一次就退出？
**原因：** 缺少 `--run-loop` 參數  
**解決：** 在啟動命令中加上 `--run-loop`

### Q2: 啟動後進入 ARMED_SAFE 狀態？
**原因：** 系統檢測到快照過期或持倉偏差  
**解決：** 
1. 檢查 `safety_reason_code`（執行步驟 3 的檢查命令）
2. 如果是 `SNAPSHOT_STALE`，可能需要等待下次對賬
3. 如果是 `RECONCILE_WARN`，檢查持倉是否一致

### Q3: 如何手動升級到 ARMED_LIVE？
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action promote \
  --reason-message "Manual promotion after verification" \
  --allow-non-halt
```

**警告：** 僅在確認持倉一致後執行！

### Q4: 遇到 BACKFILL_WINDOW_EXCEEDED 怎麼辦？
**原因：** 程式長時間離線，缺口超過回補窗口  
**處理流程：** 請參考 [TROUBLESHOOTING.md - 問題 3](TROUBLESHOOTING.md#問題-3-backfill_window_exceeded缺口超過回補窗口)

---

## 📊 日常監控清單

### 每日檢查（3 分鐘）
```bash
# 安全狀態
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key='safety_mode';"

# 事件處理進度
sqlite3 data/hyperliquid_prod.db "SELECT key, value FROM system_state WHERE key='last_processed_timestamp_ms';"

# 錯誤日誌
tail -n 50 logs/app.log | grep ERROR
```

### 每週證據收集
```bash
PYTHONPATH=src python3 tools/ops_validate_run.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --exchange-time \
  --metrics-tail 5 \
  --output docs/ops_validation_run.txt
```

---

## 📚 相關文檔

根據您的需求，選擇適合的文檔：

### 🚀 日常使用文檔（繁體中文）
- **[QUICKSTART.md](QUICKSTART.md)**（本文檔）
  - 適合：第一次使用者
  - 內容：基本啟動、概念理解、常見問題

- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** ⭐ 推薦
  - 適合：日常運維人員
  - 內容：故障排除、監控清單、安全模式升級

### 🔧 技術文檔（English）
- **[RUNBOOK.md](RUNBOOK.md)**
  - 適合：工程師、深度技術人員
  - 內容：完整運維流程、所有邊緣案例處理

### 📊 其他參考文檔
- **[CODE_REVIEW.md](CODE_REVIEW.md)**：代碼品質評估報告（8.5/10）
- **[TEST_PLAN.md](TEST_PLAN.md)**：測試計劃與驗證步驟
- **[ARCHITECTURE.md](ARCHITECTURE.md)**：系統架構設計

---

## 🎯 與舊版本的差異

| 項目 | 舊版（Epic 7.1 前） | 新版（Epic 7.1 後） |
|------|-------------------|-------------------|
| 運行模式 | 一次性執行 | 持續運行 |
| 啟動命令 | 無 `--run-loop` | 必須加 `--run-loop` |
| 斷線處理 | 程式退出 | 自動重連 + 補齊缺口 |
| HALT 行為 | 程式退出 | 程式持續運行，暫停交易 |

---

## ⚠️ 重要提醒

1. **生產環境啟動前：**
   - 確認使用 `config/settings.prod.yaml`（不是 testnet 配置）
   - 確認 `.env` 文件包含正確的 API key
   - 執行完整的 Go/No-Go 檢查（見 `docs/RUNBOOK.md`）

2. **目前限制：**
   - Replay 事件僅能平倉（`replay_policy=close_only`）
   - 開倉需要 `safety_mode=ARMED_LIVE` 且 `is_replay=0`

3. **緊急停止：**
   - 按 `Ctrl+C` 優雅關閉程序
   - 如需強制停止：`kill -9 <PID>`（不推薦，可能導致狀態不一致）

---

**技術支援：** 請參考 `docs/RUNBOOK.md` 的 Incident Response 章節
