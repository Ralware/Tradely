from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd

from app.core.fills import FeeSchedule
from app.services.indicators import compute_indicators
from app.services.strategy_config import DEFAULT_STRATEGY_CONFIG, StrategyConfig


def run_trend_breakout_backtest(
    frame: pd.DataFrame,
    *,
    initial_capital: float = 1_000.0,
    risk_fraction: float = 0.005,
    cost_bps_per_side: float = 2.0,
    slippage_bps_per_side: float = 0.0,
    max_position_fraction: float = 0.95,
    market: str = "global",
    direction_mode: Literal["long_only", "short_only", "long_short"] = "long_only",
    strategy_config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> dict:
    """Single-instrument directional backtest.

    Signal is evaluated on a completed close; entry/market exit is next bar open.
    Existing protective stop is checked against the current bar's range. If the
    market gaps through the stop, fill is conservatively modelled at the open.
    Short exposure is a simulation only and is not an exchange order.
    """
    excluded_incomplete = False
    if "is_final" in frame.columns:
        final_mask = frame["is_final"].eq(True).fillna(False)
        excluded_incomplete = not bool(final_mask.all())
        frame = frame.loc[final_mask].copy()
    indicator_warmup = max(strategy_config.sma_slow_period + 20, strategy_config.rsi_period + 1,
                 strategy_config.adx_period * 2, strategy_config.atr_period + 1,
                 strategy_config.donchian_entry_period + 1,
                 strategy_config.donchian_exit_period + 1, strategy_config.rvol_period + 1, 220)
    if len(frame) < max(indicator_warmup, 240):
        raise ValueError("At least 240 daily bars are required for this strategy backtest")
    if not math.isfinite(initial_capital) or initial_capital <= 0 or not 0 < risk_fraction <= 0.02:
        raise ValueError("Invalid initial capital or risk fraction")
    if not (math.isfinite(cost_bps_per_side) and 0 <= slippage_bps_per_side <= cost_bps_per_side) or not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid cost or max position setting")
    if direction_mode not in ("long_only", "short_only", "long_short"):
        raise ValueError("Invalid direction_mode")
    data = (compute_indicators(frame) if strategy_config == DEFAULT_STRATEGY_CONFIG
            else compute_indicators(frame, strategy_config=strategy_config))
    fast_sma = f"sma_{strategy_config.sma_fast_period}"
    slow_sma = f"sma_{strategy_config.sma_slow_period}"
    rsi_col = f"rsi_{strategy_config.rsi_period}"
    atr_col = f"atr_{strategy_config.atr_period}"
    entry_col = f"donchian_upper_{strategy_config.donchian_entry_period}"
    exit_col = f"donchian_lower_{strategy_config.donchian_exit_period}"
    rvol_col = f"rvol_{strategy_config.rvol_period}"
    trades: list[dict] = []
    equity = float(initial_capital)
    equity_curve: list[dict] = []
    position: dict | None = None
    pending_exit = False
    entry_cost_fraction = cost_bps_per_side / 10_000

    schedule = FeeSchedule(taker=(cost_bps_per_side - slippage_bps_per_side) / 10_000)

    def settle(open_position: dict, timestamp, price: float, reason: str) -> float:
        quantity = open_position["quantity"]
        entry_price = open_position["entry"]
        entry = quantity * entry_price
        exit_value = quantity * price
        entry_fee = schedule.charge(quantity, entry_price, "taker")
        exit_fee = schedule.charge(quantity, price, "taker")
        slippage = (entry + exit_value) * slippage_bps_per_side / 10_000
        costs = entry_fee + exit_fee + slippage
        gross = _gross_pnl(open_position, price)
        net = gross - costs
        trade = _trade_record(open_position, timestamp, price, gross, costs, net, reason)
        trade.update(entry_notional=entry, exit_notional=exit_value, entry_fee=entry_fee,
                     exit_fee=exit_fee, maker_fees=0.0, taker_fees=entry_fee + exit_fee,
                     funding=0.0, entry_liquidity="taker", exit_liquidity="taker",
                     slippage=slippage, net_return_pct=100 * net / entry,
                     holding_hours=(timestamp - pd.Timestamp(open_position["entry_time"])).total_seconds() / 3600)
        trades.append(trade)
        return net

    first_bar = max(220, indicator_warmup - 1)
    equity_curve.append({"timestamp": data.index[first_bar - 1].isoformat(), "equity": equity})
    for i in range(first_bar, len(data)):
        exited_this_bar = False
        row = data.iloc[i]
        ts = data.index[i]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        stop_hit = (
            position is not None
            and (
                low <= position["stop"]
                if position["direction"] == "LONG"
                else high >= position["stop"]
            )
        )
        # Check protective stop known before this candle. Gap-through stops fill at open.
        if stop_hit and position is not None and not pending_exit:
            stop = float(position["stop"])
            exit_price = _stop_fill(position, open_price, stop)
            equity += settle(position, ts, exit_price, "protective_stop")
            position = None
            pending_exit = False
            exited_this_bar = True

        # A close-based exit signal from the previous bar executes at this bar's open.
        elif position is not None and pending_exit:
            exit_price = open_price
            equity += settle(position, ts, exit_price, "donchian_10_exit")
            position = None
            pending_exit = False
            exited_this_bar = True

        # Enter at this bar's open if the prior completed bar generated a full setup.
        if position is None and not exited_this_bar and i >= first_bar:
            signal_row = data.iloc[i - 1]
            required = [fast_sma, slow_sma, rsi_col, "adx", atr_col, entry_col, rvol_col]
            candle_is_final = "is_final" not in data.columns or bool(signal_row["is_final"])
            if (
                candle_is_final
                and all(pd.notna(signal_row[name]) for name in required)
                and pd.notna(data[slow_sma].iloc[i - 21])
            ):
                long_setup = (
                    direction_mode != "short_only"
                    and signal_row["close"] > signal_row[entry_col]
                    and signal_row["close"] > signal_row[slow_sma]
                    and signal_row[fast_sma] > signal_row[slow_sma]
                    and signal_row[slow_sma] > data[slow_sma].iloc[i - 21]
                    and signal_row[rsi_col] > strategy_config.rsi_threshold
                    and signal_row["adx"] >= strategy_config.min_adx
                    and signal_row[rvol_col] >= strategy_config.min_rvol
                )
                prior_lows = data["low"].iloc[max(0, i - strategy_config.donchian_entry_period - 1):i - 1]
                short_setup = (
                    direction_mode != "long_only"
                    and not prior_lows.empty
                    and signal_row["close"] < prior_lows.min()
                    and signal_row["close"] < signal_row[slow_sma]
                    and signal_row[fast_sma] < signal_row[slow_sma]
                    and signal_row[slow_sma] < data[slow_sma].iloc[i - 21]
                    and signal_row[rsi_col] < 100 - strategy_config.rsi_threshold
                    and signal_row["adx"] >= strategy_config.min_adx
                    and signal_row[rvol_col] >= strategy_config.min_rvol
                )
                atr_value = float(signal_row[atr_col])
                direction = "LONG" if long_setup else "SHORT" if short_setup else None
                stop = (
                    open_price - strategy_config.initial_stop_atr * atr_value
                    if direction == "LONG"
                    else open_price + strategy_config.initial_stop_atr * atr_value
                )
                valid_stop = (
                    direction == "LONG" and 0 < stop < open_price
                ) or (
                    direction == "SHORT" and stop > open_price
                )
                if direction is not None and valid_stop:
                    risk_budget = equity * risk_fraction
                    risk_per_unit = abs(open_price - stop)
                    # Fractional sizing keeps every positive capital usable and
                    # makes results scale proportionally with the account size.
                    # Flooring to whole units silently skipped entries whenever
                    # the risk budget was smaller than one unit's stop distance.
                    quantity_by_risk = risk_budget / risk_per_unit
                    quantity_by_capital = (equity * max_position_fraction) / open_price
                    quantity = min(quantity_by_risk, quantity_by_capital)
                    # Round down to avoid ever exceeding either sizing cap.
                    quantity = math.floor(quantity * 100_000_000) / 100_000_000
                    if quantity > 0:
                        position = {
                            "entry_time": ts.isoformat(), "entry": open_price, "quantity": quantity,
                            "stop": stop, "direction": direction,
                            "signal_time": data.index[i - 1].isoformat(),
                        }

        entry_stop_hit = (
            position is not None
            and position["entry_time"] == ts.isoformat()
            and (
                low <= position["stop"]
                if position["direction"] == "LONG"
                else high >= position["stop"]
            )
        )
        if entry_stop_hit and position is not None:
            # Protective stop is active immediately after an entry at today's open.
            exit_price = _stop_fill(position, open_price, float(position["stop"]))
            equity += settle(position, ts, exit_price, "same_bar_protective_stop")
            position = None
            pending_exit = False
            exited_this_bar = True

        if position is not None:
            # Apply trailing stop only after today's close; it is effective from next bar.
            atr_value = row[atr_col]
            if pd.notna(atr_value):
                if position["direction"] == "LONG":
                    candidate = close - strategy_config.trailing_stop_atr * float(atr_value)
                    position["stop"] = max(float(position["stop"]), candidate)
                else:
                    candidate = close + strategy_config.trailing_stop_atr * float(atr_value)
                    position["stop"] = min(float(position["stop"]), candidate)
            # Compute the configured prior-bar exit channel; current bar is excluded.
            prior_lows = data["low"].iloc[max(0, i - strategy_config.donchian_exit_period):i]
            prior_highs = data["high"].iloc[max(0, i - strategy_config.donchian_exit_period):i]
            if position["direction"] == "LONG":
                pending_exit = bool(not prior_lows.empty and close < prior_lows.min())
            else:
                pending_exit = bool(not prior_highs.empty and close > prior_highs.max())
            # Entry and exit fees are recognised exactly once when a trade closes.
            unrealized = _gross_pnl(position, close) - (position["entry"] + close) * position["quantity"] * entry_cost_fraction
        else:
            unrealized = 0.0
        marked_equity = equity + unrealized
        equity_curve.append({"timestamp": ts.isoformat(), "equity": marked_equity})

    # Close an open position on the final available close so metrics are fully realised.
    if position is not None:
        last = data.iloc[-1]
        exit_price = float(last["close"])
        equity += settle(position, data.index[-1], exit_price, "end_of_test")
        if equity_curve:
            equity_curve[-1]["equity"] = equity

    gross_values = [trade["gross_pnl"] for trade in trades]
    gross_gains = sum(max(0, v) for v in gross_values)
    gross_losses = sum(max(0, -v) for v in gross_values)
    pnls = [trade["net_pnl"] for trade in trades]
    winners = [value for value in pnls if value > 0]
    losers = [value for value in pnls if value < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    curve = pd.Series([point["equity"] for point in equity_curve], dtype=float)
    running_max = curve.cummax() if not curve.empty else pd.Series(dtype=float)
    drawdown = curve / running_max - 1 if not curve.empty else pd.Series(dtype=float)
    returns = curve.pct_change().dropna() if not curve.empty else pd.Series(dtype=float)
    sharpe = None
    annualization = 365 if market == "crypto" else 252
    if len(returns) > 1 and returns.std(ddof=1) > 0:
        sharpe = float(np.sqrt(annualization) * returns.mean() / returns.std(ddof=1))
    # Downside deviation is measured against a zero daily target across the
    # full return series; using only negative observations understates risk.
    downside = np.minimum(returns.to_numpy(dtype=float), 0.0)
    sortino = None
    downside_deviation = float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0
    if len(returns) > 1 and downside_deviation > 0:
        sortino = float(np.sqrt(annualization) * returns.mean() / downside_deviation)
    limitations = [
        f"Single instrument, {direction_mode.replace('_', '-')} simulation; not a portfolio backtest.",
        "Signals use completed daily bars and entries/exits execute at next bar open.",
        "Protective stop fills model gap-through conservatively, but intrabar price path is unknown.",
        "Cost is a configurable aggregate basis-point estimate, not a broker-specific Indian tax engine.",
        "No survivorship-free historical universe or point-in-time symbol membership is supplied by this endpoint.",
        "Position quantity is fractional so every positive capital value is usable; venues that require whole shares will differ.",
        "This result is not out-of-sample proof; use a locked walk-forward validation protocol before relying on it.",
        (
            "Short exposure is hypothetical simulated exposure; no margin, borrow, or exchange execution is modelled."
            if direction_mode != "long_only"
            else "A SELL rule exits an existing long and never opens a short in long-only mode."
        ),
    ]
    if excluded_incomplete:
        limitations.append("Unfinished candles were excluded from the simulation.")
    latest = data.iloc[-1]
    strategy_indicators = {
        "sma_fast": latest.get(fast_sma), "sma_slow": latest.get(slow_sma),
        "rsi": latest.get(rsi_col), "adx": latest.get("adx"), "atr": latest.get(atr_col),
        "donchian_entry": latest.get(entry_col), "donchian_exit": latest.get(exit_col),
        "relative_volume": latest.get(rvol_col),
    }
    strategy_indicators = {key: (None if pd.isna(value) else float(value)) for key, value in strategy_indicators.items()}
    return {
        "gross_pnl": sum(gross_values), "net_pnl": sum(pnls),
        "total_maker_fees": 0.0, "total_taker_fees": sum(t["taker_fees"] for t in trades),
        "total_fees": sum(t["taker_fees"] for t in trades),
        "total_slippage": sum(t["slippage"] for t in trades), "total_funding": 0.0,
        "funding_model": "UNAVAILABLE_EXCLUDED_ZERO" if market == "crypto" else "NOT_APPLICABLE",
        "gross_return_pct": 100 * sum(gross_values) / initial_capital,
        "gross_profit_factor": gross_gains / gross_losses if gross_losses else ("infinite" if gross_gains else None),
        "gross_win_rate_pct": 100 * sum(v > 0 for v in gross_values) / len(trades) if trades else None,
        "average_duration_hours": np.mean([t["holding_hours"] for t in trades]) if trades else None,
        "direction_mode": direction_mode,
        "strategy_config": strategy_config.model_dump(mode="json"),
        "strategy_indicators": strategy_indicators,
        "initial_capital": initial_capital,
        "final_equity": equity,
        "net_profit_loss": equity - initial_capital,
        "net_return_pct": (equity / initial_capital - 1) * 100,
        "trade_count": len(trades),
        "win_rate_pct": (len(winners) / len(trades) * 100) if trades else None,
        "average_winning_trade": float(np.mean(winners)) if winners else None,
        "average_losing_trade": float(np.mean(losers)) if losers else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else (None if not gross_profit else "infinite"),
        "expectancy_per_trade": float(np.mean(pnls)) if pnls else None,
        "max_drawdown_pct": (float(drawdown.min()) * 100) if not drawdown.empty else None,
        "sharpe_daily_annualized": sharpe,
        "sortino_daily_annualized": sortino,
        "cost_bps_per_side": cost_bps_per_side,
        "annualization_factor": annualization,
        "risk_free_rate_annual": 0.0,
        "sortino_target_daily": 0.0,
        "trades": trades,
        "equity_curve": equity_curve,
        "limitations": limitations,
    }


def _gross_pnl(position: dict, exit_price: float) -> float:
    price_change = (
        exit_price - position["entry"]
        if position["direction"] == "LONG"
        else position["entry"] - exit_price
    )
    return price_change * position["quantity"]


def _stop_fill(position: dict, open_price: float, stop: float) -> float:
    if position["direction"] == "LONG":
        return min(open_price, stop)
    return max(open_price, stop)


def _trade_record(position: dict, exit_time, exit_price: float, gross: float,
                  fees: float, net: float, reason: str) -> dict:
    return {
        "direction": position["direction"],
        "signal_time": position["signal_time"],
        "entry_time": position["entry_time"],
        "exit_time": exit_time.isoformat(),
        "entry_price": position["entry"],
        "exit_price": exit_price,
        "quantity": position["quantity"],
        "gross_pnl": gross,
        "total_costs": fees,
        "net_pnl": net,
        "exit_reason": reason,
    }
