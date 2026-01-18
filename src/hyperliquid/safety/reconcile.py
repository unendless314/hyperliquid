from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


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
