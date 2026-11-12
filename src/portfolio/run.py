"""Entry point for the daily runs.

    python -m portfolio.run --mode close    # ~3:45 PM IST: stocks after market close
    python -m portfolio.run --mode night    # ~9:30 PM IST: + mutual fund NAVs, diversification

Each run updates data/portfolio.duckdb and writes data/snapshots/<date>_<mode>.json,
which Claude's scheduled research task reads to explain moves and update the dashboard.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .analytics import attribution, diversification, movement, returns, risk
from .config import DATA_DIR, Settings, load_settings
from .ingest import amfi_nav
from .ingest import prices as price_feed
from .store import db

log = logging.getLogger("portfolio")
IST = ZoneInfo("Asia/Kolkata")


# --------------------------------------------------------------------------- helpers

def _now_ist() -> datetime:
    return datetime.now(IST)


def _clean(o):
    """Makes numpy/pandas/date values JSON-safe."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if o is pd.NaT:
        return None
    if isinstance(o, pd.Timestamp):
        o = o.to_pydatetime()
    if isinstance(o, datetime):
        # DuckDB returns DATE columns as midnight timestamps; keep them as plain dates
        return o.date().isoformat() if o.time() == datetime.min.time() and o.tzinfo is None else o.isoformat()
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# --------------------------------------------------------------------------- stocks

def load_stock_holdings(src, con, notes: list[str]) -> list[dict]:
    try:
        hs = src.stock_holdings()
        return [h.__dict__ for h in hs]
    except Exception as e:
        notes.append(f"Groww holdings fetch failed, using last known holdings: {e}")
        log.error(notes[-1])
        last = db.query(con, """
            WITH latest AS (
                SELECT run_date, run_type FROM holdings_daily WHERE type = 'stock'
                ORDER BY run_date DESC, run_type DESC LIMIT 1)
            SELECT h.isin, s.symbol, h.quantity, h.avg_cost AS avg_price
            FROM holdings_daily h
            JOIN latest l ON h.run_date = l.run_date AND h.run_type = l.run_type
            JOIN securities s USING (isin)
            WHERE h.type = 'stock'""")
        return last.to_dict("records")


def ensure_stock_securities(src, con, settings: Settings, stocks: list[dict]) -> None:
    known = db.query(con, "SELECT isin, sector FROM securities WHERE type='stock'")
    have = dict(zip(known["isin"], known["sector"]))
    rows = []
    for s in stocks:
        sym = s["symbol"]
        meta = settings.sector_map.get(sym)
        if meta is None and have.get(s["isin"]):
            continue  # already classified earlier
        if meta is None:
            meta = src.sector_lookup(sym) or {}
        name = meta.get("name") or sym
        sector, asset_class, cap = meta.get("sector"), "Equity", meta.get("market_cap_bucket")
        if s["isin"].startswith("INF"):  # an exchange-traded fund, not a company share
            asset_class = amfi_nav.asset_class_for_category(None, f"{name} {sym}")
            asset_class = "Equity" if asset_class == "Unknown" else asset_class
            sector = "Gold & Silver" if asset_class == "Gold & Silver" else (sector or "Equity ETF")
            cap = None if asset_class != "Equity" else cap
        rows.append({
            "isin": s["isin"], "symbol": sym, "name": name, "type": "stock",
            "sector": sector, "industry": meta.get("industry"),
            "market_cap_bucket": cap, "amc": None,
            "fund_category": "ETF" if s["isin"].startswith("INF") else None,
            "asset_class": asset_class, "updated_at": _now_ist().replace(tzinfo=None),
        })
    if rows:
        db.upsert(con, "securities", pd.DataFrame(rows))


# --------------------------------------------------------------------------- mutual funds

