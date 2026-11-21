"""Walk-forward, bootstrap, and shared-capital experiments for V4.2 net ledgers."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import strategy_analyzer as engine
from exit_paths import prefix_max
from joint_portfolio import joint_portfolio


def walk_forward(timeframe, base, htf, boundaries, configs, *, min_train_trades=1, mode="cpu"):
    """Select on expanding history and evaluate once per disjoint holdout."""
    dates = [engine.as_utc_timestamp(value, "fold boundary") for value in boundaries]
    if mode not in ("auto", "cpu", "gpu"):
        raise ValueError("mode must be auto, cpu, or gpu")
    cadence = engine.timeframe_interval(timeframe)
    if len(dates) < 2 or any(a >= b for a, b in pairwise(dates)):
        raise ValueError("At least two strictly increasing UTC boundaries are required")
    if any(not engine.exchange_boundary_aligned(date, timeframe) for date in dates):
        raise ValueError("Fold boundaries must align with the base candle")
    if not configs or min_train_trades < 1:
        raise ValueError("Supply configurations and a positive minimum trade count")

    paths = Path(base), Path(htf)
    hashes = tuple(engine.sha256_file(path) for path in paths)
    folds = []
    combined_factor = 1.0
    for start, end in pairwise(dates):
        prepared = engine.prepare_analysis_data(
            timeframe, base, htf, start, engine.CUTOFF_MODE_STRICT
        )
        scores = []
        for idx, config in enumerate(configs):
            report = engine.run_analysis(
                timeframe,
                base,
                htf,
                config,
                data_cutoff=start,
                prepared_data=prepared,
                execution_mode=mode,
                write_outputs=False,
                collect_audit=False,
                run_id=f"train-{idx}",
            )["report"]
            metrics = report["metrics"]
            if metrics["trades"] >= min_train_trades:
                scores.append((metrics["net_pnl"], -idx))
        fold: dict[str, Any] = {"start": str(start), "end_exclusive": str(end)}
        if not scores:
            folds.append({**fold, "status": "insufficient_training_trades"})
            continue
        score, neg_idx = max(scores)
        config = {**engine.BASELINE_CONFIGS[timeframe], **configs[-neg_idx]}
        result = engine.run_analysis(
            timeframe,
            base,
            htf,
            config,
            data_cutoff=end,
            execution_mode=mode,
            write_outputs=False,
            collect_audit=False,
        )
        signals = result["signals"]
        # The last completed training candle may signal an entry at holdout open.
        holdout = signals.loc[signals.index >= start - cadence].copy()
        if start not in holdout.index or end - cadence not in holdout.index:
            raise ValueError("Holdout candle coverage is invalid")
        trades, _ = engine.simulate_trades(holdout, config, timeframe, collect_audit=False)
        pnl = math.fsum(t["net_pnl"] for t in trades)
        combined_factor *= 1 + pnl / engine.STARTING_EQUITY_USDT
        folds.append(
            {
                **fold,
                "status": "evaluated",
                "configuration": config,
                "training_net_pnl": score,
                "trades": len(trades),
                "net_pnl": pnl,
                "first_entry": trades[0]["entry_time"] if trades else None,
                "last_exit": trades[-1]["exit_time"] if trades else None,
                "signal_source_run_id": result["report"]["run_id"],
            }
        )
    if tuple(engine.sha256_file(path) for path in paths) != hashes:
        raise ValueError("Walk-forward inputs changed during evaluation")
    return {
        "timeframe": timeframe,
        "engine_source_sha256": engine.engine_source_hash(),
        "execution_mode": mode,
        "candidates": configs,
        "min_train_trades": min_train_trades,
        "folds": folds,
        "base_sha256": hashes[0],
        "htf_sha256": hashes[1],
        "selection": "Highest eligible training net PnL; ties follow input order",
        "combined_return_pct": (
            100 * (combined_factor - 1) if any(f["status"] == "evaluated" for f in folds) else None
        ),
    }


def bootstrap_trade_returns(returns, *, paths=10000, block_size=5, seed=42, mode="cpu"):
    """Sample circular blocks of settled net returns and calculate path drawdowns."""
    values = np.asarray(returns, dtype=np.float64)
    if values.ndim != 1 or not 1 <= block_size <= values.size:
        raise ValueError("Block size must be within the nonempty return history")
    if not np.isfinite(values).all() or np.any(values < -1) or paths < 1:
        raise ValueError("Expected finite returns of at least -100% and a positive path count")
    if mode not in ("auto", "cpu", "gpu"):
        raise ValueError("mode must be auto, cpu, or gpu")
    lib = np
    fallback = None
    if mode == "gpu" or (mode == "auto" and paths * len(values) >= 100000):
        try:
            lib = engine.cuda_device()
        except (ImportError, RuntimeError, OSError, MemoryError) as exc:
            fallback = str(exc)

    def calculate(xp):
        rng = np.random.default_rng(seed)
        terminal = np.empty(paths)
        drawdowns = np.empty(paths)
        blocks = math.ceil(len(values) / block_size)
        capacity = 8 * 1024**2
        if xp is not np:
            capacity = min(capacity, xp.cuda.runtime.memGetInfo()[0] // 8)
        batch = max(1, capacity // (64 * len(values)))
        samples = xp.asarray(values)
        offsets = np.arange(block_size)
        for i in range(0, paths, batch):
            stop = min(i + batch, paths)
            starts = rng.integers(len(values), size=(stop - i, blocks, 1))
            idx = ((starts + offsets) % len(values)).reshape(stop - i, -1)[:, : len(values)]
            equity = xp.cumprod(1 + samples[xp.asarray(idx)], axis=1)
            peak = xp.maximum(1, prefix_max(equity, xp))
            low = xp.min(equity / peak - 1, axis=1)
            terminal[i:stop] = equity[:, -1] if xp is np else xp.asnumpy(equity[:, -1])
            drawdowns[i:stop] = low if xp is np else xp.asnumpy(low)
        if not np.isfinite(terminal).all() or not np.isfinite(drawdowns).all():
            raise ValueError("Bootstrap path equity exceeded numeric bounds")
        return terminal - 1, drawdowns

    try:
        terminal, drawdowns = calculate(lib)
    except (RuntimeError, MemoryError) as exc:
        if lib is np:
            raise
        fallback, lib = str(exc), np
        terminal, drawdowns = calculate(lib)
    quantiles = [5, 50, 95]
    return {
        "paths": paths,
        "trades_per_path": len(values),
        "block_size": block_size,
        "seed": seed,
        "execution_backend": "cpu" if lib is np else "cuda",
        "fallback_reason": fallback,
        "percentiles": quantiles,
        "terminal_return_pct": (100 * np.percentile(terminal, quantiles)).tolist(),
        "drawdown_pct": (100 * np.percentile(drawdowns, quantiles)).tolist(),
        "loss_probability": float(np.mean(terminal < 0)),
    }


def portfolio_replay(ledgers: Mapping[str, Sequence[Mapping[str, Any]]], *, capital=1000.0):
    """Allocate shared cash to precomputed trade intents without borrowing."""
    if not math.isfinite(capital) or capital <= 0 or not ledgers:
        raise ValueError("Supply one or more ledgers and positive finite capital")
    entries = defaultdict(list)
    exits = defaultdict(list)
    for symbol, trades in sorted(ledgers.items()):
        previous_exit = None
        for idx, trade in enumerate(trades):
            start = engine.as_utc_timestamp(trade["entry_time"], "entry")
            end = engine.as_utc_timestamp(trade["exit_time"], "exit")
            if start > end or (previous_exit is not None and start <= previous_exit):
                raise ValueError(f"Invalid or overlapping trades for {symbol}")
            previous_exit = end
            standalone = float(trade["equity_before"])
            notional = float(trade["entry_notional"])
            net_pnl = float(trade["net_pnl"])
            if not all(
                map(math.isfinite, (standalone, notional, net_pnl))
            ) or not 0 < notional <= standalone * (1 + 1e-12):
                raise ValueError(f"Invalid cash ledger amounts for {symbol}")
            key = (symbol, idx)
            entries[start].append((key, standalone, notional, net_pnl))
            exits[end].append(key)

    balance = cash = float(capital)
    positions = {}
    settled = []
    realized_equity = []
    skipped = 0
    peak, drawdown = balance, 0.0
    for time in sorted(entries.keys() | exits.keys()):
        # All entries precede exits stamped with the same bar. Symbol order
        # breaks ties. This avoids spending proceeds before unknown intrabar exits.
        for key, standalone, notional, net_pnl in entries[time]:
            if cash <= 0 or balance <= 0:
                skipped += 1
                continue
            scale = min(balance / standalone, cash / notional)
            reserve = min(cash, notional * scale)
            cash -= reserve
            positions[key] = (reserve, net_pnl * scale)
        for key in exits[time]:
            if key not in positions:
                continue
            reserve, pnl = positions.pop(key)
            cash += reserve + pnl
            balance += pnl
            settled.append(
                {
                    "symbol": key[0],
                    "trade_index": key[1],
                    "exit_time": str(time),
                    "reserved_notional": reserve,
                    "net_pnl": pnl,
                }
            )
        if exits[time]:
            realized_equity.append({"time": str(time), "equity": balance})
        peak = max(peak, balance)
        drawdown = min(drawdown, balance / peak - 1)
    return {
        "starting_capital": capital,
        "ending_capital": balance,
        "net_pnl": balance - capital,
        "realized_max_drawdown_pct": 100 * drawdown,
        "skipped_trades": skipped,
        "trades": settled,
        "realized_equity": realized_equity,
    }


def portfolio_backtest(
    timeframe, datasets, cutoff, *, capital=1000.0, mode="auto", maintenance_rate=None
):
    """Simulate concurrent signals against a shared futures wallet."""
    frames, configs, provenance = {}, {}, {}
    for symbol, dataset in sorted(datasets.items()):
        base, htf = Path(dataset["base"]), Path(dataset["htf"])
        analysis = engine.run_analysis(
            timeframe,
            base,
            htf,
            dataset.get("config"),
            data_cutoff=cutoff,
            execution_mode=mode,
            write_outputs=False,
            collect_audit=False,
        )
        report = analysis["report"]
        if report["warmup"]["evaluation_start_index"] is None:
            raise ValueError(f"{symbol} has no eligible evaluation interval")
        frames[symbol] = analysis["signals"].iloc[report["warmup"]["evaluation_start_index"] :]
        configs[symbol] = report["configuration"]
        provenance[symbol] = {
            "run_id": report["run_id"],
            "configuration": report["configuration"],
            "base_sha256": report["base_source_sha256"],
            "htf_sha256": report["htf_source_sha256"],
            "funding_model": report["funding_model"],
            "execution_backend": report["active_backend"],
            "fallback_reason": report["backend_fallback"],
        }
    if not frames:
        raise ValueError("Supply at least one symbol history")
    start = max(frame.index[0] for frame in frames.values())
    frames = {symbol: frame.loc[start:] for symbol, frame in frames.items()}
    return {
        "common_evaluation_start": str(start),
        "portfolio_source_sha256": engine.sha256_file(
            Path(__file__).with_name("joint_portfolio.py")
        ),
        **joint_portfolio(
            frames, configs, timeframe, capital=capital, maintenance_rate=maintenance_rate
        ),
        "timeframe": timeframe,
        "data_cutoff": str(cutoff),
        "engine_source_sha256": engine.engine_source_hash(),
        "datasets": provenance,
    }


def read_ledger(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    walk = sub.add_parser("walk-forward")
    walk.add_argument("timeframe", choices=engine.BASELINE_CONFIGS)
    walk.add_argument("boundaries", nargs="+")
    walk.add_argument(
        "--configs", type=Path, required=True, help="JSON array of config override objects"
    )
    walk.add_argument("--base", type=Path)
    walk.add_argument("--htf", type=Path)
    walk.add_argument("--min-trades", type=int, default=1)
    monte = sub.add_parser("monte-carlo")
    monte.add_argument("trades", type=Path, help="V4.2 trade CSV")
    monte.add_argument("--paths", type=int, default=10000)
    monte.add_argument("--block-size", type=int, default=5)
    monte.add_argument("--seed", type=int, default=42)
    for command in (walk, monte):
        command.add_argument("--mode", choices=("cpu", "gpu", "auto"), default="auto")
    portfolio = sub.add_parser("portfolio")
    portfolio.add_argument(
        "ledgers", type=Path, help="JSON object mapping symbols to trade CSV paths"
    )
    portfolio.add_argument("--capital", type=float, default=1000)
    combined = sub.add_parser("portfolio-backtest")
    combined.add_argument("timeframe", choices=engine.BASELINE_CONFIGS)
    combined.add_argument("cutoff")
    combined.add_argument(
        "datasets", type=Path, help="JSON mapping symbols to base/htf/config objects"
    )
    combined.add_argument("--capital", type=float, default=1000)
    combined.add_argument(
        "--maintenance-rate", type=float, help="Flat close-mark maintenance stress rate"
    )
    combined.add_argument("--mode", choices=("cpu", "gpu", "auto"), default="auto")
    args = parser.parse_args()
    if args.command == "walk-forward":
        configs = json.loads(args.configs.read_text(encoding="utf-8-sig"))
        if not isinstance(configs, list) or any(not isinstance(item, dict) for item in configs):
            parser.error("--configs must contain an array of configuration objects")
        report = walk_forward(
            args.timeframe,
            args.base or engine.BASE_DATA_FILES[args.timeframe],
            args.htf or engine.HTF_DATA_FILES[args.timeframe],
            args.boundaries,
            configs,
            min_train_trades=args.min_trades,
            mode=args.mode,
        )
    elif args.command == "monte-carlo":
        ledger = read_ledger(args.trades)
        returns = [float(t["net_pnl"]) / float(t["equity_before"]) for t in ledger]
        report = bootstrap_trade_returns(
            returns,
            paths=args.paths,
            block_size=args.block_size,
            seed=args.seed,
            mode=args.mode,
        )
        report["trades_sha256"] = engine.sha256_file(args.trades)
    elif args.command == "portfolio-backtest":
        datasets = json.loads(args.datasets.read_text(encoding="utf-8-sig"))
        if not isinstance(datasets, dict) or any(
            not isinstance(value, dict) or not {"base", "htf"}.issubset(value)
            for value in datasets.values()
        ):
            parser.error("datasets must map symbols to base and htf paths")
        for value in datasets.values():
            for key in ("base", "htf"):
                value[key] = args.datasets.parent / value[key]
        report = portfolio_backtest(
            args.timeframe,
            datasets,
            args.cutoff,
            capital=args.capital,
            maintenance_rate=args.maintenance_rate,
            mode=args.mode,
        )
    else:
        paths = {
            symbol: args.ledgers.parent / path
            for symbol, path in json.loads(args.ledgers.read_text(encoding="utf-8-sig")).items()
        }
        report = portfolio_replay(
            {symbol: read_ledger(path) for symbol, path in paths.items()}, capital=args.capital
        )
        report["ledger_sha256"] = {
            symbol: engine.sha256_file(path) for symbol, path in paths.items()
        }
    print(json.dumps(engine.json_safe(report), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
