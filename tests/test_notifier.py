import asyncio
import json

import pytest

from utils.notifications import Notifier
from utils.rate_limiters import SimpleRateLimiter


class DummyRequests:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        class R:
            status_code = 200
        return R()


@pytest.mark.asyncio
async def test_notifier_stdout_and_telegram_optional(monkeypatch, capsys):
    dummy_requests = DummyRequests()
    monkeypatch.setattr("utils.notifications.requests", dummy_requests)

    notifier = Notifier(
        mode="dry-run",
        rate_limiter=SimpleRateLimiter(0.0),
        telegram_enabled=True,
        telegram_bot_token="token",
        telegram_chat_id="chat",
        telegram_base_url="https://example.com",
        dedup_cooldown_sec=0.0,
    )

    await notifier.send("hello", correlation_id="cid1")
    out = capsys.readouterr().out.strip()
    assert out.startswith("[NOTIFY]")
    payload = json.loads(out.split(" ", 1)[1])
    assert payload["mode"] == "dry-run"
    assert payload["message"] == "hello"
    assert payload["correlation_id"] == "cid1"
    assert len(dummy_requests.calls) == 1
    assert dummy_requests.calls[0]["data"]["text"] == "hello"


@pytest.mark.asyncio
async def test_notifier_dedup(monkeypatch, capsys):
    dummy_requests = DummyRequests()
    monkeypatch.setattr("utils.notifications.requests", dummy_requests)

    notifier = Notifier(rate_limiter=SimpleRateLimiter(0.0), telegram_enabled=True, telegram_bot_token="t", telegram_chat_id="c", dedup_cooldown_sec=0.1)
    await notifier.send("same")
    await notifier.send("same")  # should be deduped
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert len(dummy_requests.calls) == 1
