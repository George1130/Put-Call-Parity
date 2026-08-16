"""Live market data helpers via Yahoo Finance (yfinance)."""
from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    yf = None
    HAS_YF = False

# Retry transient network errors (timeouts / dropped connections). yfinance
# does not retry HTTP 429 rate limits by itself — see _rate_limited() below.
if HAS_YF:
    try:
        yf.config.network.retries = 3
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Thread-safe TTL cache, memory + disk.
#
# The web app is deployed on Render behind `gunicorn --workers 1 --threads 4`,
# so one process serves everyone and a process-local cache is shared and safe.
# Without caching, *every* page click fires several Yahoo Finance requests
# (expirations, spot, chain, dividends, ^IRX) from Render's shared datacenter
# IP, which Yahoo throttles with HTTP 429 ("Too Many Requests. Rate limited.").
#
# Two layers:
#   1. In-memory cache — fast path within a running process.
#   2. Disk cache in /tmp (PCP_CACHE_DIR) — survives Render free-plan
#      spin-downs and restarts, so repeat visitors never fetch cold.
#
# Plus a serve-stale fallback: if a fetch fails with a 429 but we hold recent
# (possibly expired) data on disk, we serve that instead of erroring. Freshness
# TTLs below decide when to re-fetch; the stale TTLs cap how old data may be
# before we refuse to serve it during an outage.
# ---------------------------------------------------------------------------

import os
import tempfile

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()

# Freshness TTLs (seconds): quotes move, so the chain is short-lived;
# expirations / dividends / the T-bill rate are stable.
TTL_RF = 3600.0          # ^IRX 13-week T-bill: ~1h
TTL_EXPIRATIONS = 900.0  # option expirations list: ~15min
TTL_SPOT = 60.0          # spot price: ~1min
TTL_CHAIN = 120.0        # option chain (bids/asks): ~2min
TTL_DIVIDENDS = 21600.0  # dividend schedule: ~6h

# Stale-serving ceilings: how old a disk copy may be before we refuse to serve
# it during a Yahoo outage / rate limit.
STALE_RF = 7 * 86400.0        # 1 week
STALE_EXPIRATIONS = 7 * 86400.0
STALE_SPOT = 86400.0          # 1 day
STALE_CHAIN = 86400.0         # 1 day
STALE_DIVIDENDS = 30 * 86400.0

STALE_GRACE = 60.0  # after serving stale, don't hammer Yahoo again for 1 min


def _cache_dir():
    d = os.environ.get("PCP_CACHE_DIR") or os.path.join(
        tempfile.gettempdir(), "put-call-parity-cache")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _cache_file(key):
    safe = "_".join(str(part).replace("/", "-") for part in key)
    return os.path.join(_cache_dir(), safe + ".json")


def _to_jsonable(v):
    if isinstance(v, dict) and "__df__" in v:
        return v  # already encoded
    if isinstance(v, (dt.datetime, dt.date)):
        return {"__date__": v.isoformat()}
    if hasattr(v, "to_json") and hasattr(v, "columns"):  # pandas DataFrame
        return {"__df__": True, "data": v.to_json(orient="split")}
    if isinstance(v, tuple):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    return v


def _from_jsonable(v):
    if isinstance(v, dict) and v.get("__df__"):
        # read_json treats single-line JSON strings as file paths; wrap in
        # StringIO so the split-orient payload is parsed as data.
        import io
        import pandas as pd
        return pd.read_json(io.StringIO(v["data"]), orient="split")
    if isinstance(v, dict) and "__date__" in v:
        s = v["__date__"]
        try:
            return dt.date.fromisoformat(s)
        except ValueError:
            return dt.datetime.fromisoformat(s)
    if isinstance(v, list):
        return [_from_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _from_jsonable(x) for k, x in v.items()}
    return v


def _disk_load(key):
    """Read a cache entry from disk. Returns dict(value, fetched_at,
    expires_at) or None. Expired entries are still returned — the caller
    decides whether to serve them stale."""
    import json
    path = _cache_file(key)
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        return {
            "value": _from_jsonable(raw["value"]),
            "fetched_at": float(raw["fetched_at"]),
            "expires_at": float(raw["expires_at"]),
        }
    except (OSError, ValueError, KeyError, TypeError):
        try:
            os.unlink(path)  # drop corrupt entries
        except OSError:
            pass
        return None


def _disk_save(key, value, expires_at):
    """Atomically write a cache entry to disk (tmp file + rename).

    Best-effort: the in-memory cache is the critical path, so any disk
    problem (full /tmp, exotic value, permissions) is logged, not raised."""
    import json
    path = _cache_file(key)
    try:
        payload = json.dumps({
            "fetched_at": time.time(),
            "expires_at": expires_at,
            "value": _to_jsonable(value),
        })
        tmp = path + f".tmp{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(payload)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        logging.getLogger(__name__).warning("disk cache write failed: %s", exc)
        try:
            os.unlink(tmp)
        except (OSError, NameError):
            pass
    _prune_disk()


_last_prune = [0.0]


