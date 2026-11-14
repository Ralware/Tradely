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

_BINANCE_STREAM = True
_BINANCE_QUANTITY_SOURCE = "Binance exchangeInfo (verified at request time)"


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
    """Derive only the capabilities the verified provider actually offers."""
    payload = dict(instrument) if isinstance(instrument, dict) else instrument.model_dump()
    market = str(payload.get("market") or "")
    status = str(payload.get("status") or "active").lower()
    provider_key = provider_key_for(payload)
    intervals = _intervals(payload)
    active = status in {"active", "listed"}
    key = provider_key

    if key == "tejhq":
        adjusted = bool(settings and settings.tejhq_api_key)
        limitations = [
            "TejHQ currently exposes completed daily candles only.",
            "Quotes are end-of-day, not real-time.",
        ]
        if not adjusted:
            limitations.append(
                "Corporate-action-adjusted Indian history requires a TejHQ API key; "
                "backtesting and actionable signals are suppressed without it."
            )
        capabilities = InstrumentCapabilities(
            instrument_id=str(payload.get("instrument_id") or ""),
            status=status,
            quote_available=active,
            real_time_streaming=False,
            historical_ohlcv=active,
            supported_intervals=intervals,
            adjusted_history=adjusted,
            technicals=active,
            backtesting_eligible=active and adjusted,
            corporate_events=False,
            news=active,
            provider=str(payload.get("provider") or ""),
            provider_key=key,
            quote_freshness="end_of_day",
            quantity=TradingQuantityRules(
                quantity_step=1,
                min_quantity=1,
                fractional=False,
                min_notional=0,
                source="Indian equity whole-share default",
            ),
            data_limitations=limitations,
        )
    elif key == "binance":
        pair = split_crypto_pair(str(payload.get("symbol") or ""))
        limitations = [
            "Binance Spot public market data only; no account or order execution.",
            "Prices are unadjusted exchange prices.",
        ]
        capabilities = InstrumentCapabilities(
            instrument_id=str(payload.get("instrument_id") or ""),
            status=status,
            quote_available=active and pair is not None,
            real_time_streaming=active and _BINANCE_STREAM and pair is not None,
            historical_ohlcv=active and pair is not None,
            supported_intervals=intervals,
            adjusted_history=False,
            technicals=active and pair is not None,
            backtesting_eligible=active and pair is not None,
            corporate_events=False,
            news=active,
            provider=str(payload.get("provider") or ""),
            provider_key=key,
            quote_freshness="real_time",
            quantity=TradingQuantityRules(
                quantity_step=None,
                min_quantity=None,
                fractional=True,
                min_notional=None,
                source=_BINANCE_QUANTITY_SOURCE,
            ),
            data_limitations=limitations,
        )
    else:
        limitations = [
            "Yahoo Finance is an unofficial adapter; availability and delay vary.",
            "Yahoo history is adjusted for splits and dividends.",
        ]
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
            news=active,
            provider=str(payload.get("provider") or ""),
            provider_key=key,
            quote_freshness="delayed_or_end_of_day",
            quantity=TradingQuantityRules(
                quantity_step=1,
                min_quantity=1,
                fractional=False,
                min_notional=0,
                source="International equity whole-share default",
            ),
            data_limitations=limitations,
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
