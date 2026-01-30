# Fill Aggregation Verification Report

## Purpose
Verify whether Hyperliquid fills are already aggregated (REST/WS), and determine if ingest-level aggregation is required.

## Run Metadata
- Date/Time (UTC): 2026-01-30
- Operator: codex
- Environment (testnet/mainnet): mainnet
- Target wallet: 0x45e7014f092c5f9c39482caec131346f13ac5e73
- Config path: config/settings.yaml
- Time window: 2026-01-28 03:30:39 → 2026-01-30 03:30:39 (UTC)

## Data Sources
- REST: userFillsByTime (aggregateByTime=false)
- WS: userFills subscription (non-snapshot capture attempted; no messages in 90s window)
- Local DB: processed_txs / trade_history

## REST Evidence (Required)
Command:
```bash
PYTHONPATH=src python3 tools/ops_verify_fill_aggregation.py \
  --config config/settings.yaml \
  --schema config/schema.json \
  --hours 48 \
  --max-fills 20000 \
  --raw-dump docs/archive/evidence/fill_aggregation_raw_48h.json \
  --raw-limit 20000
```

Summary (JSON output):
```json
{
  "wallet": "0x45e7014f092c5f9c39482caec131346f13ac5e73",
  "rest_url": "https://api.hyperliquid.xyz/info",
  "since_ms": 1769571039244,
  "until_ms": 1769743839244,
  "since_human": "2026-01-28 03:30:39",
  "until_human": "2026-01-30 03:30:39",
  "fetch_ok": true,
  "fills_summary": {
    "count": 437,
    "time_range": {
      "min_ms": 1769598177325,
      "max_ms": 1769738581329,
      "min_human": "2026-01-28 11:02:57",
      "max_human": "2026-01-30 02:03:01"
    },
    "coins": {
      "BTC": 437
    },
    "sides": {
      "B": 375,
      "A": 62
    }
  },
  "candidate_fields": {
    "sample_size": 50,
    "non_null_field_counts": {
      "closedPnl": 50,
      "coin": 50,
      "crossed": 50,
      "dir": 50,
      "fee": 50,
      "feeToken": 50,
      "hash": 50,
      "oid": 50,
      "px": 50,
      "side": 50,
      "startPosition": 50,
      "sz": 50,
      "tid": 50,
      "time": 50
    },
    "hash_key_counts": {
      "hash": 50,
      "txHash": 0,
      "tx_hash": 0
    }
  },
  "selected_hash_key": "hash",
  "group_analysis": {
    "total_groups": 7,
    "groups_with_multiple_fills": 7,
    "max_group_size": 124,
    "mixed_side_groups": 0,
    "start_position_variance_groups": 7,
    "ordering_issues_groups": 7,
    "multi_coin_same_hash": 0,
    "missing_hash_groups": 0
  },
  "raw_dump_path": "docs/archive/evidence/fill_aggregation_raw_48h.json"
}
```

Notes:
- Selected hash key: hash
- Groups with multiple fills: 7 / 7 (100%)
- Mixed-side groups: 0
- Multi-coin same-hash groups: 0
- Ordering issues (time, tid): 7 (order not stable in payload; sort before aggregation)
- StartPosition variance: 7 (expected for multi-fill sequences)

## WS Evidence (Attempted)
Command:
```bash
PYTHONPATH=src python3 tools/ops_capture_userfills_ws.py \
  --config config/settings.yaml \
  --schema config/schema.json \
  --duration-sec 90 \
  --output docs/archive/evidence/userfills_ws_capture.jsonl
```

Observations:
- Non-snapshot filter enabled (data.isSnapshot is skipped).
- Captured 0 messages in 90 seconds (file is empty).
- WS evidence is inconclusive; REST evidence remains primary.

## DB Cross-Check (Optional)
Data window (from REST fills): 1769598177325 → 1769738581329

- DB path: data/hyperliquid_mainnet.db
- processed_txs rows in window: 86
- trade_history rows in window: 0
- Fills in window: 437
- Missing in DB: 351 (fills not present as processed_txs by tx_hash + tid + symbol)
- Sample missing keys:
  - (0xec64408eb939649aeddd04344759500201530074543c836c902cebe1783d3e85, 193849190002740, BTCUSDT)
  - (0xa6f731670d3ec487a8700434496f780203cb004ca831e3594abfdcb9cc329e72, 906596462725470, BTCUSDT)
  - (0x81598b57e98b969182d30434505113020591003d848eb563252236aaa88f707c, 1016482416214039, BTCUSDT)

Interpretation:
- processed_txs is written at ingest time (before decision filters). A large missing set implies ingest did not record many fills in this window (e.g., service not running, gap handling, or data not received), not simply decision filtering.

## Conclusion
Decision:
- [x] REST returns multiple fills per tx; ingest aggregation is likely required to avoid min-qty filtering of tiny fills.
- [ ] REST/WS already aggregated; issue likely elsewhere (filters/symbol map).
- [ ] Inconclusive; collect more data.

Follow-ups:
- Validate WS payload behavior with a short live capture.
- If aggregation is implemented, group by (tx_hash, coin) and sort by (time, tid).
- Investigate ingest gap vs runtime uptime for the 351 missing fills.
