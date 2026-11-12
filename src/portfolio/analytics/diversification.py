"""Diversification: allocation, look-through exposure, concentration, fund overlap, flags.

holdings frame columns used:
    isin, name, type ('stock'|'mf'), market_value, sector, market_cap_bucket,
    asset_class, fund_category
constituents frame (optional; from AMC monthly disclosures):
    fund_isin, stock_isin, stock_name, sector, weight_pct
"""
from __future__ import annotations

from itertools import combinations

import pandas as pd


def _alloc(df: pd.DataFrame, key: str, total: float) -> list[dict]:
    g = df.assign(**{key: df[key].fillna("Unclassified")}).groupby(key)["market_value"].sum()
    g = g.sort_values(ascending=False)
    return [{"name": k, "value": float(v), "pct": round(float(v) / total * 100, 2)} for k, v in g.items()]


def look_through(holdings: pd.DataFrame, constituents: pd.DataFrame | None) -> pd.DataFrame:
    """Combines direct stocks with each fund's stock weights x money in the fund.

    Funds without disclosure data stay as a single line (the fund itself)."""
    rows = []
    for _, h in holdings[holdings["type"] == "stock"].iterrows():
        rows.append({"key": h["isin"], "name": h["name"], "sector": h.get("sector"),
                     "value": h["market_value"], "via": "direct"})
    cons = constituents if constituents is not None else pd.DataFrame()
    for _, f in holdings[holdings["type"] == "mf"].iterrows():
        parts = cons[cons["fund_isin"] == f["isin"]] if len(cons) else cons
        if len(parts):
            covered = parts["weight_pct"].sum()
            for _, p in parts.iterrows():
                rows.append({"key": p["stock_isin"], "name": p["stock_name"], "sector": p.get("sector"),
                             "value": f["market_value"] * p["weight_pct"] / 100, "via": f["name"]})
            rest = max(0.0, 100 - covered)
            if rest > 0.5:
                rows.append({"key": f"{f['isin']}:other", "name": f"{f['name']} (cash & other)",
                             "sector": "Cash & Other", "value": f["market_value"] * rest / 100, "via": f["name"]})
        else:
            rows.append({"key": f["isin"], "name": f["name"], "sector": f.get("sector") or f.get("fund_category"),
                         "value": f["market_value"], "via": "fund (no breakdown yet)"})
    lt = pd.DataFrame(rows)
    if lt.empty:
        return lt
    agg = (lt.groupby("key")
             .agg(name=("name", "first"), sector=("sector", "first"), value=("value", "sum"),
                  via=("via", lambda s: sorted(set(s))))
             .reset_index())
    agg["pct"] = agg["value"] / agg["value"].sum() * 100
    return agg.sort_values("value", ascending=False)


def hhi(weights_pct: pd.Series) -> float:
    w = weights_pct / 100
    return float((w ** 2).sum())


def fund_overlap(constituents: pd.DataFrame, fund_names: dict[str, str]) -> list[dict]:
    """Overlap(A,B) = sum over shared stocks of min(weight in A, weight in B)."""
    out = []
    if constituents is None or constituents.empty:
        return out
    by_fund = {f: g.set_index("stock_isin")["weight_pct"] for f, g in constituents.groupby("fund_isin")}
    for a, b in combinations(sorted(by_fund), 2):
        shared = by_fund[a].index.intersection(by_fund[b].index)
        ov = float(pd.concat([by_fund[a][shared], by_fund[b][shared]], axis=1).min(axis=1).sum())
        out.append({"fund_a": fund_names.get(a, a), "fund_b": fund_names.get(b, b),
                    "overlap_pct": round(ov, 1), "shared_stocks": int(len(shared))})
    return sorted(out, key=lambda r: -r["overlap_pct"])


