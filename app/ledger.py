"""Calculation engine: replays the operations to obtain positions, average cost (PRU), deposits, dividends and returns.

Weighted-average cost method, brokerage fees and financial transaction tax included (as on the statements).
No network access here: prices and exchange rates come through the functions passed as arguments.
"""
from collections import defaultdict
from datetime import date as _date

# Display names of the brokers we know; any other broker is shown with its key, title-cased.
ACCOUNTS = {"degiro": "DEGIRO (brokerage)", "fortuneo": "Fortuneo (PEA)"}
SHORT_NAMES = {"degiro": "DEGIRO", "fortuneo": "Fortuneo PEA"}


def account_label(broker):
    """Full display name of a broker's account."""
    return ACCOUNTS.get(broker) or broker.replace("_", " ").title()


def account_short(broker):
    """Short name, for buttons and table cells."""
    return SHORT_NAMES.get(broker) or broker.replace("_", " ").title()

# Fortuneo labels (the export has no ISIN) -> ISIN. Users map them from the page; defaults can be added here.
FORTUNEO_SEED = {}


def _norm(label):
    return " ".join((label or "").lower().split())


class Position:
    __slots__ = ("broker", "isin", "name", "qty", "cost", "realized", "first", "last", "dividends", "buys", "unmapped")

    def __init__(self, broker, isin, name):
        self.broker, self.isin, self.name = broker, isin, name
        self.qty = 0.0
        self.cost = 0.0
        self.realized = 0.0
        self.first = None
        self.last = None
        self.dividends = 0.0
        self.buys = 0.0
        self.unmapped = False

    def buy(self, qty, cost, day):
        self.qty += qty
        self.cost += cost
        self.buys += cost
        self.first = self.first or day
        self.last = day

    def carry_out(self, qty, day):
        """Exit without a sale (split, exchange): the cost follows the shares, no gain or loss."""
        avg = self.cost / self.qty if self.qty else 0.0
        self.qty -= qty
        self.cost -= avg * qty
        self.last = day
        if abs(self.qty) < 1e-9:
            self.qty, self.cost = 0.0, 0.0
        return avg * qty

    def sell(self, qty, proceeds, day):
        """Remove qty (positive) at the average cost; returns the removed cost."""
        avg = self.cost / self.qty if self.qty else 0.0
        removed = avg * qty
        self.qty -= qty
        self.cost -= removed
        self.realized += proceeds - removed
        self.last = day
        if abs(self.qty) < 1e-9:
            self.qty, self.cost = 0.0, 0.0
        return removed


def _key(rec):
    return (rec["broker"], rec["isin"])


