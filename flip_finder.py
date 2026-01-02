#!/usr/bin/env python3
"""
OSRS high-volume flip finder (P2P).
Pulls OSRS Wiki Prices API data and prints top flips with:
- suggested buy / sell
- profit per unit (optionally after GE tax model)
- suggested qty based on your bank
- gp needed + estimated profit

Adds:
- High Alch floor (break-even buy price) + HA net profit if you bail to HA
- Risk/Reward as profit-per-hour-to-clear (time/liquidity risk)
- Buy-limit aware daily profit estimates + daily cap (limit+volume)

Endpoints used: /mapping, /latest, /24h (fallback: /5m), /volumes
See: https://prices.runescape.wiki/  (API is community-run, fed by RuneLite)
"""

from __future__ import annotations
import argparse
import math
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
    # GE tax is 2% capped at 5,000,000 (integer math avoids float edge cases)
    return min((sell_price * 2) // 100, 5_000_000)


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


def pick_price_window(
    item_id: int,
    latest: Dict[str, Any],
    five_min: Dict[str, Any],
    daily: Dict[str, Any],
    now_ts: float,
    max_age: int = 30 * 60,
) -> Tuple[int, int, str]:
    """
    Use a single, consistent price window to avoid mixing stale highs/lows.
    Prefer 5m averages, then 24h averages, then latest if it's fresh.
    """
    key = str(item_id)

    fm = (five_min.get(key) or {}) if five_min else {}
    hi = safe_int(fm.get("avgHighPrice"), 0)
    lo = safe_int(fm.get("avgLowPrice"), 0)
    if hi > 0 and lo > 0 and hi > lo:
        return hi, lo, "5m"

    d = (daily.get(key) or {}) if daily else {}
    hi = safe_int(d.get("avgHighPrice"), 0)
    lo = safe_int(d.get("avgLowPrice"), 0)
    if hi > 0 and lo > 0 and hi > lo:
        return hi, lo, "24h"

    l = (latest.get(key) or {}) if latest else {}
    hi = safe_int(l.get("high"), 0)
    lo = safe_int(l.get("low"), 0)
    hi_t = safe_int(l.get("highTime"), 0)
    lo_t = safe_int(l.get("lowTime"), 0)

    # Guard against stale or mismatched latest data causing fake spreads.
    if hi > 0 and lo > 0 and hi > lo:
        too_old = (hi_t and now_ts - hi_t > max_age) or (lo_t and now_ts - lo_t > max_age)
        timestamps_far_apart = hi_t and lo_t and abs(hi_t - lo_t) > max_age
        if not too_old and not timestamps_far_apart:
            return hi, lo, "latest"

    return 0, 0, ""


def find_flips(cfg: argparse.Namespace) -> List[Dict[str, Any]]:
    """Compute candidate flips using the provided configuration."""
    ua = cfg.ua
    slots = max(1, getattr(cfg, "slots", 1))
    ha_rune_cost = max(0, getattr(cfg, "ha_rune_cost", 180))
    require_ha_floor = bool(getattr(cfg, "require_ha_floor", False))

    mapping = get_json("mapping", ua)  # list[dict]
    latest = get_json("latest", ua).get("data", {})  # dict[id] -> {high, low, ...}

    # Price windows: prefer 5m averages; 24h averages as fallback.
    five_min: Dict[str, Any] = {}
    try:
        five_min = get_json("5m", ua).get("data", {})
    except Exception:
        five_min = {}

    daily: Dict[str, Any] = {}
    try:
        daily = get_json("24h", ua).get("data", {})
    except Exception:
        daily = {}

    # Extra fallback for 24h volume if needed:
    volumes: Dict[str, Any] = {}
    try:
        volumes = get_json("volumes", ua).get("data", {})
    except Exception:
        volumes = {}

    rows: List[Dict[str, Any]] = []
    now_ts = time.time()

    for item in mapping:
        if not item.get("members", False):
            continue  # P2P only

        item_id = safe_int(item.get("id"))
        lim = item.get("limit")
        limit = safe_int(lim, 0)
        if limit <= 0:
            continue

        high, low, price_src = pick_price_window(item_id, latest, five_min, daily, now_ts)
        if high <= 0 or low <= 0 or high <= low:
            continue

        buy, sell = choose_prices(low, high, cfg.aggr)
        if sell <= buy:
            continue

        # Cross-check against fresh latest to avoid phantom spreads.
        l_latest = (latest.get(str(item_id)) or {})
        l_hi = safe_int(l_latest.get("high"), 0)
        l_lo = safe_int(l_latest.get("low"), 0)
        hi_t = safe_int(l_latest.get("highTime"), 0)
        lo_t = safe_int(l_latest.get("lowTime"), 0)

        max_age = 30 * 60
        fresh_latest = (
            l_hi > 0 and l_lo > 0 and l_hi > l_lo
            and (not hi_t or now_ts - hi_t <= max_age)
            and (not lo_t or now_ts - lo_t <= max_age)
        )
        if not fresh_latest:
            continue

        # Skip if suggested prices are too far from latest (tune 0.20 as needed).
        if l_lo > 0 and abs(buy - l_lo) / l_lo > 0.20:
            continue
        if l_hi > 0 and abs(sell - l_hi) / l_hi > 0.20:
            continue

        tax = 0 if cfg.no_tax else ge_tax(sell)
        profit_unit = sell - buy - tax
        if profit_unit < cfg.min_profit_unit:
            continue

        # Volume: prefer 24h two-sided volume (min of high/low volumes)
        d = daily.get(str(item_id), {})
        vol_hi = safe_int(d.get("highPriceVolume"), 0)
        vol_lo = safe_int(d.get("lowPriceVolume"), 0)
        vol_twosided = min(vol_hi, vol_lo) if (vol_hi and vol_lo) else 0

        # If missing, fall back to 5m two-sided volume as weak signal.
        if vol_twosided == 0:
            fm = five_min.get(str(item_id), {})
            vol_hi_fm = safe_int(fm.get("highPriceVolume"), 0)
            vol_lo_fm = safe_int(fm.get("lowPriceVolume"), 0)
            vol_twosided = min(vol_hi_fm, vol_lo_fm) if (vol_hi_fm and vol_lo_fm) else 0

        # If still missing, use /volumes (24h-ish total volume by id).
        vol_24h = vol_twosided if vol_twosided > 0 else safe_int(volumes.get(str(item_id), 0), 0)

        # Only enforce 24h volume floor when we have a 24h-like signal.
        if vol_24h and vol_24h < cfg.min_vol_24h:
            continue

        # Suggested qty based on your bank + buy limit
        per_slot_bank = max(1, cfg.bank // slots)
        max_qty = min(limit, per_slot_bank // max(1, buy))
        if max_qty <= 0:
            continue

        gp_needed = buy * max_qty
        est_profit = profit_unit * max_qty
        roi = est_profit / gp_needed if gp_needed else 0.0

        # High alch fallback value (net of rune cost)
        ha_value = safe_int(item.get("highalch"), 0)
        ha_floor = (ha_value - ha_rune_cost) if ha_value > 0 else 0  # break-even buy price for HA
        ha_profit = (ha_floor - buy) if ha_value > 0 else 0          # net vs suggested buy
        ha_safe = bool(ha_value > 0 and buy <= ha_floor)

        if require_ha_floor:
            # Only keep items where your suggested buy is HA-break-even or better.
            if not ha_safe:
                continue

        # Buy-limit + timeframe metrics
        cycles_per_day = 0.0
        if vol_24h > 0 and limit > 0:
            # If daily volume is 2x the buy limit, expect ~2 cycles/day, capped at 6 (every 4h).
            cycles_per_day = min(6.0, vol_24h / max(1, limit))

        hours_to_clear = (max_qty / max(1, vol_24h)) * 24 if vol_24h > 0 else float("inf")
        days_to_clear = hours_to_clear / 24 if math.isfinite(hours_to_clear) else float("inf")

        daily_profit_est = est_profit * cycles_per_day  # your-bank-limited expected daily profit
        # Theoretical daily cap if you had infinite bank: limited by buy limit cycles AND market volume.
        daily_limit_qty = limit * 6
        daily_qty_cap = min(vol_24h, daily_limit_qty) if vol_24h > 0 else 0
        daily_profit_cap = profit_unit * daily_qty_cap

        # Participation: what % of 24h volume your position represents (lower is safer)
        participation_pct = (max_qty / vol_24h) * 100.0 if vol_24h > 0 else float("inf")

        # Risk/Reward: profit-per-hour-to-clear (higher = better; low volume increases hours -> lower score)
        profit_per_hour = (est_profit / max(0.25, hours_to_clear)) if math.isfinite(hours_to_clear) else 0.0

        # Rank score: emphasize bank-limited daily profit and liquidity
        score = daily_profit_est * (1.0 + math.log1p(max(0, vol_24h)) / 10.0)

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
            "price_src": price_src,

            # HA fallback
            "ha_value": ha_value,
            "ha_rune_cost": ha_rune_cost,
            "ha_floor": ha_floor,
            "ha_profit": ha_profit,
            "ha_safe": ha_safe,

            # Time / risk / caps
            "cycles_per_day": cycles_per_day,
            "daily_profit_est": daily_profit_est,
            "daily_profit_cap": daily_profit_cap,
            "daily_qty_cap": daily_qty_cap,
            "daily_limit_qty": daily_limit_qty,
            "hours_to_clear": hours_to_clear,
            "days_to_clear": days_to_clear,
            "participation_pct": participation_pct,
            "profit_per_hour": profit_per_hour,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=int, default=10_000_000, help="GP you want to allocate (default 10,000,000)")
    ap.add_argument("--n", type=int, default=10, help="How many items to print (default 10)")
    ap.add_argument("--min-vol-24h", type=int, default=20_000, help="Min 24h volume filter (default 20,000)")
    ap.add_argument("--aggr", type=float, default=0.15, help="Price aggressiveness (default 0.15)")
    ap.add_argument("--slots", type=int, default=5, help="How many concurrent flips to budget for (default 5)")
    ap.add_argument("--min-profit-unit", type=int, default=5, help="Minimum profit per unit to keep a flip (default 5 gp)")
    ap.add_argument("--ha-rune-cost", type=int, default=180, help="Cost of a nature rune for HA fallback calc (default 180)")
    ap.add_argument("--require-ha-floor", action="store_true",
                    help="Only include flips where suggested buy is <= High Alch break-even floor")
    ap.add_argument("--no-tax", action="store_true", help="Ignore GE tax in profit calc")
    ap.add_argument("--ua", type=str, default="FlipFinderScript - your@email_or_discord",
                    help="User-Agent identification string")
    args = ap.parse_args()

    rows = find_flips(args)
    top = rows[: args.n]

    print(
        f"\nTop {len(top)} flips (P2P) | price window: 5m avg -> 24h avg -> latest fallback | bank={args.bank:,} gp\n"
    )
    for r in top:
        print(f"- {r['name']} (ID {r['id']})")
        print(f"  Buy @ {r['buy']:,} | Sell @ {r['sell']:,} | Tax {r['tax']:,} | Profit/unit {r['profit_unit']:,}")

        eta = "∞" if r["hours_to_clear"] == float("inf") else f"{r['hours_to_clear']:.1f}h"
        part = "∞" if r["participation_pct"] == float("inf") else f"{r['participation_pct']:.2f}%"

        ha_note = ""
        if r.get("ha_value"):
            ha_note = (
                f" | HA floor {r['ha_floor']:,} (HA net {r['ha_profit']:,} @ buy)"
                f" | HA safe {'YES' if r.get('ha_safe') else 'no'}"
            )

        print(
            f"  Qty {r['qty']:,} (limit {r['limit_4h']:,}/4h) | GP needed {r['gp_needed']:,} "
            f"| Est profit {r['est_profit']:,} | ROI {r['roi_pct']:.2f}% | Source {r['price_src']}{ha_note}"
        )
        print(
            f"  Vol {r['vol']:,} | Cycles/day {r['cycles_per_day']:.1f} "
            f"| Daily est {int(r['daily_profit_est']):,} | Daily cap {int(r['daily_profit_cap']):,} "
            f"| ETA {eta} | Participation {part} | Profit/hr {r['profit_per_hour']:.2f}\n"
        )

    if not top:
        print("No candidates passed your filters. Try lowering --min-vol-24h or increasing --bank.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
