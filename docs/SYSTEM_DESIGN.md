# Hyperliquid Copy Trader - 系統設計規格書 (Technical Specification)

## 1. 專案目標
打造一個全自動、低延遲、高可靠性的 Hyperliquid 鏈上跟單系統。系統需能 7x24 小時監控目標錢包（大戶），並根據預設策略同步執行相同方向的交易。

## 2. 系統架構 (System Architecture)

採用模組化設計，確保各組件職責分離（Separation of Concerns）：

### 2.1 模組定義
- **Main (入口)**: `main.py`。負責初始化所有模組，啟動監控循環，處理系統信號（如優雅退出）。
- **Monitor (監聽模組)**: `core/monitor.py`。負責透過 WebSocket 建立與 Hyperliquid 的長連線。專注於即時解析目標錢包的 `userFills` 訊息。
- **Strategy (策略模組)**: `core/strategy.py`。系統的「大腦」。負責過濾訊號、計算倉位大小、管理交易白名單。
- **Executor (執行模組)**: `core/executor.py`。負責與您的錢包交互，執行 API 下單指令，處理手續費與滑點設定。
- **Utils (工具模組)**: 包含日誌系統 (`logger.py`)、環境變數載入與通知發送。

### 2.2 資料流向 (Data Flow)
1.  **Monitor** (Hyperliquid SDK) 收到 WebSocket 訊息 -> 解析為 `TradeEvent` (Raw Symbol)。
2.  **Strategy** 接收 `TradeEvent`：
    - **Symbol Mapping**: 將 Hyperliquid Symbol (如 `HYPE`) 轉換為 CEX Symbol (如 `HYPE/USDT`). 若無對應則 Drop。
    - 讀取 `settings.yaml` 判斷當前模式 (Fixed/Proportional/Kelly)。
    - 呼叫 `Executor` 查詢 **Binance** 帳戶餘額與資金佔用率。
    - **風控檢查**: (Soft/Hard Limit 針對 Binance 帳戶)。
    - 計算最終下單金額 `size_usd`。
    - 產生 `OrderAction` (標準化指令)。
3.  **Executor** (CCXT) 接收 `OrderAction` -> 調用 Binance API 下單 -> 返回結果。
4.  **Logger & Recorder**: 
    - **Logger**: 記錄技術日誌至 `logs/trading.log`。
    - **Recorder**: 將成交結果寫入 `trade_history.csv`。
    - **Notifier**: 若 Telegram 開啟，同步發送訊息通知。

## 3. 檔案結構 (File Structure)
```text
hyperliquid_copy_trader/
├── config/
│   ├── settings.yaml       
│   └── .env                
├── core/
│   ├── monitor.py          
│   ├── strategy.py         
│   └── executor.py         
├── utils/
│   ├── logger.py           
│   ├── mapper.py           
│   ├── recorder.py         # [New] 負責 CSV 檔案讀寫
│   └── notifications.py    
├── logs/                   
├── data/
│   └── trade_history.csv   # [New] 存放交易歷史數據
├── docs/
│   ├── PRD.md              
│   └── SYSTEM_DESIGN.md    
...
```

## 4. 關鍵技術細節 (Technical Details)

### 4.1 錯誤處理與防呆機制
- **WebSocket 斷線重連**:
    - **監控**: Monitor 需實作「心跳偵測 (Heartbeat)」，若超過預定時間（如 30秒）未收到伺服器回報，視為中斷。
    - **復原**: 採用指數退避 (Exponential Backoff) 機制嘗試重新連線，避免頻繁請求造成 IP 被封鎖。
- **異常捕獲**: 任何 API 請求失敗均需捕獲異常，避免程式崩潰，並透過日誌與 Telegram 警告。
- **餘額與水位檢查**: 每次執行 Strategy 前，必須先同步 Binance 的最新帳戶狀態。

### 4.2 安全性
- **私鑰管理**: 僅透過 `.env` 載入，程式運行中不以明文列印私鑰。
- **唯讀 vs 交易**: 建議監控功能與執行功能分開處理權限（若 API 支援）。

## 5. 概念驗證 (POC) 階段目標
1. 實現穩定連線並正確捕捉目標錢包的交易紀錄。
2. 在控制台 (Console) 正確顯示模擬下單的計算結果（不實際扣款）。
3. 完成日誌系統，確保所有操作可追溯。

---
*Last Updated: 2026-01-13*
