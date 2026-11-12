"""The single place where the pipeline touches the outside world.

`LiveSources` calls Groww, Yahoo Finance, AMFI and mfapi.in. Tests swap in a fake with
the same methods, so the whole pipeline can run offline on fixtures.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import amfi_nav, groww_client, mf_cas, prices


class LiveSources:
    def stock_holdings(self) -> list[groww_client.StockHolding]:
        return groww_client.fetch_holdings()

    def price_history(self, symbols: list[str], days: int) -> pd.DataFrame:
        return prices.history(symbols, days)

    def groww_ltp(self, symbols: list[str]) -> dict[str, float]:
        return groww_client.fetch_ltp(symbols)

    def sector_lookup(self, symbol: str) -> dict:
        return prices.lookup_sector(symbol)

    def nav_latest(self) -> dict[str, amfi_nav.NavRecord]:
        return amfi_nav.fetch_latest()

    def nav_history(self, scheme_code: str) -> list[tuple[date, float]]:
        return amfi_nav.fetch_history(scheme_code)

    def parse_cas(self, path: Path, password: str) -> mf_cas.CASResult:
        return mf_cas.parse_pdf(path, password)
