"""Live market data helpers via Yahoo Finance (yfinance)."""
from __future__ import annotations

import datetime as dt
import logging
import math

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    yf = None
    HAS_YF = False


def _require_yf():
    if not HAS_YF:
        raise RuntimeError(
            "yfinance is not installed. In the project venv run:\n"
            "    ./venv/bin/pip install yfinance pandas")


def get_rf_rate():
    """Risk-free proxy: 13-week T-bill (^IRX) yield, as a fraction. Returns (rate, source)."""
    _require_yf()
    try:
        irx = yf.Ticker("^IRX")
        fi = irx.fast_info
        v = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
        if v is not None and float(v) >= 0:
            return float(v) / 100.0, "^IRX (13-week T-bill)"
    except Exception:
        pass
    try:
        h = yf.Ticker("^IRX").history(period="5d")
        if len(h) and not math.isnan(float(h["Close"].iloc[-1])):
            return float(h["Close"].iloc[-1]) / 100.0, "^IRX (13-week T-bill)"
    except Exception:
        pass
    return None, None


def get_ticker(ticker):
    _require_yf()
    return yf.Ticker(ticker)


def get_spot(t):
    """Returns (price, bid, ask, currency) or (None,)*3."""
    price = bid = ask = None
    cur = "USD"
    try:
        fi = t.fast_info
        price = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
        cur = getattr(fi, "currency", "USD")
    except Exception:
        pass
    try:
        info = t.get_info()
        if price is None:
            price = info.get("regularMarketPrice") or info.get("currentPrice")
        bid = info.get("bid")
        ask = info.get("ask")
        cur = info.get("currency") or cur
    except Exception:
        pass
    if price is None:
        return None, None, None, None
    b = _num(bid) or float(price)
    a = _num(ask) or float(price)
    return float(price), b, a, (cur or "USD")


def get_expirations(t):
    return list(t.options)


def get_chain(t, expiry):
    oc = t.option_chain(expiry)
    return oc.calls, oc.puts


