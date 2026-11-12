"""Free daily prices for stocks and indices from Yahoo Finance (via yfinance).

NSE symbols get a ".NS" suffix; anything not found on NSE is retried on BSE (".BO").
Index symbols (starting with "^" or already containing ".") are used as given.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)


def to_yahoo(symbol: str) -> str:
    if symbol.startswith("^") or "." in symbol:
        return symbol
    return f"{symbol.upper()}.NS"


def _download(tickers: list[str], days: int) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(
        tickers=tickers,
        period=f"{days}d",
        interval="1d",
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    return df


def history(symbols: list[str], days: int = 400) -> pd.DataFrame:
    """Returns long-format daily bars: date, symbol, open, high, low, close, volume.

    `symbol` in the output is the caller's symbol (without the Yahoo suffix).
    """
    if not symbols:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    ymap = {to_yahoo(s): s for s in symbols}
    frames = _frames_from(_download(list(ymap), days), ymap)

    missing = [s for s in symbols if s not in {f["symbol"].iat[0] for f in frames if len(f)}]
    retry = {f"{s.upper()}.BO": s for s in missing if not (s.startswith("^") or "." in s)}
    if retry:
        log.info("Retrying on BSE: %s", ", ".join(retry.values()))
        frames += _frames_from(_download(list(retry), days), retry)

    if not frames:
        raise RuntimeError("Yahoo Finance returned no price data")
    return pd.concat(frames, ignore_index=True)


def _frames_from(raw: pd.DataFrame, ymap: dict[str, str]) -> list[pd.DataFrame]:
    frames = []
    if raw is None or raw.empty:
        return frames
    multi = isinstance(raw.columns, pd.MultiIndex)
    for yt, sym in ymap.items():
        try:
            sub = raw[yt] if multi else raw
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            continue
        f = pd.DataFrame(
            {
                "date": pd.to_datetime(sub.index).date,
                "symbol": sym,
                "open": sub["Open"].astype(float).values,
                "high": sub["High"].astype(float).values,
                "low": sub["Low"].astype(float).values,
                "close": sub["Close"].astype(float).values,
                "volume": sub.get("Volume", pd.Series(0, index=sub.index)).fillna(0).astype(float).values,
            }
        )
        frames.append(f)
    return frames


def latest_change(bars: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    """Per symbol: last close, previous close, day change %, and the date of the last bar."""
    rows = []
    bars = bars.assign(date=pd.to_datetime(bars["date"]).dt.date)
    for sym, g in bars.sort_values("date").groupby("symbol"):
        if as_of is not None:
            g = g[g["date"] <= as_of]
        if len(g) == 0:
            continue
        last = g.iloc[-1]
        prev = g.iloc[-2]["close"] if len(g) > 1 else None
        rows.append(
            {
                "symbol": sym,
                "price_date": last["date"],
                "close": float(last["close"]),
                "prev_close": float(prev) if prev is not None else None,
                "day_change_pct": (float(last["close"]) / float(prev) - 1) * 100 if prev else None,
                "high_52w": float(g.tail(252)["high"].max()),
                "low_52w": float(g.tail(252)["low"].min()),
            }
        )
    return pd.DataFrame(rows)


def lookup_sector(symbol: str) -> dict:
    """Best-effort sector lookup from Yahoo when a stock is missing from config/sector_map.csv."""
    try:
        import yfinance as yf

        info = yf.Ticker(to_yahoo(symbol)).info or {}
        mcap = info.get("marketCap")
        # SEBI buckets are rank-based; these crore thresholds approximate them.
        bucket = None
        if mcap:
            cr = mcap / 1e7
            bucket = "Large" if cr >= 100_000 else "Mid" if cr >= 33_000 else "Small"
        return {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap_bucket": bucket,
            "name": info.get("longName") or info.get("shortName"),
        }
    except Exception as e:
        log.warning("Sector lookup failed for %s: %s", symbol, e)
        return {}
