from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH))

import strategy_analyzer as engine


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


def make_htf(index: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    values = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": values,
        "high": values + 1.0,
        "low": values - 1.0,
        "close": values,
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


def full_2h_base(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="2h", inclusive="left",
                          tz="UTC", name="datetime")
    return make_ohlcv(index)


def full_daily_base(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="1D", inclusive="left",
                          tz="UTC", name="datetime")
    return make_ohlcv(index)


def daily_htf(start: str, periods: int, offset: float = 0.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="1D", tz="UTC",
                          name="datetime")
    closes = [100.0 + offset + i for i in range(periods)]
    return make_htf(index, closes)


class TempDataMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base_path = self.root / "base.csv"
        self.htf_path = self.root / "htf.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, base: pd.DataFrame, htf: pd.DataFrame) -> None:
        write_ohlcv(base, self.base_path)
        write_ohlcv(htf, self.htf_path)


# ---------------------------------------------------------------------------
# A. Missing explicit cutoff in strict mode
# ---------------------------------------------------------------------------

class StrictModeRequiresVerifiedCutoffTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        htf = daily_htf("2023-12-01", 60)
        self.write(base, htf)

    def test_strict_mode_without_cutoff_fails_clearly(self):
        output = self.root / "results"
        with self.assertRaises(ValueError) as ctx:
            engine.run_analysis("2h", self.base_path, self.htf_path,
                                output_dir=output)
        message = str(ctx.exception)
        self.assertIn("requires an independently verified data cutoff", message)
        self.assertIn("--data-cutoff", message)
        self.assertIn("not proof", message)
        self.assertFalse((output / "2h_summary.json").exists())

    def test_resolve_cutoff_does_not_silently_infer_in_strict_mode(self):
        base = engine.read_ohlcv(self.base_path)
        with self.assertRaises(ValueError):
            engine.resolve_data_cutoff(base, "2h", None, "strict")

    def test_invalid_cutoff_values_are_rejected(self):
        base = engine.read_ohlcv(self.base_path)
        with self.assertRaises(ValueError):
            engine.resolve_data_cutoff(base, "2h", "not-a-date", "strict")
        with self.assertRaises(ValueError):
            engine.resolve_data_cutoff(base, "2h", pd.NaT, "strict")

    def test_cutoff_beyond_available_data_is_rejected(self):
        base = engine.read_ohlcv(self.base_path)
        last_close = base.index[-1] + pd.Timedelta(2, unit="h")
        with self.assertRaises(ValueError) as ctx:
            engine.resolve_data_cutoff(
                base, "2h", last_close + pd.Timedelta(1, unit="s"), "strict"
            )
        self.assertIn("extends beyond", str(ctx.exception))


# ---------------------------------------------------------------------------
# B. Explicit verified cutoff
# ---------------------------------------------------------------------------

class ExplicitVerifiedCutoffTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        self.htf = daily_htf("2023-12-01", 60)
        self.write(self.base, self.htf)
        self.cutoff = self.base.index[30] + pd.Timedelta(2, unit="h")

    def test_verified_cutoff_is_accepted_and_recorded(self):
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=self.cutoff, cutoff_mode="strict",
        )
        report = result["report"]
        self.assertTrue(report["data_cutoff_verified"])
        self.assertEqual(report["data_cutoff_source"], "explicit")
        self.assertEqual(report["cutoff_mode"], "strict")
        self.assertEqual(report["data_cutoff"], str(self.cutoff))
        self.assertFalse(report["last_base_candle_included"])
        self.assertEqual(report["excluded_incomplete_candles"], 9)
        self.assertEqual(report["last_included_base_candle"],
                         str(self.base.index[30]))

    def test_only_candles_before_cutoff_reach_signals(self):
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=self.cutoff,
        )
        signals = result["signals"]
        self.assertEqual(signals.index.max(), self.base.index[30])
        self.assertEqual(len(signals), 31)
        summary = json.loads((output / "2h_summary.json").read_text())
        self.assertEqual(summary["data_cutoff"], str(self.cutoff))
        self.assertTrue(summary["data_cutoff_verified"])
        self.assertEqual(summary["htf_completion"]["cutoff_source"], "explicit")
        self.assertTrue(summary["htf_completion"]["cutoff_verified"])

    def test_cutoff_between_candle_closes_is_accepted(self):
        # A verified cutoff need not coincide with a candle close. Internal
        # helpers must not re-reject it after run_analysis truncates the frame.
        cutoff = (
            self.base.index[30]
            + pd.Timedelta(2, unit="h")
            + pd.Timedelta(30, unit="m")
        )
        output = self.root / "between_results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=cutoff, cutoff_mode="strict",
        )
        report = result["report"]
        self.assertTrue(report["data_cutoff_verified"])
        self.assertEqual(report["data_cutoff"], str(cutoff))
        self.assertEqual(report["last_included_base_candle"],
                         str(self.base.index[30]))
        self.assertEqual(report["excluded_incomplete_candles"], 9)
        self.assertEqual(result["signals"].index.max(), self.base.index[30])


