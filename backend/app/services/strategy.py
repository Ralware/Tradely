from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd

from app.core.models import DirectionMode, PositionDirection, SignalCondition, StrategySignal
from app.services.indicators import compute_indicators

STRATEGY_VERSION = "trend-donchian-v1.2.0"


def _evaluate_trend_breakout_long_only(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    source: str | None = None,
    min_adx: float = 20.0,
    min_rvol: float = 1.0,
) -> StrategySignal:
    """Long-only completed-bar candidate; close breakout over the prior 20 bars.

    The latest input bar must be final. Execution is not modelled here; an actual
    backtest should execute no earlier than the next available bar.
    """
    if len(frame) < 220:
        return StrategySignal(
            symbol=symbol,
            market=market,  # type: ignore[arg-type]
            strategy="Trend + Donchian 20 Breakout",
            strategy_version=STRATEGY_VERSION,
            state="INSUFFICIENT_DATA",
            conditions=[],
            explanation=f"At least 220 completed bars are required; received {len(frame)}.",
            data_source=source,
        )

    data = compute_indicators(frame)
    row = data.iloc[-1]
    required = ["sma_50", "sma_200", "rsi_14", "adx", "atr_14", "donchian_upper_20", "donchian_lower_10", "rvol_20"]
    if any(pd.isna(row[name]) for name in required) or pd.isna(data["sma_200"].iloc[-21]):
        return StrategySignal(
            symbol=symbol,
            market=market,  # type: ignore[arg-type]
            strategy="Trend + Donchian 20 Breakout",
            strategy_version=STRATEGY_VERSION,
            state="INSUFFICIENT_DATA",
            conditions=[],
            explanation="Indicator warm-up is incomplete; no signal was generated.",
            data_source=source,
        )

    close = float(row["close"])
    upper = float(row["donchian_upper_20"])
    sma_200 = float(row["sma_200"])
    sma_200_prior = float(data["sma_200"].iloc[-21])
    sma_50 = float(row["sma_50"])
    rsi_value = float(row["rsi_14"])
    adx_value = float(row["adx"])
    rvol_value = float(row["rvol_20"])
    atr_value = float(row["atr_14"])
    exit_level = float(row["donchian_lower_10"])

    entry_checks = [
        SignalCondition(
            name="Close above prior 20-bar high",
            passed=close > upper,
            observed=close,
            threshold=upper,
            explanation="The current completed close must exceed the previous 20 completed bars' high.",
        ),
        SignalCondition(
            name="Close above SMA 200",
            passed=close > sma_200,
            observed=close,
            threshold=sma_200,
            explanation="Long-term price regime filter.",
        ),
        SignalCondition(
            name="SMA 50 above SMA 200",
            passed=sma_50 > sma_200,
            observed=sma_50,
            threshold=sma_200,
            explanation="Medium/long-term trend alignment.",
        ),
        SignalCondition(
            name="SMA 200 rising over 20 bars",
            passed=sma_200 > sma_200_prior,
            observed=sma_200,
            threshold=sma_200_prior,
            explanation="Avoids treating a flat or falling long-term average as an uptrend.",
        ),
        SignalCondition(
            name="RSI 14 above 50",
            passed=rsi_value > 50,
            observed=rsi_value,
            threshold=50,
            explanation="Momentum confirmation; not an independent entry trigger.",
        ),
        SignalCondition(
            name=f"ADX 14 at least {min_adx:g}",
            passed=adx_value >= min_adx,
            observed=adx_value,
            threshold=min_adx,
            explanation="Trend-strength filter; ADX does not indicate direction.",
        ),
        SignalCondition(
            name=f"Relative volume 20 at least {min_rvol:g}",
            passed=rvol_value >= min_rvol,
            observed=rvol_value,
            threshold=min_rvol,
            explanation="Current volume divided by the mean volume of the prior 20 bars.",
        ),
    ]
    exit_check = SignalCondition(
        name="Close below prior 10-bar low (exit long)",
        passed=close < exit_level,
        observed=close,
        threshold=exit_level,
        explanation="SELL means exit an existing long position; this strategy does not initiate short positions.",
    )
    checks = entry_checks + [exit_check]
    passed = sum(check.passed for check in entry_checks)
    if exit_check.passed:
        state = "SELL"
    elif all(check.passed for check in entry_checks):
        state = "BUY"
    else:
        state = "WAIT"
    stop = close - 2.0 * atr_value
    timestamp = row.name.to_pydatetime() if hasattr(row.name, "to_pydatetime") else row.name
    if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    explanation = (
        "All seven pre-defined entry conditions passed on the latest completed candle. This is a research "
        "signal, not an order; any backtest/live execution must use the next executable price."
        if state == "BUY" else
        "The close broke the previous 10-bar low. SELL means exit an existing long position, not open a short."
        if state == "SELL" else
        f"{passed}/7 entry conditions passed. Wait for the complete rule set; no partial score is promoted to BUY."
    )
    return StrategySignal(
        symbol=symbol,
        market=market,  # type: ignore[arg-type]
        strategy="Trend + Donchian 20 Breakout",
        strategy_version=STRATEGY_VERSION,
        state=state,  # type: ignore[arg-type]
        as_of=timestamp,
        entry_reference=close if state == "BUY" else None,
        stop_reference=stop if state == "BUY" else None,
        risk_per_unit=2.0 * atr_value if state == "BUY" else None,
        conditions=checks,
        explanation=explanation,
        data_source=source,
    )


