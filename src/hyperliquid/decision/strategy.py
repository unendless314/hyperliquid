from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from hyperliquid.common.models import (
    OrderIntent,
    PositionDeltaEvent,
    assert_contract_version,
    correlation_id,
)
from hyperliquid.decision import reasons
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.position import reduce_only_for_action
from hyperliquid.decision.types import DecisionInputs


@dataclass(frozen=True)
class StrategyV1:
    config: DecisionConfig

    def build_intents(
        self,
        event: PositionDeltaEvent,
        inputs: DecisionInputs,
        *,
        strategy_version: str,
    ) -> Tuple[List[OrderIntent], Optional[str]]:
        if event.action_type == "FLIP":
            return self._build_flip_intents(event, inputs, strategy_version)

        if event.action_type == "DECREASE":
            close_qty, close_reason = self._compute_close_qty(event, inputs)
            if close_qty <= 0:
                return [], close_reason or reasons.NO_CLOSABLE_QTY
            close_side = "SELL" if event.prev_target_net_position > 0 else "BUY"
            return [
                self._build_intent(
                    event=event,
                    side=close_side,
                    qty=close_qty,
                    reduce_only=reduce_only_for_action(event.action_type),
                    strategy_version=strategy_version,
                )
            ], None

        qty, sizing_reason = self._compute_increase_qty(event)
        if qty <= 0:
            return [], sizing_reason or reasons.SIZING_INVALID
        side = "BUY" if event.delta_target_net_position > 0 else "SELL"
        return [
            self._build_intent(
                event=event,
                side=side,
                qty=qty,
                reduce_only=reduce_only_for_action(event.action_type),
                strategy_version=strategy_version,
            )
        ], None

    @staticmethod
    def _build_intent(
        event: PositionDeltaEvent,
        *,
        side: str,
        qty: float,
        reduce_only: int,
        strategy_version: str,
        suffix: str | None = None,
        risk_notes: Optional[str] = None,
    ) -> OrderIntent:
        intent = OrderIntent(
            correlation_id=correlation_id(
                event.tx_hash, event.event_index, event.symbol, suffix=suffix
            ),
            client_order_id=None,
            strategy_version=strategy_version,
            symbol=event.symbol,
            side=side,
            order_type="MARKET",
            qty=qty,
            price=None,
            reduce_only=reduce_only,
            time_in_force="IOC",
            is_replay=event.is_replay,
            risk_notes=risk_notes,
        )
        assert_contract_version(intent.contract_version)
        return intent

    def _build_flip_intents(
        self,
        event: PositionDeltaEvent,
        inputs: DecisionInputs,
        strategy_version: str,
    ) -> Tuple[List[OrderIntent], Optional[str]]:
        if event.close_component is None or event.open_component is None:
            raise ValueError("FLIP requires close_component and open_component")

        close_qty = abs(event.close_component)
        open_qty = abs(event.open_component)
        if close_qty <= 0 and open_qty <= 0:
            return [], None

        if close_qty > 0:
            close_qty, close_reason = self._compute_close_qty(event, inputs)
            if close_qty <= 0:
                return [], close_reason or reasons.NO_CLOSABLE_QTY

        intents: List[OrderIntent] = []
        if close_qty > 0:
            close_side = "SELL" if event.prev_target_net_position > 0 else "BUY"
            intents.append(
                self._build_intent(
                    event=event,
                    side=close_side,
                    qty=close_qty,
                    reduce_only=reduce_only_for_action(event.action_type, "close"),
                    strategy_version=strategy_version,
                    suffix="close",
                )
            )
        if open_qty > 0:
            open_side = "BUY" if event.next_target_net_position > 0 else "SELL"
            intents.append(
                self._build_intent(
                    event=event,
                    side=open_side,
                    qty=open_qty,
                    reduce_only=reduce_only_for_action(event.action_type, "open"),
                    strategy_version=strategy_version,
                    suffix="open",
                )
            )
        return intents, None

    @staticmethod
    def _compute_close_qty(
        event: PositionDeltaEvent, inputs: DecisionInputs
    ) -> tuple[float, Optional[str]]:
        if inputs.local_current_position is None:
            return 0.0, reasons.MISSING_LOCAL_POSITION
        if inputs.closable_qty is None:
            return 0.0, reasons.MISSING_CLOSABLE_QTY
        if event.prev_target_net_position == 0:
            return 0.0, reasons.NO_CLOSABLE_QTY
        target_ratio = min(
            1.0,
            abs(event.delta_target_net_position) / max(abs(event.prev_target_net_position), 1e-9),
        )
        local_close_qty = abs(inputs.local_current_position) * target_ratio
        return min(local_close_qty, abs(inputs.closable_qty)), None

    def _compute_increase_qty(self, event: PositionDeltaEvent) -> tuple[float, Optional[str]]:
        base_qty = abs(event.delta_target_net_position)
        if base_qty <= 0:
            return 0.0, reasons.SIZING_INVALID
        sizing = self.config.sizing
        if sizing.mode == "fixed":
            return float(sizing.fixed_qty), None
        if sizing.mode == "proportional":
            return float(base_qty * sizing.proportional_ratio), None
        if sizing.mode == "kelly":
            win_rate = sizing.kelly_win_rate
            edge = sizing.kelly_edge
            if win_rate <= 0 or edge <= 0:
                return 0.0, reasons.KELLY_PARAMS_MISSING
            kelly_fraction = win_rate - ((1 - win_rate) / edge)
            if kelly_fraction <= 0:
                return 0.0, reasons.SIZING_INVALID
            return float(base_qty * kelly_fraction * sizing.kelly_fraction), None
        return 0.0, reasons.SIZING_INVALID