# ---------------------------------------------------------------------------
# C. Partially completed final base candle
# ---------------------------------------------------------------------------

class FinalBaseCandleTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        self.base.iloc[-1, self.base.columns.get_loc("close")] = 9999.0
        self.base.iloc[-1, self.base.columns.get_loc("high")] = 10000.0
        self.htf = daily_htf("2023-12-01", 60)
        self.write(self.base, self.htf)

    def test_explicit_cutoff_excludes_final_unverified_candle(self):
        cutoff = self.base.index[-2] + pd.Timedelta(2, unit="h")
        policy = engine.resolve_data_cutoff(self.base, "2h", cutoff, "strict")
        self.assertEqual(policy["excluded_incomplete_candles"], 1)
        self.assertFalse(policy["last_base_candle_included"])
        self.assertEqual(policy["last_verified_base_candle"], self.base.index[-2])
        self.assertEqual(policy["excluded_candle_reasons"][0]["reason"],
                         "completion_after_verified_data_cutoff")

    def test_diagnostic_inferred_cutoff_excludes_final_candle(self):
        policy = engine.resolve_data_cutoff(self.base, "2h", None, "diagnostic")
        self.assertFalse(policy["verified"])
        self.assertEqual(policy["mode"], "diagnostic")
        self.assertEqual(policy["value"], self.base.index[-1])
        self.assertEqual(policy["excluded_incomplete_candles"], 1)
        self.assertFalse(policy["last_base_candle_included"])

    def test_final_candle_does_not_influence_signals_or_trades(self):
        cutoff = self.base.index[-2] + pd.Timedelta(2, unit="h")
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=cutoff,
        )
        self.assertLess(result["signals"].index.max(), self.base.index[-1])
        self.assertNotIn(9999.0, set(result["signals"]["close"]))

        trimmed_path = self.root / "trimmed.csv"
        write_ohlcv(self.base.iloc[:-1], trimmed_path)
        trimmed_output = self.root / "trimmed_results"
        trimmed = engine.run_analysis(
            "2h", trimmed_path, self.htf_path, output_dir=trimmed_output,
            data_cutoff=cutoff,
        )
        pd.testing.assert_frame_equal(result["signals"], trimmed["signals"])


# ---------------------------------------------------------------------------
# D. Inferred cutoff in diagnostic mode
# ---------------------------------------------------------------------------

class DiagnosticModeTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        self.htf = daily_htf("2023-12-01", 60)
        self.write(self.base, self.htf)

    def test_diagnostic_mode_marks_cutoff_inferred_and_warns(self):
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            cutoff_mode="diagnostic",
        )
        report = result["report"]
        self.assertFalse(report["data_cutoff_verified"])
        self.assertEqual(report["data_cutoff_source"],
                         "inferred_from_final_base_candle_open")
        self.assertEqual(report["cutoff_mode"], "diagnostic")
        self.assertIsNotNone(report["diagnostic_warning"])
        self.assertIn("NOT independently verified", report["diagnostic_warning"])
        self.assertIsNone(report["last_verified_base_candle"])
        self.assertFalse(report["last_base_candle_included"])
        self.assertEqual(report["excluded_incomplete_candles"], 1)
        self.assertEqual(report["data_cutoff"], str(self.base.index[-1]))
        self.assertEqual(result["signals"].index.max(), self.base.index[-2])

    def test_diagnostic_never_claims_verified_htf_completion(self):
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            cutoff_mode="diagnostic",
        )
        completion = result["report"]["htf_completion"]
        self.assertFalse(completion["cutoff_verified"])
        self.assertEqual(completion["cutoff_mode"], "diagnostic")
        self.assertEqual(completion["cutoff_source"],
                         "inferred_from_final_base_candle_open")

    def test_diagnostic_with_explicit_cutoff_matches_strict_behaviour(self):
        cutoff = self.base.index[-2] + pd.Timedelta(2, unit="h")
        strict = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "strict", data_cutoff=cutoff,
            cutoff_mode="strict",
        )
        diagnostic = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "diagnostic", data_cutoff=cutoff,
            cutoff_mode="diagnostic",
        )
        pd.testing.assert_frame_equal(strict["signals"], diagnostic["signals"])
        pd.testing.assert_frame_equal(
            pd.DataFrame(strict["trades"]), pd.DataFrame(diagnostic["trades"])
        )


# ---------------------------------------------------------------------------
# Verification status must follow the selected mode
# ---------------------------------------------------------------------------

class VerificationStatusTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        self.htf = daily_htf("2023-12-01", 60)
        self.write(self.base, self.htf)
        self.cutoff = self.base.index[-2] + pd.Timedelta(2, unit="h")
        self.cfg = dict(engine.BASELINE_CONFIGS["2h"])

    def test_strict_explicit_cutoff_is_verified(self):
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "strict", data_cutoff=self.cutoff,
            cutoff_mode="strict",
        )
        report = result["report"]
        self.assertEqual(report["data_cutoff_source"], "explicit")
        self.assertTrue(report["data_cutoff_verified"])
        self.assertIsNotNone(report["last_verified_base_candle"])
        self.assertIsNone(report["diagnostic_warning"])

    def test_diagnostic_inferred_cutoff_is_unverified(self):
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "diagnostic_inferred",
            cutoff_mode="diagnostic",
        )
        report = result["report"]
        self.assertEqual(report["data_cutoff_source"],
                         "inferred_from_final_base_candle_open")
        self.assertFalse(report["data_cutoff_verified"])
        self.assertIsNone(report["last_verified_base_candle"])
        self.assertIsNotNone(report["diagnostic_warning"])

    def test_diagnostic_explicit_cutoff_is_unverified_but_explicit(self):
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "diagnostic_explicit",
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
        )
        report = result["report"]
        self.assertEqual(report["data_cutoff_source"], "explicit")
        self.assertEqual(report["data_cutoff"], str(self.cutoff))
        self.assertFalse(report["data_cutoff_verified"])
        self.assertIsNone(report["last_verified_base_candle"])
        self.assertIsNotNone(report["diagnostic_warning"])

        policy = engine.resolve_data_cutoff(
            self.base, "2h", self.cutoff, "diagnostic"
        )
        self.assertEqual(policy["source"], "explicit")
        self.assertFalse(policy["verified"])

    def test_verification_metadata_is_consistent_across_outputs(self):
        output = self.root / "metrics_consistency"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
        )
        report = result["report"]
        summary = json.loads((output / "2h_summary.json").read_text())
        metrics_csv = pd.read_csv(output / "2h_metrics.csv")

        self.assertFalse(report["data_cutoff_verified"])
        self.assertFalse(summary["data_cutoff_verified"])
        self.assertFalse(bool(metrics_csv.loc[0, "data_cutoff_verified"]))
        self.assertFalse(report["metrics"]["data_cutoff_verified"])
        self.assertFalse(report["htf_completion"]["cutoff_verified"])
        self.assertFalse(report["data_cutoff_policy"]["verified"])
        self.assertEqual(report["htf_completion"]["cutoff_source"], "explicit")
        self.assertEqual(report["cutoff_mode"], "diagnostic")
        self.assertEqual(summary["cutoff_mode"], "diagnostic")

        # A strict run with the same cutoff must report the opposite status.
        strict_output = self.root / "strict_consistency"
        strict = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=strict_output,
            data_cutoff=self.cutoff, cutoff_mode="strict",
        )
        strict_summary = json.loads(
            (strict_output / "2h_summary.json").read_text()
        )
        strict_metrics = pd.read_csv(strict_output / "2h_metrics.csv")
        self.assertTrue(strict["report"]["data_cutoff_verified"])
        self.assertTrue(strict_summary["data_cutoff_verified"])
        self.assertTrue(bool(strict_metrics.loc[0, "data_cutoff_verified"]))
        self.assertTrue(strict["report"]["htf_completion"]["cutoff_verified"])

    def test_run_id_reflects_corrected_verification_status(self):
        policy_strict = engine.resolve_data_cutoff(
            self.base, "2h", self.cutoff, "strict"
        )
        policy_diagnostic = engine.resolve_data_cutoff(
            self.base, "2h", self.cutoff, "diagnostic"
        )
        strict_id = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_policy=policy_strict,
        )
        diagnostic_id = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_policy=policy_diagnostic,
        )
        self.assertNotEqual(strict_id, diagnostic_id)

        # The verified flag alone must change the identity.
        flagged_true = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
            data_cutoff_verified=True,
        )
        flagged_false = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
            data_cutoff_verified=False,
        )
        self.assertNotEqual(flagged_true, flagged_false)

        strict = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "id_strict", data_cutoff=self.cutoff,
            cutoff_mode="strict",
        )
        diagnostic = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "id_diagnostic", data_cutoff=self.cutoff,
            cutoff_mode="diagnostic",
        )
        self.assertEqual(strict["report"]["run_id"], strict_id)
        self.assertEqual(diagnostic["report"]["run_id"], diagnostic_id)
        self.assertNotEqual(
            strict["report"]["run_id"], diagnostic["report"]["run_id"]
        )


# ---------------------------------------------------------------------------
# E. Incomplete higher-timeframe candle
# ---------------------------------------------------------------------------

class IncompleteHtfCandleTests(unittest.TestCase):
    def test_htf_interval_not_fully_covered_by_base_is_not_attached(self):
        base = full_2h_base("2024-01-01 00:00", "2024-01-03 00:00")
        # Jan 2 is almost entirely missing: only its final 2H bar survives.
        keep = base.index.isin([pd.Timestamp("2024-01-02 22:00", tz="UTC")])
        not_jan2 = base.index < pd.Timestamp("2024-01-02 00:00", tz="UTC")
        base = base.loc[keep | not_jan2]
        htf_index = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-02 00:00", tz="UTC"),
        ], name="datetime")
        htf = make_htf(htf_index, [100.0, 200.0])
        cutoff = pd.Timestamp("2024-01-03 00:00", tz="UTC")
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        frame, report = engine.htf_completion_frame(
            htf, "1d", cutoff, base=base, base_timeframe="2h"
        )
        jan2 = frame.loc[pd.Timestamp("2024-01-02", tz="UTC")]
        self.assertEqual(jan2["htf_completion_status"], "INCOMPLETE")
        self.assertEqual(jan2["htf_exclusion_reason"],
                         "underlying_base_candles_missing_or_incomplete")
        self.assertAlmostEqual(
            float(merged.loc["2024-01-02 22:00", "htf_close"]), 100.0
        )
        self.assertEqual(report["complete_count"], 1)

    def test_unaligned_htf_open_is_unknown_and_not_attached(self):
        base = full_2h_base("2024-01-01 00:00", "2024-01-04 00:00")
        htf_index = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-03 12:00", tz="UTC"),
        ], name="datetime")
        htf = make_htf(htf_index, [100.0, 200.0])
        cutoff = pd.Timestamp("2024-01-04 00:00", tz="UTC")
        frame, report = engine.htf_completion_frame(
            htf, "1d", cutoff, base=base, base_timeframe="2h"
        )
        unaligned = frame.loc[pd.Timestamp("2024-01-03 12:00", tz="UTC")]
        self.assertEqual(unaligned["htf_completion_status"], "UNKNOWN")
        self.assertEqual(unaligned["htf_exclusion_reason"],
                         "open_not_aligned_to_exchange_timeframe_boundary")
        self.assertEqual(report["unknown_count"], 1)


