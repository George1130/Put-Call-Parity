#!/usr/bin/env python3


import argparse
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
    import numpy as np
    import pandas as pd
except ImportError:
    sys.exit(
        "Please install following packages using the below command.\n"
        "pip install -r requirements.txt"
    )

# Script should restricted to work for only European Options
EUROPEAN_STYLE_TICKERS = {"^SPX", "^NDX", "^RUT", "^VIX", "^DJX", "^XSP"}


# Binomial (Cox-Ross-Rubinstein) Note: Didn't implemented american
def crr_binomial_price(S, K, T, r, sigma, N=200, option_type="call", q=0.0, american=False):
    """
    Price an option with a Cox-Ross-Rubinstein binomial tree.

    Parameters
    ----------
    S, K      : spot price, strike price
    T         : time to expiry, in years
    r         : continuously-compounded risk-free rate
    sigma     : annualized volatility
    N         : number of binomial steps (more = closer to Black-Scholes)
    option_type : "call" or "put"
    q         : continuous dividend yield
    american  : if True, allow early exercise at each node (American-style).
                Defaults to False (European), which is what makes exact put-call parity hold.

    Returns
    -------
    float : the option's model price
    """
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")
    if T <= 0 or sigma <= 0 or N < 1:
        intrinsic = (S - K) if option_type == "call" else (K - S)
        return max(0.0, intrinsic)

    dt = T / N
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    disc = np.exp(-r * dt)
    p = (np.exp((r - q) * dt) - d) / (u - d)

    if not (0.0 <= p <= 1.0):
        raise ValueError(
            f"Risk-neutral probability p={p:.4f} fell outside [0, 1] for "
            f"S={S}, K={K}, T={T}, r={r}, sigma={sigma}, N={N}. "
            "This usually means N is too small for this sigma/T combination "
            "(try a larger --steps), or sigma/r/q are inconsistent."
        )

    # Terminal stock prices
    j = np.arange(N + 1)
    ST = S * (u ** j) * (d ** (N - j))
    values = np.maximum(ST - K, 0.0) if option_type == "call" else np.maximum(K - ST, 0.0)

    # Backward induction through the tree
    for i in range(N, 0, -1):
        values = disc * (p * values[1:i + 1] + (1 - p) * values[0:i])
        if american:
            j = np.arange(i)
            St = S * (u ** j) * (d ** (i - 1 - j))
            intrinsic = np.maximum(St - K, 0.0) if option_type == "call" else np.maximum(K - St, 0.0)
            values = np.maximum(values, intrinsic)

    return float(values[0])


def put_call_parity_rhs(S, K, T, r, q=0.0):
    """Right-hand side of C - P = S*e^(-qT) - K*e^(-rT)."""
    return S * np.exp(-q * T) - K * np.exp(-r * T)



#  Market Helpers
def get_risk_free_rate(default=0.05):
    """Approximate the risk-free rate from the 13-week T-bill (^IRX, quoted in %)."""
    try:
        irx = yf.Ticker("^IRX").history(period="5d")["Close"].dropna()
        if len(irx):
            return float(irx.iloc[-1]) / 100.0
    except Exception:
        pass
    print(f"Warning: couldn't fetch ^IRX for a risk-free rate; defaulting to {default:.2%}")
    return default


def get_spot_and_dividend_yield(ticker_obj):
    hist = ticker_obj.history(period="5d")["Close"].dropna()
    if hist.empty:
        raise ValueError("Could not retrieve recent price history for the spot price.")
    S = float(hist.iloc[-1])

    q = 0.0
    try:
        info = ticker_obj.info
        raw_q = info.get("dividendYield") or 0.0
        q = float(raw_q)
        if q > 1:  # have to fix percentage/decimal issue.
            q /= 100.0
    except Exception:
        pass
    return S, q


