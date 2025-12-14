#!/usr/bin/env python3
"""
OSRS high-volume flip finder (P2P).
Pulls OSRS Wiki Prices API data and prints top flips with:
- suggested buy / sell
- profit per unit (optionally after GE tax model)
- suggested qty based on your bank
- gp needed + estimated profit

Endpoints used: /mapping, /latest, /24h (fallback: /5m), /volumes
See: https://prices.runescape.wiki/  (API is community-run, fed by RuneLite)
"""

from __future__ import annotations
import argparse
import math
import sys
import time
from typing import Any, Dict, List, Tuple

import requests

BASE = "https://prices.runescape.wiki/api/v1/osrs"

def get_json(path: str, ua: str) -> Dict[str, Any]:
    url = f"{BASE}/{path}"
    r = requests.get(url, headers={"User-Agent": ua}, timeout=30)
    r.raise_for_status()
    return r.json()

def ge_tax(sell_price: int) -> int:
    # Common GE tax model used by community tooling: 1% capped at 5,000,000
    # (If you want "no tax", pass --no-tax)
    return min(int(math.floor(sell_price * 0.01)), 5_000_000)

def choose_prices(low: int, high: int, aggressiveness: float) -> Tuple[int, int]:
    """
    Suggest buy slightly above low, sell slightly below high.
    aggressiveness in [0..0.5] (0.15 default). Higher = quicker fills, smaller margin.
    """
    spread = high - low
    if spread <= 1:
        return low, high
    step = max(1, int(spread * aggressiveness))
    buy = low + step
    sell = high - step
    return buy, sell

def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=int, default=10_000_000, help="GP you want to allocate (default 10,000,000)")
    ap.add_argument("--n", type=int, default=10, help="How many items to print (default 10)")
    ap.add_argument("--min-vol-24h", type=int, default=20_000, help="Min 24h volume filter (default 20,000)")
    ap.add_argument("--aggr", type=float, default=0.15, help="Price aggressiveness (default 0.15)")
    ap.add_argument("--no-tax", action="store_true", help="Ignore GE tax in profit calc")
    ap.add_argument("--ua", type=str, default="FlipFinderScript - your@email_or_discord",
                    help="User-Agent identification string")
    args = ap.parse_args()

    ua = args.ua

    mapping = get_json("mapping", ua)  # list[dict]
    latest = get_json("latest", ua).get("data", {})  # dict[id] -> {high, low, ...}

    # Prefer /24h (daily averages + volumes). If unavailable, fall back to /5m.
    daily_mode = "24h"
    try:
        daily = get_json("24h", ua).get("data", {})
    except Exception:
        daily_mode = "5m"
        daily = get_json("5m", ua).get("data", {})

    # Extra fallback for 24h volume if needed:
    volumes = get_json("volumes", ua).get("data", {})

    rows: List[Dict[str, Any]] = []

    for item in mapping:
        if not item.get("members", False):
            continue  # P2P only

        item_id = safe_int(item.get("id"))
        lim = item.get("limit")
        limit = safe_int(lim, 0)
        if limit <= 0:
            continue

        l = latest.get(str(item_id))
        if not l:
            continue

        high = safe_int(l.get("high"))
        low = safe_int(l.get("low"))
        if high <= 0 or low <= 0 or high <= low:
            continue

        buy, sell = choose_prices(low, high, args.aggr)
        if sell <= buy:
            continue

        tax = 0 if args.no_tax else ge_tax(sell)
        profit_unit = sell - buy - tax
        if profit_unit <= 0:
            continue

        # Volume: if /24h or /5m provides highPriceVolume/lowPriceVolume, use min() to estimate "two-sided" liquidity.
        d = daily.get(str(item_id), {})
        vol_hi = safe_int(d.get("highPriceVolume"), 0)
        vol_lo = safe_int(d.get("lowPriceVolume"), 0)
        vol_twosided = min(vol_hi, vol_lo) if (vol_hi and vol_lo) else 0

        # If that’s missing, use /volumes (24h-ish total volume by id).
        vol_24h = vol_twosided if vol_twosided > 0 else safe_int(volumes.get(str(item_id), 0), 0)

        if daily_mode == "24h":
            # /24h volume is already 24h; /5m is short-window, so don’t enforce huge min-vol in that case.
            if vol_24h < args.min_vol_24h:
                continue

        # Suggested qty based on your bank + buy limit
        max_qty = min(limit, args.bank // buy)
        if max_qty <= 0:
            continue

        gp_needed = buy * max_qty
        est_profit = profit_unit * max_qty
        roi = est_profit / gp_needed if gp_needed else 0.0

        # Rank score: prioritize profit *and* liquidity (volume), while still rewarding ROI.
        score = profit_unit * max_qty * (1.0 + min(1.0, roi * 5.0))

        rows.append({
            "name": item.get("name", f"ID {item_id}"),
            "id": item_id,
            "buy": buy,
            "sell": sell,
            "tax": tax,
            "profit_unit": profit_unit,
            "qty": max_qty,
            "gp_needed": gp_needed,
            "est_profit": est_profit,
            "roi_pct": roi * 100.0,
            "limit_4h": limit,
            "vol": vol_24h,
            "score": score,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[: args.n]

    print(f"\nTop {len(top)} flips (P2P) | price window: /latest + /{daily_mode} | bank={args.bank:,} gp\n")
    for r in top:
        print(f"- {r['name']} (ID {r['id']})")
        print(f"  Buy @ {r['buy']:,} | Sell @ {r['sell']:,} | Tax {r['tax']:,} | Profit/unit {r['profit_unit']:,}")
        print(f"  Qty {r['qty']:,} (limit {r['limit_4h']:,}/4h) | GP needed {r['gp_needed']:,} | Est profit {r['est_profit']:,} | ROI {r['roi_pct']:.2f}%")
        print(f"  Volume signal: {r['vol']:,}\n")

    if not top:
        print("No candidates passed your filters. Try lowering --min-vol-24h or increasing --bank.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
