"""Generates deterministic sample data for offline tests (no real portfolio data)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

TODAY = date(2026, 11, 12)  # a Thursday

STOCKS = {  # symbol: (isin, qty, avg_price, start_price, beta, sector_index)
    "RELIANCE": ("INE002A01018", 20, 1200.0, 1250.0, 1.0, "^CNXENERGY"),
    "TCS": ("INE467B01029", 10, 3500.0, 3400.0, 0.8, "^CNXIT"),
    "INFY": ("INE009A01021", 25, 1500.0, 1450.0, 0.9, "^CNXIT"),
    "HDFCBANK": ("INE040A01034", 40, 1550.0, 1600.0, 1.1, "^NSEBANK"),
    "ITC": ("INE154A01025", 100, 420.0, 410.0, 0.6, "^CNXFMCG"),
}
INDICES = ["^NSEI", "^CRSLDX", "^CNXENERGY", "^CNXIT", "^NSEBANK", "^CNXFMCG"]

FUNDS = {  # isin: (amfi_code, name, category, units, cost, start_nav)
    "INF179K01YV8": ("119551", "Sample Large Cap Fund - Direct Growth", "Equity Scheme - Large Cap Fund", 500.0, 40000.0, 80.0),
    "INF879O01027": ("122639", "Sample Flexi Cap Fund - Direct Growth", "Equity Scheme - Flexi Cap Fund", 300.0, 20000.0, 70.0),
    "INF200K01RA0": ("119800", "Sample Short Duration Fund - Direct Growth", "Debt Scheme - Short Duration Fund", 1000.0, 30000.0, 31.0),
}


def trading_days(end: date, n: int) -> list[date]:
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def price_bars(n: int = 420, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = trading_days(TODAY, n)
    mkt = rng.normal(0.04, 0.9, n) / 100
    mkt[-1] = -0.008  # Nifty -0.8% today
    sector = {s: mkt * b + rng.normal(0, 0.6, n) / 100 for s, b in
              [("^CNXENERGY", 1.0), ("^CNXIT", 0.8), ("^NSEBANK", 1.1), ("^CNXFMCG", 0.6)]}
    sector["^CNXIT"][-1] = 0.021  # IT sector +2.1% today
    series = {"^NSEI": (24000, mkt), "^CRSLDX": (22000, mkt * 1.05 + rng.normal(0, 0.2, n) / 100)}
    for s, r in sector.items():
        series[s] = (30000, r)
    for sym, (_, _, _, p0, b, sidx) in STOCKS.items():
        r = sector[sidx] * 0.8 + mkt * (b - 0.8) + rng.normal(0, 1.0, n) / 100
        series[sym] = (p0, r)
    series["RELIANCE"][1][-1] = -0.043  # stock-specific drop today
    rows = []
    for sym, (p0, r) in series.items():
        close = p0 * np.cumprod(1 + r)
        for d, c in zip(days, close):
            rows.append({"date": d, "symbol": sym, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6})
    return pd.DataFrame(rows)


def nav_histories(n: int = 420, seed: int = 11) -> dict[str, list[tuple[date, float]]]:
    rng = np.random.default_rng(seed)
    days = trading_days(TODAY, n)
    out = {}
    for isin, (code, _, cat, _, _, nav0) in FUNDS.items():
        vol = 0.15 if cat.startswith("Debt") else 0.9
        r = rng.normal(0.03, vol, n) / 100
        navs = nav0 * np.cumprod(1 + r)
        out[code] = list(zip(days, navs.round(4)))
    return out


def navall_text(hist: dict) -> str:
    lines = ["Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date", ""]
    by_cat: dict[str, list] = {}
    for isin, (code, name, cat, *_rest) in FUNDS.items():
        by_cat.setdefault(cat, []).append((isin, code, name))
    for cat, funds in by_cat.items():
        lines += [f"Open Ended Schemes({cat})", "", "Sample Mutual Fund", ""]
        for isin, code, name in funds:
            d, nav = hist[code][-1]
            lines.append(f"{code};{isin};-;{name};{nav};{d.strftime('%d-%b-%Y')}")
        lines.append("")
    lines.append("999999;INF000000000;-;Closed Fund;N.A.;12-Nov-2026")
    return "\n".join(lines)


def cas_dict(hist: dict) -> dict:
    """A CAMS-style CAS as casparser returns it; holdings as of 2026-10-31."""
    as_of = date(2026, 10, 31)
    folios = []
    for isin, (code, name, _cat, units, cost, _n) in FUNDS.items():
        nav = next(n for d, n in reversed(hist[code]) if d <= as_of)
        # two purchases making up the position
        txns = [
            {"date": date(2025, 6, 10), "description": "Purchase", "amount": cost * 0.6, "units": units * 0.65,
             "nav": cost * 0.6 / (units * 0.65), "balance": units * 0.65, "type": "PURCHASE"},
            {"date": date(2026, 3, 5), "description": "SIP", "amount": cost * 0.4, "units": units * 0.35,
             "nav": cost * 0.4 / (units * 0.35), "balance": units, "type": "PURCHASE_SIP"},
            {"date": date(2026, 3, 5), "description": "Stamp duty", "amount": 1.0, "units": None,
             "nav": None, "balance": units, "type": "STAMP_DUTY_TAX"},
        ]
        folios.append({
            "folio": f"1234/{code}", "amc": "Sample Mutual Fund", "PAN": "ABCDE1234F",
            "schemes": [{"scheme": name, "isin": isin, "amfi": code, "open": 0, "close": units,
                         "close_calculated": units, "type": "EQUITY",
                         "valuation": {"date": as_of, "nav": nav, "cost": cost, "value": units * nav},
                         "transactions": txns}],
        })
    return {"statement_period": {"from": "01-Jan-2025", "to": "31-Oct-2026"}, "folios": folios,
            "investor_info": {"name": "Sample Investor", "email": "x@example.com"},
            "cas_type": "DETAILED", "file_type": "CAMS", "parse_warnings": []}


def groww_holdings_response() -> dict:
    return {"holdings": [
        {"isin": isin, "trading_symbol": sym, "quantity": qty, "average_price": avg,
         "pledge_quantity": 0, "demat_locked_quantity": 0}
        for sym, (isin, qty, avg, *_r) in STOCKS.items()
    ] + [{"isin": "INE000000000", "trading_symbol": "SOLD", "quantity": 0, "average_price": 10}]}


def constituents() -> pd.DataFrame:
    rows = [
        ("INF179K01YV8", "INE040A01034", "HDFC Bank", "Banks", 10.0),
        ("INF179K01YV8", "INE002A01018", "Reliance Industries", "Energy", 9.0),
        ("INF179K01YV8", "INE009A01021", "Infosys", "Information Technology", 6.0),
        ("INF179K01YV8", "INE090A01021", "ICICI Bank", "Banks", 8.0),
        ("INF879O01027", "INE040A01034", "HDFC Bank", "Banks", 8.0),
        ("INF879O01027", "INE090A01021", "ICICI Bank", "Banks", 6.0),
        ("INF879O01027", "INE397D01024", "Bharti Airtel", "Communication Services", 5.0),
    ]
    return pd.DataFrame(rows, columns=["fund_isin", "stock_isin", "stock_name", "sector", "weight_pct"])