def analyse(holdings: pd.DataFrame, constituents: pd.DataFrame | None, limits: dict) -> dict:
    total = float(holdings["market_value"].sum())
    h = holdings.copy()
    h["asset_class"] = h["asset_class"].where(h["asset_class"].notna(), h["type"].map({"stock": "Equity"}))
    h["holding_type"] = h["type"].map({"stock": "Direct stocks", "mf": "Mutual funds"})

    lt = look_through(h, constituents)
    top10 = lt.head(10)
    n_eff = 1 / hhi(lt["pct"]) if len(lt) else 0
    top5_pct = float(lt.head(5)["pct"].sum()) if len(lt) else 0.0

    # Sector view: direct stocks by sector + funds via look-through when available
    sector_alloc = (lt.assign(sector=lt["sector"].fillna("Unclassified"))
                      .groupby("sector")["value"].sum().sort_values(ascending=False)) if len(lt) else pd.Series()
    sectors = [{"name": k, "value": float(v), "pct": round(float(v) / total * 100, 2)} for k, v in sector_alloc.items()]

    names = dict(zip(h["isin"], h["name"]))
    overlap = fund_overlap(constituents, names) if constituents is not None else []

    flags, suggestions = [], []
    for _, r in lt.iterrows():
        if r["pct"] > limits.get("max_single_stock_pct", 10) and not str(r["key"]).endswith(":other") \
                and "fund (no breakdown yet)" not in r["via"]:
            flags.append(f"{r['name']} is {r['pct']:.1f}% of the portfolio (limit {limits.get('max_single_stock_pct', 10)}%).")
    for s in sectors:
        if s["name"] not in ("Unclassified", "Cash & Other") and s["pct"] > limits.get("max_sector_pct", 30) \
                and not s["name"].startswith("Equity Scheme"):
            flags.append(f"{s['name']} is {s['pct']:.1f}% of the portfolio (limit {limits.get('max_sector_pct', 30)}%).")
    for o in overlap:
        if o["overlap_pct"] > limits.get("max_fund_overlap_pct", 50):
            flags.append(f"{o['fund_a']} and {o['fund_b']} overlap {o['overlap_pct']:.0f}%.")
            suggestions.append(f"{o['fund_a']} and {o['fund_b']} hold largely the same stocks; "
                               "keeping both adds little diversification.")
    if top5_pct > limits.get("max_top5_pct", 50):
        flags.append(f"Top 5 positions make up {top5_pct:.0f}% of the portfolio.")

    asset = _alloc(h, "asset_class", total)
    asset_names = {a["name"] for a in asset}
    if "Debt" not in asset_names and "Hybrid" not in asset_names:
        suggestions.append("No debt or hybrid allocation: the whole portfolio moves with equity markets.")
    # Market-cap split only makes sense for equity; shown as a share of the equity portion.
    eq = h[h["asset_class"] == "Equity"]
    eq_total = float(eq["market_value"].sum())
    caps = _alloc(eq, "market_cap_bucket", eq_total) if eq_total else []
    cap_names = {c["name"] for c in caps}
    if not cap_names & {"Mid", "Small", "Multi", "Large & Mid"}:
        suggestions.append("No mid- or small-cap exposure.")
    if not cap_names & {"Large", "Multi", "Large & Mid"}:
        suggestions.append("No large-cap exposure: the portfolio may be more volatile than the market.")
    if n_eff and n_eff < 8:
        suggestions.append(f"Effective number of holdings is {n_eff:.1f}; returns depend heavily on a few positions.")
    no_breakdown = [r["name"] for _, r in lt.iterrows() if "fund (no breakdown yet)" in r["via"]]

    return {
        "total_value": total,
        "by_holding_type": _alloc(h, "holding_type", total),
        "by_asset_class": asset,
        "by_market_cap": caps,
        "by_fund_category": _alloc(h[h["type"] == "mf"], "fund_category", total) if (h["type"] == "mf").any() else [],
        "by_sector": sectors,
        "top_exposures": [
            {"name": r["name"], "pct": round(float(r["pct"]), 2), "value": float(r["value"]), "via": r["via"]}
            for _, r in top10.iterrows()
        ],
        "effective_holdings": round(float(n_eff), 1),
        "hhi": round(hhi(lt["pct"]), 4) if len(lt) else None,
        "top5_pct": round(top5_pct, 1),
        "fund_overlap": overlap,
        "flags": flags,
        "suggestions": suggestions,
        "funds_without_breakdown": no_breakdown,
    }