def fetch_chain(ticker_symbol, expiry=None):
    t = yf.Ticker(ticker_symbol)
    try:
        expirations = t.options
    except Exception as e:
        raise ValueError(f"Couldn't fetch expirations for '{ticker_symbol}': {e}")

    if not expirations:
        raise ValueError(f"No listed option expirations found for '{ticker_symbol}'.")

    if expiry is None:
        expiry = expirations[0]
    elif expiry not in expirations:
        raise ValueError(
            f"'{expiry}' is not a listed expiry for {ticker_symbol}.\n"
            f"Available: {', '.join(expirations)}"
        )

    chain = t.option_chain(expiry)
    return t, chain.calls, chain.puts, expiry


def years_to_expiry(expiry_str):
    # Approximate expiry as 4pm UTC-ish on the expiry date; good enough for
    # a T used inside a binomial model (precision to the hour doesn't matter).
    expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d").replace(hour=16, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = (expiry_dt - now).total_seconds() / 86400
    return max(days, 0.0) / 365.0


# 5 Factors
def build_parity_table(ticker_symbol, expiry, steps, american, moneyness_band,
                        rate_override, div_override):
    t, calls, puts, expiry = fetch_chain(ticker_symbol, expiry)
    S, q_auto = get_spot_and_dividend_yield(t)
    r = rate_override if rate_override is not None else get_risk_free_rate()
    q = div_override if div_override is not None else q_auto
    T = years_to_expiry(expiry)

    if T <= 0:
        raise ValueError(f"Expiry {expiry} has already passed (or is today after the close).")

    cols = ["strike", "lastPrice", "bid", "ask", "impliedVolatility", "volume", "openInterest"]
    missing_c = [c for c in cols if c not in calls.columns]
    missing_p = [c for c in cols if c not in puts.columns]
    if missing_c or missing_p:
        raise ValueError(
            f"Option chain is missing expected columns (calls missing {missing_c}, "
            f"puts missing {missing_p}). Yahoo may have changed its response format."
        )

    c = calls[cols].add_suffix("_call").rename(columns={"strike_call": "strike"})
    p = puts[cols].add_suffix("_put").rename(columns={"strike_put": "strike"})
    df = pd.merge(c, p, on="strike", how="inner").sort_values("strike").reset_index(drop=True)

    if moneyness_band is not None:
        lo, hi = S * (1 - moneyness_band), S * (1 + moneyness_band)
        df = df[(df["strike"] >= lo) & (df["strike"] <= hi)].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            "No overlapping call/put strikes found in the requested moneyness band "
            "-- try widening --moneyness-band or setting it to 0."
        )

    records = []
    skipped_no_iv = 0
    for row in df.itertuples(index=False):
        iv_c, iv_p = row.impliedVolatility_call, row.impliedVolatility_put
        ivs = [v for v in (iv_c, iv_p) if v and v > 0]
        if not ivs:
            skipped_no_iv += 1
            continue
        sigma = float(np.mean(ivs))

        model_call = crr_binomial_price(S, row.strike, T, r, sigma, steps, "call", q, american)
        model_put = crr_binomial_price(S, row.strike, T, r, sigma, steps, "put", q, american)

        market_call = row.lastPrice_call if row.lastPrice_call and row.lastPrice_call > 0 else np.nan
        market_put = row.lastPrice_put if row.lastPrice_put and row.lastPrice_put > 0 else np.nan

        rhs = put_call_parity_rhs(S, row.strike, T, r, q)

        records.append({
            "strike": row.strike,
            "sigma_used": sigma,
            "model_call": model_call,
            "model_put": model_put,
            "model_C_minus_P": model_call - model_put,
            "market_call": market_call,
            "market_put": market_put,
            "market_C_minus_P": market_call - market_put,
            "parity_rhs": rhs,  # S*e^(-qT) - K*e^(-rT)
            "model_parity_error": (model_call - model_put) - rhs,
            "market_parity_error": (market_call - market_put) - rhs,
        })

    if not records:
        raise ValueError("No strikes had a usable implied volatility quote to price with.")

    result = pd.DataFrame(records)
    meta = {
        "ticker": ticker_symbol, "expiry": expiry, "S": S, "r": r, "q": q,
        "T": T, "steps": steps, "skipped_no_iv": skipped_no_iv,
    }
    return result, meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Verify Put-Call Parity via a CRR binomial model using a live option chain."
    )
    ap.add_argument("--ticker", default="^SPX",
                     help="Underlying ticker (default: ^SPX -- European-style index options).")
    ap.add_argument("--expiry", default=None,
                     help="Expiry date YYYY-MM-DD. Defaults to the nearest listed expiry.")
    ap.add_argument("--steps", type=int, default=200,
                     help="Binomial tree steps (default: 200).")
    ap.add_argument("--american", action="store_true",
                     help="Price with early exercise allowed (American-style). "
                          "Off by default, since this script targets European parity.")
    ap.add_argument("--moneyness-band", type=float, default=0.15,
                     help="Keep strikes within +/- this fraction of spot (default 0.15 "
                          "= +/-15%%). Use 0 to disable filtering.")
    ap.add_argument("--rate", type=float, default=None,
                     help="Override the risk-free rate (decimal, e.g. 0.05). "
                          "Default: fetched from ^IRX.")
    ap.add_argument("--dividend-yield", type=float, default=None,
                     help="Override the continuous dividend yield (decimal). "
                          "Default: pulled from the ticker's info.")
    ap.add_argument("--csv", default=None, help="Path to save full results as CSV.")
    ap.add_argument("--plot", action="store_true", help="Save a parity-error-vs-strike plot.")
    args = ap.parse_args()

    # Haven't implemented this yet
    if not args.american and args.ticker.upper() not in EUROPEAN_STYLE_TICKERS:
        print(
            f"Note: '{args.ticker}' typically lists AMERICAN-style options, so market "
            "quotes will only satisfy put-call parity approximately (early-exercise "
            "premium + bid/ask noise). For an exact real-world check, use a European-style "
            f"index ticker such as {', '.join(sorted(EUROPEAN_STYLE_TICKERS))}, or pass "
            "--american to price this chain consistently with early exercise.\n"
        )

    band = None if args.moneyness_band == 0 else args.moneyness_band

    try:
        result, meta = build_parity_table(
            args.ticker, args.expiry, args.steps, args.american,
            band, args.rate, args.dividend_yield,
        )
    except Exception as e:
        sys.exit(f"Error: {e}")

    pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
    pd.set_option("display.width", 160)
    print(
        f"Ticker: {meta['ticker']}   Expiry: {meta['expiry']}   S={meta['S']:.2f}   "
        f"r={meta['r']:.4%}   q={meta['q']:.4%}   T={meta['T']:.4f}y   steps={meta['steps']}"
    )
    if meta["skipped_no_iv"]:
        print(f"(Skipped {meta['skipped_no_iv']} strikes with no usable implied volatility quote.)")
    print()
    print(result.to_string(index=False))

    print("\n--- Put-Call Parity summary ---")
    print(
        f"Mean |model parity error| : {result['model_parity_error'].abs().mean():.6f}  "
        "(should be ~0 -- the binomial tree is internally arbitrage-free by construction)"
    )
    print(
        f"Mean |market parity error|: {result['market_parity_error'].abs().mean():.6f}  "
        "(nonzero deviation reflects bid/ask spread, an early-exercise premium if "
        "American-style, stale quotes, or dividend/rate mis-estimates)"
    )

    if args.csv:
        result.to_csv(args.csv, index=False)
        print(f"\nSaved full results to {args.csv}")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.axhline(0, color="black", linewidth=0.8)
        ax.plot(result["strike"], result["model_parity_error"], marker="o",
                label="Model (binomial) parity error")
        ax.plot(result["strike"], result["market_parity_error"], marker="o",
                label="Market parity error")
        ax.set_xlabel("Strike")
        ax.set_ylabel("(C - P) - [S*e^(-qT) - K*e^(-rT)]")
        ax.set_title(f"Put-Call Parity Error -- {meta['ticker']} ({meta['expiry']})")
        ax.legend()
        fig.tight_layout()
        out = args.csv.replace(".csv", "_plot.png") if args.csv else "parity_plot.png"
        fig.savefig(out, dpi=150)
        print(f"Saved plot to {out}")


if __name__ == "__main__":
    main()