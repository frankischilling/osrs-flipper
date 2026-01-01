#!/usr/bin/env python3
"""
GUI (and text fallback) for OSRS flip finder with on-the-fly tuning and simple charts.
- Adjust bank, slots, aggressiveness, min volume, min profit/unit, etc.
- Refresh pulls latest prices and shows top flips.
- Simple bar charts visualize estimated profit and volume for the top results.

If Tkinter is not available, you can run in text mode with --text (or it will fall back automatically).
"""

from __future__ import annotations
import argparse
import sys
import threading
import webbrowser
from typing import Any, Dict, List, Tuple

from flip_finder import find_flips


DEFAULT_UA = "FlipFinderGUI - your@email_or_discord"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="OSRS flip finder GUI")
    ap.add_argument("--bank", type=int, default=500_000, help="GP bank to allocate (default 500,000)")
    ap.add_argument("--n", type=int, default=10, help="How many items to display (default 10)")
    ap.add_argument("--slots", type=int, default=5, help="Concurrent flips to budget for (default 5)")
    ap.add_argument("--aggr", type=float, default=0.15, help="Price aggressiveness (default 0.15)")
    ap.add_argument("--min-vol-24h", type=int, default=20_000, help="Minimum 24h volume to include (default 20,000)")
    ap.add_argument("--min-profit-unit", type=int, default=5, help="Minimum profit per unit (default 5 gp)")
    ap.add_argument("--no-tax", action="store_true", help="Ignore GE tax in profit calc")
    ap.add_argument("--ua", type=str, default=DEFAULT_UA, help="User-Agent string for API requests")
    ap.add_argument("--text", action="store_true", help="Force text mode (no GUI)")
    return ap


def fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "-"


def ensure_tk() -> Tuple[Any, Any]:
    try:
        import tkinter as tk  # type: ignore
        from tkinter import ttk  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise ImportError(
            "Tkinter is not installed. On Debian/Ubuntu try: sudo apt-get install python3-tk.\n"
            "If you prefer a venv, use a Python build with Tk support."
        ) from exc
    return tk, ttk


