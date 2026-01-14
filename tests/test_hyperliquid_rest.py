import asyncio
from types import SimpleNamespace

import pytest

from utils.hyperliquid_rest import HyperliquidRestAdapter, HyperliquidRestError


class DummyResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HyperliquidRestError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


async def _run_adapter(method, *args, **kwargs):
    return await method(*args, **kwargs)


@pytest.mark.asyncio
async def test_get_latest_cursor_uses_latest_fill(monkeypatch):
    # Mock requests.post to return two fills (ensure we take max)
    def fake_post(url, json, timeout):
        assert json["type"] == "userFills"
        return DummyResponse({"userFills": [{"time": 200}, {"time": 100}]})

    monkeypatch.setattr("utils.hyperliquid_rest.requests.post", fake_post)

    adapter = HyperliquidRestAdapter(wallet="0xabc")
    latest = await adapter.get_latest_cursor()
    assert latest == 200


@pytest.mark.asyncio
async def test_fetch_range_normalizes_fields(monkeypatch):
    def fake_post(url, json, timeout):
        assert json["startTime"] == 10 and json["endTime"] == 20
        return DummyResponse(
            {
                "userFills": [
                    {"txHash": "h1", "eventId": 1, "coin": "BTC", "time": 11, "px": 100, "sz": 2, "side": "buy"},
                    {"hash": "h2", "event_index": 2, "symbol": "ETH", "time": 12, "price": 200, "size": 3},
                ]
            }
        )

    monkeypatch.setattr("utils.hyperliquid_rest.requests.post", fake_post)

    adapter = HyperliquidRestAdapter(wallet="0xabc")
    events = await adapter.fetch_range(10, 20)
    assert len(events) == 2
    e1, e2 = events
    assert e1["tx_hash"] == "h1"
    assert e1["event_index"] == 1
    assert e1["symbol"] == "BTC"
    assert e1["price"] == 100
    assert e1["size"] == 2
    assert e1["timestamp"] == 11
    assert e2["tx_hash"] == "h2"
    assert e2["event_index"] == 2
    assert e2["symbol"] == "ETH"
    assert e2["price"] == 200
    assert e2["size"] == 3
