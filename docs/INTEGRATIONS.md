# External Integrations

## Hyperliquid

### Endpoints (Info API)
- Base URL: https://api.hyperliquid.xyz/info

### Minimal Required Endpoints
- POST /info (userFills)
  - Purpose: REST backfill of target wallet fills
  - Required: Yes

- POST /info (clearinghouseState)
  - Purpose: startup snapshot of target wallet positions
  - Required: Yes

### WebSocket
- Purpose: real-time fills for target wallet
- Subscription: official userFills/fills channel for target wallet
- Must support reconnect with backoff
- Required: Yes

### Rate Limits and Errors
- Treat 429 and network errors as transient; retry with backoff
- If backfill fails or gap exceeds backfill_window, enter HALT

## Binance USDT-M Futures

### Minimal Required Endpoints
- POST /fapi/v1/order
  - Purpose: submit order
  - Required: Yes

- GET /fapi/v1/order
  - Purpose: query order status
  - Required: Yes

- DELETE /fapi/v1/order
  - Purpose: cancel order
  - Required: Yes

- GET /fapi/v2/positionRisk
  - Purpose: fetch positions for reconciliation
  - Required: Yes

- GET /fapi/v1/premiumIndex
  - Purpose: mark price / funding / index
  - Required: Yes

- GET /fapi/v1/exchangeInfo
  - Purpose: symbol filters (min_qty, step_size, min_notional)
  - Required: Yes

### Filters and Constraints
- min_qty, step_size, min_notional per symbol
- position_mode must be one-way

### Error Handling
- 429: shared backoff with other API calls
- Insufficient balance: block new INCREASE orders, alert
- Unknown order status: mark UNKNOWN and resolve via reconciliation

## Time Sync and Retry Policy
- Use exchange server time to compute timestamp offset.
- Offset is refreshed at startup and then periodically (configurable, e.g. every 5-10 minutes).
- Respect recvWindow for Binance requests.
- Retry strategy: exponential backoff with jitter, capped max delay.
- Retry budget is configurable; exceeding the budget enters ARMED_SAFE or HALT with a reason code.
- 429 triggers shared cooldown for order submit and polling.

## Environment Switching
- Use a single config switch to select testnet vs mainnet.
- Base URLs and API keys must be bound to the selected environment.
- Do not allow mixed endpoints within one run.

## Symbol Mapping
- Maintain a deterministic mapping between Hyperliquid symbols and Binance symbols.
- Mapping must be explicit to avoid accidental mismatches.
- Mapping changes require a config update and restart.
- Mapping is stored in settings.yaml; one-to-one mapping only.

## Environment
- MVP uses Binance testnet for dry-run/integration testing.
- Production uses Binance USDT-M mainnet with guarded rollout.
