from __future__ import annotations

import re
import secrets
from typing import Tuple

from hyperliquid.common.models import normalize_symbol

_CLIENT_ORDER_ID_MAX_LEN = 36
_CLIENT_ORDER_ID_ALLOWED = re.compile(r"[^A-Za-z0-9_-]+")


def generate_nonce() -> str:
    return secrets.token_hex(4)


def parse_correlation_id(correlation_id: str) -> Tuple[str, int]:
    parts = correlation_id.split("-")
    if len(parts) < 4 or parts[0] != "hl":
        raise ValueError(f"Invalid correlation_id: {correlation_id}")
    tx_hash = parts[1]
    try:
        event_index = int(parts[2])
    except ValueError as exc:
        raise ValueError(f"Invalid correlation_id: {correlation_id}") from exc
    return tx_hash, event_index


def sanitize_client_order_id(value: str, *, max_len: int = _CLIENT_ORDER_ID_MAX_LEN) -> str:
    cleaned = _CLIENT_ORDER_ID_ALLOWED.sub("", value)
    if len(cleaned) <= max_len:
        return cleaned
    if max_len <= 3:
        return cleaned[:max_len]
    return f"hl-{cleaned[-(max_len - 3):]}"


def build_client_order_id(
    *,
    correlation_id: str,
    symbol: str,
    nonce: str,
    max_len: int = _CLIENT_ORDER_ID_MAX_LEN,
) -> str:
    tx_hash, event_index = parse_correlation_id(correlation_id)
    normalized_symbol = normalize_symbol(symbol)
    raw = f"hl-{tx_hash}-{event_index}-{normalized_symbol}-{nonce}"
    return sanitize_client_order_id(raw, max_len=max_len)
