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
    assert result["annualization_factor"] == 252
    for trade in result["trades"]:
        assert trade["net_pnl"] == pytest.approx(trade["gross_pnl"] - trade["total_costs"])
    assert result["final_equity"] == pytest.approx(
        result["initial_capital"] + sum(trade["net_pnl"] for trade in result["trades"])
    )


def test_backtest_charges_each_side_once_for_end_of_test_exit(monkeypatch):
    index = pd.date_range("2025-01-01", periods=241, freq="B", tz="UTC")
    frame = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=index)
    indicators = frame.copy()
    for column, value in {"sma_50": 99.0, "sma_200": 98.0, "rsi_14": 60.0, "adx": 25.0,
                          "atr_14": 1.0, "donchian_upper_20": 99.0, "rvol_20": 1.2}.items():
        indicators[column] = value
    indicators.loc[indicators.index[:201], "sma_200"] = 97.0
    monkeypatch.setattr("app.services.backtest.compute_indicators", lambda _: indicators)
    result = run_trend_breakout_backtest(frame, initial_capital=10_000, risk_fraction=0.01, cost_bps_per_side=10)
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    expected_costs = (trade["entry_price"] + trade["exit_price"]) * trade["quantity"] * 0.001
    assert trade["total_costs"] == pytest.approx(expected_costs)
    assert trade["net_pnl"] == pytest.approx(trade["gross_pnl"] - expected_costs)
