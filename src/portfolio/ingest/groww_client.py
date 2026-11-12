"""Read-only access to Groww: TOTP login and stock holdings.

Safety: this module deliberately exposes ONLY read endpoints. Nothing in this
project may place, modify or cancel orders; tests/test_safety.py enforces it.

Credentials come from environment variables set as GitHub Actions secrets:
    GROWW_TOTP_TOKEN   - the TOTP token from Groww Cloud API Keys page
    GROWW_TOTP_SECRET  - the TOTP secret (base32 text shown beside the QR code)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


class GrowwAuthError(RuntimeError):
    pass


@dataclass
class StockHolding:
    isin: str
    symbol: str
    quantity: float
    avg_price: float
    pledged: float = 0.0
    locked: float = 0.0

    @property
    def cost(self) -> float:
        return self.quantity * self.avg_price


def _retry(fn, attempts: int = 3, base_delay: float = 2.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # network or API error
            last = e
            log.warning("Groww call failed (attempt %d/%d): %s", i + 1, attempts, e)
            time.sleep(base_delay * (2 ** i))
    raise last


def _access_token() -> str:
    token = os.environ.get("GROWW_TOTP_TOKEN", "").strip()
    secret = os.environ.get("GROWW_TOTP_SECRET", "").strip().replace(" ", "")
    if not token or not secret:
        raise GrowwAuthError(
            "GROWW_TOTP_TOKEN and GROWW_TOTP_SECRET must be set "
            "(GitHub repo -> Settings -> Secrets and variables -> Actions)."
        )
    import pyotp
    from growwapi import GrowwAPI

    def call():
        return GrowwAPI.get_access_token(api_key=token, totp=pyotp.TOTP(secret).now())

    try:
        return _retry(call)
    except Exception as e:
        raise GrowwAuthError(f"Could not get a Groww access token: {e}") from e


def _client():
    from growwapi import GrowwAPI

    return GrowwAPI(_access_token())


def parse_holdings(response: dict) -> list[StockHolding]:
    """Accepts either the SDK's parsed payload or the raw REST JSON."""
    body = response.get("payload", response) if isinstance(response, dict) else {}
    out = []
    for h in body.get("holdings", []) or []:
        qty = float(h.get("quantity") or 0)
        if qty <= 0:
            continue
        out.append(
            StockHolding(
                isin=h["isin"],
                symbol=str(h.get("trading_symbol", "")).replace("-EQ", "").upper(),
                quantity=qty,
                avg_price=float(h.get("average_price") or 0),
                pledged=float(h.get("pledge_quantity") or 0),
                locked=float(h.get("demat_locked_quantity") or 0),
            )
        )
    return out


def fetch_holdings() -> list[StockHolding]:
    client = _client()
    resp = _retry(lambda: client.get_holdings_for_user(timeout=20))
    holdings = parse_holdings(resp)
    log.info("Fetched %d stock holdings from Groww", len(holdings))
    return holdings


def fetch_ltp(symbols: list[str]) -> dict[str, float]:
    """Live prices via Groww. Needs the paid Live Data plan; callers fall back to Yahoo."""
    client = _client()
    out: dict[str, float] = {}
    for i in range(0, len(symbols), 50):
        batch = tuple(f"NSE_{s}" for s in symbols[i : i + 50])
        resp = _retry(lambda: client.get_ltp(exchange_trading_symbols=batch, segment="CASH", timeout=20))
        body = resp.get("payload", resp)
        for k, v in body.items():
            out[k.replace("NSE_", "")] = float(v)
    return out
