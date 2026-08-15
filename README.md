# Put-Call Parity Checker

A Python toolkit that verifies the **put-call parity** relationship — the no-arbitrage link between a call, a put, and the underlying stock — using both **manually entered quotes** and **live options market data** from Yahoo Finance.

It reports whether parity holds, and when it does not, it shows the exact **riskless arbitrage trade** (with per-leg cash flows and profit), adjusted for dividends and for the cost of crossing the bid/ask spread.

## Overview

Put-call parity is one of the most fundamental results in option pricing. For **European** options on the same underlying with the same strike `K` and expiration `T`:

```
C + PV(K) + PV(D) = P + S
```

where

| Symbol | Meaning |
|--------|---------|
| `C` | Call option price |
| `P` | Put option price |
| `S` | Spot price of the underlying |
| `K` | Strike price |
| `T` | Time to expiry (years) |
| `r` | Risk-free rate (continuous) |
| `PV(K)` | Present value of the strike = `K · e^(-r·T)` |
| `PV(D)` | Present value of dividends paid before expiry |

If the two sides are unequal beyond a tolerance, an arbitrage opportunity exists: sell the rich side, buy the cheap side, and lock in a riskless profit regardless of where the stock finishes.

The project provides four ways to use this:

1. **Interactive CLI** — type in quotes by hand.
2. **Manual CLI** — pass quotes as command-line arguments.
3. **Live market scan** — pull the entire option chain from Yahoo Finance, scan every strike for parity violations, and rank them by profitability after transaction costs.
4. **Desktop GUI** (Tkinter) — a visual app that combines manual analysis, live data, and a payoff chart.
5. **Web app** (Flask) — the same analysis served in the browser: manual inputs, live chain scans, and the payoff diagram.

## Features

- **Live market data** via `yfinance`: spot price (with bid/ask), option chain, open interest, volume.
- **Automatic risk-free rate** from the 13-week T-bill (`^IRX`), with `--rf` override.
- **Automatic dividend handling**: infers the dividend schedule from price history, computes expected payments before expiry, and discounts them to `PV(D)` (toggleable with `--no-dividends`).
- **Fair value pricing**: computes the theoretical "fair" call and put prices implied by the other leg.
- **Arbitrage detection** with a full trade construction: sells the rich side, buys the cheap side, borrows/lends `PV(K)+PV(D)`, and reports the riskless profit today and at expiry.
- **Transaction-cost-aware screening**: computes `NET` profit after crossing the bid/ask spread on every leg — only positive-NET strikes are genuinely tradeable.
- **Data-quality filtering**: flags quotes as `full` (two-sided on both options), `partial`, or `stale`, and excludes strikes with stale/mid-delta outliers by default (`--loose` to include them).
- **Payoff diagram** (`--plot`): shows the flat riskless profit line, independent of the terminal spot.
- **A CLI, a GUI, and a web app**, all sharing the same core model.

## Repository Structure

```
.
├── app.py              # Flask web app (API + serves the browser UI)
├── templates/          # index.html — single-page web UI
├── static/             # style.css, app.js — web UI assets
├── render.yaml         # Render blueprint (free web service, auto-deploy)
├── main.py             # Tkinter desktop GUI
├── put_call_parity.py  # Core parity model + CLI (manual & live scan)
├── market_data.py      # Yahoo Finance helpers (spot, chain, rate, dividends)
├── requirements.txt    # Python dependencies (Flask, gunicorn, ...)
├── example.txt         # Example commands
└── LICENSE             # MIT
```

## Installation

Requires **Python 3.8+**.

```bash
# 1. Clone the repository
git clone https://github.com/George1130/Put-Call-Parity.git
cd Put-Call-Parity

# 2. (Recommended) create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

The live-data features need `yfinance` and `pandas`; the payoff chart needs `matplotlib`. Manual/interactive mode works with the standard library alone.

## How to Run

### 1. Interactive CLI (manual quotes)

```bash
python put_call_parity.py
```

Prompts for spot, strike, rate, time-to-expiry, call, and put prices, then prints the full parity report.

### 2. Manual CLI (arguments)

```bash
python put_call_parity.py --spot 100 --strike 100 --rate 5 --t 0.5 --call 8 --put 5
```

All six inputs must be supplied together. Add `--plot` to show the payoff diagram:

```bash
python put_call_parity.py --spot 100 --strike 100 --rate 5 --t 0.5 --call 8 --put 5 --plot
```

### 3. Live market scan

```bash
python put_call_parity.py --ticker AAPL
```

Fetches the nearest viable expiry, scans every strike, and prints a ranked table of parity violations with fair values, mid-price deltas, NET profitability, and open interest — followed by a detailed report of the best opportunity.

Typical examples:

```bash
# Specific expiry, ignore dividends, loosen filtering
python put_call_parity.py --ticker AAPL --expiry 2026-09-18 --no-dividends --loose

