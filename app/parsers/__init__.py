"""Reading broker exports (CSV). No external library.

Each file type is a `BaseParser` subclass (see ``base.py``); the ones defined in the modules of this package are found
automatically, so supporting a new broker means adding one module here and nothing else:

    # parsers/mybroker.py
    from .base import BaseParser, fr_num, iso, rows

    class MyBrokerTrades(BaseParser):
        kind = "mybroker_trades"
        @classmethod
        def detect(cls, header): return header.startswith("date,symbol,qty")
        @classmethod
        def parse(cls, text): ...   # -> [{"type": "trade", "broker": "mybroker", "date": "2025-01-31", ...}]

`parse(raw)` is the public entry point: bytes -> (file type, records with a stable key).
"""
import hashlib
import importlib
import pkgutil

from .base import BaseParser, fr_num, iso, rows  # noqa: F401  (re-exported for callers and tests)

# Parser version: bump it whenever the output for a file type changes (see store.migrate, which re-reads the preserved files).
PARSER_VERSION = 2
AFFECTED = {2: ("degiro_transactions", "degiro_account")}     # file types whose output changed in this version


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def _discover():
    """Import every module of the package, then register the BaseParser subclasses they define, by `kind`."""
    for mod in sorted(m.name for m in pkgutil.iter_modules(__path__)):
        if mod != "base":
            importlib.import_module(f"{__name__}.{mod}")
    found = {}
    for cls in _all_subclasses(BaseParser):
        if not cls.kind:
            continue
        if cls.kind in found and found[cls.kind] is not cls:
            raise RuntimeError(f"two parsers declare the kind {cls.kind!r}")
        found[cls.kind] = cls
    return found


REGISTRY = _discover()     # kind -> parser class


def decode(raw):
    """DEGIRO exports are UTF-8, Fortuneo ones ISO-8859-1 (sometimes with a BOM)."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("unreadable encoding")


def detect(text):
    """File type of a decoded export, from its header line; None if no parser recognizes it."""
    head = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    h = head.lower()
    for cls in REGISTRY.values():
        if cls.detect(h):
            return cls.kind
    return None


def keyed(kind, records):
    """Stable key per record: re-uploading an export that overlaps another doubles nothing.
    Two identical lines in the same file keep different keys (order of appearance)."""
    seen = {}
    for r in records:
        base = hashlib.sha256((kind + "|" + repr(sorted(r.items()))).encode()).hexdigest()[:24]
        n = seen.get(base, 0)
        seen[base] = n + 1
        r["key"] = f"{base}#{n}"
    return records


def parse(raw):
    """bytes -> (file type, records with key). Raises ValueError if the format is unknown or empty."""
    text = decode(raw)
    kind = detect(text)
    if not kind:
        raise ValueError("unrecognized format (expected: DEGIRO Transactions, Account or Portfolio export; Fortuneo history or account)")
    recs = keyed(kind, REGISTRY[kind].parse(text))
    if not recs:
        raise ValueError("no usable row in this file")
    return kind, recs
