"""Price synchronization (refresh) and computation of everything the page displays (compute)."""
import bisect
import time
from datetime import date, timedelta

import ledger
import perf
import quotes
import store
from i18n import join_and, number
from i18n import t as tr      # `t` is a common local name in this module (a table, a date): do not shadow the function

# Benchmarks: **accumulating** ETFs listed in euros (dividends reinvested, ETF fees deducted), the only fair way to compare
# them with a portfolio that reinvests. Checked on Yahoo on 2026-11-17: daily prices since 2023 at least.
BENCHMARKS = [
    ("world", "MSCI World", "IWDA.AS", "iShares Core MSCI World (accumulating)"),
    ("sp500", "S&P 500", "SXR8.DE", "iShares Core S&P 500 (accumulating)"),
    ("nasdaq", "Nasdaq-100", "SXRV.DE", "iShares Nasdaq 100 (accumulating)"),
    ("em", "Emerging Markets", "IS3N.DE", "iShares Core MSCI EM IMI (accumulating)"),
    ("eu600", "STOXX Europe 600", "XSX6.DE", "Xtrackers STOXX Europe 600 1C (accumulating)"),
    ("cac", "CAC 40", "CACC.PA", "Amundi CAC 40 (accumulating)"),
]
BENCH_SYMBOL = "IWDA.AS"     # reference for the main curve
STALE_AFTER = 300            # a price under 5 minutes old is not requested again
RETRY_UNRESOLVED = 6 * 3600  # an ISIN without a symbol is looked up at most once every 6 h


def _twelve_key(data_dir):
    try:
        k = (data_dir / "twelvedata.key").read_text().strip()
        return k or None
    except OSError:
        return None


def _snapshots(records):
    return {r["isin"]: r for r in records if r["type"] == "snapshot"}


def _all_isins(records, aliases):
    """Useful ISINs: held positions first, then closed ones (for the past curve)."""
    res = ledger.build(records, aliases)
    held = [p.isin for p in res["positions"].values() if p.qty > 0 and not p.isin.startswith("?:")]
    gone = [p.isin for p in res["positions"].values() if p.qty == 0 and not p.isin.startswith("?:")]
    out = []
    for i in held + gone:
        if i not in out:
            out.append(i)
    return out


def refresh(db, data_dir, progress=None):
    """Update prices, histories and rates. Stops at the first refusal from the service. Returns the list of notes."""
    if store.meta_get(db, "demo"):      # synthetic prices: never replaced by real ones
        return []
    notes = []
    say = progress or (lambda *_: None)
    records = store.all_records(db)
    snaps = _snapshots(records)
    isins = _all_isins(records, store.aliases(db))
    tkey = _twelve_key(data_dir)
    now = int(time.time())
    dates = [r["date"] for r in records if r.get("date")]
    first = (date.fromisoformat(min(dates)) - timedelta(days=14)).isoformat() if dates else (date.today() - timedelta(days=365)).isoformat()
    try:
        for n, isin in enumerate(isins, 1):
            say("Prices {n}/{total}", {"n": n, "total": len(isins)})
            row = db.execute("SELECT symbol, ccy, manual, tried FROM instruments WHERE isin=?", (isin,)).fetchone()
            symbol = row[0] if row else None
            if not symbol:
                if row and now - row[3] < RETRY_UNRESOLVED:
                    continue
                snap = snaps.get(isin, {})
                sym, c = quotes.resolve(isin, snap.get("ccy"), snap.get("price"))
                db.execute("INSERT INTO instruments(isin,symbol,ccy,tried) VALUES(?,?,?,?) ON CONFLICT(isin) DO UPDATE SET symbol=?, ccy=?, tried=?",
                           (isin, sym, c["ccy"] if c else None, now, sym, c["ccy"] if c else None, now))
                db.commit()
                symbol = sym
                if not symbol:
                    notes.append(f"{isin}: no symbol found")
                    continue
            _refresh_symbol(db, symbol, tkey, now, first)
        for i, (_, label, sym, _) in enumerate(BENCHMARKS, 1):
            say("Benchmarks {n}/{total}", {"n": i, "total": len(BENCHMARKS)})
            _refresh_symbol(db, sym, tkey, now, first)
        say("Exchange rates", {})
        _refresh_fx(db, records)
        store.meta_set(db, "last_refresh", str(now))
        store.meta_set(db, "last_error", "")
    except quotes.Refused as e:
        store.meta_set(db, "last_error", str(e))
        notes.append(str(e))
    return notes