# ---------------------------------------------------------------------------
# F. Exact boundary handling
# ---------------------------------------------------------------------------

class BoundaryTests(unittest.TestCase):
    def test_base_candle_ending_exactly_at_cutoff_is_included(self):
        index = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 21:59:59", tz="UTC"),
            pd.Timestamp("2024-01-01 22:00:00", tz="UTC"),
        ], name="datetime")
        base = make_ohlcv(index)
        cutoff = pd.Timestamp("2024-01-01 23:59:59", tz="UTC")
        policy = engine.resolve_data_cutoff(base, "2h", cutoff, "strict")
        self.assertEqual(policy["last_included_base_candle"], index[0])
        self.assertEqual(policy["excluded_incomplete_candles"], 1)

    def test_base_candle_ending_one_second_after_cutoff_is_excluded(self):
        index = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 22:00:00", tz="UTC"),
            pd.Timestamp("2024-01-01 22:00:01", tz="UTC"),
        ], name="datetime")
        base = make_ohlcv(index)
        cutoff = pd.Timestamp("2024-01-02 00:00:00", tz="UTC")
        policy = engine.resolve_data_cutoff(base, "2h", cutoff, "strict")
        self.assertEqual(policy["last_included_base_candle"], index[0])
        self.assertEqual(policy["excluded_incomplete_candles"], 1)

    def test_htf_completion_exact_boundary_convention(self):
        index = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC",
                              name="datetime")
        htf = make_htf(index, [100.0, 200.0])
        end = pd.Timestamp("2024-01-02 00:00:00", tz="UTC")

        frame, _ = engine.htf_completion_frame(htf, "1d", end)
        self.assertEqual(frame.loc[index[0], "htf_completion_status"], "COMPLETE")

        frame, _ = engine.htf_completion_frame(
            htf, "1d", end - pd.Timedelta(1, unit="s")
        )
        self.assertEqual(frame.loc[index[0], "htf_completion_status"], "INCOMPLETE")

        frame, _ = engine.htf_completion_frame(
            htf, "1d", end + pd.Timedelta(1, unit="s")
        )
        self.assertEqual(frame.loc[index[0], "htf_completion_status"], "COMPLETE")


# ---------------------------------------------------------------------------
# G. Missing base-timeframe candles
# ---------------------------------------------------------------------------

class MissingBaseCandlesTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base = full_2h_base("2024-01-01 00:00", "2024-01-03 00:00")
        self.base = self.base.drop(pd.Timestamp("2024-01-02 04:00", tz="UTC"))
        self.htf = daily_htf("2024-01-01", 4)
        self.write(self.base, self.htf)

    def test_gap_inside_htf_interval_prevents_certification(self):
        cutoff = pd.Timestamp("2024-01-03 00:00", tz="UTC")
        frame, report = engine.htf_completion_frame(
            self.htf, "1d", cutoff, base=self.base, base_timeframe="2h"
        )
        jan2 = frame.loc[pd.Timestamp("2024-01-02", tz="UTC")]
        self.assertEqual(jan2["htf_completion_status"], "INCOMPLETE")
        self.assertEqual(jan2["missing_base_candles"], 1)
        self.assertGreaterEqual(report["excluded_candle_count"], 1)

    def test_gap_reporting_is_preserved(self):
        report = engine.detect_missing_candles(self.base, "2h")
        self.assertEqual(report["missing_candle_count"], 1)
        self.assertEqual(report["gap_events"][0]["previous_candle"],
                         "2024-01-02 02:00:00+00:00")

    def test_run_summary_reports_gap_and_exclusion(self):
        output = self.root / "results"
        result = engine.run_analysis(
            "2h", self.base_path, self.htf_path, output_dir=output,
            data_cutoff=pd.Timestamp("2024-01-03 00:00", tz="UTC"),
        )
        report = result["report"]
        self.assertEqual(
            report["data_quality"]["base"]["missing_candles"]["missing_candle_count"],
            1,
        )
        self.assertGreaterEqual(
            report["htf_completion"]["excluded_candle_count"], 1
        )
        self.assertIn(report["htf_completion_status"],
                      {"INCOMPLETE_HTF_CANDLES_EXCLUDED", "NO_COMPLETE_HTF_CANDLES"})


# ---------------------------------------------------------------------------
# H. Monthly and weekly boundaries
# ---------------------------------------------------------------------------

class CalendarBoundaryTests(unittest.TestCase):
    def test_month_end_including_leap_year(self):
        self.assertEqual(
            engine.htf_period_end("2024-02-01", "1m"),
            pd.Timestamp("2024-03-01", tz="UTC"),
        )
        self.assertEqual(
            engine.htf_period_end("2023-02-01", "1m"),
            pd.Timestamp("2023-03-01", tz="UTC"),
        )
        self.assertEqual(
            engine.htf_period_end("2024-12-01", "1m"),
            pd.Timestamp("2025-01-01", tz="UTC"),
        )

    def test_monthly_and_weekly_boundary_alignment(self):
        self.assertTrue(engine.exchange_boundary_aligned(
            pd.Timestamp("2024-03-01 00:00", tz="UTC"), "1m"))
        self.assertFalse(engine.exchange_boundary_aligned(
            pd.Timestamp("2024-03-02 00:00", tz="UTC"), "1m"))
        self.assertTrue(engine.exchange_boundary_aligned(
            pd.Timestamp("2024-01-01 00:00", tz="UTC"), "1w"))
        self.assertFalse(engine.exchange_boundary_aligned(
            pd.Timestamp("2024-01-02 00:00", tz="UTC"), "1w"))
        self.assertFalse(engine.exchange_boundary_aligned(
            pd.Timestamp("2024-01-01 01:00", tz="UTC"), "1w"))

    def test_monthly_htf_requires_full_leap_february_coverage(self):
        base = full_daily_base("2024-02-01 00:00", "2024-03-01 00:00")
        htf_index = pd.DatetimeIndex(
            [pd.Timestamp("2024-02-01 00:00", tz="UTC")], name="datetime"
        )
        htf = make_htf(htf_index, [100.0])
        cutoff = pd.Timestamp("2024-03-01 00:00", tz="UTC")
        frame, report = engine.htf_completion_frame(
            htf, "1m", cutoff, base=base, base_timeframe="1d"
        )
        self.assertEqual(frame.iloc[0]["htf_completion_status"], "COMPLETE")
        self.assertEqual(frame.iloc[0]["required_base_candles"], 29)
        self.assertEqual(report["complete_count"], 1)

        short = full_daily_base("2024-02-01 00:00", "2024-02-29 00:00")
        frame, report = engine.htf_completion_frame(
            htf, "1m", cutoff, base=short, base_timeframe="1d"
        )
        self.assertEqual(frame.iloc[0]["htf_completion_status"], "INCOMPLETE")
        self.assertEqual(frame.iloc[0]["missing_base_candles"], 1)

    def test_weekly_htf_requires_full_week_coverage(self):
        base = full_daily_base("2024-01-01 00:00", "2024-01-08 00:00")
        htf_index = pd.DatetimeIndex(
            [pd.Timestamp("2024-01-01 00:00", tz="UTC")], name="datetime"
        )
        htf = make_htf(htf_index, [100.0])
        cutoff = pd.Timestamp("2024-01-08 00:00", tz="UTC")
        frame, _ = engine.htf_completion_frame(
            htf, "1w", cutoff, base=base, base_timeframe="1d"
        )
        self.assertEqual(frame.iloc[0]["htf_completion_status"], "COMPLETE")
        self.assertEqual(frame.iloc[0]["required_base_candles"], 7)

        short = base.drop(pd.Timestamp("2024-01-03", tz="UTC"))
        frame, _ = engine.htf_completion_frame(
            htf, "1w", cutoff, base=short, base_timeframe="1d"
        )
        self.assertEqual(frame.iloc[0]["htf_completion_status"], "INCOMPLETE")

    def test_timezone_normalization(self):
        cutoff = engine.as_utc_timestamp(
            "2024-03-01T00:00:00+01:00", "data cutoff"
        )
        self.assertEqual(cutoff, pd.Timestamp("2024-02-29 23:00", tz="UTC"))
        base = full_daily_base("2024-02-01 00:00", "2024-03-01 00:00")
        htf_index = pd.DatetimeIndex(
            [pd.Timestamp("2024-02-01 00:00", tz="UTC")], name="datetime"
        )
        htf = make_htf(htf_index, [100.0])
        frame, _ = engine.htf_completion_frame(
            htf, "1m", cutoff, base=base, base_timeframe="1d"
        )
        self.assertEqual(frame.iloc[0]["htf_completion_status"], "INCOMPLETE")


