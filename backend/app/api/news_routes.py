from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.instruments.resolver import (
    AmbiguousInstrumentError,
    InstrumentNotFoundError,
    InstrumentUnavailableError,
)
from app.providers.yahoo_news import YahooNewsError

router = APIRouter(prefix="/api/news", tags=["news"])


def _service(request: Request) -> Any:
    return request.app.state.news_service


def _resolve(service: Any, *, symbol: str | None = None, instrument_id: str | None = None) -> dict[str, Any]:
    try:
        return service.resolve_instrument(symbol, instrument_id=instrument_id)
    except AmbiguousInstrumentError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "candidates": exc.candidates}) from exc
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InstrumentUnavailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _date_bound(value: str | None, *, end_of_day: bool = False) -> str | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min, tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
        return parsed.isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date filters must be ISO dates or timestamps") from exc


@router.get("")
def general_news(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    date_from: str | None = Query(None, max_length=40),
    date_to: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=120),
    symbol: str | None = Query(None, max_length=120),
    instrument_id: str | None = Query(None, max_length=120),
    sort: str = Query("newest", pattern="^newest$"),
) -> dict[str, Any]:
    service = _service(request)
    selected_symbol = None
    if symbol or instrument_id:
        instrument = _resolve(service, symbol=symbol, instrument_id=instrument_id)
        # Use the canonical Tradely symbol in SQL, not the user's ambiguous input.
        selected_symbol = str(instrument["symbol"])
    return service.general_feed(
        page=page, page_size=page_size, query=q.strip() if q and q.strip() else None,
        date_from=_date_bound(date_from), date_to=_date_bound(date_to, end_of_day=True),
        symbol=selected_symbol,
    )


@router.get("/search")
def search_news_instruments(
    request: Request,
    q: str = Query(..., min_length=1, max_length=120),
) -> dict[str, Any]:
    try:
        return _service(request).search_instruments(q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except YahooNewsError as exc:
        raise HTTPException(status_code=502, detail="Yahoo Finance instrument search is temporarily unavailable") from exc


@router.get("/status")
def news_status(
    request: Request,
    instrument_id: str | None = Query(None, max_length=120),
) -> dict[str, Any]:
    instrument = _resolve(_service(request), instrument_id=instrument_id) if instrument_id else None
    return _service(request).refresh_status(instrument)


@router.post("/{symbol}/refresh")
def refresh_news(
    request: Request,
    symbol: str,
    instrument_id: str | None = Query(None, max_length=120),
) -> dict[str, Any]:
    service = _service(request)
    instrument = _resolve(service, symbol=symbol, instrument_id=instrument_id)
    queued = service.request_refresh(instrument, force=True, respect_cooldown=True)
    return {
        "status": "queued" if queued else "already_fresh_or_rate_limited",
        "symbol": instrument.get("symbol"),
        "instrument_id": instrument.get("instrument_id"),
        "message": "Yahoo Finance refresh queued in the background." if queued else "A refresh is already running, recently attempted, or the cache is fresh.",
    }


@router.get("/{symbol}")
def symbol_news(
    request: Request,
    symbol: str,
    instrument_id: str | None = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    q: str | None = Query(None, max_length=120),
    date_from: str | None = Query(None, max_length=40),
    date_to: str | None = Query(None, max_length=40),
) -> dict[str, Any]:
    service = _service(request)
    instrument = _resolve(service, symbol=symbol, instrument_id=instrument_id)
    return service.symbol_feed(
        instrument, page=page, page_size=page_size,
        query=q.strip() if q and q.strip() else None,
        date_from=_date_bound(date_from), date_to=_date_bound(date_to, end_of_day=True),
    )
