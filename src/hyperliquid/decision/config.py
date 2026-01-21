from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class DecisionConfig:
    max_stale_ms: int = 0
    max_future_ms: int = 2000
    replay_policy: str = "close-only"
    price_source: str = "adapter"
    price_fallback_enabled: bool = False
    price_fallback_max_stale_ms: int = 0
    filters_enabled: bool = True
    blacklist_symbols: List[str] = field(default_factory=list)

    @staticmethod
    def from_settings(settings: Dict[str, Any]) -> "DecisionConfig":
        raw = settings.get("decision", {}) or {}
        blacklist = raw.get("blacklist_symbols", []) or []
        return DecisionConfig(
            max_stale_ms=int(raw.get("max_stale_ms", 0)),
            max_future_ms=int(raw.get("max_future_ms", 2000)),
            replay_policy=str(raw.get("replay_policy", "close-only")),
            price_source=str(raw.get("price_source", "adapter")),
            price_fallback_enabled=bool(raw.get("price_fallback_enabled", False)),
            price_fallback_max_stale_ms=int(raw.get("price_fallback_max_stale_ms", 0)),
            filters_enabled=bool(raw.get("filters_enabled", True)),
            blacklist_symbols=[str(item) for item in blacklist],
        )
