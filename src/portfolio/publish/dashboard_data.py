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
            # Latest market date wins; on the same date the night run (with fund NAVs) wins.
            key = (s["run"]["date"], s["run"]["mode"] == "night")
            if best is None or key > (best["run"]["date"], best["run"]["mode"] == "night"):
                best = s
    if best is None:
        raise SystemExit("No snapshot found in data/snapshots")
    return best


def _load_research(day: str) -> dict:
    """Today's research notes. Reasons for moves and the market wrap are used only from the
    same day's file; news, upcoming events and outlook carry over from the latest earlier file,
    with events already past dropped."""
    dated = sorted(p for p in RESEARCH_DIR.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))
    same = RESEARCH_DIR / f"{day}.json"
    older = [p for p in dated if p.stem < day]
    res = json.loads(older[-1].read_text()) if older else {}
    res = {k: v for k, v in res.items() if k not in ("reasons", "market_wrap")}
    if same.exists():
        today = json.loads(same.read_text())
        # Today's news is added on top of earlier news; other keys replace the carried-over ones.
        if "news" in today:
            seen = {n.get("source_url") for n in today["news"]}
            today["news"] = today["news"] + [n for n in res.get("news", []) if n.get("source_url") not in seen]
        res.update(today)
    res["events"] = [e for e in res.get("events", []) if e.get("date", "") >= day]
    return res


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _kind(h: dict) -> str:
    name = h["name"].lower()
    if h["type"] == "mf":
        # Exchange-traded funds can arrive through the CAS too (e.g. one held in another demat account)
        is_etf = ("etf" in name or "bees" in name) and "fof" not in name and "fund of fund" not in name
        return "ETF" if is_etf else "Mutual fund"
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

    # Link each news item to the holdings it is about, so a holding's panel can show its own news.
    # A research note may list `match` (symbols, scheme codes or ISINs); otherwise names are matched.
    def _news_isins(n: dict) -> list[str]:
        keys = {str(k) for k in n.get("match", [])}
        if keys:
            return [x["isin"] for x in holdings if str(x["symbol"]) in keys or x["isin"] in keys]
        who = n.get("holding", "").lower()
        if "silver" in who:
            return [x["isin"] for x in holdings if x["category"] == "Silver"]
        if "gold" in who:
            return [x["isin"] for x in holdings if x["category"] == "Gold"]
        words = [w for w in re.split(r"\W+", who) if len(w) > 2][:2]
        return [x["isin"] for x in holdings if words and all(w in x["name"].lower() for w in words)]

    news = []
    for n in sorted(research.get("news", []), key=lambda n: n["date"], reverse=True):
        isins = _news_isins(n)
        news.append({**{k: v for k, v in n.items() if k != "match"}, "isins": ",".join(isins),
                     "scope": "holding" if isins else "market"})

    # Which "things to watch" theme applies to each holding
    def _theme(x: dict) -> str:
        c = x["category"].lower()
        if c in ("silver", "gold"):
            return "Silver" if c == "silver" else "Gold"
        if "large" in c:
            return "Large caps"
        if "bond" in c or "arbitrage" in c:
            return "Interest rates"
        if x["symbol"] == "HINDCOPPER":
            return "Copper & metals"
        if "thematic" in c or c == "technology":
            return "Technology"
        if "small" in c or "mid" in c or x["cap"] in ("Small", "Mid"):
            return "Small & mid caps"
        return ""
    for x in holdings:
        x["theme"] = _theme(x)

    profiles = _profiles(holdings)

    return {
        "summary": summary, "holdings": holdings, "allocation": allocation, "profiles": profiles,
        "news": news,
        "events": sorted(research.get("events", []), key=lambda e: e["date"]),
        "outlook": research.get("outlook", []), "suggestions": sugg, "scenarios": scenarios,
        "history": history, "indices": indices, "health": health,
    }


