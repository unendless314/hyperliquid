#!/usr/bin/env python3
"""
Capture Hyperliquid userFills WebSocket messages for a short window.
Writes raw messages to a JSONL file for later analysis.
"""

from __future__ import annotations

import argparse
import json
import time
import threading
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from hyperliquid.common.settings import load_settings
from hyperliquid.ingest.adapters.hyperliquid import HyperliquidIngestConfig

try:
    import websocket  # type: ignore
except Exception as exc:  # pragma: no cover - optional dependency
    websocket = None
    websocket_error = exc
else:
    websocket_error = None

load_dotenv()


def _now_ms() -> int:
    return int(time.time() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture Hyperliquid userFills WebSocket messages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=60,
        help="Capture duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/userfills_ws_capture.jsonl"),
        help="Output JSONL file path",
    )
    args = parser.parse_args()

    if websocket is None:
        print(f"❌ websocket-client not available: {websocket_error}")
        return 1

    settings = load_settings(Path(args.config), Path(args.schema))
    ingest_config = HyperliquidIngestConfig.from_settings(settings.raw)

    if not ingest_config.target_wallet:
        print("❌ No target wallet configured (HYPERLIQUID_TARGET_WALLET required).")
        return 1

    ws_url = ingest_config.ws_url
    if not ws_url:
        print("❌ WebSocket URL not configured.")
        return 1

    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    messages: List[Dict[str, Any]] = []

    def on_open(ws) -> None:
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "userFills",
                "user": ingest_config.target_wallet,
                "aggregateByTime": False,
            },
        }
        ws.send(json.dumps(subscription))

    def on_message(_ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if payload.get("isSnapshot") is True:
            return
        data_node = payload.get("data")
        if isinstance(data_node, dict) and data_node.get("isSnapshot") is True:
            return
        if payload.get("channel") != "userFills":
            return
        data = {
            "received_ms": _now_ms(),
            "payload": payload,
        }
        messages.append(data)

    ws_app = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
    )

    thread = threading.Thread(
        target=ws_app.run_forever,
        kwargs={"ping_interval": 20, "ping_timeout": 10},
        daemon=True,
    )
    thread.start()
    time.sleep(max(args.duration_sec, 1))
    ws_app.close()
    thread.join(timeout=5)

    with output_path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    print(f"✅ Captured {len(messages)} userFills WS messages")
    print(f"📄 Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