def evaluate_trend_breakout(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    source: str | None = None,
    min_adx: float = 20.0,
    min_rvol: float = 1.0,
    direction_mode: DirectionMode = "long_only",
    position_side: PositionDirection | None = None,
) -> StrategySignal:
    if direction_mode not in ("long_only", "short_only", "long_short"):
        raise ValueError("Invalid direction_mode")
    if (
        not frame.empty
        and "is_final" in frame.columns
        and (pd.isna(frame.iloc[-1]["is_final"]) or not bool(frame.iloc[-1]["is_final"]))
    ):
        return StrategySignal(
            symbol=symbol,
            market=market,  # type: ignore[arg-type]
            strategy="Trend + Donchian 20 Breakout",
            strategy_version=STRATEGY_VERSION,
            direction_mode=direction_mode,
            state="WAIT",
            conditions=[
                SignalCondition(
                    name="Latest candle is complete",
                    passed=False,
                    observed="incomplete",
                    threshold="complete",
                    explanation="Incomplete candles cannot trigger strategy entries or exits.",
                )
            ],
            explanation="The latest candle is incomplete; no signal was generated.",
            data_source=source,
        )

    long_signal = _evaluate_trend_breakout_long_only(
        frame,
        symbol=symbol,
        market=market,
        source=source,
        min_adx=min_adx,
        min_rvol=min_rvol,
    )
    if long_signal.state == "INSUFFICIENT_DATA":
        return long_signal.model_copy(update={"direction_mode": direction_mode})
    if direction_mode == "long_only" and position_side is None:
        direction = "LONG" if long_signal.state in {"BUY", "SELL"} else None
        return long_signal.model_copy(
            update={"direction_mode": direction_mode, "direction": direction}
        )

    data = compute_indicators(frame)
    row = data.iloc[-1]
    close = float(row["close"])
    short_entry_level = float(data["low"].iloc[-21:-1].min())
    short_exit_level = float(data["high"].iloc[-11:-1].max())
    sma_50 = float(row["sma_50"])
    sma_200 = float(row["sma_200"])
    sma_200_prior = float(data["sma_200"].iloc[-21])
    rsi_value = float(row["rsi_14"])
    adx_value = float(row["adx"])
    rvol_value = float(row["rvol_20"])
    atr_value = float(row["atr_14"])
    short_entry_checks = [
        SignalCondition(
            name="Close below prior 20-bar low",
            passed=close < short_entry_level,
            observed=close,
            threshold=short_entry_level,
            explanation="The current completed close must break the previous 20 completed bars' low.",
        ),
        SignalCondition(
            name="Close below SMA 200",
            passed=close < sma_200,
            observed=close,
            threshold=sma_200,
            explanation="Long-term price regime filter for short exposure.",
        ),
        SignalCondition(
            name="SMA 50 below SMA 200",
            passed=sma_50 < sma_200,
            observed=sma_50,
            threshold=sma_200,
            explanation="Medium/long-term bearish trend alignment.",
        ),
        SignalCondition(
            name="SMA 200 falling over 20 bars",
            passed=sma_200 < sma_200_prior,
            observed=sma_200,
            threshold=sma_200_prior,
            explanation="Avoids treating a flat or rising long-term average as a downtrend.",
        ),
        SignalCondition(
            name="RSI 14 below 50",
            passed=rsi_value < 50,
            observed=rsi_value,
            threshold=50,
            explanation="Downside momentum confirmation; not an independent entry trigger.",
        ),
        SignalCondition(
            name=f"ADX 14 at least {min_adx:g}",
            passed=adx_value >= min_adx,
            observed=adx_value,
            threshold=min_adx,
            explanation="Trend-strength filter; ADX does not indicate direction.",
        ),
        SignalCondition(
            name=f"Relative volume 20 at least {min_rvol:g}",
            passed=rvol_value >= min_rvol,
            observed=rvol_value,
            threshold=min_rvol,
            explanation="Current volume divided by the mean volume of the prior 20 bars.",
        ),
    ]
    short_exit_check = SignalCondition(
        name="Close above prior 10-bar high (cover short)",
        passed=close > short_exit_level,
        observed=close,
        threshold=short_exit_level,
        explanation="BUY TO COVER exits an existing short position; it does not open a long.",
    )
    short_entry_ready = all(check.passed for check in short_entry_checks)
    if position_side == "LONG":
        state = "SELL" if long_signal.state == "SELL" else "WAIT"
        checks = long_signal.conditions
    elif position_side == "SHORT":
        state = "BUY_TO_COVER" if short_exit_check.passed else "WAIT"
        checks = short_entry_checks + [short_exit_check]
    elif direction_mode == "short_only":
        state = "SELL_SHORT" if short_entry_ready else "WAIT"
        checks = short_entry_checks + [short_exit_check]
    else:
        if long_signal.state == "BUY":
            state = "BUY"
        elif short_entry_ready:
            state = "SELL_SHORT"
        else:
            state = "WAIT"
        checks = long_signal.conditions + short_entry_checks + [short_exit_check]

    direction: PositionDirection | None = (
        "LONG" if state in {"BUY", "SELL"} else
        "SHORT" if state in {"SELL_SHORT", "BUY_TO_COVER"} else
        position_side
    )
    entry_reference = close if state in {"BUY", "SELL_SHORT"} else None
    stop_reference = (
        close + 2.0 * atr_value if state == "SELL_SHORT"
        else close - 2.0 * atr_value if state == "BUY"
        else None
    )
    if state == "SELL_SHORT":
        explanation = (
            "All seven short-entry conditions passed on the latest completed candle. This is manual research "
            "exposure, not a borrow or an order; execution is not provided."
        )
    elif state == "SELL":
        explanation = "The close broke the prior 10-bar low. SELL exits an existing long; it never opens a short."
    elif state == "BUY_TO_COVER":
        explanation = "The close broke the prior 10-bar high. BUY TO COVER exits an existing short; it never opens a long."
    elif state == "BUY":
        explanation = long_signal.explanation
    elif position_side:
        explanation = f"No exit rule triggered for the existing {position_side} position."
    else:
        passed = max(
            sum(check.passed for check in long_signal.conditions[:7]),
            sum(check.passed for check in short_entry_checks),
        )
        explanation = f"{passed}/7 directional entry conditions passed; no partial score is promoted to an entry."

    return long_signal.model_copy(
        update={
            "direction_mode": direction_mode,
            "direction": direction,
            "state": state,
            "as_of": long_signal.as_of,
            "entry_reference": entry_reference,
            "stop_reference": stop_reference,
            "risk_per_unit": 2.0 * atr_value if state in {"BUY", "SELL_SHORT"} else None,
            "conditions": checks,
            "explanation": explanation,
            "data_source": source,
        }
    )