def _refresh_symbol(db, symbol, tkey, now, first):
    q = db.execute("SELECT at FROM quote WHERE symbol=?", (symbol,)).fetchone()
    if q and now - q[0] < STALE_AFTER:
        return
    # full daily history since the first operation, once; afterwards only the last month
    have = store.meta_get(db, "daily_from:" + symbol)
    full = not have or have > first
    c = quotes.yahoo_chart(symbol, start=first) if full else quotes.yahoo_chart(symbol, "1mo")
    src = "yahoo"
    if not c and tkey:
        c, src = quotes.twelvedata_close(symbol.split(".")[0], tkey), "twelvedata"
    if not c:
        return
    if full and src == "yahoo":
        db.execute("DELETE FROM prices WHERE symbol=?", (symbol,))      # discards old monthly points
        store.meta_set(db, "daily_from:" + symbol, first)
    db.executemany("INSERT OR REPLACE INTO prices(symbol,day,close) VALUES(?,?,?)", [(symbol, d, v) for d, v in c["closes"].items()])
    db.execute("INSERT OR REPLACE INTO quote(symbol,price,ccy,at,source) VALUES(?,?,?,?,?)", (symbol, c["price"], c["ccy"], now, src))
    db.commit()


def _refresh_fx(db, records):
    ccys = {r.get("ccy") for r in records if r.get("ccy") and r["type"] in ("dividend", "dividend_tax", "fee")}
    ccys |= {c for (c,) in db.execute("SELECT DISTINCT ccy FROM quote WHERE ccy IS NOT NULL")}
    ccys.discard("EUR")
    ccys.discard("")
    ccys.discard(None)
    first = min([r["date"] for r in records if r.get("date")] or [date.today().isoformat()])
    for ccy in sorted(ccys):
        last = db.execute("SELECT MAX(day) FROM fx WHERE ccy=?", (ccy,)).fetchone()[0]
        start = (date.fromisoformat(last) - timedelta(days=5)).isoformat() if last else first
        rates = quotes.ecb_rates(ccy, start, date.today().isoformat())
        db.executemany("INSERT OR REPLACE INTO fx(ccy,day,rate) VALUES(?,?,?)", [(ccy, d, r) for d, r in rates.items()])
        db.commit()


# ---------------------------------------------------------------- computation
class Table:
    """Dated series with a "last known value at this date" lookup."""

    def __init__(self, rows):
        rows = sorted(rows)
        self.days = [d for d, _ in rows]
        self.vals = [v for _, v in rows]

    def at(self, day, strict=False):
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0 and strict:
            return None
        return self.vals[i] if i >= 0 else (self.vals[0] if self.vals else None)

    def __bool__(self):
        return bool(self.days)


def qccy_of(quote, sym):
    q = quote.get(sym)
    return q[1] if q else "EUR"


