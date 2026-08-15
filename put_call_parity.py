#!/usr/bin/env python3
"""
Put-Call Parity Model for European options.

    C + PV(K) + PV(D) = P + S      where   PV(K) = K * exp(-r * T)

PV(D) is the present value of any dividends paid during the option's life;
set pv_d = 0 for non-dividend-paying assets (the classic textbook form).

Two modes:

1) Manual quotes:
   python put_call_parity.py --spot 100 --strike 100 --rate 5 --t 0.5 --call 8 --put 5

2) Live market scan (Yahoo Finance via yfinance):
   python put_call_parity.py --ticker AAPL
   python put_call_parity.py --ticker AAPL --expiry 2026-09-18 --top 5 --no-dividends
"""

import argparse
import math

TOLERANCE = 0.01  # $0.01 per share before a trade is flagged

MONEY = lambda x: f"${x:,.4f}"
MONEY2 = lambda x: f"${x:,.2f}"


def analyze(S, K, r, T, C, P, tolerance=TOLERANCE, pv_d=0.0):
    """Core Put-Call Parity model. Returns a dict of results."""
    pv_k = K * math.exp(-r * T)
    left = C + pv_k + pv_d
    right = P + S
    diff = left - right
    abs_diff = abs(diff)

    fair_p = left - S
    fair_c = right - pv_k - pv_d

    if abs_diff <= tolerance:
        status = "parity"
        trade = None
    elif diff > 0:
        status = "arb_left_rich"
        label = "PV(K)" if pv_d <= 1e-12 else "PV(K)+PV(D)"
        trade = {
            "direction": "Left side rich -> sell call, buy put, buy stock, borrow " + label,
            "legs": [
                ("Sell 1 Call", +C),
                ("Buy 1 Put", -P),
                ("Buy 1 Stock", -S),
                (f"Borrow {label}", +(pv_k + pv_d)),
            ],
        }
    else:
        status = "arb_right_rich"
        label = "PV(K)" if pv_d <= 1e-12 else "PV(K)+PV(D)"
        trade = {
            "direction": "Right side rich -> buy call, sell put, short stock, lend " + label,
            "legs": [
                ("Buy 1 Call", -C),
                ("Sell 1 Put", +P),
                ("Short 1 Stock", +S),
                (f"Lend {label}", -(pv_k + pv_d)),
            ],
        }

    return {
        "S": S, "K": K, "r": r, "T": T, "C": C, "P": P, "pv_d": pv_d,
        "rT": r * T,
        "PV(K)": pv_k,
        "PV(D)": pv_d,
        "left": left, "right": right,
        "diff": diff, "abs_diff": abs_diff,
        "fair_p": fair_p, "fair_c": fair_c,
        "status": status,
        "trade": trade,
        "profit": abs_diff if status != "parity" else 0.0,
        "profit_expiry": abs_diff * math.exp(r * T) if status != "parity" else 0.0,
    }


def print_report(res):
    print("=" * 62)
    print("PUT-CALL PARITY MODEL  |  C + PV(K) + PV(D) = P + S")
    print("=" * 62)
    print(f"Spot  S                : {MONEY(res['S'])}")
    print(f"Strike K               : {MONEY(res['K'])}")
    print(f"Risk-free rate r       : {res['r'] * 100:.4f}% p.a. (continuous)")
    print(f"Time to expiry T       : {res['T']:.4f} years  ({res['T'] * 365:.2f} days)")
    print(f"Call price C (market)  : {MONEY(res['C'])}")
    print(f"Put price P (market)   : {MONEY(res['P'])}")
    print("-" * 62)
    print(f"PV(K)  = K*exp(-rT)    : {MONEY(res['PV(K)'])}   (rT = {res['rT']:.6f})")
    if res["pv_d"] > 1e-12:
        print(f"PV(D)  (dividends)     : {MONEY(res['PV(D)'])}")
    print(f"LEFT   = C + PV(K)     : {MONEY(res['left'])}"
          + (" + PV(D)" if res["pv_d"] > 1e-12 else ""))
    print(f"RIGHT  = P + S         : {MONEY(res['right'])}")
    print(f"Fair Put = C+PV(K)-S   : {MONEY(res['fair_p'])}   (market {MONEY(res['P'])}, "
          f"{'over' if res['P'] > res['fair_p'] else 'under'}priced)")
    print(f"Fair Call = P+S-PV(K)  : {MONEY(res['fair_c'])}   (market {MONEY(res['C'])}, "
          f"{'over' if res['C'] > res['fair_c'] else 'under'}priced)")
    print("-" * 62)

    if res["status"] == "parity":
        print(f"VERDICT: Parity HOLDS within tolerance "
              f"({MONEY(res['abs_diff'])} <= {MONEY(TOLERANCE)}).  No arbitrage.")
    else:
        print(f"VERDICT: PARITY VIOLATED by {MONEY(res['abs_diff'])} "
              f"({res['abs_diff'] / max(res['right'], 1e-12) * 100:.4f}% of P+S).  ARBITRAGE AVAILABLE.")
        print()
        print("ARBITRAGE TRADE:")
        print("  " + res["trade"]["direction"])
        total = 0.0
        for leg, cf in res["trade"]["legs"]:
            total += cf
            sign = "+" if cf >= 0 else "-"
            print(f"    {leg:<18} {sign}{MONEY(abs(cf)):>12}")
        print(f"    {'Net cash now':<18} +{MONEY(total):>12}")
        print(f"  Riskless profit today    : {MONEY(res['profit'])} per share")
        print(f"  Riskless profit at expiry: {MONEY(res['profit_expiry'])} per share (any S_T)")
        print("  Net payoff at expiry is zero for every spot; profit is locked in.")

    print("=" * 62)
    print("Per standard equity contract (x100):", MONEY(res["profit"] * 100), "riskless profit.")
    print("Assumes European options, no transaction costs/frictions, unlimited borrowing")
    print("at the risk-free rate, no short-sell constraints.")


