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
# Helpers
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


def make_signal_frame(side: str = "LONG", entry: float = 100.0,
                      stop: float = 95.0, second_open: float = 100.0,
                      second_high: float = 101.0, second_low: float = 99.0,
                      second_close: float = 100.0,
                      bars: int = 4) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=bars, freq="2h", tz="UTC",
                        name="datetime")
    frame = pd.DataFrame({
        "open": [100.0, entry] + [100.0] * (bars - 2),
        "high": [101.0, 101.0] + [101.0] * (bars - 2),
        "low": [99.0, 99.0] + [99.0] * (bars - 2),
        "close": [100.0, 100.0] + [100.0] * (bars - 2),
        "atr": [2.0] * bars,
        "adx": [25.0] * bars,
        "signal": [side] + ["WAIT"] * (bars - 1),
        "long_stop": [stop] + [np.nan] * (bars - 1),
        "short_stop": [105.0] + [np.nan] * (bars - 1),
        "long_stop_distance_atr_signal": [2.5] * bars,
        "short_stop_distance_atr_signal": [2.5] * bars,
        "ema_fast": 100.0, "ema_mid": 99.0, "ema_slow": 95.0,
        "plus_di": 30.0, "minus_di": 10.0,
        "htf_close": 110.0, "htf_ema": 100.0,
    }, index=idx)
    if bars >= 3:
        frame.iloc[2, frame.columns.get_loc("open")] = second_open
        frame.iloc[2, frame.columns.get_loc("high")] = second_high
        frame.iloc[2, frame.columns.get_loc("low")] = second_low
        frame.iloc[2, frame.columns.get_loc("close")] = second_close
    return frame


# ---------------------------------------------------------------------------
# A. Higher-timeframe integrity
# ---------------------------------------------------------------------------

def full_2h_base(start: str, end: str) -> pd.DataFrame:
    """Contiguous 2H base coverage for every hour in [start, end)."""
    index = pd.date_range(start, end, freq="2h", inclusive="left",
                          tz="UTC", name="datetime")
    return make_ohlcv(index)


