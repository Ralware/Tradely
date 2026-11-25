"""Interval-aware market-data freshness rules.

One module owns the definition of a "stale" candle so the REST routes, the
analytics precompute engine and the frontend mirror use the same windows.
A daily threshold of 48/120 hours is correct for daily bars but silently
accepts hours-old intraday data; freshness therefore scales with the interval
and accounts for equity market closures.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.services.quotes import market_status_for

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "45m": 2700,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1wk": 604800,
    "1mo": 2592000,
}

_INTERVAL_ALIASES = {
    "1w": "1wk",
    "1M": "1mo",
}

_EQUITY_MARKETS = {"india", "global"}

# Equity intraday data is allowed to be older while the exchange is closed
# (weekends, holidays and overnight gaps). Four days covers a long weekend and
# a holiday without accepting a genuinely missing week of bars.
_CLOSED_MARKET_GRACE = timedelta(days=4)


def canonical_interval(interval: str) -> str:
    return _INTERVAL_ALIASES.get(interval, interval)


def interval_seconds(interval: str) -> int | None:
    return INTERVAL_SECONDS.get(canonical_interval(interval))


def freshness_window(
    market: str,
    interval: str,
    *,
    now: pd.Timestamp | None = None,
) -> timedelta:
    """Maximum age of the newest candle before it is treated as stale."""
    interval = canonical_interval(interval)
    seconds = INTERVAL_SECONDS.get(interval)

    if interval == "1wk":
        return timedelta(days=14)
    if interval == "1mo":
        return timedelta(days=62)
    if interval in {"1d", "3d"}:
        # Crypto trades continuously, so a daily bar must advance every day.
        # Equities need room for weekends and exchange holidays.
        return timedelta(hours=26 if market == "crypto" else 120)
    if seconds is None:
        return timedelta(hours=48 if market == "crypto" else 120)

    base = timedelta(seconds=max(seconds * 2, 60))
    if market not in _EQUITY_MARKETS:
        return base

    reference = now if now is not None else pd.Timestamp.now(tz="UTC")
    status = market_status_for(market, reference.to_pydatetime())
    if status == "closed":
        return max(base, _CLOSED_MARKET_GRACE)
    # A live equity feed can still be delayed; ten minutes avoids flagging a
    # normal provider delay while catching hours-old intraday history.
    return max(base, timedelta(minutes=10))


def last_candle_age(
    frame: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
) -> timedelta | None:
    if frame is None or frame.empty:
        return None
    reference = now if now is not None else pd.Timestamp.now(tz="UTC")
    latest = pd.Timestamp(frame.index[-1])
    if latest.tzinfo is None:
        latest = latest.tz_localize("UTC")
    else:
        latest = latest.tz_convert("UTC")
    return reference - latest


def is_candle_stale(
    frame: pd.DataFrame,
    market: str,
    interval: str = "1d",
    *,
    now: pd.Timestamp | None = None,
) -> bool:
    """True when the newest candle is older than its interval-aware window."""
    if frame is None or frame.empty:
        return True
    age = last_candle_age(frame, now=now)
    if age is None:
        return True
    return age > freshness_window(market, interval, now=now)
