#!/usr/bin/env python3
"""
Query live positions from Hyperliquid target wallet.

This tool directly queries the Hyperliquid API to fetch the current
open positions in the target wallet, independent of the local database.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import request as url_request

from dotenv import load_dotenv

load_dotenv()


def query_wallet_positions(wallet_address: str, rest_url: str) -> Optional[Dict[str, Any]]:
    """Query positions from Hyperliquid API."""
    payload = {
        "type": "clearinghouseState",
        "user": wallet_address,
    }
    
    body = json.dumps(payload).encode("utf-8")
    req = url_request.Request(
        rest_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with url_request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        return json.loads(data)
    except Exception as exc:
        print(f"❌ API request failed: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query live positions from Hyperliquid wallet"
    )
    parser.add_argument(
        "--wallet",
        help="Wallet address (default: from HYPERLIQUID_TARGET_WALLET env)",
    )
    parser.add_argument(
        "--rest-url",
        default="https://api.hyperliquid.xyz/info",
        help="Hyperliquid REST API URL",
    )
    
    args = parser.parse_args()
    
    wallet = args.wallet or os.getenv("HYPERLIQUID_TARGET_WALLET", "")
    if not wallet:
        print("❌ No wallet address provided")
        print("   Use --wallet or set HYPERLIQUID_TARGET_WALLET environment variable")
        return 1
    
    print("=" * 80)
    print("HYPERLIQUID WALLET POSITIONS QUERY")
    print("=" * 80)
    print(f"🎯 Wallet: {wallet}")
    print(f"🌐 API: {args.rest_url}")
    print()
    
    result = query_wallet_positions(wallet, args.rest_url)
    
    if result is None:
        return 1
    
    # Extract asset positions
    asset_positions = result.get("assetPositions", [])
    
    if not asset_positions:
        print("ℹ️  No open positions found in this wallet")
        print()
        return 0
    
    print(f"✅ Found {len(asset_positions)} position(s)")
    print()
    print("-" * 80)
    
    for pos in asset_positions:
        position_data = pos.get("position", {})
        coin = position_data.get("coin", "UNKNOWN")
        entry_px = float(position_data.get("entryPx", 0))
        position_value = position_data.get("positionValue", "0")
        unrealized_pnl = position_data.get("unrealizedPnl", "0")
        leverage = position_data.get("leverage", {})
        leverage_value = leverage.get("value", "0") if isinstance(leverage, dict) else str(leverage)
        szi = float(position_data.get("szi", 0))
        
        # Determine position direction
        if szi > 0:
            direction = "📈 LONG"
        elif szi < 0:
            direction = "📉 SHORT"
        else:
            direction = "⚪ FLAT"
        
        print(f"Symbol: {coin}")
        print(f"  Direction: {direction}")
        print(f"  Size: {szi}")
        print(f"  Entry Price: ${entry_px:,.2f}")
        print(f"  Position Value: ${position_value}")
        print(f"  Unrealized PnL: ${unrealized_pnl}")
        print(f"  Leverage: {leverage_value}x")
        print()
    
    print("-" * 80)
    
    # Show raw JSON for debugging
    print()
    print("📋 Raw API Response (for debugging):")
    print(json.dumps(result, indent=2))
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