def _prune_disk():
    """Drop entries older than 31 days; at most once per hour."""
    now = time.time()
    if now - _last_prune[0] < 3600.0:
        return
    _last_prune[0] = now
    try:
        cutoff = now - 31 * 86400.0
        for name in os.listdir(_cache_dir()):
            path = os.path.join(_cache_dir(), name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.unlink(path)
            except OSError:
                pass
    except OSError:
        pass


def _cached(key, ttl, stale_ttl, producer):
    """Return cached data or fetch+store it.

    Priority: fresh memory -> fresh disk -> fetch (with retry) -> stale disk.
    Failures that are NOT rate limits propagate immediately; only a 429 can
    trigger the serve-stale fallback.
    """
    key_s = str(key)
    now_m = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key_s)
        if entry is not None and entry[0] > now_m:
            return entry[1]

    now_t = time.time()
    disk = _disk_load(key)
    if disk is not None and disk["expires_at"] > now_t:
        with _CACHE_LOCK:
            _CACHE[key_s] = (now_m + (disk["expires_at"] - now_t), disk["value"])
        return disk["value"]

    try:
        value = producer()
    except Exception as exc:
        if (_is_rate_limit(exc) and disk is not None
                and (now_t - disk["fetched_at"]) <= stale_ttl):
            # Yahoo is throttling us; serve recent data instead of failing.
            with _CACHE_LOCK:
                _CACHE[key_s] = (time.monotonic() + STALE_GRACE, disk["value"])
            return disk["value"]
        raise

    expires_t = now_t + ttl
    with _CACHE_LOCK:
        _CACHE[key_s] = (time.monotonic() + ttl, value)
    _disk_save(key, value, expires_t)
    return value


def cache_info():
    """Cache state for /api/health: memory entries + disk file count."""
    now_m = time.monotonic()
    with _CACHE_LOCK:
        mem = {k: int(exp - now_m) for k, (exp, _) in _CACHE.items()}
    try:
        disk_files = len([n for n in os.listdir(_cache_dir())
                          if n.endswith(".json")])
    except OSError:
        disk_files = 0
    return {"memory": mem, "disk_files": disk_files}


def _is_rate_limit(exc):
    """True for yfinance's YFRateLimitError (any version) or 429-looking text."""
    if type(exc).__name__ == "YFRateLimitError":
        return True
    msg = str(exc)
    return "Too Many Requests" in msg or "Rate limit" in msg


# --- Yahoo call pacing ------------------------------------------------------
# Render free instances share egress IPs with many apps. Serialize our Yahoo
# requests (one process, 4 gunicorn threads) with a tiny delay between them so
# a page load doesn't arrive as a burst that trips the rate limiter.

_YF_LOCK = threading.Lock()
_YF_PACE = 0.25  # seconds between Yahoo calls


def _yf_call(producer):
    with _YF_LOCK:
        time.sleep(_YF_PACE)
        return producer()


def _rate_limited(producer, attempts=4, base_delay=3.0):
    """Retry a Yahoo call that hit the 429 rate limit with a backoff.

    yfinance only auto-retries network timeouts, not HTTP 429s. A shared-IP
    rate limit usually clears within seconds; 4 attempts = ~18s worst case.
    Retry sleeps happen OUTSIDE _YF_LOCK so other threads can keep working.
    """
    from yfinance.exceptions import YFRateLimitError
    for attempt in range(attempts):
        try:
            return _yf_call(producer)
        except YFRateLimitError:
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * (attempt + 1))


def _require_yf():
    if not HAS_YF:
        raise RuntimeError(
            "yfinance is not installed. In the project venv run:\n"
            "    ./venv/bin/pip install yfinance pandas")


def _cache_key(t):
    """Stable cache key for a Ticker object (yfinance tickers are cheap to
    rebuild but not hashable for long-lived caching)."""
    return str(getattr(t, "ticker", t)).upper()


def get_rf_rate():
    """Risk-free proxy: 13-week T-bill (^IRX) yield, as a fraction. Returns (rate, source)."""
    return _cached(("rf",), TTL_RF, STALE_RF,
                   lambda: _rate_limited(_fetch_rf_rate))


def _fetch_rf_rate():
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
    return _cached(("spot", _cache_key(t)), TTL_SPOT, STALE_SPOT,
                   lambda: _rate_limited(lambda: _fetch_spot(t)))


def _fetch_spot(t):
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
    return _cached(("exp", _cache_key(t)), TTL_EXPIRATIONS, STALE_EXPIRATIONS,
                   lambda: _rate_limited(lambda: _fetch_expirations(t)))


def _fetch_expirations(t):
    return list(t.options)


def get_chain(t, expiry):
    return _cached(("chain", _cache_key(t), expiry), TTL_CHAIN, STALE_CHAIN,
                   lambda: _rate_limited(lambda: _fetch_chain(t, expiry)))


def _fetch_chain(t, expiry):
    oc = t.option_chain(expiry)
    return oc.calls, oc.puts


def dividend_profile(t):
    """Infer dividend schedule from history. Returns dict or None."""
    return _cached(("div", _cache_key(t)), TTL_DIVIDENDS, STALE_DIVIDENDS,
                   lambda: _rate_limited(lambda: _fetch_dividend_profile(t)))


def _fetch_dividend_profile(t):
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
