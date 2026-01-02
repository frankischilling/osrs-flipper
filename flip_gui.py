#!/usr/bin/env python3
"""
Better GUI for OSRS flip finder:
- Live search + extra filters (ROI, profit/hr, ETA, HA net, cycles/day, hide inf ETA)
- Auto-refresh (toggle + interval)
- Export CSV + Copy table + Copy selected row CSV
- Column picker (show/hide columns)
- Extra context actions: open OSRS wiki / prices page
"""

from __future__ import annotations
import argparse
import csv
import os
import sys
import threading
import time
import webbrowser
from typing import Any, Dict, List, Tuple, Optional
from flip_finder import find_flips

DEFAULT_UA = "FlipFinderGUI - your@email_or_discord"
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".flipfinder_gui.json")

CHART_OPTIONS: List[Tuple[str, str]] = [
    ("est_profit", "Est profit (your qty)"),
    ("vol", "Volume (24h)"),
    ("profit_unit", "Profit/unit"),
    ("roi_pct", "ROI %"),
    ("daily_profit_est", "Daily est profit (bank)"),
    ("daily_profit_cap", "Daily profit cap (limit+vol)"),
    ("cycles_per_day", "Cycles/day"),
    ("hours_to_clear", "ETA to clear (hours)"),
    ("profit_per_hour", "Profit/hr (risk/reward)"),
    ("ha_profit", "HA net (vs buy)"),
]

CHART_COLOR = {
    "est_profit": "#4caf50",
    "daily_profit_est": "#4caf50",
    "daily_profit_cap": "#4caf50",
    "vol": "#2196f3",
    "profit_per_hour": "#ff9800",
    "hours_to_clear": "#9c27b0",
    "roi_pct": "#607d8b",
    "profit_unit": "#607d8b",
    "cycles_per_day": "#795548",
    "ha_profit": "#f44336",
}

# Full column set (visible columns exclude the name; tree column shows icon+name)
ALL_COLUMNS = (
    "buy", "sell", "profit_unit", "qty", "gp_needed", "est_profit",
    "roi_pct", "vol", "limit_4h", "cycles_per_day", "daily_profit_est",
    "daily_profit_cap", "hours_to_clear", "profit_per_hour", "ha_value", "ha_floor", "ha_profit", "price_src"
)

COLUMN_HEADINGS = {
    "buy": "Buy",
    "sell": "Sell",
    "profit_unit": "Profit/u",
    "qty": "Qty",
    "gp_needed": "GP needed",
    "est_profit": "Est profit",
    "roi_pct": "ROI %",
    "vol": "Vol",
    "limit_4h": "Limit/4h",
    "cycles_per_day": "Cycles/d",
    "daily_profit_est": "Daily est",
    "daily_profit_cap": "Daily cap",
    "hours_to_clear": "ETA h",
    "profit_per_hour": "Profit/hr",
    "ha_value": "HA value",
    "ha_floor": "HA floor",
    "ha_profit": "HA net",
    "price_src": "Src",
}

COLUMN_WIDTHS = {
    "buy": 90,
    "sell": 90,
    "profit_unit": 90,
    "qty": 85,
    "gp_needed": 120,
    "est_profit": 120,
    "roi_pct": 75,
    "vol": 110,
    "limit_4h": 90,
    "cycles_per_day": 90,
    "daily_profit_est": 120,
    "daily_profit_cap": 120,
    "hours_to_clear": 90,
    "profit_per_hour": 105,
    "ha_value": 110,
    "ha_floor": 100,
    "ha_profit": 100,
    "price_src": 70,
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="OSRS flip finder GUI")
    ap.add_argument("--bank", type=int, default=500_000)
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--slots", type=int, default=5)
    ap.add_argument("--aggr", type=float, default=0.15)
    ap.add_argument("--min-vol-24h", type=int, default=20_000)
    ap.add_argument("--min-profit-unit", type=int, default=5)
    ap.add_argument("--ha-rune-cost", type=int, default=180)
    ap.add_argument("--require-ha-floor", action="store_true")
    ap.add_argument("--no-tax", action="store_true")
    ap.add_argument("--ua", type=str, default=DEFAULT_UA)
    ap.add_argument("--text", action="store_true")
    return ap


def fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "-"


def fmt_float(n: Any, places: int = 2) -> str:
    try:
        return f"{float(n):.{places}f}"
    except Exception:
        return "-"


def fmt_eta_hours(h: Any) -> str:
    try:
        hh = float(h)
        if hh == float("inf"):
            return "∞"
        return f"{hh:.1f}"
    except Exception:
        return "-"


def fmt_value(key: str, v: Any) -> str:
    if key in {"roi_pct", "profit_per_hour"}:
        return fmt_float(v, 2)
    if key in {"cycles_per_day"}:
        return fmt_float(v, 1)
    if key in {"hours_to_clear"}:
        return fmt_eta_hours(v)
    return fmt_int(v)


