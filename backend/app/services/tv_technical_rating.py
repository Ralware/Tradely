"""TradingView Technical Rating v3, ported from the published Pine library.

Authority
---------
``TradingView/TechnicalRating`` v3, published 2024-11-29, Pine Script v6:
https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/
Dependency: ``TradingView/ta/9``, published 2024-11-26.

The Pine sources are preserved verbatim in ``docs/reference/tradingview``.
The formulas, historical offsets, comparison operators, smoothing and
aggregation below are transcribed from those files.  The public Pine library
only returns the three aggregate ratings, so the 26 constituent values and
ratings are computed with the same expressions the library uses internally.

The engine is the single source of truth for the API.  It never rounds an
intermediate calculation; display precision is a presentation concern.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.services import pine_ta as pine

Action = Literal["Buy", "Sell", "Neutral"]
Assessment = Literal["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"]

SOURCE_NAME = "TradingView TechnicalRating"
SOURCE_VERSION = "v3 (2024-11-29)"
SOURCE_URL = "https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/"
DEPENDENCY = "TradingView/ta/9 (2024-11-26)"
STRONG_BOUND = 0.5
WEAK_BOUND = 0.1

MOVING_AVERAGE_KEYS = (
    "ema_10",
    "sma_10",
    "ema_20",
    "sma_20",
    "ema_30",
    "sma_30",
    "ema_50",
    "sma_50",
    "ema_100",
    "sma_100",
    "ema_200",
    "sma_200",
    "ichimoku_base",
    "vwma_20",
    "hma_9",
)

OSCILLATOR_KEYS = (
    "rsi_14",
    "stoch_k",
    "cci_20",
    "adx_14",
    "ao",
    "mom_10",
    "macd_line",
    "stoch_rsi_k",
    "williams_r_14",
    "bbp",
    "uo",
)

DISPLAY_NAMES = {
    "ema_10": "Exponential Moving Average (10)",
    "sma_10": "Simple Moving Average (10)",
    "ema_20": "Exponential Moving Average (20)",
    "sma_20": "Simple Moving Average (20)",
    "ema_30": "Exponential Moving Average (30)",
    "sma_30": "Simple Moving Average (30)",
    "ema_50": "Exponential Moving Average (50)",
    "sma_50": "Simple Moving Average (50)",
    "ema_100": "Exponential Moving Average (100)",
    "sma_100": "Simple Moving Average (100)",
    "ema_200": "Exponential Moving Average (200)",
    "sma_200": "Simple Moving Average (200)",
    "ichimoku_base": "Ichimoku Base Line (26)",
    "vwma_20": "Volume Weighted Moving Average (20)",
    "hma_9": "Hull Moving Average (9)",
    "rsi_14": "Relative Strength Index (14)",
    "stoch_k": "Stochastic %K (14, 3, 3)",
    "cci_20": "Commodity Channel Index (20)",
    "adx_14": "Average Directional Index (14)",
    "ao": "Awesome Oscillator",
    "mom_10": "Momentum (10)",
    "macd_line": "MACD Level (12, 26)",
    "stoch_rsi_k": "Stochastic RSI (14, 14, 3, 3)",
    "williams_r_14": "Williams %R (14)",
    "bbp": "Bull Bear Power",
    "uo": "Ultimate Oscillator (7, 14, 28)",
}

PRICE_KEYS = {
    "ema_10",
    "sma_10",
    "ema_20",
    "sma_20",
    "ema_30",
    "sma_30",
    "ema_50",
    "sma_50",
    "ema_100",
    "sma_100",
    "ema_200",
    "sma_200",
    "ichimoku_base",
    "vwma_20",
    "hma_9",
}

DETAILS: dict[str, tuple[str, ...]] = {
    "ichimoku_base": ("ichimoku_conversion", "ichimoku_span1", "ichimoku_span2"),
    "rsi_14": ("rsi_14_previous",),
    "stoch_k": ("stoch_d", "stoch_k_previous", "stoch_d_previous"),
    "cci_20": ("cci_20_previous", "cci_20_hlc3"),
    "adx_14": ("plus_di_14", "minus_di_14", "adx_14_previous"),
    "ao": ("ao_previous", "ao_previous_2"),
    "mom_10": ("mom_10_previous",),
    "macd_line": ("macd_signal", "macd_hist"),
    "stoch_rsi_k": ("stoch_rsi_d", "ema_50"),
    "williams_r_14": ("williams_r_14_previous",),
    "bbp": ("bull_power_13", "bear_power_13", "bear_power_13_previous", "bull_power_13_previous"),
    "uo": (),
}


def ohlcv_fingerprint(frame: pd.DataFrame) -> str:
    """Deterministic SHA-256 fingerprint of the OHLCV series."""
    if frame.empty:
        return "empty"
    tail = frame[["open", "high", "low", "close", "volume"]].tail(10)
    buffer = f"{len(frame)}:{frame.index[0]}:{frame.index[-1]}:"
    for row in tail.itertuples(index=True):
        buffer += f"{row[0]},{row[1]:.8f},{row[2]:.8f},{row[3]:.8f},{row[4]:.8f},{row[5]:.8f};"
    return hashlib.sha256(buffer.encode("utf-8")).hexdigest()[:16]


def rating_status(value: float | None) -> Assessment | str:
    """Pine ``ratingStatus`` with the v3 default bounds."""
    if value is None or not np.isfinite(value):
        return "-"
    if value < -STRONG_BOUND:
        return "Strong Sell"
    if value < -WEAK_BOUND:
        return "Sell"
    if value > STRONG_BOUND:
        return "Strong Buy"
    if value > WEAK_BOUND:
        return "Buy"
    return "Neutral"


def _action(rating: int | None) -> Action:
    if rating == 1:
        return "Buy"
    if rating == -1:
        return "Sell"
    return "Neutral"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _rating_ma(ma: pd.Series, source: pd.Series) -> pd.Series:
    """``calcRatingMA``: ``math.sign(src - ma)``."""
    return pine.sign(source - ma)


def _rating(src: pd.Series, bullish: pd.Series, bearish: pd.Series) -> pd.Series:
    """``calcRating``: ``na`` when ``src`` is na, else +1/-1/0."""
    values = np.where(
        src.isna().to_numpy(),
        np.nan,
        np.where(bullish.fillna(False).to_numpy(), 1.0, np.where(bearish.fillna(False).to_numpy(), -1.0, 0.0)),
    )
    return pd.Series(values, index=src.index)


def _average_ratings(frame: pd.DataFrame, keys: tuple[str, ...]) -> pd.Series:
    """Pine ``array.avg``: mean of the available ratings, ignoring ``na``."""
    if not keys:
        return pd.Series(np.nan, index=frame.index)
    values = frame[list(keys)].to_numpy(dtype=float)
    finite = np.isfinite(values)
    counts = finite.sum(axis=1)
    totals = np.where(finite, values, 0.0).sum(axis=1)
    output = np.full(len(frame), np.nan, dtype=float)
    valid = counts > 0
    output[valid] = totals[valid] / counts[valid]
    return pd.Series(output, index=frame.index)


@dataclass
class TechnicalRatingEvaluation:
    """All constituent series and the latest snapshot."""

    frame: pd.DataFrame
    close: float
    history: pd.DataFrame = field(repr=False)

    def snapshot(self) -> dict[str, Any]:
        latest = self.history.iloc[-1]
        rows: list[dict[str, Any]] = []
        for group, keys in (
            ("oscillators", OSCILLATOR_KEYS),
            ("moving_averages", MOVING_AVERAGE_KEYS),
        ):
            for key in keys:
                value = _number(latest.get(key))
                rating_value = _number(latest.get(f"rating_{key}"))
                rating = int(rating_value) if rating_value is not None else None
                detail_values = {
                    name: _number(latest.get(name))
                    for name in DETAILS.get(key, ())
                }
                rows.append(
                    {
                        "key": key,
                        "field": key,
                        "name": DISPLAY_NAMES[key],
                        "group": group,
                        "value": value,
                        "rating": rating,
                        "action": _action(rating),
                        "precision": 4 if key in PRICE_KEYS else 2,
                        "details": detail_values,
                    }
                )

        oscillators = [row for row in rows if row["group"] == "oscillators"]
        moving_averages = [row for row in rows if row["group"] == "moving_averages"]

        def summary(group_rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
            counts = {"sell": 0, "neutral": 0, "buy": 0}
            for row in group_rows:
                if row["rating"] == 1:
                    counts["buy"] += 1
                elif row["rating"] == -1:
                    counts["sell"] += 1
                elif row["rating"] == 0:
                    counts["neutral"] += 1
            rating_keys = tuple(f"rating_{k}" for k in keys)
            score = _number(_average_ratings(self.history, rating_keys).iloc[-1])
            return {
                "action": rating_status(score),
                "score": score,
                **counts,
                "available": sum(counts.values()),
                "total": len(keys),
            }

        moving_average_summary = summary(moving_averages, MOVING_AVERAGE_KEYS)
        oscillator_summary = summary(oscillators, OSCILLATOR_KEYS)
        total_series = _total_rating(self.history)
        total_score = _number(total_series.iloc[-1])
        overall_counts = {
            key: moving_average_summary[key] + oscillator_summary[key]
            for key in ("sell", "neutral", "buy")
        }
        overall = {
            "action": rating_status(total_score),
            "score": total_score,
            **overall_counts,
            "available": moving_average_summary["available"] + oscillator_summary["available"],
            "total": 26,
        }

        return {
            "close": self.close,
            "fingerprint": ohlcv_fingerprint(self.frame),
            "oscillators": oscillators,
            "moving_averages": moving_averages,
            "summary": {
                "oscillators": oscillator_summary,
                "moving_averages": moving_average_summary,
                "overall": overall,
            },
            "source_name": SOURCE_NAME,
            "source_version": SOURCE_VERSION,
            "source_url": SOURCE_URL,
            "dependency": DEPENDENCY,
            "method": (
                "TradingView TechnicalRating v3 (2024-11-29) with TradingView/ta/9 "
                "(2024-11-26). Pine-compatible calculations; not investment advice."
            ),
        }


def _total_rating(history: pd.DataFrame) -> pd.Series:
    """v3 ``calcRatingAll`` total: mean of available group ratings."""
    ma = history["rating_group_moving_averages"].to_numpy(dtype=float)
    other = history["rating_group_oscillators"].to_numpy(dtype=float)
    output = np.full(len(history), np.nan, dtype=float)
    both = np.isfinite(ma) & np.isfinite(other)
    only_ma = np.isfinite(ma) & ~np.isfinite(other)
    only_other = np.isfinite(other) & ~np.isfinite(ma)
    output[both] = (ma[both] + other[both]) / 2.0
    output[only_ma] = ma[only_ma]
    output[only_other] = other[only_other]
    return pd.Series(output, index=history.index)


def evaluate(frame: pd.DataFrame) -> TechnicalRatingEvaluation:
    """Compute all 26 constituents and the three v3 aggregates.

    ``frame`` must contain ``open, high, low, close, volume`` with a sorted
    index.  The caller is responsible for supplying confirmed or provisional
    candles; this engine does not decide bar state.
    """
    missing = {"high", "low", "close", "volume"} - set(frame.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(sorted(missing))}")
    data = frame.copy()
    for column in ("high", "low", "close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if data.empty:
        raise ValueError("No valid OHLCV rows")

    high = data["high"]
    low = data["low"]
    close = data["close"]
    volume = data["volume"]

    history = pd.DataFrame(index=data.index)
    history["close"] = close

    for length in (10, 20, 30, 50, 100, 200):
        history[f"sma_{length}"] = pine.sma(close, length)
        history[f"ema_{length}"] = pine.ema(close, length)
    history["hma_9"] = pine.hma(close, 9)
    history["vwma_20"] = pine.vwma(close, volume, 20)

    tenkan, kijun, span_one, span_two, _ = pine.ichimoku(high, low, close)
    history["ichimoku_conversion"] = tenkan
    history["ichimoku_base"] = kijun
    history["ichimoku_span1"] = span_one
    history["ichimoku_span2"] = span_two

    history["rsi_14"] = pine.rsi(close, 14)
    history["rsi_14_previous"] = history["rsi_14"].shift(1)
    stoch_k, stoch_d = pine.stoch_full(high, low, close, 14, 3, 3)
    history["stoch_k"] = stoch_k
    history["stoch_d"] = stoch_d
    history["stoch_k_previous"] = stoch_k.shift(1)
    history["stoch_d_previous"] = stoch_d.shift(1)
    history["cci_20"] = pine.cci(close, 20)
    history["cci_20_previous"] = history["cci_20"].shift(1)
    history["cci_20_hlc3"] = pine.cci((high + low + close) / 3.0, 20)
    plus_di, minus_di, adx = pine.dmi(high, low, close, 14, 14)
    history["plus_di_14"] = plus_di
    history["minus_di_14"] = minus_di
    history["adx_14"] = adx
    history["adx_14_previous"] = adx.shift(1)
    history["ao"] = pine.awesome_oscillator(high, low)
    history["ao_previous"] = history["ao"].shift(1)
    history["ao_previous_2"] = history["ao"].shift(2)
    history["mom_10"] = pine.momentum(close, 10)
    history["mom_10_previous"] = history["mom_10"].shift(1)
    macd_line, macd_signal, macd_hist = pine.macd(close, 12, 26, 9)
    history["macd_line"] = macd_line
    history["macd_signal"] = macd_signal
    history["macd_hist"] = macd_hist
    stoch_rsi_k, stoch_rsi_d = pine.stoch_rsi(close, 14, 14, 3, 3)
    history["stoch_rsi_k"] = stoch_rsi_k
    history["stoch_rsi_d"] = stoch_rsi_d
    history["williams_r_14"] = pine.williams_r(high, low, close, 14)
    history["williams_r_14_previous"] = history["williams_r_14"].shift(1)
    history["ema_13"] = pine.ema(close, 13)
    history["bull_power_13"] = high - history["ema_13"]
    history["bear_power_13"] = low - history["ema_13"]
    history["bull_power_13_previous"] = history["bull_power_13"].shift(1)
    history["bear_power_13_previous"] = history["bear_power_13"].shift(1)
    history["bbp"] = history["bull_power_13"] + history["bear_power_13"]
    history["uo"] = pine.ultimate_oscillator(high, low, close, 7, 14, 28)

    # Moving-average ratings (v3 order: SMA, EMA, HMA, VWMA, Ichimoku).
    for length in (10, 20, 30, 50, 100, 200):
        history[f"rating_sma_{length}"] = _rating_ma(history[f"sma_{length}"], close)
        history[f"rating_ema_{length}"] = _rating_ma(history[f"ema_{length}"], close)
    history["rating_hma_9"] = _rating_ma(history["hma_9"], close)
    history["rating_vwma_20"] = _rating_ma(history["vwma_20"], close)

    lead1 = history["ichimoku_span1"]
    lead2 = history["ichimoku_span2"]
    base = history["ichimoku_base"]
    conversion = history["ichimoku_conversion"]
    history["rating_ichimoku_base"] = _rating(
        lead2,
        (lead1.shift(26) > lead2.shift(26))
        & (base > lead1.shift(26))
        & (conversion > base)
        & (close > conversion),
        (lead1.shift(26) < lead2.shift(26))
        & (base < lead1.shift(26))
        & (conversion < base)
        & (close < conversion),
    )

    # Oscillator ratings, transcribed from calcRatingAll().
    rsi_values = history["rsi_14"]
    history["rating_rsi_14"] = _rating(
        history["rsi_14_previous"],
        (rsi_values < 30.0) & (history["rsi_14_previous"] < rsi_values),
        (rsi_values > 70.0) & (history["rsi_14_previous"] > rsi_values),
    )

    k = history["stoch_k"]
    d = history["stoch_d"]
    history["rating_stoch_k"] = _rating(
        history["stoch_d_previous"],
        (k < 20.0) & (d < 20.0) & (k > d),
        (k > 80.0) & (d > 80.0) & (k < d),
    )

    cci_values = history["cci_20"]
    history["rating_cci_20"] = _rating(
        history["cci_20_previous"],
        (cci_values < -100.0) & (cci_values > history["cci_20_previous"]),
        (cci_values > 100.0) & (cci_values < history["cci_20_previous"]),
    )

    history["rating_adx_14"] = _rating(
        history["adx_14"],
        (history["adx_14"] > 20.0)
        & (history["adx_14"] > history["adx_14_previous"])
        & (plus_di > minus_di),
        (history["adx_14"] > 20.0)
        & (history["adx_14"] > history["adx_14_previous"])
        & (plus_di < minus_di),
    )

    ao = history["ao"]
    history["rating_ao"] = _rating(
        history["ao_previous"],
        pine.crossover(ao, 0.0)
        | (
            (ao > 0.0)
            & (history["ao_previous"] > 0.0)
            & (ao > history["ao_previous"])
            & (history["ao_previous_2"] > history["ao_previous"])
        ),
        pine.crossunder(ao, 0.0)
        | (
            (ao < 0.0)
            & (history["ao_previous"] < 0.0)
            & (ao < history["ao_previous"])
            & (history["ao_previous_2"] < history["ao_previous"])
        ),
    )

    history["rating_mom_10"] = _rating(
        history["mom_10_previous"],
        history["mom_10"] > history["mom_10_previous"],
        history["mom_10"] < history["mom_10_previous"],
    )

    history["rating_macd_line"] = _rating(
        macd_signal,
        macd_line > macd_signal,
        macd_line < macd_signal,
    )

    price_average = history["ema_50"]
    down_trend = close < price_average
    up_trend = close > price_average
    history["rating_stoch_rsi_k"] = _rating(
        price_average,
        down_trend & (stoch_rsi_k < 20.0) & (stoch_rsi_d < 20.0) & (stoch_rsi_k > stoch_rsi_d),
        up_trend & (stoch_rsi_k > 80.0) & (stoch_rsi_d > 80.0) & (stoch_rsi_k < stoch_rsi_d),
    )

    wr = history["williams_r_14"]
    history["rating_williams_r_14"] = _rating(
        history["williams_r_14_previous"],
        (wr < -80.0) & (wr > history["williams_r_14_previous"]),
        (wr > -20.0) & (wr < history["williams_r_14_previous"]),
    )

    history["rating_bbp"] = _rating(
        price_average,
        up_trend
        & (history["bear_power_13"] < 0.0)
        & (history["bear_power_13"] > history["bear_power_13_previous"]),
        down_trend
        & (history["bull_power_13"] > 0.0)
        & (history["bull_power_13"] < history["bull_power_13_previous"]),
    )

    history["rating_uo"] = _rating(
        history["uo"],
        history["uo"] > 70.0,
        history["uo"] < 30.0,
    )

    history["rating_group_moving_averages"] = _average_ratings(history, tuple(f"rating_{key}" for key in MOVING_AVERAGE_KEYS))
    history["rating_group_oscillators"] = _average_ratings(history, tuple(f"rating_{key}" for key in OSCILLATOR_KEYS))
    history["rating_total"] = _total_rating(history)

    return TechnicalRatingEvaluation(frame=data, close=float(close.iloc[-1]), history=history)


def build_technical_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Return the latest v3 snapshot consumed by the technicals API."""
    return evaluate(frame).snapshot()
