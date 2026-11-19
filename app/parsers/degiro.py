"""DEGIRO exports: Transactions, Account (cash movements) and Portfolio (snapshot).

The header and description patterns below are matched against the **French-language** DEGIRO exports, so they stay in
French on purpose. Exports in another language have different headers and are not recognized yet.
"""
from .base import BaseParser, fr_num, iso, rows


class DegiroTransactions(BaseParser):
    kind = "degiro_transactions"

    @classmethod
    def detect(cls, header):
        return header.startswith("date,heure,produit,code isin,place")

    @classmethod
    def parse(cls, text):
        out = []
        for r in rows(text, ",")[1:]:
            if len(r) < 16 or not r[0].strip():
                continue
            qty = fr_num(r[6])
            out.append({
                "type": "trade", "broker": "degiro", "date": iso(r[0], "%d-%m-%Y"), "time": r[1],
                "name": r[2].strip(), "isin": r[3].strip(), "qty": qty,
                "price": fr_num(r[7]), "price_ccy": r[8].strip(),
                "amount_eur": fr_num(r[15]) if fr_num(r[15]) is not None else fr_num(r[11]),   # "traded amount": fees included
                "fees_eur": fr_num(r[14]) or 0.0, "autofx_eur": fr_num(r[13]) or 0.0,
                "corporate": not r[16].strip() if len(r) > 16 else True,   # no order ID: corporate action (split...)
            })
        return out


class DegiroAccount(BaseParser):
    kind = "degiro_account"

    @classmethod
    def detect(cls, header):
        return header.startswith("date,heure,date de,produit,code isin,description")

    @classmethod
    def parse(cls, text):
        out = []
        for r in rows(text, ",")[1:]:
            if len(r) < 10 or not r[0].strip():
                continue
            desc, amt, ccy = r[5].strip(), fr_num(r[8]), r[7].strip()
            base = {"broker": "degiro", "date": iso(r[0], "%d-%m-%Y"), "name": r[3].strip(), "isin": r[4].strip(), "ccy": ccy, "amount": amt}
            d = desc.lower()
            if amt is None:
                continue
            if d.startswith("dépôt flatex") or d.startswith("depot flatex"):
                out.append({**base, "type": "deposit"})
            elif d.startswith("retrait flatex") or d.startswith("flatex withdrawal"):
                out.append({**base, "type": "withdrawal"})      # the real withdrawal. "Processed Flatex Withdrawal" (a processing entry, reversed later) is ignored
            elif d.startswith("dividende"):
                out.append({**base, "type": "dividend"})
            elif d.startswith("impôts sur dividende") or d.startswith("impots sur dividende"):
                out.append({**base, "type": "dividend_tax"})
            elif d.startswith("frais de connexion"):
                out.append({**base, "type": "fee", "kind": "connexion"})
            elif d.startswith("frais degiro"):
                out.append({**base, "type": "fee", "kind": "courtage"})      # already in the orders (Transactions): only used for checking
            elif d.startswith("taxe sur les transactions"):
                out.append({**base, "type": "fee", "kind": "ttf"})
            elif "interest" in d:
                out.append({**base, "type": "interest"})
        return out


class DegiroPortfolio(BaseParser):
    kind = "degiro_portfolio"

    @classmethod
    def detect(cls, header):
        return header.startswith("produit,ticker/isin,quantit")

    @classmethod
    def parse(cls, text):
        out = []
        for r in rows(text, ",")[1:]:
            if len(r) < 7 or not r[0].strip():
                continue
            name, isin = r[0].strip(), r[1].strip()
            if name.upper().startswith("CASH"):
                out.append({"type": "snapshot_cash", "broker": "degiro", "value_eur": fr_num(r[6])})
            elif isin:
                out.append({"type": "snapshot", "broker": "degiro", "name": name, "isin": isin, "qty": fr_num(r[2]),
                            "price": fr_num(r[3]), "ccy": r[4].strip(), "value_eur": fr_num(r[6])})
        return out
