# The FolioLib generic CSV

A single, documented CSV format that data from **any** broker can be converted into. Use it when your broker has no dedicated
parser yet, when it only gives you PDF statements, or simply when you track an account by hand.

Everything below is exercised by the test suite, including the example at the end.

## In three steps

1. Create a file whose **first line is exactly this** (copy it):

```text
date,type,account,isin,name,quantity,price,amount,currency,fees,note
```

2. Add **one row per event**: a deposit, a purchase, a dividend... (the types are listed below).
3. Drop the file on the page, like any other export. Dropping a file again, or a file that overlaps it, never counts a row twice.

## Columns

All eleven columns must be present in the header, but any cell may be left empty unless a row type needs it. Columns can come
in any order, and extra columns are ignored.

| Column | Meaning |
| --- | --- |
| `date` | `YYYY-MM-DD`. Required on every row |
| `type` | What happened: see the table below. Case and spaces do not matter (`Dividend Tax` works) |
| `account` | Free text naming the account (`Brokerage`, `PEA`...). Rows with the same name belong to the same account; one file may hold several accounts. Empty means `Portfolio` |
| `isin` | The 12-character ISIN of the security. Needed for buys, sells, dividends and exchanges, because it is how prices are found |
| `name` | The security's name. Optional (the ISIN is used if it is empty), except for exchanges |
| `quantity` | Number of shares, **always positive**: the type says whether they come or go |
| `price` | Price per share. Optional when you give `amount` |
| `amount` | The money, **always positive** (except `cash_balance`): the type says which way it goes |
| `currency` | Three-letter code. Empty means `EUR`. Only dividends, taxes and fees may use another currency |
| `fees` | Brokerage fee of a buy or a sell, **on top of** `amount` |
| `note` | Anything you want to remember. Never read |

## Row types

| `type` | What it means | Needs | Effect |
| --- | --- | --- | --- |
| `deposit` | Money you paid into the account | `date`, `amount` | Counted as money invested |
| `withdrawal` | Money you took out | `date`, `amount` | Subtracted from money invested |
| `buy` | A purchase | `date`, `isin`, `quantity`, and `amount` **or** `price`; `fees` optional | Adds shares; cash goes down by the amount plus the fees |
| `sell` | A sale | the same as `buy` | Removes shares at their average cost and records a realized gain; cash goes up by the amount minus the fees |
| `dividend` | A gross dividend received | `date`, `isin`, `amount` | Counted as dividends |
| `dividend_tax` | Tax withheld on a dividend | `date`, `isin`, `amount` | Subtracted from dividends and counted as withholding tax |
| `fee` | Any other account fee | `date`, `amount` | Lowers cash; shows in the "Other" line of the gain breakdown |
| `transaction_tax` | A financial transaction tax | `date`, `amount` | Like `fee`, but counted as "Financial transaction tax" |
| `cash_balance` | Your cash balance on that date | `date`, `amount` | Replaces the rebuilt balance (see below). The most recent date wins |
| `exchange_out`, `exchange_in` | The two legs of a split, a reverse split or a share exchange | `date`, `isin`, `quantity`, and the **same `name` on both legs** | Shares move to the new line **keeping their cost basis**, so no gain or loss is invented |

## Rules to know

- **Euros.** Deposits, withdrawals, buys, sells and balances must be in euros: use the euro amount your broker charged or
  credited. Dividends, dividend taxes and fees may be in another currency; they are converted at the ECB rate of their date.
- **Signs.** Write every amount and quantity as a positive number. The `type` carries the direction.
- **Order.** List rows in chronological order. Rows of the same day are processed in the order of the file, and the order
  matters: selling after a purchase of the same day uses a different average cost than selling before it.
- **Cash.** FolioLib needs your cash balance, otherwise money that is deposited but not yet invested looks like a loss.
  Without a `cash_balance` row it is **rebuilt from the file** (deposits, withdrawals, buys, sells, euro dividends, taxes,
  fees). That is only right if the file holds the account's **whole history**, and it leaves out dividends in other
  currencies. If your file is partial, or you have such dividends, add a `cash_balance` row with the real balance. If the
  rebuilt balance would be negative (deposits are missing), no balance is recorded rather than a wrong one.