# ---------------------------------------------------------------------------
# I. Run ID integrity
# ---------------------------------------------------------------------------

class RunIdCutoffTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        base = full_2h_base("2024-01-01 00:00", "2024-01-04 08:00")
        htf = daily_htf("2023-12-01", 60)
        self.write(base, htf)
        self.cfg = dict(engine.BASELINE_CONFIGS["2h"])
        self.cutoff = engine.read_ohlcv(self.base_path).index[20] + pd.Timedelta(2, unit="h")

    def test_different_cutoff_timestamps_change_run_id(self):
        first = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff,
        )
        second = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff + pd.Timedelta(2, unit="h"),
        )
        self.assertNotEqual(first, second)

    def test_verified_and_inferred_policies_change_run_id(self):
        verified = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="strict",
            data_cutoff_verified=True,
        )
        inferred = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
            data_cutoff_verified=False,
        )
        self.assertNotEqual(verified, inferred)

    def test_strict_and_diagnostic_modes_change_run_id(self):
        strict = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="strict",
            data_cutoff_verified=True,
        )
        diagnostic = engine.compute_run_id(
            "2h", self.cfg, self.base_path, self.htf_path,
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
            data_cutoff_verified=True,
        )
        self.assertNotEqual(strict, diagnostic)

    def test_run_analysis_ids_reflect_policy(self):
        cutoff = engine.read_ohlcv(self.base_path).index[-2] + pd.Timedelta(2, unit="h")
        strict = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "strict", data_cutoff=cutoff,
            cutoff_mode="strict",
        )
        diagnostic = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "diagnostic", cutoff_mode="diagnostic",
        )
        self.assertNotEqual(strict["report"]["run_id"],
                            diagnostic["report"]["run_id"])


# ---------------------------------------------------------------------------
# J. No strategy regression on fully verified data
# ---------------------------------------------------------------------------

