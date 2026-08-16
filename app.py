#!/usr/bin/env python3
"""
Put-Call Parity Model - Web app (Flask).

    C + PV(K) + PV(D) = P + S      where   PV(K) = K * exp(-r * T)

Serves the same core model as the CLI and the Tkinter GUI (main.py) over
HTTP: manual parity analysis, live Yahoo Finance chain scans, and the
payoff diagram as a PNG.

Run:
    python app.py                  # -> http://127.0.0.1:5000
    PORT=8080 python app.py        # custom port (useful on PaaS deploys)

Endpoints
---------
GET  /                       web UI (single page)
POST /api/analyze            manual parity analysis   {S, K, r, T, C, P, pv_d}
GET  /api/expirations        live: list expirations   ?ticker=AAPL
GET  /api/live               live: chain scan         ?ticker=AAPL&expiry=...&rf=...&dividends=0
GET  /api/chart              payoff diagram PNG       ?S=...&K=...&r=...&T=...&C=...&P=...&pv_d=...
"""

import datetime as dt
import io
import json
import os

from flask import Flask, jsonify, render_template, request, send_file

from put_call_parity import analyze, TOLERANCE

try:
    import market_data
    HAS_LIVE = getattr(market_data, "HAS_YF", False)
except Exception:
    market_data = None
    HAS_LIVE = False

# Force matplotlib to render to PNGs without any GUI backend.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

app = Flask(__name__)

# GitHub-dark palette, matching the Tkinter GUI (main.py).
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#2d333b"
FG = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d29922"

MONEY2 = lambda x: f"${x:,.2f}"


# ----------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------

def jsonable(obj):
    """Make a result dict safe for json.dumps (dates -> ISO strings)."""
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, tuple):
        return [jsonable(v) for v in obj]
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)


def _bad(msg, code=400):
    return jsonify({"error": msg}), code


def _friendly_rate_limit(exc):
    """Make Yahoo's 429 ('Too Many Requests') errors actionable in the UI."""
    msg = str(exc)
    if "Too Many Requests" in msg or "Rate limit" in msg:
        return ("Yahoo Finance is rate-limiting this server's IP right now. "
                "Wait a minute and retry — once any ticker fetch succeeds it "
                "is cached server-side (memory + disk) and served even during "
                "future rate limits.")
    return msg


# ----------------------------------------------------------------------
# Manual parity analysis
# ----------------------------------------------------------------------

@app.post("/api/analyze")
def api_analyze():
    data = request.get_json(silent=True) or {}
    try:
        S = float(data["S"]); K = float(data["K"])
        r = float(data["r"]) / 100.0            # UI gives % p.a., model wants fraction
        T = float(data["T"])
        C = float(data["C"]); P = float(data["P"])
        pv_d = float(data.get("pv_d") or 0.0)
    except (KeyError, TypeError, ValueError):
        return _bad("Need numeric S, K, r (% p.a.), T, C, P — got: "
                    + json.dumps({k: data.get(k) for k in ("S", "K", "r", "T", "C", "P")}))
    if not (S > 0 and K > 0 and T > 0 and C >= 0 and P >= 0):
        return _bad("Invalid inputs: S, K, T must be > 0; C, P >= 0.")
    if pv_d < 0:
        return _bad("pv_d must be >= 0.")

    res = analyze(S, K, r, T, C, P, pv_d=pv_d)
    res["days"] = T * 365.0
    res["pv_d"] = pv_d
    return jsonify(jsonable(res))


# ----------------------------------------------------------------------
# Live market data (Yahoo Finance)
# ----------------------------------------------------------------------

@app.get("/api/expirations")
def api_expirations():
    if not HAS_LIVE:
        return _bad("yfinance is not installed (pip install yfinance pandas).", 503)
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return _bad("Missing ?ticker= parameter.")
    try:
        t = market_data.get_ticker(ticker)
        exps = market_data.get_expirations(t)
        if not exps:
            return _bad(f"No listed options for {ticker!r}.", 404)
        return jsonify({"ticker": ticker, "expirations": sorted(exps)})
    except Exception as exc:
        return _bad(f"Could not fetch expirations: {_friendly_rate_limit(exc)}", 502)