def draw_bar_chart(canvas: Any, rows: List[Dict[str, Any]], key: str, color: str, title: str) -> None:
    canvas.delete("all")
    canvas.update_idletasks()
    canvas.bar_meta = []
    width = canvas.winfo_width() or 520
    height = canvas.winfo_height() or 200
    padding = 10
    title_h = 18
    label_space = 18  # reserve space for names under bars

    canvas.create_text(padding, padding, anchor="nw", text=title, font=("TkDefaultFont", 10, "bold"))

    bars = rows[:10]
    if not bars:
        canvas.create_text(width // 2, height // 2, text="No data", fill="gray")
        return

    vals = [max(0, float(r.get(key, 0) or 0)) for r in bars]
    max_val = max(vals) if vals else 0
    if max_val <= 0:
        canvas.create_text(width // 2, height // 2, text="No data", fill="gray")
        return

    bar_area_h = height - title_h - padding * 2 - label_space
    if bar_area_h <= 0:
        return
    bar_w = (width - padding * 2) / max(len(bars), 1)

    # Estimate label width budget per bar to avoid overlap; ellipsize if needed.
    max_chars = max(4, int(bar_w // 6))  # ~6px per char in default font

    for idx, r in enumerate(bars):
        val = vals[idx]
        bar_h = 0 if max_val == 0 else (val / max_val) * bar_area_h
        x0 = padding + idx * bar_w + 4
        x1 = x0 + bar_w - 8
        y1 = height - padding - label_space
        y0 = y1 - bar_h
        canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
        raw_name = r.get("name", "item")
        name = raw_name if len(raw_name) <= max_chars else raw_name[: max_chars - 3] + "..."
        canvas.create_text(
            (x0 + x1) / 2,
            y1 + 2,
            anchor="n",
            text=name,
            font=("TkDefaultFont", 8),
            width=max(20, bar_w - 6),  # allow wrapping within the bar width
        )
        canvas.bar_meta.append({
            "bbox": (x0, x1, y0, y1 + label_space),
            "row": r,
            "key": key,
            "value": val,
            "title": title,
        })

    canvas.create_text(width - padding, padding, anchor="ne", text=f"Max: {fmt_int(max_val)}", font=("TkDefaultFont", 8))


class FlipGUI:
    def __init__(self, tk_mod: Any, ttk_mod: Any, args: argparse.Namespace) -> None:
        self.tk = tk_mod
        self.ttk = ttk_mod
        self.root = self.tk.Tk()
        self.root.title("OSRS Flip Finder")
        self.rows: List[Dict[str, Any]] = []
        self.last_top: List[Dict[str, Any]] = []
        self.row_by_iid: Dict[str, Dict[str, Any]] = {}
        self.sort_state: Dict[str, bool] = {}
        self.last_cfg: argparse.Namespace | None = None
        self._build_ui(args)

    def _build_ui(self, args: argparse.Namespace) -> None:
        tk = self.tk
        ttk = self.ttk

        # Basic styling
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", rowheight=22)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))

        controls = ttk.LabelFrame(self.root, text="Settings")
        controls.pack(fill="x", padx=8, pady=8)

        self.bank_var = tk.StringVar(value=str(args.bank))
        self.n_var = tk.StringVar(value=str(args.n))
        self.slots_var = tk.StringVar(value=str(args.slots))
        self.aggr_var = tk.StringVar(value=str(args.aggr))
        self.min_vol_var = tk.StringVar(value=str(args.min_vol_24h))
        self.min_profit_var = tk.StringVar(value=str(args.min_profit_unit))
        self.ua_var = tk.StringVar(value=args.ua)
        self.no_tax_var = tk.BooleanVar(value=bool(args.no_tax))

        row0 = ttk.Frame(controls)
        row0.pack(fill="x", pady=2)
        self._add_labeled_entry(row0, "Bank", self.bank_var, 0)
        self._add_labeled_entry(row0, "Slots", self.slots_var, 1)
        self._add_labeled_entry(row0, "Top N", self.n_var, 2)

        row1 = ttk.Frame(controls)
        row1.pack(fill="x", pady=2)
        self._add_labeled_entry(row1, "Aggressiveness", self.aggr_var, 0)
        self._add_labeled_entry(row1, "Min vol 24h", self.min_vol_var, 1)
        self._add_labeled_entry(row1, "Min profit/unit", self.min_profit_var, 2)

        row2 = ttk.Frame(controls)
        row2.pack(fill="x", pady=2)
        self._add_labeled_entry(row2, "User-Agent", self.ua_var, 0, span=2, width=40)
        ttk.Checkbutton(row2, text="No tax", variable=self.no_tax_var).grid(row=0, column=2, padx=6, sticky="w")

        btn_row = ttk.Frame(controls)
        btn_row.pack(fill="x", pady=4)
        self.refresh_btn = ttk.Button(btn_row, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side="left")
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(btn_row, textvariable=self.status_var, foreground="gray").pack(side="left", padx=10)

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)
        columns = ("name", "buy", "sell", "profit_unit", "qty", "est_profit", "roi_pct", "vol", "price_src")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "name": "Item",
            "buy": "Buy",
            "sell": "Sell",
            "profit_unit": "Profit/unit",
            "qty": "Qty",
            "est_profit": "Est profit",
            "roi_pct": "ROI %",
            "vol": "Volume",
            "price_src": "Price src",
        }
        for col, label in headings.items():
            self.tree.heading(col, text=label, command=lambda c=col: self.sort_by_column(c))
            default_w = 100
            if col == "name":
                default_w = 200
            elif col in ("profit_unit", "est_profit"):
                default_w = 110
            elif col == "roi_pct":
                default_w = 80
            elif col == "price_src":
                default_w = 90
            self.tree.column(col, width=default_w, anchor="center", stretch=True)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("even", background="#f9fbff")
        self.tree.tag_configure("odd", background="#ffffff")

        # Interaction: double-click to open wiki page; right-click context menu.
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Control-Button-1>", self._on_right_click)  # mac-style secondary click

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open wiki page", command=lambda: self._context_action("open"))
        self.menu.add_command(label="Copy summary", command=lambda: self._context_action("copy"))
        self.menu.add_command(label="Copy prices", command=lambda: self._context_action("copy_prices"))

        charts = ttk.Frame(self.root)
        charts.pack(fill="both", expand=True, padx=8, pady=4)
        self.profit_canvas = tk.Canvas(charts, height=200, bg="#f7f7f7", highlightthickness=0)
        self.vol_canvas = tk.Canvas(charts, height=200, bg="#f7f7f7", highlightthickness=0)
        self.profit_canvas.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.vol_canvas.pack(side="left", fill="both", expand=True, padx=(4, 0))
        # Redraw charts on resize to keep labels/spacing correct.
        self.profit_canvas.bind("<Configure>", lambda _e: self._redraw_charts())
        self.vol_canvas.bind("<Configure>", lambda _e: self._redraw_charts())
        # Click on bars to get details / sync selection.
        self.profit_canvas.bind("<Button-1>", lambda e: self._on_chart_click(self.profit_canvas, e))
        self.vol_canvas.bind("<Button-1>", lambda e: self._on_chart_click(self.vol_canvas, e))

        self.root.after(200, self.refresh)

    def _add_labeled_entry(self, parent: Any, label: str, var: Any, column: int, span: int = 1, width: int = 12) -> None:
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=0, column=column * 2, padx=4, sticky="w")
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=0, column=column * 2 + 1, padx=4, sticky="w")

    def refresh(self) -> None:
        try:
            cfg = argparse.Namespace(
                bank=int(self.bank_var.get() or 0),
                n=int(self.n_var.get() or 0),
                min_vol_24h=int(self.min_vol_var.get() or 0),
                aggr=float(self.aggr_var.get() or 0.0),
                slots=int(self.slots_var.get() or 1),
                min_profit_unit=int(self.min_profit_var.get() or 0),
                no_tax=bool(self.no_tax_var.get()),
                ua=self.ua_var.get() or DEFAULT_UA,
            )
        except ValueError:
            self.status_var.set("Invalid input")
            return

        self.status_var.set("Loading...")
        self.refresh_btn.state(["disabled"])
        threading.Thread(target=self._fetch_worker, args=(cfg,), daemon=True).start()

    def _fetch_worker(self, cfg: argparse.Namespace) -> None:
        err = None
        rows: List[Dict[str, Any]] = []
        try:
            rows = find_flips(cfg)
        except Exception as e:
            err = str(e)
        self.root.after(0, self._apply_results, rows, err, cfg)

    def _apply_results(self, rows: List[Dict[str, Any]], err: str | None, cfg: argparse.Namespace) -> None:
        self.refresh_btn.state(["!disabled"])
        if err:
            self.status_var.set(f"Error: {err}")
            return

        self.sort_state.clear()
        self._render_rows(rows, cfg)

    def _render_rows(self, rows: List[Dict[str, Any]], cfg: argparse.Namespace) -> None:
        self.rows = rows
        self.last_cfg = cfg
        self.row_by_iid.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        top = rows[: cfg.n]
        self.last_top = top
        for idx, r in enumerate(top):
            iid = str(r.get("id", f"row-{idx}"))
            self.row_by_iid[iid] = r
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    r.get("name", ""),
                    fmt_int(r.get("buy")),
                    fmt_int(r.get("sell")),
                    fmt_int(r.get("profit_unit")),
                    fmt_int(r.get("qty")),
                    fmt_int(r.get("est_profit")),
                    f"{r.get('roi_pct', 0):.2f}",
                    fmt_int(r.get("vol")),
                    r.get("price_src", ""),
                ),
                tags=(tag,),
            )

        self._redraw_charts()
        self.status_var.set(f"Showing top {len(top)} | bank {fmt_int(cfg.bank)} | UA set")

    def _redraw_charts(self) -> None:
        top = self.last_top if hasattr(self, "last_top") else []
        draw_bar_chart(self.profit_canvas, top, "est_profit", "#4caf50", "Estimated profit (top)")
        draw_bar_chart(self.vol_canvas, top, "vol", "#2196f3", "Volume (top)")

    def sort_by_column(self, col: str) -> None:
        if not self.rows:
            return
        reverse = not self.sort_state.get(col, False)
        numeric_cols = {"buy", "sell", "profit_unit", "qty", "est_profit", "roi_pct", "vol"}

        def sort_key(r: Dict[str, Any]) -> Any:
            v = r.get(col, "")
            if col in numeric_cols:
                try:
                    return float(v)
                except Exception:
                    return -float("inf") if reverse else float("inf")
            return str(v)

        sorted_rows = sorted(self.rows, key=sort_key, reverse=reverse)
        self.sort_state[col] = reverse
        cfg = self.last_cfg or argparse.Namespace(n=10, bank=0)
        self._render_rows(sorted_rows, cfg)

    def _on_double_click(self, event: Any) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            iid = self.tree.focus()
        self._open_wiki_for_iid(iid)

    def _on_right_click(self, event: Any) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _context_action(self, action: str) -> None:
        iid = self.tree.selection()[0] if self.tree.selection() else None
        if not iid:
            self.status_var.set("No item selected")
            return
        row = self.row_by_iid.get(iid)
        if not row:
            self.status_var.set("No data for selected item")
            return
        if action == "open":
            self._open_wiki(row)
        elif action == "copy":
            self._copy_summary(row)
        elif action == "copy_prices":
            self._copy_prices(row)

    def _open_wiki_for_iid(self, iid: str | None) -> None:
        if not iid:
            return
        row = self.row_by_iid.get(iid)
        if row:
            self._open_wiki(row)

    def _open_wiki(self, row: Dict[str, Any]) -> None:
        item_id = row.get("id")
        if not item_id:
            self.status_var.set("Missing item id")
            return
        url = f"https://prices.runescape.wiki/osrs/item/{item_id}"
        webbrowser.open_new_tab(url)
        self.status_var.set(f"Opened wiki for {row.get('name', '')}")

    def _copy_summary(self, row: Dict[str, Any]) -> None:
        summary = (
            f"{row.get('name', '')} | Buy {fmt_int(row.get('buy'))} | "
            f"Sell {fmt_int(row.get('sell'))} | Qty {fmt_int(row.get('qty'))} | "
            f"Profit/unit {fmt_int(row.get('profit_unit'))}"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(summary)
        self.status_var.set("Copied summary")

    def _copy_prices(self, row: Dict[str, Any]) -> None:
        text = f"Buy {fmt_int(row.get('buy'))} | Sell {fmt_int(row.get('sell'))} | Qty {fmt_int(row.get('qty'))}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied prices")

    def _on_chart_click(self, canvas: Any, event: Any) -> None:
        meta = getattr(canvas, "bar_meta", [])
        if not meta:
            return
        for m in meta:
            x0, x1, y0, y1 = m["bbox"]
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                row = m["row"]
                name = row.get("name", "")
                value = m.get("value", 0)
                detail = (
                    f"{name} | {m.get('title', '')}: {fmt_int(value)} | "
                    f"Buy {fmt_int(row.get('buy'))} | Sell {fmt_int(row.get('sell'))} | "
                    f"Qty {fmt_int(row.get('qty'))} | Profit/unit {fmt_int(row.get('profit_unit'))}"
                )
                # Sync selection in table
                iid = str(row.get("id"))
                if iid in self.row_by_iid:
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                    self.tree.see(iid)
                self.status_var.set(detail)
                return


