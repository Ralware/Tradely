"""Independently reconcile a joint portfolio report against its candle files."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd


def reconcile(report, datasets):
    """Value each trade separately in Decimal and sum its contribution at each close."""
    start = Decimal(str(report["starting_capital"]))
    marks = {
        pd.Timestamp(row["time"]): Decimal(str(row["equity"])) for row in report["marked_equity"]
    }
    open_pnl = defaultdict(Decimal)
    settled = defaultdict(Decimal)
    largest_trade_error = Decimal(0)
    if set(datasets) != set(report["datasets"]) or any(
        t["symbol"] not in datasets for t in report["trades"]
    ):
        raise ValueError("Unexpected report symbols")
    units = {"2h": (2, "h"), "4h": (4, "h"), "1d": (1, "d")}
    cadence = pd.Timedelta(*units[report["timeframe"]])
    start_time = pd.Timestamp(report["common_evaluation_start"])
    cutoff = pd.Timestamp(report["data_cutoff"])
    for symbol in datasets:
        with Path(datasets[symbol]["base"]).open("rb") as source:
            if (
                hashlib.file_digest(source, "sha256").hexdigest()
                != report["datasets"][symbol]["base_sha256"]
            ):
                raise ValueError(f"Source hash mismatch for {symbol}")
        fills = [t for t in report["trades"] if t["symbol"] == symbol]
        with Path(datasets[symbol]["base"]).open(encoding="utf-8-sig", newline="") as handle:
            bars = {
                pd.Timestamp(int(row["timestamp"]), unit="ms", tz="UTC"): row
                for row in csv.DictReader(handle)
            }
        expected = [stamp for stamp in bars if start_time <= stamp and stamp + cadence <= cutoff]
        if list(marks) != expected:
            raise ValueError(f"Mark timestamps differ from eligible bars for {symbol}")
        for t in fills:
            entry, exit_time = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
            q, entry_px, exit_px = (
                Decimal(str(t[key])) for key in ("quantity", "entry_fill", "exit_fill")
            )
            signed = q if t["side"] == "LONG" else -q
            taker, maker = Decimal("0.0002"), Decimal("0.0005")
            entry_fee = q * entry_px * taker
            funding = Decimal(0)
            for stamp in pd.date_range(entry, exit_time, freq=report["timeframe"]):
                row = bars[stamp]
                if stamp != entry:
                    if "funding_rate" in row and "funding_open_per_unit" not in row:
                        funding += (
                            signed
                            * Decimal(row["funding_rate"] or 0)
                            * Decimal(row["funding_mark_price"] or 0)
                        )
                    else:
                        funding += signed * Decimal(row.get("funding_open_per_unit") or 0)
                if stamp < exit_time or t["exit_reason"] in (
                    "TIME_STOP",
                    "DATA_END",
                    "MAINTENANCE_CLOSE",
                ):
                    funding += signed * Decimal(row.get("funding_inside_per_unit") or 0)
                if stamp < exit_time:
                    close = Decimal(row["close"])
                    open_pnl[stamp] += (
                        signed * (close - entry_px) - entry_fee - funding - close * q * taker
                    )
            rate = maker if t["exit_reason"] in ("TARGET", "GAP_TARGET_LIMIT") else taker
            gross = signed * (exit_px - entry_px)
            exit_fee = exit_px * q * rate
            net = gross - entry_fee - funding - exit_fee
            settled[exit_time] += net
            for key, expected_value in (
                ("gross_pnl", gross),
                ("entry_fee", entry_fee),
                ("exit_fee", exit_fee),
                ("funding", funding),
                ("net_pnl", net),
            ):
                largest_trade_error = max(
                    largest_trade_error, abs(expected_value - Decimal(str(t[key])))
                )
    if (
        len(marks) != len(report["marked_equity"])
        or not marks
        or not (open_pnl.keys() | settled.keys()) <= marks.keys()
    ):
        raise ValueError("Missing or duplicated portfolio marks")
    balance = marked_peak = realized_peak = start
    marked_drawdown = realized_drawdown = Decimal(0)
    largest_mark_error = Decimal(0)
    for stamp in sorted(marks):
        balance += settled[stamp]
        marked = balance + open_pnl[stamp]
        largest_mark_error = max(largest_mark_error, abs(marked - marks[stamp]))
        marked_peak = max(marked_peak, marked)
        realized_peak = max(realized_peak, balance)
        marked_drawdown = min(marked_drawdown, 100 * (marked / marked_peak - 1))
        realized_drawdown = min(realized_drawdown, 100 * (balance / realized_peak - 1))
    ending_error = abs(balance - Decimal(str(report["ending_capital"])))
    for field, expected_value in (
        ("net_pnl", balance - start),
        ("marked_max_drawdown_pct", marked_drawdown),
        ("realized_max_drawdown_pct", realized_drawdown),
    ):
        if abs(expected_value - Decimal(str(report[field]))) > Decimal("1e-8"):
            raise ValueError(f"Portfolio reconciliation failed for {field}")
    if max(largest_trade_error, largest_mark_error, ending_error) > Decimal("1e-8"):
        raise ValueError(
            f"Ledger reconciliation failed: {largest_trade_error}, {largest_mark_error}, {ending_error}"
        )
    return {
        "checked_trades": len(report["trades"]),
        "checked_marks": len(marks),
        "max_trade_error_usdt": str(largest_trade_error),
        "max_mark_error_usdt": str(largest_mark_error),
        "ending_error_usdt": str(ending_error),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("datasets", type=Path)
    args = parser.parse_args()
    datasets = json.loads(args.datasets.read_text(encoding="utf-8-sig"))
    for dataset in datasets.values():
        dataset["base"] = args.datasets.parent / dataset["base"]
    with args.report.open("rb") as handle:
        print(json.dumps(reconcile(json.load(handle), datasets), indent=2))
