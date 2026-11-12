from datetime import date

import make_fixtures as fx
import pandas as pd
import pytest

from portfolio.ingest import amfi_nav, groww_client, mf_cas, prices


def test_parse_groww_holdings_skips_zero_quantity():
    hs = groww_client.parse_holdings(fx.groww_holdings_response())
    assert len(hs) == len(fx.STOCKS)
    tcs = next(h for h in hs if h.symbol == "TCS")
    assert tcs.quantity == 10 and tcs.avg_price == 3500.0 and tcs.cost == 35000.0


def test_parse_groww_holdings_accepts_raw_rest_shape():
    raw = {"status": "SUCCESS", "payload": fx.groww_holdings_response()}
    assert len(groww_client.parse_holdings(raw)) == len(fx.STOCKS)


def test_parse_navall_categories_and_na_rows():
    navs = amfi_nav.parse_navall(fx.navall_text(fx.nav_histories()))
    rec = navs["INF179K01YV8"]
    assert rec.scheme_code == "119551"
    assert rec.category == "Equity Scheme - Large Cap Fund"
    assert rec.scheme_type == "Open Ended Schemes"
    assert rec.amc == "Sample Mutual Fund"
    assert rec.nav_date == fx.TODAY
    assert "INF000000000" not in navs  # N.A. NAV skipped


def test_category_mappings():
    assert amfi_nav.asset_class_for_category("Debt Scheme - Short Duration Fund") == "Debt"
    assert amfi_nav.asset_class_for_category("Equity Scheme - ELSS") == "Equity"
    assert amfi_nav.market_cap_bucket_for_category("Equity Scheme - Large & Mid Cap Fund") == "Large & Mid"
    assert amfi_nav.market_cap_bucket_for_category("Equity Scheme - Small Cap Fund") == "Small"
    assert amfi_nav.market_cap_bucket_for_category("Equity Scheme - Flexi Cap Fund") == "Multi"


def test_parse_mfapi_sorts_oldest_first():
    js = {"data": [{"date": "12-11-2026", "nav": "101.5"}, {"date": "11-11-2026", "nav": "100.0"}]}
    assert amfi_nav.parse_mfapi(js) == [(date(2026, 11, 11), 100.0), (date(2026, 11, 12), 101.5)]


def test_cas_drops_tax_lines_and_personal_data():
    res = mf_cas.from_dict(fx.cas_dict(fx.nav_histories()))
    assert len(res.holdings) == 3
    assert all(t.type != "STAMP_DUTY_TAX" for t in res.transactions)
    assert len(res.transactions) == 6
    assert res.period_to == date(2026, 10, 31)
    assert "ABCDE1234F" not in repr(res)  # PAN never kept


def test_cas_nsdl_shape():
    data = {"file_type": "CDSL", "statement_period": {"from": "01-Oct-2026", "to": "31-Oct-2026"},
            "accounts": [{"mutual_funds": [{"name": "X Fund", "isin": "INF1", "amfi": "123", "balance": 10,
                                            "avg_cost": 50, "nav": 60, "total_cost": None}]}]}
    res = mf_cas.from_dict(data)
    assert res.holdings[0].cost == 500 and res.holdings[0].units == 10


def test_latest_change_and_bse_suffix():
    bars = fx.price_bars()
    lc = prices.latest_change(bars).set_index("symbol")
    assert lc.loc["^NSEI", "price_date"] == fx.TODAY
    assert abs(lc.loc["^NSEI", "day_change_pct"] - (-0.8)) < 1e-6
    assert prices.to_yahoo("TCS") == "TCS.NS" and prices.to_yahoo("^NSEI") == "^NSEI"


def test_frames_from_multiindex():
    idx = pd.to_datetime(["2026-11-11", "2026-11-12"])
    cols = pd.MultiIndex.from_product([["TCS.NS"], ["Open", "High", "Low", "Close", "Volume"]])
    raw = pd.DataFrame([[1, 2, 0.5, 1.5, 10], [1.5, 2.5, 1, 2, 20]], index=idx, columns=cols)
    frames = prices._frames_from(raw, {"TCS.NS": "TCS"})
    assert frames[0]["symbol"].iat[0] == "TCS" and frames[0]["close"].tolist() == [1.5, 2.0]


def test_cdsl_same_fund_in_demat_and_folio_is_merged():
    data = {"file_type": "CDSL", "statement_period": {"from": "01-Oct-2026", "to": "31-Oct-2026"},
            "accounts": [
                {"type": "CDSL Demat Account", "equities": [
                    {"isin": "INE002A01018", "name": "RELIANCE", "num_shares": 5, "price": 1300}],
                 "mutual_funds": [{"name": "Midcap (demat)", "isin": "INF247L01445", "amfi": "127042",
                                   "balance": 282.225, "avg_cost": None, "total_cost": None}]},
                {"type": "Mutual Fund Folios", "mutual_funds": [
                    {"name": "Midcap (folio)", "isin": "INF247L01445", "amfi": "127042", "balance": 219.168,
                     "avg_cost": None, "total_cost": 26000}]},
            ]}
    res = mf_cas.from_dict(data)
    merged = res.merged_holdings()
    assert len(merged) == 1
    assert merged[0].units == pytest.approx(501.393)
    assert merged[0].cost is None  # demat part has no cost, so the total is unknown
    assert res.equities[0].quantity == 5
