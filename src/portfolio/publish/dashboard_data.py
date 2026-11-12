"""Builds the dashboard's data files from the latest snapshot and research notes.

    python -m portfolio.publish.dashboard_data            # uses latest_night.json, else latest_close.json
    python -m portfolio.publish.dashboard_data --mode close

Writes data/dashboard/*.json (lists of rows). Claude's research runs upload these to the
dashboard after each update. Suggestions are worked out here from the numbers, so they are
the same every day for the same portfolio, and stay at the level of categories, never
specific securities to buy or sell.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ..config import DATA_DIR

SNAP_DIR = DATA_DIR / "snapshots"
RESEARCH_DIR = DATA_DIR / "research"
OUT_DIR = DATA_DIR / "dashboard"

INDEX_NAMES = {"^NSEI": "Nifty 50", "^CRSLDX": "Nifty 500", "^CNXIT": "Nifty IT", "^CNXMETAL": "Nifty Metal",
               "^CNXFMCG": "Nifty FMCG", "^CNXINFRA": "Nifty Infra", "^NSEBANK": "Bank Nifty",
               "^CNXENERGY": "Nifty Energy", "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma",
               "^CNXREALTY": "Nifty Realty", "^CNXMEDIA": "Nifty Media", "NIFTY_FIN_SERVICE.NS": "Nifty Financial"}


def _load_snapshot(mode: str | None) -> dict:
    order = [mode] if mode else ["night", "close"]
    best = None
    for m in order:
        p = SNAP_DIR / f"latest_{m}.json"
        if p.exists():
            s = json.loads(p.read_text())
            if best is None or s["run"]["generated_at"] > best["run"]["generated_at"]:
                best = s
    if best is None:
        raise SystemExit("No snapshot found in data/snapshots")
    return best


def _load_research(day: str) -> dict:
    p = RESEARCH_DIR / f"{day}.json"
    if p.exists():
        return json.loads(p.read_text())
    older = sorted(RESEARCH_DIR.glob("*.json"))
    return json.loads(older[-1].read_text()) if older else {}


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _kind(h: dict) -> str:
    if h["type"] == "mf":
        return "Mutual fund"
    return "ETF" if str(h["isin"]).startswith("INF") else "Stock"


def _category(h: dict, sec: dict) -> str:
    """A short, readable category for each holding."""
    if h["type"] == "stock" and not str(h["isin"]).startswith("INF"):
        return h.get("sector") or "Unclassified"
    cat = (sec.get("fund_category") or h.get("sector") or "")
    name = h["name"].lower()
    if "silver" in name:
        return "Silver"
    if "gold" in name:
        return "Gold"
    if "arbitrage" in name:
        return "Arbitrage (hybrid)"
    if " - " in cat:
        cat = cat.split(" - ", 1)[1]
    cat = re.sub(r"\s+", " ", cat.replace(" Fund", "").replace("Sectoral/ Thematic", "Sector / thematic")).strip()
    return cat or "Other"


def build(mode: str | None = None) -> dict[str, list]:
    snap = _load_snapshot(mode)
    day = snap["run"]["date"]
    research = _load_research(day)
    total = snap["summary"]["total_value"]

    reasons = {}
    for r in research.get("reasons", []):
        for key in r.get("match", []):
            reasons[str(key)] = r

    holdings = []
    for h in snap["holdings"]:
        r = reasons.get(str(h["symbol"])) or reasons.get(h["isin"]) or {}
        src = (r.get("sources") or [{}])[0]
        attr = h.get("attribution") or {}
        holdings.append({
            "isin": h["isin"], "symbol": h["symbol"], "name": h["name"], "kind": _kind(h),
            "category": _category(h, h), "cap": h.get("market_cap_bucket") or "",
            "quantity": _r(h["quantity"], 3), "avg_cost": _r(h.get("avg_cost")), "price": _r(h["price"]),
            "price_date": h["price_date"], "value": _r(h["market_value"]), "weight_pct": _r(h["weight_pct"]),
            "day_pct": _r(h["day_change_pct"]), "day_inr": _r(h["day_change_inr"]),
            "contribution_pct": _r(h.get("contribution_pct"), 4),
            "gain_inr": _r(h.get("gain_inr")), "gain_pct": _r(h.get("gain_pct")), "xirr_pct": _r(h.get("xirr_pct")),
            "high_52w": _r(h.get("high_52w")), "low_52w": _r(h.get("low_52w")),
            "significant": bool(h.get("significant_mover")),
            "driver": r.get("driver") or {"market": "Market", "sector": "Sector",
                                          "stock_specific": "Company / other"}.get(attr.get("driver"), ""),
            "reason": r.get("reason") or "", "sentiment": r.get("sentiment") or "",
            "source_name": src.get("name", ""), "source_url": src.get("url", ""),
        })

    s, risk, div = snap["summary"], snap["risk"]["metrics"], snap["diversification"]
    silver = [x for x in holdings if x["category"] == "Silver"]
    gold = [x for x in holdings if x["category"] == "Gold"]
    stocks = [x for x in holdings if x["kind"] == "Stock"]
    summary = [{
        "as_of": day, "mode": snap["run"]["mode"], "generated_at": snap["run"]["generated_at"],
        "total_value": _r(total), "day_inr": _r(s["day_change_inr"]), "day_pct": _r(s["day_change_pct"]),
        "nifty_pct": _r(s.get("benchmark_change_pct")), "vs_nifty_pct": _r(s.get("vs_benchmark_pct")),
        "invested": _r(s.get("total_cost")), "gain_inr": _r(s.get("total_gain_inr")),
        "gain_pct": _r(s.get("total_gain_pct")), "cost_coverage_pct": _r(s.get("cost_coverage_pct"), 0),
        "holdings_count": len(holdings), "stocks_count": len(stocks),
        "funds_count": sum(x["kind"] != "Stock" for x in holdings),
        "effective_holdings": div.get("effective_holdings"), "top5_pct": div.get("top5_pct"),
        "volatility_pct": risk.get("annual_volatility_pct"), "beta": risk.get("beta"),
        "max_drawdown_pct": risk.get("max_drawdown_pct"), "sharpe": risk.get("sharpe"),
        "one_year_return_pct": risk.get("annual_return_pct"),
        "movers_count": sum(x["significant"] for x in holdings),
        "market_wrap": (research.get("market_wrap") or {}).get("text", ""),
        "market_wrap_source": (research.get("market_wrap") or {}).get("source_url", ""),
    }]

    allocation = []
    for dim, rows in [("Asset class", div.get("by_asset_class", [])),
                      ("Market cap (equity only)", div.get("by_market_cap", []))]:
        for a in rows:
            name = {"Unclassified": "Thematic / other", "FoF": "Fund of funds"}.get(a["name"], a["name"])
            allocation.append({"dimension": dim, "name": name, "value": _r(a["value"]), "pct": _r(a["pct"])})
    cats: dict[str, float] = {}
    for x in holdings:
        cats[x["category"]] = cats.get(x["category"], 0) + x["value"]
    for name, v in sorted(cats.items(), key=lambda kv: -kv[1]):
        allocation.append({"dimension": "Category", "name": name, "value": _r(v), "pct": _r(v / total * 100)})

    # ---- suggestions (category level only)
    sugg = []
    sv = sum(x["value"] for x in silver)
    if silver and sv / total > 0.15:
        sugg.append({"area": "Silver", "level": "high",
                     "finding": f"Silver is your largest exposure: {sv / total * 100:.0f}% of the portfolio across "
                                f"{len(silver)} holdings.",
                     "detail": "The silver fund-of-funds invest in silver ETFs, so these holdings move almost "
                               "identically and add little diversification over holding one. A single commodity "
                               "at this weight makes the portfolio swing with silver prices.",
                     "consider": "Decide what share of the portfolio you want in precious metals; one vehicle may be enough."})
    caps = {a["name"]: a["pct"] for a in div.get("by_market_cap", [])}
    ms = caps.get("Mid", 0) + caps.get("Small", 0)
    if ms > 45:
        sugg.append({"area": "Market cap", "level": "medium",
                     "finding": f"{ms:.0f}% of your equity is in mid- and small-cap funds and stocks; "
                                f"large caps are {caps.get('Large', 0):.0f}%.",
                     "detail": "Mid and small caps can grow faster but usually fall further in market corrections.",
                     "consider": "Check that this tilt matches how much short-term volatility you can sit through."})
    small_funds = [x for x in holdings if x["kind"] == "Mutual fund" and x["category"].startswith("Small Cap")]
    mid_funds = [x for x in holdings if x["kind"] == "Mutual fund" and x["category"].startswith("Mid Cap")]
    if len(small_funds) >= 2 or len(mid_funds) >= 2:
        parts = []
        if len(small_funds) >= 2:
            parts.append(f"{len(small_funds)} small-cap funds")
        if len(mid_funds) >= 2:
            parts.append(f"{len(mid_funds)} mid-cap funds")
        sugg.append({"area": "Fund overlap", "level": "medium",
                     "finding": f"You hold {' and '.join(parts)}.",
                     "detail": "Funds in the same category often own many of the same companies, so extra funds "
                               "add complexity more than diversification.",
                     "consider": "Compare their portfolios; one or two per category is usually enough."})
    if stocks:
        sval = sum(x["value"] for x in stocks)
        losers = sum(1 for x in stocks if (x["gain_pct"] or 0) < 0)
        sugg.append({"area": "Direct stocks", "level": "low",
                     "finding": f"{len(stocks)} stocks make up {sval / total * 100:.0f}% of the portfolio; "
                                f"{losers} are below your purchase price.",
                     "detail": "Most are small companies, with positions of a few thousand rupees each, so they "
                               "barely move the total but need following.",
                     "consider": "Review each against why you bought it, using the news and results below."})
    thematic = [x for x in holdings if "thematic" in x["category"].lower()]
    tv = sum(x["value"] for x in thematic)
    if tv / total > 0.10:
        sugg.append({"area": "Sector bet", "level": "medium",
                     "finding": f"Sector / thematic funds are {tv / total * 100:.0f}% of the portfolio.",
                     "detail": "A single-sector fund rises and falls with that industry.",
                     "consider": "Keep sector funds to a size you are comfortable seeing swing."})
    ac = {a["name"]: a["pct"] for a in div.get("by_asset_class", [])}
    dh = ac.get("Debt", 0) + ac.get("Hybrid", 0)
    if dh < 15:
        sugg.append({"area": "Stability", "level": "low",
                     "finding": f"Debt and hybrid funds are {dh:.0f}% of the portfolio.",
                     "detail": "These usually cushion falls in stocks and metals.",
                     "consider": "Think about whether you want a larger cushion for money you may need in the next few years."})

    scenarios = [{"nifty_move_pct": x["nifty_move_pct"], "portfolio_move_pct": x["portfolio_move_pct"],
                  "impact_inr": x["impact_inr"]} for x in snap["risk"]["scenarios"]]
    history = [{"date": h["date"], "value": _r(h["value"])} for h in snap.get("history", [])]
    indices = [{"symbol": k, "name": INDEX_NAMES.get(k, k), "close": _r(v["close"]), "day_pct": _r(v["day_change_pct"])}
               for k, v in snap.get("indices", {}).items() if k in INDEX_NAMES]
    health = [{"item": n} for n in snap["health"]["notes"]] or [{"item": "All sources loaded normally."}]

    return {
        "summary": summary, "holdings": holdings, "allocation": allocation,
        "news": sorted(research.get("news", []), key=lambda n: n["date"], reverse=True),
        "events": sorted(research.get("events", []), key=lambda e: e["date"]),
        "outlook": research.get("outlook", []), "suggestions": sugg, "scenarios": scenarios,
        "history": history, "indices": indices, "health": health,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["close", "night"])
    args = ap.parse_args(argv)
    out = build(args.mode)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in out.items():
        (OUT_DIR / f"{name}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"Wrote {len(out)} files to {OUT_DIR}")


if __name__ == "__main__":
    main()
