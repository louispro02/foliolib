"""Portfolio performance and risk, business day by business day.

Method:
- Time-weighted return (TWR): each day, r = (evening value + day's dividends) / (previous value + day's net purchases) - 1,
  then geometric chaining. Purchases and sales (fees included) are the flows: they count neither as gain nor as loss.
  Scope: the **securities** (cash is not in the curve). Dividends reinvested (net of withholding tax).
- Volatility: standard deviation of daily returns x square root of 252. Holidays (unchanged price) count as 0: volatility is
  slightly underestimated.
- Sharpe, Sortino: on **monthly** returns (x square root of 12), 3 % risk-free rate (assumption: a savings account).
  Lo (2002) standard error.
- Maximum drawdown: largest fall between a peak and the following trough of the TWR index (excluding the effect of deposits).
- 1-day 95 % VaR: parametric (1.645 x daily volatility x value) and historical (5th percentile).
"""
import math
from datetime import date, timedelta

RF = 0.03          # annual risk-free rate (assumption)
MIN_START = 500.0  # the index starts when securities reach 500 €: before that, 1 € of fees on 2 € invested would read -50 % forever
Z95 = 1.645
TRADING_DAYS = 252


def weekdays(start, end):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _mean(x):
    return sum(x) / len(x) if x else 0.0


def _sd(x):
    n = len(x)
    if n < 2:
        return 0.0
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def portfolio_days(ev, price_eur, invest, divs, brokers, end):
    """Business days with value, flows, dividends, return and TWR index (base 1) for the `brokers` accounts."""
    ev = [e for e in ev if e[1][0] in brokers]
    inv = sorted((d, a) for d, b, a in invest if b in brokers)
    dv = sorted((x[0], x[4]) for x in divs if x[1] in brokers)
    if not ev:
        return []
    start = date.fromisoformat(min(ev[0][0], inv[0][0] if inv else ev[0][0]))
    days = weekdays(start, end)
    qty, last_px, i, j, k = {}, {}, 0, 0, 0
    out, prev_v, idx = [], 0.0, 1.0
    for day in days:
        s = day.isoformat()
        while i < len(ev) and ev[i][0] <= s:
            qty[ev[i][1]] = qty.get(ev[i][1], 0.0) + ev[i][2]
            i += 1
        cf = 0.0
        while j < len(inv) and inv[j][0] <= s:
            cf += inv[j][1]
            j += 1
        dd = 0.0
        while k < len(dv) and dv[k][0] <= s:
            dd += dv[k][1]
            k += 1
        v, open_pos = 0.0, False
        for (b, isin), q in qty.items():
            if q <= 1e-9:
                continue
            open_pos = True
            px = price_eur(isin, s)
            if px is not None:
                last_px[isin] = px
            elif isin in last_px:
                px = last_px[isin]
            if px is not None:
                v += q * px
        base = prev_v + cf
        r = (v + dd) / base - 1 if base > 1e-6 else 0.0
        if open_pos and v <= 0 and base > 1e-6:      # no known price that day: missing data, not a total loss
            r = 0.0
        idx *= 1 + r
        out.append({"date": s, "v": v, "cf": cf, "div": dd, "r": r, "idx": idx})
        prev_v = v
    # the TWR index restarts at 1 the day the portfolio reaches MIN_START; the euro amounts (value, flows) cover the whole period
    first = next((i for i, d in enumerate(out) if d["v"] >= MIN_START), None)
    if first is None:
        return []
    idx = 1.0
    for n, d in enumerate(out):
        if n <= first:
            d["r"], d["idx"], d["start"] = 0.0, 1.0, n == first
        else:
            idx *= 1 + d["r"]
            d["idx"] = idx
    return out


def _streaks(vals, positive):
    best = cur = 0
    for v in vals:
        cur = cur + 1 if ((v > 0) if positive else (v < 0)) else 0
        best = max(best, cur)
    return best


def monthly_returns(days):
    """[(YYYY-MM, return, partial)] from the TWR index at each month end; the first month is partial."""
    if not days:
        return []
    out, prev, cur_m, last_idx, first = [], 1.0, days[0]["date"][:7], 1.0, True
    for d in days:
        m = d["date"][:7]
        if m != cur_m:
            out.append((cur_m, last_idx / prev - 1 if prev > 0 else 0.0, first))
            prev, first, cur_m = last_idx, False, m
        last_idx = d["idx"]
    out.append((cur_m, last_idx / prev - 1 if prev > 0 else 0.0, first))
    return out


def measured(days):
    """Days over which the indicators are measured: from the day the index starts."""
    i = next((n for n, d in enumerate(days) if d.get("start")), 0)
    return days[i:]


