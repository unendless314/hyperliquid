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

    validated = dict(settings)  # shallow copy

    # Fill config_version if missing
    if not validated.get("config_version"):
        validated["config_version"] = time.strftime("%Y%m%d%H%M%S", time.gmtime())

    # Compute config_hash over canonical content excluding any existing hash
    content_for_hash = dict(validated)
    content_for_hash.pop("config_hash", None)
    validated["config_hash"] = _stable_hash(content_for_hash)

    return validated
