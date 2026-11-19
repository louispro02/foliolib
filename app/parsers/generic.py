"""FolioLib generic CSV: one documented format that data from ANY broker can be converted into.

Use it when your broker has no dedicated parser yet, or only offers PDFs: fill the file by hand, from a spreadsheet, or with a
small conversion script. The full specification, with examples, is in `docs/generic-csv.md`.

One row per event. The header line is fixed (see HEADER); columns may come in any order and extra columns are ignored.
Numbers use a dot as the decimal separator and no thousands separator, except in a semicolon-separated file (what a French
spreadsheet produces), where a decimal comma is accepted. Dates are `YYYY-MM-DD`.
"""
import math
import re
from datetime import datetime

from i18n import Msg, RowErrors

from .base import BaseParser, rows

REQUIRED = ("date", "type", "account", "isin", "name", "quantity", "price", "amount", "currency", "fees")
HEADER = ",".join(REQUIRED + ("note",))        # the line to copy at the top of a file
TYPES = ("deposit", "withdrawal", "buy", "sell", "dividend", "dividend_tax", "fee", "transaction_tax",
         "cash_balance", "exchange_out", "exchange_in")
DEFAULT_ACCOUNT = "portfolio"                  # used when the `account` column is empty
MAX_ERRORS = 5                                 # report at most this many bad rows at once


def _delimiter(line):
    return ";" if line.count(";") > line.count(",") else ","


def _columns(line):
    return [c.strip().lower() for c in rows(line, _delimiter(line))[0]] if line.strip() else []


def _number(text, field, decimal_comma):
    s = text.replace("\xa0", "").replace(" ", "")
    if decimal_comma:
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        if decimal_comma:
            raise Msg("{field} {value} is not a number", field=field, value=repr(text)) from None
        raise Msg("{field} {value} is not a number (use a dot as the decimal separator and no thousands separator)",
                  field=field, value=repr(text)) from None
    if not math.isfinite(value):
        raise Msg("{field} {value} is not a number", field=field, value=repr(text))
    return value


def _date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise Msg("date {value} must be written YYYY-MM-DD", value=repr(text)) from None


