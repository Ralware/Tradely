from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.instruments import normalize_symbol
from app.instruments.catalogue_data import _crypto, _equity
from app.providers.tradingview import TradingViewBridge

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


def refresh_catalogue(
    db: Any,
    settings: Settings,
    *,
    query: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Import supported listings from live TradingView search.

    There is no direct Binance/NSE catalogue call any more. An explicit query
    returns matching supported listings; without one the endpoint reports that
    live search is available on demand instead of pretending to enumerate every
    exchange.
    """
    report: dict[str, Any] = {"updated": 0, "sources": {}, "errors": []}
    if not query:
        report["sources"]["TradingView market search"] = {
            "entries": 0,
            "note": (
                "Provide q=... to import matching supported listings. Unknown "
                "symbols are also resolved through live TradingView search on demand."
            ),
        }
        return report
    try:
        bridge = TradingViewBridge(settings)
        results = bridge.search(query, limit=min(max(1, limit), 50))
        entries = [
            entry
            for entry in (entry_from_search_result(item) for item in results)
            if entry is not None
        ]
        written = db.upsert_catalogue_entries(entries)
        report["sources"]["TradingView market search"] = {
            "entries": written,
            "query": query,
        }
        report["updated"] = written
    except Exception as exc:  # bridge/network failures must stay explicit
        report["sources"]["TradingView market search"] = {"entries": 0, "query": query}
        report["errors"].append(f"TradingView market search: {exc}")
    return report
