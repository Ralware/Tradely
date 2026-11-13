import numpy as np
import pandas as pd
import pytest

from app.services.indicators import atr, compute_indicators, donchian, rsi, sma, validate_ohlcv


def test_sma_requires_full_lookback():
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = sma(values, 3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(3.0)


def test_rsi_monotonic_up_is_100_after_warmup():
    result = rsi(pd.Series(range(30), dtype=float), 14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_flat_series_is_neutral_50():
    result = rsi(pd.Series([10.0] * 30), 14)
    assert result.iloc[-1] == pytest.approx(50.0)


def test_rsi_matches_wilder_reference_example():
    # Classic Wilder RSI example; first RSI(14) should be approximately 70.464.
    prices = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10,
        45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
        46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21,
    ]
    result = rsi(pd.Series(prices, dtype=float), 14)
    assert result.iloc[14] == pytest.approx(70.4641, abs=1e-3)


def test_donchian_excludes_current_candle():
    frame = pd.DataFrame({
        "open": [1, 2, 3, 4], "high": [2, 3, 4, 100],
        "low": [0.5, 1.5, 2.5, 3.5], "close": [1.5, 2.5, 3.5, 50],
        "volume": [100, 100, 100, 100],
    })
    result = donchian(frame, 2)
    assert result.iloc[2, 0] == pytest.approx(3.0)
    assert result.iloc[3, 0] == pytest.approx(4.0)


def test_atr_uses_gap_aware_true_range():
    index = pd.date_range("2025-01-01", periods=20, freq="D", tz="UTC")
    frame = pd.DataFrame({
        "open": [10.0] * 20,
        "high": [11.0] * 20,
        "low": [9.0] * 20,
        "close": [10.0] * 20,
        "volume": [1000.0] * 20,
    }, index=index)
    frame.loc[index[-1], ["open", "high", "low", "close"]] = [15.0, 16.0, 14.0, 15.0]
    result = atr(frame, 14)
    assert result.iloc[-1] > 2.0


def test_daily_vwap_is_unavailable_without_intraday_volume_distribution():
    index = pd.date_range("2025-01-01", periods=30, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100, 120, len(index)), index=index)
    frame = pd.DataFrame({
        "open": close - 0.5, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": 1000.0,
    }, index=index)
    result = compute_indicators(frame)
    assert result["vwap_session"].isna().all()


def test_intraday_vwap_resets_at_new_session():
    index = pd.to_datetime([
        "2025-01-01T09:15:00Z", "2025-01-01T09:30:00Z",
        "2025-01-02T09:15:00Z", "2025-01-02T09:30:00Z",
    ])
    frame = pd.DataFrame({
        "open": [10, 11, 20, 21], "high": [11, 12, 21, 22],
        "low": [9, 10, 19, 20], "close": [10, 11, 20, 21],
        "volume": [100, 100, 100, 100],
    }, index=index)
    result = compute_indicators(frame)
    # On the first bar of a new session VWAP starts from that bar's typical price.
    expected = (21 + 19 + 20) / 3
    assert result.loc[index[2], "vwap_session"] == pytest.approx(expected)


def test_ohlcv_validation_rejects_inconsistent_candle():
    frame = pd.DataFrame({
        "open": [10], "high": [9], "low": [8], "close": [9], "volume": [100]
    })
    with pytest.raises(ValueError, match="Invalid OHLCV"):
        validate_ohlcv(frame)