def _spark(table, fx, ccy, n=60):
    """Latest closes in euros (at today's rate), at most n points: for each line's small curve."""
    if not table or not table.days:
        return []
    rate = fx(ccy, date.today().isoformat()) or 1.0
    vals = [round(v * rate, 4) for v in table.vals[-90:]]
    step = max(1, len(vals) // n)
    return vals[::step][-n:]


SAVINGS_RATE = 0.03       # assumption: a savings account at 3 % a year, to measure the "cost of doing nothing"
PEA_CAP = 150_000         # PEA deposit ceiling


def _compare(flows, today, tables, total_value, lang="en"):
    """Same deposit schedule placed in each benchmark index or in a savings account: value, gap, annualized return."""
    if not flows:
        return None
    t = date.fromisoformat(today)
    invested = sum(a for _, a in flows)
    fl = [(d, a) for d, a in flows]
    rows = []
    for key, label, sym, desc in BENCHMARKS:
        tb = tables.get(sym)
        if not tb:
            continue
        units = sum(a / tb.at(d) for d, a in flows if tb.at(d))
        val = units * tb.at(today)
        rows.append({"key": key, "label": tr(lang, label), "desc": tr(lang, desc), "value": val, "irr": ledger.xirr(fl, val, today), "diff": total_value - val})
    livret = sum(a * (1 + SAVINGS_RATE) ** ((t - date.fromisoformat(d)).days / 365.0) for d, a in flows)
    return {"invested": invested, "portfolio": total_value, "irr_portfolio": ledger.xirr(fl, total_value, today),
            "benchmarks": rows, "livret": livret, "irr_livret": SAVINGS_RATE, "alpha_livret": total_value - livret}


def _performance(records, alias, closes, fx, inst, res, today, lang="en"):
    """TWR, risk, monthly returns, absolute change and base-100 curves, for all accounts then each one."""
    ev = ledger.timeline(records, alias)

    def price_eur(isin, s):
        sym, ccy = inst.get(isin, (None, None))
        t = closes.get(sym) if sym else None
        px = t.at(s, strict=True) if t else None
        if px is None:
            return None
        return px * (fx(ccy or "EUR", s) or 1.0)

    out, end = {}, date.fromisoformat(today)
    present = sorted({b for b, _ in res["positions"]})
    for key, brokers in (("all", set(present)), *((b, {b}) for b in present)):
        days = perf.portfolio_days(ev, price_eur, res["invest"], res["dividends"], brokers, end)
        m = perf.metrics(days)
        if not m:
            continue
        stamps = [d["date"] for d in perf.measured(days)]
        bench, curves = [], {}
        for bkey, label, sym, desc in BENCHMARKS:
            tb = closes.get(sym)
            bd = perf.from_prices(tb, stamps) if tb else []
            bm = perf.metrics(bd) if bd else None
            if bm:
                bench.append({"key": bkey, "label": tr(lang, label), "desc": tr(lang, desc), "m": _round_m(bm)})
                curves[bkey] = {d["date"]: d["idx"] for d in bd}
        md = perf.measured(days)
        step = 1 if len(md) < 700 else 2
        keep = [i for i in range(len(md)) if i % step == 0 or i == len(md) - 1]
        out[key] = {
            "m": _round_m(m), "bench": bench, "periods": [{**p, "label": tr(lang, p["label"])} for p in perf.periods(days)],
            "monthly": [[a, round(b, 5), c] for a, b, c in perf.monthly_returns(perf.measured(days))],
            "value_end": days[-1]["v"],
            "curve": {"days": [stamps[i] for i in keep], "portfolio": [round(md[i]["idx"] * 100, 2) for i in keep],
                      "bench": {k: [round(c.get(stamps[i], c.get(stamps[max(0, i - 1)], 1.0)) * 100, 2) for i in keep] for k, c in curves.items()}},
        }
    return out


def _round_m(m):
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in m.items()}


TAX_RATE_CTO = 0.30        # assumption: flat tax (30 %), to estimate the latent tax on the brokerage account


def _costs(res, pos, flows, kpi_gain, total_unreal, total_real, div_total, lang="en"):
    c = res["costs"]
    first = date.fromisoformat(flows[0][0]) if flows else date.today()
    years = max((date.today() - first).days / 365.25, 0.1)
    invested = sum(a for _, _, a in flows) or 1.0
    fees = [("Brokerage fees", c["courtage"]), ("Brokerage fees (PEA)", c["courtage_pea"]),
            ("Currency conversion fees", c["change"]), ("Exchange connection fees", c["connexion"])]
    taxes = [("Financial transaction tax", c["ttf"]), ("Withholding tax on foreign dividends", c["retenue"])]
    tf, tt = sum(v for _, v in fees), sum(v for _, v in taxes)
    cto_gain = sum(p["gain"] for p in pos if p["broker"] != "fortuneo")      # every account but the PEA (taxed differently)
    other = kpi_gain - (total_unreal + total_real + div_total)
    return {
        "fees": [{"label": tr(lang, a), "eur": round(b, 2)} for a, b in fees], "taxes": [{"label": tr(lang, a), "eur": round(b, 2)} for a, b in taxes],
        "total_fees": round(tf, 2), "total_taxes": round(tt, 2), "pct_invested": (tf + tt) / invested, "per_year_pct": (tf + tt) / invested / years,
        "tax_estimate": {"rate": TAX_RATE_CTO, "base": cto_gain, "amount": max(0.0, cto_gain) * TAX_RATE_CTO},
        "bridge": {"gain": kpi_gain, "unrealized": total_unreal, "realized": total_real, "dividends": div_total, "other": other},
    }


