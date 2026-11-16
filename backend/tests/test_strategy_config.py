import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.services.indicators import compute_indicators, sma
from app.services.strategy_config import StrategyConfig
from app.services.backtest import run_trend_breakout_backtest


def sample_frame(periods=1100):
    index = pd.date_range("2020-01-01", periods=periods, freq="D", tz="UTC")
    close = pd.Series(np.linspace(50, 180, periods) + np.sin(np.arange(periods) / 7), index=index)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": np.linspace(1000, 3000, periods)}, index=index)


def test_custom_sma_period_recalculates_indicator_values():
    frame = sample_frame()
    config = StrategyConfig(sma_fast_period=100, sma_slow_period=250)
    calculated = compute_indicators(frame, strategy_config=config)
    assert calculated["sma_100"].iloc[-1] == pytest.approx(sma(frame.close, 100).iloc[-1])
    assert calculated["sma_100"].iloc[-1] != pytest.approx(sma(frame.close, 50).iloc[-1])
    assert calculated["sma_250"].iloc[-1] == pytest.approx(sma(frame.close, 250).iloc[-1])


def test_custom_periods_thresholds_and_matching_donchian_periods_are_supported():
    config = StrategyConfig(sma_fast_period=30, sma_slow_period=80, rsi_period=21,
                            adx_period=18, atr_period=12, donchian_entry_period=15,
                            donchian_exit_period=15, rvol_period=25, min_adx=25,
                            min_rvol=1.2, rsi_threshold=55)
    result = compute_indicators(sample_frame(300), strategy_config=config)
    assert "sma_30" in result and "sma_80" in result and "rsi_21" in result
    assert "atr_12" in result and "rvol_25" in result
    assert "donchian_upper_15" in result and "donchian_lower_15" in result


def test_invalid_sma_relationship_is_rejected():
    with pytest.raises(ValidationError):
        StrategyConfig(sma_fast_period=200, sma_slow_period=50)


def test_backtest_receives_and_returns_the_exact_configuration(monkeypatch):
    frame = sample_frame(300)
    config = StrategyConfig(sma_fast_period=30, sma_slow_period=80, rsi_period=10,
                            adx_period=10, atr_period=10, donchian_entry_period=12,
                            donchian_exit_period=8, rvol_period=12)
    real_compute = compute_indicators
    observed = {}

    def configured_compute(data, *, strategy_config=None):
        observed["config"] = strategy_config
        return real_compute(data, strategy_config=strategy_config)

    monkeypatch.setattr("app.services.backtest.compute_indicators", configured_compute)
    result = run_trend_breakout_backtest(frame, strategy_config=config)
    assert observed["config"] == config
    assert result["strategy_config"] == config.model_dump(mode="json")

