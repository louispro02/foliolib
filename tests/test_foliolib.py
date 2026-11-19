"""FolioLib tests: parsers, calculations, sign-in, server. Synthetic data, no network access.
    python3 -I tests/test_foliolib.py
"""
import atexit
import http.client
import json
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="foliolib-test-")
atexit.register(shutil.rmtree, TMP, True)
os.environ["FOLIOLIB_DATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import auth
import demo
import engine
import ledger
import main
import parsers
import perf
import quotes
import store

REAL_REFRESH = engine.refresh      # the Server tests replace engine.refresh below; the demo tests need the real one

# Fortuneo exports carry no ISIN: the tests map their synthetic label to a fictitious one
ledger.FORTUNEO_SEED["engie"] = "FR0000000012"

TRANS = ("Date,Heure,Produit,Code ISIN,Place boursière sectionnée,Lieu d'exécution,Quantité,Cours,,Montant devise locale,,Montant EUR,Taux de change,Frais conversion AutoFX,Frais de courtage et/ou de parties,Montant négocié EUR,ID Ordre\n"
         '01-02-2025,10:00,ETF MONDE,IE0000000001,EPA,XPAR,10,"100,0000",EUR,"-1000,00",EUR,"-1000,00","0,0000","0,00","-2,00","-1002,00",aaa\n'
         '01-03-2025,10:00,ETF MONDE,IE0000000001,EPA,XPAR,-4,"120,0000",EUR,"480,00",EUR,"480,00","0,0000","0,00","-2,00","478,00",bbb\n'
         '01-04-2025,00:00,PETITE SA,FR0000000010,EPA,,-20,"0,5000",EUR,"10,00",EUR,"10,00","0,0000","0,00",,"10,00",\n'
         '01-04-2025,00:00,PETITE SA,FR0000000011,EPA,,2,"5,0000",EUR,"-10,00",EUR,"-10,00","0,0000","0,00",,"-10,00",\n'
         '01-01-2025,10:00,PETITE SA,FR0000000010,EPA,XPAR,20,"1,1000",EUR,"-22,00",EUR,"-22,00","0,0000","0,00","-1,00","-23,00",ccc\n')
ACCOUNT = ("Date,Heure,Date de,Produit,Code ISIN,Description,FX,Mouvements,,Solde,,ID Ordre\n"
           '02-01-2025,10:00,02-01-2025,,,Dépôt flatex,,EUR,"2000,00",EUR,"2000,00",\n'
           '02-06-2025,10:00,02-06-2025,ETF MONDE,IE0000000001,Dividende,,USD,"11,00",USD,"11,00",\n'
           '02-07-2025,10:00,02-07-2025,,,Processed Flatex Withdrawal,,EUR,"-100,00",EUR,"1900,00",\n'
           '02-07-2025,22:30,03-07-2025,,,Processed Flatex Withdrawal,,EUR,"100,00",EUR,"2000,00",\n'
           '02-07-2025,22:30,03-07-2025,,,Retrait flatex,,EUR,"-100,00",EUR,"1900,00",\n')
PORTFOLIO = ('Produit,Ticker/ISIN,Quantité,Clôture,Devise,,Montant en EUR\n'
             'CASH & CASH FUND & FTX CASH (EUR),,,,EUR,"50,00","50,00"\n'
             'ETF MONDE,IE0000000001,6,"130,00",EUR,"780,00","780,00"\n')
F_OPS = ("libellé;Opération;Place;Date;Qté;Prix d'éxé;Montant brut;Courtage/Prélèvement;Montant net;Devise;\n"
         "ENGIE;Achat Comptant;Euronext Paris;03/06/2025;40.0;10.0;-400.0;-1.0;-401.0;EUR;\n"
         "ENGIE;TAXE TRANSAC FINAN;Euronext Paris;03/06/2025;1.0;0.0;-0.8;0.0;-0.8;EUR;\n"
         "ENGIE;Encaissement coupons intérêt/dividende;Euronext Paris;05/08/2025;40.0;0.0;5.0;0.0;5.0;EUR;\n"
         "ENGIE;OST de création de coupons - Détachement coupon optionnel;Euronext Paris;03/08/2025;40.0;0.0;5.0;0.0;5.0;EUR;\n"
         "ENGIE;OST de mutation - Echange automatique    ;Euronext Paris;08/09/2025;40.0;0.0;0.0;0.0;0.0;EUR;\n"
         "ENGIE;OST de mutation - Echange automatique    ;Euronext Paris;08/09/2025;4.0;0.0;0.0;0.0;0.0;EUR;\n").encode("latin-1")
F_CASH = ("Date opération;Date valeur;libellé;Débit;Crédit;\n"
          "22/05/2025;22/05/2025;versement;; 500;\n"
          "04/06/2025;03/06/2025;achat 40 engie;-401,8;;\n"
          "06/08/2025;05/08/2025;dividende 40 engie;; 5;\n").encode("latin-1")


def load(*blobs):
    recs = []
    for b in blobs:
        recs += parsers.parse(b if isinstance(b, bytes) else b.encode())[1]
    return recs


class Parsers(unittest.TestCase):
    def test_detection(self):
        kinds = [parsers.parse(x if isinstance(x, bytes) else x.encode())[0] for x in (TRANS, ACCOUNT, PORTFOLIO, F_OPS, F_CASH)]
        self.assertEqual(kinds, ["degiro_transactions", "degiro_account", "degiro_portfolio", "fortuneo_ops", "fortuneo_cash"])

    def test_registry_discovers_every_file_type(self):
        self.assertEqual(sorted(parsers.REGISTRY), ["degiro_account", "degiro_portfolio", "degiro_transactions", "foliolib_csv", "fortuneo_cash", "fortuneo_ops"])
        for kind, cls in parsers.REGISTRY.items():
            self.assertTrue(issubclass(cls, parsers.BaseParser))
            self.assertEqual(cls.kind, kind)

    def test_each_export_matches_exactly_one_parser(self):
        # a new broker's detect() must not steal another broker's files: every fixture is claimed by one parser only
        for blob, kind in ((TRANS, "degiro_transactions"), (ACCOUNT, "degiro_account"), (PORTFOLIO, "degiro_portfolio"), (F_OPS, "fortuneo_ops"), (F_CASH, "fortuneo_cash")):
            raw = blob if isinstance(blob, bytes) else blob.encode()
            header = parsers.decode(raw).lstrip("﻿").splitlines()[0].lower()
            self.assertEqual([c.kind for c in parsers.REGISTRY.values() if c.detect(header)], [kind])

    def test_unknown_or_empty_format(self):
        with self.assertRaises(ValueError):
            parsers.parse(b"a,b,c\n1,2,3\n")
        with self.assertRaises(ValueError):
            parsers.parse(TRANS.splitlines()[0].encode() + b"\n")

    def test_french_decimals(self):
        self.assertEqual(parsers.fr_num("1 234,56"), 1234.56)
        self.assertEqual(parsers.fr_num(" 100"), 100.0)
        self.assertEqual(parsers.fr_num("-0.08"), -0.08)
        self.assertIsNone(parsers.fr_num(""))

    def test_uploading_twice_doubles_nothing(self):
        db = store.connect(Path(TMP) / "dedup.sqlite")
        k, r = parsers.parse(TRANS.encode())
        self.assertEqual(store.add_file(db, "a.csv", k, r), (5, 5))
        k, r = parsers.parse(TRANS.encode())
        self.assertEqual(store.add_file(db, "a.csv", k, r), (5, 0))


class Calculations(unittest.TestCase):
    def setUp(self):
        self.res = ledger.build(load(TRANS, ACCOUNT, PORTFOLIO, F_OPS, F_CASH), fx=lambda c, d: 0.9 if c == "USD" else None)

    def pos(self, broker, isin):
        return self.res["positions"][(broker, isin)]

    def test_average_cost_and_partial_sale(self):
        p = self.pos("degiro", "IE0000000001")
        self.assertAlmostEqual(p.cost, 1002 * 6 / 10)                  # fees included, sale at the average cost
        self.assertEqual(p.qty, 6)
        self.assertAlmostEqual(p.realized, 478 - 1002 * 0.4)

    def test_split_keeps_cost_basis_without_gain(self):
        old, new = self.pos("degiro", "FR0000000010"), self.pos("degiro", "FR0000000011")
        self.assertEqual((old.qty, old.realized), (0, 0.0))
        self.assertEqual((new.qty, round(new.cost, 2)), (2, 23.0))

    def test_fortuneo_tax_dividend_exchange(self):
        p = self.pos("fortuneo", "FR0000000012")
        self.assertEqual(p.qty, 4)                                       # 40 -> 4
        self.assertAlmostEqual(p.cost, 401.8)                            # 401 + 0.8 of tax
        self.assertEqual(p.dividends, 5.0)                               # the duplicate "coupon creation" line is not counted
        self.assertEqual(sum(1 for d in self.res["dividends"] if d[1] == "fortuneo"), 1)

    def test_deposits_and_cash(self):
        by = {}
        for _, b, a in self.res["flows"]:
            by[b] = by.get(b, 0) + a
        self.assertEqual(by, {"degiro": 1900.0, "fortuneo": 500.0})
        self.assertAlmostEqual(self.res["cash"]["fortuneo"], 500 - 401.8 + 5)
        self.assertEqual(self.res["cash"]["degiro"], 50.0)

    def test_dollar_dividend_converted(self):
        d = [x for x in self.res["dividends"] if x[1] == "degiro"][0]
        self.assertAlmostEqual(d[4], 9.9)

    def test_annualized_return(self):
        r = ledger.xirr([("2025-01-01", 1000.0)], 1100.0, "2026-01-01")
        self.assertAlmostEqual(r, 0.10, places=3)
        self.assertIsNone(ledger.xirr([], 100.0, "2026-01-01"))
        self.assertIsNone(ledger.xirr([("2025-01-01", 1000.0)], 0.0, "2026-01-01"))

    def test_fortuneo_split_in_the_other_direction(self):
        ops = F_OPS.replace(b"40.0;0.0;0.0;0.0;0.0;EUR;\n", b"@@").replace(b"ENGIE;OST de mutation - Echange automatique    ;Euronext Paris;08/09/2025;4.0;0.0;0.0;0.0;0.0;EUR;\n", b"")
        # buy 40, then split 10-for-1: the quantity goes from 40 to 400 (the statement gives 40 then 400)
        ops = F_OPS.split(b"ENGIE;OST de mutation")[0] + (b"ENGIE;OST de mutation - Echange automatique    ;Euronext Paris;08/09/2025;40.0;0.0;0.0;0.0;0.0;EUR;\n"
                                                         b"ENGIE;OST de mutation - Echange automatique    ;Euronext Paris;08/09/2025;400.0;0.0;0.0;0.0;0.0;EUR;\n")
        res = ledger.build(load(ops))
        self.assertEqual(res["positions"][("fortuneo", "FR0000000012")].qty, 400)
        self.assertEqual(res["warnings"], [])
        ev = ledger.timeline(load(ops))
        self.assertEqual(sum(d for _, k, d in ev if k == ("fortuneo", "FR0000000012")), 400)

    def test_comparison_and_wrapper(self):
        t = engine.Table([("2025-01-01", 100.0), ("2026-01-01", 110.0)])
        c = engine._compare([("2025-01-01", 1000.0)], "2026-01-01", {"IWDA.AS": t}, 1200.0)
        w = c["benchmarks"][0]
        self.assertEqual(w["key"], "world")
        self.assertAlmostEqual(w["value"], 1100.0)
        self.assertAlmostEqual(w["diff"], 100.0)
        self.assertAlmostEqual(c["livret"], 1030.0, places=0)
        self.assertIsNone(engine._compare([], "2026-01-01", {}, 1.0))

    def test_unknown_fortuneo_label_flagged(self):
        res = ledger.build(load(F_OPS.replace(b"ENGIE", b"INCONNU")))
        self.assertTrue(any(p.unmapped for p in res["positions"].values()))


class Performance(unittest.TestCase):
    """Time-weighted index on a synthetic security: +10%, purchase, -20%, +50%."""

    @staticmethod
    def days(prices, buys):
        from datetime import date as D
        start = D(2025, 1, 6)
        ev = [(start.isoformat(), ("degiro", "X"), 10.0)] + [(d, ("degiro", "X"), q) for d, q, _ in buys]
        inv = [(start.isoformat(), "degiro", 1000.0)] + [(d, "degiro", c) for d, _, c in buys]
        series = {}
        d = start
        for p in prices:
            while d.weekday() >= 5:
                d += __import__("datetime").timedelta(days=1)
            series[d.isoformat()] = p
            d += __import__("datetime").timedelta(days=1)
        px = lambda isin, s: series.get(s)
        return perf.portfolio_days(ev, px, inv, [], {"degiro"}, D.fromisoformat(max(series))), series

    def test_deposits_are_not_return(self):
        prices = [100.0] * 25 + [110.0] * 5 + [88.0] * 5 + [132.0] * 5
        days, series = self.days(prices, [])
        self.assertAlmostEqual(days[-1]["idx"], 1.32, places=6)                      # 100 -> 132, whatever happens in between
        # same path with a purchase of 10 shares at the top: the index does not change, the euro value does
        buy_day = sorted(series)[29]
        days2, _ = self.days(prices, [(buy_day, 10.0, 1100.0)])
        self.assertAlmostEqual(days2[-1]["idx"], 1.32, places=6)
        self.assertGreater(days2[-1]["v"], days[-1]["v"])

    def test_max_drawdown_and_run_up(self):
        prices = [100.0] * 25 + [110.0] * 5 + [88.0] * 5 + [132.0] * 5
        days, _ = self.days(prices, [])
        m = perf.metrics(days)
        self.assertAlmostEqual(m["max_drawdown"], 88 / 110 - 1, places=6)
        self.assertAlmostEqual(m["max_runup"], 132 / 88 - 1, places=6)
        self.assertEqual(m["mdd_peak"] < m["mdd_trough"], True)
        self.assertIsNone(perf.metrics(days[:10]))                                    # too short to measure anything

    def test_index_only_starts_after_500_euros(self):
        from datetime import date as D
        ev = [("2025-01-06", ("degiro", "X"), 1.0)]
        days = perf.portfolio_days(ev, lambda i, s: 2.0, [("2025-01-06", "degiro", 3.0)], [], {"degiro"}, D(2025, 3, 1))
        self.assertEqual(days, [])                                                    # 2 € of securities: nothing to measure

    def test_volatility_and_monthly_returns(self):
        prices = [100.0 + (i % 2) for i in range(60)]
        days, _ = self.days(prices, [])
        m = perf.metrics(days)
        self.assertGreater(m["volatility"], 0)
        self.assertEqual(len(perf.monthly_returns(perf.measured(days))), len({d["date"][:7] for d in days}))


class Migration(unittest.TestCase):
    def test_preserved_files_are_re_read(self):
        db = store.connect(Path(TMP) / "mig.sqlite")
        raw = TRANS.encode()
        sha = store.save_raw(raw)
        k, r = parsers.parse(raw)
        store.add_file(db, "t.csv", k, r, sha)
        store.add_file(db, "old.csv", "degiro_account", parsers.parse(ACCOUNT.encode())[1])     # uploaded before preservation
        store.meta_set(db, "parser_version", "1")
        need = store.migrate(db)
        self.assertEqual(need, ["degiro_account"])                                   # only the one that was not kept needs re-uploading
        self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='degiro_transactions'").fetchone()[0], 5)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='degiro_account'").fetchone()[0], 0)
        self.assertEqual(store.migrate(db), [])                                      # only once
        self.assertEqual(oct(store.UPLOADS.stat().st_mode & 0o777), "0o700")