def dividend_profile(t):
    """Infer dividend schedule from history. Returns dict or None."""
    try:
        divs = t.get_dividends()
    except Exception:
        divs = None
    try:
        info = t.get_info()
    except Exception:
        info = {}

    rate = info.get("dividendRate")
    amount = None
    freq_days = 365.0
    last_date = None

    if divs is not None and len(divs) > 0:
        s = divs.dropna()
        if len(s) > 0:
            vals = [float(v) for v in s.values]
            last_date = s.index[-1].date()
            if len(vals) >= 2:
                idx = list(s.index)
                gaps = [(idx[i + 1] - idx[i]).days for i in range(max(0, len(idx) - 8), len(idx) - 1)]
                gaps = [g for g in gaps if g > 0]
                if gaps:
                    med = float(sorted(gaps)[len(gaps) // 2])
                    if 50 <= med <= 120:
                        freq_days = 91.25
                    elif 15 <= med <= 45:
                        freq_days = 30.44
                    elif med > 200:
                        freq_days = 365.0
                    else:
                        freq_days = float(med)
            recent = vals[-4:]
            if recent:
                amount = float(sorted(recent)[len(recent) // 2])

    if amount is None:
        if rate:
            amount = float(rate) / (365.0 / freq_days)
        else:
            return None
    if amount <= 0:
        return None

    return {
        "amount": amount,
        "freq_days": freq_days,
        "last_date": last_date,
        "annual_rate": float(rate) if rate else amount * (365.0 / freq_days),
    }


def expected_dividends(t, expiry_str, rf=None, today_=None):
    """Dividends expected between today and expiry. Returns a dict."""
    profile = dividend_profile(t)
    today_ = today_ or dt.date.today()
    expiry = dt.date.fromisoformat(expiry_str)
    if profile is None:
        return {"pays": False, "amount": 0.0, "freq_days": None, "dates": [],
                "total": 0.0, "pv": 0.0}

    amount, freq = profile["amount"], profile["freq_days"]
    dates = []
    d = profile["last_date"]
    guard = 0
    while d is not None and d <= expiry and guard < 60:
        guard += 1
        if d > today_:
            dates.append(d)
        d = d + dt.timedelta(days=freq)

    total = amount * len(dates)
    if total > 0 and rf is not None:
        pv = sum(amount * math.exp(-rf * (d - today_).days / 365.0) for d in dates)
    else:
        pv = total

    return {"pays": True, "amount": amount, "freq_days": freq,
            "dates": dates, "total": total, "pv": pv}


def _num(x):
    try:
        v = float(x)
        return v if not math.isnan(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _mid(bid, ask, last):
    b, a, l = _num(bid), _num(ask), _num(last)
    return (b + a) / 2.0 if (b > 0 and a > 0) else l


def choose_expiry(t, expirations, today_=None):
    """Nearest expiry at least ~1 week out; fallback to the earliest listed."""
    today_ = today_ or dt.date.today()
    if not expirations:
        return None
    for e in sorted(expirations):
        if dt.date.fromisoformat(e) >= today_ + dt.timedelta(days=7):
            return e
    return sorted(expirations)[0]


def build_surface(ticker, expiry=None, rf=None, use_dividends=True, min_oi=0):
    """Fetch spot + option chain from Yahoo and compute the parity surface."""
    from put_call_parity import analyze

    t = get_ticker(ticker)
    spot, spot_bid, spot_ask, cur = get_spot(t)
    if spot is None:
        raise RuntimeError(f"Could not fetch a spot price for {ticker!r}.")

    expirations = get_expirations(t)
    if not expirations:
        raise RuntimeError(f"No listed options for {ticker!r}.")

    if expiry is None:
        expiry = choose_expiry(t, expirations)
    if expiry not in expirations:
        raise RuntimeError(f"Expiry {expiry} not available. First few: {', '.join(expirations[:5])}")

    if rf is None:
        rf, rf_src = get_rf_rate()
        if rf is None:
            rf, rf_src = 0.03, "default 3% (could not fetch ^IRX)"
    else:
        rf_src = "user-provided"

    calls, puts = get_chain(t, expiry)

    div = expected_dividends(t, expiry, rf) if use_dividends else \
        {"pays": False, "amount": 0.0, "freq_days": None, "dates": [], "total": 0.0, "pv": 0.0}
    pv_d = div["pv"]

    today_ = dt.date.today()
    days = (dt.date.fromisoformat(expiry) - today_).days
    T = days / 365.0
    if T <= 0:
        raise RuntimeError(f"Expiry {expiry} has already passed.")

    ccols = ["strike", "bid", "ask", "lastPrice", "openInterest", "volume"]
    c = calls[ccols].copy()
    p = puts[ccols].copy()
    df = c.merge(p, on="strike", suffixes=("_c", "_p"))
    df = df.sort_values("strike")

    rows = []
    for _, r in df.iterrows():
        cb, ca = _num(r["bid_c"]), _num(r["ask_c"])
        pb, pa = _num(r["bid_p"]), _num(r["ask_p"])
        cl, pl = _num(r["lastPrice_c"]), _num(r["lastPrice_p"])
        call_two = cb > 0 and ca > 0
        put_two = pb > 0 and pa > 0
        if call_two and put_two:
            qflag = "full"
        elif call_two or put_two:
            qflag = "partial"
        else:
            qflag = "stale"
        C = _mid(cb, ca, cl)
        P = _mid(pb, pa, pl)
        if C <= 0 and P <= 0:
            continue
        oi_c = int(_num(r["openInterest_c"]))
        oi_p = int(_num(r["openInterest_p"]))
        oi_total = oi_c + oi_p
        res = analyze(spot, float(r["strike"]), rf, T, C, P, pv_d=pv_d)
        res_raw = analyze(spot, float(r["strike"]), rf, T, C, P, pv_d=0.0)
        pv_total = res["PV(K)"] + pv_d
        if qflag == "full" and oi_c > 0 and oi_p > 0:
            if res["diff"] > 0:  # left rich: sell call @ bid, buy put @ ask, buy stock @ ask, borrow
                tradeable = cb - pa - spot_ask + pv_total
            else:                # right rich: buy call @ ask, sell put @ bid, short stock @ bid, lend
                tradeable = pb + spot_bid - ca - pv_total
        else:
            tradeable = None
        rows.append({
            "strike": float(r["strike"]),
            "call_bid": cb, "call_ask": ca, "call_mid": C,
            "put_bid": pb, "put_ask": pa, "put_mid": P,
            "call_oi": oi_c, "put_oi": oi_p, "oi_total": oi_total,
            "call_vol": int(_num(r["volume_c"])), "put_vol": int(_num(r["volume_p"])),
            "qflag": qflag,
            "liquid": oi_total >= min_oi,
            "tradeable": tradeable,
            "res": res,
            "res_raw": res_raw,
        })

    return {
        "ticker": ticker, "currency": cur, "spot": spot,
        "spot_bid": spot_bid, "spot_ask": spot_ask,
        "rf": rf, "rf_source": rf_src, "expiry": expiry,
        "days": days, "T": T, "expirations": expirations,
        "dividend": div, "pv_d": pv_d,
        "rows": rows,
    }