def ensure_tk() -> Tuple[Any, Any, Any, Any]:
    try:
        import tkinter as tk  # type: ignore
        from tkinter import ttk  # type: ignore
        from tkinter import filedialog  # type: ignore
        from tkinter import messagebox  # type: ignore
    except ImportError as exc:
        raise ImportError("Tkinter not installed. Debian/Ubuntu: sudo apt-get install python3-tk") from exc
    return tk, ttk, filedialog, messagebox


def draw_bar_chart(canvas: Any, rows: List[Dict[str, Any]], key: str, title: str) -> None:
    canvas.delete("all")
    canvas.update_idletasks()
    canvas.bar_meta = []

    width = canvas.winfo_width() or 520
    height = canvas.winfo_height() or 200
    padding = 10
    title_h = 18
    label_space = 18

    canvas.create_text(padding, padding, anchor="nw", text=title, font=("TkDefaultFont", 10, "bold"))

    bars = rows[:10]
    if not bars:
        canvas.create_text(width // 2, height // 2, text="No data", fill="gray")
        return

    vals: List[float] = []
    for r in bars:
        x = r.get(key, 0)
        try:
            f = float(x)
            if f == float("inf"):
                f = 0.0
            vals.append(max(0.0, f))
        except Exception:
            vals.append(0.0)

    max_val = max(vals) if vals else 0.0
    if max_val <= 0:
        canvas.create_text(width // 2, height // 2, text="No data", fill="gray")
        return

    bar_area_h = height - title_h - padding * 2 - label_space
    if bar_area_h <= 0:
        return

    bar_w = (width - padding * 2) / max(len(bars), 1)
    max_chars = max(4, int(bar_w // 6))
    color = CHART_COLOR.get(key, "#777777")

    for idx, r in enumerate(bars):
        val = vals[idx]
        bar_h = (val / max_val) * bar_area_h if max_val else 0
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
            width=max(20, bar_w - 6),
        )

        canvas.bar_meta.append({
            "bbox": (x0, x1, y0, y1 + label_space),
            "row": r,
            "key": key,
            "value": r.get(key, 0),
            "title": title,
        })

    canvas.create_text(width - padding, padding, anchor="ne",
                       text=f"Max: {fmt_value(key, max_val)}", font=("TkDefaultFont", 8))


class FlipGUI:
    def __init__(self, tk_mod: Any, ttk_mod: Any, filedialog_mod: Any, messagebox_mod: Any, args: argparse.Namespace) -> None:
        self.tk = tk_mod
        self.ttk = ttk_mod
        self.filedialog = filedialog_mod
        self.messagebox = messagebox_mod

        self.root = self.tk.Tk()
        self.root.title("OSRS Flip Finder")
        self.root.geometry("1500x880")

        self._lock = threading.Lock()
        self._refresh_inflight = False
        self._auto_job: Optional[str] = None
        self._search_job: Optional[str] = None

        self.all_rows: List[Dict[str, Any]] = []  # raw results from find_flips (sorted)
        self.rows: List[Dict[str, Any]] = []      # filtered/sorted view used by table
        self.last_top: List[Dict[str, Any]] = []

        self.row_by_iid: Dict[str, Dict[str, Any]] = {}
        self.sort_state: Dict[str, bool] = {}
        self.last_cfg: argparse.Namespace | None = None

        # column visibility
        self.visible_columns: List[str] = list(ALL_COLUMNS)

        self._build_ui(args)
        self._load_settings()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self.refresh)

    # ---------- UI BUILD ----------
    def _build_ui(self, args: argparse.Namespace) -> None:
        tk = self.tk
        ttk = self.ttk

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", rowheight=22)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))

        # Menu bar
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export CSV…", command=self.export_csv)
        file_menu.add_command(label="Copy table (TSV)", command=self.copy_table)
        file_menu.add_separator()
        file_menu.add_command(label="Save settings", command=self._save_settings)
        file_menu.add_command(label="Reload settings", command=self._load_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Choose columns…", command=self.open_column_picker)
        view_menu.add_command(label="Reset columns", command=self.reset_columns)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

        # Controls
        controls = ttk.LabelFrame(self.root, text="Settings")
        controls.pack(fill="x", padx=8, pady=8)

        self.bank_var = tk.StringVar(value=str(args.bank))
        self.n_var = tk.StringVar(value=str(args.n))
        self.slots_var = tk.StringVar(value=str(args.slots))
        self.aggr_var = tk.StringVar(value=str(args.aggr))
        self.min_vol_var = tk.StringVar(value=str(args.min_vol_24h))
        self.min_profit_var = tk.StringVar(value=str(args.min_profit_unit))
        self.ha_rune_cost_var = tk.StringVar(value=str(args.ha_rune_cost))
        self.ua_var = tk.StringVar(value=args.ua)
        self.no_tax_var = tk.BooleanVar(value=bool(args.no_tax))
        self.require_ha_var = tk.BooleanVar(value=bool(args.require_ha_floor))

        # Filters
        self.search_var = tk.StringVar(value="")
        self.f_min_roi_var = tk.StringVar(value="")
        self.f_min_pph_var = tk.StringVar(value="")
        self.f_max_eta_var = tk.StringVar(value="")
        self.f_min_ha_var = tk.StringVar(value="")
        self.f_min_cycles_var = tk.StringVar(value="")
        self.f_hide_inf_eta = tk.BooleanVar(value=False)

        # Auto refresh
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.auto_refresh_sec_var = tk.StringVar(value="30")

        # Charts (store label in var for nicer UI)
        chart_labels = [lbl for _, lbl in CHART_OPTIONS]
        self._chart_key_by_label = {lbl: key for key, lbl in CHART_OPTIONS}
        self._chart_label_by_key = {key: lbl for key, lbl in CHART_OPTIONS}

        self.chart_left_label_var = tk.StringVar(value=self._chart_label_by_key.get("est_profit", chart_labels[0]))
        self.chart_right_label_var = tk.StringVar(value=self._chart_label_by_key.get("vol", chart_labels[1]))

        # Row 0
        row0 = ttk.Frame(controls)
        row0.pack(fill="x", pady=2)
        self._add_labeled_entry(row0, "Bank", self.bank_var, 0)
        self._add_labeled_entry(row0, "Slots", self.slots_var, 1)
        self._add_labeled_entry(row0, "Show N", self.n_var, 2)
        ttk.Label(row0, text="Search").grid(row=0, column=6, padx=4, sticky="w")
        search_entry = ttk.Entry(row0, textvariable=self.search_var, width=22)
        search_entry.grid(row=0, column=7, padx=4, sticky="w")
        search_entry.bind("<KeyRelease>", lambda _e: self._debounced_apply_filters())

        # Row 1
        row1 = ttk.Frame(controls)
        row1.pack(fill="x", pady=2)
        self._add_labeled_entry(row1, "Aggressiveness", self.aggr_var, 0)
        self._add_labeled_entry(row1, "Min vol 24h", self.min_vol_var, 1)
        self._add_labeled_entry(row1, "Min profit/u", self.min_profit_var, 2)

        # Row 2
        row2 = ttk.Frame(controls)
        row2.pack(fill="x", pady=2)
        self._add_labeled_entry(row2, "Nat rune cost", self.ha_rune_cost_var, 0)
        ttk.Checkbutton(row2, text="Require HA-safe", variable=self.require_ha_var).grid(row=0, column=2, padx=6, sticky="w")
        ttk.Checkbutton(row2, text="No tax", variable=self.no_tax_var).grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(row2, text="Auto").grid(row=0, column=4, padx=(14, 4), sticky="e")
        ttk.Checkbutton(row2, variable=self.auto_refresh_var, command=self._toggle_auto_refresh).grid(row=0, column=5, padx=4, sticky="w")
        ttk.Label(row2, text="every").grid(row=0, column=6, padx=4, sticky="e")
        ttk.Entry(row2, textvariable=self.auto_refresh_sec_var, width=6).grid(row=0, column=7, padx=4, sticky="w")
        ttk.Label(row2, text="sec").grid(row=0, column=8, padx=4, sticky="w")

        # Row 3 UA
        row3 = ttk.Frame(controls)
        row3.pack(fill="x", pady=2)
        self._add_labeled_entry(row3, "User-Agent", self.ua_var, 0, span=2, width=46)

        # Filter row
        filt = ttk.LabelFrame(self.root, text="Filters (applied after results load)")
        filt.pack(fill="x", padx=8, pady=(0, 8))

        fr = ttk.Frame(filt)
        fr.pack(fill="x", pady=4)
        self._add_labeled_entry(fr, "Min ROI %", self.f_min_roi_var, 0, width=10)
        self._add_labeled_entry(fr, "Min Profit/hr", self.f_min_pph_var, 1, width=10)
        self._add_labeled_entry(fr, "Max ETA h", self.f_max_eta_var, 2, width=10)
        self._add_labeled_entry(fr, "Min HA net", self.f_min_ha_var, 3, width=10)
        self._add_labeled_entry(fr, "Min Cycles/d", self.f_min_cycles_var, 4, width=10)
        ttk.Checkbutton(fr, text="Hide ∞ ETA", variable=self.f_hide_inf_eta, command=self.apply_filters_now).grid(row=0, column=10, padx=10, sticky="w")
        ttk.Button(fr, text="Apply filters", command=self.apply_filters_now).grid(row=0, column=11, padx=8, sticky="w")
        ttk.Button(fr, text="Clear filters", command=self.clear_filters).grid(row=0, column=12, padx=8, sticky="w")

        # Charts row
        charts_picker = ttk.LabelFrame(self.root, text="Charts")
        charts_picker.pack(fill="x", padx=8, pady=(0, 8))

        cr = ttk.Frame(charts_picker)
        cr.pack(fill="x", pady=4)
        ttk.Label(cr, text="Chart A").grid(row=0, column=0, padx=4, sticky="w")
        self.chart_a = ttk.Combobox(cr, textvariable=self.chart_left_label_var, width=34, state="readonly",
                                    values=[lbl for _, lbl in CHART_OPTIONS])
        self.chart_a.grid(row=0, column=1, padx=4, sticky="w")
        ttk.Label(cr, text="Chart B").grid(row=0, column=2, padx=12, sticky="w")
        self.chart_b = ttk.Combobox(cr, textvariable=self.chart_right_label_var, width=34, state="readonly",
                                    values=[lbl for _, lbl in CHART_OPTIONS])
        self.chart_b.grid(row=0, column=3, padx=4, sticky="w")
        self.chart_a.bind("<<ComboboxSelected>>", lambda _e: self._redraw_charts())
        self.chart_b.bind("<<ComboboxSelected>>", lambda _e: self._redraw_charts())

        # Buttons + status
        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_btn = ttk.Button(btn_row, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side="left")
        ttk.Button(btn_row, text="Export CSV…", command=self.export_csv).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Copy table", command=self.copy_table).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Columns…", command=self.open_column_picker).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(btn_row, textvariable=self.status_var, foreground="gray").pack(side="left", padx=12)

        # Table
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)

        col_tcl = " ".join(ALL_COLUMNS)
        self.tree = ttk.Treeview(
            table_frame,
            columns=col_tcl,
            displaycolumns=col_tcl,
            show="tree headings",
            height=16
        )
        # Force apply
        self.tree["columns"] = ALL_COLUMNS
        self.tree["displaycolumns"] = tuple(self.visible_columns)
        self.tree.heading("#0", text="Item")
        self.tree.column("#0", width=260, minwidth=160, anchor="w", stretch=False)

        for col in ALL_COLUMNS:
            label = COLUMN_HEADINGS.get(col, col)
            self.tree.heading(col, text=label, command=lambda c=col: self.sort_by_column(c))
            self.tree.column(col, width=COLUMN_WIDTHS.get(col, 90), minwidth=60, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.tag_configure("even", background="#f9fbff")
        self.tree.tag_configure("odd", background="#ffffff")

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Control-Button-1>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_row)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open Prices page", command=lambda: self._context_action("open_prices"))
        self.menu.add_command(label="Open OSRS Wiki page", command=lambda: self._context_action("open_osrs_wiki"))
        self.menu.add_separator()
        self.menu.add_command(label="Copy summary", command=lambda: self._context_action("copy"))
        self.menu.add_command(label="Copy prices", command=lambda: self._context_action("copy_prices"))
        self.menu.add_command(label="Copy row CSV", command=lambda: self._context_action("copy_row_csv"))

        # Charts area
        charts = self.ttk.Frame(self.root)
        charts.pack(fill="both", expand=False, padx=8, pady=6)
        self.chart_left = tk.Canvas(charts, height=220, bg="#f7f7f7", highlightthickness=0)
        self.chart_right = tk.Canvas(charts, height=220, bg="#f7f7f7", highlightthickness=0)
        self.chart_left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.chart_right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.chart_left.bind("<Configure>", lambda _e: self._redraw_charts())
        self.chart_right.bind("<Configure>", lambda _e: self._redraw_charts())
        self.chart_left.bind("<Button-1>", lambda e: self._on_chart_click(self.chart_left, e))
        self.chart_right.bind("<Button-1>", lambda e: self._on_chart_click(self.chart_right, e))

        # Hotkeys
        self.root.bind("<Control-r>", lambda _e: self.refresh())
        self.root.bind("<Control-f>", lambda _e: search_entry.focus_set())

    def _add_labeled_entry(self, parent: Any, label: str, var: Any, column: int, span: int = 1, width: int = 12) -> None:
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=0, column=column * 2, padx=4, sticky="w")
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=0, column=column * 2 + 1, padx=4, sticky="w")
        if span > 1:
            entry.grid_configure(columnspan=span * 2 - 1)

    # ---------- Refresh / Fetch ----------
    def refresh(self) -> None:
        if self._refresh_inflight:
            return

        try:
            cfg = argparse.Namespace(
                bank=int(self.bank_var.get() or 0),
                n=int(self.n_var.get() or 0),
                min_vol_24h=int(self.min_vol_var.get() or 0),
                aggr=float(self.aggr_var.get() or 0.0),
                slots=int(self.slots_var.get() or 1),
                min_profit_unit=int(self.min_profit_var.get() or 0),
                ha_rune_cost=int(self.ha_rune_cost_var.get() or 180),
                require_ha_floor=bool(self.require_ha_var.get()),
                no_tax=bool(self.no_tax_var.get()),
                ua=self.ua_var.get() or DEFAULT_UA,
            )
        except ValueError:
            self.status_var.set("Invalid input")
            return

        self.last_cfg = cfg
        self.status_var.set("Loading…")
        self.refresh_btn.state(["disabled"])
        self._refresh_inflight = True
        threading.Thread(target=self._fetch_worker, args=(cfg,), daemon=True).start()

    def _fetch_worker(self, cfg: argparse.Namespace) -> None:
        err = None
        rows: List[Dict[str, Any]] = []
        try:
            rows = find_flips(cfg)
        except Exception as e:
            err = str(e)
        self.root.after(0, self._apply_results, rows, err, cfg)

    def _apply_results(self, rows: List[Dict[str, Any]], err: Optional[str], cfg: argparse.Namespace) -> None:
        self._refresh_inflight = False
        self.refresh_btn.state(["!disabled"])

        if err:
            self.status_var.set(f"Error: {err}")
            return

        self.sort_state.clear()
        self.all_rows = rows or []
        self.apply_filters_now()
        ts = time.strftime("%H:%M:%S")
        self.status_var.set(f"Loaded {len(self.all_rows)} candidates @ {ts} | Showing {len(self.last_top)}")

    # ---------- Filters ----------
    def _debounced_apply_filters(self) -> None:
        if self._search_job:
            try:
                self.root.after_cancel(self._search_job)
            except Exception:
                pass
        self._search_job = self.root.after(200, self.apply_filters_now)

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.f_min_roi_var.set("")
        self.f_min_pph_var.set("")
        self.f_max_eta_var.set("")
        self.f_min_ha_var.set("")
        self.f_min_cycles_var.set("")
        self.f_hide_inf_eta.set(False)
        self.apply_filters_now()

    def apply_filters_now(self) -> None:
        rows = list(self.all_rows)

        # parse filters
        name_q = (self.search_var.get() or "").strip().lower()

        def parse_float(s: str) -> Optional[float]:
            s = (s or "").strip()
            if not s:
                return None
            try:
                return float(s)
            except Exception:
                return None

        def parse_int(s: str) -> Optional[int]:
            s = (s or "").strip()
            if not s:
                return None
            try:
                return int(float(s))
            except Exception:
                return None

        min_roi = parse_float(self.f_min_roi_var.get() or "")
        min_pph = parse_float(self.f_min_pph_var.get() or "")
        max_eta = parse_float(self.f_max_eta_var.get() or "")
        min_ha = parse_int(self.f_min_ha_var.get() or "")
        min_cycles = parse_float(self.f_min_cycles_var.get() or "")
        hide_inf = bool(self.f_hide_inf_eta.get())

        filtered: List[Dict[str, Any]] = []
        for r in rows:
            if name_q and name_q not in str(r.get("name", "")).lower():
                continue

            if min_roi is not None:
                try:
                    if float(r.get("roi_pct", 0.0) or 0.0) < min_roi:
                        continue
                except Exception:
                    continue

            if min_pph is not None:
                try:
                    if float(r.get("profit_per_hour", 0.0) or 0.0) < min_pph:
                        continue
                except Exception:
                    continue

            if min_cycles is not None:
                try:
                    if float(r.get("cycles_per_day", 0.0) or 0.0) < min_cycles:
                        continue
                except Exception:
                    continue

            if min_ha is not None:
                try:
                    if int(r.get("ha_profit", 0) or 0) < min_ha:
                        continue
                except Exception:
                    continue

            eta = r.get("hours_to_clear", float("inf"))
            try:
                eta_f = float(eta)
            except Exception:
                eta_f = float("inf")

            if hide_inf and eta_f == float("inf"):
                continue

            if max_eta is not None:
                if eta_f == float("inf") or eta_f > max_eta:
                    continue

            filtered.append(r)

        # keep existing sort if user clicked a column; otherwise keep the native ordering from find_flips (score-sorted)
        self.rows = filtered

        # render (top N)
        cfg = self.last_cfg or argparse.Namespace(n=int(self.n_var.get() or 25), bank=int(self.bank_var.get() or 0))
        self._render_rows(self.rows, cfg)

    # ---------- Render ----------
    def _render_rows(self, rows: List[Dict[str, Any]], cfg: argparse.Namespace) -> None:
        self.row_by_iid.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        n = int(cfg.n) if getattr(cfg, "n", None) is not None else int(self.n_var.get() or 25)
        top = rows[: max(0, n)]
        self.last_top = top

        display_cols = tuple(self.visible_columns)
        self.tree["displaycolumns"] = display_cols

        for idx, r in enumerate(top):
            iid = str(r.get("id", f"row-{idx}"))
            self.row_by_iid[iid] = r
            tag = "even" if idx % 2 == 0 else "odd"

            values = []
            for col in ALL_COLUMNS:
                if col == "price_src":
                    values.append(str(r.get(col, "")))
                else:
                    values.append(fmt_value(col, r.get(col)))

            name_text = r.get("name") or f"ID {r.get('id', '')}"

            self.tree.insert("", "end", iid=iid, text=name_text, values=tuple(values), tags=(tag,))

        self._redraw_charts()

        ts = time.strftime("%H:%M:%S")
        self.status_var.set(
            f"Showing {len(top)}/{len(rows)} (filtered) | total {len(self.all_rows)} | bank {fmt_int(getattr(cfg, 'bank', 0))} | {ts}"
        )

    def _redraw_charts(self) -> None:
        top = self.last_top

        left_key = self._chart_key_by_label.get(self.chart_left_label_var.get(), "est_profit")
        right_key = self._chart_key_by_label.get(self.chart_right_label_var.get(), "vol")
        left_title = self.chart_left_label_var.get() or left_key
        right_title = self.chart_right_label_var.get() or right_key

        draw_bar_chart(self.chart_left, top, left_key, left_title)
        draw_bar_chart(self.chart_right, top, right_key, right_title)

    # ---------- Sorting ----------
    def sort_by_column(self, col: str) -> None:
        if not self.rows:
            return
        reverse = not self.sort_state.get(col, False)

        numeric_cols = {
            "buy", "sell", "profit_unit", "qty", "gp_needed", "est_profit", "roi_pct", "vol",
            "limit_4h", "cycles_per_day", "daily_profit_est", "daily_profit_cap",
            "hours_to_clear", "profit_per_hour", "ha_floor", "ha_profit"
        }

        def sort_key(r: Dict[str, Any]) -> Any:
            v = r.get(col, "")
            if col in numeric_cols:
                try:
                    f = float(v)
                    if f == float("inf"):
                        return 1e30 if reverse else -1e30
                    return f
                except Exception:
                    return -1e30 if reverse else 1e30
            return str(v)

        self.rows = sorted(self.rows, key=sort_key, reverse=reverse)
        self.sort_state[col] = reverse
        cfg = self.last_cfg or argparse.Namespace(n=int(self.n_var.get() or 25), bank=int(self.bank_var.get() or 0))
        self._render_rows(self.rows, cfg)

    # ---------- Context + Clicks ----------
    def _on_double_click(self, event: Any) -> None:
        iid = self.tree.identify_row(event.y) or self.tree.focus()
        self._open_prices_for_iid(iid)

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

        if action == "open_prices":
            self._open_prices(row)
        elif action == "open_osrs_wiki":
            self._open_osrs_wiki(row)
        elif action == "copy":
            self._copy_summary(row)
        elif action == "copy_prices":
            self._copy_prices(row)
        elif action == "copy_row_csv":
            self._copy_row_csv(row)

    def _open_prices_for_iid(self, iid: Optional[str]) -> None:
        if not iid:
            return
        row = self.row_by_iid.get(iid)
        if row:
            self._open_prices(row)

    def _open_prices(self, row: Dict[str, Any]) -> None:
        item_id = row.get("id")
        if not item_id:
            self.status_var.set("Missing item id")
            return
        url = f"https://prices.runescape.wiki/osrs/item/{item_id}"
        webbrowser.open_new_tab(url)

    def _open_osrs_wiki(self, row: Dict[str, Any]) -> None:
        item_id = row.get("id")
        if not item_id:
            self.status_var.set("Missing item id")
            return
        url = f"https://oldschool.runescape.wiki/w/Special:Lookup?type=item&id={item_id}"
        webbrowser.open_new_tab(url)

    def _copy_summary(self, row: Dict[str, Any]) -> None:
        text = self._detail_text(row, brief=False)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied summary")

    def _copy_prices(self, row: Dict[str, Any]) -> None:
        text = f"Buy {fmt_int(row.get('buy'))} | Sell {fmt_int(row.get('sell'))} | Qty {fmt_int(row.get('qty'))}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Copied prices")

    def _copy_row_csv(self, row: Dict[str, Any]) -> None:
        cols = list(self.visible_columns)
        # always include name/id even if hidden (helpful)
        base_cols = ["name", "id"]
        out_cols = base_cols + [c for c in cols if c not in base_cols]
        values = []
        for c in out_cols:
            if c == "id":
                values.append(str(row.get("id", "")))
            elif c == "name":
                values.append(str(row.get("name", "")))
            else:
                values.append(str(row.get(c, "")))
        csv_line = ",".join(v.replace(",", " ") for v in values)
        self.root.clipboard_clear()
        self.root.clipboard_append(csv_line)
        self.status_var.set("Copied row CSV")

    def _on_chart_click(self, canvas: Any, event: Any) -> None:
        meta = getattr(canvas, "bar_meta", [])
        if not meta:
            return
        for m in meta:
            x0, x1, y0, y1 = m["bbox"]
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                row = m["row"]
                key = m.get("key", "")
                value = m.get("value", 0)
                detail = f"{m.get('title', '')}: {fmt_value(key, value)} | {self._detail_text(row, brief=True)}"
                iid = str(row.get("id"))
                if iid in self.row_by_iid:
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                    self.tree.see(iid)
                self.status_var.set(detail)
                return

    def _on_select_row(self, _event: Any) -> None:
        iid = self.tree.selection()[0] if self.tree.selection() else None
        if not iid:
            return
        row = self.row_by_iid.get(iid)
        if row:
            self.status_var.set(self._detail_text(row, brief=False))

    def _detail_text(self, row: Dict[str, Any], brief: bool = False) -> str:
        eta = row.get("hours_to_clear", float("inf"))
        eta_txt = "∞" if eta == float("inf") else f"{float(eta):.1f}h"
        base = (
            f"{row.get('name', '')} | Buy {fmt_int(row.get('buy'))} | Sell {fmt_int(row.get('sell'))} | "
            f"Qty {fmt_int(row.get('qty'))} | Profit/u {fmt_int(row.get('profit_unit'))}"
        )
        if brief:
            return base

        extras = (
            f" | ROI {fmt_float(row.get('roi_pct', 0), 2)}% | Vol {fmt_int(row.get('vol'))}"
            f" | Limit/4h {fmt_int(row.get('limit_4h'))} | Cycles/d {fmt_float(row.get('cycles_per_day', 0), 1)}"
            f" | Daily est {fmt_int(row.get('daily_profit_est'))} | Daily cap {fmt_int(row.get('daily_profit_cap'))}"
            f" | ETA {eta_txt} | Profit/hr {fmt_float(row.get('profit_per_hour', 0), 2)}"
            f" | HA value {fmt_int(row.get('ha_value'))} | HA floor {fmt_int(row.get('ha_floor'))} | HA net {fmt_int(row.get('ha_profit'))}"
        )
        return base + extras

    # ---------- Columns ----------
    def open_column_picker(self) -> None:
        tk = self.tk
        ttk = self.ttk

        win = tk.Toplevel(self.root)
        win.title("Choose columns")
        win.geometry("420x520")
        win.transient(self.root)
        win.grab_set()

        info = ttk.Label(win, text="Toggle which columns are visible.", foreground="gray")
        info.pack(padx=10, pady=8, anchor="w")

        box = ttk.Frame(win)
        box.pack(fill="both", expand=True, padx=10, pady=6)

        canvas = tk.Canvas(box, highlightthickness=0)
        scroll = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)

        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        vars_by_col: Dict[str, Any] = {}
        for c in ALL_COLUMNS:
            v = tk.BooleanVar(value=(c in self.visible_columns))
            vars_by_col[c] = v
            ttk.Checkbutton(inner, text=f"{COLUMN_HEADINGS.get(c, c)}  ({c})", variable=v).pack(anchor="w", pady=2)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=10)

        def apply_cols() -> None:
            cols = []
            for c in ALL_COLUMNS:
                if vars_by_col.get(c) and bool(vars_by_col[c].get()):
                    cols.append(c)
            self.visible_columns = cols or list(ALL_COLUMNS)
            self.tree["displaycolumns"] = tuple(self.visible_columns)
            self._render_rows(self.rows, self.last_cfg or argparse.Namespace(n=int(self.n_var.get() or 25), bank=int(self.bank_var.get() or 0)))
            self._save_settings()
            win.destroy()

        ttk.Button(btns, text="Apply", command=apply_cols).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=6)

    def reset_columns(self) -> None:
        self.visible_columns = list(ALL_COLUMNS)
        self.tree["displaycolumns"] = tuple(self.visible_columns)
        self._render_rows(self.rows, self.last_cfg or argparse.Namespace(n=int(self.n_var.get() or 25), bank=int(self.bank_var.get() or 0)))
        self._save_settings()

    # ---------- Export / Copy ----------
    def export_csv(self) -> None:
        if not self.last_top:
            self.status_var.set("Nothing to export")
            return
        cols = ["name", "id"] + [c for c in self.visible_columns if c not in {"name", "id"}]

        path = self.filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in self.last_top:
                    row_out = []
                    for c in cols:
                        if c == "id":
                            row_out.append(r.get("id", ""))
                        elif c == "name":
                            row_out.append(r.get("name", ""))
                        else:
                            row_out.append(r.get(c, ""))
                    w.writerow(row_out)
            self.status_var.set(f"Exported CSV: {path}")
        except Exception as e:
            self.status_var.set(f"Export failed: {e}")

    def copy_table(self) -> None:
        if not self.last_top:
            self.status_var.set("Nothing to copy")
            return
        cols = ["name", "id"] + [c for c in self.visible_columns if c not in {"name", "id"}]
        header = "\t".join(cols)
        lines = [header]
        for r in self.last_top:
            parts = []
            for c in cols:
                parts.append(str(r.get(c, "")))
            lines.append("\t".join(parts))
        txt = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.status_var.set("Copied table (TSV)")

    # ---------- Auto refresh ----------
    def _toggle_auto_refresh(self) -> None:
        if bool(self.auto_refresh_var.get()):
            self._schedule_auto_refresh()
        else:
            self._cancel_auto_refresh()

    def _cancel_auto_refresh(self) -> None:
        if self._auto_job:
            try:
                self.root.after_cancel(self._auto_job)
            except Exception:
                pass
        self._auto_job = None

    def _schedule_auto_refresh(self) -> None:
        self._cancel_auto_refresh()
        try:
            sec = int(float(self.auto_refresh_sec_var.get() or 30))
            sec = max(5, min(sec, 3600))
        except Exception:
            sec = 30
            self.auto_refresh_sec_var.set("30")

        def tick() -> None:
            if bool(self.auto_refresh_var.get()):
                self.refresh()
                self._schedule_auto_refresh()

        self._auto_job = self.root.after(sec * 1000, tick)

    # ---------- Settings ----------
    def _save_settings(self) -> None:
        try:
            import json
            data = {
                "geometry": self.root.geometry(),
                "bank": self.bank_var.get(),
                "n": self.n_var.get(),
                "slots": self.slots_var.get(),
                "aggr": self.aggr_var.get(),
                "min_vol_24h": self.min_vol_var.get(),
                "min_profit_unit": self.min_profit_var.get(),
                "ha_rune_cost": self.ha_rune_cost_var.get(),
                "ua": self.ua_var.get(),
                "no_tax": bool(self.no_tax_var.get()),
                "require_ha": bool(self.require_ha_var.get()),
                "search": self.search_var.get(),
                "f_min_roi": self.f_min_roi_var.get(),
                "f_min_pph": self.f_min_pph_var.get(),
                "f_max_eta": self.f_max_eta_var.get(),
                "f_min_ha": self.f_min_ha_var.get(),
                "f_min_cycles": self.f_min_cycles_var.get(),
                "hide_inf_eta": bool(self.f_hide_inf_eta.get()),
                "auto": bool(self.auto_refresh_var.get()),
                "auto_sec": self.auto_refresh_sec_var.get(),
                "chart_left": self.chart_left_label_var.get(),
                "chart_right": self.chart_right_label_var.get(),
                "visible_columns": self.visible_columns,
            }
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_settings(self) -> None:
        try:
            import json
            if not os.path.exists(SETTINGS_PATH):
                return
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            geom = data.get("geometry")
            if geom:
                self.root.geometry(str(geom))

            self.bank_var.set(str(data.get("bank", self.bank_var.get())))
            self.n_var.set(str(data.get("n", self.n_var.get())))
            self.slots_var.set(str(data.get("slots", self.slots_var.get())))
            self.aggr_var.set(str(data.get("aggr", self.aggr_var.get())))
            self.min_vol_var.set(str(data.get("min_vol_24h", self.min_vol_var.get())))
            self.min_profit_var.set(str(data.get("min_profit_unit", self.min_profit_var.get())))
            self.ha_rune_cost_var.set(str(data.get("ha_rune_cost", self.ha_rune_cost_var.get())))
            self.ua_var.set(str(data.get("ua", self.ua_var.get())))

            self.no_tax_var.set(bool(data.get("no_tax", self.no_tax_var.get())))
            self.require_ha_var.set(bool(data.get("require_ha", self.require_ha_var.get())))

            self.search_var.set(str(data.get("search", "")))
            self.f_min_roi_var.set(str(data.get("f_min_roi", "")))
            self.f_min_pph_var.set(str(data.get("f_min_pph", "")))
            self.f_max_eta_var.set(str(data.get("f_max_eta", "")))
            self.f_min_ha_var.set(str(data.get("f_min_ha", "")))
            self.f_min_cycles_var.set(str(data.get("f_min_cycles", "")))
            self.f_hide_inf_eta.set(bool(data.get("hide_inf_eta", False)))

            self.auto_refresh_var.set(bool(data.get("auto", False)))
            self.auto_refresh_sec_var.set(str(data.get("auto_sec", self.auto_refresh_sec_var.get())))

            left = data.get("chart_left")
            right = data.get("chart_right")
            if left:
                self.chart_left_label_var.set(left)
            if right:
                self.chart_right_label_var.set(right)

            vis = data.get("visible_columns")
            if isinstance(vis, list) and vis:
                cleaned = [c for c in vis if c in ALL_COLUMNS]
                self.visible_columns = cleaned or list(ALL_COLUMNS)
            # Ensure HA value is visible by default if missing from settings.
            if "ha_value" not in self.visible_columns:
                self.visible_columns.append("ha_value")
            self.tree["displaycolumns"] = tuple(self.visible_columns)

            if bool(self.auto_refresh_var.get()):
                self._schedule_auto_refresh()

            # apply filter render if we already have data
            if self.all_rows:
                self.apply_filters_now()

            self.status_var.set("Settings loaded")
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_settings()
        self._cancel_auto_refresh()
        self.root.destroy()

    def _about(self) -> None:
        self.messagebox.showinfo(
            "OSRS Flip Finder",
            "Flip Finder GUI\n\n"
            "Hotkeys:\n"
            "  Ctrl+R refresh\n"
            "  Ctrl+F search\n\n"
            "Right-click rows for actions.\n"
            "Use View → Choose columns to hide/show metrics."
        )


