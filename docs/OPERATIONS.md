# 運維記錄與操作指南

## 系統設定變更歷史

### 2026-02-03: 解決 WebSocket 斷線問題

**問題描述**：
- 交易程序在 2026-01-30 13:35 停止運行
- WebSocket 每 57 秒規律性斷線（Inactive）
- 疑似 Mac Mini Power Nap 或省電模式導致

**原因分析**：
- 系統啟用了 Power Nap (`powernap: 1`)
- 網路卡可能進入省電模式
- WebSocket 心跳包（20秒間隔）無法正常發送
- 詳細分析見：[斷線診斷報告](file:///.gemini/antigravity/brain/9cced445-33d3-43b7-bb1b-54e15745ad59/disconnection_analysis.md)

**解決方案**：
使用 `caffeinate` 防止系統睡眠

**原始系統設定**（保留備份）：
```bash
# 2026-02-03 備份
System Sleep Timer:    0 分鐘
Disk Sleep Timer:      10 分鐘
Display Sleep Timer:   10 分鐘
Power Nap:             1 (啟用)
```

**變更內容**：
- ✅ 使用 `caffeinate` 包裹程序啟動指令
- ⚠️ 未修改系統層級設定（保持原樣）

**驗證計畫**：
1. 使用 caffeinate 運行 24-48 小時
2. 監控 WebSocket 斷線情況
3. 如果問題解決，則採用此方案
4. 如果問題持續，再考慮修改系統設定

---

## 程序啟動方式

### 標準啟動（可能遇到斷線問題）

```bash
cd /Users/linchunchiao/Documents/Python/hyperliquid
source .venv/bin/activate
python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.yaml \
  --run-loop
```

### 推薦啟動（防止睡眠導致斷線）

```bash
cd /Users/linchunchiao/Documents/Python/hyperliquid
source .venv/bin/activate
caffeinate -dimsu python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.yaml \
  --run-loop
```

**caffeinate 參數說明**：
- `-d`: 防止顯示器睡眠
- `-i`: 防止系統閒置睡眠
- `-m`: 防止硬碟睡眠
- `-s`: 防止系統睡眠
- `-u`: 宣告使用者活躍

### 使用便利腳本啟動（推薦）

```bash
# 使用我們創建的啟動腳本
./tools/start_with_caffeinate.sh
```

---

## 診斷工具

### 檢查系統睡眠設定

```bash
./tools/diagnose_sleep_mode.sh
```

### 檢查程序運行狀態

```bash
# 檢查進程
ps aux | grep -E "python.*hyperliquid" | grep -v grep

# 查看最新日誌
tail -f logs/app.log

# 檢查最後心跳時間
tail -20 logs/app.log | grep loop_heartbeat
```

---

## 如需修改系統設定（備選方案）

⚠️ **注意**：以下操作會修改系統層級設定，執行前請確認

### 關閉 Power Nap

```bash
# 查看當前設定
pmset -g | grep powernap

# 關閉 Power Nap
sudo pmset -a powernap 0

# 恢復 Power Nap（如需回復）
sudo pmset -a powernap 1
```

### 關閉硬碟睡眠

```bash
# 查看當前設定
pmset -g | grep disksleep

# 關閉硬碟睡眠
sudo pmset -a disksleep 0

# 恢復硬碟睡眠（如需回復）
sudo pmset -a disksleep 10
```

---

## 監控與日誌

### 實時監控電源事件

```bash
# 在另一個終端執行
pmset -g log | grep -E "(Sleep|Wake|DarkWake)" >> ~/power_events_$(date +%Y%m%d).log
```

### 檢查日誌中的斷線模式

```bash
# 查看 WebSocket 斷線記錄
grep "ingest_ws_closed" logs/app.log | tail -20

# 分析斷線間隔
python3 -c "
import json
from dateutil import parser

with open('logs/app.log', 'r') as f:
    ws_events = [json.loads(line) for line in f if 'ingest_ws_closed' in line]
    
for i in range(max(0, len(ws_events)-5), len(ws_events)):
    print(ws_events[i]['ts'])
"
```

---

## 變更日誌

| 日期 | 操作 | 說明 | 狀態 |
|------|------|------|------|
| 2026-02-03 | 創建運維文檔 | 建立系統設定變更追蹤 | ✅ 完成 |
| 2026-02-03 | 創建啟動腳本 | `tools/start_with_caffeinate.sh` | ✅ 完成 |
| 2026-02-03 | 創建診斷腳本 | `tools/diagnose_sleep_mode.sh` | ✅ 完成 |
| 待定 | 使用 caffeinate 測試 | 驗證 24-48 小時 | ⏸️ 待執行 |

---

## 相關文件

- [系統架構文檔](../docs/ARCHITECTURE.md)
- [斷線診斷報告](file:///.gemini/antigravity/brain/9cced445-33d3-43b7-bb1b-54e15745ad59/disconnection_analysis.md)
- [啟動腳本](../tools/start_with_caffeinate.sh)
- [診斷腳本](../tools/diagnose_sleep_mode.sh)
