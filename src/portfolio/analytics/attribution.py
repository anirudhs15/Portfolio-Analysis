"""Splits each stock's move into market, sector and stock-specific parts.

    r_stock = beta * r_nifty  +  (r_sector - beta_s * r_nifty)  +  residual
              -- market --       --------- sector ----------      stock-specific

beta   = stock's beta to Nifty over the lookback window
beta_s = sector index's beta to Nifty
The sector term is only counted to the extent the stock actually tracks its sector.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def returns_wide(prices: pd.DataFrame) -> pd.DataFrame:
    """prices: long frame (date, symbol, close) -> wide daily % returns."""
    wide = prices.pivot_table(index="date", columns="symbol", values="close").sort_index()
    return wide.pct_change(fill_method=None) * 100


def beta(asset: pd.Series, market: pd.Series, min_obs: int = 60) -> float | None:
    df = pd.concat([asset, market], axis=1).dropna()
    if len(df) < min_obs:
        return None
    m = df.iloc[:, 1]
    var = m.var()
    if not var or np.isnan(var):
        return None
    return float(df.iloc[:, 0].cov(m) / var)


def attribute(
    stock_move: float,
    nifty_move: float,
    sector_move: float | None,
    b_stock: float | None,
    b_sector: float | None,
    sector_tracking: float | None = None,
) -> dict:
    b = 1.0 if b_stock is None else b_stock
    market = b * nifty_move
    sector = 0.0
    if sector_move is not None:
        bs = 1.0 if b_sector is None else b_sector
        # Scale the sector's excess move by how closely this stock follows its sector (0..1).
        loading = 1.0 if sector_tracking is None else max(0.0, min(1.0, sector_tracking))
        sector = (sector_move - bs * nifty_move) * loading
    specific = stock_move - market - sector

    parts = {"market": market, "sector": sector, "stock_specific": specific}
    driver = max(parts, key=lambda k: abs(parts[k]))
    return {**{f"{k}_pct": round(v, 3) for k, v in parts.items()}, "driver": driver}


def sector_tracking(stock: pd.Series, sector_idx: pd.Series, nifty: pd.Series, min_obs: int = 60) -> float | None:
    """Beta of the stock's market-excess return to the sector's market-excess return."""
    b_st = beta(stock, nifty, min_obs)
    b_se = beta(sector_idx, nifty, min_obs)
    if b_st is None or b_se is None:
        return None
    return beta(stock - b_st * nifty, sector_idx - b_se * nifty, min_obs)


def is_significant(stock_move: float, sector_move: float | None, abs_pct: float, sector_multiple: float) -> bool:
    if abs(stock_move) >= abs_pct:
        return True
    if sector_move is not None and abs(sector_move) > 0.25:
        return abs(stock_move) >= sector_multiple * abs(sector_move) and abs(stock_move) >= abs_pct / 2
    return False


def run(
    holdings: pd.DataFrame,
    rets: pd.DataFrame,
    benchmark: str,
    sector_index: dict[str, str],
    abs_pct: float,
    sector_multiple: float,
    lookback: int = 250,
) -> pd.DataFrame:
    """holdings: stock rows with symbol, sector, day_change_pct. rets: wide % returns incl. indices."""
    window = rets.tail(lookback + 1).iloc[:-1]  # exclude today from beta estimation
    today = rets.iloc[-1] if len(rets) else pd.Series(dtype=float)
    nifty_move = float(today.get(benchmark, 0.0) or 0.0)
    rows = []
    for _, h in holdings.iterrows():
        sym = h["symbol"]
        move = h.get("day_change_pct")
        if move is None or pd.isna(move):
            continue
        sidx = sector_index.get(h.get("sector") or "")
        s_move = float(today[sidx]) if sidx and sidx in today and pd.notna(today[sidx]) else None
        b = beta(window[sym], window[benchmark]) if sym in window and benchmark in window else None
        bs = beta(window[sidx], window[benchmark]) if s_move is not None and sidx in window else None
        trk = (
            sector_tracking(window[sym], window[sidx], window[benchmark])
            if s_move is not None and sym in window else None
        )
        a = attribute(float(move), nifty_move, s_move, b, bs, trk)
        rows.append({
            "isin": h["isin"], "symbol": sym, "sector": h.get("sector"), "sector_index": sidx,
            "move_pct": float(move), "nifty_move_pct": nifty_move, "sector_move_pct": s_move,
            "beta": b, **a,
            "significant": is_significant(float(move), s_move, abs_pct, sector_multiple),
        })
    return pd.DataFrame(rows)
