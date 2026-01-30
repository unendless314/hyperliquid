# 跟單系統邏輯缺陷分析與修復計劃

## 🔴 問題確認

### 實際案例
**鏈上交易**：
- 交易哈希：`0xc13cc075c97b8fc5c2b60434407ae0020127005b647eae9765056bc8887f69b0`
- 時間：2026-01-29 11:02:59
- 訂單大小：**12.90529 BTC**
- 動作：Long BTC

**系統行為**：
- Hyperliquid API 返回此交易被拆成約 **86 個 fills**（成交記錄）
- 每個 fill 代表一次小額成交，例如：
  - Fill 1: +0.0002 BTC
  - Fill 2: +0.0025 BTC
  - Fill 3: +0.0050 BTC
  - ...
  - Fill 86: +0.0003 BTC

**當前系統處理邏輯**：
1. 系統對每個 fill 單獨觸發 `PositionDeltaEvent`
2. 對每個事件計算跟單量：
   - Fill 1: 0.0002 × 0.001 = 0.0000002 BTC → ❌ `filter_min_qty` (太小)
   - Fill 2: 0.0025 × 0.001 = 0.0000025 BTC → ❌ `filter_min_qty` (太小)
   - ...
   - Fill 86: 0.0003 × 0.001 = 0.0000003 BTC → ❌ `filter_min_qty` (太小)
3. **結果：86 個 fills 全部被拒絕**

**正確的邏輯應該是**：
- 聚合同一個 `tx_hash` 的所有 fills
- 計算總持倉變化：12.90529 BTC
- 計算跟單量：12.90529 × 0.001 = **0.01290529 BTC**
- ✅ 執行訂單（超過 Binance 最小交易量 0.001 BTC）

---

## 💥 根本原因

### 代碼層面

