#!/usr/bin/env python3
"""
Verify Hyperliquid fill aggregation behavior via REST (and optional WS capture).

Outputs a JSON summary to stdout to support evidence collection before changing ingest logic.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import request as url_request
from urllib import error as url_error

from dotenv import load_dotenv

from hyperliquid.common.settings import load_settings
from hyperliquid.ingest.adapters.hyperliquid import HyperliquidIngestConfig

load_dotenv()

HASH_KEY_CANDIDATES = ("hash", "txHash", "tx_hash")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt_ts(ts_ms: int) -> str:
    return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _post_json(url: str, payload: dict, timeout_ms: int) -> Tuple[List[dict], bool]:
    body = json.dumps(payload).encode("utf-8")
    req = url_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = max(timeout_ms / 1000.0, 1.0)
    try:
        with url_request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
        parsed = json.loads(data)
        if isinstance(parsed, list):
            return parsed, True
        return [], False
    except (url_error.URLError, json.JSONDecodeError):
        return [], False


def _fetch_fills_by_time(
    *, rest_url: str, wallet: str, since_ms: int, until_ms: int, timeout_ms: int, max_fills: int
) -> Tuple[List[dict], bool]:
    fills: List[dict] = []
    success = False
    end_time = until_ms
    while end_time >= since_ms:
        payload = {
            "type": "userFillsByTime",
            "user": wallet,
            "startTime": since_ms,
            "endTime": end_time,
            "aggregateByTime": False,
        }
        batch, ok = _post_json(rest_url, payload, timeout_ms)
        if ok:
            success = True
        if not batch:
            break
        fills.extend(batch)
        if len(fills) >= max_fills:
            fills = fills[:max_fills]
            break
        oldest = _oldest_fill_time(batch)
        if oldest is None or oldest <= since_ms:
            break
        end_time = oldest - 1
    return fills, success


def _oldest_fill_time(fills: Iterable[dict]) -> Optional[int]:
    times = [int(fill.get("time", 0)) for fill in fills if "time" in fill]
    if not times:
        return None
    return min(times)


def _pick_hash_key(fills: Iterable[dict]) -> Optional[str]:
    counts = _hash_key_stats(fills)
    for key in HASH_KEY_CANDIDATES:
        if counts.get(key, 0) > 0:
            return key
    return None


def _hash_key_stats(fills: Iterable[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for key in HASH_KEY_CANDIDATES:
        counts[key] = 0
    for fill in fills:
        for key in HASH_KEY_CANDIDATES:
            if fill.get(key):
                counts[key] += 1
    return counts


def _group_key(fill: dict, hash_key: Optional[str]) -> Tuple[str, str]:
    coin = str(fill.get("coin", ""))
    if hash_key:
        tx_hash = str(fill.get(hash_key) or "")
    else:
        tx_hash = ""
    if not tx_hash:
        tx_hash = "missing_hash"
    return tx_hash, coin


def _extract_candidate_fields(fills: List[dict], limit: int) -> Dict[str, Any]:
    sample = fills[:limit]
    field_counts: Dict[str, int] = defaultdict(int)
    for fill in sample:
        for key, value in fill.items():
            if value is not None:
                field_counts[key] += 1
    return {
        "sample_size": len(sample),
        "non_null_field_counts": dict(sorted(field_counts.items())),
        "hash_key_counts": _hash_key_stats(sample),
    }


def _analyze_groups(fills: List[dict], hash_key: Optional[str]) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for fill in fills:
        groups[_group_key(fill, hash_key)].append(fill)

    group_sizes = [len(items) for items in groups.values()]
    multi_fill_groups = [k for k, v in groups.items() if len(v) > 1]

    mixed_side = 0
    time_order_issues = 0
    start_pos_variance = 0
    multi_coin_same_hash = 0
    missing_hash_groups = 0

    by_hash: Dict[str, set[str]] = defaultdict(set)

    for (tx_hash, coin), items in groups.items():
        by_hash[tx_hash].add(coin)
        if tx_hash == "missing_hash":
            missing_hash_groups += 1

        sides = {
            str(f.get("side", "")).upper()
            for f in items
            if f.get("side") is not None and str(f.get("side", "")).strip() != ""
        }
        if len(sides) > 1:
            mixed_side += 1

        start_positions = [
            float(f["startPosition"]) for f in items if f.get("startPosition") is not None
        ]
        if start_positions and (max(start_positions) - min(start_positions)) != 0:
            start_pos_variance += 1

        # Check ordering stability (time, tid)
        order = [(int(f.get("time", 0)), int(f.get("tid", 0))) for f in items]
        if order != sorted(order):
            time_order_issues += 1

    for tx_hash, coins in by_hash.items():
        if len(coins) > 1:
            multi_coin_same_hash += 1

    return {
        "total_groups": len(groups),
        "groups_with_multiple_fills": len(multi_fill_groups),
        "max_group_size": max(group_sizes) if group_sizes else 0,
        "mixed_side_groups": mixed_side,
        "start_position_variance_groups": start_pos_variance,
        "ordering_issues_groups": time_order_issues,
        "multi_coin_same_hash": multi_coin_same_hash,
        "missing_hash_groups": missing_hash_groups,
    }


def _summarize_fills(fills: List[dict]) -> Dict[str, Any]:
    times = [int(f.get("time", 0)) for f in fills if "time" in f]
    coins = Counter(str(f.get("coin", "")) for f in fills if f.get("coin") is not None)
    sides = Counter(str(f.get("side", "")).upper() for f in fills if f.get("side") is not None)
    return {
        "count": len(fills),
        "time_range": {
            "min_ms": min(times) if times else None,
            "max_ms": max(times) if times else None,
            "min_human": _fmt_ts(min(times)) if times else None,
            "max_human": _fmt_ts(max(times)) if times else None,
        },
        "coins": dict(coins.most_common(10)),
        "sides": dict(sides.most_common()),
    }


def _write_raw_dump(path: Path, fills: List[dict], limit: int) -> None:
    payload = {
        "limit": limit,
        "fills": fills[:limit],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Hyperliquid fill aggregation using REST backfill data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument("--hours", type=int, default=48, help="Hours of history to fetch")
    parser.add_argument("--wallet", help="Override target wallet address")
    parser.add_argument("--rest-url", help="Override Hyperliquid REST URL")
    parser.add_argument(
        "--max-fills",
        type=int,
        default=10000,
        help="Max fills to fetch (default: 10000)",
    )
    parser.add_argument(
        "--raw-dump",
        type=Path,
        help="Write raw fills sample to a JSON file",
    )
    parser.add_argument(
        "--raw-limit",
        type=int,
        default=200,
        help="Max raw fills to dump (default: 200)",
    )
    args = parser.parse_args()

    settings = load_settings(Path(args.config), Path(args.schema))
    ingest_config = HyperliquidIngestConfig.from_settings(settings.raw)

    wallet = args.wallet or ingest_config.target_wallet
    rest_url = args.rest_url or ingest_config.rest_url
    if not wallet:
        print("❌ No target wallet provided (config or --wallet).")
        return 1

    now_ms = _now_ms()
    since_ms = now_ms - (args.hours * 3600 * 1000)

    fills, ok = _fetch_fills_by_time(
        rest_url=rest_url,
        wallet=wallet,
        since_ms=since_ms,
        until_ms=now_ms,
        timeout_ms=ingest_config.request_timeout_ms,
        max_fills=args.max_fills,
    )

    summary: Dict[str, Any] = {
        "wallet": wallet,
        "rest_url": rest_url,
        "since_ms": since_ms,
        "until_ms": now_ms,
        "since_human": _fmt_ts(since_ms),
        "until_human": _fmt_ts(now_ms),
        "fetch_ok": ok,
        "fills_summary": _summarize_fills(fills),
        "candidate_fields": _extract_candidate_fields(fills, limit=50),
    }

    hash_key = _pick_hash_key(fills)
    summary["selected_hash_key"] = hash_key
    summary["group_analysis"] = _analyze_groups(fills, hash_key)

    if args.raw_dump:
        _write_raw_dump(args.raw_dump, fills, args.raw_limit)
        summary["raw_dump_path"] = str(args.raw_dump)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
