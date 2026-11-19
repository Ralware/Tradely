"""Deterministic artificial OHLCV for regression and performance tests."""

from pathlib import Path

import numpy as np
import pandas as pd


def write_fixture(directory: Path, timeframe: str = "2h", bars: int = 6000):
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    i = np.arange(bars)
    close = 200 * np.exp(
        0.00005 * i + 0.12 * np.sin(i / 180) + np.cumsum(rng.normal(0, 0.004, bars))
    )
    opens = np.r_[close[0], close[:-1]]
    spread = rng.uniform(0.001, 0.008, bars) * close
    base = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) + spread,
            "low": np.minimum(opens, close) - spread,
            "close": close,
            "volume": rng.uniform(1, 100, bars),
        },
        index=pd.date_range("2000-01-03", periods=bars, freq=timeframe, tz="UTC", name="datetime"),
    )
    htf = base.resample("W-MON" if timeframe == "1d" else "1D", label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    paths = directory / f"{timeframe}_base.csv", directory / f"{timeframe}_htf.csv"
    for frame, path in zip((base, htf), paths):
        frame.assign(timestamp=frame.index.as_unit("ms").asi8)[
            ["timestamp", "open", "high", "low", "close", "volume"]
        ].to_csv(path, index=False)
    return paths
