# OSRS Flipper

**OSRS Flipper** is a lightweight Python tool that finds **high-volume, high-liquidity Grand Exchange flips** for Old School RuneScape (P2P).
It pulls live price and volume data from the **OSRS Wiki Prices API** and calculates **buy price, sell price, GP required, and estimated profit** based on your available bankroll.

Designed for **real traders**, not guesswork.

Licensed under **GPLv3**.

---

## Features

- 🔄 **High-volume flips only** (avoids dead items and phantom spreads)
- 💰 Bankroll-aware position sizing split across slots (no all-in on one item)
- 📈 Automatic buy/sell price suggestions with latest/5m/24h sanity checks
- 🧮 Estimated profit **after 2% GE tax** (toggle with `--no-tax`)
- 🧹 Filters out tiny per-unit profits and stale data to reduce fake ROI spikes
- 🔥 High alch info: HA value, HA floor (break-even buy), HA net (safety bail)
- ⏳ Risk/time cues: cycles/day, ETA to clear, profit/hr, participation %, daily caps
- 🎛️ Extra filters and safety checks: min ROI, min profit/hr, max ETA, HA-safe only, min HA net, min cycles/day, hide ∞ ETA
- 🖥️ GUI with live search, column picker, charts (selectable metrics), CSV export/copy, auto-refresh; CLI and text mode still available
- 🪶 Lightweight, no database required; uses live RuneLite-fed price data

---

## How It Works

OSRS Flipper:

1. Pulls item metadata (members, buy limits)
2. Fetches live **GE high/low prices**
3. Analyzes **24-hour trading volume**
4. Calculates safe buy/sell prices inside the spread
5. Sizes the flip based on your GP and GE limits
6. Ranks flips by **profit × liquidity**

Only items with enough daily volume are shown.

---

## Requirements

* Python **3.9+**
* Internet connection
* Optional for GUI: Tkinter (`python3-tk` on Debian/Ubuntu)

### Python Dependencies

```bash
pip install requests
```

---

## Installation

```bash
git clone https://github.com/yourusername/osrs-flipper.git
cd osrs-flipper
```

For the GUI on Debian/Ubuntu:

```bash
sudo apt-get install python3-tk
```

---

## Usage

### Basic run (10M bank default)

```bash
python3 flip_finder.py
```

### Use a 500k bankroll

```bash
python3 flip_finder.py --bank 500000
```

### Show top 10 high-volume flips

```bash
python3 flip_finder.py --bank 500000 --n 10
```

### Use the GUI

```bash
python3 flip_gui.py --bank 500000 --slots 5 --n 10 --ua "your contact"
```

If Tk is unavailable, run the same flags with `--text` to fall back to CLI output.

---

## Output Example

```
- Adamant platebody (ID 1123)
  Buy @ 9,850 | Sell @ 10,150 | Tax 203 | Profit/unit 97
  Qty 50 (limit 125/4h) | GP needed 492,500 | Est profit 4,850 | ROI 0.98% | Source 5m
  Vol 120,000 | Cycles/day 3.8 | Daily est 18,430 | Daily cap 48,500 | ETA 1.0h | Profit/hr 4,850.00
  HA value 9,984 | HA floor 9,804 | HA net -46
```

---

## Configuration Options

| Flag                | Description                                                                                   |
| ------------------- | --------------------------------------------------------------------------------------------- |
| `--bank`            | GP allocated across flips                                                                     |
| `--slots`           | How many concurrent flips to budget for (prevents going all-in on one)                        |
| `--n`               | Number of results                                                                             |
| `--min-vol-24h`     | Minimum daily volume filter                                                                   |
| `--min-profit-unit` | Minimum per-unit profit (filters out 1–2 gp flips)                                            |
| `--aggr`            | Price aggressiveness (0.1 = wider margins, 0.25 = faster fills)                               |
| `--ha-rune-cost`    | Nature rune cost used for high-alch fallback math (default 180)                               |
| `--require-ha-floor`| Only include flips where suggested buy is ≤ HA break-even                                     |
| `--no-tax`          | Ignore GE tax in calculations                                                                 |
| `--ua`              | Custom User-Agent string                                                                      |
| `--text`            | (GUI) Force text-mode output if Tk is unavailable                                             |

---

## Strategy Notes

* **Low bank (≤1M):** Runes, ammo, food, mid-tier alchables
* **Medium bank (5–20M):** Bars, ores, potions, armor
* **High bank:** Use multiple flips simultaneously

High volume matters more than raw margin.

---

## Data Source

All price and volume data comes from the
**OSRS Wiki Prices API**, powered by RuneLite user data.

[https://prices.runescape.wiki/](https://prices.runescape.wiki/)

---

## License

This project is licensed under the **GNU General Public License v3.0**.

You are free to:

* Use
* Modify
* Share
* Redistribute

As long as derivative works remain **GPLv3 licensed**.

See the `LICENSE` file for details.

---

## Disclaimer

This tool provides **estimates**, not guarantees.
Grand Exchange prices fluctuate, margins shift, and fills are not instant.

Use at your own risk — and never flip more than you can afford to park.

---

## Glossary (GUI/CLI Terms)

- **Buy / Sell**: Suggested prices inside the spread, based on aggressiveness and latest/5m/24h sanity checks.
- **Profit/u**: Profit per unit after tax (unless `--no-tax`).
- **Tax**: GE tax (2%, capped at 5m) applied to the sell price.
- **Qty**: Suggested quantity using your bank and the item’s buy limit, spread across your slots.
- **GP needed**: Total GP required for the suggested quantity at the suggested buy price.
- **Est profit**: Total profit for the suggested quantity (profit/u × qty).
- **ROI %**: Return on investment for the suggested trade (est profit ÷ GP needed).
- **Vol**: 24h-ish two-sided volume (or best available fallback) to gauge liquidity.
- **Limit/4h**: GE buy limit per 4 hours for the item.
- **Cycles/d**: Estimated number of times you can hit the buy limit in a day (vol vs limit, capped at 6).
- **Daily est**: Bank-limited expected daily profit (cycles/d × est profit).
- **Daily cap**: Theoretical daily profit if bank were unlimited (volume + limit constrained).
- **ETA / Hours to clear**: Estimated time to clear your suggested quantity based on volume.
- **Profit/hr**: Profit divided by ETA; lower volume increases ETA and reduces this number.
- **Participation %**: (Not always shown in GUI) How much of daily volume your position represents; lower is safer.
- **HA value**: High Alchemy value (gp received if you alch the item).
- **HA floor**: HA value minus rune cost (break-even buy price for alching).
- **HA net**: HA floor minus suggested buy; positive means HA is a safe bailout.
- **Price src**: Which price window was used (5m, 24h, or latest).
- **Aggressiveness (`--aggr`)**: Fraction of spread to move inside low/high; higher fills faster with smaller margin.
- **Slots**: How many concurrent flips to budget for; prevents going all-in on one item.
- **Filters (GUI)**:
  - **Min ROI %**: Drop items below this ROI.
  - **Min Profit/hr**: Drop items below this profit-per-hour-to-clear.
  - **Max ETA h**: Drop items whose ETA exceeds this number of hours.
  - **Min HA net**: Require at least this net gp from HA as a safety floor.
  - **Min Cycles/d**: Require at least this many limit cycles per day.
  - **Hide ∞ ETA**: Exclude items where ETA is effectively infinite (no volume).
- **HA-safe**: When the suggested buy is ≤ HA floor (you can alch without loss).
- **Auto-refresh** (GUI): Periodically rerun and refresh results.
- **Column picker** (GUI): Show/hide data columns; name stays in the tree column.