def import_new_cas(src, con, cas_dir: Path, notes: list[str]) -> None:
    done = set(db.query(con, "SELECT filename FROM cas_files")["filename"])
    for pdf in sorted(cas_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime):
        if pdf.name in done:
            continue
        try:
            res = src.parse_cas(pdf, os.environ.get("CAS_PASSWORD", ""))
        except Exception as e:
            notes.append(f"Could not read CAS {pdf.name}: {e}")
            log.error(notes[-1])
            continue
        if not res.holdings:
            notes.append(f"CAS {pdf.name} had no mutual fund holdings; skipped.")
            continue
        con.execute("DELETE FROM mf_positions")
        db.upsert(con, "mf_positions", pd.DataFrame([{
            # Folio numbers are account identifiers and aren't needed for analysis, so they aren't stored.
            "isin": h.isin, "amfi_code": h.amfi_code, "name": h.name, "amc": h.amc, "folio": None,
            "units": h.units, "cost": h.cost, "as_of": h.statement_date or res.period_to,
            "source": res.file_type,
        } for h in res.merged_holdings() if h.isin]))
        if res.equities:
            con.execute("DELETE FROM cas_equities")
            db.upsert(con, "cas_equities", pd.DataFrame([{
                "isin": e.isin, "name": e.name, "quantity": e.quantity, "price": e.price, "as_of": res.period_to,
            } for e in res.equities]))
        if res.transactions:
            db.upsert(con, "mf_transactions", pd.DataFrame([{
                "isin": t.isin, "amfi_code": t.amfi_code, "date": t.date, "type": t.type,
                "units": t.units, "nav": t.nav, "amount": t.amount, "source": "cas",
            } for t in res.transactions if t.isin and t.date]))
        db.upsert(con, "cas_files", pd.DataFrame([{
            "filename": pdf.name, "imported_at": _now_ist().replace(tzinfo=None), "period_to": res.period_to,
            "holdings": len(res.holdings), "transactions": len(res.transactions),
        }]))
        notes.append(f"Imported CAS {pdf.name}: {len(res.holdings)} funds.")
        log.info(notes[-1])
        if os.environ.get("DELETE_CAS_AFTER_IMPORT", "").lower() in ("1", "true", "yes"):
            pdf.unlink()  # the PDF contains PAN and contact details; only parsed fund data is kept
            log.info("Deleted %s after import", pdf.name)


def nav_on_or_before(hist: list[tuple[date, float]], d: date) -> float | None:
    best = None
    for hd, nav in hist:
        if hd <= d:
            best = nav
        else:
            break
    return best


def project_sips(positions: pd.DataFrame, sips: list[dict], histories: dict[str, list], today: date) -> tuple[pd.DataFrame, list[dict]]:
    """Adds units for SIP instalments that fell after each fund's CAS date. Returns (positions, projected txns)."""
    pos = positions.copy()
    projected = []
    for sip in sips:
        isin = sip.get("isin")
        if not isin:
            name = str(sip.get("fund", "")).lower()
            match = pos[pos["name"].str.lower() == name]
            if match.empty:
                continue
            isin = match.iloc[0]["isin"]
        row = pos[pos["isin"] == isin]
        if row.empty:
            continue
        i = row.index[0]
        as_of = pd.to_datetime(pos.at[i, "as_of"]).date()
        code = pos.at[i, "amfi_code"]
        hist = histories.get(code, [])
        amount, day = float(sip["amount"]), int(sip["day"])
        d = date(as_of.year, as_of.month, 1)
        while d <= today:
            try:
                due = d.replace(day=min(day, 28))
            except ValueError:
                due = d
            if as_of < due <= today:
                nav = nav_on_or_before(hist, due + timedelta(days=1))
                if nav:
                    units = amount / nav
                    pos.at[i, "units"] += units
                    pos.at[i, "cost"] = (pos.at[i, "cost"] or 0) + amount
                    projected.append({"isin": isin, "amfi_code": code, "date": due, "type": "PURCHASE_SIP",
                                      "units": units, "nav": nav, "amount": amount, "source": "projected"})
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return pos, projected


