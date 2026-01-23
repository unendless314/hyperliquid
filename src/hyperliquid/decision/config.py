from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SizingConfig:
    mode: str = "proportional"
    fixed_qty: float = 0.0
    proportional_ratio: float = 1.0
    kelly_win_rate: float = 0.0
    kelly_edge: float = 0.0
    kelly_fraction: float = 1.0


@dataclass(frozen=True)
class DecisionConfig:
    max_stale_ms: int = 0
    max_future_ms: int = 2000
    price_max_stale_ms: int = 0
    expected_price_max_stale_ms: int = 0
    strategy_version: Optional[str] = None
    replay_policy: str = "close_only"
    price_source: str = "adapter"
    price_fallback_enabled: bool = False
    price_fallback_max_stale_ms: int = 0
    price_failure_policy: str = "allow_without_price"
    filters_enabled: bool = True
    filters_failure_policy: str = "allow_without_filters"
    blacklist_symbols: List[str] = field(default_factory=list)
    slippage_cap_pct: float = 0.0
    sizing: SizingConfig = field(default_factory=SizingConfig)

    @staticmethod
    def from_settings(settings: Dict[str, Any]) -> "DecisionConfig":
        raw = settings.get("decision", {}) or {}
        blacklist = raw.get("blacklist_symbols", []) or []
        sizing_raw = raw.get("sizing", {}) or {}
        return DecisionConfig(
            max_stale_ms=int(raw.get("max_stale_ms", 0)),
            max_future_ms=int(raw.get("max_future_ms", 2000)),
            price_max_stale_ms=int(raw.get("price_max_stale_ms", 0)),
            expected_price_max_stale_ms=int(raw.get("expected_price_max_stale_ms", 0)),
            strategy_version=raw.get("strategy_version"),
            replay_policy=str(raw.get("replay_policy", "close_only")),
            price_source=str(raw.get("price_source", "adapter")),
            price_fallback_enabled=bool(raw.get("price_fallback_enabled", False)),
            price_fallback_max_stale_ms=int(raw.get("price_fallback_max_stale_ms", 0)),
            price_failure_policy=str(
                raw.get("price_failure_policy", "allow_without_price")
            ),
            filters_enabled=bool(raw.get("filters_enabled", True)),
            filters_failure_policy=str(
                raw.get("filters_failure_policy", "allow_without_filters")
            ),
            blacklist_symbols=[str(item) for item in blacklist],
            slippage_cap_pct=float(raw.get("slippage_cap_pct", 0.0)),
            sizing=SizingConfig(
                mode=str(sizing_raw.get("mode", "proportional")),
                fixed_qty=float(sizing_raw.get("fixed_qty", 0.0)),
                proportional_ratio=float(sizing_raw.get("proportional_ratio", 1.0)),
                kelly_win_rate=float(sizing_raw.get("kelly_win_rate", 0.0)),
                kelly_edge=float(sizing_raw.get("kelly_edge", 0.0)),
                kelly_fraction=float(sizing_raw.get("kelly_fraction", 1.0)),
            ),
        )
