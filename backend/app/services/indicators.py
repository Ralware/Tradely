from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def validate_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(sorted(missing))}")
    result = frame.copy()
    for column in REQUIRED_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.loc[~result.index.duplicated(keep="last")]
    result = result.sort_index(kind="stable")
    if result.empty:
        raise ValueError("No valid OHLCV rows")
    finite = pd.Series(
        np.isfinite(result[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)).all(axis=1),
        index=result.index,
    )
    invalid = (
        ~finite
        | (result["high"] < result[["open", "close", "low"]].max(axis=1))
        | (result["low"] > result[["open", "close", "high"]].min(axis=1))
        | (result["volume"] < 0)
        | (result[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    if invalid.any():
        raise ValueError(f"Invalid OHLCV rows detected: {int(invalid.sum())}")
    return result


def sma(series: pd.Series, period: int) -> pd.Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    output = 100 - (100 / (1 + rs))
    output = output.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    output = output.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return output


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    if not 0 < fast < slow or signal < 1:
        raise ValueError("MACD requires 0 < fast < slow and signal >= 1")
    line = ema(close, fast) - ema(close, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": signal_line, "macd_hist": line - signal_line})


def true_range(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing seeded with the arithmetic mean of the first full window.

    This differs from an EMA initialized from the first observation. Seeding is
    important for reproducible RSI, ATR, +DI/-DI and ADX values.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)
    finite_positions = np.flatnonzero(np.isfinite(values))
    if len(finite_positions) < period:
        return pd.Series(output, index=series.index, name=series.name)
    # Require a contiguous full seed window; restart only after the first run of `period` values.
    seed_end = None
    for start in range(0, len(values) - period + 1):
        window = values[start:start + period]
        if np.isfinite(window).all():
            seed_end = start + period - 1
            output[seed_end] = float(window.mean())
            break
    if seed_end is None:
        return pd.Series(output, index=series.index, name=series.name)
    previous = output[seed_end]
    for index in range(seed_end + 1, len(values)):
        current = values[index]
        if not np.isfinite(current):
            previous = np.nan
            continue
        if not np.isfinite(previous):
            # Do not manufacture a smoothed value after a data gap; require a new seed window.
            window = values[index - period + 1:index + 1] if index >= period - 1 else np.array([])
            if len(window) == period and np.isfinite(window).all():
                previous = float(window.mean())
                output[index] = previous
            continue
        previous = previous + (current - previous) / period
        output[index] = previous
    return pd.Series(output, index=series.index, name=series.name)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    if period < 1:
        raise ValueError("period must be >= 1")
    return wilder_smooth(true_range(frame), period)


def adx(frame: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    if period < 1:
        raise ValueError("period must be >= 1")
    up_move = frame["high"].diff()
    down_move = -frame["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
    tr_smoothed = wilder_smooth(true_range(frame), period)
    plus_di = 100 * wilder_smooth(plus_dm, period) / tr_smoothed.replace(0, np.nan)
    minus_di = 100 * wilder_smooth(minus_dm, period) / tr_smoothed.replace(0, np.nan)
    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denominator
    return pd.DataFrame(
        {"plus_di": plus_di, "minus_di": minus_di, "adx": wilder_smooth(dx, period)}
    )


def bollinger(close: pd.Series, period: int = 20, deviations: float = 2.0) -> pd.DataFrame:
    middle = sma(close, period)
    standard_deviation = close.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + deviations * standard_deviation
    lower = middle - deviations * standard_deviation
    return pd.DataFrame({"bb_mid": middle, "bb_upper": upper, "bb_lower": lower})


def donchian(frame: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Previous completed bars only; current bar is excluded from its own trigger level."""
    if period < 1:
        raise ValueError("period must be >= 1")
    upper = frame["high"].shift(1).rolling(period, min_periods=period).max()
    lower = frame["low"].shift(1).rolling(period, min_periods=period).min()
    return pd.DataFrame({f"donchian_upper_{period}": upper, f"donchian_lower_{period}": lower})


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    average = volume.shift(1).rolling(period, min_periods=period).mean()
    return volume / average.replace(0, np.nan)


def obv(frame: pd.DataFrame) -> pd.Series:
    direction = np.sign(frame["close"].diff()).fillna(0)
    return (direction * frame["volume"]).cumsum()


def vwap(frame: pd.DataFrame, reset_by_day: bool = False) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    pv = typical * frame["volume"]
    if reset_by_day:
        index = pd.to_datetime(frame.index)
        group = pd.Series(index.date, index=frame.index)
        numerator = pv.groupby(group).cumsum()
        denominator = frame["volume"].groupby(group).cumsum().replace(0, np.nan)
    else:
        numerator = pv.cumsum()
        denominator = frame["volume"].cumsum().replace(0, np.nan)
    return numerator / denominator


def mfi(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    raw_flow = typical * frame["volume"]
    direction = typical.diff()
    positive = raw_flow.where(direction > 0, 0.0).rolling(period, min_periods=period).sum()
    negative = raw_flow.where(direction < 0, 0.0).rolling(period, min_periods=period).sum()
    ratio = positive / negative.replace(0, np.nan)
    result = 100 - (100 / (1 + ratio))
    result = result.mask((negative == 0) & (positive > 0), 100.0)
    result = result.mask((negative == 0) & (positive == 0), 50.0)
    return result


def cmf(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    spread = (frame["high"] - frame["low"]).replace(0, np.nan)
    multiplier = ((frame["close"] - frame["low"]) - (frame["high"] - frame["close"])) / spread
    flow_volume = multiplier.fillna(0) * frame["volume"]
    return flow_volume.rolling(period, min_periods=period).sum() / frame["volume"].rolling(
        period, min_periods=period
    ).sum().replace(0, np.nan)


def cci(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    average = typical.rolling(period, min_periods=period).mean()
    mean_deviation = typical.rolling(period, min_periods=period).apply(
        lambda values: np.mean(np.abs(values - np.mean(values))), raw=True
    )
    return (typical - average) / (0.015 * mean_deviation.replace(0, np.nan))


def stochastic_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    rsi_values = rsi(close, rsi_period)
    lowest = rsi_values.rolling(stoch_period, min_periods=stoch_period).min()
    highest = rsi_values.rolling(stoch_period, min_periods=stoch_period).max()
    return 100 * (rsi_values - lowest) / (highest - lowest).replace(0, np.nan)


def compute_indicators(frame: pd.DataFrame, *, strategy_config=None) -> pd.DataFrame:
    data = validate_ohlcv(frame)
    result = data.copy()
    for period in (20, 50, 100, 200):
        result[f"sma_{period}"] = sma(data["close"], period)
    for period in (9, 20, 50, 100, 200):
        result[f"ema_{period}"] = ema(data["close"], period)
    result["rsi_14"] = rsi(data["close"], strategy_config.rsi_period if strategy_config else 14)
    result = result.join(macd(data["close"]))
    result["atr_14"] = atr(data, strategy_config.atr_period if strategy_config else 14)
    result = result.join(adx(data, strategy_config.adx_period if strategy_config else 14))
    result = result.join(bollinger(data["close"], 20, 2.0))
    for period in dict.fromkeys((strategy_config.donchian_exit_period, strategy_config.donchian_entry_period) if strategy_config else (10, 20)):
        channel = donchian(data, period)
        for column in channel:
            result[column] = channel[column]
    result = result.join(donchian(data, 55))
    result["rvol_20"] = relative_volume(data["volume"], strategy_config.rvol_period if strategy_config else 20)
    if strategy_config:
        result[f"sma_{strategy_config.sma_fast_period}"] = sma(data["close"], strategy_config.sma_fast_period)
        result[f"sma_{strategy_config.sma_slow_period}"] = sma(data["close"], strategy_config.sma_slow_period)
        result[f"rsi_{strategy_config.rsi_period}"] = result["rsi_14"]
        result[f"atr_{strategy_config.atr_period}"] = result["atr_14"]
        result[f"rvol_{strategy_config.rvol_period}"] = result["rvol_20"]
    result["obv"] = obv(data)
    # Session VWAP requires intraday bars. With one OHLCV candle per day,
    # intraday price/volume distribution is unknowable and the result would
    # collapse to that candle's typical price, which is not a valid session VWAP.
    if len(data.index) > 1:
        deltas = data.index.to_series().diff().dropna()
        intraday = not deltas.empty and deltas.median() < pd.Timedelta(hours=20)
    else:
        intraday = False
    result["vwap_session"] = vwap(data, reset_by_day=True) if intraday else np.nan
    result["mfi_14"] = mfi(data, 14)
    result["cmf_20"] = cmf(data, 20)
    result["cci_20"] = cci(data, 20)
    result["stoch_rsi_14"] = stochastic_rsi(data["close"])
    return result
