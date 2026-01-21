from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, List, Optional

from hyperliquid.decision.config import DecisionConfig

from hyperliquid.common.models import OrderIntent, PositionDeltaEvent, assert_contract_version, correlation_id


SafetyModeProvider = Callable[[], str]
ReplayPolicyProvider = Callable[[], str]
NowMsProvider = Callable[[], int]


@dataclass(frozen=True)
class DecisionInputs:
    local_current_position: float
    closable_qty: float
    safety_mode: str


def _default_now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DecisionService:
    config: DecisionConfig
    safety_mode_provider: SafetyModeProvider
    replay_policy_provider: Optional[ReplayPolicyProvider] = None
    now_ms_provider: NowMsProvider = _default_now_ms
    logger: Optional[object] = None
    _replay_policy_provider: ReplayPolicyProvider = field(init=False)

    def __post_init__(self) -> None:
        if self.replay_policy_provider is None:
            self._replay_policy_provider = lambda: self.config.replay_policy
        else:
            self._replay_policy_provider = self.replay_policy_provider

    def decide(
        self, event: PositionDeltaEvent, inputs: DecisionInputs | None = None
    ) -> List[OrderIntent]:
        assert_contract_version(event.contract_version)
        if inputs is None:
            safety_mode = self.safety_mode_provider()
            inputs = DecisionInputs(
                local_current_position=0.0,
                closable_qty=0.0,
                safety_mode=safety_mode,
            )
        safety_mode = inputs.safety_mode

        if not self._validate_event(event):
            return []

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
            client_order_id=None,
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
            policy = self._replay_policy_provider()
            if policy == "close-only":
                intents = [intent for intent in intents if intent.reduce_only == 1]
        return intents

    def _validate_event(self, event: PositionDeltaEvent) -> bool:
        max_stale_ms = int(self.config.max_stale_ms)
        max_future_ms = int(self.config.max_future_ms)
        if max_stale_ms <= 0 and max_future_ms <= 0:
            return True
        if event.timestamp_ms <= 0:
            self._log_reject("missing_timestamp_ms", event)
            return False
        now_ms = self.now_ms_provider()
        staleness_ms = now_ms - int(event.timestamp_ms)
        if max_future_ms >= 0 and staleness_ms < -max_future_ms:
            self._log_reject(
                "future_event",
                event,
                extra={"staleness_ms": staleness_ms, "max_future_ms": max_future_ms},
            )
            return False
        if max_stale_ms > 0 and staleness_ms > max_stale_ms:
            self._log_reject(
                "stale_event",
                event,
                extra={"staleness_ms": staleness_ms, "max_stale_ms": max_stale_ms},
            )
            return False
        return True

    def _log_reject(
        self, reason: str, event: PositionDeltaEvent, extra: Optional[dict] = None
    ) -> None:
        logger = self.logger
        if logger is None:
            return
        payload = {
            "reason": reason,
            "symbol": event.symbol,
            "tx_hash": event.tx_hash,
            "event_index": event.event_index,
            "action_type": event.action_type,
            "is_replay": event.is_replay,
        }
        if extra:
            payload.update(extra)
        log_fn = getattr(logger, "warning", None)
        if callable(log_fn):
            log_fn("decision_reject", extra=payload)
