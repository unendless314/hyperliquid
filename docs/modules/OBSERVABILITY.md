# Observability / Alert Spec

## Responsibilities
- Structured logging
- Metrics collection and periodic dump
- Alerting (Telegram or stdout fallback)

## Inputs
- Module events and errors

## Outputs
- Logs, metrics, alerts

## Key Rules
- Redact secrets
- Correlation IDs on all key events
