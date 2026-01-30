# Fill Aggregation Verification Report (Template)

## Purpose
Verify whether Hyperliquid fills are already aggregated (REST/WS), and determine if ingest-level aggregation is required.

## Run Metadata
- Date/Time (UTC):
- Operator:
- Environment (testnet/mainnet):
- Target wallet:
- Config path:
- Time window:

## Data Sources
- REST: userFillsByTime (aggregateByTime=false)
- WS: userFills subscription (if captured)
- Local DB: processed_txs / trade_history (optional)

## REST Evidence (Required)
Command:
```bash
PYTHONPATH=src python3 tools/ops_verify_fill_aggregation.py \
  --config config/settings.prod.yaml \
  --schema config/schema.json \
  --hours 48 \
  --raw-dump docs/fill_aggregation_raw_sample.json
```

Summary (paste JSON output):
```json
{}
```

Notes:
- Selected hash key:
- Groups with multiple fills:
- Mixed-side groups:
- Multi-coin same-hash groups:
- Ordering issues:
- StartPosition variance:

## WS Evidence (Optional)
Command (if captured):
```bash
# TODO: add WS capture command/output when available
```

Observations:
- WS payload structure:
- Same hash/coin appears across multiple WS messages:

## DB Cross-Check (Optional)
Evidence:
- processed_txs count:
- trade_history count:
- Any tx_hash present on-chain but missing in DB:

## Conclusion
Decision:
- [ ] REST/WS already aggregated; issue likely elsewhere (filters/symbol map).
- [ ] REST/WS returns multiple fills per tx; ingest aggregation needed.
- [ ] Inconclusive; collect more data.

Follow-ups:
- If aggregation is needed, consider grouping key (tx_hash, coin).
- Validate end position logic (use last fill if available).
- Add minimal tests for multi-fill and multi-coin cases.