# Index (European-style) option
python put_call_parity.py --ticker ^SPX --top 10

# Override the risk-free rate and show top violations
python put_call_parity.py --ticker ^NDX --rf 4.2 --top 8
```

### 4. Desktop GUI

```bash
python main.py
```

A Tkinter window with:

- **Live data panel** — enter a ticker, fetch quotes, browse expiries, click any chain row to load it into the model.
- **Manual inputs** — adjust `S`, `K`, `r`, `T`, `C`, `P` with live recomputation.
- **Results panel** — `PV(K)`, left/right sides, fair call/put, verdict, and the arbitrage trade with per-leg cash flows.
- **Payoff chart** — the flat riskless-profit diagram (requires `matplotlib`).

> Note: the GUI needs a graphical display (it won't run on a headless server without a display server / X forwarding).

### 5. Web app (Flask)

```bash
python app.py
```

Then open <http://127.0.0.1:5000> in your browser. The page provides the same panels as the desktop GUI:

- **Live data panel** — enter a ticker, fetch the option chain, switch expiries, click any row to load it into the model.
- **Manual inputs** — adjust `S`, `K`, `r`, `T`, `C`, `P` with live recomputation as you type.
- **Results panel** — `PV(K)`, left/right sides, fair call/put, verdict, and the arbitrage trade with per-leg cash flows.
- **Payoff diagram** — rendered as a PNG by the server (`matplotlib`).

Set the `PORT` environment variable to run on a different port (useful for Render, Railway, etc.):

```bash
PORT=8080 python app.py
```

HTTP API (useful for scripting or other frontends):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze` | POST | JSON `{S, K, r, T, C, P, pv_d}` → full parity result |
| `/api/live` | GET | `?ticker=AAPL&expiry=YYYY-MM-DD&rf=4.2&dividends=0` → chain scan |
| `/api/expirations` | GET | `?ticker=AAPL` → available expiration dates |
| `/api/chart` | GET | `?S=&K=&r=&T=&C=&P=&pv_d=` → payoff diagram PNG |
| `/api/health` | GET | server + live-data status |

### 6. Deploy to Render (free, auto-deploys from GitHub)

This repo ships a `render.yaml` blueprint — the fastest way to go live:

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New → Blueprint** → connect the
   `Put-Call-Parity` repo.
3. Render reads `render.yaml` and creates the web service: Python 3.12, free plan,
   `gunicorn` start command, health check on `/api/health`.
4. Click **Apply** → after the build (~5 min) the app is live at
   `https://put-call-parity.onrender.com` with free HTTPS. Every push to `main`
   redeploys automatically.

Alternatively, without the blueprint: **New → Web Service** → pick the repo →
**Runtime: Python 3.12** → **Build:** `pip install -r requirements.txt` →
**Start:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
→ **Instance type: Free**.

Notes:

- The free plan spins down after ~15 min idle and takes 30–50 s to wake up on the
  first visit after sleep (a Render loading page is shown meanwhile).
- `PYTHON_VERSION` is pinned to 3.12 in `render.yaml` because newer default
  runtimes can lack prebuilt wheels for pandas/numpy.
- The 180 s gunicorn timeout keeps slow Yahoo Finance chain fetches from being
  killed.
- `app.py` already honors the `PORT` env var Render injects.

## Command-Line Reference

| Flag | Applies to | Default | Description |
|------|-----------|---------|-------------|
| `--spot` | Manual | – | Spot price `S` |
| `--strike` | Manual | – | Strike price `K` |
| `--rate` | Manual | – | Risk-free rate, % p.a. (continuous) |
| `--t` | Manual | – | Time to expiry in years |
| `--call` | Manual | – | Call price `C` |
| `--put` | Manual | – | Put price `P` |
| `--plot` | Both | off | Show payoff diagram |
| `--tolerance` | Both | `0.01` | Mispricing threshold ($/share) before flagging arbitrage |
| `--ticker` | Live | – | Yahoo Finance ticker to scan |
| `--expiry` | Live | nearest | Expiration date `YYYY-MM-DD` |
| `--rf` | Live | `^IRX` | Override risk-free rate, % p.a. |
| `--top` | Live | `5` | Show top N violations |
| `--min-oi` | Live | `10` | Minimum total open interest per strike |
| `--no-dividends` | Live | off | Ignore dividend adjustment (classic non-dividend model) |
| `--loose` | Live | off | Include strikes without two-sided quotes on both options |

