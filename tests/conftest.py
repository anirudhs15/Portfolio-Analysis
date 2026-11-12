import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures as fx  # noqa: E402

from portfolio.config import load_settings  # noqa: E402
from portfolio.ingest import amfi_nav, groww_client, mf_cas  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class FakeSources:
    """Offline stand-in for LiveSources, backed by generated fixtures."""

    def __init__(self, fail_groww: bool = False):
        self.bars = fx.price_bars()
        self.navs = fx.nav_histories()
        self.fail_groww = fail_groww
        self.calls: list[str] = []

    def stock_holdings(self):
        self.calls.append("holdings")
        if self.fail_groww:
            raise RuntimeError("simulated Groww outage")
        return groww_client.parse_holdings(fx.groww_holdings_response())

    def price_history(self, symbols, days):
        self.calls.append("prices")
        return self.bars[self.bars["symbol"].isin(symbols)].copy()

    def groww_ltp(self, symbols):
        raise RuntimeError("live data plan not active")

    def sector_lookup(self, symbol):
        return {}

    def nav_latest(self):
        self.calls.append("nav_latest")
        return amfi_nav.parse_navall(fx.navall_text(self.navs))

    def nav_history(self, code):
        self.calls.append(f"nav_history:{code}")
        return self.navs[code]

    def parse_cas(self, path, password):
        self.calls.append("cas")
        return mf_cas.from_dict(fx.cas_dict(self.navs))


@pytest.fixture
def settings():
    return load_settings(ROOT / "config")


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "cas").mkdir(parents=True)
    (d / "cas" / "sample_cas.pdf").write_bytes(b"%PDF-1.4 placeholder")
    return d


@pytest.fixture
def fake():
    return FakeSources()