class HigherTimeframeIntegrityTests(unittest.TestCase):
    def test_consecutive_2h_candles_use_configured_duration(self):
        htf_idx = pd.date_range("2023-12-31", periods=4, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [50.0, 100.0, 200.0, 300.0])
        base = full_2h_base("2023-12-31 00:00", "2024-01-03 00:00")
        cutoff = pd.Timestamp("2024-01-03 00:00", tz="UTC")
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        # Daily Dec 31 completes at Jan 1 00:00; Jan 1 at Jan 2 00:00;
        # Jan 2 at Jan 3 00:00.
        self.assertAlmostEqual(float(merged.loc["2023-12-31 22:00", "htf_close"]), 50.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-01 20:00", "htf_close"]), 50.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-01 22:00", "htf_close"]), 100.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-02 20:00", "htf_close"]), 100.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-02 22:00", "htf_close"]), 200.0)

    def test_missing_one_base_candle_is_not_certified_complete(self):
        # Full Jan 1 plus two isolated later candles. Jan 2's daily interval is
        # missing most of its underlying 2H candles, so it must not be attached.
        base_idx = pd.DatetimeIndex(
            list(pd.date_range("2024-01-01", periods=12, freq="2h", tz="UTC"))
            + [pd.Timestamp("2024-01-02 20:00", tz="UTC"),
               pd.Timestamp("2024-01-03 10:00", tz="UTC")],
            name="datetime",
        )
        htf_idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [100.0, 200.0, 300.0, 400.0])
        cutoff = pd.Timestamp("2024-01-03 12:00", tz="UTC")
        base = make_ohlcv(base_idx)
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        # Jan 1 is complete. Jan 2 is not, so Jan 3 10:00 must NOT see 200.
        self.assertAlmostEqual(float(merged.loc["2024-01-02 20:00", "htf_close"]), 100.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-03 10:00", "htf_close"]), 100.0)
        frame, report = engine.htf_completion_frame(
            htf, "1d", cutoff, base=base, base_timeframe="2h"
        )
        jan2 = frame.loc[pd.Timestamp("2024-01-02", tz="UTC")]
        self.assertEqual(jan2["htf_completion_status"], "INCOMPLETE")
        self.assertEqual(
            jan2["htf_exclusion_reason"],
            "underlying_base_candles_missing_or_incomplete",
        )
        self.assertGreater(report["incomplete_count"], 0)

    def test_missing_multiple_base_candles_do_not_look_ahead(self):
        base_idx = pd.DatetimeIndex(
            list(pd.date_range("2024-01-01", periods=12, freq="2h", tz="UTC"))
            + [pd.Timestamp("2024-01-04 10:00", tz="UTC")],
            name="datetime",
        )
        htf_idx = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [100.0, 200.0, 300.0, 400.0, 500.0])
        cutoff = pd.Timestamp("2024-01-04 12:00", tz="UTC")
        base = make_ohlcv(base_idx)
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        self.assertAlmostEqual(float(merged.loc["2024-01-04 10:00", "htf_close"]), 100.0)

    def test_daily_htf_candle_completing_during_base_gap(self):
        # Days 6-8 are complete; the Feb 9 candle is missing all but one bar.
        base_idx = pd.DatetimeIndex(
            list(pd.date_range("2024-02-06", "2024-02-09", freq="2h",
                               inclusive="left", tz="UTC"))
            + [pd.Timestamp("2024-02-09 10:00", tz="UTC")],
            name="datetime",
        )
        htf_idx = pd.date_range("2024-02-06", periods=4, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [100.0, 200.0, 300.0, 400.0])
        cutoff = pd.Timestamp("2024-02-09 12:00", tz="UTC")
        base = make_ohlcv(base_idx)
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        # Feb 8 00:00 closes 02:00 -> Feb 7 daily. Feb 9 10:00 closes 12:00 ->
        # Feb 8 daily completed at Feb 9 00:00 during the base-data gap.
        self.assertAlmostEqual(float(merged.loc["2024-02-08 00:00", "htf_close"]), 200.0)
        self.assertAlmostEqual(float(merged.loc["2024-02-09 10:00", "htf_close"]), 300.0)
        frame, _ = engine.htf_completion_frame(
            htf, "1d", cutoff, base=base, base_timeframe="2h"
        )
        feb9 = frame.loc[pd.Timestamp("2024-02-09", tz="UTC")]
        self.assertEqual(feb9["htf_completion_status"], "INCOMPLETE")

    def test_base_candle_immediately_before_and_after_htf_completion(self):
        base = full_2h_base("2023-12-31 00:00", "2024-01-02 02:00")
        htf_idx = pd.date_range("2023-12-31", periods=3, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [50.0, 100.0, 200.0])
        cutoff = pd.Timestamp("2024-01-02 02:00", tz="UTC")
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        self.assertAlmostEqual(float(merged.loc["2024-01-01 20:00", "htf_close"]), 50.0)
        # Decision at exactly the completion timestamp may use the candle.
        self.assertAlmostEqual(float(merged.loc["2024-01-01 22:00", "htf_close"]), 100.0)
        self.assertAlmostEqual(float(merged.loc["2024-01-02 00:00", "htf_close"]), 100.0)

    def test_final_incomplete_htf_candle_is_excluded(self):
        base = full_2h_base("2024-01-01 00:00", "2024-01-02 02:00")
        htf_idx = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [100.0, 200.0, 300.0])
        cutoff = pd.Timestamp("2024-01-02 00:00", tz="UTC")
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        _, report = engine.htf_completion_frame(
            htf, "1d", cutoff, base=base, base_timeframe="2h"
        )
        self.assertGreaterEqual(report["incomplete_count"], 2)
        # The last included base candle closes exactly at the cutoff.
        self.assertAlmostEqual(float(merged.loc["2024-01-01 22:00", "htf_close"]), 100.0)
        # The final base row completes after the cutoff and gets no attachment.
        self.assertTrue(pd.isna(merged.loc["2024-01-02 00:00", "htf_close"]))
        self.assertLessEqual(
            pd.Timestamp("2024-01-02 00:00", tz="UTC"),
            pd.Timestamp(report["last_complete_available_at"]),
        )

    def test_final_base_candle_is_handled_explicitly(self):
        base = full_2h_base("2024-01-01 00:00", "2024-01-02 02:00")
        htf_idx = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC",
                                name="datetime")
        htf = make_htf(htf_idx, [100.0, 200.0])
        cutoff = pd.Timestamp("2024-01-02 02:00", tz="UTC")
        policy = engine.resolve_data_cutoff(
            base, "2h", cutoff, engine.CUTOFF_MODE_STRICT
        )
        self.assertTrue(policy["last_base_candle_included"])
        self.assertEqual(policy["excluded_incomplete_candles"], 0)
        merged = engine.attach_htf_indicators(
            base, htf, 1, timeframe="2h", htf_timeframe="1d",
            data_cutoff=cutoff,
        )
        self.assertAlmostEqual(float(merged.iloc[-1]["htf_close"]), 100.0)

    def test_indicator_snapshot_handles_final_base_candle(self):
        base_idx = pd.date_range("2024-01-01", periods=1300, freq="2h",
                                 tz="UTC", name="datetime")
        base = make_ohlcv(base_idx, step=0.05)
        htf_idx = pd.date_range("2023-01-01", periods=500, freq="1D",
                                tz="UTC", name="datetime")
        htf = make_htf(htf_idx, list(np.linspace(100.0, 600.0, 500)))
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        snapshot = engine.indicator_snapshot(
            base, htf, cfg, len(base) - 1, "2h",
            data_cutoff=base_idx[-1] + pd.Timedelta(2, unit="h"),
        )
        self.assertTrue(snapshot)
        self.assertTrue(np.isfinite(snapshot["htf_ema"]))
        self.assertTrue(np.isfinite(snapshot["ema_fast"]))


