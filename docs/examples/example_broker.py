"""Example parser for a made-up broker, "Acme", whose CSV export looks like this:

    date,type,isin,name,quantity,price,amount
    2025-01-02,deposit,,,,,1000
    2025-01-03,buy,US0000000009,ACME CORP,10,50,
    2025-03-01,dividend,US0000000009,ACME CORP,,,4.5

This file is the worked example of CONTRIBUTING.md and is exercised by the test suite. To make it live, copy it to
`app/parsers/acme.py`: nothing else needs to change, the parser is discovered automatically.
"""
from .base import BaseParser, iso, rows


def num(text):
    """'12.5' -> 12.5; '' -> None. (parsers.fr_num is for French numbers, where the comma is the decimal separator.)"""
    return float(text) if text.strip() else None


class AcmeActivity(BaseParser):
    kind = "acme_activity"                     # unique name of this file type

    @classmethod
    def detect(cls, header):                   # `header` is the first line, lowercased
        return header.startswith("date,type,isin,name,quantity,price,amount")

    @classmethod
    def parse(cls, text):
        out, cash = [], 0.0                    # `cash` is rebuilt from the activity: this export has no balance column
        for r in rows(text, ",")[1:]:
            if len(r) < 7 or not r[0].strip():
                continue                       # blank or malformed line: skip it
            day, what, isin, name, qty, price, amount = (c.strip() for c in r[:7])
            base = {"broker": "acme", "date": iso(day, "%Y-%m-%d"), "isin": isin, "name": name, "ccy": "EUR"}
            if what in ("deposit", "withdrawal"):
                out.append({**base, "type": what, "amount": num(amount)})
                cash += num(amount) if what == "deposit" else -num(amount)
            elif what in ("buy", "sell"):
                sign = 1 if what == "buy" else -1
                out.append({**base, "type": "trade", "qty": sign * num(qty), "price": num(price), "price_ccy": "EUR",
                            "amount_eur": -sign * num(qty) * num(price)})     # cash moved: negative for a purchase
                cash -= sign * num(qty) * num(price)
            elif what == "dividend":
                out.append({**base, "type": "dividend", "amount": num(amount)})
                cash += num(amount)
        if out:                                # without the cash balance, money not yet invested would look like a loss
            out.append({"type": "snapshot_cash", "broker": "acme", "value_eur": round(cash, 2)})
        return out