FUND_ABOUT = {
    "Small Cap": "A mutual fund that invests mainly in small companies: higher growth potential, bigger swings.",
    "Mid Cap": "A mutual fund that invests mainly in mid-sized companies.",
    "Large Cap": "A mutual fund that invests in India's largest, most established companies.",
    "Sector / thematic": "A fund that invests in a single sector or theme, so it rises and falls with that industry.",
    "Corporate Bond": "A debt fund that lends to highly rated companies; meant to be steady, with returns tied to interest rates.",
    "Arbitrage (hybrid)": "A low-risk fund that earns from small price gaps between markets, behaving much like a debt fund.",
    "Silver": "A fund of funds that invests in silver ETFs, so it tracks the price of silver.",
    "Gold": "A fund that tracks the price of gold.",
    "Other ETFs": "An exchange-traded fund that tracks an index of companies.",
}


def _profiles(holdings: list[dict]) -> list[dict]:
    """Long-format rows: one per piece of background for each holding (about, up, down, near, far, analyst)."""
    p = RESEARCH_DIR / "profiles.json"
    if not p.exists():
        return []
    prof = json.loads(p.read_text())
    stocks, etfs, themes = prof.get("stocks", {}), prof.get("etfs", {}), prof.get("themes", {})
    rows: list[dict] = []

    def add(isin, section, text, order=0, src_name="", src_url="", **extra):
        rows.append({"isin": isin, "section": section, "order": order, "text": text,
                     "source_name": src_name, "source_url": src_url,
                     "rating": extra.get("rating"), "analysts": extra.get("analysts"),
                     "target_avg": extra.get("target_avg"), "target_low": extra.get("target_low"),
                     "target_high": extra.get("target_high"), "as_of": extra.get("as_of")})

    for h in holdings:
        isin, sym = h["isin"], str(h["symbol"])
        st = stocks.get(sym)
        if st:
            src = (st.get("sources") or [{}])[0]
            add(isin, "about", st["about"])
            for i, t in enumerate(st.get("up", [])):
                add(isin, "up", t, i)
            for i, t in enumerate(st.get("down", [])):
                add(isin, "down", t, i)
            add(isin, "near", st.get("near", ""), 0, src.get("name", ""), src.get("url", ""))
            add(isin, "far", st.get("far", ""), 0, src.get("name", ""), src.get("url", ""))
            a = st.get("analyst")
            if a:
                add(isin, "analyst", a.get("detail", ""), 0, a.get("source_name", ""), a.get("source_url", ""),
                    rating=a.get("rating"), analysts=a.get("analysts"), target_avg=a.get("target_avg"),
                    target_low=a.get("target_low"), target_high=a.get("target_high"), as_of=a.get("as_of"))
            continue
        # ETFs and funds: background comes from their theme
        about = (etfs.get(sym) or {}).get("about") or FUND_ABOUT.get(h["category"]) or ""
        if about:
            add(isin, "about", about)
        th = themes.get(h.get("theme") or "")
        if th:
            for i, t in enumerate(th.get("up", [])):
                add(isin, "up", t, i)
            for i, t in enumerate(th.get("down", [])):
                add(isin, "down", t, i)
            add(isin, "near", th.get("near", ""), 0, th.get("source_name", ""), th.get("source_url", ""))
            add(isin, "far", th.get("far", ""), 0, th.get("source_name", ""), th.get("source_url", ""))
    return rows


APP_DOCS = ["summary", "holdings", "allocation", "news", "events", "suggestions", "scenarios", "health", "profiles"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["close", "night"])
    args = ap.parse_args(argv)
    out = build(args.mode)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in out.items():
        (OUT_DIR / f"{name}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    # Ready-to-write documents for the Portfolio Pulse app's store (collection "dash").
    app_dir = DATA_DIR / "app_docs"
    app_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name in APP_DOCS:
        (app_dir / f"{name}.json").write_text(json.dumps({"rows": out[name], "updated": now}, ensure_ascii=False))
    s = out["summary"][0]
    print(f"Wrote {len(out)} files to {OUT_DIR} and {len(APP_DOCS)} app documents to {app_dir}")
    print(f"Snapshot: {s['as_of']} ({s['mode']}), value {s['total_value']}, day {s['day_pct']}%, "
          f"significant movers {s['movers_count']}, research for today: {'yes' if s['market_wrap'] else 'no'}")


if __name__ == "__main__":
    main()
