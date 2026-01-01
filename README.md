# OSRS Flipper

**OSRS Flipper** is a lightweight Python tool that finds **high-volume, high-liquidity Grand Exchange flips** for Old School RuneScape (P2P).
It pulls live price and volume data from the **OSRS Wiki Prices API** and calculates **buy price, sell price, GP required, and estimated profit** based on your available bankroll.

Designed for **real traders**, not guesswork.

Licensed under **GPLv3**.

---

## Features

* 🔄 **High-volume flips only** (avoids dead items and phantom spreads)
* 💰 Bankroll-aware position sizing split across slots (no all-in on one item)
* 📈 Automatic buy/sell price suggestions with latest/5m/24h sanity checks
* 🧮 Estimated profit **after 2% GE tax** (toggle with `--no-tax`)
* 🧹 Filters out tiny per-unit profits and stale data to reduce fake ROI spikes
* ⏱ Uses live RuneLite-fed price data
* ⚙️ Fully configurable from the command line or via the GUI
* 🪶 Lightweight, no database required

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
  Buy @ 9,850 | Sell @ 10,150 | Tax 101 | Profit/unit 199
  Qty 50 (limit 125/4h) | GP needed 492,500 | Est profit 9,950 | ROI 2.02% | Source 5m
  Volume signal: 120,000
```

---

## Configuration Options

| Flag                | Description                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------- |
| `--bank`            | GP allocated across flips                                                                   |
| `--slots`           | How many concurrent flips to budget for (prevents going all-in on one)                      |
| `--n`               | Number of results                                                                           |
| `--min-vol-24h`     | Minimum daily volume filter                                                                 |
| `--min-profit-unit` | Minimum per-unit profit (filters out 1–2 gp flips)                                          |
| `--aggr`            | Price aggressiveness (0.1 = wider margins, 0.25 = faster fills)                             |
| `--no-tax`          | Ignore GE tax in calculations                                                               |
| `--ua`              | Custom User-Agent string                                                                    |
| `--text`            | (GUI) Force text-mode output if Tk is unavailable                                           |

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
