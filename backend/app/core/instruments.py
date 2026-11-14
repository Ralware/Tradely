from __future__ import annotations

import re

from app.core.models import Instrument, Market

# Exchange and provider routing is deliberately explicit. A symbol is never
# looked up on a different exchange merely because it exists there.
MARKET_DEFAULTS: dict[str, dict[str, str]] = {
    "india": {
        "exchange": "NSE",
        "currency": "INR",
        "asset_type": "equity",
        "provider": "TejHQ",
    },
    "global": {
        "exchange": "NASDAQ",
        "currency": "USD",
        "asset_type": "equity",
        "provider": "Yahoo Finance (yfinance; unofficial)",
    },
    "crypto": {
        "exchange": "BINANCE",
        "currency": "USDT",
        "asset_type": "crypto",
        "provider": "Binance Spot Public Market Data",
    },
}

ALLOWED_EXCHANGES: dict[str, set[str]] = {
    "india": {"NSE", "BSE"},
    "global": {"NASDAQ", "NYSE", "AMEX", "NYSEARCA"},
    "crypto": {"BINANCE"},
}

CRYPTO_QUOTE_ASSETS = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB", "EUR", "TRY", "BRL", "GBP", "AUD", "USD")

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._&-]{0,29}$")


def split_crypto_pair(symbol: str) -> tuple[str, str] | None:
    """Split ``BTCUSDT`` into ``("BTC", "USDT")`` using verified quote assets.

    The longest matching quote suffix wins so ``ETHBTC`` is ETH/BTC and never
    ETHB/BTC. The quote asset is never assumed: an unknown suffix returns None.
    """
    value = symbol.strip().upper()
    for quote in sorted(CRYPTO_QUOTE_ASSETS, key=len, reverse=True):
        if len(value) > len(quote) and value.endswith(quote):
            return value[: -len(quote)], quote
    return None



def normalize_symbol(symbol: str, market: Market | str) -> str:
    value = symbol.strip().upper()
    if market == "crypto":
        # Accept BTC/USDT and BTC-USDT input but never append a quote asset the
        # owner did not select. The resulting pair must be explicit.
        value = value.replace("/", "").replace("-", "").replace("_", "")
    if not _SYMBOL_RE.fullmatch(value):
        raise ValueError("Invalid symbol format")
    if market == "crypto" and not any(
        len(value) > len(asset) and value.endswith(asset) for asset in CRYPTO_QUOTE_ASSETS
    ):
        raise ValueError(
            "Crypto instruments must use an exact supported pair, for example BTCUSDT"
        )
    return value


def resolve_exchange(market: Market, exchange: str | None) -> str:
    allowed = ALLOWED_EXCHANGES[market]
    value = (exchange or MARKET_DEFAULTS[market]["exchange"]).strip().upper()
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(f"{exchange or value!r} is not a supported {market} exchange; use {options}")
    return value


def provider_for(market: Market, exchange: str) -> str:
    return MARKET_DEFAULTS[market]["provider"]


def provider_symbol_for(symbol: str, market: Market, exchange: str) -> str:
    """Provider-specific symbol without silently changing the canonical symbol."""
    if market == "crypto":
        return symbol
    return symbol


def instrument_id_for(symbol: str, market: Market, exchange: str) -> str:
    return f"{market}:{exchange.upper()}:{symbol.upper()}"


def canonical_instrument(
    symbol: str,
    market: Market,
    *,
    exchange: str | None = None,
    name: str | None = None,
    currency: str | None = None,
    asset_type: str | None = None,
    provider: str | None = None,
    provider_symbol: str | None = None,
) -> Instrument:
    exchange_code = resolve_exchange(market, exchange)
    clean_symbol = normalize_symbol(symbol, market)
    default_currency = MARKET_DEFAULTS[market]["currency"]
    resolved_currency = (currency or default_currency).strip().upper()
    resolved_asset_type = asset_type or MARKET_DEFAULTS[market]["asset_type"]
    if resolved_asset_type not in {"equity", "crypto"}:
        raise ValueError("asset_type must be equity or crypto")
    if market == "crypto" and resolved_asset_type != "crypto":
        raise ValueError("crypto market instruments must use asset_type crypto")
    if market != "crypto" and resolved_asset_type != "equity":
        raise ValueError("equity market instruments must use asset_type equity")
    base_currency: str | None = None
    quote_currency: str | None = None
    settlement_currency: str | None = None
    trading_pair: str | None = None
    if market == "crypto":
        pair = split_crypto_pair(clean_symbol)
        if pair is None:
            raise ValueError("Crypto instruments must use an exact supported pair")
        base_currency, quote_currency = pair
        settlement_currency = quote_currency
        trading_pair = f"{base_currency}/{quote_currency}"
        if resolved_currency == MARKET_DEFAULTS[market]["currency"]:
            resolved_currency = quote_currency
    else:
        base_currency = resolved_currency
        quote_currency = resolved_currency
        settlement_currency = resolved_currency
    return Instrument(
        instrument_id=instrument_id_for(clean_symbol, market, exchange_code),
        symbol=clean_symbol,
        name=(name or "").strip() or clean_symbol,
        market=market,
        exchange=exchange_code,
        currency=resolved_currency,
        asset_type=resolved_asset_type,  # type: ignore[arg-type]
        provider=(provider or "").strip() or provider_for(market, exchange_code),
        provider_symbol=(provider_symbol or "").strip()
        or provider_symbol_for(clean_symbol, market, exchange_code),
        display_name=(name or "").strip() or clean_symbol,
        base_currency=base_currency,
        quote_currency=quote_currency,
        settlement_currency=settlement_currency,
        trading_pair=trading_pair,
    )


def parse_instrument_id(instrument_id: str) -> tuple[str, str, str] | None:
    parts = instrument_id.split(":", 2)
    if len(parts) != 3:
        return None
    market, exchange, symbol = parts
    if market not in {"india", "global", "crypto"}:
        return None
    try:
        return market, resolve_exchange(market, exchange), normalize_symbol(symbol, market)  # type: ignore[arg-type]
    except ValueError:
        return None