def _account(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or DEFAULT_ACCOUNT


def day_of_last(records, broker):
    """Date of the account's last record: the date a rebuilt cash balance refers to."""
    return max((r["date"] for r in records if r["broker"] == broker and r.get("date")), default="")


class GenericCsv(BaseParser):
    kind = "foliolib_csv"

    @classmethod
    def detect(cls, header):
        return set(REQUIRED) <= set(_columns(header))

    @classmethod
    def parse(cls, text):
        lines = text.lstrip("﻿").splitlines()
        delim = _delimiter(lines[0])
        comma = delim == ";"
        table = rows(text.lstrip("﻿"), delim)
        index = {c.strip().lower(): i for i, c in enumerate(table[0])}
        out, errors = [], []
        cash, balances = {}, {}                   # cash rebuilt from the activity, and the balances the file states itself
        for n, r in enumerate(table[1:], start=2):
            if not any(c.strip() for c in r):
                continue

            def cell(name, r=r):
                i = index.get(name)
                return r[i].strip() if i is not None and i < len(r) else ""

            try:
                recs, delta = cls._row(cell, comma)
            except Msg as e:
                errors.append((n, e))
                continue
            rec = recs[0]
            if rec["type"] == "snapshot_cash":
                if rec["broker"] not in balances or rec["date"] >= balances[rec["broker"]]["date"]:
                    balances[rec["broker"]] = rec     # several balances in one file: the most recent date wins
                continue
            out += recs
            if delta is not None:
                cash[rec["broker"]] = cash.get(rec["broker"], 0.0) + delta
        if errors:
            raise RowErrors(errors, MAX_ERRORS)
        # Without a stated balance, rebuild the cash from the activity: it is only right if the file holds the account's whole
        # history. A negative result means deposits are missing, so no balance is better than a wrong one.
        out += [balances[b] for b in sorted(balances)]
        for broker in sorted(set(cash) - set(balances)):
            if cash[broker] >= 0:
                out.append({"type": "snapshot_cash", "broker": broker, "date": day_of_last(out, broker), "value_eur": round(cash[broker], 2)})
        return out

    @staticmethod
    def _row(cell, comma):
        """One CSV row -> (records, change of the account's cash in euros, or None if it is not rebuildable)."""
        what = cell("type").lower().replace(" ", "_").replace("-", "_")
        if what not in TYPES:
            raise Msg("unknown type {value} (expected one of: {types})", value=repr(cell("type")), types=", ".join(TYPES))
        broker, day = _account(cell("account")), _date(cell("date"))
        isin, name, ccy = cell("isin").upper(), cell("name"), (cell("currency") or "EUR").upper()
        if not re.fullmatch(r"[A-Z]{3}", ccy):
            raise Msg("currency {value} is not a 3-letter code: a number written with a comma was probably split in two columns "
                      "(use a dot as the decimal separator, or put the number in quotes)", value=repr(cell("currency")))

        def num(field, required=True):
            raw = cell(field)
            if not raw:
                if required:
                    raise Msg("{field} is required for a {what}", field=field, what=what)
                return None
            return _number(raw, field, comma)

        def need_isin():
            if len(isin) != 12 or not isin.isalnum():
                raise Msg("isin {value} must be 12 letters or digits (required for a {what})", value=repr(cell("isin")), what=what)

        def need_euro():
            if ccy != "EUR":
                raise Msg("a {what} must be in euros: convert it first (currency is {currency})", what=what, currency=ccy)

        base = {"broker": broker, "date": day, "isin": isin, "name": name, "ccy": ccy}
        if what in ("deposit", "withdrawal"):
            need_euro()
            amount = abs(num("amount"))
            return [{**base, "type": what, "amount": amount}], amount if what == "deposit" else -amount
        if what == "cash_balance":
            need_euro()
            return [{"type": "snapshot_cash", "broker": broker, "date": day, "value_eur": num("amount")}], None
        if what in ("buy", "sell"):
            need_isin()
            need_euro()
            qty, fees = abs(num("quantity")), abs(num("fees", required=False) or 0.0)
            if qty <= 0:
                raise Msg("quantity must be greater than zero")
            price = num("price", required=False)
            gross = abs(num("amount")) if cell("amount") else qty * (price or 0.0)
            if not gross:
                raise Msg("a {what} needs an amount, or a price and a quantity", what=what)
            sign = 1 if what == "buy" else -1
            cash_moved = -(gross + fees) if what == "buy" else gross - fees
            rec = {**base, "type": "trade", "time": "", "name": name or isin, "qty": sign * qty, "price": price or gross / qty,
                   "price_ccy": "EUR", "amount_eur": round(cash_moved, 6), "fees_eur": -fees, "autofx_eur": 0.0, "corporate": False}
            return [rec], cash_moved
        if what in ("exchange_out", "exchange_in"):
            need_isin()
            if not name:
                raise Msg("an exchange needs the same name on both legs, to pair them")
            qty = abs(num("quantity"))
            if qty <= 0:
                raise Msg("quantity must be greater than zero")
            rec = {**base, "type": "trade", "time": "", "qty": -qty if what == "exchange_out" else qty, "price": None,
                   "price_ccy": "EUR", "amount_eur": 0.0, "fees_eur": 0.0, "autofx_eur": 0.0, "corporate": True}
            return [rec], 0.0
        amount = abs(num("amount"))
        eur_delta = (lambda sign: sign * amount) if ccy == "EUR" else (lambda sign: None)   # other currencies are converted later
        if what == "dividend":
            need_isin()
            return [{**base, "type": "dividend", "amount": amount}], eur_delta(1)
        if what == "dividend_tax":
            need_isin()
            return [{**base, "type": "dividend_tax", "amount": -amount}], eur_delta(-1)
        rec = {**base, "type": "fee", "amount": -amount}
        if what == "transaction_tax":
            rec["kind"] = "ttf"
        return [rec], eur_delta(-1)
