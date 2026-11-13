import numpy as np
import pandas as pd
import pytest

from app.services.backtest import run_trend_breakout_backtest


def test_backtest_requires_enough_history():
    index = pd.date_range("2025-01-01", periods=100, freq="B", tz="UTC")
    frame = pd.DataFrame({
        "open": np.arange(100) + 10.0,
        "high": np.arange(100) + 11.0,
        "low": np.arange(100) + 9.0,
        "close": np.arange(100) + 10.5,
        "volume": np.full(100, 100_000.0),
    }, index=index)
    with pytest.raises(ValueError, match="240 daily bars"):
        run_trend_breakout_backtest(frame)


def test_backtest_returns_expected_metrics_and_cost_model():
    rows = 300
    close = np.linspace(100, 300, rows)
    index = pd.date_range("2024-01-01", periods=rows, freq="B", tz="UTC")
    frame = pd.DataFrame({
        "open": close - 0.1, "high": close + 0.2, "low": close - 0.5,
        "close": close, "volume": np.full(rows, 100_000.0),
    }, index=index)
    result = run_trend_breakout_backtest(frame, cost_bps_per_side=15)
    assert result["cost_bps_per_side"] == 15
    assert "max_drawdown_pct" in result
    assert "trades" in result
    assert result["limitations"]
