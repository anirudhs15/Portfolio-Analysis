# 10 PM research run (full day)

You are updating a personal portfolio dashboard after mutual fund NAVs are published.

## Inputs
- Repository: `anirudhs15/Portfolio-Analysis`. Clone it and read `data/snapshots/latest_night.json`.
- If `run.date` is not today (IST), wait 5 minutes and pull again, up to 20 minutes; if still missing,
  mark "Night data delayed" in Data health and stop.
- Check `health.notes` and surface any problems in the Data health section.

## Research
1. **Mutual funds that moved ≥1%:** explain using the fund's category and the day's market/sector moves
   (e.g. a small-cap fund on a day small caps fell). Keep to one sentence each.
2. **Today's filings and results:** for each stock holding, check NSE/BSE announcements filed today.
3. **Upcoming events, next 30 days** (refresh weekly on Mondays, or when missing):
   results dates, dividend record dates, bonus/split dates, AGMs for each stock;
   RBI policy dates, Union Budget, major data releases (CPI, GDP) for the market.
4. **Analyst views:** only when a rating or target changed in the last week; attribute to the broker.
5. **What to know (3-6 items):** short notes connecting news to the holdings, e.g. "Results on Friday;
   last quarter's margins fell". Use the `risk.scenarios` numbers for one item on market sensitivity.
6. **Diversification commentary (2-4 sentences):** read `diversification.flags` and `.suggestions`, and explain
   them in plain language. Suggestions stay at the category level (asset class, market cap, sector);
   never name specific securities to buy.

## Rules
- Use only sources you actually opened; paraphrase; cite each item.
- No price predictions, no buy/sell calls. Analyst targets are reported as the broker's view, not yours.

## Output
Write into the dashboard's data store (`ArtifactData`, dashboard URL in `prompts/dashboard_url.txt`):
- `snapshot/latest_night`: summary, holdings, movers, indices, risk, diversification, history.
- `events/<date>-<n>`, `outlook/<date>`, `reasons/<isin>` for funds, `news/...` for filings.

Then send a push notification with the full-day summary: value, day change, total gain, one item to know.
