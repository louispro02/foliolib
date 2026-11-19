"""Demo mode: a fully synthetic portfolio, so anyone can try FolioLib in seconds without any real data or network access.

`python main.py demo` fills an EMPTY database with two years of fictitious activity on a fictitious DEGIRO account:
monthly deposits, purchases of a world ETF and two stocks, quarterly dividends with withholding tax, and a few fees.
Prices are generated from a seeded random walk (the same data on every run) and are never refreshed from the network.

Nothing here is real: names, ISINs, symbols, prices and amounts are made up. The database is flagged as a demo
(`meta.demo`), which blocks importing real files into it until it is erased from the page ("Erase imported data").
"""
import math
import random
import time
from datetime import date, timedelta

import engine
import parsers
import perf
import store

SEED = "foliolib-demo-82"   # changes the synthetic price paths; fixed so the demo is identical on every run
MONTHS = 24
DEPOSIT = 500.0          # monthly deposit, EUR
ORDER_FEE = 2.0          # brokerage fee per order, EUR
CONNECTION_FEE = 2.5     # yearly exchange connection fee, EUR
TTF_RATE = 0.004         # financial transaction tax on the French stock
WITHHOLDING = 0.30       # tax withheld on dividends
BLUE_DIVIDEND = 0.45     # quarterly dividend per share of the blue chip, EUR

# key, ISIN, name, symbol, start price, annual drift, annual volatility, correlation with the market. All priced in euros.
INSTRUMENTS = [
    ("etf", "IE0000000001", "DEMO WORLD ETF", "DEMOETF", 80.0, 0.08, 0.15, 0.90),
    ("tech", "US0000000002", "DEMO TECH INC", "DEMOTECH", 120.0, 0.14, 0.30, 0.75),
    ("blue", "FR0000000003", "DEMO BLUE CHIP SA", "DEMOBLUE", 45.0, 0.05, 0.18, 0.65),
]
# start price, annual drift, annual volatility, correlation with the market, for each benchmark of engine.BENCHMARKS
# ("world" reuses the demo ETF's path)
BENCH_PARAMS = {"sp500": (400.0, 0.10, 0.16, 0.92), "nasdaq": (900.0, 0.13, 0.24, 0.85),
                "em": (28.0, 0.04, 0.16, 0.60), "eu600": (95.0, 0.06, 0.15, 0.80), "cac": (150.0, 0.05, 0.17, 0.80)}


def _walk(name, start, mu, sigma, rho, days):
    """Deterministic daily closes: a geometric random walk seeded by the instrument's name. Every instrument shares the
    same market shocks (weighted by `rho`), so the prices move together the way real markets do."""
    market, own = random.Random(SEED + "-market"), random.Random(SEED + "-" + name)
    px, out = start, {}
    for d in days:
        z = rho * market.gauss(0, 1) + math.sqrt(1 - rho ** 2) * own.gauss(0, 1)
        px *= math.exp((mu - 0.5 * sigma ** 2) / 252 + sigma / math.sqrt(252) * z)
        out[d.isoformat()] = round(px, 4)
    return out