## How the Analysis Works

1. **Fetch inputs** — live mode pulls spot (with bid/ask), the option chain for the chosen expiry, the risk-free rate from `^IRX`, and the expected dividend stream.
2. **Compute the parity equation** for each strike:
   - `PV(K) = K · e^(-r·T)`, `PV(D)` = discounted dividends before expiry.
   - `LEFT = C + PV(K) + PV(D)`, `RIGHT = P + S`.
3. **Verdict** — if `|LEFT − RIGHT| ≤ tolerance` (default `$0.01`/share), parity holds; otherwise an arbitrage exists.
4. **Trade construction**:
   - *Left side rich* (`LEFT > RIGHT`): **sell call, buy put, buy stock, borrow `PV(K)+PV(D)`**.
   - *Right side rich* (`RIGHT > LEFT`): **buy call, sell put, short stock, lend `PV(K)+PV(D)`**.
   - Profit = `|LEFT − RIGHT|` per share today, growing to `|LEFT − RIGHT| · e^(r·T)` at expiry, **for any terminal spot** (the payoff diagram shows this flat line).
5. **Cost-adjusted NET** — for fully-quoted strikes, the trade is priced using executable sides (sell at bid, buy at ask, plus the stock bid/ask). `NET > 0` means the arbitrage survives transaction costs.
6. **Ranking** — strikes are sorted by tradeability (NET when available, else raw mispricing), and the top `N` are displayed.

## How Is This Helpful?

- **Learning / education**: visualizes the most important no-arbitrage relationship in options; shows *why* parity must hold and what happens when it breaks.
- **Fair-value estimation**: quickly derives the theoretical price of a put from a call (or vice versa) for any strike and expiry.
- **Market surveillance**: scans an entire option chain in one command and surfaces strikes where mid-market quotes violate parity — with a transparent, per-leg explanation of the correction trade.
- **Cost-aware screening**: separates headline mispricings (which may be quote artifacts) from ones that are actually profitable after the bid/ask spread, using open interest and quote-quality filters to reduce noise.
- **Teaching trade construction**: the generated arbitrage portfolio (stock + borrow/lend + two options) is a concrete illustration of how synthetic positions replicate one another.

## Possible Limitations

- **European-option assumption**: parity is *exact* only for European options. American-style options (most single stocks) can legitimately trade outside the bounds due to early-exercise premiums — violations on such tickers may be structural, not real arbitrage. Index options like `^SPX`/`^NDX` are European and match the model exactly.
- **Yahoo Finance data quality**: quotes are not exchange-realtime; they can be delayed, stale, or missing, and low-liquidity strikes often have wide or one-sided quotes. The tool filters aggressively, but garbage-in/garbage-out still applies.
- **Idealized assumptions**: the model assumes zero transaction costs (only the spread is accounted for), no short-sale constraints or borrow fees, unlimited borrowing/lending at the risk-free rate, and continuous compounding. Real markets violate all of these, which is why genuine arbitrage is rare.
- **Risk-free rate proxy**: `^IRX` (13-week T-bill) is a reasonable proxy but not the exact rate a trader can borrow/lend at; the mismatch introduces small errors in `PV(K)`.
- **Dividend estimation**: the schedule is inferred from historical payments and projected forward, not read from an official corporate calendar — it can be wrong around special dividends, suspensions, or irregular payers.
- **One price per expiry**: the scan uses the mid quote and a single `T` for all strikes; early-exercise and dividend timing effects per strike are not modeled.
- **Not investment advice**: findings are for research/education. By the time quotes reach Yahoo and the model runs, any real edge is usually gone; treat "arbitrage available" as a market-data artifact until verified on a live feed with executable prices.
- **GUI platform**: `main.py` requires a display environment (Tkinter); it won't run on headless servers without a virtual display.
- **Web data freshness**: the Flask app fetches Yahoo quotes per request; heavy scanning can be slow on a remote host (Yahoo rate limits), so the browser UI is best used interactively rather than as a batch tool.

## Disclaimer

This project is for **educational and research purposes only**. It is not financial advice, and nothing here should be used to place real trades without independent verification of prices, rates, dividends, and market conditions.

## License

[MIT](LICENSE) © 2026 George1130
