"""Check a completed CPU sweep against its parameters and durable export."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import v42_exhaustive_combination_tester as tester


def verify(run_dir: Path, expected: int):
    manifest = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    if (
        manifest["status"] != "complete"
        or manifest["ok_count"] != expected
        or manifest["error_count"]
    ):
        raise ValueError("Sweep has missing or failed configurations")
    snapshot = manifest["search_signature"]
    timeframe = manifest["timeframe"]
    ids = {
        tester.config_id(timeframe, config)
        for config in tester.iter_candidates(
            timeframe,
            manifest["parameter_ranges"],
            snapshot["target_r_values"],
        )
    }
    if len(ids) != expected:
        raise ValueError("Grid size does not match the expected count")
    all_results = run_dir / "all_results.csv"
    total_trades = 0
    max_residual = 0.0
    checkpoint_ids = set()
    rankable = []
    with all_results.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            cid = row["config_id"]
            ids.remove(cid)
            if row["status"] != "ok" or row["active_backend"] != "cpu":
                raise ValueError(f"{cid}: expected successful CPU result")
            record = run_dir / "records" / cid[:2] / f"{cid}.json"
            persisted = json.loads(record.read_text(encoding="utf-8"))
            for field, value in row.items():
                if value != str(tester._csv_value(persisted.get(field))):
                    raise ValueError(f"{cid}: checkpoint differs from CSV in {field}")
            config = json.loads(row["configuration_json"])
            if tester.config_id(timeframe, config) != cid:
                raise ValueError(f"{cid}: configuration identity differs")
            amounts = {
                k: float(row[k])
                for k in (
                    "net_pnl",
                    "gross_pnl",
                    "total_fees",
                    "total_slippage",
                    "total_funding",
                    "total_maker_fees",
                    "total_taker_fees",
                    "net_return_pct",
                    "starting_equity_usdt",
                    "maker_rate",
                    "taker_rate",
                    "slippage_rate",
                )
            }
            if not all(map(math.isfinite, amounts.values())):
                raise ValueError(f"{cid}: non-finite accounting values")
            residual = abs(
                amounts["net_pnl"]
                - (
                    amounts["gross_pnl"]
                    - amounts["total_fees"]
                    - amounts["total_funding"]
                    - amounts["total_slippage"]
                )
            )
            if (
                residual > 1e-8
                or not math.isclose(
                    amounts["total_fees"],
                    amounts["total_maker_fees"] + amounts["total_taker_fees"],
                    rel_tol=1e-12,
                    abs_tol=1e-10,
                )
                or not math.isclose(
                    amounts["net_return_pct"],
                    100 * amounts["net_pnl"] / amounts["starting_equity_usdt"],
                    rel_tol=1e-12,
                    abs_tol=1e-10,
                )
                or (
                    amounts["maker_rate"],
                    amounts["taker_rate"],
                    amounts["slippage_rate"],
                    amounts["total_slippage"],
                    amounts["starting_equity_usdt"],
                )
                != (0.0005, 0.0002, 0, 0, 1000)
            ):
                raise ValueError(f"{cid}: net accounting does not reconcile")
            for key in ("base_source_sha256", "htf_source_sha256", "engine_source_sha256"):
                if row[key] != snapshot[key]:
                    raise ValueError(f"{cid}: provenance differs for {key}")
            if row["funding_model"] != "HISTORICAL_SETTLEMENTS":
                raise ValueError(f"{cid}: expected historical funding")
            max_residual = max(max_residual, residual)
            total_trades += int(row["trades"])
            checkpoint_ids.add(cid)
            if row["rankable"] == "true":
                rankable.append((amounts["net_pnl"], float(row["max_drawdown_pct"]), cid))
    if ids or {path.stem for path in (run_dir / "records").glob("*/*.json")} != checkpoint_ids:
        raise ValueError("CSV coverage differs from grid or checkpoint")
    if manifest["rank_by"] != "net_pnl":
        raise ValueError("This sweep verifier expects net PnL ranking")
    with (run_dir / "top_configs.csv").open(encoding="utf-8", newline="") as handle:
        top_ids = [row["config_id"] for row in csv.DictReader(handle)]
    expected_top = [cid for _, _, cid in sorted(rankable, reverse=True)[: manifest["top_n"]]]
    if top_ids != expected_top or len(rankable) != manifest["rankable_count"]:
        raise ValueError("Leaderboard does not reconcile to net PnL")
    jsonl = run_dir.parents[2] / "checkpoints" / timeframe / f"{manifest['search_id']}.jsonl"
    with jsonl.open(encoding="utf-8") as handle:
        for line in handle:
            checkpoint_ids.remove(json.loads(line)["config_id"])
    if checkpoint_ids:
        raise ValueError("JSONL checkpoint is missing configurations")
    with all_results.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "search_id": manifest["search_id"],
        "configs_verified": expected,
        "completed_trades": total_trades,
        "elapsed_seconds": manifest["elapsed_seconds"],
        "configurations_per_second": expected / manifest["elapsed_seconds"],
        "workers": manifest["workers"],
        "batch_size": manifest["batch_size"],
        "rankable_count": manifest["rankable_count"],
        "best_rankable": manifest["best_rankable"],
        "max_net_pnl_residual_usdt": max_residual,
        "all_results_sha256": digest,
        "search_signature": snapshot,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--count", type=int, default=45000)
    args = parser.parse_args()
    print(json.dumps(verify(args.run_directory, args.count), indent=2, allow_nan=False))
