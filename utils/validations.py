"""
Config and input schema validations.

Lightweight, dependency-free checks to avoid pulling in pydantic.
Adds `config_version` (timestamp-based when absent) and `config_hash` (SHA256 of
canonical JSON) to the validated settings dictionary.
"""

from __future__ import annotations

import json
import time
from hashlib import sha256
from typing import Dict, Any


class SettingsValidationError(ValueError):
    """Raised when settings.yaml fails validation."""


def _require_keys(settings: Dict[str, Any], required: Dict[str, str]) -> None:
    missing = [k for k in required if k not in settings]
    if missing:
        raise SettingsValidationError(f"Missing required field(s): {', '.join(missing)}")


def _assert_in(name: str, value: str, allowed) -> None:
    if value not in allowed:
        raise SettingsValidationError(f"{name} must be one of {allowed}, got {value!r}")


def _assert_positive(name: str, value: float, allow_zero: bool = False) -> None:
    if allow_zero and value < 0:
        raise SettingsValidationError(f"{name} must be >= 0")
    if not allow_zero and value <= 0:
        raise SettingsValidationError(f"{name} must be > 0")


def _assert_between(name: str, value: float, low: float, high: float) -> None:
    if not (low <= value <= high):
        raise SettingsValidationError(f"{name} must be between {low} and {high}")