def _watch(pos, kpi, accounts_flows, lang="en"):
    """Facts to keep an eye on, computed from the numbers (never buy or sell advice)."""
    out = []
    if pos:
        top = max(pos, key=lambda p: p["weight"])
        if top["weight"] > 0.30:
            out.append({"kind": "concentration", "text": tr(lang, "{name} is {pct} % of your securities.", name=top["name"], pct=number(lang, top["weight"] * 100, 1))})
    micro = [p for p in pos if p["weight"] < 0.005]
    if len(micro) >= 2:
        out.append({"kind": "micro", "text": tr(lang, "{count} holdings under 0.5 % of the portfolio ({total} € in total): {names}.", count=len(micro),
                                              total=number(lang, sum(p["value"] for p in micro), 0), names=", ".join(p["name"].title() for p in micro[:4]))})
    for p in pos:
        if p["gain_pct"] is not None and p["gain_pct"] < -0.30 and p["value"] > 50:
            out.append({"kind": "loss", "text": tr(lang, "{name}: {pct} % ({gain} €) versus cost basis.", name=p["name"].title(),
                                                  pct=number(lang, p["gain_pct"] * 100, 0), gain=number(lang, p["gain"], 0, signed=True))})
    if kpi["cash"] and kpi["value"] and kpi["cash"] / kpi["value"] > 0.05:
        out.append({"kind": "cash", "text": tr(lang, "Cash: {pct} % of the total.", pct=number(lang, kpi["cash"] / kpi["value"] * 100, 1))})
    return out


def _category(name):
    n = name.lower()
    return "ETF" if ("etf" in n or "ucits" in n) else "Stock"