class SignIn(unittest.TestCase):
    def test_password_and_cookie(self):
        auth.set_password("admin", "a-long-password")
        self.assertTrue(auth.check("admin", "a-long-password"))
        self.assertFalse(auth.check("admin", "wrong"))
        self.assertFalse(auth.check("autre", "a-long-password"))
        auth._fails.clear()
        c = auth.make_cookie()
        self.assertTrue(auth.valid_cookie(c))
        self.assertFalse(auth.valid_cookie(c[:-2] + "aa"))
        self.assertFalse(auth.valid_cookie("n'importe quoi"))
        self.assertEqual(oct(auth.PATH.stat().st_mode & 0o777), "0o600")
        auth.set_password("admin", "a-long-password")
        self.assertFalse(auth.valid_cookie(c))                           # changing the password closes sessions

    def test_lockout_after_five_failures(self):
        auth.set_password("admin", "a-long-password")
        auth._fails.clear()
        auth._fails.extend([__import__("time").time()] * 5)
        self.assertFalse(auth.check("admin", "a-long-password"))
        auth._fails.clear()


ROOT = Path(__file__).resolve().parent.parent
ACME_CSV = ("date,type,isin,name,quantity,price,amount\n"
            "2025-01-02,deposit,,,,,1000\n"
            "2025-01-03,buy,US0000000009,ACME CORP,10,50,\n"
            "2025-03-01,dividend,US0000000009,ACME CORP,,,4.5\n")


