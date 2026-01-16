# Test Plan

## Minimal Test Set (MVP Priority)
1. Gap and Backfill
   - Simulate WS disconnect
   - Verify backfill + dedup produces consistent cursor

2. Restart Recovery
   - Stop and restart process mid-stream
   - Verify cursor and idempotency prevent duplicate orders

3. Partial Fill Handling
   - Simulate partial fills
   - Verify subsequent INCREASE decisions are not blocked

## Unit Tests
- Config validation
- Sizing logic
- Dedup logic

## Integration Tests
- Binance testnet
- WS reconnect and backfill

## Chaos Tests
- Network errors
- 429 rate limit