def compute(db, data_dir, lang="en"):
    records = store.all_records(db)
    alias = store.aliases(db)
    today = date.today().isoformat()
    fxt = {}
    for ccy in {c for (c,) in db.execute("SELECT DISTINCT ccy FROM fx")}:
        fxt[ccy] = Table(db.execute("SELECT day, rate FROM fx WHERE ccy=?", (ccy,)).fetchall())

    def fx(ccy, day):
        if ccy in ("EUR", "", None):
            return 1.0
        t = fxt.get(ccy)
        r = t.at(day) if t else None
        return 1.0 / r if r else None

    res = ledger.build(records, alias, fx)
    snaps = _snapshots(records)
    inst = {isin: (sym, ccy) for isin, sym, ccy in db.execute("SELECT isin, symbol, ccy FROM instruments")}
    closes, quote = {}, {}
    for sym in {s for s, _ in inst.values() if s} | {b[2] for b in BENCHMARKS}:
        closes[sym] = Table(db.execute("SELECT day, close FROM prices WHERE symbol=?", (sym,)).fetchall())
        q = db.execute("SELECT price, ccy, at, source FROM quote WHERE symbol=?", (sym,)).fetchone()
        if q:
            quote[sym] = q

    out_pos, warnings = [], [tr(lang, template, **params) for template, params in res["warnings"]]
    if store.meta_get(db, "demo"):
        warnings.insert(0, tr(lang, "Demo mode: every operation and price on this page is synthetic."))
    pending = [k for k in store.meta_get(db, "reimport").split(",") if k and not db.execute("SELECT 1 FROM files WHERE kind=?", (k,)).fetchone()]
    if pending:
        warnings.append(tr(lang, "The parser was fixed: re-upload {files} (DEGIRO) for the figures to be correct.",
                          files=join_and(lang, [{"degiro_transactions": "Transactions.csv", "degiro_account": "Account.csv"}.get(k, k) for k in pending])))
    total_mv = 0.0
    for (broker, isin), p in res["positions"].items():
        if p.qty <= 0:
            continue
        sym, ccy = inst.get(isin, (None, None))
        snap = snaps.get(isin)
        price_eur, source, age, prev = None, None, None, None
        if sym and sym in quote:
            price, qccy, at, src = quote[sym]
            rate = fx(qccy, today)
            if rate:
                price_eur, source, age = price * rate, src, int(time.time()) - at
                t = closes[sym]
                before = [(d, v) for d, v in zip(t.days, t.vals) if d < today]
                if before:
                    prev = before[-1][1] * rate
        if price_eur is None and snap and snap.get("price") is not None:
            rate = fx(snap.get("ccy"), today) or 1.0
            price_eur, source = snap["price"] * rate, "export"
        if price_eur is None:
            price_eur, source = (p.cost / p.qty if p.qty else 0.0), "cost basis"
            warnings.append(tr(lang, "{name}: no price, valued at cost basis.", name=p.name))
        mv = price_eur * p.qty
        total_mv += mv
        out_pos.append({
            "broker": broker, "account": ledger.account_label(broker, lang), "account_short": ledger.account_short(broker, lang), "isin": isin, "name": p.name, "category": tr(lang, _category(p.name)),
            "symbol": sym, "ccy": ccy or (snap or {}).get("ccy") or "EUR", "qty": p.qty, "cost": p.cost, "pru": p.cost / p.qty,
            "price": price_eur, "value": mv, "gain": mv - p.cost, "gain_pct": (mv / p.cost - 1) if p.cost else None,
            "day_pct": (price_eur / prev - 1) if prev else None, "day_eur": (price_eur - prev) * p.qty if prev else None,
            "dividends": p.dividends, "first": p.first, "source": source, "age": age,
            "spark": _spark(closes.get(sym), fx, qccy_of(quote, sym)) if sym else [],
        })
        if p.unmapped:
            warnings.append(tr(lang, "\"{name}\" (Fortuneo) has no ISIN: map it below.", name=p.name))
    for r in out_pos:
        r["weight"] = r["value"] / total_mv if total_mv else 0.0
    out_pos.sort(key=lambda r: -r["value"])

    brokers = sorted({b for b, _ in res["positions"]} | {b for _, b, _ in res["flows"]} | set(res["cash"]))
    cash = {b: res["cash"].get(b, 0.0) for b in brokers}
    flows = res["flows"]
    total_flows = [(d, a) for d, _, a in flows]
    invested = sum(a for _, a in total_flows)
    total_value = total_mv + sum(cash.values())

    def per_broker(b):
        fl = [(d, a) for d, bb, a in flows if bb == b]
        val = sum(r["value"] for r in out_pos if r["broker"] == b) + cash[b]
        inv = sum(a for _, a in fl)
        return {"key": b, "account": ledger.account_label(b, lang), "short": ledger.account_short(b, lang), "value": val, "invested": inv, "gain": val - inv,
                "gain_pct": (val / inv - 1) if inv else None, "irr": ledger.xirr(fl, val, today), "cash": cash[b],
                "securities": val - cash[b]}

    divs = res["dividends"]
    since = (date.today() - timedelta(days=365)).isoformat()
    div_total = sum(e for *_, e, _ in divs)
    div_12m = sum(e for d, *_, e, _ in divs if d >= since)
    by_month = {}
    for d, b, isin, name, e, ok in divs:
        by_month[d[:7]] = by_month.get(d[:7], 0.0) + e
    unconv = sum(1 for *_, ok in divs if not ok)
    if unconv:
        warnings.append(tr(lang, "{count} dividend(s) in a foreign currency without an exchange rate: counted at face value until rates are loaded.", count=unconv))

    series = _series(records, alias, closes, fx, inst, flows, today)
    try:
        performance = _performance(records, alias, closes, fx, inst, res, today, lang)
    except Exception as exc:                      # an indicator calculation must never prevent displaying the rest
        performance = {}
        warnings.append(tr(lang, "Performance indicators unavailable: {error}", error=type(exc).__name__))
    costs = _costs(res, out_pos, flows, kpi_gain=total_value - invested, total_unreal=sum(r["gain"] for r in out_pos),
                   total_real=sum(p.realized for p in res["positions"].values()), div_total=div_total, lang=lang)
    compare = _compare([(d, a) for d, _, a in flows], today, closes, total_value, lang)
    pea_in = [(d, a) for d, b, a in flows if b == "fortuneo"]
    pea_net = sum(a for _, a in pea_in)
    envelopes = ({"pea": {"invested": pea_net, "cap": PEA_CAP, "pct": pea_net / PEA_CAP, "opened": pea_in[0][0],
                          "five_years": pea_in[0][0].replace(pea_in[0][0][:4], str(int(pea_in[0][0][:4]) + 5), 1)}} if pea_in else {})
    last = int(store.meta_get(db, "last_refresh", "0") or 0)
    last_error = store.meta_get(db, "last_error")
    realized = sum(p.realized for p in res["positions"].values())
    unreal = sum(r["gain"] for r in out_pos)
    return {
        "as_of": today, "last_refresh": last, "last_error": tr(lang, "{error}: keeping the last known prices", error=last_error) if last_error else "",
        "kpi": {"value": total_value, "securities": total_mv, "cash": sum(cash.values()), "invested": invested,
                "gain": total_value - invested, "gain_pct": (total_value / invested - 1) if invested else None,
                "irr": ledger.xirr(total_flows, total_value, today), "unrealized": unreal, "realized": realized,
                "dividends": div_total, "dividends_12m": div_12m,
                "day_eur": sum(r["day_eur"] or 0.0 for r in out_pos), "cost": sum(r["cost"] for r in out_pos)},
        "accounts": [per_broker(b) for b in brokers if any(bb == b for _, bb, _ in flows) or cash[b]],
        "positions": out_pos, "series": series, "perf": performance, "costs": costs, "compare": compare, "envelopes": envelopes,
        "watch": _watch(out_pos, {"cash": sum(cash.values()), "value": total_value}, flows, lang), "dividend_months": sorted(by_month.items()),
        "dividend_list": [{"date": d, "account": ledger.account_label(b, lang), "name": n, "eur": e} for d, b, _, n, e, _ in divs][-40:][::-1],
        "flows": [{"date": d, "account": ledger.account_label(b, lang), "eur": a} for d, b, a in flows][-40:][::-1],
        "files": [{"name": n, "kind": k, "n": c, "new": nw, "at": at} for n, k, c, nw, at in
                  db.execute("SELECT name, kind, n, new, added FROM files ORDER BY id DESC LIMIT 30")],
        "unmapped": sorted({p.name for p in res["positions"].values() if p.unmapped}),
        "warnings": warnings[:20],
        "empty": not records,
    }


