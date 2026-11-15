from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.instruments import split_crypto_pair
from app.instruments.catalogue_data import (
    CRYPTO_INTERVALS,
    GLOBAL_INTERVALS,
    INDIA_INTERVALS,
)
from app.instruments.models import InstrumentCapabilities, TradingQuantityRules
from app.instruments.provider_mapping import provider_key_for


def _get(instrument: dict[str, Any] | Any, key: str) -> Any:
    if isinstance(instrument, dict):
        return instrument.get(key)
    return getattr(instrument, key, None)


def _intervals(instrument: dict[str, Any]) -> list[str]:
    configured = _get(instrument, "supported_intervals")
    if isinstance(configured, str):
        configured = [item for item in configured.split(",") if item]
    if configured:
        return list(configured)
    market = _get(instrument, "market")
    if market == "india":
        return list(INDIA_INTERVALS)
    if market == "crypto":
        return list(CRYPTO_INTERVALS)
    return list(GLOBAL_INTERVALS)


def capabilities_for(
    instrument: dict[str, Any] | Any,
    settings: Settings | None = None,
) -> InstrumentCapabilities:
    """Describe only what the TradingView-backed bridge actually offers."""
    payload = dict(instrument) if isinstance(instrument, dict) else instrument.model_dump()
    market = str(payload.get("market") or "")
    status = str(payload.get("status") or "active").lower()
    provider_key = provider_key_for(payload)
    intervals = _intervals(payload)
    active = status in {"active", "listed"}

    limitations = [
        "TradingView is an unofficial community API backed by exchange feeds; "
        "availability and access limits can change without notice.",
        "Anonymous access is delayed on many exchanges: NSE data is typically "
        "15 minutes delayed and other venues vary.",
        "History is split-adjusted; dividend-adjusted history is not enabled.",
        "No news feed is provided by TradingView.",
    ]
    if market == "crypto":
        limitations.append(
            "TradingView is used for public market data only; no account or order execution."
        )
        quantity = TradingQuantityRules(
            quantity_step=None,
            min_quantity=None,
            fractional=True,
            min_notional=None,
            source="TradingView symbol metadata at request time (derived, not exchange filters)",
        )
    elif market == "india":
        limitations.append(
            "Indian intraday history can be limited or delayed for anonymous sessions."
        )
        quantity = TradingQuantityRules(
            quantity_step=1,
            min_quantity=1,
            fractional=False,
            min_notional=0,
            source="Indian equity whole-share default",
        )
    else:
        limitations.append(
            "International equity depth and delay depend on TradingView's anonymous access."
        )
        quantity = TradingQuantityRules(
            quantity_step=1,
            min_quantity=1,
            fractional=False,
            min_notional=0,
            source="International equity whole-share default",
        )

    capabilities = InstrumentCapabilities(
        instrument_id=str(payload.get("instrument_id") or ""),
        status=status,
        quote_available=active,
        real_time_streaming=False,
        historical_ohlcv=active,
        supported_intervals=intervals,
        adjusted_history=True,
        technicals=active,
        backtesting_eligible=active,
        corporate_events=False,
        news=False,
        provider=str(payload.get("provider") or ""),
        provider_key=provider_key,
        quote_freshness="real_time_or_delayed",
        quantity=quantity,
        data_limitations=limitations,
    )

    if market == "crypto" and split_crypto_pair(str(payload.get("symbol") or "")) is None:
        capabilities.quote_available = False
        capabilities.historical_ohlcv = False
        capabilities.technicals = False
        capabilities.backtesting_eligible = False
        capabilities.data_limitations.append(
            "The crypto symbol has no verified quote asset; market data is not requested."
        )

    if not active:
        capabilities.quote_available = False
        capabilities.real_time_streaming = False
        capabilities.historical_ohlcv = False
        capabilities.technicals = False
        capabilities.backtesting_eligible = False
        capabilities.news = False
        capabilities.data_limitations.append(
            f"Instrument status is {status}; market data is not requested."
        )
    return capabilities


def capabilities_payload(
    instrument: dict[str, Any] | Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    return capabilities_for(instrument, settings).model_dump(mode="json")
