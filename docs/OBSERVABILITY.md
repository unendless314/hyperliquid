# Observability

## Minimal Metrics (MVP Priority)
- cursor_lag_ms
- backfill_count
- dedup_drop_count
- order_success_rate
- reconciliation_drift

## Metric Definitions
- cursor_lag_ms: now_ms - last_processed_timestamp_ms
- backfill_count: number of backfilled events processed in the last interval
- dedup_drop_count: number of events dropped by dedup in the last interval
- order_success_rate: (filled + partially_filled) / total_submitted
  - UNKNOWN is excluded from denominator until it times out; after timeout it counts as failure.
- reconciliation_drift: max per-symbol drift during last reconcile cycle

## Suggested Thresholds (MVP)
- cursor_lag_ms > cursor_lag_halt_ms: alert and enter HALT
- order_success_rate < 0.8 over 5 min: warn
- reconciliation_drift >= critical_threshold (from settings): critical alert and enter ARMED_SAFE

## Logging and Storage
- Metrics are emitted to stdout in structured form.
- Metrics are also appended to a local file (e.g., logs/metrics.log).

## Checks
- tail -n 50 <metrics_log_path>
- grep "[METRICS]" <app_log_path>

## Logs
- Structured logs
- Correlation IDs

## Alerts
- Critical drift
- Halt events
- Repeated order failures

## SLO/SLA
- To be defined