def _series(records, alias, closes, fx, inst, flows, today):
    ev = ledger.timeline(records, alias)
    if not ev:
        return {"days": []}
    start = min(ev[0][0], flows[0][0] if flows else ev[0][0])
    d0, d1 = date.fromisoformat(start), date.fromisoformat(today)
    step = 1 if (d1 - d0).days <= 400 else 3        # beyond a year, one point out of three is enough to the eye
    qty, i = {}, 0
    brokers = sorted({k[0] for _, k, _ in ev} | {b for _, b, _ in flows})
    days, val, dep, brk = [], [], [], {b: [] for b in brokers}
    depb = {b: [] for b in brokers}
    cumb = {b: 0.0 for b in brokers}
    fl, fi, cum = flows, 0, 0.0
    b_units = {k: 0.0 for k, *_ in BENCHMARKS}
    bts = {k: closes.get(sym) for k, _, sym, _ in BENCHMARKS}
    bench_all = {k: [] for k, *_ in BENCHMARKS}
    day = d0
    while day <= d1:
        s = day.isoformat()
        while i < len(ev) and ev[i][0] <= s:
            qty[ev[i][1]] = qty.get(ev[i][1], 0.0) + ev[i][2]
            i += 1
        while fi < len(fl) and fl[fi][0] <= s:
            cum += fl[fi][2]
            cumb[fl[fi][1]] += fl[fi][2]
            for k, tb in bts.items():
                if tb and tb.at(fl[fi][0]):
                    b_units[k] += fl[fi][2] / tb.at(fl[fi][0])
            fi += 1
        if (day - d0).days % step == 0 or day == d1:
            tot, per = 0.0, {b: 0.0 for b in brokers}
            for (b, isin), q in qty.items():
                if q <= 1e-9:
                    continue
                sym, _ = inst.get(isin, (None, None))
                t = closes.get(sym) if sym else None
                px = t.at(s) if t else None
                if px is None:
                    continue
                rate = fx(inst.get(isin, (None, None))[1] or "EUR", s) or 1.0
                v = q * px * rate
                tot += v
                per[b] += v
            days.append(s)
            val.append(round(tot, 2))
            dep.append(round(cum, 2))
            for k, tb in bts.items():
                bench_all[k].append(round(b_units[k] * tb.at(s), 2) if tb and tb.at(s) else None)
            for b in per:
                brk[b].append(round(per[b], 2))
                depb[b].append(round(cumb[b], 2))
        day += timedelta(days=1)
    return {"days": days, "value": val, "deposits": dep, "benchmarks": bench_all, "by_account": brk, "deposits_by_account": depb}
