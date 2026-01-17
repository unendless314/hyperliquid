from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from hyperliquid.common.models import OrderIntent, PositionDeltaEvent, assert_contract_version, correlation_id


SafetyModeProvider = Callable[[], str]
ReplayPolicyProvider = Callable[[], str]


def _default_replay_policy() -> str:
    return "close-only"


@dataclass
class DecisionService:
    safety_mode_provider: SafetyModeProvider
    replay_policy_provider: ReplayPolicyProvider = _default_replay_policy

    def decide(self, event: PositionDeltaEvent) -> List[OrderIntent]:
        assert_contract_version(event.contract_version)
        safety_mode = self.safety_mode_provider()

        if safety_mode == "HALT":
            return []

        if event.action_type == "FLIP":
            intents = self._build_flip_intents(event)
            return self._apply_policy_gates(intents, safety_mode, event.is_replay)

        qty = abs(event.delta_target_net_position)
        if qty <= 0:
            return []

        side = "BUY" if event.delta_target_net_position > 0 else "SELL"
        reduce_only = 1 if event.action_type in ("DECREASE", "FLIP") else 0

        intent = self._build_intent(
            event=event,
            side=side,
            qty=qty,
            reduce_only=reduce_only,
        )
        return self._apply_policy_gates([intent], safety_mode, event.is_replay)

    @staticmethod
    def _build_intent(
        event: PositionDeltaEvent,
        *,
        side: str,
        qty: float,
        reduce_only: int,
        suffix: str | None = None,
    ) -> OrderIntent:
        intent = OrderIntent(
            correlation_id=correlation_id(
                event.tx_hash, event.event_index, event.symbol, suffix=suffix
            ),
            symbol=event.symbol,
            side=side,
            order_type="MARKET",
            qty=qty,
            price=None,
            reduce_only=reduce_only,
            time_in_force="IOC",
            is_replay=event.is_replay,
            risk_notes=None,
        )
        assert_contract_version(intent.contract_version)
        return intent

    def _build_flip_intents(self, event: PositionDeltaEvent) -> List[OrderIntent]:
        if event.close_component is None or event.open_component is None:
            raise ValueError("FLIP requires close_component and open_component")

        close_qty = abs(event.close_component)
        open_qty = abs(event.open_component)
        if close_qty <= 0 and open_qty <= 0:
            return []

        intents: List[OrderIntent] = []
        if close_qty > 0:
            close_side = "SELL" if event.prev_target_net_position > 0 else "BUY"
            intents.append(
                self._build_intent(
                    event=event,
                    side=close_side,
                    qty=close_qty,
                    reduce_only=1,
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
                    reduce_only=0,
                    suffix="open",
                )
            )
        return intents

    def _apply_policy_gates(
        self, intents: List[OrderIntent], safety_mode: str, is_replay: int
    ) -> List[OrderIntent]:
        if safety_mode == "ARMED_SAFE":
            intents = [intent for intent in intents if intent.reduce_only == 1]
        if is_replay:
            policy = self.replay_policy_provider()
            if policy == "close-only":
                intents = [intent for intent in intents if intent.reduce_only == 1]
        return intents