def plot_payoff(res):
    """Flat payoff diagram: riskless profit is constant for any S_T."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[--plot] matplotlib not installed. Run: pip install matplotlib")
        return

    S, K, r, T = res["S"], res["K"], res["r"], res["T"]
    profit_today = res["profit"]
    profit_expiry = res["profit_expiry"]

    xs = [0.4 * min(S, K) + (1.6 * max(S, K) - 0.4 * min(S, K)) * i / 200 for i in range(201)]
    ys = [profit_expiry] * len(xs)  # flat line: independent of S_T

    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")
    ax.plot(xs, ys, lw=2.5, color="#3fb950", label=f"Profit at expiry = ${profit_expiry:.2f} (any S_T)")
    if profit_today > 0:
        ax.axhline(profit_today, lw=1.2, ls="--", color="#58a6ff",
                   label=f"Profit captured today = ${profit_today:.2f}")
        ax.fill_between(xs, 0, profit_today, color="#3fb950", alpha=0.12)
    ax.axhline(0, color="#8b949e", lw=1)
    ax.set_title("Put-Call Parity Arbitrage — Riskless Profit at Expiry", color="#e6edf3")
    ax.set_xlabel("Spot at expiry  S_T", color="#8b949e")
    ax.set_ylabel("P&L", color="#8b949e")
    ax.tick_params(colors="#8b949e")
    for spine in ax.spines.values():
        spine.set_color("#2d333b")
    ax.legend(facecolor="#161b22", edgecolor="#2d333b", labelcolor="#e6edf3")
    ax.grid(True, color="#21262d", lw=0.6)
    plt.tight_layout()
    plt.show()


def scan_live(ticker, expiry=None, rf_pct=None, min_oi=10, top=5, use_dividends=True, loose=False):
    """Fetch live quotes via yfinance and scan the chain for parity violations."""
    import market_data

    if not market_data.HAS_YF:
        raise SystemExit(
            "yfinance/pandas are not installed. In the project venv run:\n"
            "    ./venv/bin/pip install yfinance pandas")

    try:
        surf = market_data.build_surface(
            ticker, expiry=expiry,
            rf=(float(rf_pct) / 100.0) if rf_pct is not None else None,
            use_dividends=use_dividends, min_oi=0)
    except Exception as exc:
        raise SystemExit(f"Live data error: {exc}")

    div = surf["dividend"]
    print("=" * 78)
    print(f"LIVE PUT-CALL PARITY SCAN - {surf['ticker'].upper()} ({surf['currency']})")
    print("=" * 78)
    print(f"Spot     : {MONEY2(surf['spot'])}   (bid {MONEY2(surf['spot_bid'])} / ask {MONEY2(surf['spot_ask'])})")
    print(f"Risk-free: {surf['rf'] * 100:.3f}% p.a. ({surf['rf_source']})")
    print(f"Expiry   : {surf['expiry']}  ({surf['days']} days, T = {surf['T']:.5f} y)")
    if div["pays"]:
        print(f"Dividends: {div['freq_days']:.0f}-day schedule, ${div['amount']:.3f}/share, "
              f"{len(div['dates'])} payment(s) before expiry, PV(D) = {MONEY2(div['pv'])}")
    else:
        print("Dividends: none detected")
    print("Quotes   : mid = (bid+ask)/2 (lastPrice fallback if no two-sided quote).")
    print("           NET = mid-based parity violation minus the cost of crossing the")
    print("           bid/ask spread on all legs. Positive NET = actually tradeable.")
    print("           By default, strikes with |mid delta| > 1% of spot are excluded")
    print("           (almost always stale Yahoo quotes). Use --loose to include them.")
    print("=" * 78)

    # keep only: two-sided quotes on both options, OI on both legs, plausible magnitude
    sanity_cap = None if loose else 0.01 * surf["spot"]
    if loose:
        base = [r for r in surf["rows"] if r["liquid"]]
    else:
        base = [r for r in surf["rows"]
                if r["qflag"] == "full" and r["call_oi"] > 0 and r["put_oi"] > 0
                and r["res"]["abs_diff"] <= sanity_cap]
    cand = [r for r in base if r["res"]["status"] != "parity"]
    cand.sort(key=lambda r: -(r["tradeable"] if r["tradeable"] is not None else r["res"]["abs_diff"]))

    if not cand:
        print("No parity violations above tolerance among liquid, fully-quoted strikes.")
        return

    print(f"{'#':>3} {'Strike':>8} {'Call':>9} {'Put':>9} {'FairC':>9} {'FairP':>9} "
          f"{'MID Δ':>9} {'NET':>8} {'OI c/p':>10}  Side")
    print("-" * 78)
    for i, r in enumerate(cand[:top], 1):
        res = r["res"]
        side = "LEFT rich" if res["diff"] > 0 else "RIGHT rich"
        net = r["tradeable"]
        net_s = f"{net:+.3f}" if net is not None else "n/a"
        print(f"{i:>3} {r['strike']:>8.2f} {MONEY2(r['call_mid']):>9} {MONEY2(r['put_mid']):>9} "
              f"{MONEY2(res['fair_c']):>9} {MONEY2(res['fair_p']):>9} "
              f"{res['abs_diff']:>+9.3f} {net_s:>8} "
              f"{r['call_oi']:>4}/{r['put_oi']:<5}  {side}")
    print("-" * 78)
    n_tr = sum(1 for r in cand[:top] if r["tradeable"] is not None and r["tradeable"] > 0)
    print(f"{n_tr} of the top {min(top, len(cand))} strikes have NET profit > 0 "
          f"(profitable after crossing the spread).")
    print("\nBest opportunity (top of list), full detail:")
    print()
    print_report(cand[0]["res"])


def parse_args():
    p = argparse.ArgumentParser(
        description="Put-Call Parity model: C + PV(K) + PV(D) = P + S, with arbitrage detection.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # manual mode
    p.add_argument("--spot", type=float, help="Spot price S")
    p.add_argument("--strike", type=float, help="Strike price K")
    p.add_argument("--rate", type=float, help="Risk-free rate r, percent p.a. (continuous)")
    p.add_argument("--t", type=float, help="Time to expiry T, in years")
    p.add_argument("--call", type=float, help="Call price C")
    p.add_argument("--put", type=float, help="Put price P")
    p.add_argument("--plot", action="store_true", help="Show payoff diagram")
    p.add_argument("--tolerance", type=float, default=TOLERANCE,
                   help="Mispricing threshold ($/share) before flagging arbitrage")
    # live mode
    p.add_argument("--ticker", type=str, help="Live mode: Yahoo Finance ticker to scan (e.g. AAPL)")
    p.add_argument("--expiry", type=str, help="Live mode: expiration date YYYY-MM-DD (default: nearest)")
    p.add_argument("--rf", type=float, help="Live mode: override risk-free rate, percent p.a.")
    p.add_argument("--top", type=int, default=5, help="Live mode: show top N violations")
    p.add_argument("--min-oi", type=int, default=10,
                   help="Live mode: minimum total open interest to consider a strike")
    p.add_argument("--no-dividends", action="store_true",
                   help="Live mode: ignore dividend adjustment (classic non-dividend model)")
    p.add_argument("--loose", action="store_true",
                   help="Live mode: also include strikes without two-sided quotes on both options")
    return p.parse_args()


def interactive():
    def ask(prompt, cast=float):
        while True:
            try:
                return cast(input(prompt).strip())
            except ValueError:
                print("  Invalid number, try again.")

    print("Enter market inputs:")
    S = ask("  Spot price S            : ")
    K = ask("  Strike price K          : ")
    r = ask("  Risk-free rate r (% p.a.): ") / 100.0
    T = ask("  Time to expiry T (years): ")
    C = ask("  Call price C            : ")
    P = ask("  Put price P             : ")
    return S, K, r, T, C, P


def main():
    args = parse_args()

    if args.ticker:
        scan_live(args.ticker, expiry=args.expiry, rf_pct=args.rf,
                  min_oi=args.min_oi, top=args.top, use_dividends=not args.no_dividends,
                  loose=args.loose)
        return

    if args.spot is None:
        S, K, r, T, C, P = interactive()
    else:
        vals = (args.spot, args.strike, args.rate, args.t, args.call, args.put)
        missing = [name for name, v in zip(
            ["spot", "strike", "rate", "t", "call", "put"], vals) if v is None]
        if missing:
            raise SystemExit(f"Missing CLI arguments: {', '.join(missing)}")
        S, K, r, T, C, P = vals
        r = r / 100.0

    res = analyze(S, K, r, T, C, P, tolerance=args.tolerance)
    print_report(res)
    if args.plot:
        plot_payoff(res)


if __name__ == "__main__":
    main()
