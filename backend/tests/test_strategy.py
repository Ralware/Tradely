import numpy as np
import pandas as pd

from app.services.strategy import evaluate_trend_breakout, position_size


def synthetic_uptrend(rows: int = 270) -> pd.DataFrame:
    close = np.linspace(100, 250, rows)
    high = close + 0.4
    low = close - 0.4
    open_ = close - 0.1
    volume = np.full(rows, 100_000.0)
    # Latest completed candle breaks the previous 20-bar high with volume confirmation.
    close[-1] = close[-2] + 2.0
    open_[-1] = close[-1] - 0.2
    high[-1] = close[-1] + 0.4
    low[-1] = close[-1] - 0.4
    volume[-1] = 250_000.0
    index = pd.date_range("2025-01-01", periods=rows, freq="B", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": volume}, index=index)


def test_strategy_requires_sufficient_history():
    frame = synthetic_uptrend(100)
    result = evaluate_trend_breakout(frame, symbol="TEST", market="global")
    assert result.state == "INSUFFICIENT_DATA"


def test_trend_breakout_signal_is_explainable():
    frame = synthetic_uptrend()
    result = evaluate_trend_breakout(frame, symbol="TEST", market="global")
    assert result.state == "BUY"
    assert len(result.conditions) == 8
    assert all(item.passed for item in result.conditions[:7])
    assert result.conditions[-1].passed is False
    assert result.stop_reference < result.entry_reference


def test_position_sizing_calculation():
    result = position_size(capital=100_000, risk_fraction=0.005, entry=1_000, stop=980)
    assert result["risk_budget"] == 500
    assert result["quantity"] == 25
    assert result["planned_loss"] == 500


def test_position_sizing_rejects_stop_above_entry():
    import pytest
    with pytest.raises(ValueError, match="stop must be below entry"):
        position_size(capital=100_000, risk_fraction=0.005, entry=980, stop=1_000)


def test_sell_signal_means_exit_long_on_prior_ten_bar_low_break():
    frame = synthetic_uptrend()
    prior_floor = frame["low"].iloc[-11:-1].min()
    frame.iloc[-1, frame.columns.get_loc("open")] = prior_floor - 2.0
    frame.iloc[-1, frame.columns.get_loc("high")] = prior_floor - 1.0
    frame.iloc[-1, frame.columns.get_loc("low")] = prior_floor - 3.0
    frame.iloc[-1, frame.columns.get_loc("close")] = prior_floor - 2.5
    result = evaluate_trend_breakout(frame, symbol="TEST", market="global")
    assert result.state == "SELL"
    assert "exit an existing long" in result.explanation