- **Several files.** Import the oldest first, and put a `cash_balance` row in the last one: a balance rebuilt from a partial
  file would be wrong, and a newer file's balance replaces an older one's.
- **Adding rows.** Append them to your file and drop it again: rows already known are ignored, only the new ones count.
- **Correcting a row.** A row is recognized by its **content**, so a corrected row is added **next to** the wrong one, which
  stays. To fix a mistake, use **Erase imported data** on the page (it erases everything you imported, not just this file)
  and import your corrected files again.

## Numbers and dates in a spreadsheet

- **Dates** must read `2025-03-14`. Spreadsheets like to turn them into `14/03/2025`: format the column as text, or with the
  custom format `yyyy-mm-dd`, before saving.
- **Decimals.** A comma-separated file takes a **dot** as the decimal separator and **no thousands separator**: `1250.5`, not
  `1,250.50`. A **semicolon-separated** file (what a French spreadsheet saves as "CSV") takes a decimal comma: `1250,5`.
- **Encoding.** UTF-8 (with or without a byte-order mark) or Latin-1, which covers what Excel produces.

## When a row is rejected

The whole file is refused with a message that names the rows, up to five at a time. Nothing is imported until it is fixed.

| Message | Cause and fix |
| --- | --- |
| `date '...' must be written YYYY-MM-DD` | A date in another format |
| `unknown type '...'` | A `type` that is not in the table above |
| `... is not a number` | A number with a thousands separator, a currency symbol or a comma in a comma-separated file. Use a dot, or put the number in quotes |
| `currency '...' is not a 3-letter code ... probably split in two columns` | A number written with a comma, without quotes, shifted every column after it |
| `... must be in euros` | A deposit, withdrawal, buy, sell or balance in another currency: convert it |
| `isin '...' must be 12 letters or digits` | A missing or malformed ISIN on a row that needs one |
| `quantity must be greater than zero` | A quantity of `0` |
| `needs an amount, or a price and a quantity` | A buy or a sell with neither |
| `an exchange needs the same name on both legs` | An `exchange_in` or `exchange_out` without a `name` |
| `no usable row in this file` | Only the header was found |

## What it does not cover

Interest, options, futures, bonds with accrued interest, cryptocurrencies, and short positions. Foreign-currency purchases
must be entered at their euro amount.

## A complete example

This invented account shows every kind of row. It is the file `docs/examples/generic-example.csv`, which the tests load and
check figure by figure:

```csv
date,type,account,isin,name,quantity,price,amount,currency,fees,note
2025-01-02,deposit,Brokerage,,,,,2000,EUR,,First deposit
2025-01-03,buy,Brokerage,IE0000000001,WORLD ETF,10,80,,EUR,1.5,
2025-01-03,buy,Brokerage,FR0000000003,BLUE CHIP SA,20,45,,EUR,1.5,
2025-03-14,dividend,Brokerage,FR0000000003,BLUE CHIP SA,,,9,EUR,,Gross dividend
2025-03-14,dividend_tax,Brokerage,FR0000000003,BLUE CHIP SA,,,2.7,EUR,,Withholding tax
2025-04-01,fee,Brokerage,,,,,2.5,EUR,,Exchange connection fee
2025-06-02,sell,Brokerage,IE0000000001,WORLD ETF,4,90,,EUR,1.5,
2025-09-01,exchange_out,Brokerage,FR0000000003,BLUE CHIP SA,20,,,,,Reverse split 5 for 1: old shares leave
2025-09-01,exchange_in,Brokerage,FR0000000030,BLUE CHIP SA,4,,,,,Reverse split 5 for 1: new shares arrive
```

It describes a brokerage account where you deposit 2,000 EUR, buy 10 shares of a world ETF and 20 of a French stock, receive
a dividend with its withholding tax, pay an account fee, sell 4 ETF shares, and the French stock undergoes a 5-for-1 reverse
split (20 old shares become 4 new ones under a new ISIN). With the ETF quoted at 95 and the new shares at 250, FolioLib shows:

- a cash balance of **659.30 EUR** (rebuilt from the rows) and a portfolio value of **2,229.30 EUR**;
- a realized gain of **37.90 EUR** on the sale;
- the 4 new shares keeping the **901.50 EUR** cost of the 20 old ones.
