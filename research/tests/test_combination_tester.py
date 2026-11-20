from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH))

import strategy_analyzer as engine
import v42_exhaustive_combination_tester as tester

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_ohlcv(index: pd.DatetimeIndex, start: float = 100.0,
               step: float = 0.25) -> pd.DataFrame:
    close = start + np.arange(len(index), dtype=float) * step
    return pd.DataFrame({
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1.0,
    }, index=index)


def write_ohlcv(df: pd.DataFrame, path: Path) -> None:
    out = df.reset_index()
    time_column = out.columns[0]
    out["timestamp"] = [
        int(pd.Timestamp(value).value // 1_000_000) for value in out[time_column]
    ]
    out = out.drop(columns=[time_column])
    out[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(
        path, index=False
    )


SMALL_RANGES: dict[str, dict[str, float]] = {
    "fast_ema": {"min": 5, "max": 10, "step": 5},
    "medium_ema": {"min": 20, "max": 25, "step": 5},
    "slow_ema": {"min": 100, "max": 200, "step": 100},
    "adx_period": {"min": 7, "max": 7, "step": 1},
    "adx_min": {"min": 15, "max": 15, "step": 1},
    "atr_period": {"min": 7, "max": 7, "step": 1},
    "htf_ema": {"min": 20, "max": 20, "step": 1},
    "pullback_n": {"min": 2, "max": 2, "step": 1},
    "pullback_depth_atr": {"min": 0.0, "max": 0.0, "step": 0.1},
    "trigger_close_location": {"min": 0.55, "max": 0.55, "step": 0.05},
    "stop_buffer_atr": {"min": 0.1, "max": 0.1, "step": 0.1},
    "min_stop_atr": {"min": 0.25, "max": 0.25, "step": 0.25},
    "max_stop_atr": {"min": 1.5, "max": 1.5, "step": 0.5},
    "chandelier_atr": {"min": 1.5, "max": 1.5, "step": 0.5},
    "time_stop": {"min": 10, "max": 10, "step": 1},
}


class TempDataMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outputs = self.root / "optimization"
        self.base_path = self.root / "base.csv"
        self.htf_path = self.root / "htf.csv"
        self.write_fixture("2h")

    def tearDown(self):
        self.tmp.cleanup()

    def write_fixture(self, timeframe: str, periods: int = 60) -> None:
        frequency = {"2h": "2h", "4h": "4h", "1d": "1D"}[timeframe]
        index = pd.date_range(
            "2024-01-01", periods=periods, freq=frequency, tz="UTC",
            name="datetime",
        )
        htf_index = pd.date_range(
            "2023-09-01", periods=150, freq="1D", tz="UTC", name="datetime"
        )
        write_ohlcv(make_ohlcv(index), self.base_path)
        write_ohlcv(make_ohlcv(htf_index, start=90.0, step=0.5), self.htf_path)


def fake_report(config: dict, *, trades: int = 12,
                total_gross_R: float = 4.0,
                mode: str = "diagnostic", verified: bool = False,
                source: str = "inferred_from_final_base_candle_open",
                cutoff: str = "2024-01-03 00:00:00+00:00") -> dict:
    wins = max(1, trades // 2)
    return {
        "metrics": {
            "trades": trades,
            "wins": wins,
            "losses": trades - wins,
            "win_rate_pct": wins / trades * 100.0,
            "total_gross_R": total_gross_R,
            "net_pnl": -total_gross_R,
            "average_gross_R": total_gross_R / trades,
            "profit_factor_gross_R": 1.75,
            "compounded_equity_return_pct": 12.5,
            "max_drawdown_pct": -8.0,
            "long_trades": trades // 2,
            "short_trades": trades - trades // 2,
            "long_expectancy_gross_R": 0.2,
            "short_expectancy_gross_R": 0.1,
            "gap_uncertain_trades": 0,
        },
        "configuration": dict(config),
        "data_cutoff": cutoff,
        "data_cutoff_source": source,
        "data_cutoff_verified": verified,
        "cutoff_mode": mode,
        "base_source_sha256": "base-hash",
        "htf_source_sha256": "htf-hash",
        "engine_source_sha256": engine.engine_source_hash(),
        "engine_version": engine.ENGINE_VERSION,
        "data_processing_version": engine.DATA_PROCESSING_VERSION,
        "cost_model": engine.COST_MODEL,
        "funding_model": engine.FUNDING_MODEL,
        "market_mode": "binance_usdt_perpetual_simulation",
    }


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# 1-3. Ranges, EMA ordering, 1D cap
# ---------------------------------------------------------------------------

class RangeTests(unittest.TestCase):
    def test_inclusive_endpoint_and_integer_steps(self):
        self.assertEqual(
            tester.range_values("fast_ema", {"min": 5, "max": 40, "step": 12}),
            [5, 17, 29, 40],
        )
        self.assertEqual(
            tester.range_values("time_stop", {"min": 10, "max": 60, "step": 25}),
            [10, 35, 60],
        )

    def test_float_values_are_deduplicated_and_rounded(self):
        values = tester.range_values(
            "trigger_close_location", {"min": 0.55, "max": 0.80, "step": 0.05}
        )
        self.assertEqual(len(values), 6)
        self.assertAlmostEqual(values[0], 0.55)
        self.assertAlmostEqual(values[-1], 0.80)

    def test_invalid_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            tester.range_values("fast_ema", {"min": 5, "max": 40, "step": 0})
        with self.assertRaises(ValueError):
            tester.range_values("fast_ema", {"min": 40, "max": 5, "step": 5})
        with self.assertRaises(ValueError):
            tester.range_values("fast_ema", {"min": 1, "max": 40, "step": 5})
        with self.assertRaises(ValueError):
            tester.range_values("fast_ema", {"min": 5, "max": 40, "step": 2.5})

    def test_1d_slow_ema_is_capped_at_250(self):
        _, axes_1d = tester.build_axes("1d", tester.PARAMETER_RANGES)
        slow_1d = axes_1d[list(tester.PARAMETER_RANGES).index("slow_ema")]
        self.assertLessEqual(max(slow_1d), tester.SLOW_EMA_1D_CAP)
        self.assertIn(250, slow_1d)

        _, axes_2h = tester.build_axes("2h", tester.PARAMETER_RANGES)
        slow_2h = axes_2h[list(tester.PARAMETER_RANGES).index("slow_ema")]
        self.assertIn(365, slow_2h)

        config = tester.to_analyzer_config({
            name: (axis[0] if axis else 0)
            for name, axis in zip(tester.PARAMETER_RANGES,
                                  tester.build_axes("1d", SMALL_RANGES)[1])
        })
        config["slow_ema"] = 300
        with self.assertRaises(ValueError):
            tester.validate_candidate("1d", config)


# ---------------------------------------------------------------------------
# 4-7. Candidate validation and mapping
# ---------------------------------------------------------------------------

class CandidateValidationTests(unittest.TestCase):
    def config(self, **overrides):
        base = next(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        base.update(overrides)
        return base

    def test_invalid_ema_ordering_is_rejected(self):
        config = self.config(fast_ema=40, medium_ema=20, slow_ema=100)
        with self.assertRaises(ValueError):
            tester.validate_candidate("2h", config)

    def test_invalid_stop_ordering_is_rejected(self):
        config = self.config(min_stop_atr=2.0, max_stop_atr=1.5)
        with self.assertRaises(ValueError):
            tester.validate_candidate("2h", config)

    def test_forbidden_cost_keys_are_rejected(self):
        config = self.config()
        config["fee_pct"] = 0.001
        with self.assertRaises(ValueError):
            tester.validate_candidate("2h", config)

    def test_explicit_target_sweep_preserves_default(self):
        tester.validate_candidate("2h", self.config(target_r=3.0))
        self.assertEqual({c["target_r"] for c in tester.iter_candidates("2h", SMALL_RANGES)}, {2.0})
        with self.assertRaises(ValueError):
            list(tester.iter_candidates("2h", SMALL_RANGES, [-1.5]))

    def test_trigger_mapping_is_explicit(self):
        raw = {
            "fast_ema": 5, "medium_ema": 20, "slow_ema": 100,
            "adx_period": 7, "adx_min": 15, "atr_period": 7, "htf_ema": 20,
            "pullback_n": 2, "pullback_depth_atr": 0.0,
            "trigger_close_location": 0.65, "stop_buffer_atr": 0.1,
            "min_stop_atr": 0.25, "max_stop_atr": 1.5, "chandelier_atr": 1.5,
            "time_stop": 10, "target_r": 2.0,
        }
        config = tester.to_analyzer_config(raw)
        self.assertEqual(config["trigger_close_long"], 0.65)
        self.assertAlmostEqual(config["trigger_close_short"], 0.35)
        self.assertNotIn("trigger_close_location", config)
        self.assertNotIn("fee", config)

    def test_candidate_generation_is_deterministic_and_unique(self):
        first = list(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        second = list(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)  # 2 fast x 2 medium x 2 slow
        ids = {tester.config_id("2h", config) for config in first}
        self.assertEqual(len(ids), len(first))
        for config in first:
            self.assertLess(config["fast_ema"], config["medium_ema"])
            self.assertLess(config["medium_ema"], config["slow_ema"])

    def test_generated_config_is_a_fresh_dictionary(self):
        first = next(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        first["fast_ema"] = 999
        second = next(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        self.assertEqual(second["fast_ema"], 5)


# ---------------------------------------------------------------------------
# 8-10. Analyzer dispatch, non-mutation, strict/diagnostic semantics
# ---------------------------------------------------------------------------

class AnalyzerIntegrationTests(TempDataMixin, unittest.TestCase):
    def test_candidate_reaches_the_real_analyzer(self):
        calls = []
        original = engine.run_analysis

        def spy(**kwargs):
            calls.append({
                key: (copy.deepcopy(value) if key == "config_override" else value)
                for key, value in kwargs.items()
            })
            return original(**kwargs)

        with mock.patch.object(tester.engine, "run_analysis", side_effect=spy):
            result = tester.run_search(
                workers=1,
                timeframe="2h",
                output_root=self.outputs,
                base_path=self.base_path,
                htf_path=self.htf_path,
                cutoff_mode="diagnostic",
                max_combinations=1,
                min_trades=0,
                parameter_ranges=SMALL_RANGES,
                echo=False,
            )

        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["timeframe"], "2h")
        self.assertEqual(call["base_path"], self.base_path.resolve())
        self.assertEqual(call["htf_path"], self.htf_path.resolve())
        self.assertEqual(call["cutoff_mode"], "diagnostic")
        self.assertIsNone(call["data_cutoff"])

        row = next(iter(result["rows"].values()))
        self.assertEqual(row["status"], "ok")
        self.assertEqual(
            json.loads(row["configuration_json"]), call["config_override"]
        )
        self.assertEqual(
            row["engine_source_sha256"], engine.engine_source_hash()
        )
        self.assertTrue((Path(result["outputs"]["all_results_csv"])).is_file())

    def test_analyzer_configuration_and_baseline_are_not_mutated(self):
        baseline_before = copy.deepcopy(engine.BASELINE_CONFIGS)
        seen = []
        original = engine.run_analysis

        def spy(**kwargs):
            seen.append(copy.deepcopy(kwargs["config_override"]))
            return original(**kwargs)

        with mock.patch.object(tester.engine, "run_analysis", side_effect=spy):
            tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2, min_trades=0,
                parameter_ranges=SMALL_RANGES, echo=False,
            )

        self.assertEqual(engine.BASELINE_CONFIGS, baseline_before)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0]["fast_ema"], 999)
        for config in seen:
            self.assertEqual(
                set(config),
                {
                    "fast_ema", "medium_ema", "slow_ema", "adx_period",
                    "adx_min", "atr_period", "htf_ema", "pullback_n",
                    "pullback_depth_atr", "trigger_close_long",
                    "trigger_close_short", "stop_buffer_atr", "min_stop_atr",
                    "max_stop_atr", "chandelier_atr", "time_stop", "target_r",
                },
            )

    def test_strict_mode_requires_an_explicit_cutoff(self):
        calls = []
        with mock.patch.object(
            tester.engine, "run_analysis",
            side_effect=lambda **kwargs: calls.append(kwargs),
        ):
            with self.assertRaises(ValueError) as ctx:
                tester.run_search(
                workers=1,
                    timeframe="2h", output_root=self.outputs,
                    base_path=self.base_path, htf_path=self.htf_path,
                    cutoff_mode="strict", max_combinations=1,
                    parameter_ranges=SMALL_RANGES, echo=False,
                )
        self.assertIn("requires an explicit", str(ctx.exception))
        self.assertEqual(calls, [])
        self.assertFalse(self.outputs.exists())

    def test_strict_explicit_cutoff_is_verified(self):
        interval = engine.timeframe_interval("2h")
        base = engine.read_ohlcv(self.base_path)
        cutoff = str(base.index[-1] + interval)
        result = tester.run_search(
                workers=1,
            timeframe="2h", output_root=self.outputs,
            base_path=self.base_path, htf_path=self.htf_path,
            data_cutoff=cutoff, cutoff_mode="strict",
            max_combinations=1, min_trades=0,
            parameter_ranges=SMALL_RANGES, echo=False,
        )
        row = next(iter(result["rows"].values()))
        self.assertEqual(row["status"], "ok")
        self.assertTrue(row["data_cutoff_verified"])
        self.assertEqual(row["data_cutoff_source"], "explicit")
        self.assertEqual(row["cutoff_mode"], "strict")
        self.assertTrue(result["metadata"]["data"]["data_cutoff_verified"])

    def test_diagnostic_explicit_cutoff_stays_unverified(self):
        interval = engine.timeframe_interval("2h")
        base = engine.read_ohlcv(self.base_path)
        cutoff = str(base.index[-1] + interval)
        result = tester.run_search(
                workers=1,
            timeframe="2h", output_root=self.outputs,
            base_path=self.base_path, htf_path=self.htf_path,
            data_cutoff=cutoff, cutoff_mode="diagnostic",
            max_combinations=1, min_trades=0,
            parameter_ranges=SMALL_RANGES, echo=False,
        )
        row = next(iter(result["rows"].values()))
        self.assertEqual(row["status"], "ok")
        self.assertFalse(row["data_cutoff_verified"])
        self.assertEqual(row["data_cutoff_source"], "explicit")
        self.assertEqual(row["cutoff_mode"], "diagnostic")

    def test_diagnostic_inferred_cutoff_is_unverified(self):
        result = tester.run_search(
                workers=1,
            timeframe="2h", output_root=self.outputs,
            base_path=self.base_path, htf_path=self.htf_path,
            cutoff_mode="diagnostic", max_combinations=1, min_trades=0,
            parameter_ranges=SMALL_RANGES, echo=False,
        )
        row = next(iter(result["rows"].values()))
        self.assertFalse(row["data_cutoff_verified"])
        self.assertEqual(
            row["data_cutoff_source"], "inferred_from_final_base_candle_open"
        )
        self.assertFalse(result["metadata"]["data"]["data_cutoff_verified"])


# ---------------------------------------------------------------------------
# 11-13. Checkpoints, resume, interruption, duplicates, error logging
# ---------------------------------------------------------------------------

class CheckpointTests(TempDataMixin, unittest.TestCase):
    def fake_engine(self, calls, *, fail_first: bool = False,
                    interrupt_on: int | None = None):
        counter = {"n": 0}

        def run(**kwargs):
            counter["n"] += 1
            calls.append(copy.deepcopy(kwargs["config_override"]))
            if interrupt_on is not None and counter["n"] == interrupt_on:
                raise KeyboardInterrupt()
            if fail_first and counter["n"] == 1:
                raise RuntimeError("synthetic failure")
            config = kwargs["config_override"]
            return {"report": fake_report(
                config,
                total_gross_R=float(config["fast_ema"]),
            )}

        return run

    def test_checkpoint_and_all_outputs_are_created(self):
        calls = []
        with mock.patch.object(
            tester.engine, "run_analysis", side_effect=self.fake_engine(calls)
        ):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )

        outputs = result["outputs"]
        for key in (
            "all_results_csv", "top_configs_csv", "failed_combinations_csv",
            "run_metadata_json", "search_config_json", "config_snapshot_json",
            "checkpoint_jsonl", "log_file",
        ):
            self.assertTrue(Path(outputs[key]).is_file(), key)
        checkpoint = Path(outputs["checkpoint_jsonl"])
        self.assertEqual(len(checkpoint.read_text().strip().splitlines()), 2)
        self.assertEqual(len(read_csv_rows(Path(outputs["all_results_csv"]))), 2)
        metadata = json.loads(Path(outputs["run_metadata_json"]).read_text())
        self.assertEqual(metadata["checkpoint_total"], 2)
        self.assertEqual(metadata["newly_evaluated"], 2)

    def test_resume_does_not_repeat_completed_combinations(self):
        calls: list[dict] = []
        fake = self.fake_engine(calls)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=fake):
            first = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )
            self.assertEqual(len(calls), 2)
            second = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
                resume=True,
            )

        self.assertEqual(len(calls), 4)
        self.assertEqual(second["metadata"]["skipped_completed"], 2)
        self.assertEqual(second["metadata"]["checkpoint_total"], 4)
        self.assertEqual(
            first["search_id"], second["search_id"]
        )
        rows = read_csv_rows(Path(second["outputs"]["all_results_csv"]))
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row["config_id"] for row in rows}), 4)

    def test_interrupted_run_preserves_completed_results(self):
        calls: list[dict] = []
        fake = self.fake_engine(calls, interrupt_on=2)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=fake):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=5,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )

        self.assertTrue(result["interrupted"])
        self.assertEqual(result["metadata"]["status"], "interrupted")
        self.assertEqual(len(calls), 2)
        checkpoint = Path(result["outputs"]["checkpoint_jsonl"])
        self.assertEqual(len(checkpoint.read_text().strip().splitlines()), 1)
        self.assertEqual(
            len(read_csv_rows(Path(result["outputs"]["all_results_csv"]))), 1
        )

        # The interrupted candidate was never checkpointed, so a resume retries
        # it without repeating the completed one.
        calls.clear()
        fake = self.fake_engine(calls)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=fake):
            resumed = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=5,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
                resume=True,
            )
        self.assertEqual(resumed["metadata"]["skipped_completed"], 1)
        self.assertEqual(resumed["metadata"]["newly_evaluated"], 5)
        self.assertEqual(resumed["metadata"]["checkpoint_total"], 6)
        self.assertEqual(len(calls), 5)

    def test_retry_failed_retries_previous_errors(self):
        calls: list[dict] = []
        failing = self.fake_engine(calls, fail_first=True)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=failing):
            first = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=1,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )
        self.assertEqual(first["metadata"]["error_count"], 1)

        calls.clear()
        succeeding = self.fake_engine(calls)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=succeeding):
            second = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=1,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
                resume=True, retry_failed=True,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(second["metadata"]["checkpoint_total"], 1)
        self.assertEqual(second["metadata"]["ok_count"], 1)
        self.assertEqual(second["metadata"]["error_count"], 0)
        rows = read_csv_rows(Path(second["outputs"]["all_results_csv"]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(
            read_csv_rows(Path(second["outputs"]["failed_combinations_csv"])), []
        )

    def test_duplicate_candidates_are_not_evaluated_twice(self):
        candidates = list(tester.iter_candidates("2h", SMALL_RANGES, [2.0]))
        calls: list[dict] = []

        def duplicate_stream(*_args, **_kwargs):
            yield candidates[0]
            yield copy.deepcopy(candidates[0])
            yield candidates[1]

        with mock.patch.object(tester, "iter_candidates", side_effect=duplicate_stream):
            with mock.patch.object(
                tester.engine, "run_analysis",
                side_effect=self.fake_engine(calls),
            ):
                result = tester.run_search(
                workers=1,
                    timeframe="2h", output_root=self.outputs,
                    base_path=self.base_path, htf_path=self.htf_path,
                    cutoff_mode="diagnostic", max_combinations=10,
                    min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
                )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["metadata"]["duplicate_skipped"], 1)
        self.assertEqual(result["metadata"]["checkpoint_total"], 2)

    def test_errors_are_logged_and_do_not_abort_the_search(self):
        calls: list[dict] = []
        fake = self.fake_engine(calls, fail_first=True)
        with mock.patch.object(tester.engine, "run_analysis", side_effect=fake):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )

        self.assertEqual(len(calls), 2)
        metadata = result["metadata"]
        self.assertEqual(metadata["ok_count"], 1)
        self.assertEqual(metadata["error_count"], 1)
        failed = read_csv_rows(Path(result["outputs"]["failed_combinations_csv"]))
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["status"], "error")
        self.assertEqual(failed[0]["error_type"], "RuntimeError")
        self.assertIn("synthetic failure", failed[0]["error"])
        self.assertTrue(failed[0]["traceback"])
        log_text = Path(result["outputs"]["log_file"]).read_text()
        self.assertIn("synthetic failure", log_text)


