"""Loads settings, SIP schedule and sector map from the config/ folder."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("PORTFOLIO_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


@dataclass
class Settings:
    raw: dict
    sips: list[dict] = field(default_factory=list)
    sector_map: dict[str, dict] = field(default_factory=dict)
    manual_costs: dict[str, float] = field(default_factory=dict)  # ISIN -> total amount invested

    def get(self, *keys, default=None):
        node = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def benchmark(self) -> str:
        return self.get("benchmark", "primary", default="^NSEI")

    @property
    def sector_index(self) -> dict[str, str]:
        return self.get("sector_index", default={}) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    cdir = Path(config_dir) if config_dir else CONFIG_DIR
    raw = yaml.safe_load((cdir / "settings.yaml").read_text()) or {}

    sips: list[dict] = []
    sip_file = cdir / "sip_schedule.yaml"
    if sip_file.exists():
        sips = (yaml.safe_load(sip_file.read_text()) or {}).get("sips") or []

    sector_map: dict[str, dict] = {}
    smap = cdir / "sector_map.csv"
    if smap.exists():
        with smap.open(newline="") as f:
            for row in csv.DictReader(f):
                sector_map[row["symbol"].strip().upper()] = {
                    "sector": row.get("sector", "").strip() or None,
                    "industry": row.get("industry", "").strip() or None,
                    "market_cap_bucket": row.get("market_cap_bucket", "").strip() or None,
                }
    manual_costs: dict[str, float] = {}
    mfile = cdir / "manual_costs.yaml"
    if mfile.exists():
        for isin, entry in ((yaml.safe_load(mfile.read_text()) or {}).get("costs") or {}).items():
            amt = entry.get("invested") if isinstance(entry, dict) else entry
            if amt not in (None, "", 0):
                manual_costs[str(isin).strip().upper()] = float(amt)
    return Settings(raw=raw, sips=sips, sector_map=sector_map, manual_costs=manual_costs)
