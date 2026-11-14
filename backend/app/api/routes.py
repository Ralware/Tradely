from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from app.core.models import BacktestRequest, HoldingTransaction, RiskRequest, RiskResult, WatchlistItem
from app.providers.base import ProviderError
from app.providers.news import (
    GDELTNewsProvider, YahooFinanceNewsProvider,
)
from app.services.backtest import run_trend_breakout_backtest
from app.services.indicators import compute_indicators
from app.services.market import MarketService
from app.services.strategy import evaluate_trend_breakout, position_size
from app.services.technicals import build_technical_summary

router = APIRouter(prefix="/api")


def _clean_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", value):
        raise HTTPException(status_code=422, detail="Invalid symbol format")
    return value


def _to_json_records(frame: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    selected = frame.tail(limit).copy()
    selected.index = selected.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    selected = selected.replace({float("nan"): None})
    return selected.reset_index(names="timestamp").to_dict(orient="records")


def _is_stale(frame: pd.DataFrame, market: str) -> bool:
    if frame.empty:
        return True
    age = pd.Timestamp.now(tz="UTC") - frame.index[-1]
    # Daily EOD candle timestamps are often session-date labels, not close timestamps.
    threshold_hours = 48 if market == "crypto" else 120
    return age > pd.Timedelta(hours=threshold_hours)


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "application": "Tradely", "mode": "private-single-user", "ai": False,
            "paper_trading": False, "order_execution": False,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/providers/status")
def provider_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    providers = [
        {"name": "TejHQ Adjusted OHLCV", "configured": bool(settings.tejhq_api_key), "available": bool(settings.tejhq_api_key),
         "purpose": "Indian NSE/BSE daily adjusted OHLCV", "note": "Requires TEJHQ_API_KEY."},
        {"name": "TejHQ Raw OHLCV", "configured": True, "available": True,
         "purpose": "Indian NSE/BSE daily unadjusted OHLCV", "note": "Keyless; unadjusted history suppresses Indian actionable signals and backtests."},
        {"name": "Yahoo Finance (yfinance)", "configured": True, "available": True,
         "purpose": "International equity prices", "note": "Unofficial adapter; availability and freshness vary."},
        {"name": "Binance Spot", "configured": True, "available": True,
         "purpose": "Public crypto prices and OHLCV", "note": "Public market-data endpoints only; no API key or trading access."},
        {"name": "GDELT", "configured": bool(settings.gdelt_enabled), "available": bool(settings.gdelt_enabled),
         "purpose": "Global news discovery", "note": "Results require source verification."},
        {"name": "Yahoo Finance News", "configured": bool(settings.yahoo_news_enabled), "available": bool(settings.yahoo_news_enabled),
         "purpose": "Supplementary news discovery", "note": "Optional unofficial feed."},
    ]
    return {"providers": providers, "checked_at": datetime.now(timezone.utc).isoformat()}


@router.get("/market/candles")
def candles(
    request: Request,
    symbol: str = Query(...),
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(365, ge=1, le=3650),
    provider: str = "auto",
) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval, days=days, provider=provider
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    latest = frame.index[-1].to_pydatetime()
    stale = _is_stale(frame, market)
    return {
        "symbol": symbol, "market": market, "exchange": exchange, "interval": interval,
        "source": source, "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "freshness": "stale" if stale else frame.attrs.get("freshness", "provider-dependent"),
        "is_stale": stale, "history_truncated": bool(frame.attrs.get("history_truncated", False)),
        "history_pages": frame.attrs.get("history_pages"),
        "last_candle_at": latest.isoformat(), "count": len(frame),
        "candles": _to_json_records(frame),
        "warnings": (["Provider history was capped at 20,000 candles; the requested date range may not be fully covered."]
                     if frame.attrs.get("history_truncated", False) else []),
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
            stale = _is_stale(frame, item["market"])
            adjusted = bool(frame.attrs.get("is_adjusted", False))
            if stale:
                signal.state = "STALE_DATA"
                signal.explanation = "Latest candle is stale; signal suppressed."
            elif item["market"] == "india" and not adjusted:
                signal.state = "DATA_QUALITY_ERROR"
                signal.explanation = "Unadjusted Indian history; strategy signal suppressed."
            results.append({"symbol": item["symbol"], "market": item["market"], "source": source,
                            "last_close": float(frame.iloc[-1]["close"]), "is_adjusted": adjusted,
                            "is_stale": stale, "strategy": signal.model_dump(mode="json")})
        except Exception as exc:
            results.append({"symbol": item["symbol"], "market": item["market"], "error": str(exc),
                            "strategy": {"state": "DATA_QUALITY_ERROR"}})
    return {"items": results, "count": len(results), "note": "Scanner only evaluates the configured daily strategy on completed daily bars."}


@router.get("/instruments/{symbol}/analysis")
def analyze(
    request: Request,
    symbol: str,
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(500, ge=1, le=3650),
    provider: str = "auto",
) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
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
    if interval != "1d":
        signal = evaluate_trend_breakout(frame.iloc[:0], symbol=symbol, market=market, source=source)
        signal.explanation = "This strategy is currently calibrated for completed daily candles only. Indicator values are still shown for the selected interval."
    else:
        signal = evaluate_trend_breakout(frame, symbol=symbol, market=market, source=source)
    adjusted = bool(frame.attrs.get("is_adjusted", False))
    stale = _is_stale(frame, market)
    warnings = []
    if frame.attrs.get("history_truncated", False):
        warnings.append("Provider history was capped at 20,000 candles; the requested date range may not be fully covered.")
    if stale:
        warnings.append("Latest candle is stale for this market; actionable signal output is suppressed.")
        signal.state = "STALE_DATA"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.explanation = "Signal suppressed because the latest candle exceeds the configured freshness window. Verify the provider and market session."
    if market == "india" and not adjusted:
        warnings.append("Indian equity candles are unadjusted. Corporate actions can distort long-term indicators; do not treat strategy output as actionable.")
        signal.state = "DATA_QUALITY_ERROR"
        signal.entry_reference = None
        signal.stop_reference = None
        signal.risk_per_unit = None
        signal.explanation = "Signal suppressed because the available Indian equity history is not confirmed as corporate-action-adjusted. Configure a TejHQ free key or use adjusted Yahoo history."
    signal_payload = signal.model_dump(mode="json")
    request.app.state.db.save_signal(signal_payload)
    return {
        "symbol": symbol, "market": market, "exchange": exchange, "interval": interval,
        "source": source, "is_adjusted": adjusted, "is_stale": stale,
        "history_truncated": bool(frame.attrs.get("history_truncated", False)),
        "history_pages": frame.attrs.get("history_pages"),
        "as_of": frame.index[-1].isoformat(),
        "latest": {key: float(latest[key]) for key in ("open", "high", "low", "close", "volume")},
        "indicators": values,
        "strategy": signal_payload,
        "warnings": warnings,
        "candles": _to_json_records(frame.tail(300)),
    }


@router.get("/instruments/{symbol}/indicators")
def indicator_series(
    request: Request,
    symbol: str,
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(500, ge=1, le=3650),
    provider: str = "auto",
    limit: int = Query(300, ge=50, le=1000),
) -> dict[str, Any]:
    """Per-bar indicator values for chart rendering.

    Read-only and additive: this reuses the exact same ``compute_indicators``
    implementation as ``/analysis``. It does not change any existing endpoint,
    formula or signal threshold; the frontend still renders backend values only.
    """
    symbol = _clean_symbol(symbol)
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
        "source": source, "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "is_stale": _is_stale(frame, market),
        "as_of": frame.index[-1].isoformat(),
        "count": len(records),
        "series": records,
    }


@router.get("/instruments/{symbol}/technicals")
def technical_summary(
    request: Request,
    symbol: str,
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(500, ge=1, le=3650),
    provider: str = "auto",
) -> dict[str, Any]:
    """Per-indicator Buy/Sell/Neutral labels and gauge counts.

    Additive and read-only. It reuses ``compute_indicators`` unchanged and only
    classifies the values it already returns with published threshold
    conventions. No strategy rule, existing route or stored record is changed.
    """
    symbol = _clean_symbol(symbol)
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=market, exchange=exchange, interval=interval, days=days, provider=provider
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    indicators = compute_indicators(frame)
    latest = indicators.iloc[-1]
    payload = build_technical_summary(latest, close=float(latest["close"]))
    return {
        "symbol": symbol,
        "market": market,
        "exchange": exchange,
        "interval": interval,
        "source": source,
        "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
        "is_stale": _is_stale(frame, market),
        "as_of": frame.index[-1].isoformat(),
        **payload,
    }


@router.get("/instruments/{symbol}/news")
def instrument_news(
    request: Request, symbol: str, market: str = Query("india", pattern="^(india|global|crypto)$"),
    company_name: str | None = None, limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    query = f'"{company_name}" OR {symbol}' if company_name else symbol
    cache_key = f"news:{market}:{symbol}:{company_name or ''}:{limit}"
    cached = request.app.state.response_cache.get(cache_key)
    if cached is not None:
        return cached
    gdelt = GDELTNewsProvider(request.app.state.settings)
    items = gdelt.search(query, symbol, limit=limit)
    yahoo_provider = YahooFinanceNewsProvider()
    if request.app.state.settings.yahoo_news_enabled:
        items += yahoo_provider.search(symbol, market)
    # Deduplicate by canonical URL; never fabricate news when providers return nothing.
    unique: dict[str, Any] = {}
    for item in items:
        unique[item.url.rstrip("/")] = item
    sorted_items = sorted(
        unique.values(), key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True
    )[:limit]
    result = {
        "symbol": symbol, "market": market, "items": [item.model_dump(mode="json") for item in sorted_items],
        "count": len(sorted_items),
        "providers": {
            "GDELT": {"enabled": request.app.state.settings.gdelt_enabled, "error": gdelt.last_error},
            "Yahoo Finance News": {"enabled": request.app.state.settings.yahoo_news_enabled,
                                   "note": "Optional unofficial personal-use feed; errors may appear as an empty result."},
        },
        "note": "News discovery can return false ticker matches. Open and verify each original publisher item. An empty list is not proof that no news exists.",
    }
    request.app.state.response_cache.set(cache_key, result, request.app.state.settings.news_cache_seconds)
    return result


@router.post("/backtests/trend-breakout")
def backtest_trend_breakout(request: Request, payload: BacktestRequest) -> dict[str, Any]:
    symbol = _clean_symbol(payload.symbol)
    if payload.interval != "1d":
        raise HTTPException(status_code=422, detail="The initial research backtest is defined for daily candles only.")
    try:
        frame, source = request.app.state.market_service.candles(
            symbol, market=payload.market, exchange=payload.exchange, interval=payload.interval,
            days=payload.days, provider=payload.provider,
        )
        if _is_stale(frame, payload.market):
            raise HTTPException(
                status_code=409,
                detail="Backtest refused: the latest candle is stale for this market. Refresh data before evaluating results.",
            )
        if payload.market == "india" and not bool(frame.attrs.get("is_adjusted", False)):
            raise HTTPException(
                status_code=409,
                detail="Backtest refused: Indian equity history is not confirmed corporate-action-adjusted. Configure the TejHQ free key or use adjusted Yahoo data.",
            )
        result = run_trend_breakout_backtest(
            frame, initial_capital=payload.initial_capital, risk_fraction=payload.risk_fraction,
            cost_bps_per_side=payload.cost_bps_per_side,
            max_position_fraction=payload.max_position_fraction,
            market=payload.market,
        )
    except HTTPException:
        raise
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.update({"symbol": symbol, "market": payload.market, "source": source,
                   "strategy": "Trend + Donchian 20 Breakout", "strategy_version": "trend-donchian-20-v1.0.0",
                   "data_adjusted": bool(frame.attrs.get("is_adjusted", False))})
    return result


@router.get("/signals/history")
def signal_history(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    import json
    with request.app.state.db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM signal_audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"signals": [json.loads(row["payload_json"]) for row in rows]}


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


@router.get("/watchlist")
def get_watchlist(request: Request) -> dict[str, Any]:
    return {"items": request.app.state.db.get_watchlist()}


@router.post("/watchlist")
def add_watchlist(request: Request, item: WatchlistItem) -> dict[str, Any]:
    return request.app.state.db.add_watchlist(item)


@router.delete("/watchlist/{market}/{symbol}")
def delete_watchlist(request: Request, market: str, symbol: str, exchange: str | None = None) -> dict[str, Any]:
    removed = request.app.state.db.remove_watchlist(_clean_symbol(symbol), market, exchange)
    return {"removed": removed}


@router.get("/portfolio/transactions")
def portfolio_transactions(request: Request) -> dict[str, Any]:
    return {"transactions": request.app.state.db.list_transactions(), "mode": "actual-holdings-ledger"}


@router.post("/portfolio/transactions")
def add_portfolio_transaction(request: Request, transaction: HoldingTransaction) -> dict[str, Any]:
    try:
        return request.app.state.db.add_transaction(transaction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/portfolio/positions")
def portfolio_positions(request: Request) -> dict[str, Any]:
    transactions = request.app.state.db.list_transactions()
    positions: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in transactions:
        key = (item["market"], item["symbol"], item["currency"])
        position = positions.setdefault(key, {"market": item["market"], "symbol": item["symbol"],
                                              "currency": item["currency"], "quantity": 0.0,
                                              "cost_basis": 0.0, "realised_pnl": 0.0, "lots": []})
        qty = float(item["quantity"])
        fees_per_unit = float(item["fees"]) / qty
        if item["side"] == "BUY":
            position["lots"].append({"quantity": qty, "unit_cost": float(item["price"]) + fees_per_unit})
            position["quantity"] += qty
            position["cost_basis"] += qty * (float(item["price"]) + fees_per_unit)
        else:
            proceeds_per_unit = float(item["price"]) - fees_per_unit
            remaining = qty
            while remaining > 1e-9 and position["lots"]:
                lot = position["lots"][0]
                consumed = min(remaining, lot["quantity"])
                position["realised_pnl"] += consumed * (proceeds_per_unit - lot["unit_cost"])
                position["cost_basis"] -= consumed * lot["unit_cost"]
                lot["quantity"] -= consumed
                remaining -= consumed
                if lot["quantity"] <= 1e-9:
                    position["lots"].pop(0)
            position["quantity"] -= qty
    output = []
    for position in positions.values():
        quantity = max(0.0, position["quantity"])
        if quantity <= 1e-9:
            continue
        position.pop("lots", None)
        position["average_cost"] = position["cost_basis"] / quantity
        output.append(position)
    return {"positions": output, "accounting_method": "FIFO with fees allocated per unit",
            "note": "Realised P&L is calculated from recorded transactions. Unrealised P&L is not shown until a market price is fetched and matched to the holding currency."}
