#!/usr/bin/env python3
"""
Operational tool to verify target wallet positions and recent fills on Hyperliquid.

This tool helps you verify:
1. Whether the correct target wallet is being tracked
2. Current positions in the target wallet
3. Recent trading activity (fills) in the target wallet
4. Comparison with local database records
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

# Load .env file
load_dotenv()

from hyperliquid.common.settings import load_settings
from hyperliquid.ingest.adapters.hyperliquid import HyperliquidIngestAdapter, HyperliquidIngestConfig
from hyperliquid.storage.db import init_db, assert_schema_version


def _format_timestamp(ts_ms: int) -> str:
    """Convert millisecond timestamp to readable format."""
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _now_ms() -> int:
    return int(time.time() * 1000)


def check_target_wallet(config_path: Path, schema_path: Path, hours_back: int = 24) -> int:
    """Check target wallet positions and recent activity."""
    
    # Load configuration
    settings = load_settings(config_path, schema_path)
    ingest_config = HyperliquidIngestConfig.from_settings(settings.raw)
    
    if not ingest_config.enabled:
        print("❌ Hyperliquid ingest is NOT enabled in config")
        return 1
    
    if ingest_config.mode != "live":
        print(f"ℹ️  Hyperliquid mode: {ingest_config.mode} (not live)")
        return 0
    
    print("=" * 80)
    print("HYPERLIQUID TARGET WALLET VERIFICATION")
    print("=" * 80)
    print()
    
    # Display target wallet
    target_wallet = ingest_config.target_wallet
    print(f"🎯 Target Wallet: {target_wallet}")
    print(f"🌐 REST URL: {ingest_config.rest_url}")
    print(f"🌐 WebSocket URL: {ingest_config.ws_url}")
    print()
    
    # Initialize adapter
    adapter = HyperliquidIngestAdapter(ingest_config)
    
    # Check recent fills
    print("-" * 80)
    print(f"📊 RECENT TRADING ACTIVITY (Last {hours_back} hours)")
    print("-" * 80)
    
    now_ms = _now_ms()
    since_ms = now_ms - (hours_back * 3600 * 1000)
    
    try:
        events, success = adapter.fetch_backfill_with_status(since_ms=since_ms, until_ms=now_ms)
        
        if not success:
            print("⚠️  Failed to fetch data from Hyperliquid API")
            return 1
        
        if not events:
            print(f"ℹ️  No trading activity found in the last {hours_back} hours")
            print("   This could mean:")
            print("   - The target wallet has not traded recently")
            print("   - You may be tracking the wrong wallet")
            print("   - The wallet might be inactive")
        else:
            print(f"✅ Found {len(events)} position change events")
            print()
            
            # Group by symbol for summary
            symbol_activity: Dict[str, List[Any]] = {}
            for event in events:
                if event.symbol not in symbol_activity:
                    symbol_activity[event.symbol] = []
                symbol_activity[event.symbol].append(event)
            
            print("📈 ACTIVITY SUMMARY BY SYMBOL:")
            print()
            for symbol in sorted(symbol_activity.keys()):
                symbol_events = symbol_activity[symbol]
                print(f"  {symbol}:")
                print(f"    • Total events: {len(symbol_events)}")
                
                # Get latest position
                latest = symbol_events[-1]
                print(f"    • Latest position: {latest.next_target_net_position}")
                print(f"    • Last update: {_format_timestamp(latest.timestamp_ms or 0)}")
                print()
            
            # Show recent events
            print("🔍 RECENT EVENTS (Last 10):")
            print()
            for event in events[-10:]:
                ts_str = _format_timestamp(event.timestamp_ms or 0)
                direction = "📈 LONG" if event.next_target_net_position > event.prev_target_net_position else "📉 SHORT"
                print(f"  {ts_str} | {event.symbol:10} | {direction}")
                print(f"    Position: {event.prev_target_net_position:+.4f} → {event.next_target_net_position:+.4f}")
                print(f"    TX: {event.tx_hash[:20]}...")
                print()
    
    except Exception as exc:
        print(f"❌ Error fetching data: {exc}")
        return 1
    
    # Check database records
    print("-" * 80)
    print("💾 DATABASE RECORDS")
    print("-" * 80)
    
    try:
        conn = init_db(settings.db_path)
        assert_schema_version(conn)
        
        # Count processed transactions
        cursor = conn.execute("SELECT COUNT(*) FROM processed_txs")
        tx_count = cursor.fetchone()[0]
        print(f"✅ Processed transactions in DB: {tx_count}")
        
        # Get last processed event
        cursor = conn.execute(
            "SELECT tx_hash, symbol, timestamp_ms FROM processed_txs "
            "ORDER BY timestamp_ms DESC LIMIT 1"
        )
        last_tx = cursor.fetchone()
        if last_tx:
            print(f"📅 Last processed: {last_tx[1]} at {_format_timestamp(last_tx[2])}")
            print(f"   TX: {last_tx[0][:30]}...")
        else:
            print("ℹ️  No processed transactions found in database")
        
        print()
        
        # Check order history
        cursor = conn.execute("SELECT COUNT(*) FROM order_intents")
        intent_count = cursor.fetchone()[0]
        print(f"📋 Order intents created: {intent_count}")
        
        cursor = conn.execute("SELECT COUNT(*) FROM trade_history")
        trade_count = cursor.fetchone()[0]
        print(f"💼 Trades executed: {trade_count}")
        
        conn.close()
        
    except Exception as exc:
        print(f"⚠️  Database check failed: {exc}")
    
    print()
    print("=" * 80)
    print("✅ VERIFICATION COMPLETE")
    print("=" * 80)
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Hyperliquid target wallet positions and activity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of history to fetch (default: 24)",
    )
    
    args = parser.parse_args()
    
    return check_target_wallet(
        config_path=Path(args.config),
        schema_path=Path(args.schema),
        hours_back=args.hours,
    )


if __name__ == "__main__":
    raise SystemExit(main())
