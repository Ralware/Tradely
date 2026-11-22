from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.instruments import canonical_instrument, parse_instrument_id
from app.core.config import get_settings
from app.core.models import (
    AmountTransactionRequest,
    BacktestRequest,
    DirectionMode,
    HoldingTransaction,
    RiskRequest,
    RiskResult,
    WatchlistItem,
)
from app.core.trading_rules import calculate_amount_transaction
from app.instruments.resolver import (
    AmbiguousInstrumentError,
    InstrumentNotFoundError,
    InstrumentResolutionError,
    InstrumentUnavailableError,
)
from app.providers.base import ProviderError
from app.services.backtest import run_trend_breakout_backtest
from app.services.indicators import compute_indicators
from app.services.portfolio import build_ledger, detail_view, position_view, summary_view
from app.services.strategy import STRATEGY_VERSION, evaluate_trend_breakout, position_size
from app.services.technicals import build_technical_summary as build_conventional_summary
from app.services.tv_technical_rating import (
    DEPENDENCY as TV_RATING_DEPENDENCY,
    SOURCE_VERSION as TV_RATING_SOURCE_VERSION,
    build_technical_summary as build_tv_technical_summary,
    ohlcv_fingerprint,
)
from app.services.technical_rating_cache import technical_rating_cache

router = APIRouter(prefix="/api")


def _clean_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", value):
        raise HTTPException(status_code=422, detail="Invalid symbol format")
    return value


def _to_json_records(
    frame: pd.DataFrame, limit: int | None = None
) -> list[dict[str, Any]]:
    selected = (frame.tail(limit) if limit is not None else frame).copy()
    selected.index = selected.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    selected = selected.replace({float("nan"): None})
    return selected.reset_index(names="timestamp").to_dict(orient="records")


def _is_stale(frame: pd.DataFrame, market: str, interval: str = "1d") -> bool:
    if frame.empty:
        return True
    age = pd.Timestamp.now(tz="UTC") - frame.index[-1]
    # Daily EOD candle timestamps are often session-date labels, not close timestamps.
    if interval == "1wk":
        threshold = timedelta(days=14)
    elif interval == "1mo":
        threshold = timedelta(days=62)
    else:
        threshold_hours = 48 if market == "crypto" else 120
        threshold = timedelta(hours=threshold_hours)
    return age > threshold


def _scan_identity(item: dict[str, Any]) -> dict[str, Any]:
    """Canonical identity for a watchlist row, resolved once by the catalogue."""
    instrument_id = item.get("instrument_id") or ""
    if not instrument_id:
        try:
            instrument_id = canonical_instrument(
                item["symbol"], item["market"], exchange=item.get("exchange") or None
            ).instrument_id
        except Exception:
            instrument_id = ""
    return {
        "instrument_id": instrument_id,
        "name": item.get("name") or item.get("display_name") or "",
        "exchange": item.get("exchange") or "",
        "currency": item.get("currency") or "",
    }


