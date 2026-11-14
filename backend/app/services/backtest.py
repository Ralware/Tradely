from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.services.indicators import compute_indicators


def run_trend_breakout_backtest(
    frame: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    risk_fraction: float = 0.005,
    cost_bps_per_side: float = 10.0,
    max_position_fraction: float = 0.95,
    initial_stop_atr: float = 2.0,
    trailing_stop_atr: float = 3.0,
    market: str = "global",
) -> dict:
    """Single-instrument long-only research backtest.

    Signal is evaluated on a completed close; entry/market exit is next bar open.
    Existing protective stop is checked against the current bar's range. If the
    market gaps through the stop, fill is conservatively modelled at the open.
    This is an approximation, not a broker/exchange execution simulator.
    """
    if len(frame) < 240:
        raise ValueError("At least 240 daily bars are required for this strategy backtest")
    if initial_capital <= 0 or not 0 < risk_fraction <= 0.02:
        raise ValueError("Invalid initial capital or risk fraction")
    if cost_bps_per_side < 0 or not 0 < max_position_fraction <= 1:
        raise ValueError("Invalid cost or max position setting")
    data = compute_indicators(frame)
    trades: list[dict] = []
    equity = float(initial_capital)
    equity_curve: list[dict] = []
    position: dict | None = None
    pending_exit = False
    entry_cost_fraction = cost_bps_per_side / 10_000

    for i in range(220, len(data)):
        exited_this_bar = False
        row = data.iloc[i]
        ts = data.index[i]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        # Check protective stop known before this candle. Gap-through stops fill at open.
        if position is not None and low <= position["stop"]:
            stop = float(position["stop"])
            exit_price = min(open_price, stop) if open_price < stop else stop
            gross = (exit_price - position["entry"]) * position["quantity"]
            fees = (position["entry"] + exit_price) * position["quantity"] * entry_cost_fraction
            net = gross - fees
            equity += net
            trades.append(_trade_record(position, ts, exit_price, gross, fees, net, "protective_stop"))
            position = None
            pending_exit = False
            exited_this_bar = True

        # A close-based exit signal from the previous bar executes at this bar's open.
        elif position is not None and pending_exit:
            exit_price = open_price
            gross = (exit_price - position["entry"]) * position["quantity"]
            fees = (position["entry"] + exit_price) * position["quantity"] * entry_cost_fraction
            net = gross - fees
            equity += net
            trades.append(_trade_record(position, ts, exit_price, gross, fees, net, "donchian_10_exit"))
            position = None
            pending_exit = False
            exited_this_bar = True

        # Enter at this bar's open if the prior completed bar generated a full setup.
        if position is None and not exited_this_bar and i > 220:
            signal_row = data.iloc[i - 1]
            required = ["sma_50", "sma_200", "rsi_14", "adx", "atr_14", "donchian_upper_20", "rvol_20"]
            if all(pd.notna(signal_row[name]) for name in required) and pd.notna(data["sma_200"].iloc[i - 21]):
                trend_ok = (
                    signal_row["close"] > signal_row["donchian_upper_20"]
                    and signal_row["close"] > signal_row["sma_200"]
                    and signal_row["sma_50"] > signal_row["sma_200"]
                    and signal_row["sma_200"] > data["sma_200"].iloc[i - 21]
                    and signal_row["rsi_14"] > 50
                    and signal_row["adx"] >= 20
                    and signal_row["rvol_20"] >= 1.0
                )
                atr_value = float(signal_row["atr_14"])
                stop = open_price - initial_stop_atr * atr_value
                if trend_ok and stop > 0 and open_price > stop:
                    risk_budget = equity * risk_fraction
                    quantity_by_risk = math.floor(risk_budget / (open_price - stop))
                    quantity_by_capital = math.floor((equity * max_position_fraction) / open_price)
                    quantity = max(0, min(quantity_by_risk, quantity_by_capital))
                    if quantity > 0:
                        position = {
                            "entry_time": ts.isoformat(), "entry": open_price, "quantity": quantity,
                            "stop": stop,
                            "signal_time": data.index[i - 1].isoformat(),
                        }

        if position is not None and position["entry_time"] == ts.isoformat() and low <= position["stop"]:
            # Protective stop is active immediately after an entry at today's open.
            exit_price = min(open_price, float(position["stop"]))
            gross = (exit_price - position["entry"]) * position["quantity"]
            fees = (position["entry"] + exit_price) * position["quantity"] * entry_cost_fraction
            net = gross - fees
            equity += net
            trades.append(_trade_record(position, ts, exit_price, gross, fees, net, "same_bar_protective_stop"))
            position = None
            pending_exit = False
            exited_this_bar = True

        if position is not None:
            # Apply trailing stop only after today's close; it is effective from next bar.
            atr_value = row["atr_14"]
            if pd.notna(atr_value):
                candidate = close - trailing_stop_atr * float(atr_value)
                position["stop"] = max(float(position["stop"]), candidate)
            # Compute prior-10-day lower channel explicitly; current day excluded.
            lower10 = data["low"].iloc[max(0, i - 10):i].min() if i >= 10 else np.nan
            pending_exit = bool(pd.notna(lower10) and close < lower10)
            # Entry and exit fees are recognised exactly once when a trade closes.
            unrealized = (close - position["entry"]) * position["quantity"]
        else:
            unrealized = 0.0
        marked_equity = equity + unrealized
        equity_curve.append({"timestamp": ts.isoformat(), "equity": marked_equity})

    # Close an open position on the final available close so metrics are fully realised.
    if position is not None:
        last = data.iloc[-1]
        exit_price = float(last["close"])
        gross = (exit_price - position["entry"]) * position["quantity"]
        fees = (position["entry"] + exit_price) * position["quantity"] * entry_cost_fraction
        net = gross - fees
        equity += net
        trades.append(_trade_record(position, data.index[-1], exit_price, gross, fees, net, "end_of_test"))
        if equity_curve:
            equity_curve[-1]["equity"] = equity

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
    return {
        "initial_capital": initial_capital,
        "final_equity": equity,
        "net_return_pct": (equity / initial_capital - 1) * 100,
        "trade_count": len(trades),
        "win_rate_pct": (len(winners) / len(trades) * 100) if trades else None,
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
        "limitations": [
            "Single instrument, long-only research simulation; not a portfolio backtest.",
            "Signals use completed daily bars and entries/exits execute at next bar open.",
            "Protective stop fills model gap-through conservatively, but intrabar price path is unknown.",
            "Cost is a configurable aggregate basis-point estimate, not a broker-specific Indian tax engine.",
            "No survivorship-free historical universe or point-in-time symbol membership is supplied by this endpoint.",
            "This result is not out-of-sample proof; use a locked walk-forward research protocol before relying on it.",
        ],
    }


def _trade_record(position: dict, exit_time, exit_price: float, gross: float,
                  fees: float, net: float, reason: str) -> dict:
    return {
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
