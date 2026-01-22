import argparse
import json
import time
from pathlib import Path
from urllib import request

from hyperliquid.common.settings import load_settings, compute_config_hash
from hyperliquid.storage.db import init_db, assert_schema_version


def _print_kv(label: str, value) -> None:
    print(f"{label}={value}")


def _fetch_exchange_time(base_url: str) -> int:
    url = base_url.rstrip("/") + "/fapi/v1/time"
    raw = request.urlopen(url, timeout=5).read()
    payload = json.loads(raw.decode("utf-8"))
    return int(payload.get("serverTime", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ops preflight checks.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--exchange-time",
        action="store_true",
        help="Fetch exchange server time using execution.binance.base_url",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    schema_path = Path(args.schema)
    settings = load_settings(config_path, schema_path)

    _print_kv("config_hash", compute_config_hash(config_path))
    _print_kv("local_time_ms", int(time.time() * 1000))

    if args.exchange_time:
        base_url = str(
            settings.raw.get("execution", {})
            .get("binance", {})
            .get("base_url", "https://fapi.binance.com")
        )
        server_time = _fetch_exchange_time(base_url)
        _print_kv("exchange_time_ms", server_time)

    conn = init_db(settings.db_path)
    try:
        assert_schema_version(conn)
    finally:
        conn.close()
    _print_kv("schema_version", "ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
