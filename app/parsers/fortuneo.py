"""Fortuneo exports: operations history (securities) and cash account.

Like the DEGIRO module, the patterns match the French-language exports and stay in French on purpose. Fortuneo's
securities export carries no ISIN: users map each label to an ISIN from the page (see `ledger.FORTUNEO_SEED`).
"""
import re

from .base import BaseParser, fr_num, iso, rows


class FortuneoOps(BaseParser):
    kind = "fortuneo_ops"

    @classmethod
    def detect(cls, header):
        return header.startswith("libell") and "op" in header and "prix d'" in header

    @classmethod
    def parse(cls, text):
        out = []
        for r in rows(text, ";")[1:]:
            if len(r) < 10 or not r[0].strip():
                continue
            out.append({"type": "f_op", "broker": "fortuneo", "name": r[0].strip(), "op": re.sub(r"\s+", " ", r[1]).strip(),
                        "date": iso(r[3], "%d/%m/%Y"), "qty": fr_num(r[4]), "price": fr_num(r[5]),
                        "gross": fr_num(r[6]), "fees": fr_num(r[7]), "net": fr_num(r[8]), "ccy": r[9].strip()})
        return out


class FortuneoCash(BaseParser):
    kind = "fortuneo_cash"

    @classmethod
    def detect(cls, header):
        return header.startswith("date op") and "bit" in header and "cr" in header

    @classmethod
    def parse(cls, text):
        out = []
        for r in rows(text, ";")[1:]:
            if len(r) < 5 or not r[0].strip():
                continue
            debit, credit = fr_num(r[3]), fr_num(r[4])
            out.append({"type": "f_cash", "broker": "fortuneo", "date": iso(r[0], "%d/%m/%Y"), "label": re.sub(r"\s+", " ", r[2]).strip().lower(),
                        "amount": (credit or 0.0) + (debit or 0.0)})
        return out