def build(records, aliases=None, fx=None):
    """records: parser records (all types mixed). aliases: normalized Fortuneo label -> ISIN.
    fx(ccy, 'YYYY-MM-DD') -> EUR for 1 unit of ccy, or None. Returns a results dict."""
    aliases = {**FORTUNEO_SEED, **{_norm(k): v for k, v in (aliases or {}).items()}}
    pos = {}
    flows = []          # (date, broker, EUR amount): deposits (+) and withdrawals (-) seen from the account
    divs = []           # net dividends: (date, broker, isin, name, EUR, converted?)
    fees = []           # fees outside the cost basis (exchange connection, taxes)
    cash = {}
    invest = []         # flows into securities: (date, account, amount); buy > 0, sell < 0, fees included
    costs = {"courtage": 0.0, "change": 0.0, "connexion": 0.0, "ttf": 0.0, "retenue": 0.0, "courtage_pea": 0.0}
    snapshots = []
    warnings = []

    def position(broker, isin, name):
        k = (broker, isin)
        if k not in pos:
            pos[k] = Position(broker, isin, name)
        if name and (not pos[k].name or len(name) > len(pos[k].name)):
            pos[k].name = name
        return pos[k]

    def to_eur(amount, ccy, day):
        if ccy in ("EUR", "", None):
            return amount, True
        rate = fx(ccy, day) if fx else None
        return (amount * rate, True) if rate else (amount, False)

    # ------------------------------------------------ securities accounts (DEGIRO, ...): orders, then corporate actions
    # Every record of the generic types (trade, deposit, withdrawal, dividend, dividend_tax, fee, snapshot_cash) belongs to
    # the broker it names, so a new broker's parser works without any change here.
    dg = sorted([r for r in records if r["type"] == "trade"], key=lambda r: (r["date"], r.get("time", "")))
    corp = defaultdict(list)
    for r in dg:
        if r.get("corporate"):
            corp[(r["broker"], r["date"], r["name"])].append(r)
            continue
        p = position(r["broker"], r["isin"], r["name"])
        invest.append((r["date"], r["broker"], -r["amount_eur"]))
        costs["courtage"] += abs(r.get("fees_eur", 0.0))
        costs["change"] += abs(r.get("autofx_eur", 0.0))
        if r["qty"] > 0:
            p.buy(r["qty"], -r["amount_eur"], r["date"])
        elif r["qty"] < 0:
            p.sell(-r["qty"], r["amount_eur"], r["date"])
    # split / reverse split: shares leave one line and enter the other with the same cost basis
    for (broker, day, name), legs in sorted(corp.items()):
        carried, ins = 0.0, [x for x in legs if x["qty"] > 0]
        for x in legs:
            if x["qty"] < 0:
                carried += position(broker, x["isin"], x["name"]).carry_out(-x["qty"], day)
        for x in ins:
            position(broker, x["isin"], x["name"]).buy(x["qty"], carried / len(ins) if ins else 0.0, day)

    for r in records:
        if r["type"] == "snapshot":
            snapshots.append(r)
        elif r["type"] == "snapshot_cash":
            cash[r["broker"]] = r["value_eur"]
        elif r["type"] in ("deposit", "withdrawal"):
            flows.append((r["date"], r["broker"], r["amount"] if r["type"] == "deposit" else -abs(r["amount"])))
        elif r["type"] in ("dividend", "dividend_tax"):
            eur, ok = to_eur(r["amount"], r["ccy"], r["date"])
            divs.append((r["date"], r["broker"], r["isin"], r["name"], eur, ok))
            if r["type"] == "dividend_tax":
                costs["retenue"] += -eur          # withholding tax: negative amount in the export, reversals count as positive
        elif r["type"] == "fee":
            eur, ok = to_eur(r["amount"], r["ccy"], r["date"])
            fees.append((r["date"], r["broker"], eur))
            if r.get("kind") in ("connexion", "ttf"):
                costs[r["kind"]] += -eur

    # ------------------------------------------------ Fortuneo: orders, coupons, share exchanges
    fo = sorted([r for r in records if r["type"] == "f_op"], key=lambda r: r["date"])
    mutations = defaultdict(list)
    for r in fo:
        label = _norm(r["name"])
        isin = aliases.get(label)
        p = position("fortuneo", isin or "?:" + label, r["name"])
        p.unmapped = isin is None
        op = r["op"].lower()
        if op.startswith("achat"):
            p.buy(r["qty"], -r["net"], r["date"])
            invest.append((r["date"], "fortuneo", -r["net"]))
            costs["courtage_pea"] += abs(r["fees"] or 0.0)
        elif op.startswith("vente"):
            p.sell(r["qty"], r["net"], r["date"])
            invest.append((r["date"], "fortuneo", -r["net"]))
            costs["courtage_pea"] += abs(r["fees"] or 0.0)
        elif op.startswith("taxe"):
            p.cost += -r["net"]
            p.buys += -r["net"]
            invest.append((r["date"], "fortuneo", -r["net"]))
            costs["ttf"] += -r["net"]
        elif op.startswith("encaissement"):
            divs.append((r["date"], "fortuneo", p.isin, r["name"], r["net"], True))
        elif op.startswith("ost de mutation"):
            mutations[(r["date"], label)].append(r)
    for (day, label), legs in sorted(mutations.items()):
        # automatic exchange: the statement gives two lines (quantity before, quantity after). The held quantity moves from the
        # one we actually have to the other, in both directions (reverse split 40 -> 4, split 4 -> 40). Cost basis unchanged.
        p = position("fortuneo", aliases.get(label) or "?:" + label, legs[0]["name"])
        qs = sorted(x["qty"] for x in legs)
        if len(qs) == 2 and abs(p.qty - qs[1]) < 1e-9:
            p.qty = qs[0]
        elif len(qs) == 2 and abs(p.qty - qs[0]) < 1e-9:
            p.qty = qs[1]
        else:
            warnings.append(f"Share exchange \"{legs[0]['name']}\" on {day} not applied (quantities {qs}, held {p.qty:g}): check the export.")

    for r in records:
        if r["type"] == "f_cash":
            cash["fortuneo"] = cash.get("fortuneo", 0.0) + r["amount"]
            if r["label"].startswith("versement") and r["amount"] > 0:
                flows.append((r["date"], "fortuneo", r["amount"]))

    # ------------------------------------------------ dividends attached to positions
    for d, broker, isin, name, eur, ok in divs:
        if (broker, isin) in pos:
            pos[(broker, isin)].dividends += eur
        else:
            for p in pos.values():
                if p.broker == broker and p.name and name and p.name.lower()[:12] == name.lower()[:12]:
                    p.dividends += eur
                    break

    return {"positions": pos, "flows": sorted(flows), "invest": sorted(invest), "costs": costs, "dividends": sorted(divs), "fees": sorted(fees), "cash": cash,
            "snapshots": snapshots, "warnings": warnings}


