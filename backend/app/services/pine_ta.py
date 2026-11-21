"""Pine Script v6 compatible technical-analysis primitives.

Tradely's trading indicators use pandas conveniences (``ewm``, ``rolling``)
whose initialization and missing-value behaviour differ from Pine Script.
The TradingView Technical Rating library depends on Pine's exact semantics, so
this module implements the subset of Pine built-ins and ``TradingView/ta/9``
functions that the library calls.

Every function takes and returns a pandas Series indexed like the input.  A
missing value is represented by ``numpy.nan`` and propagates the same way as
Pine's ``na``.  No value is back-filled, and no intermediate result is rounded.

The source/version audit is recorded in ``docs/TECHNICAL_RATING_SOURCE_AUDIT.md``.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


def _series(values: Iterable[float] | np.ndarray, index: pd.Index, name: str | None = None) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float), index=index, name=name)


def _values(source: pd.Series) -> np.ndarray:
    return pd.to_numeric(source, errors="coerce").to_numpy(dtype=float)


def _rolling_sum(source: pd.Series, length: int) -> pd.Series:
    return source.rolling(length, min_periods=length).sum()


def highest(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.highest``: maximum over exactly ``length`` non-na values."""
    if length < 1:
        raise ValueError("length must be >= 1")
    return source.rolling(length, min_periods=length).max()


