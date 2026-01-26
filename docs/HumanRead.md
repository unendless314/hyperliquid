# 操作流程（Human Read）

## 一、準備設定
- 確認 `.env` 內是主網 API key/secret
- 使用 `config/settings.prod.yaml` 作為啟動設定（不要用 testnet 的 `config/settings.yaml`）
- `filters_enabled=true`（已恢復即可）

## 二、啟動前檢查
```bash
PYTHONPATH=src python3 tools/validate_config.py --config config/settings.prod.yaml --schema config/schema.json
PYTHONPATH=src python3 tools/hash_config.py --config config/settings.prod.yaml
```

## 三、啟動常駐（持續運行模式）
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.prod.yaml \
  --run-loop
```

**重要說明：**
- `--run-loop`：啟用持續運行模式（必須加上，否則執行一次就會退出）
- 程式會持續監聽 Hyperliquid 事件，無需手動重啟
- 使用 Ctrl+C 可優雅關閉程序

## 四、啟動後檢查（必要）
```bash
sqlite3 data/hyperliquid_prod.db "select key, value from system_state where key in ('safety_mode','safety_reason_code','safety_reason_message');"
tail -n 50 logs/metrics.log
```

## 五、手動升級到 ARMED_LIVE（要允許加倉時才做）
前提：你已確認持倉狀態與預期一致，並接受風險。
- 確認 target wallet 持倉與預期一致
- 確認沒有未預期的掛單或未完成狀態

強制升級指令（從 ARMED_SAFE 進 ARMED_LIVE）：
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action promote \
  --reason-message "Promote to ARMED_LIVE after verification" \
  --allow-non-halt

注意：
- 這步驟來自 `docs/RUNBOOK.md` 的 Maintenance restart 段落。
- 如果快照仍被判定過期（SNAPSHOT_STALE），系統可能在下一次 reconcile 時又降回 ARMED_SAFE。
```

## 六、升級後留存證據
```bash
PYTHONPATH=src python3 tools/ops_validate_run.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --exchange-time \
  --metrics-tail 5 \
  --output docs/ops_validation_run.txt
```

## 七、重要提醒
- 即使升到 ARMED_LIVE，`decision.replay_policy=close_only` 仍會限制 replay 事件只能減倉。
- 允許加倉的條件是：`safety_mode=ARMED_LIVE` 且 `is_replay=0`。

## 八、連續多日運行的最小監控清單（每日檢查）
目標：確保持續運行期間沒有卡住、降級或異常下單。

### 每日必做（3 分鐘內）
1) 確認安全狀態
```bash
sqlite3 data/hyperliquid_prod.db "select key, value from system_state where key in ('safety_mode','safety_reason_code','safety_reason_message');"
```
- 期待：`safety_mode=ARMED_LIVE`（若長期停在 ARMED_SAFE，代表一直無法加倉）

2) 確認事件有持續前進
```bash
sqlite3 data/hyperliquid_prod.db "select key, value from system_state where key like 'last_processed_%';"
```
- 期待：時間戳與你當前時間接近（若停住代表 ingest 卡住）

3) 檢查最近錯誤
```bash
tail -n 80 logs/app.log
tail -n 50 logs/metrics.log
```
- 期待：沒有持續出現 ERROR / retry budget / rate limited

### 每週一次（留證據）
```bash
PYTHONPATH=src python3 tools/ops_validate_run.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --exchange-time \
  --metrics-tail 5 \
  --output docs/ops_validation_run.txt
```

### 重要提醒
- 如果 `safety_mode` 變成 `HALT`，立刻停止程式並依 RUNBOOK 處理。
- 如果 `safety_reason_code` 持續是 `SNAPSHOT_STALE`，代表快照過期問題沒有解決，請先排查再長期運行。

## 九、啟動時出現 BACKFILL_WINDOW_EXCEEDED（Gap Exceeded）怎麼辦
現象：
- log 出現 `ingest_gap_exceeded`
- `safety_mode=HALT`、`reason_code=BACKFILL_WINDOW_EXCEEDED`

最短處理流程（依 RUNBOOK 的 Long Downtime Recovery 簡化）：
1) 先把 `ingest.maintenance_skip_gap` 暫時打開（只做一次）
```yaml
ingest:
  maintenance_skip_gap: true
```

2) 套用 maintenance skip（會更新 cursor，但不改 safety_mode）
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action maintenance-skip \
  --reason-message "Maintenance skip applied"
```

3) 用 dry-run 啟動一次（驗證狀態）
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode dry-run \
  --config config/settings.prod.yaml \
  --run-loop
```
**注意：**驗證後請按 Ctrl+C 停止，確認無異常後再進入 live 模式

4) 把 `ingest.maintenance_skip_gap` 改回 `false`
```yaml
ingest:
  maintenance_skip_gap: false
```

5) 人工 unhalt 再進入 live 模式
```bash
PYTHONPATH=src python3 tools/ops_recovery.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --action unhalt \
  --reason-message "Manual unhalt after verification"
```

6) 再用 live 模式啟動（持續運行）
```bash
PYTHONPATH=src python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.prod.yaml \
  --run-loop
```

補充：
- 這個流程會把游標跳到現在，等於你接受「缺口期間的事件不追補」。
- 如果你願意承擔缺口風險，這是啟動最快的方法。
- 想要更簡潔：使用一鍵腳本（會暫時開啟 maintenance skip 並啟動）
```bash
./tools/start_live_with_maintenance_skip.sh
```
說明：
- 腳本會暫時把 `maintenance_skip_gap` 改成 `true` 後啟動。
- 程式結束後會自動還原原本的設定檔內容。
