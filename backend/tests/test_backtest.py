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


def test_long_short_backtest_opens_and_accounts_for_short_exposure(monkeypatch):
    index = pd.date_range("2025-01-01", periods=241, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=index,
    )
    frame.iloc[220, frame.columns.get_loc("open")] = 98.0
    frame.iloc[220, frame.columns.get_loc("high")] = 99.0
    frame.iloc[220, frame.columns.get_loc("low")] = 97.0
    frame.iloc[220, frame.columns.get_loc("close")] = 98.0
    frame.iloc[-1, frame.columns.get_loc("high")] = 101.0
    frame.iloc[-1, frame.columns.get_loc("low")] = 94.0
    frame.iloc[-1, frame.columns.get_loc("close")] = 95.0

    indicators = frame.copy()
    for column, value in {
        "sma_50": 101.0,
        "sma_200": 102.0,
        "rsi_14": 40.0,
        "adx": 25.0,
        "atr_14": 1.0,
        "donchian_upper_20": 101.0,
        "rvol_20": 1.2,
    }.items():
        indicators[column] = value
    indicators.loc[indicators.index[:201], "sma_200"] = 103.0
    monkeypatch.setattr("app.services.backtest.compute_indicators", lambda _: indicators)

    result = run_trend_breakout_backtest(
        frame,
        initial_capital=10_000,
        risk_fraction=0.01,
        cost_bps_per_side=10,
        direction_mode="long_short",
    )

    assert result["direction_mode"] == "long_short"
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["direction"] == "SHORT"
    assert trade["gross_pnl"] > 0
    assert trade["net_pnl"] == pytest.approx(trade["gross_pnl"] - trade["total_costs"])
    assert trade["exit_reason"] == "end_of_test"

    short_only = run_trend_breakout_backtest(
        frame,
        initial_capital=10_000,
        risk_fraction=0.01,
        cost_bps_per_side=10,
        direction_mode="short_only",
    )
    assert short_only["trade_count"] == 1
    assert short_only["trades"][0]["direction"] == "SHORT"

    indicators.loc[index[222], ["open", "high", "low"]] = [105.0, 106.0, 104.0]
    stopped = run_trend_breakout_backtest(
        frame,
        initial_capital=10_000,
        risk_fraction=0.01,
        cost_bps_per_side=10,
        direction_mode="long_short",
    )
    stop_trade = stopped["trades"][0]
    assert stop_trade["direction"] == "SHORT"
    assert stop_trade["exit_reason"] == "protective_stop"
    assert stop_trade["exit_price"] == 105.0
    expected_costs = (stop_trade["entry_price"] + 105.0) * stop_trade["quantity"] * 0.001
    assert stop_trade["total_costs"] == pytest.approx(expected_costs)
    assert stop_trade["net_pnl"] == pytest.approx(
        stop_trade["gross_pnl"] - expected_costs
    )


def test_long_only_backtest_does_not_open_short_on_bearish_breakout(monkeypatch):
    index = pd.date_range("2025-01-01", periods=241, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=index,
    )
    frame.iloc[220, frame.columns.get_loc("open")] = 98.0
    frame.iloc[220, frame.columns.get_loc("high")] = 99.0
    frame.iloc[220, frame.columns.get_loc("low")] = 97.0
    frame.iloc[220, frame.columns.get_loc("close")] = 98.0
    indicators = frame.copy()
    for column, value in {
        "sma_50": 101.0,
        "sma_200": 102.0,
        "rsi_14": 40.0,
        "adx": 25.0,
        "atr_14": 1.0,
        "donchian_upper_20": 101.0,
        "rvol_20": 1.2,
    }.items():
        indicators[column] = value
    indicators.loc[indicators.index[:201], "sma_200"] = 103.0
    monkeypatch.setattr("app.services.backtest.compute_indicators", lambda _: indicators)

    result = run_trend_breakout_backtest(frame, direction_mode="long_only")

    assert result["direction_mode"] == "long_only"
    assert result["trade_count"] == 0
    assert any("never opens a short" in limitation for limitation in result["limitations"])


def test_backtest_ignores_unfinished_signal_candle(monkeypatch):
    index = pd.date_range("2025-01-01", periods=241, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
            "is_final": True,
        },
        index=index,
    )
    frame.iloc[220, frame.columns.get_loc("open")] = 98.0
    frame.iloc[220, frame.columns.get_loc("high")] = 99.0
    frame.iloc[220, frame.columns.get_loc("low")] = 97.0
    frame.iloc[220, frame.columns.get_loc("close")] = 98.0
    frame.iloc[220, frame.columns.get_loc("is_final")] = False
    indicators = frame.copy()
    for column, value in {
        "sma_50": 101.0,
        "sma_200": 102.0,
        "rsi_14": 40.0,
        "adx": 25.0,
        "atr_14": 1.0,
        "donchian_upper_20": 101.0,
        "rvol_20": 1.2,
    }.items():
        indicators[column] = value
    indicators.loc[indicators.index[:201], "sma_200"] = 103.0
    monkeypatch.setattr("app.services.backtest.compute_indicators", lambda _: indicators)

    result = run_trend_breakout_backtest(frame, direction_mode="long_short")

    assert result["trade_count"] == 0
    assert any("Unfinished candles were excluded" in item for item in result["limitations"])


def _bullish_flat_fixture(monkeypatch, rows: int = 241):
    index = pd.date_range("2025-01-01", periods=rows, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
        index=index,
    )
    indicators = frame.copy()
    for column, value in {
        "sma_50": 99.0,
        "sma_200": 98.0,
        "rsi_14": 60.0,
        "adx": 25.0,
        "atr_14": 1.0,
        "donchian_upper_20": 99.0,
        "rvol_20": 1.2,
    }.items():
        indicators[column] = value
    indicators.loc[indicators.index[:201], "sma_200"] = 97.0
    monkeypatch.setattr("app.services.backtest.compute_indicators", lambda _: indicators)
    return frame


@pytest.mark.parametrize("capital", [50.0, 1_000.0, 100_000.0])
def test_backtest_takes_trades_for_any_positive_capital(monkeypatch, capital):
    frame = _bullish_flat_fixture(monkeypatch)
    result = run_trend_breakout_backtest(
        frame, initial_capital=capital, risk_fraction=0.01, cost_bps_per_side=10,
    )
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert 0 < trade["quantity"] <= (capital * 0.95) / 100.0
    assert result["final_equity"] == pytest.approx(
        result["initial_capital"] + sum(item["net_pnl"] for item in result["trades"])
    )


def test_backtest_returns_scale_consistently_across_capital(monkeypatch):
    frame = _bullish_flat_fixture(monkeypatch)
    small = run_trend_breakout_backtest(
        frame, initial_capital=500.0, risk_fraction=0.01, cost_bps_per_side=10,
    )
    large = run_trend_breakout_backtest(
        frame, initial_capital=500_000.0, risk_fraction=0.01, cost_bps_per_side=10,
    )
    assert small["trade_count"] == large["trade_count"] == 1
    assert small["net_return_pct"] == pytest.approx(large["net_return_pct"], rel=1e-6, abs=1e-9)