def lowest(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.lowest``: minimum over exactly ``length`` non-na values."""
    if length < 1:
        raise ValueError("length must be >= 1")
    return source.rolling(length, min_periods=length).min()


def sma(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.sma``: arithmetic mean over exactly ``length`` values."""
    if length < 1:
        raise ValueError("length must be >= 1")
    return source.rolling(length, min_periods=length).mean()


def _seeded_recursive(
    source: pd.Series,
    length: int,
    alpha: float,
    *,
    name: str | None = None,
) -> pd.Series:
    """Pine-style RMA seed: first full SMA window, then recursive smoothing.

    A later ``na`` emits ``na`` for that bar; the previous state is retained
    so the filter can resume without inventing data. Pine ``ta.ema`` uses a
    different first-value seed and is implemented separately below.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    values = _values(source)
    output = np.full(len(values), np.nan, dtype=float)
    run = 0
    seed_end: int | None = None
    for index, value in enumerate(values):
        if np.isfinite(value):
            run += 1
            if run == length:
                seed_end = index
                output[index] = float(np.mean(values[index - length + 1 : index + 1]))
                break
        else:
            run = 0
    if seed_end is None:
        return _series(output, source.index, name or source.name)

    previous = output[seed_end]
    for index in range(seed_end + 1, len(values)):
        value = values[index]
        if not np.isfinite(value):
            output[index] = np.nan
            continue
        previous = alpha * value + (1.0 - alpha) * previous
        output[index] = previous
    return _series(output, source.index, name or source.name)


def ema(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.ema``: alpha ``2 / (length + 1)``, seeded by first valid value.

    Pine's EMA starts on the first non-``na`` source value and then applies
    ``alpha * source + (1 - alpha) * previous_ema``. Unlike ``ta.rma``, it does
    not wait for a full SMA window. Missing source values emit ``na`` while
    preserving the previous recursive state for the next valid observation.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    values = _values(source)
    output = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (length + 1.0)
    previous: float | None = None
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        previous = value if previous is None else alpha * value + (1.0 - alpha) * previous
        output[index] = previous
    return _series(output, source.index, source.name)


def rma(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.rma`` (Wilder): alpha ``1 / length``, seeded by SMA."""
    if length < 1:
        raise ValueError("length must be >= 1")
    return _seeded_recursive(source, length, 1.0 / length, name=source.name)


def wma(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.wma``: linearly weighted mean with weights 1..length."""
    if length < 1:
        raise ValueError("length must be >= 1")
    weights = np.arange(1, length + 1, dtype=float)
    denominator = float(weights.sum())
    values = _values(source)
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if np.isfinite(window).all():
            output[index] = float(np.dot(window, weights) / denominator)
    return _series(output, source.index, source.name)


def hma(source: pd.Series, length: int = 9) -> pd.Series:
    """Pine ``ta.hma``.

    ``wma(2 * wma(source, length / 2) - wma(source, length), sqrt(length))``.
    Pine's built-in resolves the half-length with integer division; for the
    rating library's length of 9 that is 4 and the square root is 3.
    """
    if length < 2:
        raise ValueError("length must be >= 2")
    half = length // 2
    root = int(round(math.sqrt(length)))
    inner = 2.0 * wma(source, half) - wma(source, length)
    return wma(inner, root)


def vwma(source: pd.Series, volume: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.vwma``: volume-weighted mean, ``na`` when volume sums to zero."""
    if length < 1:
        raise ValueError("length must be >= 1")
    numerator = _rolling_sum(source * volume, length)
    denominator = _rolling_sum(volume, length)
    return numerator / denominator.replace(0.0, np.nan)


def change(source: pd.Series, length: int = 1) -> pd.Series:
    return source.diff(length)


def rsi(source: pd.Series, length: int = 14) -> pd.Series:
    """Pine ``ta.rsi`` using Wilder's RMA for average gain and loss."""
    if length < 1:
        raise ValueError("length must be >= 1")
    delta = source.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = rma(gain, length)
    average_loss = rma(loss, length)
    output = 100.0 - 100.0 / (1.0 + average_gain / average_loss.replace(0.0, np.nan))
    output = output.mask((average_loss == 0.0) & (average_gain > 0.0), 100.0)
    output = output.mask((average_loss == 0.0) & (average_gain == 0.0), 50.0)
    output = output.mask((average_gain == 0.0) & (average_loss > 0.0), 0.0)
    return output


def dev(source: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.dev``: mean absolute deviation from the SMA over ``length`` bars."""
    if length < 1:
        raise ValueError("length must be >= 1")
    values = _values(source)
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if np.isfinite(window).all():
            mean = float(np.mean(window))
            output[index] = float(np.mean(np.abs(window - mean)))
    return _series(output, source.index, source.name)


def cci(source: pd.Series, length: int = 20) -> pd.Series:
    """Pine ``ta.cci``: ``(source - sma) / (0.015 * dev)``."""
    if length < 1:
        raise ValueError("length must be >= 1")
    average = sma(source, length)
    deviation = dev(source, length)
    return (source - average) / (0.015 * deviation.replace(0.0, np.nan))


def stoch(source: pd.Series, high: pd.Series, low: pd.Series, length: int) -> pd.Series:
    """Pine ``ta.stoch``: ``100 * (source - lowest) / (highest - lowest)``."""
    if length < 1:
        raise ValueError("length must be >= 1")
    lowest_low = lowest(low, length)
    highest_high = highest(high, length)
    span = (highest_high - lowest_low).replace(0.0, np.nan)
    return 100.0 * (source - lowest_low) / span


def stoch_full(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period_k: int = 14,
    smooth_k: int = 3,
    period_d: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """``TradingView/ta/9.stochFull``."""
    raw = stoch(close, high, low, period_k)
    k = sma(raw, smooth_k)
    d = sma(k, period_d)
    return k, d


def stoch_rsi(
    close: pd.Series,
    length_rsi: int = 14,
    period_k: int = 14,
    smooth_k: int = 3,
    period_d: int = 3,
    source: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series]:
    """``TradingView/ta/9.stochRsi``."""
    base = close if source is None else source
    rsi_values = rsi(base, length_rsi)
    raw = stoch(rsi_values, rsi_values, rsi_values, period_k)
    k = sma(raw, smooth_k)
    d = sma(k, period_d)
    return k, d


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    result = ranges.max(axis=1, skipna=False)
    # Pine's ta.tr on the first bar has no previous close and uses high - low.
    if len(result):
        result.iloc[0] = high.iloc[0] - low.iloc[0]
    return result


def dmi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    di_length: int = 14,
    adx_smoothing: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Pine ``ta.dmi``: returns ``(+DI, -DI, ADX)``."""
    if di_length < 1 or adx_smoothing < 1:
        raise ValueError("lengths must be >= 1")
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)
    plus_dm = plus_dm.where(up_move.notna(), np.nan)
    minus_dm = minus_dm.where(down_move.notna(), np.nan)
    tr = true_range(high, low, close)
    tr_smoothed = rma(tr, di_length)
    plus_di = 100.0 * rma(plus_dm, di_length) / tr_smoothed.replace(0.0, np.nan)
    minus_di = 100.0 * rma(minus_dm, di_length) / tr_smoothed.replace(0.0, np.nan)
    total = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / total.where(total != 0.0, 1.0)
    adx = rma(dx, adx_smoothing)
    return plus_di, minus_di, adx


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Pine ``ta.macd``: returns ``(macd, signal, histogram)``."""
    if not 0 < fast < slow or signal < 1:
        raise ValueError("MACD requires 0 < fast < slow and signal >= 1")
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line, signal)
    return line, signal_line, line - signal_line


def awesome_oscillator(high: pd.Series, low: pd.Series) -> pd.Series:
    """``TradingView/ta/9.ao`` with its default 5/34 lengths."""
    source = (high + low) / 2.0
    return sma(source, 5) - sma(source, 34)


def momentum(source: pd.Series, length: int = 10) -> pd.Series:
    return source - source.shift(length)


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Pine ``ta.wpr``: range ``-100..0``."""
    highest_high = highest(high, length)
    lowest_low = lowest(low, length)
    span = (highest_high - lowest_low).replace(0.0, np.nan)
    return 100.0 * (close - highest_high) / span


def ultimate_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    fast: int = 7,
    mid: int = 14,
    slow: int = 28,
) -> pd.Series:
    """``TradingView/ta/9.uo``."""
    previous_close = close.shift(1)
    true_max = pd.concat([high, previous_close], axis=1).max(axis=1, skipna=False)
    true_min = pd.concat([low, previous_close], axis=1).min(axis=1, skipna=False)
    true_range_values = true_max - true_min
    buying_pressure = close - true_min
    average_fast = _rolling_sum(buying_pressure, fast) / _rolling_sum(true_range_values, fast)
    average_mid = _rolling_sum(buying_pressure, mid) / _rolling_sum(true_range_values, mid)
    average_slow = _rolling_sum(buying_pressure, slow) / _rolling_sum(true_range_values, slow)
    return 100.0 * (4.0 * average_fast + 2.0 * average_mid + average_slow) / 7.0


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    conversion: int = 9,
    base: int = 26,
    span: int = 52,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """``TradingView/ta/9.ichimoku`` without future displacement."""
    def midpoint(length: int) -> pd.Series:
        return (highest(high, length) + lowest(low, length)) / 2.0

    tenkan = midpoint(conversion)
    kijun = midpoint(base)
    span_one = (tenkan + kijun) / 2.0
    span_two = midpoint(span)
    return tenkan, kijun, span_one, span_two, close


def crossover(first: pd.Series, second: pd.Series | float) -> pd.Series:
    """Pine ``ta.crossover``; ``na`` comparisons are false."""
    other = second if isinstance(second, pd.Series) else pd.Series(second, index=first.index)
    current = first > other
    previous = first.shift(1) <= other.shift(1)
    return (current & previous).fillna(False)


def crossunder(first: pd.Series, second: pd.Series | float) -> pd.Series:
    """Pine ``ta.crossunder``; ``na`` comparisons are false."""
    other = second if isinstance(second, pd.Series) else pd.Series(second, index=first.index)
    current = first < other
    previous = first.shift(1) >= other.shift(1)
    return (current & previous).fillna(False)


def sign(source: pd.Series) -> pd.Series:
    """Pine ``math.sign``; ``na`` stays ``na``."""
    values = _values(source)
    output = np.full(len(values), np.nan, dtype=float)
    finite = np.isfinite(values)
    output[finite] = np.sign(values[finite])
    return _series(output, source.index, source.name)
