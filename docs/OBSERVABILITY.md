# Observability

## Minimal Metrics (MVP Priority)
- cursor_lag_ms
- backfill_count
- dedup_drop_count
- order_success_rate
- reconciliation_drift

## Logging and Storage
- Metrics are emitted to stdout in structured form.
- Metrics are also appended to a local file (e.g., logs/metrics.log).

## Logs
- Structured logs
- Correlation IDs

## Alerts
- Critical drift
- Halt events
- Repeated order failures

## SLO/SLA
- To be defined

