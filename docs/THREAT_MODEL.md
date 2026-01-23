# Threat Model (MVP)

## Assets
- API credentials
- Trading capital
- Position and order history

## Core Threats and Mitigations

1) Key leakage
- Risk: API keys exposed via logs or config leaks
- Mitigation: strict redaction, no key logging, environment-based secrets

2) Duplicate execution (replay / dedup failure)
- Risk: repeated orders due to retries or backfill
- Mitigation: processed_txs dedup + idempotent clientOrderId

3) Drift and desync
- Risk: local state diverges from exchange
- Mitigation: startup + periodic reconciliation; ARMED_SAFE on critical drift

4) Unsafe exposure increase
- Risk: system adds risk during uncertainty
- Mitigation: ARMED_SAFE gate; replay_policy close_only by default

5) Storage corruption or loss
- Risk: cursor and idempotency state lost
- Mitigation: WAL, backups, and HALT on storage errors