def metrics(days, idx_key="idx", value_end=None):
    """Indicators for a series of days (dicts with date, r, idx). None if fewer than 20 days."""
    days = measured(days)
    if len(days) < 20:
        return None
    rets = [d["r"] for d in days]
    idxs = [d[idx_key] for d in days]
    d0, d1 = date.fromisoformat(days[0]["date"]), date.fromisoformat(days[-1]["date"])
    years = max((d1 - d0).days, 1) / 365.25
    total = idxs[-1] - 1
    ann = (1 + total) ** (1 / years) - 1 if years >= 1 and total > -1 else None
    sd_d = _sd(rets)
    vol = sd_d * math.sqrt(TRADING_DAYS)
    m = monthly_returns(days)
    mr = [x[1] for x in m]
    ex = [x - RF / 12 for x in mr]
    sd_m = _sd(mr)
    sharpe_m = _mean(ex) / sd_m if sd_m > 0 else None
    n = len(mr)
    down = math.sqrt(_mean([min(0.0, x) ** 2 for x in ex])) if ex else 0.0
    # maximum drawdown (peak -> trough), time under water, maximum run-up (trough -> peak)
    peak, peak_d, mdd, mdd_peak, mdd_trough = idxs[0], days[0]["date"], 0.0, days[0]["date"], days[0]["date"]
    under_start, longest, longest_pair = None, 0, None
    trough, trough_d, mru, mru_t, mru_p = idxs[0], days[0]["date"], 0.0, days[0]["date"], days[0]["date"]
    for dday, ix in zip(days, idxs):
        if ix >= peak:
            if under_start is not None:
                span = (date.fromisoformat(dday["date"]) - date.fromisoformat(under_start)).days
                if span > longest:
                    longest, longest_pair = span, (under_start, dday["date"])
            peak, peak_d, under_start = ix, dday["date"], None
        else:
            if under_start is None:
                under_start = peak_d
            dd = ix / peak - 1
            if dd < mdd:
                mdd, mdd_peak, mdd_trough = dd, peak_d, dday["date"]
        if ix <= trough:
            trough, trough_d = ix, dday["date"]
        else:
            ru = ix / trough - 1
            if ru > mru:
                mru, mru_t, mru_p = ru, trough_d, dday["date"]
    if under_start is not None:
        span = (d1 - date.fromisoformat(under_start)).days
        if span > longest:
            longest, longest_pair = span, (under_start, None)
    recovered = None
    peak_val = next(x[idx_key] for x in days if x["date"] == mdd_peak)
    for dday, ix in zip(days, idxs):
        if dday["date"] > mdd_trough and ix >= peak_val:
            recovered = dday["date"]
            break
    srt = sorted(rets)
    hist_var = -srt[int(len(srt) * 0.05)] if len(srt) >= 100 else None
    best_d = max(days, key=lambda x: x["r"])
    worst_d = min(days, key=lambda x: x["r"])
    best_m, worst_m = (max(m, key=lambda x: x[1]), min(m, key=lambda x: x[1])) if m else (None, None)
    return {
        "start": days[0]["date"], "end": days[-1]["date"], "years": years,
        "twr_total": total, "twr_annual": ann, "volatility": vol, "vol_daily": sd_d,
        "sharpe": sharpe_m * math.sqrt(12) if sharpe_m is not None else None,
        "sharpe_se": math.sqrt((1 + (sharpe_m or 0) ** 2 / 2) / n) * math.sqrt(12) if sharpe_m is not None and n > 1 else None,
        "sortino": _mean(ex) / down * math.sqrt(12) if down > 0 else None, "months": n,
        "max_drawdown": mdd, "mdd_peak": mdd_peak, "mdd_trough": mdd_trough, "mdd_recovered": recovered,
        "underwater_days": longest, "underwater": longest_pair,
        "max_runup": mru, "runup_from": mru_t, "runup_to": mru_p,
        "var95_pct": Z95 * sd_d, "var95_hist_pct": hist_var,
        "best_day": (best_d["date"], best_d["r"]), "worst_day": (worst_d["date"], worst_d["r"]),
        "best_month": best_m[:2] if best_m else None, "worst_month": worst_m[:2] if worst_m else None,
        "positive_months": sum(1 for x in mr if x > 0) / n if n else None,
        "streak_up_months": _streaks(mr, True), "streak_down_months": _streaks(mr, False),
    }


def periods(days):
    """Absolute change and return over the usual periods: start and end value, flows, dividends, gain excluding flows."""
    if len(days) < 2:
        return []
    last = days[-1]
    last_year = date.fromisoformat(last["date"]).year
    ytd_i = next((i for i, x in enumerate(days) if x["date"][:4] == str(last_year)), len(days) - 1)
    ytd_i = max(ytd_i - 1, 0)
    marks = [("1 day", len(days) - 2), ("1 week", len(days) - 6), ("1 month", len(days) - 22), ("3 months", len(days) - 64),
             ("Year to date", ytd_i), ("1 year", len(days) - 253), ("Since inception", 0)]
    out = []
    for label, i in marks:
        if i < 0:
            continue
        a, seg = days[i], days[i + 1:]
        if label == "Since inception":
            a, seg = {"v": 0.0, "idx": 1.0, "date": days[0]["date"]}, days
            a = {**a, "idx": next((d["idx"] for d in days if d.get("start")), 1.0)}
        cf, dv = sum(x["cf"] for x in seg), sum(x["div"] for x in seg)
        out.append({"label": label, "from": a["date"], "v_start": a["v"], "v_end": last["v"], "flows": cf, "dividends": dv,
                    "change": last["v"] - a["v"], "gain": last["v"] - a["v"] - cf + dv, "twr": last["idx"] / a["idx"] - 1})
    return out


def from_prices(table, days_dates):
    """Days (date, r, idx) of a benchmark index on the same dates; table.at(day) = last price in euros."""
    out, prev, idx = [], None, 1.0
    for s in days_dates:
        p = table.at(s)
        if p is None:
            continue
        r = (p / prev - 1) if prev else 0.0
        idx *= 1 + r
        out.append({"date": s, "r": r, "idx": idx})
        prev = p
    return out
