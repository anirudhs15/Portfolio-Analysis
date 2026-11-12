# Dashboard

Live dashboard: https://claude.ai/artifact/NfPYz7qpinGdF6Jp9dyV3T

The page lives in the dashboard's store (`files/index.html`); `dashboard/index.html` in this repo is a copy.
Its data comes from these datasets, each an attached JSON file built by
`python -m portfolio.publish.dashboard_data` into `data/dashboard/<id>.json`:

summary, holdings, allocation, news, events, outlook, suggestions, scenarios, health

To refresh after a run:
1. Write `data/research/<date>.json` (see `data/research/2026-11-12.json` for the format).
2. Run `python -m portfolio.publish.dashboard_data`.
3. Upload each `data/dashboard/<id>.json` as an asset of the dashboard, then update `datasets/<id>`
   with the new `source.url`, `updated: {at, by}` and an `edit` stamp.