def holdings_on(pos_events, day):
    """Quantities on a date: not used as is, see timeline()."""
    raise NotImplementedError


def timeline(records, aliases=None):
    """Quantity held per (account, ISIN) over time: events (date, key, delta), expressed in **current shares of the security**.
    Yahoo prices are adjusted for splits and reverse splits; before a corporate action, old shares are therefore counted
    in today's unit (40 shares before a 10-for-1 reverse split are worth 4 shares)."""
    aliases = {**FORTUNEO_SEED, **{_norm(k): v for k, v in (aliases or {}).items()}}
    ev = []
    corp = defaultdict(list)
    dg_corp = defaultdict(list)
    for r in records:
        if r["type"] == "trade":
            ev.append((r["date"], (r["broker"], r["isin"]), r["qty"]))
            if r.get("corporate"):
                dg_corp[(r["broker"], r["date"], r["name"])].append(r)
        elif r["type"] == "f_op":
            isin = aliases.get(_norm(r["name"])) or "?:" + _norm(r["name"])
            op = r["op"].lower()
            if op.startswith("achat"):
                ev.append((r["date"], ("fortuneo", isin), r["qty"]))
            elif op.startswith("vente"):
                ev.append((r["date"], ("fortuneo", isin), -r["qty"]))
            elif op.startswith("ost de mutation"):
                corp[(r["date"], isin)].append(r["qty"])
    ev.sort(key=lambda e: e[0])
    # Securities accounts: one exit and one entry on the same day under the same name = split or reverse split
    for (broker, day, name), legs in sorted(dg_corp.items()):
        out_ = [x for x in legs if x["qty"] < 0]
        in_ = [x for x in legs if x["qty"] > 0]
        if len(out_) == 1 and len(in_) == 1 and out_[0]["isin"] != in_[0]["isin"]:
            f = in_[0]["qty"] / -out_[0]["qty"]
            old = (broker, out_[0]["isin"])
            ev = [(d, k, q * f if k == old else q) for d, k, q in ev]
    # Fortuneo: "automatic exchange", two lines (before, after), in both directions
    for (day, isin), qs in sorted(corp.items()):
        qs = sorted(qs)
        key = ("fortuneo", isin)
        held = sum(q for d, k, q in ev if k == key and d <= day)
        if len(qs) == 2 and (abs(held - qs[1]) < 1e-9 or abs(held - qs[0]) < 1e-9):
            before, after = (qs[1], qs[0]) if abs(held - qs[1]) < 1e-9 else (qs[0], qs[1])
            f = after / before
            ev = [(d, k, q * f if (k == key and d <= day) else q) for d, k, q in ev]
    return sorted(ev, key=lambda e: e[0])


def xirr(flows, end_value, end_date):
    """Annualized internal rate of return. flows: [(YYYY-MM-DD, amount paid in (+))]; end_value: final value. None if undefined."""
    pts = [(_date.fromisoformat(d), -a) for d, a in flows]
    pts.append((_date.fromisoformat(end_date), end_value))
    if len(pts) < 2 or not any(a < 0 for _, a in pts) or end_value <= 0:
        return None
    t0 = min(d for d, _ in pts)

    def npv(r):
        return sum(a / (1 + r) ** ((d - t0).days / 365.0) for d, a in pts)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2