# ---------------------------------------------------------------------------
# B. Trade execution
# ---------------------------------------------------------------------------

class TradeExecutionTests(unittest.TestCase):
    def run_trade(self, **kwargs):
        frame = make_signal_frame(**kwargs)
        trades, audit = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(len(trades), 1)
        return trades[0], audit[0]

    def test_gap_through_initial_stop(self):
        trade, audit = self.run_trade(second_open=90.0, second_high=130.0,
                                      second_low=89.0, second_close=125.0)
        self.assertEqual(trade["exit_reason"], "GAP_STOP")
        self.assertEqual(trade["exit_fill"], 90.0)
        self.assertEqual(trade["exit_stop_type"], "INITIAL_STOP")
        self.assertEqual(audit["per_bar_state"][-1]["exit_stop_type"],
                         "INITIAL_STOP")

    def test_gap_through_trailing_stop(self):
        frame = make_signal_frame(second_open=101.0, second_high=101.0,
                                  second_low=100.0, second_close=101.0)
        # Entry candle raises the chandelier stop to 108 - 3*2 = 102.
        frame.iloc[1, frame.columns.get_loc("high")] = 108.0
        frame.iloc[1, frame.columns.get_loc("close")] = 107.0
        trades, audit = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(trades[0]["exit_reason"], "GAP_STOP")
        self.assertEqual(trades[0]["exit_fill"], 101.0)
        self.assertEqual(trades[0]["exit_stop_type"], "TRAILING_STOP")
        self.assertEqual(audit[0]["per_bar_state"][-1]["exit_stop_type"],
                         "TRAILING_STOP")

    def test_gap_through_target(self):
        trade, _ = self.run_trade(second_open=115.0, second_high=140.0,
                                  second_low=114.0, second_close=120.0)
        self.assertEqual(trade["exit_reason"], "GAP_TARGET_LIMIT")
        self.assertEqual(trade["exit_fill"], 110.0)
        self.assertTrue(trade["target_gap_flag"])

    def test_intrabar_initial_stop(self):
        trade, _ = self.run_trade(second_open=100.0, second_high=101.0,
                                  second_low=94.0, second_close=96.0)
        self.assertEqual(trade["exit_reason"], "INITIAL_STOP")
        self.assertEqual(trade["exit_fill"], 95.0)

    def test_intrabar_target(self):
        trade, _ = self.run_trade(second_open=100.0, second_high=111.0,
                                  second_low=99.0, second_close=109.0)
        self.assertEqual(trade["exit_reason"], "TARGET")
        self.assertEqual(trade["exit_fill"], 110.0)

    def test_intrabar_trailing_stop(self):
        frame = make_signal_frame(second_open=104.0, second_high=104.0,
                                  second_low=98.0, second_close=99.0)
        frame.iloc[1, frame.columns.get_loc("high")] = 105.0
        frame.iloc[1, frame.columns.get_loc("close")] = 104.0
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(trades[0]["exit_reason"], "TRAILING_STOP")
        self.assertEqual(trades[0]["exit_fill"], 99.0)

    def test_same_candle_stop_and_target_stop_first(self):
        trade, _ = self.run_trade(second_open=100.0, second_high=115.0,
                                  second_low=90.0, second_close=100.0)
        self.assertEqual(trade["exit_reason"], "STOP_BOTH_TOUCHED_STOP_FIRST")
        self.assertEqual(trade["exit_fill"], 95.0)
        self.assertTrue(trade["stop_first_ambiguity"])

    def test_time_stop(self):
        frame = make_signal_frame(second_open=100.0, second_high=101.0,
                                  second_low=99.0, second_close=100.0)
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        cfg["time_stop"] = 2
        trades, _ = engine.simulate_trades(frame, cfg, "2h")
        self.assertEqual(trades[0]["exit_reason"], "TIME_STOP")
        self.assertEqual(trades[0]["exit_fill"], 100.0)

    def test_data_end_exit(self):
        frame = make_signal_frame(second_open=100.0, second_high=101.0,
                                  second_low=99.0, second_close=100.0)
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        cfg["time_stop"] = 100
        trades, _ = engine.simulate_trades(frame, cfg, "2h")
        self.assertEqual(trades[0]["exit_reason"], "DATA_END")
        self.assertEqual(trades[0]["exit_fill"], 100.0)