def _market_target(
    request: Request,
    *,
    symbol: str | None,
    instrument_id: str | None,
    market: str | None,
    exchange: str | None,
) -> dict[str, Any]:
    """Resolve one canonical instrument for a market-data operation."""
    resolver = request.app.state.instrument_resolver
    try:
        return resolver.market_target(
            symbol=symbol,
            instrument_id=instrument_id,
            market=market,
            exchange=exchange,
        )
    except AmbiguousInstrumentError as exc:
        options = ", ".join(
            f"{item.get('symbol')} ({item.get('exchange')})" for item in exc.candidates[:8]
        )
        raise HTTPException(
            status_code=409,
            detail=f"{exc}. Choose One: {options}",
        ) from exc
    except InstrumentUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _cached_tv_rating_snapshot(
    *,
    instrument: dict[str, Any],
    frame: pd.DataFrame,
    fingerprint: str,
    source: str,
    interval: str,
    days: int,
    provider: str,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return the authoritative v3 snapshot, caching only completed results."""
    scope = str(instrument.get("instrument_id") or "").strip()
    if not scope:
        scope = f"{instrument.get('market')}:{instrument.get('exchange')}:{instrument.get('symbol')}"
    if refresh:
        technical_rating_cache.invalidate(scope)
    adjusted = bool(frame.attrs.get("is_adjusted", False))
    key = (
        scope, interval, days, provider, source, adjusted, fingerprint,
        TV_RATING_SOURCE_VERSION, TV_RATING_DEPENDENCY,
    )

    def calculate() -> dict[str, Any]:
        payload = build_tv_technical_summary(frame)
        payload["calculation_timestamp"] = datetime.now(UTC).isoformat()
        return payload

    request_ttl = max(1, get_settings().market_cache_seconds)
    payload, cache_hit = technical_rating_cache.get_or_compute(
        key=key,
        scope=scope,
        ttl_seconds=request_ttl,
        compute=calculate,
    )
    return {**payload, "cache_hit": cache_hit, "cache_ttl_seconds": request_ttl}


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "application": "Tradely", "mode": "private-single-user", "ai": False,
            "paper_trading": False, "order_execution": False,
            "timestamp": datetime.now(UTC).isoformat()}


@router.get("/analytics/precomputed/index")
def precomputed_index(request: Request) -> dict[str, Any]:
    """Compact manifest only; never fetches provider data or calculates analytics."""
    return request.app.state.analytics_precompute.manifest()


@router.get("/analytics/on-demand/{instrument_id}/{interval}")
def on_demand_analytics(request: Request, instrument_id: str, interval: str) -> dict[str, Any]:
    """Return valid local analytics or compute and persist one selected timeframe on a miss."""
    instrument = request.app.state.instrument_resolver.get(instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown instrument {instrument_id}")
    try:
        return request.app.state.analytics_precompute.get_or_compute_snapshot(
            str(instrument["instrument_id"]), interval
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/analytics/precomputed/{instrument_id}/{interval}")
def precomputed_snapshot(request: Request, instrument_id: str, interval: str) -> dict[str, Any]:
    if interval == "bundle":
        instrument = request.app.state.db.instrument_for_id(instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail="Unknown instrument")
        configured = instrument.get("supported_intervals") or []
        if isinstance(configured, str):
            try:
                configured = json.loads(configured)
            except ValueError:
                configured = []
        snapshots = {}
        for timeframe in configured:
            payload = request.app.state.analytics_precompute.get_snapshot(instrument_id, timeframe)
            if payload is not None:
                snapshots[timeframe] = payload
        return {"instrument_id": instrument_id, "snapshots": snapshots}
    payload = request.app.state.analytics_precompute.get_snapshot(instrument_id, interval)
    if payload is None:
        raise HTTPException(status_code=404, detail={"status": "MISSING", "instrument_id": instrument_id, "interval": interval})
    return payload


@router.post("/analytics/precompute/refresh")
def precompute_refresh(request: Request, instrument_id: str, interval: str | None = None) -> dict[str, Any]:
    engine = request.app.state.analytics_precompute
    instruments = [item for item in request.app.state.db.get_watchlist() if item.get("instrument_id") == instrument_id]
    instrument = request.app.state.db.instrument_for_id(instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Unknown instrument")
    configured = instrument.get("supported_intervals") or []
    if isinstance(configured, str):
        try:
            configured = json.loads(configured)
        except ValueError:
            configured = []
    intervals = [interval] if interval else list(configured)
    if not intervals or any(value not in configured for value in intervals):
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    jobs = [engine.enqueue(instrument_id, value, priority=100, job_type="FULL_REFRESH") for value in intervals]
    return {"status": "QUEUED", "job_ids": jobs, "watchlisted": bool(instruments)}


@router.get("/analytics/precompute/status")
def precompute_status(request: Request) -> dict[str, Any]:
    return request.app.state.analytics_precompute.status()


@router.get("/providers/status")
def provider_status(request: Request) -> dict[str, Any]:
    bridge: dict[str, Any] | None = None
    bridge_error: str | None = None
    try:
        bridge = request.app.state.market_service.bridge_health()
    except Exception as exc:
        bridge_error = str(exc)
    available = bool(bridge and bridge.get("status") == "ok")
    providers = [
        {
            "name": "TradingView (unofficial)",
            "configured": True,
            "available": available,
            "purpose": "OHLCV, quotes, symbol metadata, technical summaries and market search",
            "note": (
                "Served by the local tradingview-bridge; anonymous access is delayed "
                "on many exchanges (NSE typically 15 minutes) and deep intraday history may be limited."
            ),
        },
    ]
    return {
        "providers": providers,
        "bridge": bridge or {"status": "unavailable", "error": bridge_error},
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("/market/candles")
def candles(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
) -> dict[str, Any]:
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval, days=days, provider=provider
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    latest = frame.index[-1].to_pydatetime()
    stale = _is_stale(frame, market, interval)
    return {
        "symbol": symbol, "market": market, "exchange": exchange, "interval": interval,
        "instrument": instrument,
        "source": source, "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "freshness": "stale" if stale else frame.attrs.get("freshness", "provider-dependent"),
        "is_stale": stale, "history_truncated": bool(frame.attrs.get("history_truncated", False)),
        "history_pages": frame.attrs.get("history_pages"),
        "last_candle_at": latest.isoformat(), "count": len(frame),
        "candles": _to_json_records(frame),
        "warnings": [],
    }


@router.get("/scanner/watchlist")
def scan_watchlist(request: Request) -> dict[str, Any]:
    results = []
    for item in request.app.state.db.get_watchlist():
        try:
            frame, source = request.app.state.market_service.candles(
                item["symbol"], market=item["market"], exchange=item["exchange"] or None,
                interval="1d", days=500, provider="auto",
            )
            signal = evaluate_trend_breakout(frame, symbol=item["symbol"], market=item["market"], source=source)
            stale = _is_stale(frame, item["market"], "1d")
            adjusted = bool(frame.attrs.get("is_adjusted", False))
            if stale:
                signal.state = "STALE_DATA"
                signal.explanation = "Latest candle is stale; signal suppressed."
            elif item["market"] == "india" and not adjusted:
                signal.state = "DATA_QUALITY_ERROR"
                signal.explanation = "Unadjusted Indian history; strategy signal suppressed."
            results.append(_scan_identity(item) | {
                            "symbol": item["symbol"], "market": item["market"], "source": source,
                            "last_close": float(frame.iloc[-1]["close"]), "is_adjusted": adjusted,
                            "is_stale": stale, "strategy": signal.model_dump(mode="json")})
        except Exception as exc:
            results.append(_scan_identity(item) | {
                            "symbol": item["symbol"], "market": item["market"], "error": str(exc),
                            "strategy": {"state": "DATA_QUALITY_ERROR"}})
    return {"items": results, "count": len(results), "note": "Scanner only evaluates the configured daily strategy on completed daily bars."}


@router.get("/instruments/{symbol}/analysis")
def analyze(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
    direction_mode: DirectionMode = Query("long_only"),
) -> dict[str, Any]:
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval, days=days, provider=provider
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    indicators = compute_indicators(frame)
    latest = indicators.iloc[-1]
    values = {}
    for column, value in latest.items():
        if column not in {"open", "high", "low", "close", "volume"}:
            values[column] = None if pd.isna(value) else float(value)
    position_side = request.app.state.db.position_side_at(
        instrument["instrument_id"],
        instrument["currency"],
        datetime.now(UTC),
    )
    signal = evaluate_trend_breakout(
        frame,
        symbol=symbol,
        market=market,
        source=source,
        direction_mode=direction_mode,
        position_side=position_side,
        indicators=indicators,
    )
    adjusted = bool(frame.attrs.get("is_adjusted", False))
    stale = _is_stale(frame, market, interval)
    warnings = []
    if stale:
        warnings.append("Latest candle is stale for this market; actionable signal output is suppressed.")
        signal.state = "STALE_DATA"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.direction = None
        signal.explanation = "Signal suppressed because the latest candle exceeds the configured freshness window. Verify the provider and market session."
    if market == "india" and not adjusted:
        warnings.append("Indian equity candles are unadjusted. Corporate actions can distort long-term indicators; do not treat strategy output as actionable.")
        signal.state = "DATA_QUALITY_ERROR"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.direction = None
        signal.explanation = "Signal suppressed because TradingView did not confirm split-adjusted history for this instrument."
    signal_payload = signal.model_dump(mode="json")
    request.app.state.db.save_signal(signal_payload)
    return {
        "symbol": symbol, "market": market, "exchange": exchange, "interval": interval,
        "instrument": instrument,
        "source": source, "is_adjusted": adjusted, "is_stale": stale,
        "history_truncated": bool(frame.attrs.get("history_truncated", False)),
        "history_pages": frame.attrs.get("history_pages"),
        "as_of": frame.index[-1].isoformat(),
        "fingerprint": ohlcv_fingerprint(frame),
        "latest": {key: float(latest[key]) for key in ("open", "high", "low", "close", "volume")},
        "indicators": values,
        "strategy": signal_payload,
        "warnings": warnings,
        "candles": _to_json_records(frame),
    }


@router.get("/instruments/{symbol}/indicators")
def indicator_series(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
    limit: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    """Per-bar indicator values for chart rendering.

    Read-only and additive: this reuses the exact same ``compute_indicators``
    implementation as ``/analysis``. It does not change any existing endpoint,
    formula or signal threshold; the frontend still renders backend values only.
    """
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval, days=days, provider=provider
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    indicators = compute_indicators(frame)
    records = _to_json_records(indicators, limit=limit)
    return {
        "symbol": symbol, "market": market, "exchange": exchange, "interval": interval,
        "instrument": instrument,
        "source": source, "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "is_stale": _is_stale(frame, market, interval),
        "as_of": frame.index[-1].isoformat(),
        "fingerprint": ohlcv_fingerprint(frame),
        "count": len(records),
        "series": records,
    }


@router.get("/instruments/{symbol}/technicals")
def technical_summary(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
    method: str = Query("conventional", pattern="^(conventional|v3|tradingview)$"),
    version: str | None = None,
    bypass_cache: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Per-indicator Buy/Sell/Neutral labels and gauge counts.

    Supports both conventional thresholds (default for backward compatibility)
    and authoritative TradingView TechnicalRating v3 parity (when method='v3'
    or method='tradingview' or version='v3').
    """
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol,
            market=market,
            exchange=exchange,
            interval=interval,
            days=days,
            provider=provider,
            bypass_cache=bypass_cache or refresh,
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    fingerprint = ohlcv_fingerprint(frame)
    if version in ("v3", "3") or method in ("v3", "tradingview"):
        payload = _cached_tv_rating_snapshot(
            instrument=instrument, frame=frame, fingerprint=fingerprint,
            source=source, interval=interval, days=days, provider=provider,
            refresh=bypass_cache or refresh,
        )
    else:
        indicators = compute_indicators(frame)
        latest = indicators.iloc[-1]
        payload = build_conventional_summary(latest, close=float(latest["close"]))

    return {
        "symbol": symbol,
        "market": market,
        "exchange": exchange,
        "instrument": instrument,
        "interval": interval,
        "source": source,
        "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "is_stale": _is_stale(frame, market, interval),
        "as_of": frame.index[-1].isoformat(),
        "fingerprint": fingerprint,
        **payload,
    }


@router.get("/instruments/{symbol}/technical-ratings")
def technical_ratings(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
    bypass_cache: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """TradingView TechnicalRating v3 authoritative 26-indicator evaluation."""
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol,
            market=market,
            exchange=exchange,
            interval=interval,
            days=days,
            provider=provider,
            bypass_cache=bypass_cache or refresh,
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    fingerprint = ohlcv_fingerprint(frame)
    payload = _cached_tv_rating_snapshot(
        instrument=instrument, frame=frame, fingerprint=fingerprint,
        source=source, interval=interval, days=days, provider=provider,
        refresh=bypass_cache or refresh,
    )
    return {
        "symbol": symbol,
        "market": market,
        "exchange": exchange,
        "instrument": instrument,
        "interval": interval,
        "source": source,
        "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "is_stale": _is_stale(frame, market, interval),
        "as_of": frame.index[-1].isoformat(),
        "fingerprint": fingerprint,
        **payload,
    }


@router.get("/instruments/{symbol}/analytics-snapshot")
def analytics_snapshot(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(3650, ge=1, le=3650),
    provider: str = "auto",
    direction_mode: DirectionMode = Query("long_only"),
    refresh: bool = False,
    prefetch: bool = False,
) -> dict[str, Any]:
    """One atomic Analytics snapshot for a single instrument/timeframe.

    Candle retrieval is shared by all Analytics outputs. The chart series,
    latest indicators, strategy output and TradingView v3 ratings therefore
    carry one identical OHLCV fingerprint.
    """
    instrument = _market_target(
        request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=exchange
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval,
            days=days, provider=provider, bypass_cache=refresh,
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if frame.empty:
        raise HTTPException(status_code=422, detail="No completed candles are available for this timeframe")

    fingerprint = ohlcv_fingerprint(frame)
    indicators = compute_indicators(frame)
    latest = indicators.iloc[-1]
    values = {
        column: None if pd.isna(value) else float(value)
        for column, value in latest.items()
        if column not in {"open", "high", "low", "close", "volume"}
    }
    position_side = request.app.state.db.position_side_at(
        instrument["instrument_id"], instrument["currency"], datetime.now(UTC),
    )
    signal = evaluate_trend_breakout(
        frame, symbol=symbol, market=market, source=source,
        direction_mode=direction_mode, position_side=position_side, indicators=indicators,
    )
    adjusted = bool(frame.attrs.get("is_adjusted", False))
    stale = _is_stale(frame, market, interval)
    warnings: list[str] = []
    if stale:
        warnings.append("Latest candle is stale for this market; actionable signal output is suppressed.")
        signal.state = "STALE_DATA"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.direction = None
        signal.explanation = "Signal suppressed because the latest candle exceeds the configured freshness window. Verify the provider and market session."
    if market == "india" and not adjusted:
        warnings.append("Indian equity candles are unadjusted. Corporate actions can distort long-term indicators; do not treat strategy output as actionable.")
        signal.state = "DATA_QUALITY_ERROR"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.direction = None
        signal.explanation = "Signal suppressed because TradingView did not confirm split-adjusted history for this instrument."

    technical_payload = _cached_tv_rating_snapshot(
        instrument=instrument, frame=frame, fingerprint=fingerprint,
        source=source, interval=interval, days=days, provider=provider,
        refresh=refresh,
    )
    technical_payload = {
        **technical_payload,
        "symbol": symbol, "market": market, "exchange": exchange,
        "instrument": instrument, "interval": interval, "source": source,
        "is_adjusted": adjusted, "is_stale": stale,
        "as_of": frame.index[-1].isoformat(), "fingerprint": fingerprint,
    }
    signal_payload = signal.model_dump(mode="json")
    if not prefetch:
        request.app.state.db.save_signal(signal_payload)
    analysis_payload = {
        "symbol": symbol, "market": market, "exchange": exchange,
        "interval": interval, "instrument": instrument, "source": source,
        "is_adjusted": adjusted, "is_stale": stale,
        "history_truncated": bool(frame.attrs.get("history_truncated", False)),
        "history_pages": frame.attrs.get("history_pages"),
        "as_of": frame.index[-1].isoformat(), "fingerprint": fingerprint,
        "latest": {key: float(latest[key]) for key in ("open", "high", "low", "close", "volume")},
        "indicators": values, "strategy": signal_payload,
        "warnings": warnings, "candles": _to_json_records(frame),
    }
    indicator_payload = {
        "symbol": symbol, "market": market, "exchange": exchange,
        "interval": interval, "instrument": instrument, "source": source,
        "is_adjusted": adjusted, "is_stale": stale,
        "as_of": frame.index[-1].isoformat(), "fingerprint": fingerprint,
        "count": len(indicators), "series": _to_json_records(indicators),
    }
    generated_at = datetime.now(UTC).isoformat()
    snapshot_identity = "|".join((
        str(instrument.get("instrument_id") or ""), interval, fingerprint,
        TV_RATING_SOURCE_VERSION, direction_mode,
    ))
    import hashlib
    snapshot_id = hashlib.sha256(snapshot_identity.encode("utf-8")).hexdigest()[:24]
    provenance = {
        "instrument_id": instrument.get("instrument_id"),
        "symbol": symbol, "market": market, "exchange": exchange,
        "interval": interval, "source": source, "is_adjusted": adjusted,
        "candle_count": len(frame),
        "latest_candle_timestamp": frame.index[-1].isoformat(),
        "last_candle_confirmed": frame.attrs.get("last_bar_confirmed"),
        "candle_status": (
            "confirmed" if frame.attrs.get("last_bar_confirmed") is True
            else "unconfirmed" if frame.attrs.get("last_bar_confirmed") is False
            else "unknown"
        ),
        "ohlcv_fingerprint": fingerprint,
        "calculation_timestamp": technical_payload.get("calculation_timestamp"),
        "snapshot_generated_at": generated_at,
        "technical_rating_source": technical_payload.get("source_name"),
        "technical_rating_version": technical_payload.get("source_version"),
        "technical_rating_dependency": technical_payload.get("dependency"),
        "data_freshness": "stale" if stale else "fresh",
        "indicator_available": technical_payload["summary"]["overall"]["available"],
        "indicator_total": technical_payload["summary"]["overall"]["total"],
        "indicator_unavailable": technical_payload["summary"]["overall"]["unavailable"],
        "technical_rating_cache_hit": technical_payload.get("cache_hit", False),
    }
    return {
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "symbol": symbol, "market": market, "exchange": exchange,
        "interval": interval, "source": source, "is_adjusted": adjusted,
        "fingerprint": fingerprint,
        "analysis": analysis_payload,
        "indicator_series": indicator_payload,
        "technical_ratings": technical_payload,
        "provenance": provenance,
    }


@router.get("/instruments/{symbol}/news")
def instrument_news(
    request: Request,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    company_name: str | None = None,
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    resolver = request.app.state.instrument_resolver
    instrument: dict[str, Any] | None = None
    if instrument_id or market is None:
        instrument = _market_target(
            request, symbol=symbol, instrument_id=instrument_id, market=market, exchange=None
        )
    elif symbol:
        legacy = resolver.resolve(symbol, market=market)
        if legacy.get("status") == "resolved":
            instrument = legacy.get("instrument")
    if instrument is not None:
        symbol = str(instrument["symbol"])
        market = str(instrument["market"])
        if not company_name and instrument.get("asset_type") == "equity":
            company_name = str(instrument.get("name") or "") or None
    elif symbol:
        symbol = _clean_symbol(symbol)
    else:
        raise HTTPException(status_code=404, detail="No Supported Instrument Found")
    if instrument is None:
        try:
            instrument = request.app.state.news_service.resolve_instrument(symbol)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="No Supported Instrument Found") from exc
    feed = request.app.state.news_service.symbol_feed(instrument, page=1, page_size=limit)
    return {
        "symbol": instrument["symbol"], "market": instrument["market"], "instrument": instrument,
        "items": feed["items"], "count": len(feed["items"]),
        "providers": {"Yahoo Finance": feed["provider_status"]},
        "requested_limit": limit,
        "stale": feed["stale"],
        "last_updated": feed["last_successful_refresh"],
        "note": "News is sourced only from Yahoo Finance. An empty feed may reflect Yahoo Finance coverage or an unavailable refresh.",
    }


@router.post("/backtests/trend-breakout")
def backtest_trend_breakout(request: Request, payload: BacktestRequest) -> dict[str, Any]:
    instrument = _market_target(
        request,
        symbol=payload.symbol or None,
        instrument_id=payload.instrument_id,
        market=payload.market,
        exchange=payload.exchange,
    )
    symbol = instrument["symbol"]
    market = instrument["market"]
    exchange = instrument["exchange"]
    if payload.interval != "1d":
        raise HTTPException(status_code=422, detail="The initial backtest is defined for daily candles only.")
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=payload.interval,
            days=payload.days, provider=payload.provider, full_history=False,
        )
        if _is_stale(frame, market, payload.interval):
            raise HTTPException(
                status_code=409,
                detail="Backtest refused: the latest candle is stale for this market. Refresh data before evaluating results.",
            )
        if market == "india" and not bool(frame.attrs.get("is_adjusted", False)):
            raise HTTPException(
                status_code=409,
                detail="Backtest refused: TradingView did not confirm split-adjusted Indian equity history.",
            )
        result = run_trend_breakout_backtest(
            frame, initial_capital=payload.initial_capital, risk_fraction=payload.risk_fraction,
            cost_bps_per_side=(payload.commission_bps_per_side if payload.commission_bps_per_side is not None else payload.cost_bps_per_side) + payload.slippage_bps_per_side,
            slippage_bps_per_side=payload.slippage_bps_per_side,
            max_position_fraction=payload.max_position_fraction,
            market=market,
            direction_mode=payload.direction_mode,
            strategy_config=payload.strategy_config,
        )
    except HTTPException:
        raise
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.update({"symbol": symbol, "market": market, "instrument": instrument,
                   "source": source,
                   "strategy": "Trend + Donchian 20 Breakout", "strategy_version": STRATEGY_VERSION,
                   "data_adjusted": bool(frame.attrs.get("is_adjusted", False)),
                   "date_range": {"start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat()},
                   "executed_at": datetime.now(UTC).isoformat(),
                   "execution_assumptions": {"initial_capital": payload.initial_capital,
                       "risk_fraction": payload.risk_fraction, "max_position_fraction": payload.max_position_fraction,
                       "cost_bps_per_side": result["cost_bps_per_side"],
                       "commission_bps_per_side": payload.commission_bps_per_side if payload.commission_bps_per_side is not None else payload.cost_bps_per_side,
                       "slippage_bps_per_side": payload.slippage_bps_per_side}})
    return result


@router.post("/risk/position-size", response_model=RiskResult)
def calculate_position_size(request: Request, payload: RiskRequest) -> RiskResult:
    settings = request.app.state.settings
    if payload.risk_fraction > settings.max_risk_fraction:
        raise HTTPException(status_code=422, detail=f"risk_fraction cannot exceed configured limit {settings.max_risk_fraction}")
    try:
        result = position_size(**payload.model_dump())
        return RiskResult(**result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Instrument identity — one centralized resolver for the whole application
# ----------------------------------------------------------------------
@router.get("/instruments/search")
def search_instruments(
    request: Request,
    q: str = Query(..., min_length=1),
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    payload = request.app.state.instrument_resolver.search(q, limit=limit, market=market)
    payload["items"] = payload.get("candidates", [])
    return payload


@router.get("/instruments/resolve")
def resolve_instrument(
    request: Request,
    query: str | None = None,
    symbol: str | None = None,
    instrument_id: str | None = None,
    market: str | None = Query(None, pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
) -> dict[str, Any]:
    """Resolve any ticker, company name or pair to one canonical instrument.

    New clients send ``query`` (or ``instrument_id``) only. Legacy callers may
    still send ``symbol`` plus an explicit market and exchange; that path is
    validated but never broadens the search to another exchange.
    """
    value = (query or symbol or instrument_id or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="Provide query, symbol or instrument_id")
    # Legacy contract: symbol + explicit market keeps exact validation semantics
    # (for example a bare crypto pair without a quote asset is rejected).
    if symbol and market and not query and not instrument_id:
        try:
            instrument = request.app.state.db.resolve_instrument(
                symbol, market, exchange=exchange
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        stored = request.app.state.instrument_resolver.get(instrument.instrument_id)
        payload = {
            "query": symbol,
            "normalized": symbol.strip().upper(),
            "status": "resolved",
            "message": None,
            "instrument": stored or instrument.model_dump(mode="json"),
            "candidates": [],
            "count": 1,
            "recognized": None,
            "resolved": True,
            "items": [],
        }
        return payload
    payload = request.app.state.instrument_resolver.resolve(
        value,
        instrument_id=instrument_id,
        market=market,
        exchange=exchange,
        allow_legacy=market is not None,
    )
    payload["resolved"] = payload.get("status") == "resolved"
    payload["items"] = payload.get("candidates", [])
    return payload


@router.get("/instruments/{instrument_id}")
def get_instrument(request: Request, instrument_id: str) -> dict[str, Any]:
    instrument = request.app.state.instrument_resolver.get(instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown instrument {instrument_id}")
    return instrument



# ----------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------
@router.get("/watchlist")
def get_watchlist(request: Request) -> dict[str, Any]:
    return {"items": request.app.state.db.get_watchlist()}


@router.post("/watchlist")
def add_watchlist(request: Request, item: WatchlistItem) -> dict[str, Any]:
    try:
        saved = request.app.state.db.add_watchlist(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"watchlist_saved": False, "prefetch_registration": "not_attempted", "error": str(exc)},
        ) from exc
    try:
        registration = request.app.state.analytics_precompute.register_watchlist_instrument(
            str(saved["instrument_id"])
        )
    except Exception as exc:
        # Membership remains durable; retrying this idempotent POST or startup
        # reconciliation will register its missing work.
        raise HTTPException(
            status_code=503,
            detail={"watchlist_saved": True, "prefetch_registration": "failed", "error": str(exc)},
        ) from exc
    return {**saved, "prefetch_registration": registration}


@router.delete("/watchlist/instruments/{instrument_id}")
def delete_watchlist_instrument(request: Request, instrument_id: str) -> dict[str, Any]:
    removed = request.app.state.db.remove_watchlist_instrument(instrument_id)
    if removed:
        request.app.state.analytics_precompute.cancel_watchlist_jobs(instrument_id)
    return {"removed": removed}


@router.delete("/watchlist/{market}/{symbol}")
def delete_watchlist(request: Request, market: str, symbol: str, exchange: str | None = None) -> dict[str, Any]:
    target_symbol = _clean_symbol(symbol)
    target_exchange = (exchange or "").upper()
    identity = next((item.get("instrument_id") for item in request.app.state.db.get_watchlist()
                     if item.get("symbol") == target_symbol and item.get("market") == market
                     and (item.get("exchange") or "").upper() == target_exchange), None)
    removed = request.app.state.db.remove_watchlist(target_symbol, market, exchange)
    if removed and identity:
        request.app.state.analytics_precompute.cancel_watchlist_jobs(str(identity))
    return {"removed": removed}


# ----------------------------------------------------------------------
# Centralised market quotes
# ----------------------------------------------------------------------
def _instrument_for_quote(
    request: Request,
    *,
    instrument_id: str | None,
    symbol: str | None,
    market: str,
    exchange: str | None,
) -> dict[str, Any]:
    if instrument_id:
        instrument = request.app.state.db.instrument_for_id(instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail=f"Unknown instrument {instrument_id}")
        return instrument
    if not symbol:
        raise HTTPException(status_code=422, detail="Provide instrument_id or symbol")
    try:
        return request.app.state.db.resolve_instrument(
            symbol, market, exchange=exchange
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _quote_payload(instrument: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    return {
        **quote,
        "instrument_id": quote.get("instrument_id") or instrument.get("instrument_id"),
        "symbol": quote.get("symbol") or instrument.get("symbol"),
        "name": instrument.get("name") or quote.get("name"),
        "market": quote.get("market") or instrument.get("market"),
        "exchange": quote.get("exchange") or instrument.get("exchange"),
        "currency": quote.get("currency") or instrument.get("currency"),
        "asset_type": quote.get("asset_type") or instrument.get("asset_type"),
        "provider": quote.get("provider") or instrument.get("provider"),
        "provider_symbol": quote.get("provider_symbol") or instrument.get("provider_symbol"),
    }


@router.get("/market/quotes")
def market_quotes(
    request: Request,
    instrument_id: list[str] = Query(default=[]),
    watchlist: bool = False,
    force: bool = False,
    symbol: str | None = None,
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
) -> dict[str, Any]:
    """Latest quotes, deduplicated and routed through one shared service."""
    instruments: list[dict[str, Any]] = []
    if watchlist:
        instruments.extend(request.app.state.db.get_watchlist())
    for value in instrument_id:
        if not value:
            continue
        instrument = request.app.state.db.instrument_for_id(value)
        if instrument is None:
            continue
        instruments.append(instrument)
    if symbol:
        instruments.append(_instrument_for_quote(
            request, instrument_id=None, symbol=symbol, market=market, exchange=exchange
        ))

    if not instruments:
        return {"quotes": [], "as_of": datetime.now(UTC).isoformat()}

    quotes = request.app.state.quote_service.quotes_for(instruments, force=force)
    return {
        "quotes": [_quote_payload(instrument, quote) for instrument, quote in zip(instruments, quotes)],
        "as_of": datetime.now(UTC).isoformat(),
        "currency_conversion": "unavailable",
    }


def _stream_instruments(request: Request, instrument_ids: list[str], watchlist: bool) -> list[dict[str, Any]]:
    instruments: list[dict[str, Any]] = []
    if watchlist:
        instruments.extend(request.app.state.db.get_watchlist())
    seen = {str(item.get("instrument_id")) for item in instruments}
    for value in instrument_ids:
        if not value or value in seen:
            continue
        instrument = request.app.state.db.instrument_for_id(value)
        if instrument is not None:
            instruments.append(instrument)
            seen.add(value)
    return instruments


@router.get("/market/quotes/stream")
async def quote_stream(
    request: Request,
    instrument_id: list[str] = Query(default=[]),
    watchlist: bool = False,
) -> StreamingResponse:
    """Server-Sent Events feed backed by the shared TradingView quote cache.

    Every tick replays the latest cached or refreshed quote with its provider
    timestamp, so delayed exchanges are never labelled real-time. A single
    bridge batch is reused for all subscribers instead of opening a socket.
    """
    instruments = _stream_instruments(request, instrument_id, watchlist)
    quote_service = request.app.state.quote_service
    interval = max(1.0, float(request.app.state.settings.quote_stream_interval_seconds))

    async def events() -> AsyncIterator[str]:
        try:
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    quotes = await asyncio.to_thread(
                        quote_service.quotes_for, instruments
                    )
                except Exception as exc:  # keep the stream alive on provider errors
                    payload = {"type": "error", "message": str(exc)}
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                    quotes = []
                for instrument, quote in zip(instruments, quotes):
                    payload = _quote_payload(instrument, quote)
                    yield f"event: quote\ndata: {json.dumps(payload, default=str)}\n\n"
                yield ": keep-alive\n\n"
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


# ----------------------------------------------------------------------
# Portfolio ledger
# ----------------------------------------------------------------------
def _portfolio_views(request: Request, *, force_quotes: bool = False) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    db = request.app.state.db
    transactions = db.list_transactions()
    ledger = build_ledger(transactions)
    open_accounts = [account for account in ledger.accounts.values() if account.is_open]
    quotes = request.app.state.quote_service.quotes_for(
        [account.__dict__ for account in open_accounts], force=force_quotes
    )
    quote_map = {quote.get("instrument_id"): quote for quote in quotes if quote.get("instrument_id")}
    positions = [position_view(account, quote_map.get(account.instrument_id)) for account in open_accounts]
    summary = summary_view(
        ledger,
        quote_map,
        base_currency=request.app.state.settings.default_account_currency,
        transactions_count=len(transactions),
    )
    return ledger, positions, summary


@router.get("/portfolio/transactions")
def portfolio_transactions(request: Request) -> dict[str, Any]:
    return {
        "transactions": [
            {**row, "intent": row.get("intent") or row.get("side")}
            for row in request.app.state.db.list_transactions()
        ],
        "mode": "manual-research-exposure-ledger",
        "purpose": "research/manual exposure tracking only",
        "accounting_method": "FIFO with fees allocated per unit",
        "order_execution": False,
        "spot_borrow_claims": False,
    }


@router.post("/portfolio/transactions")
def add_portfolio_transaction(request: Request, transaction: AmountTransactionRequest) -> dict[str, Any]:
    db = request.app.state.db
    existing = db.get_transaction_by_idempotency_key(transaction.idempotency_key or "")
    if existing is not None:
        return _transaction_saved_response(request, existing, duplicate=True)

    instrument, quote, rules, calculation = _prepare_amount_transaction(request, transaction)
    quote_time = _quote_datetime(quote)
    try:
        saved, duplicate = db.add_transaction_once(HoldingTransaction(
            symbol=instrument["symbol"],
            market=instrument["market"],
            exchange=instrument["exchange"],
            instrument_id=instrument["instrument_id"],
            name=instrument.get("name"),
            asset_type=instrument.get("asset_type"),
            provider=instrument.get("provider"),
            provider_symbol=instrument.get("provider_symbol"),
            side=transaction.intent,
            amount=calculation["requested_amount"],
            actual_amount=calculation["actual_amount"],
            quantity=calculation["quantity"],
            price=quote["price"],
            trade_time=transaction.trade_time,
            currency=instrument["currency"],
            fees=transaction.fees,
            notes=transaction.notes,
            quote_provider=quote.get("provider"),
            quote_time=quote_time,
            quote_type=quote.get("quote_type"),
            quote_status=quote.get("freshness"),
            quote_currency=quote.get("currency") or instrument["currency"],
            idempotency_key=transaction.idempotency_key,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not duplicate and (saved.get("intent") or saved["side"]) in {"BUY", "SELL_SHORT"}:
        try:
            # Held instruments are identifiable in the watchlist and deduplicated
            # by canonical identity.
            db.add_watchlist(WatchlistItem(
                symbol=saved["symbol"], market=saved["market"],
                exchange=saved["exchange"] or None,
                display_name=instrument.get("name") or saved.get("instrument_name"),
                instrument_id=saved["instrument_id"],
            ))
        except ValueError:
            pass

    return _transaction_saved_response(
        request, saved, quote=quote, instrument=instrument,
        rules=rules, calculation=calculation, duplicate=duplicate,
    )


def _quote_datetime(quote: dict[str, Any]) -> datetime | None:
    value = quote.get("quote_time")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _usable_transaction_quote(quote: dict[str, Any], instrument: dict[str, Any]) -> None:
    if not quote or quote.get("price") is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "A usable market quote is required before recording this transaction. "
                f"{quote.get('error') if quote else 'Quote unavailable'}"
            ),
        )
    quote_currency = str(quote.get("currency") or "").upper()
    instrument_currency = str(instrument.get("currency") or "").upper()
    if quote_currency and instrument_currency and quote_currency != instrument_currency:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Quote currency {quote_currency} does not match instrument currency "
                f"{instrument_currency}"
            ),
        )
    freshness = str(quote.get("freshness") or "").lower()
    quote_type = str(quote.get("quote_type") or "").lower()
    if freshness in {"stale", "unavailable", "cached"} or quote_type in {
        "stale", "unavailable", "cached",
    }:
        raise HTTPException(
            status_code=422,
            detail=(
                "The latest provider quote is stale or unavailable. Recording is disabled "
                "until a usable quote can be verified."
            ),
        )


def _prepare_amount_transaction(
    request: Request, payload: AmountTransactionRequest, *, fresh_quote: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Any, dict[str, Any]]:
    db = request.app.state.db
    instrument = db.instrument_for_id(payload.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown instrument {payload.instrument_id}")
    if payload.currency and payload.currency != instrument["currency"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Currency {payload.currency} does not match instrument currency "
                f"{instrument['currency']}"
            ),
        )
    try:
        quote = request.app.state.quote_service.quote_for_transaction(
            instrument, payload.trade_time, force=fresh_quote
        )
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unable to obtain a transaction reference quote: {exc}",
        ) from exc
    _usable_transaction_quote(quote, instrument)
    try:
        rules = request.app.state.quote_service.trading_rules_for(instrument)
    except Exception:
        rules = None
    if rules is None:
        from app.core.trading_rules import default_trading_rules
        rules = default_trading_rules(instrument)
    intent = payload.intent
    position_side = db.position_side_at(
        instrument["instrument_id"], instrument["currency"], payload.trade_time
    )
    if intent == "BUY" and position_side == "SHORT":
        raise HTTPException(
            status_code=422,
            detail="BUY cannot reverse an open SHORT exposure; use BUY_TO_COVER first",
        )
    if intent == "SELL_SHORT" and position_side == "LONG":
        raise HTTPException(
            status_code=422,
            detail="SELL_SHORT cannot reverse an open LONG exposure; use SELL first",
        )

    available = None
    if intent == "SELL":
        available = db.available_quantity(
            instrument["instrument_id"], instrument["currency"], payload.trade_time
        )
    elif intent == "BUY_TO_COVER":
        available = db.available_short_quantity(
            instrument["instrument_id"], instrument["currency"], payload.trade_time
        )
    try:
        calculation = calculate_amount_transaction(
            side="SELL" if intent in {"SELL", "BUY_TO_COVER"} else "BUY",
            requested_amount=payload.amount,
            price=float(quote["price"]),
            rules=rules,
            available_quantity=available,
            fees=payload.fees,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    calculation["intent"] = intent
    calculation["reference_notional"] = calculation["actual_amount"]
    if intent in {"SELL_SHORT", "BUY_TO_COVER"}:
        calculation["total_cash_cost"] = None
        calculation["net_proceeds"] = None
        calculation["accounting_note"] = (
            "Reference notional for manual exposure accounting; this is not an execution "
            "or settlement amount."
        )
    if intent == "BUY_TO_COVER":
        calculation["max_close_amount"] = calculation.get("max_sell_amount")
    return instrument, quote, rules, calculation


def _transaction_saved_response(
    request: Request,
    saved: dict[str, Any],
    *,
    quote: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
    rules: Any = None,
    calculation: dict[str, Any] | None = None,
    duplicate: bool = False,
) -> dict[str, Any]:
    db = request.app.state.db
    instrument = instrument or db.get_instrument(saved.get("instrument_id") or "") or {}
    _, positions, summary = _portfolio_views(request)
    account = build_ledger(db.list_transactions()).accounts.get(saved.get("instrument_id") or "")
    position = position_view(account, quote) if account else None
    return {
        "transaction": {
            **saved,
            "intent": saved.get("intent") or saved.get("side"),
            "amount": saved.get("amount") or None,
            "actual_amount": saved.get("actual_amount") or None,
        },
        "instrument": instrument or None,
        "quote": _quote_payload(instrument, quote) if quote else None,
        "quote_error": None if quote and quote.get("price") is not None else "Quote unavailable",
        "quote_available": bool(quote and quote.get("price") is not None),
        "calculation": calculation,
        "trading_rules": rules.model_dump(mode="json") if hasattr(rules, "model_dump") else rules,
        "duplicate": duplicate,
        "position": position,
        "positions": positions,
        "summary": summary,
        "transactions": [
            {**row, "intent": row.get("intent") or row.get("side")}
            for row in db.list_transactions()
        ],
        "accounting_method": "FIFO with fees allocated per unit",
        "mode": "manual-research-exposure-ledger",
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
        "price_note": (
            "Recorded using a reference quote for manual exposure accounting only. "
            "No order was executed and no spot borrow is implied."
        ),
    }


@router.post("/portfolio/transactions/preview")
def preview_amount_transaction(
    request: Request, transaction: AmountTransactionRequest,
) -> dict[str, Any]:
    """Server-authoritative amount-to-quantity preview.

    The form renders this response rather than implementing precision rules in
    React. Invalid input is returned as ``valid: false`` so the preview does not
    create console noise while the owner types.
    """
    try:
        instrument, quote, rules, calculation = _prepare_amount_transaction(
            request, transaction, fresh_quote=False
        )
    except HTTPException as exc:
        return {
            "valid": False,
            "error": exc.detail,
            "instrument_id": transaction.instrument_id,
            "side": (
                "BUY" if transaction.intent in {"BUY", "BUY_TO_COVER"} else "SELL"
            ),
            "intent": transaction.intent,
            "requested_amount": transaction.amount,
            "purpose": "research/manual exposure tracking only",
            "order_execution": False,
            "spot_borrow_claims": False,
        }
    warnings: list[str] = []
    if quote.get("quote_type") == "historical":
        warnings.append(
            "Historical entry: quantity uses the provider price at or before the selected "
            "transaction time. The current market price was not substituted."
        )
    if calculation["remaining_amount"] > 0:
        warnings.append(
            f"{instrument['currency']} {calculation['remaining_amount']:.8g} remains "
            "unallocated after quantity rounding."
        )
    if quote.get("quote_type") in {"end_of_day", "last_available"}:
        warnings.append(
            "This market is not streaming real-time prices in the configured feed. "
            "The quote timestamp and status are shown above."
        )
    return {
        "valid": True,
        "error": None,
        "side": (
            "BUY" if transaction.intent in {"BUY", "BUY_TO_COVER"} else "SELL"
        ),
        "intent": transaction.intent,
        "instrument": instrument,
        "quote": _quote_payload(instrument, quote),
        "trading_rules": rules.model_dump(mode="json"),
        **calculation,
        "warnings": warnings,
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
        "price_note": (
            "This is a reference quote for manual exposure accounting only. No order was "
            "executed and no spot borrow is implied."
        ),
    }


@router.delete("/portfolio/transactions/{transaction_id}")
def delete_portfolio_transaction(request: Request, transaction_id: int) -> dict[str, Any]:
    db = request.app.state.db
    try:
        removed = db.delete_transaction(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request.app.state.quote_service.invalidate(removed.get("instrument_id") or "")
    _, positions, summary = _portfolio_views(request)
    return {
        "removed": removed,
        "positions": positions,
        "summary": summary,
        "transactions": [
            {**row, "intent": row.get("intent") or row.get("side")}
            for row in db.list_transactions()
        ],
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
    }


@router.get("/portfolio/summary")
def portfolio_summary(request: Request, force: bool = False) -> dict[str, Any]:
    _, _, summary = _portfolio_views(request, force_quotes=force)
    return summary


@router.get("/portfolio/positions")
def portfolio_positions(request: Request, force: bool = False) -> dict[str, Any]:
    _, positions, summary = _portfolio_views(request, force_quotes=force)
    return {
        "positions": positions,
        "summary": summary,
        "accounting_method": "FIFO with fees allocated per unit",
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
        "note": (
            "Invested value and P&L come from the backend FIFO ledger. Current price "
            "and market value use the centralised quote service; when a quote is "
            "unavailable the position stays visible with a valuation error."
        ),
    }


@router.get("/portfolio/positions/{instrument_id}")
def portfolio_position_detail(
    request: Request,
    instrument_id: str,
    force: bool = False,
    days: int = Query(365, ge=30, le=3650),
) -> dict[str, Any]:
    db = request.app.state.db
    ledger = build_ledger(db.list_transactions())
    account = ledger.accounts.get(instrument_id)
    if account is None:
        parsed = parse_instrument_id(instrument_id)
        if parsed:
            market, exchange, symbol = parsed
            key = canonical_instrument(symbol, market, exchange=exchange).instrument_id
            account = ledger.accounts.get(key)
    if account is None:
        raise HTTPException(status_code=404, detail=f"No ledger history for {instrument_id}")

    quote = request.app.state.quote_service.quote_for(account.__dict__, force=force)
    detail = detail_view(account, quote)
    candles: list[dict[str, Any]] = []
    candle_source: str | None = None
    candle_error: str | None = None
    try:
        frame, candle_source = request.app.state.market_service.candles(
            account.symbol, market=account.market, exchange=account.exchange or None,
            interval="1d", days=days, provider="auto", full_history=False,
        )
        candles = _to_json_records(frame.tail(500))
    except (ProviderError, ValueError) as exc:
        candle_error = str(exc)
    detail.update({
        "candles": candles,
        "candle_source": candle_source,
        "candle_error": candle_error,
        "currency_conversion": "unavailable",
        "accounting_method": "FIFO with fees allocated per unit",
        "mode": "manual-research-exposure-ledger",
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
    })
    return detail
