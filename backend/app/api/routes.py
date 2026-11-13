from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from app.core.models import BacktestRequest, HoldingTransaction, RiskRequest, RiskResult, WatchlistItem
from app.providers.base import ProviderError
from app.providers.crypto_metadata import CoinGeckoProvider
from app.providers.fundamentals import YahooFundamentalsProvider
from app.providers.news import (
    GDELTNewsProvider, RSSNewsProvider, SECEdgarProvider, TejHQActionsProvider,
    YahooFinanceNewsProvider,
)
from app.services.backtest import run_trend_breakout_backtest
from app.services.indicators import compute_indicators
from app.services.market import MarketService
from app.services.strategy import evaluate_trend_breakout, position_size

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
        {"name": "TejHQ", "configured": True, "note": "NSE/BSE EOD; adjusted endpoint requires free API key; otherwise raw OHLCV."},
        {"name": "Yahoo Finance / yfinance", "configured": True, "note": "Unofficial personal-use data interface; coverage/freshness varies."},
        {"name": "Binance Spot", "configured": True, "note": "Public crypto market data; no API key for public endpoints."},
        {"name": "CoinGecko Demo", "configured": bool(settings.coingecko_api_key), "note": "Optional aggregate crypto metadata; key required."},
        {"name": "GDELT", "configured": bool(settings.gdelt_enabled), "note": "Global news discovery; relevance must be checked."},
        {"name": "Publisher RSS", "configured": bool(settings.rss_urls), "note": f"{len(settings.rss_urls)} configured feed(s)."},
        {"name": "SEC EDGAR", "configured": bool(settings.sec_user_agent and "contact@example.invalid" not in settings.sec_user_agent),
         "note": "Official US filings; set a real identifying User-Agent."},
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


@router.get("/instruments/{symbol}/fundamentals")
def instrument_fundamentals(
    symbol: str, market: str = Query("india", pattern="^(india|global|crypto)$"), exchange: str | None = None,
) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    try:
        return YahooFundamentalsProvider().fetch(symbol, market, exchange)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
    rss = RSSNewsProvider(request.app.state.settings)
    items = gdelt.search(query, symbol, limit=limit) + rss.search(query, symbol)
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
            "RSS": {"configured_feeds": len(request.app.state.settings.rss_urls), "errors": rss.last_errors},
            "Yahoo Finance News": {"enabled": request.app.state.settings.yahoo_news_enabled,
                                   "note": "Optional unofficial personal-use feed; errors may appear as an empty result."},
        },
        "note": "News discovery can return false ticker matches. Open and verify each original publisher item. An empty list is not proof that no news exists.",
    }
    request.app.state.response_cache.set(cache_key, result, request.app.state.settings.news_cache_seconds)
    return result


@router.get("/instruments/{symbol}/events")
def instrument_events(request: Request, symbol: str, market: str = Query("india", pattern="^(india|global|crypto)$")) -> dict[str, Any]:
    symbol = _clean_symbol(symbol)
    events = []
    provider_error = None
    if market == "india":
        actions_provider = TejHQActionsProvider(request.app.state.settings)
        events = actions_provider.get_actions(symbol)
        provider_error = actions_provider.last_error
        links = [
            {"label": "NSE corporate announcements", "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
            {"label": "BSE corporate announcements", "url": "https://www.bseindia.com/corporates/ann.html"},
        ]
    elif market == "global":
        links = [{"label": "SEC company filings", "url": "https://www.sec.gov/edgar/search/"}]
    else:
        links = []
    return {
        "symbol": symbol, "market": market,
        "events": [event.model_dump(mode="json") for event in events],
        "official_source_links": links,
        "provider_error": provider_error,
        "note": "Only provider-returned records are shown as events. No upcoming date is inferred. Exchange links are provided for manual verification where structured free feeds are unavailable.",
    }


@router.get("/us/issuers/{cik}/filings")
def sec_filings(request: Request, cik: str) -> dict[str, Any]:
    try:
        items = SECEdgarProvider(request.app.state.settings).recent_filings(cik)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"cik": cik.zfill(10), "items": [item.model_dump(mode="json") for item in items], "count": len(items)}


@router.get("/crypto/markets")
def crypto_markets(request: Request, symbols: str | None = None) -> dict[str, Any]:
    requested = [item.strip() for item in symbols.split(",")] if symbols else None
    try:
        rows = CoinGeckoProvider(request.app.state.settings).markets(requested)
        return {"source": "CoinGecko Demo", "markets": rows}
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
        if payload.market == "india" and not bool(frame.attrs.get("is_adjusted", False)):
            raise HTTPException(
                status_code=409,
                detail="Backtest refused: Indian equity history is not confirmed corporate-action-adjusted. Configure the TejHQ free key or use adjusted Yahoo data.",
            )
        result = run_trend_breakout_backtest(
            frame, initial_capital=payload.initial_capital, risk_fraction=payload.risk_fraction,
            cost_bps_per_side=payload.cost_bps_per_side,
            max_position_fraction=payload.max_position_fraction,
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
