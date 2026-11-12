"""Risk metrics from today's weights applied to past daily returns.

This answers "how risky is the portfolio I hold now", not "how risky was my past portfolio".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .attribution import beta as _beta

TRADING_DAYS = 252


def portfolio_returns(rets: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """rets: wide % daily returns; weights: {column: weight fraction}. Missing data is re-weighted."""
    cols = [c for c in weights if c in rets.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({c: weights[c] for c in cols})
    sub = rets[cols]
    avail = sub.notna()
    wsum = avail.mul(w, axis=1).sum(axis=1)
    pr = sub.fillna(0).mul(w, axis=1).sum(axis=1) / wsum.replace(0, np.nan)
    return pr.dropna()


def metrics(port: pd.Series, bench: pd.Series, risk_free_pct: float = 6.5) -> dict:
    if len(port) < 20:
        return {"observations": int(len(port))}
    r = port / 100
    vol = float(r.std() * np.sqrt(TRADING_DAYS) * 100)
    ann_ret = float(((1 + r).prod() ** (TRADING_DAYS / len(r)) - 1) * 100)
    downside = r[r < 0].std() * np.sqrt(TRADING_DAYS) * 100
    wealth = (1 + r).cumprod()
    dd = wealth / wealth.cummax() - 1
    b = _beta(port, bench, min_obs=20)
    return {
        "observations": int(len(port)),
        "annual_return_pct": round(ann_ret, 2),
        "annual_volatility_pct": round(vol, 2),
        "sharpe": round((ann_ret - risk_free_pct) / vol, 2) if vol else None,
        "sortino": round((ann_ret - risk_free_pct) / downside, 2) if downside else None,
        "max_drawdown_pct": round(float(dd.min() * 100), 2),
        "beta": round(b, 2) if b is not None else None,
    }


def scenarios(weights_betas: list[tuple[float, float | None]], total_value: float, moves: list[float]) -> list[dict]:
    """Estimated portfolio impact of Nifty moves, using each holding's beta (default 1.0)."""
    pb = sum(w * (b if b is not None else 1.0) for w, b in weights_betas)
    return [
        {"nifty_move_pct": m, "portfolio_move_pct": round(pb * m, 2), "impact_inr": round(total_value * pb * m / 100)}
        for m in moves
    ]


def correlation(rets: pd.DataFrame, cols: list[str], lookback: int = 250) -> pd.DataFrame:
    cols = [c for c in cols if c in rets.columns]
    return rets[cols].tail(lookback).corr().round(2)
