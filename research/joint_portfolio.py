"""CPU simulation of a shared, one-times-notional perpetual portfolio."""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
import strategy_analyzer as engine


class MarketBars(NamedTuple):
    signals: np.ndarray
    opens: np.ndarray
    closes: np.ndarray
    open_funding: np.ndarray
    inside_funding: np.ndarray


def joint_portfolio(frames, configs, timeframe, *, capital=1000.0, maintenance_rate=None):
    """Process synchronized bars. Signals on an exit bar remain ineligible."""
    if not frames or not math.isfinite(capital) or capital <= 0:
        raise ValueError("Supply synchronized symbol histories and positive capital")
    if maintenance_rate is not None and not 0 <= maintenance_rate < 1:
        raise ValueError("Maintenance rate must be in [0, 1)")
    symbols = sorted(frames)
    index = frames[symbols[0]].index
    if not len(index) or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("Expected unique chronological bars")
    if any(not index.equals(frame.index) for frame in frames.values()):
        raise ValueError("Portfolio histories must have identical bar timestamps")
    if any(index[1:] - index[:-1] != engine.timeframe_interval(timeframe)):
        raise ValueError("Synchronized histories contain a candle gap")
    data = {}
    for symbol in symbols:
        frame = frames[symbol]
        opened, inside = engine.funding_per_unit(frame)
        zeros = np.zeros(len(index))
        data[symbol] = MarketBars(
            frame["signal"].to_numpy(),
            frame.open.to_numpy(),
            frame.close.to_numpy(),
            zeros if opened is None else opened,
            zeros if inside is None else inside,
        )

    wallet = peak = realized_peak = float(capital)
    drawdown = realized_dd = 0.0
    positions, next_entry = {}, dict.fromkeys(symbols, 1)
    trades, marks, realized = [], [], []
    skipped = liquidations = 0
    settled_balance = float(capital)

    def mark(i, *, at_open=False):
        value = wallet
        gross = 0.0
        for symbol, pos in positions.items():
            bars = data[symbol]
            price = bars.opens[i] if at_open else bars.closes[i]
            gross += pos["quantity"] * price
            value += pos["signed_qty"] * (price - pos["entry_fill"])
        return value - gross * engine.TAKER_RATE, gross

    def settle(symbol, price, rate, reason):
        nonlocal wallet, settled_balance
        pos = positions.pop(symbol)
        gross = pos["signed_qty"] * (price - pos["entry_fill"])
        fee = pos["quantity"] * price * rate
        wallet += gross - fee
        pnl = gross - fee - pos["entry_fee"] - pos["funding"]
        settled_balance += pnl
        trades.append(
            {
                "symbol": symbol,
                "trade_index": pos["trade_index"],
                "side": pos["side"],
                "entry_time": str(index[pos["entry_i"]]),
                "exit_time": str(index[i]),
                "entry_fill": pos["entry_fill"],
                "exit_fill": price,
                "exit_reason": reason,
                "quantity": pos["quantity"],
                "reserved_notional": pos["reserve"],
                "gross_pnl": gross,
                "entry_fee": pos["entry_fee"],
                "exit_fee": fee,
                "funding": pos["funding"],
                "net_pnl": pnl,
            }
        )
        next_entry[symbol] = i + 2

    counts = dict.fromkeys(symbols, 0)
    for i, timestamp in enumerate(index):
        previous_count = len(trades)
        for symbol, pos in positions.items():
            payment = pos["signed_qty"] * data[symbol].open_funding[i]
            pos["funding"] += payment
            wallet -= payment
        sizing_equity, open_exposure = mark(i, at_open=True)
        exposure_budget = sizing_equity - open_exposure
        for symbol in symbols:
            if i < next_entry[symbol] or symbol in positions:
                continue
            if data[symbol].signals[i - 1] not in ("LONG", "SHORT"):
                continue
            config = configs[symbol]
            window = frames[symbol].iloc[i - 1 : i + int(config["time_stop"])]
            # The strategy owns stop/target priority, trailing stops and expiry.
            # Only this entry is eligible. Later signals are visited by the outer loop.
            window = window.copy()
            window.iloc[1:, window.columns.get_loc("signal")] = "NONE"
            candidates, _ = engine.simulate_trades(
                window, config, timeframe, collect_audit=False, gap_events=[]
            )
            if not candidates:
                continue
            candidate = candidates[0]
            free = wallet - sum(p["reserve"] for p in positions.values())
            reserve = min(
                sizing_equity * candidate["entry_notional"] / engine.STARTING_EQUITY_USDT,
                free / (1 + engine.TAKER_RATE),
                exposure_budget / (1 + engine.TAKER_RATE),
            )
            if reserve <= 1e-12:
                skipped += 1
                continue
            quantity = reserve / candidate["entry_fill"]
            entry_fee = reserve * engine.TAKER_RATE
            positions[symbol] = {
                **candidate,
                "quantity": quantity,
                "reserve": reserve,
                "entry_i": i,
                "exit_i": i + candidate["bars_held"] - 1,
                "signed_qty": quantity if candidate["side"] == "LONG" else -quantity,
                "entry_fee": entry_fee,
                "funding": 0.0,
                "trade_index": counts[symbol],
            }
            exposure_budget -= reserve + entry_fee
            counts[symbol] += 1
            wallet -= entry_fee
        for symbol, pos in list(positions.items()):
            exits = i == pos["exit_i"]
            if not exits or pos["exit_reason"] in ("TIME_STOP", "DATA_END"):
                payment = pos["signed_qty"] * data[symbol].inside_funding[i]
                pos["funding"] += payment
                wallet -= payment
            if exits:
                rate = engine.MAKER_RATE if pos["exit_liquidity"] == "maker" else engine.TAKER_RATE
                settle(symbol, pos["exit_fill"], rate, pos["exit_reason"])
        equity, exposure = mark(i)
        if positions and maintenance_rate is not None and equity <= exposure * maintenance_rate:
            for symbol in list(positions):
                settle(symbol, data[symbol].closes[i], engine.TAKER_RATE, "MAINTENANCE_CLOSE")
            liquidations += 1
            equity = wallet
        if previous_count != len(trades):
            realized.append({"time": str(timestamp), "equity": settled_balance})
        realized_peak = max(realized_peak, settled_balance)
        realized_dd = min(realized_dd, settled_balance / realized_peak - 1)
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
        marks.append({"time": str(timestamp), "equity": equity})
    return {
        "starting_capital": capital,
        "allocation_order": "Symbol ascending at bar open, before same-bar exits",
        "mark_model": "Candle close less estimated taker exit fee",
        "maintenance_model": "Flat cross-account threshold at candle close"
        if maintenance_rate is not None
        else "Disabled",
        "slippage_rate": 0.0,
        "maker_rate": engine.MAKER_RATE,
        "taker_rate": engine.TAKER_RATE,
        "ending_capital": wallet,
        "net_pnl": wallet - capital,
        "skipped_trades": skipped,
        "trades": trades,
        "realized_equity": realized,
        "marked_equity": marks,
        "marked_max_drawdown_pct": 100 * drawdown,
        "realized_max_drawdown_pct": 100 * realized_dd,
        "maintenance_rate": maintenance_rate,
        "maintenance_close_events": liquidations,
    }
