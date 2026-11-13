from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd

from app.core.models import SignalCondition, StrategySignal
from app.services.indicators import compute_indicators

STRATEGY_VERSION = "trend-donchian-20-v1.0.0"


def evaluate_trend_breakout(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
    source: str | None = None,
    min_adx: float = 20.0,
    min_rvol: float = 1.0,
) -> StrategySignal:
    """Long-only daily candidate; completed-bar close breakout over prior 20 bars.

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
            explanation=f"At least 220 completed daily bars are required; received {len(frame)}.",
            data_source=source,
        )

    data = compute_indicators(frame)
    row = data.iloc[-1]
    prior = data.iloc[-2]
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
        timestamp = timestamp.replace(tzinfo=timezone.utc)
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


def position_size(
    *, capital: float, risk_fraction: float, entry: float, stop: float,
    lot_size: int = 1, max_position_fraction: float = 1.0,
) -> dict[str, float | int | bool]:
    values = (capital, risk_fraction, entry, stop, max_position_fraction)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Inputs must be finite")
    if capital <= 0 or entry <= 0 or stop <= 0 or risk_fraction <= 0:
        raise ValueError("Capital, entry, stop and risk fraction must be positive")
    if stop >= entry:
        raise ValueError("For a long position, stop must be below entry")
    if lot_size < 1 or not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid lot size or maximum position fraction")
    risk_budget = capital * risk_fraction
    risk_per_unit = entry - stop
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
    }
