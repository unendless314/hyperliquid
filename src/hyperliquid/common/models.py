from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class ContractVersion:
    major: int
    minor: int

    @staticmethod
    def parse(raw: str) -> "ContractVersion":
        parts = raw.split(".")
        if len(parts) != 2:
            raise ValueError(f"Invalid contract version: {raw}")
        major, minor = parts
        return ContractVersion(major=int(major), minor=int(minor))

    def is_compatible_with(self, other: "ContractVersion") -> bool:
        return self.major == other.major and self.minor <= other.minor


def current_contract_version() -> ContractVersion:
    return ContractVersion.parse(CONTRACT_VERSION)


def assert_contract_version(producer_version: str) -> None:
    producer = ContractVersion.parse(producer_version)
    consumer = current_contract_version()
    if not producer.is_compatible_with(consumer):
        raise ValueError(
            "Contract version mismatch: "
            f"producer={producer_version} consumer={CONTRACT_VERSION}"
        )


def correlation_id(tx_hash: str, event_index: int, symbol: str) -> str:
    sanitized_symbol = symbol.replace("-", "_")
    return f"hl-{tx_hash}-{event_index}-{sanitized_symbol}"


@dataclass
class PositionDeltaEvent:
    symbol: str
    timestamp_ms: int
    tx_hash: str
    event_index: int
    is_replay: int
    prev_target_net_position: float
    next_target_net_position: float
    delta_target_net_position: float
    action_type: str
    open_component: Optional[float]
    close_component: Optional[float]
    contract_version: str = field(default=CONTRACT_VERSION)


@dataclass
class OrderIntent:
    correlation_id: str
    symbol: str
    side: str
    order_type: str
    qty: float
    price: Optional[float]
    reduce_only: int
    time_in_force: str
    is_replay: int
    risk_notes: Optional[str] = None
    contract_version: str = field(default=CONTRACT_VERSION)


@dataclass
class OrderResult:
    correlation_id: str
    exchange_order_id: Optional[str]
    status: str
    filled_qty: float
    avg_price: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]
    contract_version: str = field(default=CONTRACT_VERSION)
