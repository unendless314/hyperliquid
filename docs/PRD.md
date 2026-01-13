# Hyperliquid Copy Trader - 產品需求文件 (PRD)

## 1. 專案概述 (Overview)
本專案旨在開發一套跨平台的自動化跟單交易系統。核心邏輯為「鏈上監聽、中心化執行」：
- **訊號源 (Signal Source)**: 實時監控 Hyperliquid 交易所上的目標錢包（Smart Money）。
- **執行端 (Execution Venue)**: 將訊號轉換後，透過 API 在中心化交易所 (CEX) 自動下單。**初期版本優先支援 Binance (幣安)**，未來架構保留擴充至 OKX, Gate.io 的能力。

## 2. 核心功能需求 (Functional Requirements)

### 2.1 監控與訊號捕捉 (Input)
- **即時推播 (WebSocket Push)**: 
  - 系統採用 WebSocket 長連線技術，接收 Hyperliquid 主動推播的 `UserFills` 事件。
  - **頻率與成本**: 無需主動輪詢，資料隨成交即時推送（延遲毫秒級），且無 API 請求成本。
- **連線可靠性**: 系統必須具備監聽連線狀態的能力，確保在網路波動斷線後能自動重新建立連線，並補抓斷線期間可能發生的訊號（若 API 支援）。
- **訊號過濾**: 白名單機制，僅處理我們感興趣且在 CEX 有對應交易對的幣種。

### 2.2 跨所執行與映射 (Output)
- **交易所介接**: 使用 `CCXT` 函式庫連接 Binance USDT-M 合約交易介面。
- **幣種映射 (Symbol Mapping)**:
  - **初期限制 (Initial Phase)**: 為確保系統穩定性，初期**僅支援 BTC** (Hyperliquid: `BTC` -> Binance: `BTC/USDT`)。
  - 系統需維護一份映射表，未來可擴充至 ETH, SOL 等主流幣。
  - **若無對應幣種或未在白名單內**: 系統自動忽略該訊號 (Skip) 並記錄 Log。

### 2.2 資金管理與倉位計算 (Money Management) - **核心重點**
系統需支援多種倉位計算模式，使用者可透過設定檔切換：

1.  **固定金額模式 (Fixed Amount)**:
    - 無論大戶下單金額大小，我方每筆交易固定下單 $X USD。
    - *適用場景*: 測試階段或小額驗證。

2.  **等比例模式 (Proportional)**:
    - 依據大戶下單金額佔其（估算）總資產的比例，應用於我方帳戶。
    - *公式*: `My_Order_Size = My_Balance * (Whale_Order_Size / Whale_Estimated_Balance)`

3.  **凱利公式模式 (Kelly Criterion)**:
    - 基於大戶的歷史勝率與盈虧比，動態計算最佳下注比例。
    - *公式*: $f = \frac{bp - q}{b}$
        - $f$: 下注比例 (需支援凱利乘數，如 0.5x Kelly 以降低風險)
        - $b$: 盈虧比 (Profit Factor)
        - $p$: 勝率 (Win Rate)
        - $q$: 敗率 (1-p)
    - *參數來源*: 使用者需在設定檔提供該大戶的歷史 $p$ 與 $b$ 值（可由回測報告取得）。

### 2.3 風險控制與防呆 (Risk Control)
- **資金佔用率監控 (Capital Utilization Monitoring)**:
  - **定義**: `已使用保證金 (Used Margin) / 帳戶總權益 (Account Value)`
  - **軟性警戒 (Soft Limit, e.g., 70%)**: 當佔用率超過此數值，發送黃色警告通知，提醒使用者注意水位。
  - **硬性限制 (Hard Limit, e.g., 90%)**: 當佔用率超過此數值，系統**強制拒絕**所有「新開倉 (Open)」請求，僅允許執行「平倉 (Close)」指令以釋放保證金。

- **餘額不足處理 (Insufficient Balance Handling)**:
  - 若計算出的 `Target Size` > `Available Margin`，系統採取**放棄交易 (Skip)** 策略。
  - 不進行降級下單，直接記錄 Error 日誌並發送通知，避免無效的小額開倉或破壞資金模型。

- **最小下單門檻**: 若計算出的金額低於交易所規定的最小下單額 (Min Order Size)，則放棄該筆交易。
- **最大持倉限制**: 設定單一幣種或總帳戶的最大持倉上限，超過則不再加倉。

### 2.4 通知與紀錄系統 (Notification & Logging)
- **即時通知 (Telegram - Optional)**:
  - 系統支援 Telegram Bot 通知。使用者可於設定檔決定是否開啟 (`enabled: true/false`)。
  - **通知事件**: 大戶交易偵測、跟單成功、跟單失敗（含原因）、資金水位警告、系統異常。
- **數據保存 (CSV - Local)**:
  - 為便於事後分析且降低複雜度，系統將所有完成的跟單交易結果記錄於本地 `trade_history.csv`。
  - **記錄欄位**: `Time`, `Target_Tx_ID`, `Symbol`, `Side`, `Price`, `Quantity`, `Fee`, `PnL_Estimate`, `Status` (Success/Failed/Skipped)。
- **日誌紀錄 (Logs)**:
  - 詳盡的日誌紀錄存於 `logs/trading.log`，包含 WebSocket 連線狀態、心跳包紀錄與所有計算過程，用於系統偵錯。

## 3. 非功能需求 (Non-Functional Requirements)
- **可靠性**: 具備斷線自動重連機制。
- **安全性**: API Private Key 必須加密儲存或僅透過環境變數讀取，不得明文寫入程式碼。
- **可維護性**: 程式碼需模組化，策略邏輯與執行邏輯分離。

---
*Last Updated: 2026-01-13*