def ensure_fund_securities(con, positions: pd.DataFrame, navs: dict) -> None:
    rows = []
    for _, p in positions.iterrows():
        rec = navs.get(p["isin"])
        cat = rec.category if rec else None
        rows.append({
            "isin": p["isin"], "symbol": p["amfi_code"] or (rec.scheme_code if rec else None),
            "name": rec.scheme_name if rec else p["name"], "type": "mf", "sector": None, "industry": None,
            "market_cap_bucket": amfi_nav.market_cap_bucket_for_category(cat),
            "amc": (rec.amc if rec else None) or p["amc"], "fund_category": cat,
            "asset_class": amfi_nav.asset_class_for_category(cat, rec.scheme_name if rec else p["name"]),
            "updated_at": _now_ist().replace(tzinfo=None),
        })
    if rows:
        db.upsert(con, "securities", pd.DataFrame(rows))


# --------------------------------------------------------------------------- main run

def run(mode: str, src, data_dir: Path = DATA_DIR, settings: Settings | None = None,
        today: date | None = None) -> dict:
    settings = settings or load_settings()
    today = today or _now_ist().date()
    started = _now_ist()
    notes: list[str] = []
    con = db.connect(data_dir / "portfolio.duckdb")

    bench, broad = settings.benchmark, settings.get("benchmark", "broad", default="^CRSLDX")

    # ---- stocks
    stocks = load_stock_holdings(src, con, notes)
    ensure_stock_securities(src, con, settings, stocks)
    secs = db.query(con, "SELECT * FROM securities")
    sec_by_isin = {r["isin"]: r for r in secs.to_dict("records")}

    sector_idx_map = settings.sector_index
    needed_idx = {sector_idx_map[s] for s in (sec_by_isin.get(x["isin"], {}).get("sector") for x in stocks)
                  if s in sector_idx_map}
    symbols = sorted({x["symbol"] for x in stocks} | {bench, broad} | needed_idx)
    have_hist = db.query(con, "SELECT COUNT(DISTINCT date) AS n FROM prices_daily WHERE symbol = ?", [bench])["n"].iat[0]
    days = 10 if have_hist >= 260 else int(settings.get("risk", "lookback_days", default=365) * 1.5)
    try:
        bars = src.price_history(symbols, days)
        db.upsert(con, "prices_daily", bars[["date", "symbol", "open", "high", "low", "close", "volume"]])
    except Exception as e:
        notes.append(f"Price download failed: {e}")
        log.error(notes[-1])

    prices = db.query(con, "SELECT date, symbol, open, high, low, close, volume FROM prices_daily WHERE date <= ?", [today])
    latest = price_feed.latest_change(prices, today)
    latest_by_sym = {r["symbol"]: r for r in latest.to_dict("records")}

    bench_row = latest_by_sym.get(bench, {})
    market_open_today = bench_row.get("price_date") == today
    if mode == "close" and not market_open_today:
        notes.append("Market closed today (no Nifty bar for today); stock prices are from the last trading day.")

    if settings.get("price_source") == "groww":
        try:
            ltp = src.groww_ltp([x["symbol"] for x in stocks])
            for s, p in ltp.items():
                if s in latest_by_sym and latest_by_sym[s]["prev_close"]:
                    r = latest_by_sym[s]
                    r["close"], r["day_change_pct"] = p, (p / r["prev_close"] - 1) * 100
        except Exception as e:
            notes.append(f"Groww live prices unavailable, using Yahoo: {e}")

    rows = []
    for s in stocks:
        meta = sec_by_isin.get(s["isin"], {})
        px = latest_by_sym.get(s["symbol"])
        if not px:
            notes.append(f"No price for {s['symbol']}; excluded from today's numbers.")
            continue
        prev = px["prev_close"] if (mode != "close" or market_open_today) else px["close"]
        prev = prev or px["close"]
        rows.append({
            "isin": s["isin"], "symbol": s["symbol"], "name": meta.get("name") or s["symbol"], "type": "stock",
            "quantity": s["quantity"], "avg_cost": s["avg_price"], "cost_value": s["quantity"] * s["avg_price"],
            "price": px["close"], "price_date": px["price_date"], "prev_price": prev,
            "market_value": s["quantity"] * px["close"], "prev_value": s["quantity"] * prev,
            "sector": meta.get("sector"), "industry": meta.get("industry"),
            "market_cap_bucket": meta.get("market_cap_bucket"), "asset_class": meta.get("asset_class") or "Equity",
            "fund_category": meta.get("fund_category"),
            "high_52w": px["high_52w"], "low_52w": px["low_52w"], "units_source": "groww",
        })

    # ---- mutual funds
    import_new_cas(src, con, data_dir / "cas", notes)
    positions = db.query(con, "SELECT * FROM mf_positions")
    # ETFs sit in the demat account, so Groww reports them as stock holdings and the CAS
    # lists them as mutual funds. Count them once, from Groww (live quantity, exchange price).
    stock_isins = {r["isin"] for r in rows}
    dup = positions["isin"].isin(stock_isins) if len(positions) else pd.Series(dtype=bool)
    if len(positions) and dup.any():
        log.info("Skipping %d CAS funds already held as exchange-traded units on Groww", int(dup.sum()))
        positions = positions[~dup].reset_index(drop=True)
    mf_txns = pd.DataFrame()
    mf_status = "no CAS imported yet" if positions.empty else "ok"
    if not positions.empty:
        navs = {}
        if mode == "night":
            try:
                navs = src.nav_latest()
            except Exception as e:
                notes.append(f"AMFI NAV download failed: {e}")
                log.error(notes[-1])
        # Some CAS lines (often ETFs) carry no AMFI scheme code; recover it from the ISIN.
        missing = positions["amfi_code"].isna() | (positions["amfi_code"].astype(str).str.strip() == "")
        for i in positions.index[missing]:
            rec = navs.get(positions.at[i, "isin"])
            if rec:
                positions.at[i, "amfi_code"] = rec.scheme_code
                con.execute("UPDATE mf_positions SET amfi_code = ? WHERE isin = ?", [rec.scheme_code, positions.at[i, "isin"]])
        known = set(db.query(con, "SELECT isin FROM securities WHERE type='mf'")["isin"])
        if navs or not set(positions["isin"]) <= known:
            ensure_fund_securities(con, positions, navs)
        secs = db.query(con, "SELECT * FROM securities")
        sec_by_isin = {r["isin"]: r for r in secs.to_dict("records")}

        histories: dict[str, list] = {}
        for code in positions["amfi_code"].dropna().unique():
            stored = db.query(con, "SELECT date, nav FROM nav_daily WHERE amfi_code=? ORDER BY date", [code])
            need = mode == "night" and (len(stored) < 200 or stored["date"].max() < pd.Timestamp(today - timedelta(days=5)))
            if need:
                try:
                    hist = src.nav_history(code)
                    db.upsert(con, "nav_daily", pd.DataFrame(
                        [{"date": d, "amfi_code": code, "nav": n} for d, n in hist[-int(settings.get("risk", "lookback_days", default=365) * 1.5):]]))
                except Exception as e:
                    notes.append(f"NAV history failed for scheme {code}: {e}")
            if navs:
                rec = next((r for r in navs.values() if r.scheme_code == code), None)
                if rec:
                    db.upsert(con, "nav_daily", pd.DataFrame([{"date": rec.nav_date, "amfi_code": code, "nav": rec.nav}]))
            stored = db.query(con, "SELECT date, nav FROM nav_daily WHERE amfi_code=? ORDER BY date", [code])
            histories[code] = [(pd.to_datetime(d).date(), float(n)) for d, n in zip(stored["date"], stored["nav"])]

        positions, projected = project_sips(positions, settings.sips, histories, today)
        con.execute("DELETE FROM mf_transactions WHERE source = 'projected'")
        if projected:
            db.upsert(con, "mf_transactions", pd.DataFrame(projected))
        mf_txns = db.query(con, "SELECT * FROM mf_transactions")

        for _, p in positions.iterrows():
            hist = histories.get(p["amfi_code"], [])
            meta = sec_by_isin.get(p["isin"], {})
            if not hist:
                notes.append(f"No NAV for {p['name']}; excluded from today's numbers.")
                continue
            last_d, last_nav = hist[-1]
            prev_nav = hist[-2][1] if len(hist) > 1 else last_nav
            if mode == "close":  # today's NAV isn't out yet; show the fund flat at its last NAV
                prev_nav = last_nav
            projected_units = any(x["isin"] == p["isin"] for x in projected)
            rows.append({
                "isin": p["isin"], "symbol": p["amfi_code"], "name": meta.get("name") or p["name"], "type": "mf",
                "quantity": p["units"], "avg_cost": (p["cost"] / p["units"]) if p["cost"] and p["units"] else None,
                "cost_value": p["cost"], "price": last_nav, "price_date": last_d, "prev_price": prev_nav,
                "market_value": p["units"] * last_nav, "prev_value": p["units"] * prev_nav,
                "sector": meta.get("fund_category"), "industry": None,
                "market_cap_bucket": meta.get("market_cap_bucket"),
                "asset_class": meta.get("asset_class") or "Unknown", "fund_category": meta.get("fund_category"),
                "high_52w": max(n for _, n in hist[-252:]), "low_52w": min(n for _, n in hist[-252:]),
                "units_source": "cas+projected" if projected_units else "cas",
            })

    if not rows:
        raise RuntimeError("No holdings could be valued. " + " | ".join(notes))
    holdings = pd.DataFrame(rows)

    # ---- analytics
    mv = movement.compute(holdings)
    h = mv["holdings"]

    rets = attribution.returns_wide(prices)
    stocks_df = h[h["type"] == "stock"]
    attr = attribution.run(
        stocks_df, rets, bench, sector_idx_map,
        settings.get("movers", "abs_move_pct", default=2.0),
        settings.get("movers", "vs_sector_multiple", default=1.5),
    ) if len(stocks_df) and bench in rets.columns else pd.DataFrame()

    # Fund returns series (by AMFI code) for risk
    navs_long = db.query(con, "SELECT date, amfi_code AS symbol, nav AS close FROM nav_daily")
    all_rets = rets
    if not navs_long.empty:
        all_rets = pd.concat([rets, attribution.returns_wide(navs_long)], axis=1)
    total = h["market_value"].sum()
    weights = {r["symbol"]: r["market_value"] / total for _, r in h.iterrows()}
    port = risk.portfolio_returns(all_rets.tail(settings.get("risk", "lookback_days", default=365)), weights)
    bench_r = all_rets[bench] if bench in all_rets else pd.Series(dtype=float)
    risk_metrics = risk.metrics(port, bench_r, settings.get("risk", "risk_free_rate_pct", default=6.5))
    betas = {}
    for sym in weights:
        if sym in all_rets and bench in all_rets:
            betas[sym] = attribution.beta(all_rets[sym].tail(250), bench_r.tail(250))
    scen = risk.scenarios([(w, betas.get(s)) for s, w in weights.items()], total,
                          settings.get("scenarios", default=[-5, -10, -20]))

    constituents = load_constituents(data_dir)
    div = diversification.analyse(h, constituents, settings.get("diversification", default={}))

    # Returns per holding
    perf = []
    for _, r in h.iterrows():
        a = returns.absolute(r["cost_value"] or 0, r["market_value"]) if r["cost_value"] else {"gain_inr": None, "gain_pct": None}
        x = None
        if r["type"] == "mf" and not mf_txns.empty:
            tx = mf_txns[mf_txns["isin"] == r["isin"]].to_dict("records")
            for t in tx:
                t["date"] = pd.to_datetime(t["date"]).date()
            if tx:
                x = returns.xirr(returns.mf_cashflows(tx, r["market_value"], today))
        perf.append({"isin": r["isin"], **a, "xirr_pct": round(x * 100, 2) if x is not None else None})
    perf_df = pd.DataFrame(perf)
    # Gains only over holdings whose purchase cost is known (demat-held funds in a CDSL CAS have none).
    known_cost = h["cost_value"].notna() & (h["cost_value"] > 0)
    total_cost = float(h.loc[known_cost, "cost_value"].sum())
    value_with_cost = float(h.loc[known_cost, "market_value"].sum())
    cost_coverage_pct = value_with_cost / float(h["market_value"].sum()) * 100 if len(h) else 0.0
    if cost_coverage_pct < 99.5:
        missing_cost = h.loc[~known_cost, "name"].tolist()
        notes.append(f"Purchase cost unknown for {len(missing_cost)} holdings "
                     f"({100 - cost_coverage_pct:.0f}% of value); total gain covers the rest only.")

    # Cross-check Groww stock quantities against the latest depository CAS.
    cas_eq = db.query(con, "SELECT isin, name, quantity, as_of FROM cas_equities")
    reconciliation = []
    if len(cas_eq):
        groww_q = {r["isin"]: r["quantity"] for r in rows if r["type"] == "stock"}
        for _, e in cas_eq.iterrows():
            g = groww_q.get(e["isin"])
            if g is None or abs(g - e["quantity"]) > 1e-6:
                reconciliation.append({"isin": e["isin"], "name": e["name"], "cas_quantity": e["quantity"],
                                       "groww_quantity": g, "cas_date": e["as_of"]})

    # ---- persist
    run_type = mode
    db.upsert(con, "holdings_daily", pd.DataFrame({
        "run_date": today, "run_type": run_type, "isin": h["isin"], "type": h["type"],
        "quantity": h["quantity"], "avg_cost": h["avg_cost"], "cost_value": h["cost_value"],
        "price": h["price"], "price_date": h["price_date"], "market_value": h["market_value"],
        "day_change_pct": h["day_change_pct"], "day_change_inr": h["day_change_inr"],
        "units_source": h["units_source"],
    }))

    hist_df = db.query(con, """
        WITH totals AS (
            SELECT run_date, run_type, SUM(market_value) AS value, SUM(cost_value) AS cost
            FROM holdings_daily GROUP BY run_date, run_type)
        SELECT run_date, value, cost FROM totals t
        WHERE run_type = (SELECT MAX(run_type) FROM totals t2 WHERE t2.run_date = t.run_date)
        ORDER BY run_date""")  # 'night' > 'close', so the night total wins when both exist

    # ---- snapshot
    attr_by_isin = {r["isin"]: r for r in attr.to_dict("records")} if len(attr) else {}
    perf_by_isin = {r["isin"]: r for r in perf_df.to_dict("records")}
    holdings_out = []
    for _, r in h.sort_values("market_value", ascending=False).iterrows():
        a = attr_by_isin.get(r["isin"], {})
        holdings_out.append({
            "isin": r["isin"], "symbol": r["symbol"], "name": r["name"], "type": r["type"],
            "sector": r["sector"], "market_cap_bucket": r["market_cap_bucket"],
            "quantity": r["quantity"], "avg_cost": r["avg_cost"], "price": r["price"], "price_date": r["price_date"],
            "market_value": r["market_value"], "weight_pct": r["market_value"] / total * 100,
            "day_change_pct": r["day_change_pct"], "day_change_inr": r["day_change_inr"],
            "contribution_pct": r["contribution_pct"],
            "high_52w": r["high_52w"], "low_52w": r["low_52w"],
            "gain_inr": perf_by_isin.get(r["isin"], {}).get("gain_inr"),
            "gain_pct": perf_by_isin.get(r["isin"], {}).get("gain_pct"),
            "xirr_pct": perf_by_isin.get(r["isin"], {}).get("xirr_pct"),
            "attribution": {k: a.get(k) for k in ("market_pct", "sector_pct", "stock_specific_pct", "driver",
                                                  "sector_index", "sector_move_pct", "beta")} if a else None,
            "significant_mover": bool(a.get("significant")) if a else (
                r["type"] == "mf" and abs(r["day_change_pct"] or 0) >= settings.get("movers", "abs_move_pct", default=2.0)),
            "units_source": r["units_source"],
        })

    indices = {sym: {"close": v["close"], "day_change_pct": v["day_change_pct"], "date": v["price_date"]}
               for sym, v in latest_by_sym.items() if sym.startswith("^") or sym.endswith(".NS") and sym.isupper()}

    snapshot = {
        "schema_version": 1,
        "run": {"date": today, "mode": mode, "generated_at": _now_ist().isoformat(timespec="seconds"),
                "market_open_today": market_open_today, "mf_status": mf_status},
        "summary": {
            "total_value": mv["total_value"], "day_change_inr": mv["day_change_inr"],
            "day_change_pct": mv["day_change_pct"], "total_cost": total_cost,
            "total_gain_inr": value_with_cost - total_cost if total_cost else None,
            "total_gain_pct": (value_with_cost / total_cost - 1) * 100 if total_cost else None,
            "cost_coverage_pct": cost_coverage_pct,
            "benchmark": bench, "benchmark_change_pct": bench_row.get("day_change_pct"),
            "vs_benchmark_pct": (mv["day_change_pct"] - bench_row["day_change_pct"])
                if bench_row.get("day_change_pct") is not None else None,
            "by_type": mv["by_type"],
        },
        "movers": {"gainers": mv["gainers"], "losers": mv["losers"],
                   "to_explain": [x for x in holdings_out if x["significant_mover"]]},
        "holdings": holdings_out,
        "indices": indices,
        "risk": {"metrics": risk_metrics, "scenarios": scen},
        "diversification": div,
        "history": [{"date": d, "value": v, "cost": c} for d, v, c in hist_df.itertuples(index=False)],
        # Filled in by Claude's research step:
        "research": {"reasons": {}, "news": [], "events": [], "outlook": [], "market_wrap": None},
        "health": {"notes": notes, "price_source": settings.get("price_source", default="yahoo"),
                   "last_cas": _last_cas(con),
                   "reconciliation_vs_cas": reconciliation},
        "disclaimer": "Describes and explains the portfolio; not investment advice.",
    }
    snapshot = _clean(snapshot)

    out_dir = data_dir / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today.isoformat()}_{mode}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    (out_dir / f"latest_{mode}.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    problem = ("failed", "No price", "No NAV", "Could not", "unavailable")
    status = "partial" if any(p in n for n in notes for p in problem) else "ok"
    db.upsert(con, "runs", pd.DataFrame([{
        "run_date": today, "run_type": mode, "started_at": started.replace(tzinfo=None),
        "finished_at": _now_ist().replace(tzinfo=None), "status": status, "notes": " | ".join(notes)[:2000],
    }]))
    con.close()
    log.info("Wrote %s (status %s, value Rs %s, day %+.2f%%)", path, status,
             f"{mv['total_value']:,.0f}", mv["day_change_pct"])
    return snapshot


def _last_cas(con) -> dict | None:
    df = db.query(con, "SELECT filename, period_to, imported_at FROM cas_files ORDER BY imported_at DESC LIMIT 1")
    return df.iloc[0].to_dict() if len(df) else None


def load_constituents(data_dir: Path) -> pd.DataFrame | None:
    """Optional fund portfolio breakdowns: data/fund_portfolios/*.csv
    with columns fund_isin, stock_isin, stock_name, sector, weight_pct."""
    files = sorted((data_dir / "fund_portfolios").glob("*.csv"))
    if not files:
        return None
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["close", "night"], required=True)
    ap.add_argument("--date", help="Override today's date (YYYY-MM-DD), for re-runs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .ingest.sources import LiveSources

    today = date.fromisoformat(args.date) if args.date else None
    try:
        run(args.mode, LiveSources(), today=today)
    except Exception as e:
        log.exception("Run failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