#### 1. Ingest 層：每個 fill 產生一個事件
**文件**：[`src/hyperliquid/ingest/adapters/hyperliquid.py`](file:///Users/linchunchiao/Documents/Python/hyperliquid/src/hyperliquid/ingest/adapters/hyperliquid.py#L310-L316)

```python
def _fills_to_events(self, fills: Iterable[dict]) -> List[RawPositionEvent]:
    events: List[RawPositionEvent] = []
    for fill in fills:  # 對每個 fill 單獨處理
        event = self._fill_to_raw(fill)
        if event is not None:
            events.append(event)
    return events
```

#### 2. Decision 層：對每個事件單獨計算
**文件**：[`src/hyperliquid/decision/strategy.py`](file:///Users/linchunchiao/Documents/Python/hyperliquid/src/hyperliquid/decision/strategy.py#L154-L179)

```python
def _compute_increase_qty(self, event: PositionDeltaEvent) -> tuple[float, Optional[str]]:
    base_qty = abs(event.delta_target_net_position)  # 使用單個 fill 的變化量
    # ...
    if sizing.mode == "proportional":
        qty = float(base_qty * sizing.proportional_ratio)  # 計算單個 fill 的跟單量
        return self._apply_max_qty(qty)
```

#### 3. Filter 層：小額訂單被過濾
每個小額跟單量都無法通過 `filter_min_qty` 檢查。

---

## 📋 修復方案

### 方案 A：Transaction-level Aggregation（推薦）

**核心思想**：在 Ingest 層聚合同一個 `tx_hash` 的所有 fills

**優點**：
- 邏輯清晰，符合實際業務語義（一筆交易 = 一個事件）
- Decision 層無需修改
- 更準確反映 Vault 的實際交易意圖

**缺點**：
- 需要在 Ingest 層增加聚合邏輯
- 可能延遲事件發送（需要等待同一 tx 的所有 fills）

**實現步驟**：
1. 修改 `_fills_to_events` 方法
2. 按 `tx_hash` 分組 fills
3. 聚合每組的持倉變化
4. 產生一個聚合後的 `PositionDeltaEvent`

---

### 方案 B：Time-window Batching

**核心思想**：在短時間窗口內（如 1 秒）聚合相同 symbol 的所有事件

**優點**：
- 不依賴 `tx_hash`，更通用
不僅能聚合同一交易的 fills，還能聚合短時間內的多筆交易

**缺點**：
- 增加系統複雜度（需要引入時間窗口機制）
- 延遲更明顯
- 可能聚合不相關的交易

---

## ✅ 建議採用：方案 A（Transaction-level Aggregation）

> [!IMPORTANT]
> **為什麼選擇方案 A**
> 
> 1. **符合業務語義**：一筆鏈上交易本來就應該當作一個決策單位
> 2. **實現簡單**：只需修改 Ingest 層，不影響 Decision 和 Execution
> 3. **無副作用**：不會聚合無關的交易

---

## ✅ 實作狀態（2026-01-30）
- 已在 ingest 層實作聚合：按 `(hash, coin)` 分組、按 `(time, tid)` 排序。
- `next_position` 使用最後一筆 fill 的 `startPosition + delta`（若最後一筆無效則 fallback 為 `start + total_delta`）。
- 最小單元測試已補：同 hash 多 fills、同 hash 多幣種。
- 缺失 hash 或 side 會記錄 warning；無效 side 不參與聚合計算。
- 後續只需實盤驗證與觀察 metrics（filter_min_qty 命中率是否下降）。

---

## 📝 實現計劃

### 修改文件

#### 1. [`src/hyperliquid/ingest/adapters/hyperliquid.py`](file:///Users/linchunchiao/Documents/Python/hyperliquid/src/hyperliquid/ingest/adapters/hyperliquid.py)

**修改 `_fills_to_events` 方法**：

```python
def _fills_to_events(self, fills: Iterable[dict]) -> List[RawPositionEvent]:
    """
    聚合同一個 (hash, coin) 的 fills，產生一個綜合的 Position Delta Event
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    missing_hash_count = 0
    for fill in fills:
        coin = str(fill.get("coin", ""))
        if coin.startswith("@") or coin not in self._config.symbol_map:
            continue
        hash_value = fill.get("hash")
        if not hash_value:
            missing_hash_count += 1
        tx_hash = str(hash_value or f"tid-{fill.get('tid', '')}")
        key = (tx_hash, coin)
        grouped.setdefault(key, []).append(fill)

    if missing_hash_count:
        self._logger.warning(
            "ingest_fill_missing_hash",
            extra={"missing_hash_count": missing_hash_count},
        )

    events: List[RawPositionEvent] = []
    for (tx_hash, coin), group in grouped.items():
        group_sorted = sorted(
            group,
            key=lambda item: (int(item.get("time", 0)), int(item.get("tid", 0))),
        )
        event = self._aggregate_fills_to_raw(group_sorted, tx_hash=tx_hash, coin=coin)
        if event is not None:
            events.append(event)

    return events
```

**新增 `_aggregate_fills_to_raw` 方法**：

```python
def _aggregate_fills_to_raw(self, fills: list[dict], *, tx_hash: str, coin: str) -> Optional[RawPositionEvent]:
    """
    將同一個 tx_hash 的多個 fills 聚合成一個 RawPositionEvent
    """
    if not fills:
        return None
    
    symbol = self._config.symbol_map[coin]
    start_pos = 0.0
    for fill in fills:
        if fill.get("startPosition") is not None:
            start_pos = float(fill.get("startPosition", 0.0))
            break
    total_delta = 0.0
    sides: set[str] = set()
    valid_side_count = 0
    
    for fill in fills:
        side = str(fill.get("side", "")).upper()
        if side not in {"B", "A"}:
            self._logger.warning(
                "ingest_fill_missing_side",
                extra={"tx_hash": tx_hash, "coin": coin, "side": side},
            )
            continue
        sides.add(side)
        try:
            size = float(fill.get("sz", 0.0))
        except (TypeError, ValueError):
            self._logger.warning(
                "ingest_fill_invalid_size",
                extra={"tx_hash": tx_hash, "coin": coin},
            )
            continue
        delta = size if side == "B" else -size
        total_delta += delta
        valid_side_count += 1

    if valid_side_count == 0:
        return None
    
    last_start = None
    last_delta = None
    for fill in reversed(fills):
        if fill.get("startPosition") is None:
            continue
        side = str(fill.get("side", "")).upper()
        if side not in {"B", "A"}:
            continue
        try:
            size = float(fill.get("sz", 0.0))
        except (TypeError, ValueError):
            continue
        last_start = float(fill.get("startPosition", 0.0))
        last_delta = size if side == "B" else -size
        break

    derived_next = start_pos + total_delta
    if last_start is not None and last_delta is not None:
        next_pos = last_start + last_delta
    else:
        next_pos = derived_next

    last = fills[-1]
    timestamp_ms = int(last.get("time", 0))
    event_index = int(last.get("tid", 0))
    
    # 計算 open/close components
    open_component = None
    close_component = None
    if start_pos > 0 > next_pos or start_pos < 0 < next_pos:
        close_component = abs(start_pos)
        open_component = abs(next_pos)
    
    return RawPositionEvent(
        symbol=symbol,
        tx_hash=tx_hash,
        event_index=event_index,
        prev_target_net_position=start_pos,
        next_target_net_position=next_pos,
        timestamp_ms=timestamp_ms,
        open_component=open_component,
        close_component=close_component,
    )
```

---

### 潛在風險與注意事項

> [!WARNING]
> **需要考慮的邊界情況**
> 
> 1. **多個 symbol 在同一個 tx**：目前已按 `(hash, coin)` 分組，可安全處理多幣種
> 2. **Fills 順序**：需要確保 fills 按時間順序處理
> 3. **部分 fills 失敗**：如果某些 fills 解析失敗，是否應該放棄整個 tx？
> 4. **WebSocket vs REST**：兩種數據源的 fills 格式是否一致？

**建議**：
- 如果一個 tx 包含多個 symbols，應該分別聚合每個 symbol
- 對解析失敗的 fills 記錄警告，但仍處理成功的 fills

---

## 🧪 驗證計劃

### 1. 單元測試

**新增測試**：`tests/unit/test_ingest_hyperliquid_adapter.py`

```python
def test_aggregate_fills_same_tx():
    """
    測試：同一個 tx 的多個 fills 應該被聚合成一個事件
    """
    # 模擬 12.9 BTC 的訂單被拆成 3 個 fills
    fills = [
        {"hash": "0xabc", "coin": "BTC", "sz": "5.0", "side": "B", "startPosition": "10.0", "time": 1000, "tid": 1},
        {"hash": "0xabc", "coin": "BTC", "sz": "3.9", "side": "B", "startPosition": "15.0", "time": 1001, "tid": 2},
        {"hash": "0xabc", "coin": "BTC", "sz": "4.0", "side": "B", "startPosition": "18.9", "time": 1002, "tid": 3},
    ]
    
    adapter = HyperliquidIngestAdapter(test_config)
    events = adapter._fills_to_events(fills)
    
    # 應該只產生 1 個事件
    assert len(events) == 1
    
    # 持倉變化應該是總和
    event = events[0]
    assert event.prev_target_net_position == 10.0
    assert event.next_target_net_position == 22.9  # 10 + 5 + 3.9 + 4
    assert event.tx_hash == "0xabc"
```

**執行命令**：
```bash
PYTHONPATH=src python3 -m pytest tests/unit/test_ingest_hyperliquid_adapter.py -v
```

---

### 2. 集成測試（可選）

目前 repo 沒有 `tests/integration/test_ingest.py`，請以現有整合測試為準或略過。

---

### 3. 手動驗證（真實數據）

**步驟**：
1. 修改代碼後重啟系統
2. 等待 Vault 地址下次有交易
3. 檢查資料庫中的事件數量

**驗證命令**：
```bash
# 檢查處理的事件數（應該減少）
sqlite3 data/hyperliquid_mainnet.db \
  "SELECT COUNT(*) FROM processed_txs WHERE timestamp_ms > (strftime('%s', 'now') - 86400) * 1000;"

# 檢查是否有訂單被創建
sqlite3 data/hyperliquid_mainnet.db \
  "SELECT symbol, side, qty, reduce_only FROM order_intents ORDER BY created_at_ms DESC LIMIT 5;"

# 檢查訂單執行結果
sqlite3 data/hyperliquid_mainnet.db \
  "SELECT symbol, status, filled_qty FROM order_results ORDER BY created_at_ms DESC LIMIT 5;"
```

**預期結果**：
- ✅ 事件數量大幅減少（從 86 個減少到 1-2 個）
- ✅ 當 Vault 有大額交易時，系統能夠創建並執行跟單訂單
- ✅ 跟單量符合預期（約為 Vault 變化量的 0.1%）

---

### 4. 回歸測試（歷史數據）

**測試當前已知的問題交易**：

**交易詳情**：
- TX: `0xc13cc075c97b8fc5c2b60434407ae0020127005b647eae9765056bc8887f69b0`
- 時間：2026-01-29 11:02:59
- 預期行為：應該產生 1 個事件，持倉變化約 +1.4 BTC

**執行命令**（使用回補功能測試）：
```bash
# 清空資料庫
mv data/hyperliquid_mainnet.db data/hyperliquid_mainnet.db.before_fix

# 回補該時間段的數據
PYTHONPATH=src python3 tools/ops_check_target_wallet.py \
  --config config/settings.yaml \
  --schema config/schema.json \
  --hours 24

# 檢查處理結果
sqlite3 data/hyperliquid_mainnet.db \
  "SELECT COUNT(*) as event_count, 
          COUNT(DISTINCT tx_hash) as unique_tx 
   FROM processed_txs 
   WHERE timestamp_ms BETWEEN 1769655779000 AND 1769655780000;"
```

**預期結果**：
- `unique_tx` = 1
- `event_count` = 1 （不再是 86 個）

---

## 📊 影響評估

### 變更範圍
- **修改文件**: 1 個（`hyperliquid.py`）
- **新增方法**: 1 個（`_aggregate_fills_to_raw`）
- **修改方法**: 1 個（`_fills_to_events`）

### 風險等級
- **中等風險**：修改核心數據處理邏輯
- **可逆性**：高（只要保留舊資料庫備份）

### 性能影響
- **Ingest 階段**：略微增加（需要額外的分組操作）
- **Decision 階段**：大幅減少（事件數量減少 10-100 倍）
- **整體性能**：預期提升（減少大量無效計算）

---

## 🎯 總結

**問題本質**：
- 系統對 Hyperliquid 的 fill-level 數據逐個處理，而不是 transaction-level 聚合
- 導致大額訂單被拆分後，每個小額 fill 都因低於最小交易量被過濾
- 最終結果：Vault 成功建倉，跟單系統完全沒有跟上

**修復方案**：
- 在 Ingest 層按 `tx_hash` 聚合 fills
- 產生一個綜合的持倉變化事件
- Decision 層無需修改，自然計算出正確的跟單量

**預期效果**：
- 事件數量減少 90%+
- 大額訂單能夠成功跟單
- 系統性能提升