# ---------------------------------------------------------------------------
# C. MAE/MFE
# ---------------------------------------------------------------------------

class ExcursionTests(unittest.TestCase):
    def trade(self, side: str, **kwargs):
        frame = make_signal_frame(side=side, **kwargs)
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        return trades[0]

    def test_long_gap_stop_excludes_post_exit_rally(self):
        trade = self.trade("LONG", second_open=90.0, second_high=130.0,
                           second_low=89.0, second_close=125.0)
        self.assertEqual(trade["exit_reason"], "GAP_STOP")
        self.assertAlmostEqual(trade["mae_R"], -2.0)
        self.assertLessEqual(trade["mfe_R"], 0.2)

    def test_short_gap_stop_excludes_post_exit_decline(self):
        trade = self.trade("SHORT", second_open=110.0, second_high=111.0,
                           second_low=80.0, second_close=85.0)
        self.assertEqual(trade["exit_reason"], "GAP_STOP")
        self.assertAlmostEqual(trade["mae_R"], -2.0)
        self.assertLessEqual(trade["mfe_R"], 0.2)

    def test_long_gap_target_excludes_post_exit_reversal(self):
        trade = self.trade("LONG", second_open=115.0, second_high=140.0,
                           second_low=114.0, second_close=120.0)
        self.assertEqual(trade["exit_reason"], "GAP_TARGET_LIMIT")
        self.assertAlmostEqual(trade["mfe_R"], 2.0)
        self.assertGreaterEqual(trade["mae_R"], -0.2)

    def test_short_gap_target_excludes_post_exit_reversal(self):
        trade = self.trade("SHORT", second_open=80.0, second_high=81.0,
                           second_low=70.0, second_close=75.0)
        self.assertEqual(trade["exit_reason"], "GAP_TARGET_LIMIT")
        self.assertAlmostEqual(trade["mfe_R"], 2.0)
        self.assertGreaterEqual(trade["mae_R"], -0.2)


# ---------------------------------------------------------------------------
# D. Audit integrity
# ---------------------------------------------------------------------------