# ---------------------------------------------------------------------------
# 14-16. Ranking, per-timeframe storage, gross-only accounting, provenance
# ---------------------------------------------------------------------------

class ReportingTests(TempDataMixin, unittest.TestCase):
    def fake_engine(self, calls):
        def run(**kwargs):
            calls.append(copy.deepcopy(kwargs["config_override"]))
            config = kwargs["config_override"]
            return {"report": fake_report(
                config, total_gross_R=float(config["fast_ema"]),
            )}
        return run

    def test_insufficient_trade_configs_are_not_ranked(self):
        calls: list[dict] = []

        def run(**kwargs):
            calls.append(kwargs)
            return {"report": fake_report(
                kwargs["config_override"], trades=3, total_gross_R=99.0
            )}

        with mock.patch.object(tester.engine, "run_analysis", side_effect=run):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=2,
                min_trades=10, parameter_ranges=SMALL_RANGES, echo=False,
            )

        rows = read_csv_rows(Path(result["outputs"]["all_results_csv"]))
        self.assertTrue(all(row["insufficient_trades"] == "true" for row in rows))
        self.assertTrue(all(row["rankable"] == "false" for row in rows))
        self.assertEqual(
            read_csv_rows(Path(result["outputs"]["top_configs_csv"])), []
        )
        self.assertEqual(result["metadata"]["rankable_count"], 0)
        self.assertEqual(result["metadata"]["insufficient_trade_count"], 2)

    def test_top_configs_are_ranked_by_net_pnl(self):
        calls: list[dict] = []
        with mock.patch.object(
            tester.engine, "run_analysis", side_effect=self.fake_engine(calls)
        ):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=8,
                min_trades=1, parameter_ranges=SMALL_RANGES, echo=False,
            )

        all_rows = read_csv_rows(Path(result["outputs"]["all_results_csv"]))
        top_rows = read_csv_rows(Path(result["outputs"]["top_configs_csv"]))
        self.assertEqual(len(top_rows), len(all_rows))
        totals = [float(row["net_pnl"]) for row in top_rows]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(totals[0], max(float(r["net_pnl"]) for r in all_rows))
        self.assertEqual(result["metadata"]["rankable_count"], 8)

    def test_results_are_stored_per_timeframe(self):
        paths = {}
        for timeframe, frequency in (("2h", "2h"), ("4h", "4h")):
            index = pd.date_range(
                "2024-01-01", periods=60, freq=frequency, tz="UTC",
                name="datetime",
            )
            base = self.root / f"base_{timeframe}.csv"
            write_ohlcv(make_ohlcv(index), base)
            paths[timeframe] = base
        calls: list[dict] = []
        with mock.patch.object(
            tester.engine, "run_analysis", side_effect=self.fake_engine(calls)
        ):
            two_hour = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=paths["2h"], htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=1,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )
            four_hour = tester.run_search(
                workers=1,
                timeframe="4h", output_root=self.outputs,
                base_path=paths["4h"], htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=1,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )

        two_results = Path(two_hour["outputs"]["results_dir"])
        four_results = Path(four_hour["outputs"]["results_dir"])
        self.assertEqual(two_results.parent.name, "2h")
        self.assertEqual(two_results.parent.parent.name, "results")
        self.assertEqual(four_results.parent.name, "4h")
        self.assertEqual(four_results.parent.parent.name, "results")
        self.assertEqual(
            Path(two_hour["outputs"]["checkpoint_jsonl"]).parent.name, "2h"
        )
        self.assertEqual(
            Path(four_hour["outputs"]["checkpoint_jsonl"]).parent.name, "4h"
        )
        self.assertNotEqual(two_hour["search_id"], four_hour["search_id"])

    def test_gross_only_accounting_and_provenance_are_recorded(self):
        calls: list[dict] = []
        with mock.patch.object(
            tester.engine, "run_analysis", side_effect=self.fake_engine(calls)
        ):
            result = tester.run_search(
                workers=1,
                timeframe="2h", output_root=self.outputs,
                base_path=self.base_path, htf_path=self.htf_path,
                cutoff_mode="diagnostic", max_combinations=1,
                min_trades=0, parameter_ranges=SMALL_RANGES, echo=False,
            )

        row = read_csv_rows(Path(result["outputs"]["all_results_csv"]))[0]
        self.assertEqual(row["cost_model"], engine.COST_MODEL)
        self.assertEqual(row["funding_model"], engine.FUNDING_MODEL)
        self.assertEqual(row["market_mode"], "binance_usdt_perpetual_simulation")
        self.assertEqual(row["data_cutoff_verified"], "false")
        self.assertEqual(row["cutoff_mode"], "diagnostic")
        self.assertTrue(row["base_source_sha256"])
        self.assertTrue(row["htf_source_sha256"])
        self.assertTrue(row["engine_source_sha256"])

        for config in calls:
            self.assertFalse(
                set(config) & tester.FORBIDDEN_ANALYZER_KEYS
            )

        metadata = json.loads(
            Path(result["outputs"]["run_metadata_json"]).read_text()
        )
        self.assertFalse(metadata["accounting"]["gross_only"])
        self.assertEqual(metadata["accounting"]["cost_model"], engine.COST_MODEL)
        self.assertEqual(metadata["accounting"]["funding_model"], engine.FUNDING_MODEL)
        self.assertEqual(
            metadata["engine"]["source_sha256"], engine.engine_source_hash()
        )
        self.assertEqual(
            metadata["data"]["base_source_sha256"],
            engine.sha256_file(self.base_path),
        )
        self.assertEqual(
            metadata["data"]["htf_source_sha256"],
            engine.sha256_file(self.htf_path),
        )
        self.assertEqual(
            metadata["search_id"],
            tester.search_id_from_signature(metadata["search_signature"]),
        )

    def test_search_signature_is_deterministic_and_sensitive(self):
        policy = {
            "value": "2024-01-03 00:00:00+00:00",
            "source": "explicit",
            "verified": True,
            "mode": "strict",
        }
        kwargs = dict(
            timeframe="2h",
            parameter_ranges=SMALL_RANGES,
            target_r_values=[2.0],
            min_trades=10,
            engine_source_sha256="engine",
            base_source_sha256="base",
            htf_source_sha256="htf",
            cutoff_policy=policy,
        )
        first = tester.search_signature(**kwargs)
        second = tester.search_signature(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(
            tester.search_id_from_signature(first),
            tester.search_id_from_signature(second),
        )

        changed = dict(kwargs, min_trades=20)
        self.assertNotEqual(
            tester.search_id_from_signature(first),
            tester.search_id_from_signature(
                tester.search_signature(**changed)
            ),
        )


if __name__ == "__main__":
    unittest.main()
