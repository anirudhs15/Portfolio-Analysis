"""Mutual fund NAVs: AMFI's daily file (latest NAV + category) and mfapi.in (history).

Both are free and need no account.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import requests

log = logging.getLogger(__name__)

AMFI_URLS = [
    "https://portal.amfiindia.com/spages/NAVAll.txt",
    "https://www.amfiindia.com/spages/NAVAll.txt",
]
MFAPI_URL = "https://api.mfapi.in/mf/{code}"


@dataclass
class NavRecord:
    scheme_code: str
    isins: tuple[str, ...]
    scheme_name: str
    nav: float
    nav_date: date
    amc: str | None
    category: str | None      # e.g. "Equity Scheme - Large Cap Fund"
    scheme_type: str | None   # e.g. "Open Ended Schemes"


def _get(url: str, attempts: int = 3, timeout: int = 30) -> requests.Response:
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "portfolio-analytics/0.1"})
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            log.warning("GET %s failed (attempt %d): %s", url, i + 1, e)
            time.sleep(2 * (2 ** i))
    raise last


_CAT_RE = re.compile(r"^(?P<type>[^()]+)\((?P<cat>.+)\)\s*$")


def parse_navall(text: str) -> dict[str, NavRecord]:
    """Parses NAVAll.txt into {isin: NavRecord} (each scheme is indexed under every ISIN it has)."""
    out: dict[str, NavRecord] = {}
    category = scheme_type = amc = None
    # Column positions come from the header, because AMFI has changed the layout before
    # (Nov 2026: "Plan" and "Option" columns added before the NAV).
    idx = {"code": 0, "isin1": 1, "isin2": 2, "name": 3, "nav": 4, "date": 5}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Scheme Code"):
            cols = [c.strip().lower() for c in line.split(";")]
            for i, c in enumerate(cols):
                if c.startswith("scheme code"):
                    idx["code"] = i
                elif "isin div payout" in c or "isin growth" in c:
                    idx["isin1"] = i
                elif "reinvestment" in c:
                    idx["isin2"] = i
                elif c == "scheme name":
                    idx["name"] = i
                elif "net asset value" in c:
                    idx["nav"] = i
                elif c == "date":
                    idx["date"] = i
            continue
        if ";" not in line:
            m = _CAT_RE.match(line)
            if m and "Scheme" in m.group("type"):
                scheme_type, category = m.group("type").strip(), m.group("cat").strip()
            else:
                amc = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) <= max(idx.values()):
            continue
        code, isin1, isin2 = parts[idx["code"]], parts[idx["isin1"]], parts[idx["isin2"]]
        name, nav_s, date_s = parts[idx["name"]], parts[idx["nav"]], parts[idx["date"]]
        try:
            nav = float(nav_s)
            nav_date = datetime.strptime(date_s, "%d-%b-%Y").date()
        except ValueError:
            continue  # "N.A." or malformed rows
        isins = tuple(i for i in (isin1, isin2) if i and i != "-" and len(i) == 12)
        rec = NavRecord(code, isins, name, nav, nav_date, amc, category, scheme_type)
        for i in isins:
            out[i] = rec
    return out


def fetch_latest() -> dict[str, NavRecord]:
    """Tries each AMFI URL until one returns a parseable NAV file."""
    problems = []
    for url in AMFI_URLS:
        try:
            text = _get(url).text
        except Exception as e:
            problems.append(f"{url}: {e}")
            continue
        navs = parse_navall(text)
        if navs:
            log.info("Parsed %d ISINs from %s", len(navs), url)
            return navs
        problems.append(f"{url}: no NAV rows (starts with {text[:120]!r})")
        log.warning(problems[-1])
    raise RuntimeError("AMFI NAV file unavailable: " + " | ".join(problems))


def parse_mfapi(js: dict) -> list[tuple[date, float]]:
    out = []
    for row in js.get("data", []):
        try:
            out.append((datetime.strptime(row["date"], "%d-%m-%Y").date(), float(row["nav"])))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def fetch_history(scheme_code: str) -> list[tuple[date, float]]:
    """Full NAV history for one scheme, oldest first."""
    return parse_mfapi(_get(MFAPI_URL.format(code=scheme_code)).json())


def market_cap_bucket_for_category(category: str | None) -> str | None:
    """Maps a SEBI fund category to the market-cap bucket it mostly holds."""
    if not category:
        return None
    c = category.lower()
    if "large & mid" in c:
        return "Large & Mid"
    if "large cap" in c or "index" in c and "nifty 50" in c:
        return "Large"
    if "mid cap" in c:
        return "Mid"
    if "small cap" in c:
        return "Small"
    if any(k in c for k in ("flexi", "multi cap", "focused", "elss", "value", "contra", "dividend yield")):
        return "Multi"
    return None


def asset_class_for_category(category: str | None, name: str | None = None) -> str:
    # Gold and silver funds/ETFs/FoFs are commodities whatever SEBI category they sit in.
    text = f"{category or ''} {name or ''}".lower()
    if "silver" in text or "gold" in text:
        return "Gold & Silver"
    if not category:
        return "Unknown"
    c = category.lower()
    if c.startswith("equity") or "elss" in c:
        return "Equity"
    if c.startswith("debt"):
        return "Debt"
    if c.startswith("hybrid"):
        return "Hybrid"
    if "index" in c or "etf" in c:
        return "Equity"
    if "fof" in c or "fund of funds" in c:
        return "FoF"
    if "gold" in c or "commodit" in c:
        return "Gold/Commodity"
    return "Other"
