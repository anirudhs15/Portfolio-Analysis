from pathlib import Path

from portfolio.config import load_settings


def test_manual_costs_parsed(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("benchmark: {primary: '^NSEI'}\n")
    (tmp_path / "manual_costs.yaml").write_text(
        "costs:\n"
        "  inf247l01445: {name: Motilal, invested: 55000}\n"
        "  INF846K015J4: {name: Axis Silver, invested: }\n"
        "  INF457M01133: 120\n"
    )
    s = load_settings(tmp_path)
    assert s.manual_costs == {"INF247L01445": 55000.0, "INF457M01133": 120.0}
