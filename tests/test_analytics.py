from datetime import date

import make_fixtures as fx
import numpy as np
import pandas as pd
import pytest

from portfolio.analytics import attribution, diversification, movement, returns, risk


def _h(rows):
    return pd.DataFrame(rows, columns=["isin", "name", "type", "market_value", "prev_value", "sector",
                                       "market_cap_bucket", "asset_class", "fund_category", "symbol"])


def test_movement_contributions_sum_to_portfolio_change():
    h = _h([["A", "A", "stock", 110, 100, "IT", "Large", "Equity", None, "A"],
            ["B", "B", "stock", 190, 200, "Banks", "Large", "Equity", None, "B"],
            ["C", "C", "mf", 101, 100, None, "Multi", "Equity", "Flexi", "C"]])
    m = movement.compute(h)
    assert m["day_change_inr"] == pytest.approx(1)
    assert m["holdings"]["contribution_pct"].sum() == pytest.approx(m["day_change_pct"])
    assert m["gainers"][0]["isin"] == "A" and m["losers"][0]["isin"] == "B"


def test_beta_recovers_known_value():
    rng = np.random.default_rng(1)
    mkt = pd.Series(rng.normal(0, 1, 500))
    stock = 1.5 * mkt + pd.Series(rng.normal(0, 0.1, 500))
    assert attribution.beta(stock, mkt) == pytest.approx(1.5, abs=0.02)


def test_attribute_labels_stock_specific_move():
    a = attribution.attribute(stock_move=-4.3, nifty_move=-0.8, sector_move=-0.5, b_stock=1.0, b_sector=1.0)
    assert a["driver"] == "stock_specific"
    assert a["market_pct"] + a["sector_pct"] + a["stock_specific_pct"] == pytest.approx(-4.3, abs=1e-3)


def test_attribute_labels_sector_move():
    a = attribution.attribute(stock_move=2.2, nifty_move=-0.8, sector_move=2.1, b_stock=0.8, b_sector=0.8,
                              sector_tracking=1.0)
    assert a["driver"] == "sector"


def test_significance_rules():
    assert attribution.is_significant(-2.5, None, 2.0, 1.5)
    assert not attribution.is_significant(0.5, 0.4, 2.0, 1.5)
    assert attribution.is_significant(1.6, 0.5, 2.0, 1.5)


def test_attribution_on_fixture_flags_reliance():
    bars = fx.price_bars()
    rets = attribution.returns_wide(bars)
    lc = rets.iloc[-1]
    hold = pd.DataFrame([{"isin": i, "symbol": s, "sector": sec, "day_change_pct": lc[s]}
                         for s, (i, *_r, sidx) in fx.STOCKS.items()
                         for sec in [{"^CNXENERGY": "Energy", "^CNXIT": "Information Technology",
                                      "^NSEBANK": "Banks", "^CNXFMCG": "FMCG"}[sidx]]])
    sidx = {"Energy": "^CNXENERGY", "Information Technology": "^CNXIT", "Banks": "^NSEBANK", "FMCG": "^CNXFMCG"}
    out = attribution.run(hold, rets, "^NSEI", sidx, 2.0, 1.5).set_index("symbol")
    assert out.loc["RELIANCE", "significant"]
    assert out.loc["RELIANCE", "driver"] == "stock_specific"
    assert out.loc["TCS", "sector_move_pct"] == pytest.approx(2.1)


def test_xirr_simple_one_year():
    flows = [(date(2025, 1, 1), -100), (date(2026, 1, 1), 112)]
    assert returns.xirr(flows) == pytest.approx(0.12, abs=1e-4)


def test_xirr_sip_like():
    flows = [(date(2026, m, 1), -1000) for m in range(1, 11)] + [(date(2026, 11, 1), 10500)]
    r = returns.xirr(flows)
    assert 0.05 < r < 0.20


def test_xirr_unsolvable_returns_none():
    assert returns.xirr([(date(2026, 1, 1), -100)]) is None


def test_mf_cashflows_signs():
    tx = [{"date": date(2026, 1, 1), "amount": 1000, "type": "PURCHASE"},
          {"date": date(2026, 6, 1), "amount": -300, "type": "REDEMPTION"}]
    flows = returns.mf_cashflows(tx, 900, date(2026, 11, 1))
    assert flows == [(date(2026, 1, 1), -1000.0), (date(2026, 6, 1), 300.0), (date(2026, 11, 1), 900.0)]


def test_risk_metrics_and_scenarios():
    rng = np.random.default_rng(3)
    bench = pd.Series(rng.normal(0.05, 1, 300))
    port = 0.9 * bench + pd.Series(rng.normal(0, 0.3, 300))
    m = risk.metrics(port, bench)
    assert m["beta"] == pytest.approx(0.9, abs=0.08)
    assert m["max_drawdown_pct"] < 0
    sc = risk.scenarios([(0.5, 1.2), (0.5, None)], 100000, [-10])
    assert sc[0]["portfolio_move_pct"] == pytest.approx(-11.0)


def test_portfolio_returns_reweights_missing():
    rets = pd.DataFrame({"A": [1.0, 2.0], "B": [np.nan, 4.0]})
    pr = risk.portfolio_returns(rets, {"A": 0.5, "B": 0.5})
    assert pr.tolist() == [1.0, 3.0]


def test_diversification_lookthrough_overlap_and_flags():
    h = _h([["INE040A01034", "HDFC Bank", "stock", 60000, 60000, "Banks", "Large", "Equity", None, "HDFCBANK"],
            ["INF179K01YV8", "Large Cap Fund", "mf", 40000, 40000, None, "Large", "Equity",
             "Equity Scheme - Large Cap Fund", "119551"],
            ["INF879O01027", "Flexi Cap Fund", "mf", 20000, 20000, None, "Multi", "Equity",
             "Equity Scheme - Flexi Cap Fund", "122639"]])
    d = diversification.analyse(h, fx.constituents(), {"max_single_stock_pct": 10, "max_sector_pct": 30,
                                                       "max_fund_overlap_pct": 10, "max_top5_pct": 50})
    top = d["top_exposures"][0]
    assert top["name"] == "HDFC Bank"
    # 60000 direct + 10% of 40000 + 8% of 20000 = 65600 of 120000
    assert top["value"] == pytest.approx(65600)
    assert d["fund_overlap"][0]["shared_stocks"] == 2
    assert d["fund_overlap"][0]["overlap_pct"] == pytest.approx(14.0)
    assert any("HDFC Bank" in f for f in d["flags"])
    assert any("Banks" in f for f in d["flags"])
    assert any("No debt" in s for s in d["suggestions"])
    assert d["effective_holdings"] > 0


def test_diversification_without_constituents_keeps_funds_whole():
    h = _h([["X", "X Fund", "mf", 100, 100, None, "Large", "Equity", "Equity Scheme - Large Cap Fund", "1"]])
    d = diversification.analyse(h, None, {})
    assert d["funds_without_breakdown"] == ["X Fund"]
    assert not any("X Fund is" in f for f in d["flags"])
