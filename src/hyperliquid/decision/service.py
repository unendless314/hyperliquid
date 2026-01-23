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
)
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision import reasons
from hyperliquid.decision.strategy import StrategyV1
from hyperliquid.decision.types import DecisionInputs


SafetyModeProvider = Callable[[], str]
ReplayPolicyProvider = Callable[[], str]
NowMsProvider = Callable[[], int]
PriceProvider = Callable[[str], Optional[PriceSnapshot]]
FiltersProvider = Callable[[str], Optional[SymbolFilters]]

SUPPORTED_STRATEGY_VERSIONS = {"v1"}
SUPPORTED_REPLAY_POLICIES = {"close_only"}


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
    _strategy: StrategyV1 = field(init=False)

    def __post_init__(self) -> None:
        if self.replay_policy_provider is None:
            self._replay_policy_provider = lambda: self.config.replay_policy
        else:
            self._replay_policy_provider = self.replay_policy_provider
        self._strategy = StrategyV1(self.config)

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

    def _build_intents(
        self, event: PositionDeltaEvent, inputs: DecisionInputs
    ) -> List[OrderIntent]:
        strategy_version = self._strategy_version_value()
        intents, reject_reason = self._strategy.build_intents(
            event, inputs, strategy_version=strategy_version
        )
        if reject_reason:
            self._log_reject(reject_reason, event)
            return []
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

        def add_note(note: str) -> None:
            if note not in risk_notes:
                risk_notes.append(note)

        if reference_price is None:
            if self.config.price_failure_policy != "reject":
                add_note(
                    reasons.STALE_PRICE
                    if reference_stale
                    else reasons.MISSING_REFERENCE_PRICE
                )
        elif reference_price.source == "fallback":
            add_note(reasons.PRICE_FALLBACK_USED)

        if filters is None and self.config.filters_enabled:
            if self.config.filters_failure_policy != "reject":
                add_note(reasons.FILTERS_UNAVAILABLE)

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
                add_note(
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
                add_note(
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
