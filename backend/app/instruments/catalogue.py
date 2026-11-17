from __future__ import annotations

from typing import Any

from app.core.instruments import normalize_symbol
from app.instruments.catalogue_data import _crypto, _equity

_EQUITY_EXCHANGES = {
    "NSE": ("india", "INR"),
    "BSE": ("india", "INR"),
    "NASDAQ": ("global", "USD"),
    "NYSE": ("global", "USD"),
    "AMEX": ("global", "USD"),
    "NYSEARCA": ("global", "USD"),
}


def entry_from_search_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Map one TradingView market-search row to a canonical catalogue entry."""
    exchange = str(result.get("exchange") or "").strip().upper()
    symbol = str(result.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    description = str(result.get("description") or "").strip()
    if exchange in _EQUITY_EXCHANGES:
        market, currency = _EQUITY_EXCHANGES[exchange]
        try:
            normalize_symbol(symbol, market)
        except ValueError:
            return None
        entry = _equity(symbol, description or symbol, market, exchange, currency)
    elif exchange == "BINANCE":
        try:
            entry = _crypto(symbol)
        except ValueError:
            return None
        if description:
            entry["name"] = description
            entry["display_name"] = description
    else:
        return None
    entry["catalogue_source"] = "TradingView market search (live)"
    entry["catalogue_updated_at"] = None
    return entry
