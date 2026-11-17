# Scheduled update: Portfolio Pulse

Runs on weekdays at about 3:41 PM IST (mode `close`) and 9:43 PM IST (mode `night`).
Each run refreshes the data, researches the day, and republishes the Portfolio Pulse app.

- Repository: `anirudhs15/Portfolio-Analysis` (GitHub)
- App: https://claude.ai/artifact/BgVcYZTRyt8MrAdUW5pSuU (slug `567f06e3-c1ca-4114-bd99-36a6c7b126df`)

## Steps

1. **Get the repo.** If it isn't in this session, attach it with `add_repo` (owner `anirudhs15`, repo
   `Portfolio-Analysis`, access `push`) and clone it. `pip install -e . --break-system-packages`.

2. **Run the pipeline on GitHub** (GitHub's own schedule is off because it ran hours late):
   `gh api -X POST repos/anirudhs15/Portfolio-Analysis/actions/workflows/<mode>.yml/dispatches -f ref=main`
   (`close.yml` or `night.yml`). Wait for that run to finish (poll
   `actions/workflows/<mode>.yml/runs?per_page=1` every 15 s, up to 20 min), then `git pull`.
   If it failed, read its log, note the cause, and continue with the latest snapshot that exists.
   Night mode: if the log or `health.notes` says AMFI NAVs weren't out yet, wait 20 minutes and dispatch once more.

3. **Check the snapshot**: `data/snapshots/latest_<mode>.json`. If `run.market_open_today` is false
   (holiday), skip research: write `data/research/<date>.json` with a one-line `market_wrap` saying the
   market was closed, then go to step 5.

4. **Research the day** and write `data/research/<date>.json` (date = `run.date`), in the format of
   `data/research/2026-11-12.json`:
   - `market_wrap`: 2–3 sentences on why the Nifty moved today, from a market close report you opened, with
     its link. If none is published yet, describe the day from the snapshot's own numbers and leave the
     source empty.
   - `reasons`: one per holding in `movers.to_explain` (match on its `symbol`). Use its `attribution.driver`
     to aim the search: company news and NSE/BSE filings for stock-specific moves, the sector for sector moves,
     the commodity for silver/gold. At most two sentences, with a source. If nothing credible explains it,
     say "No company news found today" and give context; never guess.
   - `news`: only new, material items from the last day or two (results, orders, rating changes, filings),
     each with `match` (symbols or AMFI codes), impact and source. Earlier news carries over automatically.
   - Night mode only: refresh `events` (next 30–60 days: RBI, results dates, record dates) when the list is
     short or stale, and `outlook` themes if something important changed.
   - When a company reports results or analysts change ratings, update its entry in
     `data/research/profiles.json` (`up`, `down`, `near`, `far`, `analyst` with source and date).
   Rules: cite only pages you opened; paraphrase; no buy/sell calls or price predictions of your own.

5. **Build**: `python -m portfolio.publish.dashboard_data --mode <mode>`. It prints the snapshot date
   and whether research was found. Check those match today.

6. **Publish the app** with `publish_files`: `get_artifact` for the current version, run
   `python3 scripts_build_app.py`, then publish to slug `567f06e3-c1ca-4114-bd99-36a6c7b126df` with
   `base_version` = that version and files `index.html` ← `app/build/index.html` and
   `data/<name>.json` ← `data/app_docs/<name>.json` for summary, holdings, allocation, news, events,
   suggestions, scenarios, health, profiles. Label it like "Close 17 Nov".

7. **Save**: commit `data/research`, `data/dashboard`, `data/app_docs` and any profile changes, and push.

8. **Notify** (push notification, if available): portfolio change today in ₹ and %, Nifty change, and the
   biggest mover with its reason in a few words. If something failed, say what.
