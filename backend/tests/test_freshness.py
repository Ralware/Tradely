from datetime import UTC, datetime

import pandas as pd
import pytest

from app.services.freshness import (
    freshness_window,
    interval_seconds,
    is_candle_stale,
    last_candle_age,
)


def frame_at(timestamp):
    return pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=[pd.Timestamp(timestamp, tz="UTC")],
    )


def test_interval_seconds_accepts_aliases():
    assert interval_seconds("1w") == 604800
    assert interval_seconds("1M") == 2592000
    assert interval_seconds("4h") == 14400
    assert interval_seconds("2d") is None


def test_intraday_window_scales_with_the_interval():
    # A five-minute-old 1m bar is stale; the old 48h crypto threshold accepted it.
    crypto_window = freshness_window("crypto", "1m")
    assert crypto_window == pd.Timedelta(minutes=2)
    assert freshness_window("crypto", "15m") == pd.Timedelta(minutes=30)


def test_daily_crypto_bar_must_advance_every_day():
    assert freshness_window("crypto", "1d") == pd.Timedelta(hours=26)


def test_weekly_and_monthly_windows_cover_a_full_period():
    assert freshness_window("crypto", "1wk") == pd.Timedelta(days=14)
    assert freshness_window("crypto", "1mo") == pd.Timedelta(days=62)


def test_equity_intraday_uses_market_session_awareness():
    # Monday 12:00 UTC = 17:30 IST; the Indian market is closed.
    monday_afternoon = pd.Timestamp("2026-11-23T12:00:00Z")
    closed_window = freshness_window("india", "1m", now=monday_afternoon)
    assert closed_window == pd.Timedelta(days=4)

    # Monday 06:00 UTC = 11:30 IST; the market is open.
    monday_morning = pd.Timestamp("2026-11-23T06:00:00Z")
    open_window = freshness_window("india", "1m", now=monday_morning)
    assert open_window == pd.Timedelta(minutes=10)


def test_staleness_uses_the_newest_candle():
    now = pd.Timestamp("2026-11-24T12:00:00Z")
    assert is_candle_stale(frame_at("2026-11-24T11:57:00Z"), "crypto", "1m", now=now)
    assert not is_candle_stale(frame_at("2026-11-24T11:58:00Z"), "crypto", "1m", now=now)
    assert not is_candle_stale(frame_at("2026-11-23T12:00:00Z"), "crypto", "1d", now=now)
    assert is_candle_stale(frame_at("2026-11-22T12:00:00Z"), "crypto", "1d", now=now)


def test_empty_frames_are_stale():
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert is_candle_stale(empty, "crypto", "1d") is True
    assert last_candle_age(empty) is None


def test_naive_timestamps_are_treated_as_utc():
    naive = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=[pd.Timestamp("2026-11-24T11:59:00")],
    )
    age = last_candle_age(naive, now=pd.Timestamp("2026-11-24T12:00:00Z"))
    assert age == pd.Timedelta(minutes=1)
