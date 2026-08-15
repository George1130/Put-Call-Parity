#!/usr/bin/env python3
"""
Put-Call Parity Model - Desktop GUI (Tkinter) with live Yahoo Finance data.

    C + PV(K) + PV(D) = P + S      where   PV(K) = K * exp(-r * T)

Runs (from the project venv so yfinance is available):
    ./venv/bin/python put_call_parity_gui.py

Live data needs yfinance + pandas (installed in ./venv). Without it the app
still works in manual mode.
Payoff chart needs matplotlib (optional).
"""

import math
import tkinter as tk
from tkinter import ttk, font as tkfont

from put_call_parity import analyze, TOLERANCE

try:
    from market_data import build_surface, HAS_YF as HAS_LIVE
    _HAS_LIVE = HAS_LIVE
except Exception:
    build_surface = None
    _HAS_LIVE = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

BG = "#0d1117"
PANEL = "#161b22"
PANEL2 = "#1c2330"
BORDER = "#2d333b"
FG = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d29922"

MONEY = lambda x: f"${x:,.4f}"
MONEY2 = lambda x: f"${x:,.2f}"


class PutCallParityApp:
    def __init__(self, root):
        self.root = root
        root.title("Put-Call Parity Model  |  C + PV(K) + PV(D) = P + S")
        root.configure(bg=BG)
        root.geometry("1180x1040")
        root.minsize(1000, 900)

        self.pv_d = 0.0

        self.fonts = {
            "title": tkfont.Font(family="Helvetica", size=17, weight="bold"),
            "h2": tkfont.Font(family="Helvetica", size=10, weight="bold"),
            "body": tkfont.Font(family="Helvetica", size=10),
            "mono": tkfont.Font(family="Courier", size=11),
            "mono_sm": tkfont.Font(family="Courier", size=9),
        }

        self.v = {k: tk.StringVar(value=str(val)) for k, val in {
            "S": "100.00", "K": "100.00", "r": "5.00", "T": "0.5",
            "C": "8.00", "P": "5.00",
        }.items()}

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TEntry", fieldbackground=PANEL2, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, padding=6)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure("Treeview", background=PANEL2, fieldbackground=PANEL2,
                        foreground=FG, rowheight=22, borderwidth=0)
        style.map("Treeview", background=[("selected", "#2a4a7a")])
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                        relief="flat", padding=4)
        style.map("Treeview.Heading", background=[("active", BORDER)])
        style.configure("TCombobox", fieldbackground=PANEL2, foreground=FG,
                        arrowcolor=MUTED, bordercolor=BORDER)

        self._build()

        for var in self.v.values():
            var.trace_add("write", self._on_change)

        self.recompute()

    # ---------------- UI construction ----------------
    def _build(self):
        root = self.root
        root.grid_rowconfigure(3, weight=1)
        root.grid_columnconfigure(0, weight=1)

        title = tk.Label(root, text="Put-Call Parity Model",
                         font=self.fonts["title"], bg=BG, fg=FG, anchor="w")
        title.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))
        sub = tk.Label(root, text="C + PV(K) + PV(D) = P + S   |   European options  |   "
                                  "live quotes from Yahoo Finance (yfinance)",
                       font=self.fonts["body"], bg=BG, fg=MUTED, anchor="w")
        sub.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))

        self._build_live_card(root)

        body = tk.Frame(root, bg=BG)
        body.grid(row=3, column=0, sticky="nsew", padx=18)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        # ---- left: inputs card ----
        left = self._card(body, "Market Inputs (manual, or click a chain row above)")
        left.grid(row=0, column=0, sticky="n", padx=(0, 12))
        content = left.content
        fields = [
            ("S", "Spot price S"),
            ("K", "Strike price K"),
            ("r", "Risk-free rate r (% p.a.)"),
            ("T", "Time to expiry T (years)"),
        ]
        for i, (key, label) in enumerate(fields):
            self._labeled_entry(content, key, label, row=i)
        cp = tk.Frame(content, bg=PANEL)
        cp.grid(row=len(fields), column=0, sticky="ew", pady=(0, 10))
        self._labeled_entry(cp, "C", "Call price C", row=0, col=0, side=True)
        self._labeled_entry(cp, "P", "Put price P", row=0, col=1, side=True)

        self.days_lbl = tk.Label(content, text="", bg=PANEL, fg=MUTED,
                                 font=self.fonts["body"], anchor="w")
        self.days_lbl.grid(row=len(fields) + 1, column=0, sticky="ew", pady=(0, 8))

        btns = tk.Frame(content, bg=PANEL)
        btns.grid(row=len(fields) + 2, column=0, sticky="ew")
        for text, cmd, color in [
            ("Load example", self.load_example, ACCENT),
            ("Set P = fair", self.set_fair_p, GREEN),
            ("Set C = fair", self.set_fair_c, GREEN),
        ]:
            b = tk.Button(btns, text=text, command=cmd, bg=PANEL2, fg=color,
                          relief="flat", bd=0, cursor="hand2",
                          activebackground=BORDER, activeforeground=color,
                          font=self.fonts["body"], padx=10, pady=6)
            b.pack(side="left", padx=(0, 8))

        note = tk.Label(content,
                        text="Non-dividend model is PV(D)=0. Live rows adjust for\n"
                             "expected dividends. Values are per share (x100 per\n"
                             "contract). Mid quotes; NET = profit after crossing\n"
                             "the bid/ask spread.",
                        bg=PANEL, fg=MUTED, font=self.fonts["mono_sm"],
                        justify="left", anchor="w", wraplength=300)
        note.grid(row=len(fields) + 3, column=0, sticky="ew", pady=(12, 0))

        # ---- right: results card ----
        right = self._card(body, "Parity Check")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        rc = right.content
        rc.grid_rowconfigure(1, weight=1)
        rc.grid_columnconfigure(0, weight=1)

        stats = tk.Frame(rc, bg=PANEL)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.stat_frames = {}
        stat_specs = [
            ("pvk", "PV(K) = K·e^(−rT)"),
            ("rt", "r·T"),
            ("left", "LEFT  = C + PV(K)"),
            ("right", "RIGHT = P + S"),
            ("fairP", "Fair Put"),
            ("fairC", "Fair Call"),
        ]
        for i, (key, title) in enumerate(stat_specs):
            frame = tk.Frame(stats, bg=PANEL2)
            frame.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            stats.grid_columnconfigure(i % 3, weight=1)
            tk.Label(frame, text=title, bg=PANEL2, fg=MUTED,
                     font=self.fonts["mono_sm"]).pack(anchor="w", padx=8, pady=(6, 0))
            val = tk.Label(frame, text="—", bg=PANEL2, fg=FG,
                           font=self.fonts["mono"], anchor="w")
            val.pack(anchor="w", padx=8, pady=(0, 6))
            self.stat_frames[key] = (frame, val)

        self.verdict = tk.Label(rc, text="", bg=PANEL, fg=FG,
                                font=self.fonts["body"], justify="left",
                                anchor="w", wraplength=620)
        self.verdict.grid(row=1, column=0, sticky="ew", pady=(4, 8))

        self.trade = tk.Text(rc, height=9, bg=PANEL2, fg=FG,
                             font=self.fonts["mono"], relief="flat",
                             bd=0, padx=10, pady=8, wrap="none",
                             highlightbackground=BORDER, highlightthickness=1)
        self.trade.grid(row=2, column=0, sticky="nsew")
        self.trade.configure(state="disabled")
        self.trade.tag_configure("green", foreground=GREEN)
        self.trade.tag_configure("red", foreground=RED)
        self.trade.tag_configure("accent", foreground=ACCENT)
        self.trade.tag_configure("muted", foreground=MUTED)

        # ---- chart card ----
        chart_card = self._card(root, "Payoff Diagram — riskless profit at expiry (all S_T)")
        chart_card.grid(row=4, column=0, sticky="nsew", padx=18, pady=(12, 18))
        cc = chart_card.content
        cc.grid_rowconfigure(0, weight=1)
        cc.grid_columnconfigure(0, weight=1)

        if HAS_MPL:
            self.fig = Figure(figsize=(10, 3.0), dpi=100, facecolor=PANEL, constrained_layout=True)
            self.ax = self.fig.add_subplot(111)
            self.ax.set_facecolor(PANEL)
            self.canvas = FigureCanvasTkAgg(self.fig, master=cc)
            self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
            self.canvas.figure.patch.set_facecolor(PANEL)
        else:
            tk.Label(cc, text="Install matplotlib to see the payoff chart:\n"
                              "  ./venv/bin/pip install matplotlib",
                     bg=PANEL, fg=YELLOW, font=self.fonts["body"]).grid(row=0, column=0)

    def _build_live_card(self, parent):
        card = self._card(parent, "Live Market Data — Yahoo Finance (yfinance)")
        card.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        content = card.content
        content.grid_columnconfigure(5, weight=1)

        tk.Label(content, text="Ticker", bg=PANEL, fg=MUTED,
                 font=self.fonts["body"]).grid(row=0, column=0, sticky="w")
        self.ticker_var = tk.StringVar(value="AAPL")
        ttk.Entry(content, textvariable=self.ticker_var, font=self.fonts["mono"],
                  width=10).grid(row=0, column=1, sticky="w", padx=(8, 14))
        self.fetch_btn = tk.Button(content, text="Fetch live quotes", command=self.fetch_live,
                                   bg=PANEL2, fg=ACCENT, relief="flat", bd=0, cursor="hand2",
                                   activebackground=BORDER, activeforeground=ACCENT,
                                   font=self.fonts["body"], padx=12, pady=6)
        self.fetch_btn.grid(row=0, column=2, sticky="w", padx=(0, 16))
        tk.Label(content, text="Expiry", bg=PANEL, fg=MUTED,
                 font=self.fonts["body"]).grid(row=0, column=3, sticky="w")
        self.expiry_var = tk.StringVar()
        self.expiry_cb = ttk.Combobox(content, textvariable=self.expiry_var,
                                      state="readonly", width=14, font=self.fonts["mono"])
        self.expiry_cb.grid(row=0, column=4, sticky="w", padx=(8, 14))
        self.expiry_cb.bind("<<ComboboxSelected>>", self.on_expiry_change)
        if not _HAS_LIVE:
            self.fetch_btn.configure(state="disabled")

        self.live_status = tk.Label(content, text="", bg=PANEL, fg=MUTED,
                                    font=self.fonts["mono_sm"], anchor="w", justify="left")
        self.live_status.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(8, 6))

        tree_frame = tk.Frame(content, bg=PANEL)
        tree_frame.grid(row=2, column=0, columnspan=6, sticky="ew")
        cols = ("strike", "call", "put", "fairc", "fairp", "midd", "net", "oi", "qual")
        widths = {"strike": 80, "call": 80, "put": 80, "fairc": 85, "fairp": 85,
                  "midd": 75, "net": 75, "oi": 95, "qual": 75}
        heads = {"strike": "Strike", "call": "Call", "put": "Put", "fairc": "Fair C",
                 "fairp": "Fair P", "midd": "MID Δ", "net": "NET Δ", "oi": "OI c/p",
                 "qual": "Quotes"}
        anchors = {"strike": "center", "oi": "center", "midd": "e",
                   "net": "e", "qual": "center"}
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=7)
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor=anchors.get(c, "e"))
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("viol", foreground=RED)
        self.tree.tag_configure("ok", foreground=GREEN)
        self.tree.tag_configure("stale", foreground=MUTED)
        self.tree.tag_configure("best", foreground=YELLOW, background="#241a00")
        self.tree.bind("<<TreeviewSelect>>", self.use_selected)

        tk.Label(content, text="Click any row to load that strike into the manual parity model below.",
                 bg=PANEL, fg=MUTED, font=self.fonts["body"]).grid(
            row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        if not _HAS_LIVE:
            self.live_status.config(
                text="yfinance not installed. Run ./venv/bin/pip install yfinance pandas "
                     "then start with ./venv/bin/python put_call_parity_gui.py",
                fg=YELLOW)

    def _card(self, parent, title):
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        head = tk.Label(card, text=title.upper(), font=self.fonts["h2"],
                        bg=PANEL, fg=MUTED, anchor="w")
        head.pack(fill="x", padx=14, pady=(10, 8))
        content = tk.Frame(card, bg=PANEL)
        content.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        card.content = content
        return card

    def _labeled_entry(self, parent, key, label, row, col=0, side=False):
        frame = tk.Frame(parent, bg=parent["bg"])
        frame.grid(row=row, column=col, sticky="ew", pady=(0, 10),
                   padx=(0, 8) if side else 0)
        tk.Label(frame, text=label, bg=parent["bg"], fg=MUTED,
                 font=self.fonts["body"], anchor="w").pack(fill="x")
        ttk.Entry(frame, textvariable=self.v[key], font=self.fonts["mono"],
                  width=14).pack(fill="x", pady=(3, 0))

    # ---------------- live data ----------------
    def fetch_live(self):
        if not _HAS_LIVE:
            return
        ticker = self.ticker_var.get().strip()
        if not ticker:
            return
        self.live_status.config(text=f"Fetching {ticker} ...", fg=YELLOW)
        self.root.update_idletasks()
        try:
            data = build_surface(ticker, min_oi=0)
        except Exception as e:
            self.live_status.config(text=f"Error: {e}", fg=RED)
            return
        self.live = data
        self.expiry_cb["values"] = data["expirations"]
        self.expiry_var.set(data["expiry"])
        self._render_live(data)
        iid = self._best_iid(data)
        if iid:
            self.tree.selection_set(iid)
            self.tree.see(iid)
        self.use_selected()

    def on_expiry_change(self, *_):
        if not getattr(self, "live", None):
            return
        expiry = self.expiry_var.get()
        if not expiry:
            return
        self.live_status.config(text=f"Fetching {expiry} chain ...", fg=YELLOW)
        self.root.update_idletasks()
        try:
            data = build_surface(self.live["ticker"], expiry=expiry,
                                 rf=self.live["rf"], use_dividends=True, min_oi=0)
        except Exception as e:
            self.live_status.config(text=f"Error: {e}", fg=RED)
            return
        self.live = data
        self._render_live(data)
        self.use_selected()

    def _best_iid(self, data):
        rows = data["rows"]
        tr = [r for r in rows if r["tradeable"] is not None and r["tradeable"] > 0]
        if tr:
            best = max(tr, key=lambda r: r["tradeable"])
        else:
            best = min(rows, key=lambda r: abs(r["strike"] - data["spot"])) if rows else None
        if best is None:
            return None
        return self.row_by_iid.get(best["strike"])

    def _render_live(self, data):
        div = data["dividend"]
        if not div["pays"]:
            dnote = "no dividends"
        else:
            dnote = (f"{div['freq_days']:.0f}-day div ${div['amount']:.2f}/sh, "
                     f"{len(div['dates'])} before expiry, PV(D)=${div['pv']:.2f}")
        tr = [r for r in data["rows"] if r["tradeable"] is not None and r["tradeable"] > 0]
        note = (" | no tradeable arbitrage (NET <= 0 on every fully-quoted strike)"
                if not tr else
                f" | BEST tradeable: K={max(tr, key=lambda r: r['tradeable'])['strike']:.2f}, "
                f"NET {max(tr, key=lambda r: r['tradeable'])['tradeable']:+.3f}/share")
        self.live_status.config(
            text=(f"{data['ticker']}  |  spot {data['currency']} {data['spot']:.2f} "
                  f"(bid {data['spot_bid']:.2f}/ask {data['spot_ask']:.2f})  |  "
                  f"r {data['rf'] * 100:.2f}% ({data['rf_source']})  |  "
                  f"{data['expiry']} -> {data['days']}d  |  {dnote}{note}"),
            fg=FG)
        self.tree.delete(*self.tree.get_children())
        self.row_by_iid = {}
        for r in data["rows"]:
            res = r["res"]
            qual = {"full": "2sided", "partial": "1sided", "stale": "stale"}[r["qflag"]]
            net = f"{r['tradeable']:+.3f}" if r["tradeable"] is not None else "—"
            if res["status"] != "parity" and r["qflag"] == "full":
                tag = "viol"
            elif res["status"] != "parity":
                tag = "stale"
            else:
                tag = "ok"
            vals = (f"{r['strike']:.2f}", MONEY2(r["call_mid"]), MONEY2(r["put_mid"]),
                    MONEY2(res["fair_c"]), MONEY2(res["fair_p"]),
                    f"{res['abs_diff']:+.3f}", net,
                    f"{r['call_oi']}/{r['put_oi']}", qual)
            iid = self.tree.insert("", "end", values=vals, tags=(tag,))
            self.row_by_iid[r["strike"]] = iid
        tr = [r for r in data["rows"] if r["tradeable"] is not None and r["tradeable"] > 0]
        if tr:
            best = max(tr, key=lambda r: r["tradeable"])
            self.tree.item(self.row_by_iid[best["strike"]], tags=("best",))

    def use_selected(self, *_):
        sel = self.tree.selection()
        if not sel or not getattr(self, "live", None):
            return
        strike = float(self.tree.item(sel[0])["values"][0])
        data = self.live
        row = next((r for r in data["rows"] if abs(r["strike"] - strike) < 1e-6), None)
        if row is None:
            return
        self.v["S"].set(f"{data['spot']:.2f}")
        self.v["K"].set(f"{strike:.2f}")
        self.v["r"].set(f"{data['rf'] * 100:.4f}")
        self.v["T"].set(f"{data['T']:.6f}")
        self.v["C"].set(f"{row['call_mid']:.2f}")
        self.v["P"].set(f"{row['put_mid']:.2f}")
        self.pv_d = data["pv_d"]
        self.recompute()

    # ---------------- manual analysis ----------------
    def _on_change(self, *_):
        self.recompute()

    def _read(self):
        vals = {}
        for key in ("S", "K", "r", "T", "C", "P"):
            try:
                vals[key] = float(self.v[key].get())
            except ValueError:
                return None
        if not (vals["S"] > 0 and vals["K"] > 0 and vals["T"] > 0):
            return None
        if vals["C"] < 0 or vals["P"] < 0:
            return None
        return vals

    def recompute(self):
        vals = self._read()
        if vals is None:
            self._clear_results()
            return
        S, K, r, T, C, P = vals["S"], vals["K"], vals["r"] / 100, vals["T"], vals["C"], vals["P"]
        self.days_lbl.config(text=f"≈ {T * 365:.2f} days to expiry")
        res = analyze(S, K, r, T, C, P, pv_d=self.pv_d)
        self._show_results(res)

    def _clear_results(self):
        for _, val in self.stat_frames.values():
            val.config(text="—")
        self.days_lbl.config(text="")
        self.verdict.config(text="Enter valid inputs (S, K, T > 0; C, P ≥ 0).", fg=YELLOW)
        self._set_trade("")
        if HAS_MPL:
            self._clear_chart()

    def _show_results(self, res):
        self.stat_frames["pvk"][1].config(text=MONEY(res["PV(K)"]), fg=FG)
        self.stat_frames["rt"][1].config(text=f"{res['rT']:.6f}", fg=FG)
        self.stat_frames["left"][1].config(text=MONEY2(res["left"]), fg=FG)
        self.stat_frames["right"][1].config(text=MONEY2(res["right"]), fg=FG)
        self.stat_frames["fairP"][1].config(
            text=f"{MONEY2(res['fair_p'])}  (mkt {MONEY2(res['P'])})",
            fg=GREEN if abs(res["P"] - res["fair_p"]) < TOLERANCE else RED)
        self.stat_frames["fairC"][1].config(
            text=f"{MONEY2(res['fair_c'])}  (mkt {MONEY2(res['C'])})",
            fg=GREEN if abs(res["C"] - res["fair_c"]) < TOLERANCE else RED)

        pvd = self.pv_d > 1e-9
        suffix = f"\nDividend adjustment PV(D) = {MONEY2(self.pv_d)}" if pvd else ""

        if res["status"] == "parity":
            self.verdict.config(
                text=(f"PARITY HOLDS  |  |LEFT - RIGHT| = {MONEY2(res['abs_diff'])} "
                      f"<= tolerance {MONEY2(TOLERANCE)}\n"
                      f"No arbitrage. Both sides ~ {MONEY2((res['left'] + res['right']) / 2)}."
                      + suffix),
                fg=GREEN)
            self._set_trade("No trade: market prices already satisfy parity within tolerance.")
        elif res["status"] == "arb_left_rich":
            self.verdict.config(
                text=(f"ARBITRAGE  |  C + PV(K) = {MONEY2(res['left'])} is {MONEY2(res['abs_diff'])} "
                      f"richer than P + S = {MONEY2(res['right'])}\n"
                      f"Call is {(res['C'] / max(res['fair_c'], 1e-12) - 1) * 100:.2f}% overpriced "
                      f"({MONEY2(res['C'])} vs fair {MONEY2(res['fair_c'])}). Sell rich, buy cheap."
                      + suffix),
                fg=RED)
            self._show_trade(res, "SELL call, BUY put, BUY stock, BORROW PV(K)")
        else:
            self.verdict.config(
                text=(f"ARBITRAGE  |  P + S = {MONEY2(res['right'])} is {MONEY2(res['abs_diff'])} "
                      f"richer than C + PV(K) = {MONEY2(res['left'])}\n"
                      f"Put is {(res['P'] / max(res['fair_p'], 1e-12) - 1) * 100:.2f}% overpriced "
                      f"({MONEY2(res['P'])} vs fair {MONEY2(res['fair_p'])}). Sell rich, buy cheap."
                      + suffix),
                fg=RED)
            self._show_trade(res, "BUY call, SELL put, SHORT stock, LEND PV(K)")

        if HAS_MPL:
            self._draw_chart(res)

    def _show_trade(self, res, headline):
        if self.pv_d > 1e-9:
            headline = headline.replace("PV(K)", "PV(K)+PV(D)")
        lines = [headline]
        total = 0.0
        for leg, cf in res["trade"]["legs"]:
            total += cf
            sign = "+" if cf >= 0 else "−"
            color = "green" if cf >= 0 else "red"
            lines.append(("  ", f"{sign}{MONEY2(abs(cf)):>12}  {leg}", color))
        lines.append(("  ", f"+{MONEY2(total):>12}  Net cash now (riskless profit today)", "accent"))
        lines.append(("  ", f"{MONEY2(res['profit_expiry']):>13}  Value at expiry, any S_T", "muted"))
        lines.append(("  ", "Per contract (x100): " + MONEY2(res["profit"] * 100), "bold"))
        self._set_trade_lines(lines)

    def _set_trade(self, text):
        self.trade.configure(state="normal")
        self.trade.delete("1.0", "end")
        self.trade.insert("1.0", text)
        self.trade.configure(state="disabled")

    def _set_trade_lines(self, lines):
        self.trade.configure(state="normal")
        self.trade.delete("1.0", "end")
        for parts in lines:
            tag = None
            if isinstance(parts, tuple):
                if len(parts) == 3:
                    indent, text, tag = parts
                else:
                    indent, text = parts
            else:
                indent, text = "", parts
            self.trade.insert("end", indent + text + "\n", (tag,) if tag else ())
        self.trade.configure(state="disabled")

    # ---------------- buttons ----------------
    def load_example(self):
        for k, v in {"S": "100.00", "K": "100.00", "r": "5.00",
                     "T": "0.5", "C": "8.00", "P": "5.00"}.items():
            self.v[k].set(v)
        self.pv_d = 0.0
        self.recompute()

    def set_fair_p(self):
        vals = self._read()
        if not vals:
            return
        pv_k = vals["K"] * math.exp(-vals["r"] / 100 * vals["T"])
        self.v["P"].set(f"{vals['C'] + pv_k + self.pv_d - vals['S']:.4f}")
        self.recompute()

    def set_fair_c(self):
        vals = self._read()
        if not vals:
            return
        pv_k = vals["K"] * math.exp(-vals["r"] / 100 * vals["T"])
        self.v["C"].set(f"{vals['P'] + vals['S'] - pv_k - self.pv_d:.4f}")
        self.recompute()

    # ---------------- chart ----------------
    def _clear_chart(self):
        self.ax.clear()
        self.ax.set_facecolor(PANEL)
        self.canvas.draw_idle()

    def _draw_chart(self, res):
        ax = self.ax
        ax.clear()
        ax.set_facecolor(PANEL)
        S, K, r, T = res["S"], res["K"], res["r"], res["T"]
        profit_today = res["profit"]
        profit_expiry = res["profit_expiry"]

        xmin = max(0, 0.4 * min(S, K))
        xmax = 1.6 * max(S, K)
        xs = [xmin + (xmax - xmin) * i / 200 for i in range(201)]

        if profit_today <= 1e-9:
            ax.axhline(0, color=GREEN, lw=2, ls=(0, (5, 4)))
            ax.text(xmax, 0.4, "Zero P&L — no arbitrage", color=GREEN, ha="right", fontsize=9)
        else:
            ax.plot(xs, [profit_expiry] * len(xs), lw=2.5, color=GREEN,
                    label=f"Profit at expiry = ${profit_expiry:.2f} (any S_T)")
            ax.axhline(profit_today, lw=1.2, ls="--", color=ACCENT,
                       label=f"Profit captured today = ${profit_today:.2f}")
            ax.fill_between(xs, 0, profit_today, color=GREEN, alpha=0.12)
            ax.axhline(0, color=MUTED, lw=1)
            ax.set_ylim(bottom=min(0, profit_today * 1.2))
            ax.legend(facecolor=PANEL, edgecolor=BORDER, labelcolor=FG, fontsize=8)

        ax.set_title("Put-Call Parity Arbitrage — Riskless Profit at Expiry", color=FG, fontsize=10)
        ax.set_xlabel("Spot at expiry  S_T", color=MUTED, fontsize=9)
        ax.set_ylabel("P&L", color=MUTED, fontsize=9)
        ax.tick_params(colors=MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(BORDER)
        ax.grid(True, color=BORDER, lw=0.5, alpha=0.6)
        self.canvas.draw_idle()


def main():
    root = tk.Tk()
    app = PutCallParityApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