def run_text_mode(args: argparse.Namespace) -> int:
    rows = find_flips(args)
    top = rows[: args.n]
    print(f"\nTop {len(top)} flips (P2P) | bank={args.bank:,} gp\n")
    for r in top:
        eta = "∞" if r.get("hours_to_clear") == float("inf") else f"{float(r.get('hours_to_clear', 0)):.1f}h"
        print(f"- {r.get('name')} (ID {r.get('id')})")
        print(f"  Buy @ {r.get('buy'):,} | Sell @ {r.get('sell'):,} | Profit/u {r.get('profit_unit'):,}")
        if r.get("ha_value"):
            print(f"  HA value {r.get('ha_value'):,} | HA floor {r.get('ha_floor'):,} | HA net {r.get('ha_profit'):,}")
        print(f"  Qty {r.get('qty'):,} | Est {r.get('est_profit'):,} | ROI {r.get('roi_pct'):.2f}% | Vol {r.get('vol'):,} | ETA {eta}\n")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.text:
        return run_text_mode(args)

    try:
        tk_mod, ttk_mod, filedialog_mod, messagebox_mod = ensure_tk()
    except ImportError as exc:
        print(f"{exc}\nFalling back to text mode.", file=sys.stderr)
        return run_text_mode(args)

    gui = FlipGUI(tk_mod, ttk_mod, filedialog_mod, messagebox_mod, args)
    gui.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
