import numpy as np
import pandas as pd
import pytest
from app.services.backtest import run_trend_breakout_backtest


def synthetic_uptrend(rows: int = 270) -> pd.DataFrame:
    close = np.linspace(100, 250, rows)
    high = close + 1.25
    low = close - 1.25
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
    high = close + 1.25
    low = close - 1.25
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



@pytest.mark.parametrize(("factory", "mode", "direction"), [
    (synthetic_uptrend, "long_only", "LONG"),
    (synthetic_downtrend, "short_only", "SHORT"),
])
def test_completed_breakout_sizes_exposure_at_next_open(factory, mode, direction):
    frame = factory()
    next_open = frame.iloc[-1].close
    execution_bar = frame.iloc[[-1]].copy()
    execution_bar.index += pd.Timedelta(days=1)
    execution_bar["open"] = next_open
    data = pd.concat([frame, execution_bar])
    result = run_trend_breakout_backtest(data, direction_mode=mode)
    trade, = result["trades"]
    assert trade["direction"] == direction
    assert pd.Timestamp(trade["signal_time"]) == frame.index[-1]
    assert pd.Timestamp(trade["entry_time"]) == execution_bar.index[0]
    assert 0 < trade["quantity"] * next_open <= 950

    data["is_final"] = True
    data.loc[frame.index[-1], "is_final"] = False
    assert not run_trend_breakout_backtest(data, direction_mode=mode)["trades"]
