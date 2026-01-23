from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, List, Optional

from hyperliquid.common.filters import SymbolFilters, validate_intent_filters
from hyperliquid.common.models import (
    OrderIntent,
    PositionDeltaEvent,
    PriceSnapshot,
    assert_contract_version,
    correlation_id,
)
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision import reasons
from hyperliquid.decision.position import reduce_only_for_action


SafetyModeProvider = Callable[[], str]
ReplayPolicyProvider = Callable[[], str]
NowMsProvider = Callable[[], int]
PriceProvider = Callable[[str], Optional[PriceSnapshot]]
FiltersProvider = Callable[[str], Optional[SymbolFilters]]

SUPPORTED_STRATEGY_VERSIONS = {"v1"}
SUPPORTED_REPLAY_POLICIES = {"close_only"}


@dataclass(frozen=True)
class DecisionInputs:
    safety_mode: str
    local_current_position: Optional[float] = None
    closable_qty: Optional[float] = None
    expected_price: Optional[PriceSnapshot] = None


def _default_now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DecisionService:
    config: DecisionConfig
    safety_mode_provider: SafetyModeProvider
    replay_policy_provider: Optional[ReplayPolicyProvider] = None
    price_provider: Optional[PriceProvider] = None
    fallback_price_provider: Optional[PriceProvider] = None
    filters_provider: Optional[FiltersProvider] = None
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
                safety_mode=safety_mode,
            )
        safety_mode = inputs.safety_mode

        if not self._validate_event(event):
            return []

        if safety_mode == "HALT":
            return []

        if not self._validate_strategy_version(event):
            return []

        if not self._validate_replay_policy(event):
            return []

        if self._is_blacklisted(event.symbol):
            self._log_reject(reasons.BLACKLISTED_SYMBOL, event)
            return []

        intents = self._build_intents(event, inputs)
        if not intents:
            return []

        intents = self._apply_risk_checks(intents, event, inputs)
        if not intents:
            return []

        intents = self._apply_policy_gates(intents, safety_mode, event.is_replay, event)
        return intents

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

    def _build_intents(
        self, event: PositionDeltaEvent, inputs: DecisionInputs
    ) -> List[OrderIntent]:
        strategy_version = self._strategy_version_value()
        if event.action_type == "FLIP":
            return self._build_flip_intents(event, inputs, strategy_version)

        if event.action_type == "DECREASE":
            close_qty, close_reason = self._compute_close_qty(event, inputs)
            if close_qty <= 0:
                self._log_reject(close_reason or reasons.NO_CLOSABLE_QTY, event)
                return []
            close_side = "SELL" if event.prev_target_net_position > 0 else "BUY"
            return [
                self._build_intent(
                    event=event,
                    side=close_side,
                    qty=close_qty,
                    reduce_only=reduce_only_for_action(event.action_type),
                    strategy_version=strategy_version,
                )
            ]

        qty, sizing_reason = self._compute_increase_qty(event)
        if qty <= 0:
            self._log_reject(sizing_reason or reasons.SIZING_INVALID, event)
            return []
        side = "BUY" if event.delta_target_net_position > 0 else "SELL"
        return [
            self._build_intent(
                event=event,
                side=side,
                qty=qty,
                reduce_only=reduce_only_for_action(event.action_type),
                strategy_version=strategy_version,
            )
        ]

    def _build_flip_intents(
        self, event: PositionDeltaEvent, inputs: DecisionInputs, strategy_version: str
    ) -> List[OrderIntent]:
        if event.close_component is None or event.open_component is None:
            raise ValueError("FLIP requires close_component and open_component")

        close_qty = abs(event.close_component)
        open_qty = abs(event.open_component)
        if close_qty <= 0 and open_qty <= 0:
            return []

        if close_qty > 0:
            close_qty, close_reason = self._compute_close_qty(event, inputs)
            if close_qty <= 0:
                self._log_reject(close_reason or reasons.NO_CLOSABLE_QTY, event)
                return []

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
        return intents

    def _apply_policy_gates(
        self,
        intents: List[OrderIntent],
        safety_mode: str,
        is_replay: int,
        event: PositionDeltaEvent,
    ) -> List[OrderIntent]:
        if safety_mode == "ARMED_SAFE":
            intents = [intent for intent in intents if intent.reduce_only == 1]
        if is_replay:
            policy = self._replay_policy_provider()
            if policy == "close_only":
                filtered = [intent for intent in intents if intent.reduce_only == 1]
                if intents and not filtered:
                    self._log_reject(reasons.REPLAY_POLICY_BLOCKED, event)
                intents = filtered
        return intents

    def _validate_strategy_version(self, event: PositionDeltaEvent) -> bool:
        strategy_version = self.config.strategy_version
        if strategy_version is None or not str(strategy_version).strip():
            self._log_reject(reasons.STRATEGY_VERSION_MISSING, event)
            return False
        if str(strategy_version) not in SUPPORTED_STRATEGY_VERSIONS:
            self._log_reject(reasons.STRATEGY_VERSION_UNSUPPORTED, event)
            return False
        return True

    def _validate_replay_policy(self, event: PositionDeltaEvent) -> bool:
        policy = self._replay_policy_provider()
        if policy not in SUPPORTED_REPLAY_POLICIES:
            self._log_reject(reasons.REPLAY_POLICY_UNSUPPORTED, event)
            return False
        return True

    def _strategy_version_value(self) -> str:
        return str(self.config.strategy_version)

    def _apply_risk_checks(
        self,
        intents: List[OrderIntent],
        event: PositionDeltaEvent,
        inputs: DecisionInputs,
    ) -> List[OrderIntent]:
        reference_price, reference_stale = self._select_reference_price(event)
        if reference_price is None and self.config.price_failure_policy == "reject":
            reason = (
                reasons.STALE_PRICE if reference_stale else reasons.MISSING_REFERENCE_PRICE
            )
            self._log_reject(reason, event)
            return []

        filters = None
        if self.config.filters_enabled:
            if self.filters_provider is None:
                if self.config.filters_failure_policy == "reject":
                    self._log_reject(reasons.FILTERS_UNAVAILABLE, event)
                    return []
            else:
                filters = self.filters_provider(event.symbol)
                if filters is None and self.config.filters_failure_policy == "reject":
                    self._log_reject(reasons.FILTERS_UNAVAILABLE, event)
                    return []

        risk_notes: List[str] = []
        if reference_price is None:
            if self.config.price_failure_policy != "reject":
                risk_notes.append(
                    reasons.STALE_PRICE
                    if reference_stale
                    else reasons.MISSING_REFERENCE_PRICE
                )
        elif reference_price.source == "fallback":
            risk_notes.append(reasons.PRICE_FALLBACK_USED)

        if filters is None and self.config.filters_enabled:
            if self.config.filters_failure_policy != "reject":
                risk_notes.append(reasons.FILTERS_UNAVAILABLE)

        if self.config.slippage_cap_pct > 0:
            expected_price = inputs.expected_price
            expected_stale = False
            if expected_price is not None and self.config.expected_price_max_stale_ms > 0:
                staleness_ms = self.now_ms_provider() - int(expected_price.timestamp_ms)
                if staleness_ms > self.config.expected_price_max_stale_ms:
                    expected_stale = True
            if expected_price is None or expected_price.price <= 0 or expected_stale:
                if self.config.price_failure_policy == "reject":
                    reason = (
                        reasons.STALE_EXPECTED_PRICE
                        if expected_stale
                        else reasons.MISSING_EXPECTED_PRICE
                    )
                    self._log_reject(reason, event)
                    return []
                risk_notes.append(
                    reasons.STALE_EXPECTED_PRICE
                    if expected_stale
                    else reasons.MISSING_EXPECTED_PRICE
                )
            if reference_price is None or reference_price.price <= 0:
                if self.config.price_failure_policy == "reject":
                    reason = (
                        reasons.STALE_PRICE
                        if reference_stale
                        else reasons.MISSING_REFERENCE_PRICE
                    )
                    self._log_reject(reason, event)
                    return []
                risk_notes.append(
                    reasons.STALE_PRICE
                    if reference_stale
                    else reasons.MISSING_REFERENCE_PRICE
                )
            if (
                expected_price is not None
                and expected_price.price > 0
                and reference_price is not None
                and reference_price.price > 0
            ):
                slippage = abs(reference_price.price - expected_price.price) / max(
                    expected_price.price, 1e-9
                )
                if slippage > self.config.slippage_cap_pct:
                    self._log_reject(
                        reasons.SLIPPAGE_EXCEEDED,
                        event,
                        extra={"slippage": slippage, "cap": self.config.slippage_cap_pct},
                    )
                    return []

        if filters is not None:
            for intent in intents:
                try:
                    validate_intent_filters(
                        intent,
                        filters,
                        reference_price.price if reference_price else None,
                    )
                except ValueError as exc:
                    self._log_reject(self._map_filter_error(str(exc)), event)
                    return []

        if risk_notes:
            for intent in intents:
                intent.risk_notes = self._append_risk_note(intent.risk_notes, risk_notes)
        return intents

    def _select_reference_price(
        self, event: PositionDeltaEvent
    ) -> tuple[Optional[PriceSnapshot], bool]:
        if self.price_provider is None and self.fallback_price_provider is None:
            return None, False
        now_ms = self.now_ms_provider()
        snapshot = None
        stale = False
        primary = self.price_provider
        secondary = self.fallback_price_provider
        if self.config.price_source == "ingest":
            primary, secondary = secondary, primary
        if primary is not None:
            snapshot = primary(event.symbol)
            if snapshot is not None and self.config.price_max_stale_ms > 0:
                staleness_ms = now_ms - int(snapshot.timestamp_ms)
                if staleness_ms > self.config.price_max_stale_ms:
                    snapshot = None
                    stale = True

        if snapshot is None and self.config.price_fallback_enabled:
            if secondary is not None:
                fallback = secondary(event.symbol)
                if fallback is not None:
                    staleness_ms = now_ms - int(fallback.timestamp_ms)
                    if (
                        self.config.price_fallback_max_stale_ms <= 0
                        or staleness_ms <= self.config.price_fallback_max_stale_ms
                    ):
                        snapshot = PriceSnapshot(
                            price=float(fallback.price),
                            timestamp_ms=int(fallback.timestamp_ms),
                            source="fallback",
                        )
                        stale = False
                    else:
                        stale = True
        return snapshot, stale

    def _compute_close_qty(
        self, event: PositionDeltaEvent, inputs: DecisionInputs
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

    @staticmethod
    def _map_filter_error(code: str) -> str:
        mapping = {
            "filter_min_qty": reasons.FILTER_MIN_QTY,
            "filter_step_size": reasons.FILTER_STEP_SIZE,
            "filter_tick_size": reasons.FILTER_TICK_SIZE,
            "filter_min_notional": reasons.FILTER_MIN_NOTIONAL,
        }
        return mapping.get(code, code)

    def _is_blacklisted(self, symbol: str) -> bool:
        return symbol in set(self.config.blacklist_symbols)

    @staticmethod
    def _append_risk_note(existing: Optional[str], notes: List[str]) -> str:
        merged = []
        if existing:
            merged.append(existing)
        merged.extend(notes)
        return ",".join(merged)

    def _validate_event(self, event: PositionDeltaEvent) -> bool:
        max_stale_ms = int(self.config.max_stale_ms)
        max_future_ms = int(self.config.max_future_ms)
        if max_stale_ms <= 0 and max_future_ms <= 0:
            return True
        if event.timestamp_ms <= 0:
            self._log_reject(reasons.MISSING_TIMESTAMP, event)
            return False
        now_ms = self.now_ms_provider()
        staleness_ms = now_ms - int(event.timestamp_ms)
        if max_future_ms >= 0 and staleness_ms < -max_future_ms:
            self._log_reject(
                reasons.FUTURE_EVENT,
                event,
                extra={"staleness_ms": staleness_ms, "max_future_ms": max_future_ms},
            )
            return False
        if max_stale_ms > 0 and staleness_ms > max_stale_ms:
            self._log_reject(
                reasons.STALE_EVENT,
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