def strategy_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    # 266 complete days of contiguous 2H base data (3192 bars), ending exactly
    # at a daily boundary, with matching daily HTF coverage and no gaps.
    index = pd.date_range("2023-01-01", periods=3192, freq="2h", tz="UTC",
                          name="datetime")
    i = np.arange(len(index), dtype=float)
    close = 120.0 + 18.0 * np.sin(i / 45.0) + 0.012 * i
    base = pd.DataFrame({
        "open": close,
        "high": close + 1.6,
        "low": close - 1.6,
        "close": close,
        "volume": 1.0,
    }, index=index)
    htf_index = pd.date_range("2023-01-01", periods=266, freq="1D", tz="UTC",
                              name="datetime")
    j = np.arange(len(htf_index), dtype=float)
    htf_close = 110.0 + 12.0 * np.sin(j / 30.0) + 0.03 * j
    htf = pd.DataFrame({
        "open": htf_close,
        "high": htf_close + 2.0,
        "low": htf_close - 2.0,
        "close": htf_close,
        "volume": 1.0,
    }, index=htf_index)
    return base, htf


class NoStrategyRegressionTests(TempDataMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.base, self.htf = strategy_fixture()
        self.write(self.base, self.htf)
        self.cutoff = self.base.index[-1] + pd.Timedelta(2, unit="h")

    def test_complete_data_is_fully_certified(self):
        policy = engine.resolve_data_cutoff(
            self.base, "2h", self.cutoff, "strict"
        )
        self.assertTrue(policy["verified"])
        self.assertEqual(policy["excluded_incomplete_candles"], 0)
        self.assertTrue(policy["last_base_candle_included"])
        _, completion = engine.htf_completion_frame(
            self.htf, "1d", self.cutoff,
            base=self.base, base_timeframe="2h",
        )
        self.assertEqual(completion["incomplete_count"], 0)
        self.assertEqual(completion["unknown_count"], 0)

    def test_policy_modes_do_not_change_strategy_results(self):
        strict = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "strict", data_cutoff=self.cutoff,
            cutoff_mode="strict",
        )
        diagnostic = engine.run_analysis(
            "2h", self.base_path, self.htf_path,
            output_dir=self.root / "diagnostic", data_cutoff=self.cutoff,
            cutoff_mode="diagnostic",
        )
        pd.testing.assert_frame_equal(strict["signals"], diagnostic["signals"])
        strict_trades = pd.DataFrame(strict["trades"])
        diagnostic_trades = pd.DataFrame(diagnostic["trades"])
        pd.testing.assert_frame_equal(strict_trades, diagnostic_trades)
        self.assertEqual(strict["report"]["metrics"]["trades"],
                         diagnostic["report"]["metrics"]["trades"])
        self.assertEqual(strict["report"]["metrics"]["total_gross_R"],
                         diagnostic["report"]["metrics"]["total_gross_R"])
        self.assertEqual(strict["report"]["metrics"]["max_drawdown_pct"],
                         diagnostic["report"]["metrics"]["max_drawdown_pct"])

    def test_indicator_values_are_unchanged_by_cutoff_policy(self):
        strict = engine.build_signals(
            self.base, self.htf, engine.BASELINE_CONFIGS["2h"], "2h",
            engine.check_convergence(
                self.base, self.htf, engine.BASELINE_CONFIGS["2h"], "2h",
                data_cutoff=self.cutoff,
            ),
            data_cutoff=self.cutoff,
        )
        diagnostic = engine.build_signals(
            self.base, self.htf, engine.BASELINE_CONFIGS["2h"], "2h",
            engine.check_convergence(
                self.base, self.htf, engine.BASELINE_CONFIGS["2h"], "2h",
                data_cutoff=self.cutoff, cutoff_mode="diagnostic",
            ),
            data_cutoff=self.cutoff, cutoff_mode="diagnostic",
        )
        indicator_columns = [
            "ema_fast", "ema_mid", "ema_slow", "atr", "adx",
            "plus_di", "minus_di", "htf_close", "htf_ema",
        ]
        pd.testing.assert_frame_equal(
            strict[indicator_columns], diagnostic[indicator_columns]
        )
        pd.testing.assert_series_equal(strict["signal"], diagnostic["signal"])
        pd.testing.assert_series_equal(
            strict["wait_reason"], diagnostic["wait_reason"]
        )


if __name__ == "__main__":
    unittest.main()
