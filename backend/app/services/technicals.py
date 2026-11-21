"""Conventional technical-summary classification.

This module does not compute new indicators and does not reproduce the Tradely
trend-breakout strategy. It only labels the indicator values that
``app.services.indicators.compute_indicators`` already produced, using widely
published threshold conventions, and aggregates the labels into the three
counts required by the UI.

The classification is deliberately explicit so every number in the interface
can be traced back to a documented rule.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

Action = Literal["Buy", "Sell", "Neutral"]

# Thresholds are conventional oscillator levels, not Tradely strategy rules.
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
STOCH_OVERBOUGHT = 80.0
STOCH_OVERSOLD = 20.0
CCI_OVERBOUGHT = 100.0
CCI_OVERSOLD = -100.0
MFI_OVERBOUGHT = 80.0
MFI_OVERSOLD = 20.0


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _oscillator_action(field: str, value: float | None, close: float | None) -> Action:
    """Return the conventional action for one oscillator value."""
    if field == "adx":
        # ADX measures trend strength, not direction, so it has no buy/sell side.
        return "Neutral"
    if value is None:
        return "Neutral"
    if field == "rsi_14":
        if value > RSI_OVERBOUGHT:
            return "Sell"
        if value < RSI_OVERSOLD:
            return "Buy"
        return "Neutral"
    if field == "stoch_rsi_14":
        if value > STOCH_OVERBOUGHT:
            return "Sell"
        if value < STOCH_OVERSOLD:
            return "Buy"
        return "Neutral"
    if field == "cci_20":
        if value > CCI_OVERBOUGHT:
            return "Sell"
        if value < CCI_OVERSOLD:
            return "Buy"
        return "Neutral"
    if field == "mfi_14":
        if value > MFI_OVERBOUGHT:
            return "Sell"
        if value < MFI_OVERSOLD:
            return "Buy"
        return "Neutral"
    if field == "cmf_20":
        if value > 0:
            return "Buy"
        if value < 0:
            return "Sell"
        return "Neutral"
    return "Neutral"


def _macd_action(macd_value: float | None, signal_value: float | None) -> Action:
    if macd_value is None or signal_value is None:
        return "Neutral"
    if macd_value > signal_value:
        return "Buy"
    if macd_value < signal_value:
        return "Sell"
    return "Neutral"


def _band_action(
    close: float | None,
    upper: float | None,
    lower: float | None,
) -> Action:
    """Bollinger mean-reversion reading: outside the bands is stretched."""
    if close is None or upper is None or lower is None:
        return "Neutral"
    if close > upper:
        return "Sell"
    if close < lower:
        return "Buy"
    return "Neutral"


def _ma_action(close: float | None, average: float | None) -> Action:
    if close is None or average is None:
        return "Neutral"
    if close > average:
        return "Buy"
    if close < average:
        return "Sell"
    return "Neutral"


def _row(name: str, field: str, value: float | None, action: Action) -> dict[str, Any]:
    return {"name": name, "field": field, "value": value, "action": action}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result = {"sell": 0, "neutral": 0, "buy": 0}
    for row in rows:
        action = str(row["action"]).lower()
        if action in result:
            result[action] += 1
    return result


def _assessment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _counts(rows)
    total = counts["sell"] + counts["neutral"] + counts["buy"]
    if total == 0:
        return {"action": "Neutral", "score": 0.0, **counts}
    score = (counts["buy"] - counts["sell"]) / total
    if counts["buy"] > counts["sell"] and counts["buy"] > counts["neutral"]:
        action = "Strong Buy" if counts["buy"] >= 2 * max(counts["sell"], 1) else "Buy"
    elif counts["sell"] > counts["buy"] and counts["sell"] > counts["neutral"]:
        action = "Strong Sell" if counts["sell"] >= 2 * max(counts["buy"], 1) else "Sell"
    else:
        action = "Neutral"
    return {"action": action, "score": round(score, 6), **counts}


def build_technical_summary(latest: pd.Series, close: float) -> dict[str, Any]:
    """Classify the latest indicator row into oscillator and MA tables.

    ``latest`` is the final row of ``compute_indicators`` output. Missing
    values are returned as ``null`` and classified as Neutral; no value is
    estimated or back-filled.
    """

    def value(field: str) -> float | None:
        return _number(latest.get(field))

    rsi = value("rsi_14")
    stoch_rsi = value("stoch_rsi_14")
    cci = value("cci_20")
    adx = value("adx")
    macd_value = value("macd")
    macd_signal = value("macd_signal")
    mfi = value("mfi_14")
    cmf = value("cmf_20")
    bb_upper = value("bb_upper")
    bb_lower = value("bb_lower")
    vwap = value("vwap_session")

    oscillators = [
        _row("Relative Strength Index (14)", "rsi_14", rsi, _oscillator_action("rsi_14", rsi, close)),
        _row(
            "Stochastic RSI (14)",
            "stoch_rsi_14",
            stoch_rsi,
            _oscillator_action("stoch_rsi_14", stoch_rsi, close),
        ),
        _row("Commodity Channel Index (20)", "cci_20", cci, _oscillator_action("cci_20", cci, close)),
        _row("Average Directional Index (14)", "adx", adx, "Neutral"),
        _row("MACD Level (12, 26)", "macd", macd_value, _macd_action(macd_value, macd_signal)),
        _row("Money Flow Index (14)", "mfi_14", mfi, _oscillator_action("mfi_14", mfi, close)),
        _row("Chaikin Money Flow (20)", "cmf_20", cmf, _oscillator_action("cmf_20", cmf, close)),
        _row(
            "Bollinger Bands (20, 2)",
            "bollinger",
            close,
            _band_action(close, bb_upper, bb_lower),
        ),
    ]
    if vwap is not None:
        oscillators.append(_row("VWAP (Session)", "vwap_session", vwap, _ma_action(close, vwap)))

    moving_averages = [
        _row(
            "Exponential Moving Average (9)",
            "ema_9",
            value("ema_9"),
            _ma_action(close, value("ema_9")),
        ),
        _row(
            "Simple Moving Average (20)",
            "sma_20",
            value("sma_20"),
            _ma_action(close, value("sma_20")),
        ),
        _row(
            "Exponential Moving Average (20)",
            "ema_20",
            value("ema_20"),
            _ma_action(close, value("ema_20")),
        ),
        _row(
            "Simple Moving Average (50)",
            "sma_50",
            value("sma_50"),
            _ma_action(close, value("sma_50")),
        ),
        _row(
            "Exponential Moving Average (50)",
            "ema_50",
            value("ema_50"),
            _ma_action(close, value("ema_50")),
        ),
        _row(
            "Simple Moving Average (200)",
            "sma_200",
            value("sma_200"),
            _ma_action(close, value("sma_200")),
        ),
        _row(
            "Exponential Moving Average (200)",
            "ema_200",
            value("ema_200"),
            _ma_action(close, value("ema_200")),
        ),
    ]

    return {
        "close": close,
        "oscillators": oscillators,
        "moving_averages": moving_averages,
        "summary": {
            "oscillators": _assessment(oscillators),
            "moving_averages": _assessment(moving_averages),
            "overall": _assessment(oscillators + moving_averages),
        },
        "method": (
            "Conventional threshold classification of backend indicator values. "
            "Not the Tradely trend-breakout strategy and not investment advice."
        ),
    }