@app.get("/api/live")
def api_live():
    if not HAS_LIVE:
        return _bad("yfinance is not installed (pip install yfinance pandas).", 503)
    ticker = (request.args.get("ticker") or "").strip()
    expiry = (request.args.get("expiry") or "").strip() or None
    rf_pct = request.args.get("rf") or None
    use_div = request.args.get("dividends", "1") not in ("0", "false", "False")

    if not ticker:
        return _bad("Missing ?ticker= parameter.")
    try:
        surf = market_data.build_surface(
            ticker, expiry=expiry,
            rf=(float(rf_pct) / 100.0) if rf_pct is not None else None,
            use_dividends=use_div, min_oi=0)
    except ValueError:
        return _bad("rf must be a number (percent p.a.).")
    except Exception as exc:
        return _bad(f"Live data error: {_friendly_rate_limit(exc)}", 502)

    # Trim the payload: the UI needs the same fields as the GUI table.
    rows = []
    for r in surf["rows"]:
        rows.append({
            "strike": r["strike"],
            "call_bid": r["call_bid"], "call_ask": r["call_ask"], "call_mid": r["call_mid"],
            "put_bid": r["put_bid"], "put_ask": r["put_ask"], "put_mid": r["put_mid"],
            "call_oi": r["call_oi"], "put_oi": r["put_oi"],
            "qflag": r["qflag"], "tradeable": r["tradeable"],
            "res": r["res"],
        })
    out = {
        "ticker": surf["ticker"], "currency": surf["currency"],
        "spot": surf["spot"], "spot_bid": surf["spot_bid"], "spot_ask": surf["spot_ask"],
        "rf": surf["rf"], "rf_source": surf["rf_source"],
        "expiry": surf["expiry"], "days": surf["days"], "T": surf["T"],
        "pv_d": surf["pv_d"], "expirations": surf["expirations"],
        "dividend": surf["dividend"], "rows": rows,
    }
    return jsonify(jsonable(out))


# ----------------------------------------------------------------------
# Payoff diagram (PNG)
# ----------------------------------------------------------------------

@app.get("/api/chart")
def api_chart():
    args = request.args
    try:
        S = float(args["S"]); K = float(args["K"])
        r = float(args["r"]) / 100.0
        T = float(args["T"])
        C = float(args["C"]); P = float(args["P"])
        pv_d = float(args.get("pv_d") or 0.0)
    except (KeyError, ValueError):
        return _bad("Need S, K, r, T, C, P as query parameters.")
    res = analyze(S, K, r, T, C, P, pv_d=pv_d)

    fig, ax = plt.subplots(figsize=(9.6, 3.4), dpi=110, facecolor=PANEL)
    ax.set_facecolor(PANEL)
    profit_today = res["profit"]
    profit_expiry = res["profit_expiry"]

    xmin = max(0, 0.4 * min(S, K))
    xmax = 1.6 * max(S, K)
    xs = [xmin + (xmax - xmin) * i / 200 for i in range(201)]

    if profit_today <= 1e-9:
        ax.axhline(0, color=GREEN, lw=2, ls=(0, (5, 4)))
        ax.text(xmax, 0.25, "Zero P&L — no arbitrage", color=GREEN, ha="right", fontsize=9)
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
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ----------------------------------------------------------------------
# Health + page
# ----------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html", has_live=HAS_LIVE, tolerance=TOLERANCE)


@app.get("/api/health")
def health():
    cache = market_data.cache_info() if HAS_LIVE else {}
    return jsonify({"ok": True, "live_data": HAS_LIVE, "cache": cache})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") not in ("0", "false", "False")
    print(f"Put-Call Parity web app: http://127.0.0.1:{port}")
    print(f"Live Yahoo Finance data: {'enabled' if HAS_LIVE else 'DISABLED (pip install yfinance pandas)'}")
    app.run(host="127.0.0.1", port=port, debug=debug)
