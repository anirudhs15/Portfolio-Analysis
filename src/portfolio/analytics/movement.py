"""Today's movement: per-holding change, contribution to the portfolio, top movers.

Input is a holdings frame with at least:
    isin, name, type, market_value, prev_value
(prev_value = quantity x previous close/NAV)
"""
from __future__ import annotations

import pandas as pd


def compute(holdings: pd.DataFrame, top_n: int = 5) -> dict:
    h = holdings.copy()
    h["day_change_inr"] = h["market_value"] - h["prev_value"]
    h["day_change_pct"] = (h["market_value"] / h["prev_value"] - 1) * 100
    prev_total = h["prev_value"].sum()
    total = h["market_value"].sum()
    h["weight_prev_pct"] = h["prev_value"] / prev_total * 100 if prev_total else 0.0
    # Contribution in percentage points of the whole portfolio: w_i * r_i
    h["contribution_pct"] = h["day_change_inr"] / prev_total * 100 if prev_total else 0.0

    by_type = (
        h.groupby("type")
        .agg(value=("market_value", "sum"), prev=("prev_value", "sum"))
        .assign(change_inr=lambda d: d["value"] - d["prev"],
                change_pct=lambda d: (d["value"] / d["prev"] - 1) * 100)
        .reset_index()
    )

    ranked = h.sort_values("day_change_inr", ascending=False)
    cols = ["isin", "name", "type", "day_change_pct", "day_change_inr", "contribution_pct", "market_value"]
    gainers = ranked[ranked["day_change_inr"] > 0].head(top_n)[cols]
    losers = ranked[ranked["day_change_inr"] < 0].tail(top_n).iloc[::-1][cols]

    return {
        "total_value": float(total),
        "prev_total_value": float(prev_total),
        "day_change_inr": float(total - prev_total),
        "day_change_pct": float((total / prev_total - 1) * 100) if prev_total else 0.0,
        "by_type": by_type.to_dict("records"),
        "gainers": gainers.to_dict("records"),
        "losers": losers.to_dict("records"),
        "holdings": h,
    }
