from __future__ import annotations

from typing import Any

# One verified read-only provider serves every supported market. The adapter is
# selected from the resolved instrument, never from a symbol that happens to
# exist somewhere else.
_PROVIDER_KEY_BY_MARKET: dict[str, str] = {
    "india": "tradingview",
    "global": "tradingview",
    "crypto": "tradingview",
}


def provider_key_for(instrument: dict[str, Any] | Any) -> str:
    market = _get(instrument, "market")
    key = _PROVIDER_KEY_BY_MARKET.get(str(market))
    if key is None:
        raise ValueError(f"No verified market-data provider for market {market!r}")
    return key


def _get(instrument: dict[str, Any] | Any, key: str) -> Any:
    if isinstance(instrument, dict):
        return instrument.get(key)
    return getattr(instrument, key, None)
