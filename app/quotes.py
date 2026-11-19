"""Prices and exchange rates. Yahoo Finance (unofficial) first, Twelve Data (optional key) as fallback, ECB rates via Frankfurter.

Politeness rules, by design: an honest client identifier (no browser impersonation), one request at a time, at least
1.2 s between two requests to the same service, and on the first refusal (429) the series stops: the last known price is kept and the
page says so. No quantity or amount ever leaves the host: only ISINs and symbols are sent.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

# TODO: replace louispro02 with the actual GitHub username/org before launch
UA = "FolioLib/1.0 (+https://github.com/louispro02/foliolib; personal portfolio tracker, cached)"
GAP = 1.2
_lock = threading.Lock()
_last = {}


class Refused(Exception):
    """The service asks to slow down (429) or refuses: the series stops."""


def _get(url, host_key, headers=None, timeout=15):
    with _lock:
        wait = _last.get(host_key, 0) + GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host_key] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read(4_000_000).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (429, 403):
                raise Refused(f"{host_key} : HTTP {e.code}") from None
            if e.code == 404:
                return None
            if attempt == 0 and e.code >= 500:
                time.sleep(2)
                continue
            raise Refused(f"{host_key} : HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            if attempt == 0:
                time.sleep(2)
                continue
            raise Refused(f"{host_key} : {type(e).__name__}") from None


# ---------------------------------------------------------------- Yahoo
def yahoo_search(query):
    d = _get("https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode(
        {"q": query, "quotesCount": 8, "newsCount": 0, "listsCount": 0}), "yahoo")
    return [q["symbol"] for q in (d or {}).get("quotes", []) if q.get("symbol")]


def yahoo_chart(symbol, rng="5d", start=None):
    """-> {'ccy', 'price', 'time', 'closes': {YYYY-MM-DD: close}} or None if the symbol does not exist.
    `start` (YYYY-MM-DD) requests **daily** prices from that date: with `range=max`, Yahoo returns monthly data."""
    params = {"interval": "1d"}
    if start:
        params["period1"] = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        params["period2"] = int(time.time()) + 86400
    else:
        params["range"] = rng
    d = _get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol) + "?" + urllib.parse.urlencode(params), "yahoo")
    try:
        res = d["chart"]["result"][0]
        meta, ts = res["meta"], res.get("timestamp") or []
        closes = res["indicators"]["quote"][0]["close"]
    except (TypeError, KeyError, IndexError):
        return None
    ccy, scale = meta.get("currency") or "", 1.0
    if ccy == "GBp":        # pence: one pound = 100 pence
        ccy, scale = "GBP", 0.01
    out = {}
    for t, c in zip(ts, closes):
        if c is not None:
            out[datetime.fromtimestamp(t, timezone.utc).date().isoformat()] = c * scale
    price = meta.get("regularMarketPrice")
    if price is None and out:
        price = out[max(out)] / scale
    if price is None:
        return None
    return {"ccy": ccy, "price": price * scale, "time": meta.get("regularMarketTime"), "closes": out}


SUFFIXES = (".DE", ".PA", ".AS", ".MI", ".L")


def candidates(isin, search_hits):
    """Symbols to try: search results, then the same base code on euro exchanges."""
    seen, out = set(), []
    for s in search_hits:
        if "." not in s or s.split(".")[-1] not in ("SG", "F", "BE", "MU", "DU", "HM", "VI"):   # secondary German exchanges: unreliable prices
            if s not in seen:
                seen.add(s)
                out.append(s)
    bases = {s.split(".")[0] for s in out if "." in s or s.isalpha()}
    for s in list(out):                                  # Milan prefixes foreign stocks with a "1": 1GOOGL.MI -> GOOGL (home exchange)
        b = s.split(".")[0]
        if b[:1].isdigit() and b[1:].isalpha() and b[1:] not in seen:
            seen.add(b[1:])
            out.append(b[1:])
    for b in sorted(bases):
        for suf in SUFFIXES:
            s = b + suf
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out[:10]


def resolve(isin, want_ccy=None, ref_price=None):
    """Find the Yahoo symbol of an ISIN. Prefers the export's currency, then a price close to the reference price (±4 %)."""
    hits = yahoo_search(isin)
    best = None
    for sym in candidates(isin, hits):
        c = yahoo_chart(sym, "5d")
        if not c:
            continue
        score = 0
        if want_ccy and c["ccy"] == want_ccy:
            score += 2
        elif c["ccy"] == "EUR":
            score += 1
        if ref_price and c["price"] and abs(c["price"] / ref_price - 1) < 0.04:
            score += 3
        if best is None or score > best[0]:
            best = (score, sym, c)
        if score >= 5:
            break
    return (best[1], best[2]) if best else (None, None)


# ---------------------------------------------------------------- Twelve Data (optional)
def twelvedata_close(symbol, key):
    d = _get("https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(
        {"symbol": symbol, "interval": "1day", "outputsize": 5, "apikey": key}), "twelvedata")
    if not d or d.get("status") == "error" or not d.get("values"):
        return None
    v = d["values"][0]
    return {"ccy": (d.get("meta") or {}).get("currency", ""), "price": float(v["close"]), "time": None,
            "closes": {x["datetime"][:10]: float(x["close"]) for x in d["values"]}}


# ---------------------------------------------------------------- FX: ECB via Frankfurter
def ecb_rates(ccy, start, end):
    """{YYYY-MM-DD: units of ccy per 1 EUR}, business days only."""
    if ccy == "EUR":
        return {}
    d = _get(f"https://api.frankfurter.dev/v1/{start}..{end}?" + urllib.parse.urlencode({"base": "EUR", "symbols": ccy}), "frankfurter")
    return {day: v[ccy] for day, v in (d or {}).get("rates", {}).items() if ccy in v}


def today():
    return date.today().isoformat()
