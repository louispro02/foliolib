# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - unreleased

First public release. Replace "unreleased" with the release date when tagging.

### Added

- **Import** of DEGIRO exports (Transactions, Account, Portfolio) and Fortuneo exports (operations history, cash account) by
  drag and drop, in their French-language form. Records are de-duplicated by a SHA-256 of their content, so overlapping
  exports never count anything twice. Raw files are kept, so a parser fix re-reads everything without a new upload.
- **Parser request form** on GitHub: asks for an anonymized sample of a broker's export, with the rules to anonymize it, so
  that new parsers start from real file formats without exposing anyone's data.
- **Modular parsers**: one module per broker in `app/parsers/`, discovered automatically. A new broker needs a parser and no
  other change. A tested worked example and a step-by-step guide are in `CONTRIBUTING.md`.
- **Generic CSV import**: a documented format (`docs/generic-csv.md`) that any broker's data can be converted into, with
  comma or semicolon separators, clear per-row error messages, and a cash balance rebuilt from the activity when the file does
  not state one.
- **Positions and costs**: weighted-average cost with fees included, unrealized and realized gains, dividends net of
  withholding tax, cash balance, brokerage, currency-conversion and connection fees, financial transaction tax, an estimate
  of the latent tax, and a breakdown of where the gain comes from.
- **Performance and risk**: time-weighted return, internal rate of return, annualized volatility, Sharpe ratio (with its Lo
  (2002) standard error) and Sortino ratio, maximum drawdown and recovery, maximum run-up, 1-day 95% value at risk
  (parametric and historical), and a returns heatmap by month, quarter, half-year and year.
- **Benchmarks**: "same deposits, same days" comparison with six accumulating ETFs (MSCI World, S&P 500, Nasdaq-100,
  Emerging Markets, STOXX Europe 600, CAC 40) and with a savings-account assumption.
- **French wrappers**: PEA deposit ceiling and the date of its five-year mark.
- **Corporate actions**: splits, reverse splits and automatic share exchanges keep their cost basis without creating a gain
  or a loss.
- **Long-term projection** simulator with editable assumptions, computed in the browser.
- **Prices and rates** from Yahoo Finance, with Twelve Data as an optional fallback and ECB reference rates through
  Frankfurter. The sync stops at the first refusal and keeps the last known prices.
- **Demo mode** (`python main.py demo`): a deterministic, fully synthetic two-year portfolio that needs no network. It refuses
  to run on a database that already holds data, blocks importing real files until it is erased, and is erased completely
  by "Erase imported data".
- **Authentication**: scrypt-hashed password, HMAC-signed session cookie (`HttpOnly`, `Secure`, `SameSite=Strict`), login
  throttling, cross-site request protection and a strict Content-Security-Policy.
- **Docker**: multi-architecture image (amd64, arm64) running as a non-root user on a read-only filesystem with no Linux
  capabilities, a Compose file with a `/healthz` health check, and a clean shutdown on `SIGTERM`.
- **Continuous integration**: tests on Python 3.11, 3.12 and 3.13, Ruff, and a Docker build with a smoke test.
- **English and French interface**, chosen from the browser's language or with the EN | FR switch (also on the sign-in page).
  English is the source language and a language is one file (`app/i18n/`): a text without a translation shows in English.
- English documentation and code comments.

### Security

- No telemetry. Only ISINs and ticker symbols (prices) and currency codes with a date range (rates) leave the host; never a
  quantity or an amount.
- Database, uploaded files and password hash are created with mode `600`.

### Known limitations

- Only French-language DEGIRO and Fortuneo exports are recognized.
- Amounts are in euros; French-oriented assumptions (PEA ceiling, 30% flat tax, 3% savings reference) are constants in
  `app/engine.py`.
- Single-user; the login lockout after 5 failures applies to everyone. Data is not encrypted at rest.
- The `Secure` session cookie requires HTTPS or `localhost`.
- Price data relies on an unofficial Yahoo Finance endpoint.

[1.0.0]: https://github.com/louispro02/foliolib/releases/tag/v1.0.0