def load_example_broker():
    """Import docs/examples/example_broker.py as if it lived in the parsers package (it uses relative imports)."""
    spec = importlib.util.spec_from_file_location("parsers.example_broker", ROOT / "docs" / "examples" / "example_broker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NewBroker(unittest.TestCase):
    """The promise of the parsers package: a new broker needs a parser module and nothing else."""

    def setUp(self):
        self.db = store.connect(Path(tempfile.mkdtemp(prefix="foliolib-acme-", dir=TMP)) / "acme.sqlite")
        self.dir = Path(TMP)
        self.acme = load_example_broker().AcmeActivity

    def tearDown(self):
        self.db.close()

    def price(self, isin, symbol, value):
        self.db.execute("INSERT OR REPLACE INTO instruments(isin,symbol,ccy,manual,tried) VALUES(?,?,'EUR',1,0)", (isin, symbol))
        self.db.execute("INSERT OR REPLACE INTO quote(symbol,price,ccy,at,source) VALUES(?,?,'EUR',strftime('%s','now'),'yahoo')", (symbol, value))
        self.db.commit()

    def test_example_parser_reads_its_file(self):
        self.assertTrue(self.acme.detect(ACME_CSV.splitlines()[0].lower()))
        recs = self.acme.parse(ACME_CSV)
        self.assertEqual([r["type"] for r in recs], ["deposit", "trade", "dividend", "snapshot_cash"])
        self.assertEqual(recs[-1]["value_eur"], 504.5)                        # 1000 deposited - 500 invested + 4.5 dividend
        self.assertEqual(recs[1]["qty"], 10.0)
        self.assertEqual(recs[1]["amount_eur"], -500.0)

    def test_a_new_broker_is_computed_under_its_own_account(self):
        store.add_file(self.db, "acme.csv", "acme_activity", parsers.keyed("acme_activity", self.acme.parse(ACME_CSV)))
        self.price("US0000000009", "ACME", 60.0)
        d = engine.compute(self.db, self.dir)
        self.assertEqual([a["key"] for a in d["accounts"]], ["acme"])
        self.assertEqual(d["accounts"][0]["short"], "Acme")
        self.assertEqual(d["kpi"]["invested"], 1000.0)                       # the deposit is counted
        self.assertEqual(d["kpi"]["dividends"], 4.5)
        (pos,) = d["positions"]
        self.assertEqual((pos["broker"], pos["account"], pos["account_short"], pos["qty"]), ("acme", "Acme", "Acme", 10.0))
        self.assertAlmostEqual(d["kpi"]["value"], 10 * 60.0 + 504.5)         # 10 shares at 60 + the cash balance
        self.assertAlmostEqual(d["kpi"]["gain"], 104.5)
        self.assertEqual([f["account"] for f in d["flows"]], ["Acme"])

    def test_a_new_broker_works_next_to_existing_ones(self):
        records, series, last = demo.build()
        demo.load(self.db)
        store.add_file(self.db, "acme.csv", "acme_activity", parsers.keyed("acme_activity", self.acme.parse(ACME_CSV)))
        self.price("US0000000009", "ACME", 60.0)
        d = engine.compute(self.db, self.dir)
        self.assertEqual([a["key"] for a in d["accounts"]], ["acme", "degiro"])
        by_key = {a["key"]: a for a in d["accounts"]}
        self.assertEqual(by_key["acme"]["invested"], 1000.0)
        self.assertEqual(by_key["degiro"]["invested"], demo.DEPOSIT * sum(1 for r in records["degiro_account"] if r["type"] == "deposit"))
        self.assertEqual(d["kpi"]["invested"], by_key["acme"]["invested"] + by_key["degiro"]["invested"])
        self.assertEqual(sorted({p["broker"] for p in d["positions"]}), ["acme", "degiro"])
        self.assertEqual(set(d["series"]["by_account"]), {"acme", "degiro"})

    def test_dropping_the_file_into_the_package_is_enough(self):
        # real auto-discovery, in a copy of the application: no registration, no change to any other file
        work = Path(tempfile.mkdtemp(prefix="foliolib-copy-", dir=TMP)) / "app"
        shutil.copytree(ROOT / "app", work, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "docs" / "examples" / "example_broker.py", work / "parsers" / "acme.py")
        code = ("import parsers; kind, recs = parsers.parse(%r.encode()); print(kind, len(recs), sorted(parsers.REGISTRY))" % ACME_CSV)
        out = subprocess.run([sys.executable, "-c", code], cwd=work, capture_output=True, text=True, check=True).stdout
        self.assertIn("acme_activity 4", out)
        self.assertIn("degiro_account", out)


GENERIC_HEADER = "date,type,account,isin,name,quantity,price,amount,currency,fees,note"
GENERIC_EXAMPLE = ROOT / "docs" / "examples" / "generic-example.csv"


class GenericCsvFormat(unittest.TestCase):
    """The documented FolioLib CSV: one format any broker's data can be converted into."""

    def setUp(self):
        self.db = store.connect(Path(tempfile.mkdtemp(prefix="foliolib-generic-", dir=TMP)) / "generic.sqlite")
        self.dir = Path(TMP)

    def tearDown(self):
        self.db.close()

    def table(self, *rows, header=GENERIC_HEADER):
        return "\n".join([header, *rows]) + "\n"

    def parse(self, text):
        return parsers.parse(text.encode())

    def error(self, text):
        with self.assertRaises(ValueError) as caught:
            self.parse(text)
        return str(caught.exception)

    def test_header_is_the_same_in_the_code_the_example_and_the_docs(self):
        from parsers import generic
        self.assertEqual(generic.HEADER, GENERIC_HEADER)
        self.assertEqual(GENERIC_EXAMPLE.read_text().splitlines()[0], GENERIC_HEADER)

    def test_only_the_generic_parser_claims_a_generic_file(self):
        header = GENERIC_HEADER.lower()
        self.assertEqual([c.kind for c in parsers.REGISTRY.values() if c.detect(header)], ["foliolib_csv"])
        for other in ("date,type,isin,name,quantity,price,amount",                 # the broker example of CONTRIBUTING.md
                      "date,heure,produit,code isin,place boursi\u00e8re", "libell\u00e9;op\u00e9ration;place;date;qt\u00e9;prix d'ex\u00e9;montant"):
            self.assertNotIn("foliolib_csv", [c.kind for c in parsers.REGISTRY.values() if c.detect(other)])

    def test_the_example_builds_a_complete_portfolio(self):
        kind, recs = parsers.parse(GENERIC_EXAMPLE.read_bytes())
        self.assertEqual(kind, "foliolib_csv")
        store.add_file(self.db, "generic-example.csv", kind, recs)
        for isin, symbol, price in (("IE0000000001", "ETF", 95.0), ("FR0000000030", "BLUE", 250.0)):
            self.db.execute("INSERT INTO instruments(isin,symbol,ccy,manual,tried) VALUES(?,?,'EUR',1,0)", (isin, symbol))
            self.db.execute("INSERT INTO quote(symbol,price,ccy,at,source) VALUES(?,?,'EUR',strftime('%s','now'),'yahoo')", (symbol, price))
        self.db.commit()
        d = engine.compute(self.db, self.dir)
        kpi = d["kpi"]
        self.assertEqual([(a["key"], a["short"]) for a in d["accounts"]], [("brokerage", "Brokerage")])
        self.assertEqual(kpi["invested"], 2000.0)
        self.assertAlmostEqual(d["accounts"][0]["cash"], 659.30)            # 2000 - 801.5 - 901.5 + 6.3 - 2.5 + 358.5
        self.assertAlmostEqual(kpi["value"], 6 * 95 + 4 * 250 + 659.30)
        self.assertAlmostEqual(kpi["realized"], 37.9)                       # 4 shares sold at 90 over an average cost of 80.15, minus fees
        self.assertAlmostEqual(kpi["dividends"], 6.3)                       # 9.00 gross - 2.70 withholding
        positions = {p["isin"]: p for p in d["positions"]}
        self.assertAlmostEqual(positions["FR0000000030"]["cost"], 901.5)    # the reverse split carries the cost: no fake gain or loss
        self.assertAlmostEqual(positions["IE0000000001"]["cost"], 480.9)
        self.assertEqual(d["warnings"], [])

    def test_a_semicolon_file_with_decimal_commas_gives_the_same_records(self):
        point = self.table("2025-02-03,buy,Main,IE0000000001,WORLD ETF,2.5,80.25,,EUR,1.5,", "2025-02-04,deposit,Main,,,,,1000.5,EUR,,")
        comma = point.replace(",", ";").replace("2.5;80.25", "2,5;80,25").replace("1.5;", "1,5;").replace("1000.5", "1000,5")
        self.assertIn(";", comma.splitlines()[0])
        self.assertEqual([{k: v for k, v in r.items() if k != "key"} for r in self.parse(point)[1]],
                         [{k: v for k, v in r.items() if k != "key"} for r in self.parse(comma)[1]])

    def test_column_order_and_extra_columns_do_not_matter(self):
        shuffled = "note,amount,type,date,account,extra,isin,name,quantity,price,currency,fees\n,500,deposit,2025-01-02,Main,x,,,,,EUR,\n"
        (rec, balance) = self.parse(shuffled)[1][:2]
        self.assertEqual((rec["type"], rec["amount"], rec["broker"], rec["date"]), ("deposit", 500.0, "main", "2025-01-02"))
        self.assertEqual(balance["value_eur"], 500.0)

    def test_types_are_forgiving_about_case_and_spaces(self):
        recs = self.parse(self.table("2025-01-02,Dividend Tax,Main,FR0000000003,BLUE,,,2.5,EUR,,"))[1]
        self.assertEqual((recs[0]["type"], recs[0]["amount"]), ("dividend_tax", -2.5))

    def test_buy_and_sell_cash_amounts(self):
        buy, sell = self.parse(self.table("2025-01-03,buy,Main,IE0000000001,ETF,10,80,,EUR,1.5,", "2025-02-03,sell,Main,IE0000000001,ETF,4,,360,EUR,1.5,"))[1][:2]
        self.assertEqual((buy["qty"], buy["amount_eur"], buy["fees_eur"]), (10.0, -801.5, -1.5))      # price x quantity + fees leave the account
        self.assertEqual((sell["qty"], sell["amount_eur"], sell["price"]), (-4.0, 358.5, 90.0))         # amount given: the price is derived

    def test_several_accounts_in_one_file(self):
        text = self.table("2025-01-02,deposit,Broker A,,,,,100,EUR,,", "2025-01-02,deposit,Broker B,,,,,300,EUR,,")
        d = self.dashboard(text)
        self.assertEqual({a["key"]: a["invested"] for a in d["accounts"]}, {"broker_a": 100.0, "broker_b": 300.0})
        self.assertEqual(d["kpi"]["invested"], 400.0)

    def dashboard(self, text):
        store.add_file(self.db, "g.csv", *self.parse(text))
        return engine.compute(self.db, self.dir)

    def test_cash_is_rebuilt_from_the_activity_unless_the_file_states_it(self):
        deposit, buy = "2025-01-02,deposit,Main,,,,,1000,EUR,,", "2025-01-03,buy,Main,IE0000000001,ETF,5,100,,EUR,0,"
        rebuilt = [r for r in self.parse(self.table(deposit, buy))[1] if r["type"] == "snapshot_cash"]
        self.assertEqual([r["value_eur"] for r in rebuilt], [500.0])
        stated = [r for r in self.parse(self.table(deposit, buy, "2025-01-10,cash_balance,Main,,,,,777.7,EUR,,"))[1] if r["type"] == "snapshot_cash"]
        self.assertEqual([r["value_eur"] for r in stated], [777.7])                      # the stated balance replaces the rebuilt one
        two = [r for r in self.parse(self.table(deposit, "2025-03-01,cash_balance,Main,,,,,300,EUR,,", "2025-02-01,cash_balance,Main,,,,,200,EUR,,"))[1]
               if r["type"] == "snapshot_cash"]
        self.assertEqual([r["value_eur"] for r in two], [300.0])                         # the most recent date wins, not the last row

    def test_no_balance_is_better_than_a_negative_one(self):
        recs = self.parse(self.table("2025-01-03,buy,Main,IE0000000001,ETF,5,100,,EUR,0,"))[1]       # the deposits are missing
        self.assertEqual([r["type"] for r in recs], ["trade"])

    def test_a_foreign_currency_dividend_keeps_its_currency_and_stays_out_of_the_rebuilt_cash(self):
        recs = self.parse(self.table("2025-01-02,deposit,Main,,,,,100,EUR,,", "2025-02-02,dividend,Main,US0000000002,TECH,,,5,USD,,"))[1]
        dividend = next(r for r in recs if r["type"] == "dividend")
        self.assertEqual((dividend["ccy"], dividend["amount"]), ("USD", 5.0))
        self.assertEqual(next(r for r in recs if r["type"] == "snapshot_cash")["value_eur"], 100.0)

    def test_uploading_the_same_file_twice_adds_nothing(self):
        kind, recs = parsers.parse(GENERIC_EXAMPLE.read_bytes())
        first = store.add_file(self.db, "a.csv", kind, recs)
        kind, recs = parsers.parse(GENERIC_EXAMPLE.read_bytes())
        self.assertEqual((first, store.add_file(self.db, "b.csv", kind, recs)), ((10, 10), (10, 0)))

    def test_errors_say_which_row_and_what_to_fix(self):
        cases = {
            "2025-13-40,deposit,Main,,,,,100,EUR,,": "row 2: date '2025-13-40' must be written YYYY-MM-DD",
            "2025-01-02,gift,Main,,,,,100,EUR,,": "unknown type 'gift'",
            "2025-01-02,buy,Main,IE0000000001,ETF,1,10,,USD,,": "must be in euros",
            '2025-01-02,deposit,Main,,,,,"1,000.50",EUR,,': "is not a number",
            "2025-01-02,deposit,Main,,,,,12,5,EUR,,": "probably split in two columns",
            "2025-01-02,buy,Main,,ETF,1,10,,EUR,,": "isin '' must be 12 letters or digits",
            "2025-01-02,buy,Main,IE0000000001,ETF,0,10,,EUR,,": "quantity must be greater than zero",
            "2025-01-02,buy,Main,IE0000000001,ETF,1,,,EUR,,": "needs an amount, or a price and a quantity",
            "2025-01-02,deposit,Main,,,,,nan,EUR,,": "is not a number",
            "2025-01-02,exchange_in,Main,FR0000000030,,4,,,,,": "same name on both legs",
        }
        for row, expected in cases.items():
            self.assertIn(expected, self.error(self.table(row)), row)
        self.assertIn("use a dot as the decimal separator", self.error(self.table('2025-01-02,deposit,Main,,,,,"12,5",EUR,,')))

    def test_every_bad_row_is_reported_together_up_to_a_limit(self):
        message = self.error(self.table(*["2025-01-02,gift,Main,,,,,1,EUR,,"] * 8))
        self.assertEqual(message.count("row "), 5)
        self.assertTrue(message.endswith("(and 3 more)"))

    def test_rows_of_the_same_day_are_applied_in_file_order(self):
        buy_sell_buy = self.table("2025-01-02,deposit,Main,,,,,5000,EUR,,", "2025-01-03,buy,Main,IE0000000001,ETF,10,80,,EUR,0,",
                                  "2025-01-03,sell,Main,IE0000000001,ETF,5,90,,EUR,0,", "2025-01-03,buy,Main,IE0000000001,ETF,10,100,,EUR,0,")
        buy_buy_sell = self.table("2025-01-02,deposit,Main,,,,,5000,EUR,,", "2025-01-03,buy,Main,IE0000000001,ETF,10,80,,EUR,0,",
                                  "2025-01-03,buy,Main,IE0000000001,ETF,10,100,,EUR,0,", "2025-01-03,sell,Main,IE0000000001,ETF,5,90,,EUR,0,")
        self.assertAlmostEqual(self.dashboard(buy_sell_buy)["kpi"]["realized"], 50.0)    # sold at 90 over an average cost of 80
        self.db.execute("DELETE FROM records"); self.db.execute("DELETE FROM files"); self.db.commit()
        self.assertAlmostEqual(self.dashboard(buy_buy_sell)["kpi"]["realized"], 0.0)     # sold at 90 over an average cost of 90

    def test_a_transaction_tax_is_counted_under_its_own_heading(self):
        d = self.dashboard(self.table("2025-01-02,deposit,Main,,,,,1000,EUR,,", "2025-01-03,transaction_tax,Main,,,,,1.2,EUR,,", "2025-01-04,fee,Main,,,,,3,EUR,,"))
        taxes = {t["label"]: t["eur"] for t in d["costs"]["taxes"]}
        self.assertEqual(taxes["Financial transaction tax"], 1.2)                        # the plain fee is not counted there
        self.assertAlmostEqual(d["accounts"][0]["cash"], 1000 - 1.2 - 3)

    def test_a_corrected_row_does_not_replace_the_wrong_one(self):
        # documented in docs/generic-csv.md: rows are recognized by content, so correcting needs an erase and a new import
        wrong = self.table("2025-01-02,deposit,Main,,,,,100,EUR,,")
        store.add_file(self.db, "a.csv", *self.parse(wrong))
        fixed = self.table("2025-01-02,deposit,Main,,,,,200,EUR,,")
        self.assertEqual(store.add_file(self.db, "b.csv", *self.parse(fixed)), (2, 2))
        self.assertEqual(engine.compute(self.db, self.dir)["kpi"]["invested"], 300.0)
        store.wipe(self.db)
        self.assertEqual(self.dashboard(fixed)["kpi"]["invested"], 200.0)

    def test_an_empty_file_is_refused(self):
        self.assertIn("no usable row", self.error(self.table()))


class Docs(unittest.TestCase):
    """The documentation is part of the product: keep it from drifting away from the code."""

    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_contributing_embeds_the_tested_example_verbatim(self):
        example = (ROOT / "docs" / "examples" / "example_broker.py").read_text(encoding="utf-8").rstrip("\n")
        self.assertIn(example, self.read("CONTRIBUTING.md"))

    def test_relative_links_and_images_exist(self):
        for doc in ("README.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md"):
            for target in re.findall(r"\]\(([^)\s]+)\)", self.read(doc)):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                self.assertTrue((ROOT / target.split("#")[0]).exists(), f"{doc} links to a missing file: {target}")

    def test_anchors_point_to_real_headings(self):
        headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-") for h in re.findall(r"^#+ (.+)$", self.read("CONTRIBUTING.md"), re.M)}
        links = re.findall(r"\]\(CONTRIBUTING\.md#([^)\s]+)\)", self.read("README.md")) + re.findall(r"\]\(#([^)\s]+)\)", self.read("CONTRIBUTING.md"))
        self.assertTrue(links, "expected at least one link to a CONTRIBUTING.md section")
        for anchor in links:
            self.assertIn(anchor, headings, f"link to a missing section: {anchor}")

    def test_documented_environment_variables_are_the_real_ones(self):
        source = self.read("app/store.py") + self.read("app/main.py")
        documented = set(re.findall(r"`(FOLIOLIB_[A-Z]+)`", self.read("README.md")))
        self.assertEqual(documented, set(re.findall(r"FOLIOLIB_[A-Z]+", source)))

    def test_every_documented_command_exists(self):
        source = self.read("app/main.py")
        commands = set(re.findall(r"`(serve|passwd|report|import|demo)\b", self.read("README.md")))
        self.assertEqual(commands, {"serve", "passwd", "report", "import", "demo"})
        for cmd in commands:
            self.assertIn(f'"{cmd}"', source)

    def test_generic_csv_documentation_matches_the_code(self):
        from parsers import generic
        doc = self.read("docs/generic-csv.md")
        self.assertIn("```text\n" + generic.HEADER + "\n```", doc)
        for column in (*generic.REQUIRED, "note"):
            self.assertIn(f"| `{column}` |", doc, f"column {column} is not documented")
        for kind in generic.TYPES:
            self.assertIn(f"`{kind}`", doc, f"row type {kind} is not documented")
        self.assertIn(GENERIC_EXAMPLE.read_text(encoding="utf-8").rstrip("\n"), doc)
        for page in ("README.md", "CONTRIBUTING.md"):
            self.assertIn("docs/generic-csv.md", self.read(page))

    def test_license_is_the_agpl(self):
        text = self.read("LICENSE")
        self.assertTrue(text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE"))
        self.assertIn("Version 3, 19 November 2007", text)


class Demo(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="foliolib-demo-", dir=TMP))
        self.db = store.connect(self.dir / "demo.sqlite")

    def tearDown(self):
        self.db.close()

    def count(self, table):
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_build_is_deterministic(self):
        day = date(2026, 1, 15)
        self.assertEqual(demo.build(day), demo.build(day))

    def test_demo_portfolio_is_complete_and_consistent(self):
        demo.load(self.db)
        d = engine.compute(self.db, self.dir)
        self.assertEqual(len(d["positions"]), 3)
        self.assertEqual({p["source"] for p in d["positions"]}, {"demo"})
        self.assertTrue(d["warnings"][0].startswith("Demo mode"))
        self.assertEqual(len(d["compare"]["benchmarks"]), len(engine.BENCHMARKS))     # every benchmark has prices
        self.assertIn("all", d["perf"])
        self.assertGreater(d["kpi"]["dividends"], 0)
        self.assertGreater(d["costs"]["total_fees"], 0)
        deposits = sum(1 for r in store.all_records(self.db) if r["type"] == "deposit")
        self.assertEqual(d["kpi"]["invested"], demo.DEPOSIT * deposits)
        self.assertEqual(d["unmapped"], [])

    def test_world_index_follows_the_demo_etf(self):
        _, series, _ = demo.build(date(2026, 1, 15))
        self.assertEqual(series["IWDA.AS"], series["DEMOETF"])

    def test_load_refuses_a_database_with_data(self):
        demo.load(self.db)
        with self.assertRaises(SystemExit):
            demo.load(self.db)
        self.assertEqual(self.count("files"), 3)                  # untouched

    def test_load_refuses_real_imported_data(self):
        store.add_file(self.db, "real.csv", *parsers.parse(ACCOUNT.encode()))
        with self.assertRaises(SystemExit):
            demo.load(self.db)
        self.assertEqual(self.count("prices"), 0)                 # nothing was written

    def test_migration_keeps_the_demo_files(self):
        demo.load(self.db)
        before = self.count("records")
        self.assertEqual(store.migrate(self.db), [])
        self.assertEqual(self.count("records"), before)

    def test_refresh_never_reaches_the_network(self):
        demo.load(self.db)
        self.db.execute("UPDATE quote SET at = at - 3600")        # quotes older than STALE_AFTER: a normal database would refetch them
        self.db.commit()
        real_get = quotes._get
        quotes._get = lambda *a, **k: self.fail("the demo must never call the network")
        try:
            self.assertEqual(REAL_REFRESH(self.db, self.dir), [])
        finally:
            quotes._get = real_get

    def test_wipe_removes_the_synthetic_market_data_too(self):
        demo.load(self.db)
        self.assertGreater(self.count("prices"), 0)
        store.wipe(self.db)
        for table in ("records", "files", "prices", "quote", "instruments"):
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(store.meta_get(self.db, "demo"), "")


class Shutdown(unittest.TestCase):
    def test_sigterm_stops_the_server_cleanly(self):
        # a container's `docker stop` sends SIGTERM: the process must exit by itself, with code 0, not wait to be killed
        env = {**os.environ, "FOLIOLIB_DATA": tempfile.mkdtemp(dir=TMP), "FOLIOLIB_HOST": "127.0.0.1"}
        proc = subprocess.Popen([sys.executable, str(Path(main.__file__)), "serve", "--port", "0"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            self.assertIn("ready", proc.stdout.readline())
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=5), 0)
            self.assertIn("stopped", proc.stdout.read())
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth.set_password("admin", "a-long-password")
        auth._fails.clear()
        engine.refresh = lambda *a, **k: []                              # never any network in tests
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, headers=None, origin=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if origin and method == "POST":
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def cookie(self):
        st, hd, _ = self.req("POST", "/login", urllib.parse.urlencode({"user": "admin", "password": "a-long-password"}),
                             {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(st, 303)
        return {"Cookie": hd["Set-Cookie"].split(";")[0]}

    def test_demo_blocks_import_until_wiped(self):
        demo.load(store.connect())
        ck = self.cookie()
        st, _, body = self.req("POST", "/api/upload", ACCOUNT.encode(), {**ck, "Content-Type": "application/octet-stream"})
        self.assertEqual(st, 400)
        self.assertIn("Demo data is loaded", json.loads(body)["error"])
        self.assertEqual(self.req("POST", "/api/wipe", json.dumps({"confirm": "WIPE"}), {**ck, "Content-Type": "application/json"})[0], 200)
        self.assertEqual(store.meta_get(store.connect(), "demo"), "")

    def test_page_requires_sign_in(self):
        st, hd, _ = self.req("GET", "/")
        self.assertEqual((st, hd["Location"]), (303, "/login"))
        self.assertEqual(self.req("GET", "/api/data")[0], 401)
        self.assertEqual(self.req("GET", "/static/app.js")[0], 303)
        self.assertEqual(self.req("GET", "/healthz")[0], 200)

    def test_sign_in_and_headers(self):
        st, hd, _ = self.req("POST", "/login", urllib.parse.urlencode({"user": "admin", "password": "a-long-password"}),
                             {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(st, 303)
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, hd["Set-Cookie"])
        self.assertIn("script-src 'self'", hd["Content-Security-Policy"])
        self.assertEqual(self.req("POST", "/login", "user=admin&password=wrong", {"Content-Type": "application/x-www-form-urlencoded"})[0], 401)
        auth._fails.clear()

    def test_post_from_another_site_refused(self):
        ck = self.cookie()
        for site in ("cross-site", "same-site", "none"):
            self.assertEqual(self.req("POST", "/api/wipe", json.dumps({"confirm": "WIPE"}), {**ck, "Sec-Fetch-Site": site})[0], 403)
        self.assertEqual(self.req("POST", "/api/wipe", "{}", {**ck, "Sec-Fetch-Site": "same-origin"}, origin=False)[0], 400)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)    # Origin from another site, without Sec-Fetch-Site
        c.request("POST", "/api/wipe", "{}", {**ck, "Origin": "https://mal.example"})
        self.assertEqual(c.getresponse().status, 403)

    def test_post_without_origin_refused(self):
        self.assertEqual(self.req("POST", "/login", "user=a&password=b", origin=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/wipe", "{}", self.cookie(), origin=False)[0], 403)

    def test_import_then_data(self):
        ck = self.cookie()
        st, _, body = self.req("POST", "/api/upload", TRANS.encode(), {**ck, "X-Filename": "Transactions.csv"})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["new"], 5)
        st, _, body = self.req("POST", "/api/upload", b"n'importe quoi", ck)
        self.assertEqual(st, 400)
        st, _, body = self.req("GET", "/api/data", headers=ck)
        d = json.loads(body)
        self.assertEqual(len(d["positions"]), 2)
        self.assertFalse(d["empty"])
        self.assertEqual(self.req("GET", "/", headers=ck)[0], 200)

    def test_wipe_requires_confirmation(self):
        ck = self.cookie()
        self.assertEqual(self.req("POST", "/api/wipe", "{}", ck)[0], 400)

    def test_methods_and_paths(self):
        ck = self.cookie()
        self.assertEqual(self.req("PUT", "/api/data", "x", ck)[0], 405)
        self.assertEqual(self.req("GET", "/static/../auth.py", headers=ck)[0], 404)
        self.assertEqual(self.req("GET", "/static/%2e%2e/auth.py", headers=ck)[0], 404)
        try:                                                             # too large: refusal (413) or a clean cut before the end of the upload
            self.assertEqual(self.req("POST", "/api/upload", b"x" * (9 * 1024 * 1024), ck)[0], 413)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    unittest.main(verbosity=1)
