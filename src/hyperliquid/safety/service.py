from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hyperliquid.common.models import OrderIntent
from hyperliquid.safety.reconcile import (
    DriftReport,
    ReconciliationResult,
    compute_drift,
    evaluate_drift,
)


SafetyModeProvider = Callable[[], str]


@dataclass
class SafetyService:
    safety_mode_provider: SafetyModeProvider

    def pre_execution_check(self, intent: OrderIntent) -> None:
        mode = self.safety_mode_provider()
        if mode == "HALT":
            raise RuntimeError("HALT")
        if mode == "ARMED_SAFE" and intent.reduce_only == 0:
            raise RuntimeError("ARMED_SAFE_BLOCK_INCREASE")

    def post_execution_check(self, intent: OrderIntent) -> None:
        _ = intent
        return None

    def reconcile_positions(
        self,
        *,
        db_positions: dict[str, float],
        exchange_positions: dict[str, float],
        warn_threshold: float,
        critical_threshold: float,
    ) -> ReconciliationResult:
        report: DriftReport = compute_drift(db_positions, exchange_positions)
        return evaluate_drift(
            report, warn_threshold=warn_threshold, critical_threshold=critical_threshold
        )