def position_size(
    *, capital: float, risk_fraction: float, entry: float, stop: float,
    lot_size: int = 1, max_position_fraction: float = 1.0,
    direction: PositionDirection = "LONG",
) -> dict[str, float | int | bool | str]:
    values = (capital, risk_fraction, entry, stop, max_position_fraction)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Inputs must be finite")
    if capital <= 0 or entry <= 0 or stop <= 0 or risk_fraction <= 0:
        raise ValueError("Capital, entry, stop and risk fraction must be positive")
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    if direction == "LONG" and stop >= entry:
        raise ValueError("For a long position, stop must be below entry")
    if direction == "SHORT" and stop <= entry:
        raise ValueError("For a short position, stop must be above entry")
    if lot_size < 1 or not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid lot size or maximum position fraction")
    risk_budget = capital * risk_fraction
    risk_per_unit = abs(entry - stop)
    risk_limited = int(risk_budget // risk_per_unit)
    capital_limited = int((capital * max_position_fraction) // entry)
    raw_qty = min(risk_limited, capital_limited)
    quantity = (raw_qty // lot_size) * lot_size
    planned_loss = quantity * risk_per_unit
    return {
        "risk_budget": risk_budget,
        "risk_per_unit": risk_per_unit,
        "quantity": quantity,
        "position_value": quantity * entry,
        "planned_loss": planned_loss,
        "capital_limited": capital_limited < risk_limited,
        "direction": direction,
    }