class AuditIntegrityTests(unittest.TestCase):
    def test_every_trade_has_entry_and_exit_bar_records(self):
        frame = make_signal_frame(second_open=90.0, second_high=130.0,
                                  second_low=89.0, second_close=125.0)
        trades, audit = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(len(trades), len(audit))
        for trade, record in zip(trades, audit):
            bars = record["per_bar_state"]
            self.assertTrue(bars)
            self.assertEqual(bars[0]["time"], trade["entry_time"])
            self.assertEqual(bars[0]["trade_id"], trade["trade_id"])
            self.assertTrue(bars[-1]["is_exit_candle"])
            self.assertEqual(bars[-1]["time"], trade["exit_time"])
            self.assertEqual(bars[-1]["exit_reason"], trade["exit_reason"])
            self.assertEqual(bars[-1]["exit_fill"], trade["exit_fill"])
            self.assertIn(f"EXIT:{trade['exit_reason']}", bars[-1]["exit_event_order"])

    def test_exit_reasons_match_expected_execution_paths(self):
        cases = {
            "GAP_STOP": dict(second_open=90.0, second_high=130.0,
                             second_low=89.0, second_close=125.0),
            "GAP_TARGET_LIMIT": dict(second_open=115.0, second_high=140.0,
                                     second_low=114.0, second_close=120.0),
            "INITIAL_STOP": dict(second_open=100.0, second_high=101.0,
                                 second_low=94.0, second_close=96.0),
            "TARGET": dict(second_open=100.0, second_high=111.0,
                           second_low=99.0, second_close=109.0),
            "STOP_BOTH_TOUCHED_STOP_FIRST": dict(
                second_open=100.0, second_high=115.0, second_low=90.0,
                second_close=100.0),
        }
        for expected, kwargs in cases.items():
            frame = make_signal_frame(**kwargs)
            trades, audit = engine.simulate_trades(
                frame, engine.BASELINE_CONFIGS["2h"], "2h"
            )
            self.assertEqual(trades[0]["exit_reason"], expected)
            self.assertEqual(
                audit[0]["per_bar_state"][-1]["exit_reason"], expected
            )

    def test_audit_jsonl_is_deterministic(self):
        frame = make_signal_frame(second_open=100.0, second_high=111.0,
                                  second_low=99.0, second_close=109.0)
        _, first = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h", run_id="fixed"
        )
        _, second = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h", run_id="fixed"
        )
        first_bytes = "\n".join(
            json.dumps(engine.json_safe(item), sort_keys=True, allow_nan=False)
            for item in first
        )
        second_bytes = "\n".join(
            json.dumps(engine.json_safe(item), sort_keys=True, allow_nan=False)
            for item in second
        )
        self.assertEqual(first_bytes, second_bytes)

    def test_run_analysis_audit_file_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.csv"
            htf = root / "htf.csv"
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=1400, freq="2h", tz="UTC"
            )), base)
            write_ohlcv(make_ohlcv(pd.date_range(
                "2023-01-01", periods=500, freq="1D", tz="UTC"
            )), htf)
            cutoff = engine.read_ohlcv(base).index[-1] + pd.Timedelta(2, unit="h")
            output = root / "results"
            engine.run_analysis("2h", base, htf, output_dir=output,
                                data_cutoff=cutoff)
            first = (output / "2h_trade_audit.jsonl").read_bytes()
            engine.run_analysis("2h", base, htf, output_dir=output, force=True,
                                data_cutoff=cutoff)
            second = (output / "2h_trade_audit.jsonl").read_bytes()
            self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# E. Reproducibility
# ---------------------------------------------------------------------------

class ReproducibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.base = root / "base.csv"
        self.htf = root / "htf.csv"
        write_ohlcv(make_ohlcv(pd.date_range(
            "2024-01-01", periods=40, freq="2h", tz="UTC"
        )), self.base)
        write_ohlcv(make_ohlcv(pd.date_range(
            "2024-01-01", periods=10, freq="1D", tz="UTC"
        )), self.htf)
        self.cfg = dict(engine.BASELINE_CONFIGS["2h"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_engine_configuration_and_data_same_run_id(self):
        first = engine.compute_run_id("2h", self.cfg, self.base, self.htf)
        second = engine.compute_run_id("2h", self.cfg, self.base, self.htf)
        self.assertEqual(first, second)

    def test_different_engine_hash_changes_run_id(self):
        first = engine.compute_run_id(
            "2h", self.cfg, self.base, self.htf,
            engine_source_sha256="a" * 64,
        )
        second = engine.compute_run_id(
            "2h", self.cfg, self.base, self.htf,
            engine_source_sha256="b" * 64,
        )
        self.assertNotEqual(first, second)

    def test_different_dataset_hash_changes_run_id(self):
        other = Path(self.tmp.name) / "other.csv"
        write_ohlcv(make_ohlcv(pd.date_range(
            "2024-01-01", periods=40, freq="2h", tz="UTC"
        ), start=200.0), other)
        first = engine.compute_run_id("2h", self.cfg, self.base, self.htf)
        second = engine.compute_run_id("2h", self.cfg, other, self.htf)
        self.assertNotEqual(first, second)

    def test_different_configuration_changes_run_id(self):
        changed = dict(self.cfg)
        changed["adx_min"] = changed["adx_min"] + 1
        first = engine.compute_run_id("2h", self.cfg, self.base, self.htf)
        second = engine.compute_run_id("2h", changed, self.base, self.htf)
        self.assertNotEqual(first, second)

    def test_different_execution_constraints_change_run_id(self):
        first = engine.compute_run_id("2h", self.cfg, self.base, self.htf)
        second = engine.compute_run_id(
            "2h", self.cfg, self.base, self.htf,
            execution_constraints={"min_notional": 10.0},
        )
        self.assertNotEqual(first, second)

    def test_engine_hash_is_present_in_summary_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results"
            base_frame = engine.read_ohlcv(self.base)
            cutoff = base_frame.index[-1] + pd.Timedelta(2, unit="h")
            result = engine.run_analysis(
                "2h", self.base, self.htf, output_dir=output,
                data_cutoff=cutoff,
            )
            report = result["report"]
            self.assertEqual(report["engine_source_sha256"],
                             engine.engine_source_hash())
            self.assertIn("numpy", report["imported_execution_modules"])
            self.assertIn("pandas", report["imported_execution_modules"])
            self.assertEqual(report["data_processing_version"],
                             engine.DATA_PROCESSING_VERSION)
            self.assertEqual(report["run_id"], result["trades"][0]["run_id"]
                             if result["trades"] else report["run_id"])


# ---------------------------------------------------------------------------
# F. Data gaps
# ---------------------------------------------------------------------------

class DataGapReportingTests(unittest.TestCase):
    def test_trade_spanning_gap_is_classified(self):
        idx = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-01 02:00", tz="UTC"),
            pd.Timestamp("2024-01-02 00:00", tz="UTC"),
        ], name="datetime")
        frame = make_signal_frame(bars=3)
        frame.index = idx
        gap_events = [{
            "previous_candle": str(idx[1]),
            "next_candle": str(idx[2]),
            "observed_interval": "22:00:00",
            "missing_candles": 10,
        }]
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            gap_events=gap_events,
        )
        trade = trades[0]
        self.assertTrue(trade["crosses_data_gap"])
        self.assertEqual(trade["missing_candles_crossed"], 10)
        self.assertEqual(len(trade["data_gap_intervals"]), 1)
        self.assertTrue(trade["outcome_uncertain"])
        self.assertIsNotNone(trade["outcome_uncertainty_reason"])

    def test_trade_starting_after_gap_is_unaffected(self):
        idx = pd.DatetimeIndex([
            pd.Timestamp("2024-01-02 00:00", tz="UTC"),
            pd.Timestamp("2024-01-02 02:00", tz="UTC"),
            pd.Timestamp("2024-01-02 04:00", tz="UTC"),
        ], name="datetime")
        frame = make_signal_frame(bars=3)
        frame.index = idx
        gap_events = [{
            "previous_candle": str(pd.Timestamp("2024-01-01 00:00", tz="UTC")),
            "next_candle": str(idx[0]),
            "observed_interval": "24:00:00",
            "missing_candles": 11,
        }]
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            gap_events=gap_events,
        )
        self.assertFalse(trades[0]["crosses_data_gap"])
        self.assertEqual(trades[0]["missing_candles_crossed"], 0)
        self.assertFalse(trades[0]["outcome_uncertain"])

    def test_gap_sensitivity_is_reported_without_removing_trades(self):
        idx = pd.DatetimeIndex([
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-01 02:00", tz="UTC"),
            pd.Timestamp("2024-01-02 00:00", tz="UTC"),
        ], name="datetime")
        frame = make_signal_frame(bars=3)
        frame.index = idx
        gap_events = [{
            "previous_candle": str(idx[1]),
            "next_candle": str(idx[2]),
            "observed_interval": "22:00:00",
            "missing_candles": 10,
        }]
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            gap_events=gap_events,
        )
        warmup = engine.WarmupResult(
            True, 0, 0, 0, 1, "CONVERGENCE_PASSED", {}
        )
        frame["wait_reason"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            base_path = Path(tmp) / "base.csv"
            htf_path = Path(tmp) / "htf.csv"
            write_ohlcv(make_ohlcv(frame.index), base_path)
            write_ohlcv(make_ohlcv(pd.date_range(
                "2023-01-01", periods=500, freq="1D", tz="UTC"
            )), htf_path)
            report = engine.summarize(
                "2h", frame, trades, warmup, base_path, htf_path
            )
        metrics = report["metrics"]
        self.assertEqual(metrics["trades"], 1)
        self.assertEqual(metrics["gap_affected_trades"], 1)
        self.assertEqual(metrics["gap_unaffected_trades"], 0)
        self.assertEqual(metrics["gap_uncertain_trades"], 1)
        self.assertEqual(report["gap_sensitivity"]["affected"]["trades"], 1)

    def test_detect_missing_candles(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="2h", tz="UTC")
        frame = make_ohlcv(idx).drop(idx[2])
        report = engine.detect_missing_candles(frame, "2h")
        self.assertEqual(report["missing_candle_count"], 1)
        self.assertEqual(report["gap_event_count"], 1)


# ---------------------------------------------------------------------------
# G. Position sizing
# ---------------------------------------------------------------------------

class PositionSizingTests(unittest.TestCase):
    def test_one_x_notional_cap(self):
        frame = make_signal_frame(second_open=100.0, second_high=101.0,
                                  second_low=99.0, second_close=100.0)
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        cfg["risk_pct"] = 0.5
        trades, _ = engine.simulate_trades(frame, cfg, "2h")
        trade = trades[0]
        self.assertTrue(trade["notional_capped"])
        self.assertLessEqual(trade["notional_at_entry"],
                             engine.STARTING_EQUITY_USDT * engine.LEVERAGE_CAP + 1e-9)
        self.assertAlmostEqual(trade["actual_initial_risk"],
                               trade["quantity"] * (trade["entry_fill"] - trade["initial_stop"]))

    def test_min_quantity_rejection_reason(self):
        frame = make_signal_frame()
        rejections: list[dict] = []
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            execution_constraints={"min_quantity": 1_000_000.0},
            rejection_log=rejections,
        )
        self.assertEqual(trades, [])
        self.assertEqual(rejections[0]["reason"], "BELOW_MIN_QUANTITY")

    def test_min_notional_rejection_reason(self):
        frame = make_signal_frame()
        rejections: list[dict] = []
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            execution_constraints={"min_notional": 1_000_000.0},
            rejection_log=rejections,
        )
        self.assertEqual(trades, [])
        self.assertEqual(rejections[0]["reason"], "BELOW_MIN_NOTIONAL")

    def test_quantity_precision_is_applied_to_actual_risk(self):
        frame = make_signal_frame()
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        cfg["risk_pct"] = 0.0123  # 24.6 units before precision
        trades, _ = engine.simulate_trades(
            frame, cfg, "2h",
            execution_constraints={"quantity_precision": 0},
        )
        trade = trades[0]
        self.assertEqual(trade["quantity"], 24.0)
        self.assertTrue(trade["quantity_precision_applied"])
        self.assertAlmostEqual(trade["actual_initial_risk"],
                               trade["quantity"] * 5.0)

    def test_constraints_are_disabled_by_default(self):
        frame = make_signal_frame()
        rejections: list[dict] = []
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h",
            rejection_log=rejections,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(rejections, [])
        self.assertFalse(trades[0]["quantity_precision_applied"])


if __name__ == "__main__":
    unittest.main()