def _business_day(d):
    """Shift a weekend date to the following Monday."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _months_back(today, n):
    """First day of the month `n` months before `today`'s month."""
    y, m = today.year, today.month - n
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def build(today=None):
    """-> (records by file type, price series by symbol, last price by symbol). Pure: touches no database."""
    today = today or date.today()
    first = _months_back(today, MONTHS)
    months = []
    d = first
    while d <= today:
        months.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)

    start = _business_day(date(first.year, first.month, 3))
    days = perf.weekdays(start - timedelta(days=14), today)
    series = {sym: _walk(sym, p0, mu, sg, rho, days) for _, _, _, sym, p0, mu, sg, rho in INSTRUMENTS}
    for key, _, sym, _ in engine.BENCHMARKS:
        if key == "world":
            series[sym] = series["DEMOETF"]      # the demo world ETF tracks the demo "MSCI World" index
            continue
        p0, mu, sg, rho = BENCH_PARAMS[key]
        series[sym] = _walk(sym, p0, mu, sg, rho, days)

    tx, acct = [], []
    held = {k: 0.0 for k, *_ in INSTRUMENTS}
    cash = 0.0
    info = {k: (isin, name, sym) for k, isin, name, sym, *_ in INSTRUMENTS}
    for n, month in enumerate(months):
        day = _business_day(date(month.year, month.month, 3))
        if day > today:
            break
        ds = day.isoformat()
        acct.append({"type": "deposit", "broker": "degiro", "date": ds, "name": "", "isin": "", "ccy": "EUR", "amount": DEPOSIT})
        cash += DEPOSIT
        orders = [("etf", 380.0)] + ([("tech", 100.0)] if n % 2 == 0 else []) + ([("blue", 100.0)] if n % 3 == 0 else [])
        for key, budget in orders:
            isin, name, sym = info[key]
            px = series[sym][ds]
            qty = max(1, int(budget // px))
            gross = qty * px
            tx.append({"type": "trade", "broker": "degiro", "date": ds, "time": "10:00", "name": name, "isin": isin, "qty": float(qty),
                       "price": px, "price_ccy": "EUR", "amount_eur": round(-(gross + ORDER_FEE), 2), "fees_eur": -ORDER_FEE,
                       "autofx_eur": 0.0, "corporate": False})
            cash -= gross + ORDER_FEE
            held[key] += qty
            if key == "blue":
                ttf = round(gross * TTF_RATE, 2)
                acct.append({"type": "fee", "kind": "ttf", "broker": "degiro", "date": ds, "name": "", "isin": "", "ccy": "EUR", "amount": -ttf})
                cash -= ttf
        if month.month == 1:
            acct.append({"type": "fee", "kind": "connexion", "broker": "degiro", "date": ds, "name": "", "isin": "", "ccy": "EUR", "amount": -CONNECTION_FEE})
            cash -= CONNECTION_FEE
        if month.month % 3 == 0 and held["blue"]:
            dd = _business_day(date(month.year, month.month, 15))
            if dd <= today:
                isin, name, _ = info["blue"]
                gross_div = round(held["blue"] * BLUE_DIVIDEND, 2)
                tax = round(gross_div * WITHHOLDING, 2)
                base = {"broker": "degiro", "date": dd.isoformat(), "name": name, "isin": isin, "ccy": "EUR"}
                acct += [{**base, "type": "dividend", "amount": gross_div}, {**base, "type": "dividend_tax", "amount": -tax}]
                cash += gross_div - tax

    records = {"degiro_transactions": tx, "degiro_account": acct,
               "degiro_portfolio": [{"type": "snapshot_cash", "broker": "degiro", "value_eur": round(cash, 2)}]}
    last = {sym: s[max(s)] for sym, s in series.items()}
    return records, series, last


def load(db):
    """Fill an empty database with the demo portfolio. Returns a short summary. Refuses to touch a database that has data."""
    if db.execute("SELECT 1 FROM records LIMIT 1").fetchone():
        raise SystemExit("Refusing to load demo data: this database already contains imported records.\n"
                         "Use a fresh directory (FOLIOLIB_DATA=/some/empty/dir python main.py demo) or erase the data from the page first.")
    records, series, last = build()
    for kind, name in (("degiro_transactions", "demo-transactions.csv"), ("degiro_account", "demo-account.csv"), ("degiro_portfolio", "demo-portfolio.csv")):
        store.add_file(db, name, kind, parsers.keyed(kind, records[kind]), None)
    for _, isin, _, sym, *_ in INSTRUMENTS:
        db.execute("INSERT OR REPLACE INTO instruments(isin,symbol,ccy,manual,tried) VALUES(?,?,?,1,0)", (isin, sym, "EUR"))
    now = int(time.time())
    for sym, s in series.items():
        db.executemany("INSERT OR REPLACE INTO prices(symbol,day,close) VALUES(?,?,?)", [(sym, d, v) for d, v in s.items()])
        db.execute("INSERT OR REPLACE INTO quote(symbol,price,ccy,at,source) VALUES(?,?,?,?,?)", (sym, last[sym], "EUR", now, "demo"))
    store.meta_set(db, "parser_version", str(parsers.PARSER_VERSION))   # otherwise store.migrate() would discard the demo files
    store.meta_set(db, "last_refresh", str(now))
    store.meta_set(db, "last_error", "")
    store.meta_set(db, "demo", "1")                                      # last: a half-loaded database must not look like a finished demo
    return {"orders": len(records["degiro_transactions"]), "account_lines": len(records["degiro_account"]), "instruments": len(INSTRUMENTS)}
