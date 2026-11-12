# Portfolio Analytics

Daily, automated analytics for a Groww portfolio (stocks and mutual funds).

Twice every weekday the pipeline fetches holdings, prices and NAVs, computes the day's movement,
attributes each move to the market, its sector or the company itself, measures diversification
and risk, and writes a snapshot. A Claude scheduled task then researches the news behind the
moves and updates a private live dashboard.

**Read-only by design:** the code never places, modifies or cancels orders (a test enforces this).
It describes and explains the portfolio; it is not investment advice.

## How it works

| Time (IST) | What runs | Where |
| --- | --- | --- |
| 3:45 PM | `python -m portfolio.run --mode close` — stock holdings and prices | GitHub Actions |
| 4:00 PM | Research movers, write reasons, update dashboard | Claude scheduled task |
| 9:30 PM | `python -m portfolio.run --mode night` — adds mutual fund NAVs, diversification, risk | GitHub Actions |
| 10:00 PM | Fund moves, filings, upcoming events, outlook | Claude scheduled task |

## Data sources (all free)

| Data | Source |
| --- | --- |
| Stock holdings | Groww Trade API (free plan; holdings are not part of the paid Live Data plan) |
| Stock and index prices | Yahoo Finance via `yfinance` (end of day) |
| Mutual fund holdings | Monthly CAS PDF (CAMS / KFintech / MFCentral / CDSL), parsed with `casparser` |
| Mutual fund NAVs | AMFI daily NAV file; history from mfapi.in |
| News, filings, events | Claude's web research |

## Setup

1. **Groww:** activate the free Trading API plan and generate a TOTP token (Groww Cloud → API Keys).
2. **GitHub secrets** (Settings → Secrets and variables → Actions):
   - `GROWW_TOTP_TOKEN` — the TOTP token
   - `GROWW_TOTP_SECRET` — the TOTP secret (text beside the QR code)
   - `CAS_PASSWORD` — optional; only if you upload a password-protected CAS
3. **Your SIPs:** fill in `config/sip_schedule.yaml`.
4. **Your CAS:** upload the PDF to `data/cas/` (GitHub → Add file → Upload files). The next run imports it
   and deletes the PDF, keeping only fund names, ISINs, units and amounts.
5. Run once by hand: Actions → "Night run" → Run workflow.

## Monthly routine

Upload the latest CAS to `data/cas/`. Between statements, SIP units are projected from
`config/sip_schedule.yaml` and replaced by actual units when the new CAS is imported.

## Configuration

`config/settings.yaml` — benchmark, significant-move thresholds, diversification limits, scenarios, price source.
`config/sector_map.csv` — sector and market-cap bucket per NSE symbol. Stocks not listed are classified from
Yahoo Finance automatically; add a row to override.

Optional: `data/fund_portfolios/*.csv` with columns `fund_isin, stock_isin, stock_name, sector, weight_pct`
enables look-through exposure and fund overlap.

## Project layout

```
config/                 settings, SIP schedule, sector map
src/portfolio/
  ingest/               Groww, Yahoo prices, AMFI NAVs, CAS parser
  store/                DuckDB schema and helpers
  analytics/            movement, attribution, returns, risk, diversification
  run.py                entry point
data/
  portfolio.duckdb      history database
  snapshots/            <date>_<mode>.json, latest_<mode>.json
prompts/                instructions for Claude's research runs
tests/                  offline tests with generated sample data
```

## Development

```
pip install -e ".[dev]"
pytest -q
```