def run_text_mode(args: argparse.Namespace, note: str | None = None) -> int:
    if note:
        print(note)
    rows = find_flips(args)
    top = rows[: args.n]
    print(f"\nTop {len(top)} flips (P2P) | price window: 5m avg -> 24h avg -> latest fallback | bank={args.bank:,} gp\n")
    for r in top:
        print(f"- {r['name']} (ID {r['id']})")
        print(f"  Buy @ {r['buy']:,} | Sell @ {r['sell']:,} | Tax {r['tax']:,} | Profit/unit {r['profit_unit']:,}")
        print(f"  Qty {r['qty']:,} (limit {r['limit_4h']:,}/4h) | GP needed {r['gp_needed']:,} | Est profit {r['est_profit']:,} | ROI {r['roi_pct']:.2f}% | Source {r['price_src']}")
        print(f"  Volume signal: {r['vol']:,}\n")
    if not top:
        print("No candidates passed your filters. Try lowering --min-vol-24h or increasing --bank.")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.text:
        return run_text_mode(args)

    try:
        tk_mod, ttk_mod = ensure_tk()
    except ImportError as exc:
        print(f"{exc}\nFalling back to text mode.", file=sys.stderr)
        return run_text_mode(args, note="Tk not available; using text mode.")

    gui = FlipGUI(tk_mod, ttk_mod, args)
    gui.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
