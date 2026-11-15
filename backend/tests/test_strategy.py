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

def synthetic_downtrend(rows: int = 270) -> pd.DataFrame:
    close = np.linspace(250, 100, rows)
    high = close + 0.4
    low = close - 0.4
    open_ = close + 0.1
    volume = np.full(rows, 100_000.0)
    close[-1] = close[-2] - 2.0
    open_[-1] = close[-1] + 0.2
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

def test_short_signal_and_position_side_exit_are_explicit():
    short_entry = evaluate_trend_breakout(
        synthetic_downtrend(), symbol="TEST", market="global", direction_mode="short_only"
    )
    assert short_entry.state == "SELL_SHORT"
    assert short_entry.direction == "SHORT"
    assert short_entry.stop_reference > short_entry.entry_reference

    frame = synthetic_downtrend()
    cover_level = frame["high"].iloc[-11:-1].max()
    frame.iloc[-1, frame.columns.get_loc("open")] = cover_level + 1
    frame.iloc[-1, frame.columns.get_loc("high")] = cover_level + 2
    frame.iloc[-1, frame.columns.get_loc("low")] = cover_level + 0.5
    frame.iloc[-1, frame.columns.get_loc("close")] = cover_level + 1.5
    short_exit = evaluate_trend_breakout(
        frame,
        symbol="TEST",
        market="global",
        direction_mode="short_only",
        position_side="SHORT",
    )
    assert short_exit.state == "BUY_TO_COVER"
    assert short_exit.direction == "SHORT"

    no_short_position = evaluate_trend_breakout(
        synthetic_uptrend(), symbol="TEST", market="global", direction_mode="short_only"
    )
    assert no_short_position.state == "WAIT"

def test_long_only_mode_never_opens_short_and_ignores_incomplete_candles():
    bearish = synthetic_downtrend()
    long_only = evaluate_trend_breakout(bearish, symbol="TEST", market="global")
    assert long_only.state != "SELL_SHORT"

    bearish["is_final"] = True
    bearish.iloc[-1, bearish.columns.get_loc("is_final")] = False
    incomplete = evaluate_trend_breakout(
        bearish, symbol="TEST", market="global", direction_mode="long_short"
    )
    assert incomplete.state == "WAIT"
    assert incomplete.conditions[0].passed is False

def test_short_position_sizing_requires_stop_above_entry():
    result = position_size(
        capital=100_000,
        risk_fraction=0.005,
        entry=100,
        stop=110,
        direction="SHORT",
    )
    assert result["direction"] == "SHORT"
    assert result["risk_per_unit"] == 10
    assert result["quantity"] == 50

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
