from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

import time

from hyperliquid.common.models import normalize_symbol


@dataclass(frozen=True)
class PositionSnapshot:
    source: str
    positions: Dict[str, float]
    timestamp_ms: int


@dataclass(frozen=True)
class DriftReport:
    drifts: Dict[str, float]
    max_drift: float


@dataclass(frozen=True)
class ReconciliationResult:
    mode: str
    reason_code: str
    reason_message: str
    report: DriftReport


def compute_drift(
    db_positions: Dict[str, float], exchange_positions: Dict[str, float]
) -> DriftReport:
    symbols = set(db_positions.keys()) | set(exchange_positions.keys())
    drifts: Dict[str, float] = {}
    max_drift = 0.0
    for symbol in symbols:
        drift = abs(db_positions.get(symbol, 0.0) - exchange_positions.get(symbol, 0.0))
        drifts[symbol] = drift
        if drift > max_drift:
            max_drift = drift
    return DriftReport(drifts=drifts, max_drift=max_drift)


def evaluate_drift(
    report: DriftReport, *, warn_threshold: float, critical_threshold: float
) -> ReconciliationResult:
    if report.max_drift >= critical_threshold:
        return ReconciliationResult(
            mode="HALT",
            reason_code="RECONCILE_CRITICAL",
            reason_message="Drift exceeds critical threshold",
            report=report,
        )
    if report.max_drift >= warn_threshold:
        return ReconciliationResult(
            mode="ARMED_SAFE",
            reason_code="RECONCILE_WARN",
            reason_message="Drift exceeds warning threshold",
            report=report,
        )
    return ReconciliationResult(
        mode="ARMED_LIVE",
        reason_code="OK",
        reason_message="Drift within thresholds",
        report=report,
    )


def normalize_positions(
    positions: Dict[str, float], *, zero_epsilon: float = 1e-9
) -> Dict[str, float]:
    normalized: Dict[str, float] = {}
    for symbol, value in positions.items():
        key = normalize_symbol(symbol)
        normalized[key] = normalized.get(key, 0.0) + float(value)
    if zero_epsilon >= 0:
        normalized = {
            symbol: value
            for symbol, value in normalized.items()
            if abs(value) > zero_epsilon
        }
    return normalized


def find_missing_symbols(
    *, local_symbols: Iterable[str], exchange_symbols: Iterable[str]
) -> tuple[list[str], list[str]]:
    local_set = set(local_symbols)
    exchange_set = set(exchange_symbols)
    return (
        sorted(local_set - exchange_set),
        sorted(exchange_set - local_set),
    )


def reconcile_snapshots(
    *,
    local_snapshot: PositionSnapshot,
    exchange_snapshot: PositionSnapshot,
    warn_threshold: float,
    critical_threshold: float,
    snapshot_max_stale_ms: int,
    now_ms: int | None = None,
) -> ReconciliationResult:
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    staleness_ms = now_ms - exchange_snapshot.timestamp_ms
    if snapshot_max_stale_ms >= 0 and staleness_ms > snapshot_max_stale_ms:
        return ReconciliationResult(
            mode="ARMED_SAFE",
            reason_code="SNAPSHOT_STALE",
            reason_message="Exchange snapshot is stale",
            report=DriftReport(drifts={}, max_drift=0.0),
        )

    local_positions = normalize_positions(local_snapshot.positions)
    exchange_positions = normalize_positions(exchange_snapshot.positions)
    missing_local, missing_exchange = find_missing_symbols(
        local_symbols=local_positions.keys(),
        exchange_symbols=exchange_positions.keys(),
    )
    if missing_local or missing_exchange:
        missing_message = (
            f"missing_local={missing_local} missing_exchange={missing_exchange}"
        )
        return ReconciliationResult(
            mode="HALT",
            reason_code="RECONCILE_CRITICAL",
            reason_message=f"Missing symbols detected: {missing_message}",
            report=DriftReport(drifts={}, max_drift=0.0),
        )

    report = compute_drift(local_positions, exchange_positions)
    return evaluate_drift(
        report, warn_threshold=warn_threshold, critical_threshold=critical_threshold
    )
