import pytest

from utils.validations import SettingsValidationError, validate_settings


def minimal_settings(**overrides):
    base = {
        "target_wallet": "0xabc",
        "exchange": "binance",
        "market_type": "future",
        "symbol_mapping": {"BTC": "BTC/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 100.0,
        "whale_estimated_balance": 1_000_000.0,
        "capital_utilization_soft_limit": 0.5,
        "capital_utilization_hard_limit": 0.7,
    }
    base.update(overrides)
    return base


def test_validate_settings_happy_path_adds_version_and_hash():
    settings = validate_settings(minimal_settings())
    assert "config_hash" in settings
    assert "config_version" in settings
    assert settings["config_hash"]  # non-empty
    assert settings["config_version"]  # non-empty
    # defaults for monitor/backfill
    assert settings["cursor_mode"] == "block"
    assert settings["backfill_window"] == 200
    assert settings["dedup_ttl_seconds"] == 86400
    assert settings["dedup_cleanup_interval_seconds"] == 300


@pytest.mark.parametrize("bad_value", ["okex", "kraken"])
def test_invalid_exchange_raises(bad_value):
    cfg = minimal_settings(exchange=bad_value)
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_kelly_requires_params():
    cfg = minimal_settings(copy_mode="kelly")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_fixed_amount_requires_amount():
    cfg = minimal_settings()
    cfg.pop("fixed_amount_usd")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_soft_limit_must_be_below_hard():
    cfg = minimal_settings(capital_utilization_soft_limit=0.9, capital_utilization_hard_limit=0.8)
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_rejects_missing_required_field():
    cfg = minimal_settings()
    cfg.pop("target_wallet")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_invalid_cursor_mode_rejected():
    cfg = minimal_settings(cursor_mode="HEIGHT")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_non_int_backfill_window_raises():
    cfg = minimal_settings(backfill_window="abc")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_rest_backfill_defaults_and_url_validation():
    cfg = minimal_settings()
    validated = validate_settings(cfg)
    assert validated["enable_rest_backfill"] is False
    assert validated["hyperliquid_rest_base_url"] == "https://api.hyperliquid.xyz/info"

    cfg_bad_url = minimal_settings(hyperliquid_rest_base_url="")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg_bad_url)


def test_rest_backfill_requires_timestamp_cursor():
    cfg = minimal_settings(enable_rest_backfill=True, cursor_mode="block")
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg)


def test_binance_filters_validation():
    cfg = minimal_settings(binance_filters={"BTC/USDT": {"min_qty": 0.001, "step_size": 0.001, "min_notional": 5}})
    validated = validate_settings(cfg)
    assert "binance_filters" in validated

    cfg_bad = minimal_settings(binance_filters={"BTC/USDT": "oops"})
    with pytest.raises(SettingsValidationError):
        validate_settings(cfg_bad)
