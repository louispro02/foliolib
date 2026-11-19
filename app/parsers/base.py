"""Interface shared by every broker parser, plus the small helpers the readers use.

A parser turns the text of one CSV export into a list of **records** (plain dicts). The calculation core understands the
record types below for ANY broker: the `broker` field says which account a record belongs to, so supporting a new broker takes
a parser and nothing else. All records carry `broker` (a short lowercase key such as "degiro") and, when dated, `date` as
ISO `YYYY-MM-DD`.

    type                    required fields                                       optional fields
    deposit, withdrawal     date, amount (positive), ccy
    trade                   date, isin, name, qty (+ buy, - sell),                time, price, price_ccy, fees_eur,
                            amount_eur (cash moved: negative for a purchase,      autofx_eur, corporate (True for a
                            fees included)                                        split or exchange: shares move, no cash)
    dividend                date, isin, name, amount, ccy
    dividend_tax            date, isin, name, amount (negative), ccy
    fee                     date, amount (negative), ccy                          kind: "connexion" or "ttf" to count it
                                                                                  under that heading of the costs page
    snapshot_cash           value_eur: the cash balance now (the last one         (no date)
                            loaded wins). WITHOUT IT, uninvested money is not
                            counted and the gain looks smaller than it is.
    snapshot                isin, name, qty, price, ccy, value_eur: a portfolio   used as a price fallback
                            statement

Do not add a `key` yourself: the registry in `parsers/__init__.py` derives a stable one per record.
"""
import csv
import io
from abc import ABC, abstractmethod
from datetime import datetime


def fr_num(s):
    """'1 234,56' or '1234.56' or ' 100' -> float; empty -> None."""
    s = (s or "").replace("\xa0", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def iso(d, fmt):
    """Parse a date written with `fmt` (e.g. '%d-%m-%Y') into 'YYYY-MM-DD'."""
    return datetime.strptime(d.strip(), fmt).date().isoformat()


def rows(text, delim):
    """All CSV rows of `text` (header included) as lists of strings."""
    return list(csv.reader(io.StringIO(text), delimiter=delim))


class BaseParser(ABC):
    """One file type of one broker. Subclasses are discovered automatically: just define them in a module of this package."""

    kind = ""   # unique identifier of the file type, stored with every record (e.g. "degiro_transactions")

    @classmethod
    @abstractmethod
    def detect(cls, header: str) -> bool:
        """True if `header` (the first line of the file, lowercased, BOM removed) belongs to this file type."""

    @classmethod
    @abstractmethod
    def parse(cls, text: str) -> list:
        """Decoded file content -> list of records. Skip lines that carry no data; raise ValueError on unusable content."""
