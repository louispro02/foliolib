# Contributing to FolioLib

Thank you for helping. This page explains how to set up, what the rules are, and how to add support for your broker, which
is the most useful contribution.

## Ground rules

- **No runtime dependency.** FolioLib imports the Python standard library and nothing else. Please keep it that way: a
  contribution that needs a third-party package will be declined, whatever its merit.
- **No real data, ever.** Test fixtures, screenshots, issues and pull requests must contain only synthetic data: invent the
  ISINs, the names and the amounts. A real broker export contains account identifiers, so **do not attach one to an issue**.
  Make a copy and replace every identifier before sharing anything.
- **Explain the numbers.** A new figure on the page comes with a plain-language tooltip (`GLOSS` in `app/static/app.js`).
- **English everywhere**: the interface, messages, comments and documentation. The only French you will find is the text
  that matches French-language broker exports, which must stay as the broker writes it.

## Set up and check your work

There is nothing to install to run or test the code. You need Python 3.11 or newer.

```bash
git clone https://github.com/louispro02/foliolib.git
cd foliolib

python3 -I -m unittest discover tests -v        # the test suite (standard library only)

pip install ruff==0.17.5                        # the linter used by CI (in a virtual environment, ideally)
ruff check app tests docs
```

CI runs exactly these two commands on Python 3.11, 3.12 and 3.13, then builds the Docker image. Run both before you open a pull request.

To try your change in a browser with synthetic data, keeping it on your own machine:

```bash
export FOLIOLIB_DATA=/tmp/foliolib-dev FOLIOLIB_HOST=127.0.0.1
cd app
python3 main.py demo        # synthetic portfolio; needs an empty data directory
python3 main.py passwd      # choose any login for this throwaway directory
python3 main.py serve --port 8090
```

## Project map

| Path | Role |
| --- | --- |
| `app/main.py` | HTTP server, routes and command line (`serve`, `passwd`, `report`, `import`, `demo`) |
| `app/parsers/` | One module per broker: turns a CSV export into records. **Where you will work most** |
| `app/ledger.py` | Replays the records: positions, average cost, deposits, dividends, fees |
| `app/engine.py` | Price synchronization and everything the page displays |
| `app/perf.py` | Time-weighted return, volatility, Sharpe, Sortino, drawdown, value at risk |
| `app/quotes.py` | Price and exchange-rate clients (Yahoo Finance, Twelve Data, Frankfurter) |
| `app/store.py` | SQLite storage and parser migration |
| `app/auth.py` | Password hashing, signed session cookie, login throttling |
| `app/demo.py` | The synthetic demo portfolio |
| `app/static/` | The page: `index.html`, `app.js`, CSS and self-hosted fonts |
| `docs/examples/` | The tested broker example used below |

## Add support for your broker

Not a programmer, or your broker only gives PDF statements? You do not need a parser: convert your data to the
[generic CSV](docs/generic-csv.md) and drop it on the page. A parser is for **native** support of a broker's own export.

A broker is supported by **one file** in `app/parsers/`. It is found automatically: nothing needs to be registered, and
the calculation core and the page need no change. The tests prove it: one drops the example below into a copy of the
application and checks that it is discovered, another computes a whole portfolio from its records.

1. **Get a sample export** and make a synthetic copy of it: fake ISINs, round numbers, no account identifier.
2. **Write the parser.** A parser is a subclass of `BaseParser` with a unique `kind`, a `detect()` that recognizes the file
   from its header line, and a `parse()` that turns the content into records. This is the complete, tested example for a
   made-up broker (`docs/examples/example_broker.py`); copy it to `app/parsers/<yourbroker>.py` and adapt it:

```python
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
```

3. **Emit the record types the core understands.** The field `broker` says which account a record belongs to. The full
   contract is at the top of `app/parsers/base.py`; in short:

| `type` | Required fields | Notes |
| --- | --- | --- |
| `deposit`, `withdrawal` | `date`, `amount`, `ccy` | `amount` is positive |
| `trade` | `date`, `isin`, `name`, `qty`, `amount_eur` | `qty` is `+` for a purchase and `-` for a sale; `amount_eur` is the cash moved (negative for a purchase, fees included); optional: `time`, `price`, `price_ccy`, `fees_eur`, `autofx_eur`, `corporate` (true for a split or an exchange, where shares move without cash) |
| `dividend`, `dividend_tax` | `date`, `isin`, `name`, `amount`, `ccy` | a tax is negative |
| `fee` | `date`, `amount`, `ccy` | negative; optional `kind`: `"connexion"` or `"ttf"` to count it under that heading |
| `snapshot_cash` | `value_eur` | the cash balance **now** (no date; the last one loaded wins) |

4. **Add tests** to `tests/test_foliolib.py`, with a synthetic fixture: `detect()` recognizes the header, `parse()` returns
   the expected records, and (copying `NewBroker.test_a_new_broker_is_computed_under_its_own_account`) a portfolio built from
   them has the right invested amount, positions and gain.
5. **Optional polish.** Give the broker a display name in `ledger.ACCOUNTS` and `ledger.SHORT_NAMES` (otherwise its key is
   shown, title-cased), and a label for each file type in `KINDS` in `app/static/app.js` (otherwise the raw `kind` is shown).

### Things that trip people up

- **Emit the cash balance.** If your export has no balance, rebuild it from the activity as the example does. Without a
  `snapshot_cash` record, money that is deposited but not yet invested is not counted and the gain looks smaller than it is.
- **Signs.** Cash that leaves the account is negative. A sale has a negative `qty` and a positive `amount_eur`.
- **Numbers.** `fr_num()` reads French numbers, where `,` is the decimal separator and spaces group thousands. For an English
  export (`1,234.50`), do not use it: parse with `float()` after removing the grouping.
- **The header.** `detect()` receives the first line **lowercased**, with any byte-order mark removed. Match enough of it that
  no other parser claims the same file (a test checks that every fixture is claimed by exactly one parser).
- **Be deterministic.** The same file must always give the same records: a record's identity, used to ignore lines you
  already imported, is a hash of its content. Never put a timestamp or a random value in a record.
- **Skip junk, raise on garbage.** Ignore blank or malformed lines. Raise `ValueError` only when the file is unusable.
- **Encoding.** Files are decoded as UTF-8 (with or without BOM), then as Latin-1. Do not decode again.
- **One class per file type.** A broker with three kinds of export has three classes: see `app/parsers/degiro.py`.

## When you change what a parser outputs

Imported files are kept, so a parser fix can re-read everything without asking the user to upload again. For that to
happen, **bump the parser version** whenever the records produced for an existing file type change:

```python
# app/parsers/__init__.py
PARSER_VERSION = 3                                    # was 2
AFFECTED = {2: ("degiro_transactions", "degiro_account"),
            3: ("degiro_account",)}                 # the file types whose records changed in version 3
```

On the next start, `store.migrate()` discards the records of the affected file types and re-reads their preserved files. A
file that was not preserved cannot be re-read: the page then asks the user to upload it again, and says which one. If you
forget to bump the version, existing users keep the old, wrong records.

Adding a **new** file type does not need a bump: nothing was imported with it before.

## Pull requests

- Keep each one focused, and say what you changed and why.
- Tests and `ruff check app tests docs` pass.
- No real data anywhere in the diff, the fixtures or the screenshots.
- New behaviour has a test; a bug fix has a test that fails without the fix.
- No new dependency.

## Security issues

Please do not open a public issue for a vulnerability. Report it privately through the repository's **Security** tab.