def _stable_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _coerce_int(name: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SettingsValidationError(f"{name} must be an integer, got {value!r}")


def validate_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate settings dictionary and return an augmented copy with
    `config_version` and `config_hash` filled in.
    """
    if not isinstance(settings, dict):
        raise SettingsValidationError("settings must be a dict")

    required = {
        "target_wallet": "str",
        "exchange": "str",
        "market_type": "str",
        "symbol_mapping": "dict",
        "copy_mode": "str",
        "whale_estimated_balance": "float",
        "capital_utilization_soft_limit": "float",
        "capital_utilization_hard_limit": "float",
    }
    _require_keys(settings, required)

    target_wallet = settings["target_wallet"]
    if not isinstance(target_wallet, str) or not target_wallet.strip():
        raise SettingsValidationError("target_wallet must be a non-empty string")

    _assert_in("exchange", settings["exchange"], {"binance", "okx", "gate"})
    _assert_in("market_type", settings["market_type"], {"future", "spot"})

    symbol_mapping = settings["symbol_mapping"]
    if not isinstance(symbol_mapping, dict) or not symbol_mapping:
        raise SettingsValidationError("symbol_mapping must be a non-empty mapping")

    copy_mode = settings["copy_mode"]
    _assert_in("copy_mode", copy_mode, {"fixed_amount", "proportional", "kelly"})

    # Numeric validations
    for name in ("max_position_size_usd", "min_order_size_usd"):
        if name in settings:
            _assert_positive(name, float(settings[name]), allow_zero=False)

    for name in ("whale_estimated_balance", "my_account_balance_override"):
        if name in settings:
            _assert_positive(name, float(settings[name]), allow_zero=True)

    # Kelly parameters (only validated if present)
    if copy_mode == "kelly":
        for name in ("kelly_win_rate", "kelly_profit_factor", "kelly_multiplier"):
            if name not in settings:
                raise SettingsValidationError(f"{name} is required when copy_mode=kelly")
        _assert_between("kelly_win_rate", float(settings["kelly_win_rate"]), 0.0, 1.0)
        _assert_positive("kelly_profit_factor", float(settings["kelly_profit_factor"]))
        _assert_between("kelly_multiplier", float(settings["kelly_multiplier"]), 0.0, 1.0)
    elif copy_mode == "fixed_amount":
        if "fixed_amount_usd" not in settings:
            raise SettingsValidationError("fixed_amount_usd is required when copy_mode=fixed_amount")
        _assert_positive("fixed_amount_usd", float(settings["fixed_amount_usd"]))

    # Capital utilization thresholds
    soft = float(settings["capital_utilization_soft_limit"])
    hard = float(settings["capital_utilization_hard_limit"])
    _assert_between("capital_utilization_soft_limit", soft, 0.0, 1.0)
    _assert_between("capital_utilization_hard_limit", hard, 0.0, 1.0)
    if soft >= hard:
        raise SettingsValidationError("soft limit must be < hard limit")

    # Price deviation/risk fields are optional; validate if present
    optional_between = {
        "price_deviation_pct": (0.0, 1.0),
        "price_deviation_usd": (0.0, float("inf")),
    }
    for name, bounds in optional_between.items():
        if name in settings:
            low, high = bounds
            val = float(settings[name])
            if high == float("inf"):
                _assert_positive(name, val)
            else:
                _assert_between(name, val, low, high)

    # Monitor/backfill config with defaults
    cursor_mode = settings.get("cursor_mode", "block")
    if isinstance(cursor_mode, str):
        cursor_mode = cursor_mode.lower()
    _assert_in("cursor_mode", cursor_mode, {"block", "timestamp"})

    backfill_window = _coerce_int("backfill_window", settings.get("backfill_window", 200))
    _assert_positive("backfill_window", backfill_window)

    dedup_ttl_seconds = _coerce_int("dedup_ttl_seconds", settings.get("dedup_ttl_seconds", 24 * 60 * 60))
    _assert_positive("dedup_ttl_seconds", dedup_ttl_seconds)

    dedup_cleanup_interval_seconds = _coerce_int(
        "dedup_cleanup_interval_seconds", settings.get("dedup_cleanup_interval_seconds", 300)
    )
    _assert_positive("dedup_cleanup_interval_seconds", dedup_cleanup_interval_seconds)

    enable_rest_backfill = bool(settings.get("enable_rest_backfill", False))
    rest_base_url = settings.get("hyperliquid_rest_base_url", "https://api.hyperliquid.xyz/info")
    if not isinstance(rest_base_url, str) or not rest_base_url.strip():
        raise SettingsValidationError("hyperliquid_rest_base_url must be a non-empty string")
    if enable_rest_backfill and cursor_mode != "timestamp":
        raise SettingsValidationError("enable_rest_backfill requires cursor_mode='timestamp' because REST returns timestamps")

    if "max_stale_ms" in settings:
        max_stale_ms = _coerce_int("max_stale_ms", settings["max_stale_ms"])
        _assert_positive("max_stale_ms", max_stale_ms)
    else:
        max_stale_ms = None

    binance_filters = settings.get("binance_filters", {})
    if binance_filters is None:
        binance_filters = {}
    if not isinstance(binance_filters, dict):
        raise SettingsValidationError("binance_filters must be a mapping of symbol -> filter dict")
    for sym, filt in binance_filters.items():
        if not isinstance(filt, dict):
            raise SettingsValidationError(f"binance_filters[{sym}] must be a dict")
        for key in ("min_qty", "step_size", "min_notional"):
            if key in filt and filt[key] is not None:
                _assert_positive(f"binance_filters[{sym}].{key}", float(filt[key]))

    validated = dict(settings)  # shallow copy
    validated["cursor_mode"] = cursor_mode
    validated["backfill_window"] = backfill_window
    validated["dedup_ttl_seconds"] = dedup_ttl_seconds
    validated["dedup_cleanup_interval_seconds"] = dedup_cleanup_interval_seconds
    validated["enable_rest_backfill"] = enable_rest_backfill
    validated["hyperliquid_rest_base_url"] = rest_base_url
    validated["max_stale_ms"] = max_stale_ms
    validated["binance_filters"] = binance_filters

    # Fill config_version if missing
    if not validated.get("config_version"):
        validated["config_version"] = time.strftime("%Y%m%d%H%M%S", time.gmtime())

    # Compute config_hash over canonical content excluding any existing hash
    content_for_hash = dict(validated)
    content_for_hash.pop("config_hash", None)
    validated["config_hash"] = _stable_hash(content_for_hash)

    return validated
