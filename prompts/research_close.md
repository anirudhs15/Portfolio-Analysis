# 4 PM research run (stocks)

You are updating a personal portfolio dashboard after the Indian market close.

## Inputs
- Repository: `anirudhs15/Portfolio-Analysis`. Clone it and read `data/snapshots/latest_close.json`.
- If `run.date` in that file is not today's date (IST), wait 5 minutes and pull again, up to 20 minutes.
  If it is still missing, update the dashboard's Data health section to say "Close data delayed" and stop.
- If `run.market_open_today` is false, write a one-line note that markets were closed and stop.

## Research
1. **Market wrap (2-3 sentences):** why Nifty moved today. Search for today's Indian market close report.
   Cover the main driver (FII flows, global cues, RBI, crude, rupee, a sector) with the figures the sources give.
2. **For every holding in `movers.to_explain`:**
   - Use its `attribution.driver`:
     - `stock_specific` → search company news from the last 24 hours and NSE/BSE announcements
       (results, orders, management changes, rating changes, block deals, regulatory action).
     - `sector` → find what moved the sector index named in `attribution.sector_index`.
     - `market` → link to the market wrap; no separate search needed unless the move is far larger than beta implies.
   - Write a reason of at most two sentences, with one source link, and a tag: positive / negative / neutral.
   - If nothing credible explains the move, say "No clear cause found in today's news" - never guess.
3. **Other holdings:** one quick search each for major news today (results, big announcements). Only add items that matter.

## Rules
- Use only sources you actually opened; prefer exchange filings, company releases, and established financial news.
- Paraphrase; never paste article text.
- No price predictions, no buy/sell suggestions.

## Output
Write into the dashboard's data store (`ArtifactData`, dashboard URL in `prompts/dashboard_url.txt`):
- `reasons/<isin>`: {date, driver, reason, sentiment, source_url}
- `news/<date>-<n>`: {date, isin, headline, summary, sentiment, category, source_url}
- `wrap/<date>-close`: {date, text, sources}
- `snapshot/latest_close`: the snapshot JSON's summary, holdings, movers and indices.

Then send a push notification: portfolio day change (₹ and %), Nifty change, and the biggest mover with its reason in a few words.
