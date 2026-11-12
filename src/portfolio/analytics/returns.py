"""Return measures: absolute gain, XIRR (money-weighted) and CAGR."""
from __future__ import annotations

from datetime import date


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Annualised internal rate of return for dated cash flows.

    Convention: money invested is negative, money received (incl. current value) positive.
    Returns a fraction (0.12 = 12%), or None if it cannot be solved.
    """
    flows = sorted((d, a) for d, a in cashflows if a)
    if len(flows) < 2 or not any(a > 0 for _, a in flows) or not any(a < 0 for _, a in flows):
        return None
    t0 = flows[0][0]
    years = [((d - t0).days / 365.0, a) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in years)

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for t, a in years)

    r = guess
    for _ in range(100):  # Newton's method
        f, df = npv(r), dnpv(r)
        if df == 0:
            break
        nr = r - f / df
        if nr <= -0.9999:
            nr = (r - 0.9999) / 2
        if abs(nr - r) < 1e-9:
            return nr
        r = nr

    lo, hi = -0.9999, 10.0  # fall back to bisection
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def mf_cashflows(transactions: list[dict], current_value: float, as_of: date) -> list[tuple[date, float]]:
    """Builds XIRR cash flows for one fund from CAS transactions plus today's value."""
    flows: list[tuple[date, float]] = []
    for t in transactions:
        amt = t.get("amount")
        if amt is None:
            continue
        typ = t.get("type", "")
        if typ in ("DIVIDEND_REINVEST",):
            continue  # reinvested dividends are not new money
        # In CAS, purchases have positive amounts, redemptions negative; invert to investor view.
        flows.append((t["date"], -float(amt)))
    flows.append((as_of, float(current_value)))
    return flows


def absolute(cost: float, value: float) -> dict:
    gain = value - cost
    return {"gain_inr": gain, "gain_pct": (gain / cost * 100) if cost else None}


def cagr(start_value: float, end_value: float, years: float) -> float | None:
    if start_value <= 0 or years <= 0:
        return None
    return (end_value / start_value) ** (1 / years) - 1
