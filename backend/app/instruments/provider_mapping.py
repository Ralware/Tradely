from __future__ import annotations

from typing import Any

from app.core.instruments import ALLOWED_EXCHANGES

# A provider is selected from the resolved instrument, never from a symbol that
# happens to exist somewhere. Each entry has one verified primary adapter.
PROVIDER_ADAPTERS: dict[str, dict[str, Any]] = {
    "tejhq": {
        "name": "TejHQ",
        "markets": {"india"},
        "exchanges": {"NSE", "BSE"},
        "asset_types": {"equity"},
        "purpose": "Indian NSE/BSE daily OHLCV",
    },
    "yahoo": {
        "name": "Yahoo Finance (yfinance; unofficial)",
        "markets": {"global"},
        "exchanges": {"NASDAQ", "NYSE", "AMEX", "NYSEARCA"},
        "asset_types": {"equity"},
        "purpose": "International equity prices through an unofficial adapter",
    },
    "binance": {
        "name": "Binance Spot Public Market Data",
        "markets": {"crypto"},
        "exchanges": {"BINANCE"},
        "asset_types": {"crypto"},
        "purpose": "Public Binance Spot market data",
    },
}

_PROVIDER_KEY_BY_MARKET: dict[str, str] = {
    "india": "tejhq",
    "global": "yahoo",
    "crypto": "binance",
}


def provider_key_for(instrument: dict[str, Any] | Any) -> str:
    market = _get(instrument, "market")
    key = _PROVIDER_KEY_BY_MARKET.get(str(market))
    if key is None:
        raise ValueError(f"No verified market-data provider for market {market!r}")
    return key


def provider_name_for(market: str) -> str:
    key = _PROVIDER_KEY_BY_MARKET.get(market)
    if key is None:
        raise ValueError(f"No verified market-data provider for market {market!r}")
    return PROVIDER_ADAPTERS[key]["name"]


def verify_instrument_mapping(instrument: dict[str, Any] | Any) -> None:
    """Reject any instrument whose market, exchange or asset class disagree."""
    market = str(_get(instrument, "market") or "")
    exchange = str(_get(instrument, "exchange") or "").upper()
    asset_type = str(_get(instrument, "asset_type") or "")
    key = provider_key_for(instrument)
    adapter = PROVIDER_ADAPTERS[key]
    if market not in adapter["markets"]:
        raise ValueError(f"Provider {adapter['name']} does not serve the {market} market")
    if exchange not in adapter["exchanges"]:
        raise ValueError(f"Exchange {exchange} is not supported by {adapter['name']}")
    if asset_type not in adapter["asset_types"]:
        raise ValueError(f"Asset class {asset_type} is not supported by {adapter['name']}")
    if exchange not in ALLOWED_EXCHANGES.get(market, set()):
        raise ValueError(f"Exchange {exchange} is not a verified {market} exchange")
    provider_symbol = str(_get(instrument, "provider_symbol") or "").strip()
    if not provider_symbol:
        raise ValueError("Instrument has no provider-specific symbol")


def provider_chain(instrument: dict[str, Any] | Any) -> list[str]:
    """Verified adapters for this exact instrument.

    The fallback list is intentionally single-entry. None of the configured
    providers is verified to return the exact same instrument and capability
    set, so substituting a different provider would be a silent identity change.
    """
    verify_instrument_mapping(instrument)
    return [provider_key_for(instrument)]


def provider_symbol_for(instrument: dict[str, Any] | Any) -> str:
    verify_instrument_mapping(instrument)
    return str(_get(instrument, "provider_symbol"))


def _get(instrument: dict[str, Any] | Any, key: str) -> Any:
    if isinstance(instrument, dict):
        return instrument.get(key)
    return getattr(instrument, key, None)
