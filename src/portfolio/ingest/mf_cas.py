"""Parses a Consolidated Account Statement (CAS) PDF into mutual fund holdings and transactions.

Supports both kinds of CAS:
  * CAMS / KFintech / MFCentral "detailed" CAS - holdings plus full transaction history
  * NSDL / CDSL depository CAS - holdings with average cost (no transaction history)

Personal identifiers (PAN, name, email, address) are dropped here and never stored.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)

# Transaction types that change units held; tax lines (STT, stamp duty) do not.
UNIT_TYPES = {
    "PURCHASE", "PURCHASE_SIP", "REDEMPTION", "DIVIDEND_REINVEST", "SWITCH_IN",
    "SWITCH_IN_MERGER", "SWITCH_OUT", "SWITCH_OUT_MERGER", "GIFT_IN", "GIFT_OUT",
    "SEGREGATION", "REVERSAL",
}


@dataclass
class MFHolding:
    isin: str | None
    amfi_code: str | None
    name: str
    amc: str | None
    folio: str | None
    units: float
    cost: float | None
    statement_nav: float | None = None
    statement_date: date | None = None


@dataclass
class MFTransaction:
    isin: str | None
    amfi_code: str | None
    date: date
    type: str
    units: float
    nav: float | None
    amount: float | None


@dataclass
class DematEquity:
    isin: str
    name: str
    quantity: float
    price: float | None


@dataclass
class CASResult:
    file_type: str
    period_to: date | None
    holdings: list[MFHolding] = field(default_factory=list)
    transactions: list[MFTransaction] = field(default_factory=list)
    equities: list[DematEquity] = field(default_factory=list)   # depository CAS only
    warnings: list[str] = field(default_factory=list)

    def merged_holdings(self) -> list[MFHolding]:
        """One row per ISIN: the same fund can sit in a demat account AND a folio."""
        by: dict[str, MFHolding] = {}
        for h in self.holdings:
            key = h.isin or h.name
            if key not in by:
                by[key] = MFHolding(**h.__dict__)
                continue
            m = by[key]
            m.units += h.units
            # Cost is only meaningful if known for every part of the position.
            m.cost = (m.cost + h.cost) if (m.cost is not None and h.cost is not None) else None
            m.amfi_code = m.amfi_code or h.amfi_code
            m.amc = m.amc or h.amc
            m.folio = ", ".join(x for x in (m.folio, h.folio) if x)
        return list(by.values())


def _f(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float, Decimal)):
        return float(x)
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def _d(x) -> date | None:
    if x is None or isinstance(x, date):
        return x
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(x), fmt).date()
        except ValueError:
            pass
    return None


def from_dict(data: dict) -> CASResult:
    """Builds a CASResult from casparser's dict output (either CAS kind)."""
    period = data.get("statement_period") or {}
    res = CASResult(
        file_type=str(data.get("file_type") or data.get("cas_type") or "UNKNOWN"),
        period_to=_d(period.get("to")),
        warnings=[str(w) for w in (data.get("parse_warnings") or [])],
    )

    # CAMS / KFintech detailed statement
    for folio in data.get("folios") or []:
        for s in folio.get("schemes") or []:
            units = _f(s.get("close_calculated")) or _f(s.get("close")) or 0.0
            val = s.get("valuation") or {}
            isin, amfi = s.get("isin"), s.get("amfi")
            if units > 0.0001:
                res.holdings.append(
                    MFHolding(
                        isin=isin, amfi_code=str(amfi) if amfi else None, name=s.get("scheme", "").strip(),
                        amc=folio.get("amc"), folio=folio.get("folio"), units=units,
                        cost=_f(val.get("cost")), statement_nav=_f(val.get("nav")),
                        statement_date=_d(val.get("date")),
                    )
                )
            for t in s.get("transactions") or []:
                ttype = str(t.get("type") or "UNKNOWN").split(".")[-1]
                u = _f(t.get("units"))
                if ttype not in UNIT_TYPES or not u:
                    continue
                res.transactions.append(
                    MFTransaction(isin, str(amfi) if amfi else None, _d(t.get("date")), ttype,
                                  u, _f(t.get("nav")), _f(t.get("amount")))
                )

    # NSDL / CDSL depository statement
    for acct in data.get("accounts") or []:
        for eq in acct.get("equities") or []:
            q = _f(eq.get("num_shares")) or 0.0
            if q > 0 and eq.get("isin"):
                res.equities.append(DematEquity(eq["isin"], (eq.get("name") or "").strip(), q, _f(eq.get("price"))))
        for mf in acct.get("mutual_funds") or []:
            units = _f(mf.get("balance")) or 0.0
            if units <= 0.0001:
                continue
            avg = _f(mf.get("avg_cost"))
            res.holdings.append(
                MFHolding(
                    isin=mf.get("isin"), amfi_code=str(mf["amfi"]) if mf.get("amfi") else None,
                    name=(mf.get("name") or "").strip(), amc=None, folio=mf.get("folio"), units=units,
                    cost=_f(mf.get("total_cost")) or (avg * units if avg else None),
                    statement_nav=_f(mf.get("nav")), statement_date=res.period_to,
                )
            )
    return res


def parse_pdf(path: str | Path, password: str = "") -> CASResult:
    import casparser

    data = casparser.read_cas_pdf(str(path), password, output="dict")
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    res = from_dict(data)
    log.info("CAS %s: %d MF holdings, %d transactions", Path(path).name, len(res.holdings), len(res.transactions))
    return res


def latest_cas_file(cas_dir: Path) -> Path | None:
    pdfs = sorted(cas_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    return pdfs[-1] if pdfs else None
