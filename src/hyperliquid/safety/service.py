from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hyperliquid.common.models import OrderIntent
from hyperliquid.safety.reconcile import (
    DriftReport,
    PositionSnapshot,
    ReconciliationResult,
    compute_drift,
    evaluate_drift,
    reconcile_snapshots,
)
from hyperliquid.storage.safety import SafetyState


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

    def reconcile_snapshots(
        self,
        *,
        local_snapshot: PositionSnapshot,
        exchange_snapshot: PositionSnapshot,
        warn_threshold: float,
        critical_threshold: float,
        snapshot_max_stale_ms: int,
        current_state: SafetyState | None = None,
        allow_auto_promote: bool = False,
    ) -> ReconciliationResult:
        result = reconcile_snapshots(
            local_snapshot=local_snapshot,
            exchange_snapshot=exchange_snapshot,
            warn_threshold=warn_threshold,
            critical_threshold=critical_threshold,
            snapshot_max_stale_ms=snapshot_max_stale_ms,
        )
        if current_state is None:
            return result
        next_mode = _apply_reconcile_policy(
            current_state.mode, result.mode, allow_auto_promote=allow_auto_promote
        )
        if next_mode == result.mode:
            return result
        return ReconciliationResult(
            mode=next_mode,
            reason_code=current_state.reason_code,
            reason_message=current_state.reason_message,
            report=result.report,
        )


def _apply_reconcile_policy(
    current_mode: str, result_mode: str, *, allow_auto_promote: bool
) -> str:
    if current_mode == "HALT":
        return "HALT"
    if result_mode == "HALT":
        return "HALT"
    if result_mode == "ARMED_SAFE":
        return "ARMED_SAFE"
    if result_mode == "ARMED_LIVE":
        if allow_auto_promote:
            return "ARMED_LIVE"
        return current_mode
    return current_mode
