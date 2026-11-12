import json

import make_fixtures as fx
import pytest

from portfolio import run as runner
from portfolio.store import db


def test_night_run_end_to_end(fake, data_dir, settings):
    snap = runner.run("night", fake, data_dir=data_dir, settings=settings, today=fx.TODAY)

    path = data_dir / "snapshots" / f"{fx.TODAY.isoformat()}_night.json"
    assert path.exists() and (data_dir / "snapshots" / "latest_night.json").exists()
    assert json.loads(path.read_text())["run"]["mode"] == "night"

    types = {h["type"] for h in snap["holdings"]}
    assert types == {"stock", "mf"}
    assert len(snap["holdings"]) == len(fx.STOCKS) + len(fx.FUNDS)

    s = snap["summary"]
    assert s["total_value"] == pytest.approx(sum(h["market_value"] for h in snap["holdings"]), rel=1e-6)
    assert s["benchmark_change_pct"] == pytest.approx(-0.8)
    assert sum(h["weight_pct"] for h in snap["holdings"]) == pytest.approx(100, abs=0.01)

    explain = {h["symbol"] for h in snap["movers"]["to_explain"]}
    assert "RELIANCE" in explain
    rel = next(h for h in snap["holdings"] if h["symbol"] == "RELIANCE")
    assert rel["attribution"]["driver"] == "stock_specific"

    funds = [h for h in snap["holdings"] if h["type"] == "mf"]
    assert all(f["xirr_pct"] is not None for f in funds)
    debt = next(f for f in funds if "Short Duration" in f["name"])
    assert debt["sector"] == "Debt Scheme - Short Duration Fund"
    assert any(a["name"] == "Debt" for a in snap["diversification"]["by_asset_class"])

    assert snap["risk"]["metrics"]["observations"] > 200
    assert len(snap["risk"]["scenarios"]) == 3
    assert snap["history"][-1]["date"] == fx.TODAY.isoformat()
    assert snap["health"]["last_cas"]["filename"] == "sample_cas.pdf"
    assert snap["research"] == {"reasons": {}, "news": [], "events": [], "outlook": [], "market_wrap": None}

    con = db.connect(data_dir / "portfolio.duckdb")
    assert db.query(con, "SELECT COUNT(*) n FROM holdings_daily")["n"].iat[0] == 8
    assert db.query(con, "SELECT status FROM runs")["status"].iat[0] == "ok"
    con.close()


def test_close_run_shows_funds_flat_and_cas_imported_once(fake, data_dir, settings):
    runner.run("night", fake, data_dir=data_dir, settings=settings, today=fx.TODAY)
    snap = runner.run("close", fake, data_dir=data_dir, settings=settings, today=fx.TODAY)
    funds = [h for h in snap["holdings"] if h["type"] == "mf"]
    assert all(f["day_change_pct"] == pytest.approx(0) for f in funds)
    assert fake.calls.count("cas") == 1
    assert fake.calls.count("nav_latest") == 1  # close run doesn't fetch NAVs


def test_sip_projection_adds_units(fake, data_dir, settings):
    settings.sips = [{"isin": "INF879O01027", "amount": 5000, "day": 5}]
    snap = runner.run("night", fake, data_dir=data_dir, settings=settings, today=fx.TODAY)
    f = next(h for h in snap["holdings"] if h["isin"] == "INF879O01027")
    assert f["quantity"] > 300  # 300 units in CAS + the 5 Nov instalment
    assert f["units_source"] == "cas+projected"


def test_groww_outage_falls_back_to_last_holdings(data_dir, settings):
    from conftest import FakeSources

    runner.run("night", FakeSources(), data_dir=data_dir, settings=settings, today=fx.TODAY)
    snap = runner.run("close", FakeSources(fail_groww=True), data_dir=data_dir, settings=settings, today=fx.TODAY)
    assert sum(h["type"] == "stock" for h in snap["holdings"]) == len(fx.STOCKS)
    assert any("Groww holdings fetch failed" in n for n in snap["health"]["notes"])


def test_holiday_close_run_flags_market_closed(fake, data_dir, settings):
    from datetime import date

    saturday = date(2026, 11, 14)
    snap = runner.run("close", fake, data_dir=data_dir, settings=settings, today=saturday)
    assert snap["run"]["market_open_today"] is False
    assert all(h["day_change_pct"] == pytest.approx(0) for h in snap["holdings"] if h["type"] == "stock")


def test_cdsl_cas_etf_dedupe_and_missing_scheme_code(data_dir, settings):
    from conftest import FakeSources
    from portfolio.ingest import mf_cas

    class CDSLFake(FakeSources):
        def parse_cas(self, path, password):
            self.calls.append("cas")
            return mf_cas.from_dict({
                "file_type": "CDSL", "statement_period": {"from": "01-Oct-2026", "to": "31-Oct-2026"},
                "accounts": [{"type": "CDSL Demat Account",
                              "equities": [{"isin": "INE467B01029", "name": "TCS", "num_shares": 8, "price": 3400}],
                              "mutual_funds": [
                                  # an ETF Groww also reports as a stock holding (same ISIN as TCS here)
                                  {"name": "Some ETF", "isin": "INE467B01029", "amfi": None, "balance": 10},
                                  # a fund with no scheme code in the CAS
                                  {"name": "LARGE CAP DEMAT", "isin": "INF179K01YV8", "amfi": None, "balance": 100}]},
                             {"type": "Mutual Fund Folios", "mutual_funds": [
                                 {"name": "FLEXI FOLIO", "isin": "INF879O01027", "amfi": "122639",
                                  "balance": 50, "total_cost": 3000}]}]})

    snap = runner.run("night", CDSLFake(), data_dir=data_dir, settings=settings, today=fx.TODAY)
    funds = {h["isin"]: h for h in snap["holdings"] if h["type"] == "mf"}
    assert "INE467B01029" not in funds                      # ETF counted once, as a Groww holding
    assert funds["INF179K01YV8"]["symbol"] == "119551"      # scheme code recovered from AMFI by ISIN
    assert funds["INF179K01YV8"]["name"] == "Sample Large Cap Fund - Direct Growth"  # clean AMFI name
    assert snap["summary"]["cost_coverage_pct"] < 100
    rec = snap["health"]["reconciliation_vs_cas"]
    assert rec and rec[0]["cas_quantity"] == 8 and rec[0]["groww_quantity"] == 10
