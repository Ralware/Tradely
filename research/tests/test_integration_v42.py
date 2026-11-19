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


def write_ohlcv(df: pd.DataFrame, path: Path, timestamp_divisor: int = 1_000_000) -> None:
    out = df.reset_index()
    time_column = out.columns[0]
    out["timestamp"] = [
        int(pd.Timestamp(value).value // timestamp_divisor)
        for value in out[time_column]
    ]
    out = out.drop(columns=[time_column])
    out[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(
        path, index=False
    )


def make_signal_frame(side: str = "LONG", entry: float = 100.0,
                      stop: float = 95.0, target_high: float = 111.0,
                      target_low: float = 99.0,
                      second_open: float | None = None,
                      second_high: float = 101.0,
                      second_low: float = 99.0,
                      second_close: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="2h", tz="UTC", name="datetime")
    frame = pd.DataFrame({
        "open": [100.0, entry, second_open if second_open is not None else 100.0, 100.0],
        "high": [101.0, 101.0, target_high, 101.0],
        "low": [99.0, 99.0, target_low, 99.0],
        "close": [100.0, 100.0, second_close, 100.0],
        "atr": [2.0, 2.0, 2.0, 2.0],
        "adx": [25.0, 25.0, 25.0, 25.0],
        "signal": [side, "WAIT", "WAIT", "WAIT"],
        "long_stop": [stop, np.nan, np.nan, np.nan],
        "short_stop": [105.0, np.nan, np.nan, np.nan],
        "long_stop_distance_atr_signal": [2.5, np.nan, np.nan, np.nan],
        "short_stop_distance_atr_signal": [2.5, np.nan, np.nan, np.nan],
        "ema_fast": 100.0, "ema_mid": 99.0, "ema_slow": 95.0,
        "plus_di": 30.0, "minus_di": 10.0,
        "htf_close": 110.0, "htf_ema": 100.0,
    }, index=idx)
    if second_open is not None:
        frame.iloc[2, frame.columns.get_loc("open")] = second_open
    frame.iloc[2, frame.columns.get_loc("high")] = max(target_high, second_high)
    frame.iloc[2, frame.columns.get_loc("low")] = min(target_low, second_low)
    frame.iloc[2, frame.columns.get_loc("close")] = second_close
    return frame


class ConfigurationTests(unittest.TestCase):
    def test_supported_timeframes_use_existing_data_directory(self):
        data_dir = engine.DATA_DIRECTORY
        self.assertEqual(engine.BASE_DATA_FILES["2h"], data_dir / "BTCUSDT_2hours.csv")
        self.assertEqual(engine.HTF_DATA_FILES["2h"], data_dir / "BTCUSDT_1day.csv")
        self.assertEqual(engine.BASE_DATA_FILES["4h"], data_dir / "BTCUSDT_4hours.csv")
        self.assertEqual(engine.HTF_DATA_FILES["4h"], data_dir / "BTCUSDT_1day.csv")
        self.assertEqual(engine.BASE_DATA_FILES["1d"], data_dir / "BTCUSDT_1day.csv")
        self.assertEqual(engine.HTF_DATA_FILES["1d"], data_dir / "BTCUSDT_1week.csv")

    def test_default_output_is_per_timeframe(self):
        self.assertEqual(
            engine.default_output_directory("2h"),
            engine.OUTPUT_DIRECTORY / "2h",
        )
        self.assertEqual(
            set(engine.result_paths(Path("x"), "4h")),
            {"signals", "trades", "audit", "summary", "metrics"},
        )

    def test_run_id_is_deterministic_and_timeframe_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.csv"
            htf = root / "htf.csv"
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=10, freq="2h", tz="UTC"
            )), base)
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=10, freq="1D", tz="UTC"
            )), htf)
            cfg_2h = dict(engine.BASELINE_CONFIGS["2h"])
            cfg_4h = dict(engine.BASELINE_CONFIGS["4h"])
            first = engine.compute_run_id("2h", cfg_2h, base, htf)
            second = engine.compute_run_id("2h", cfg_2h, base, htf)
            other = engine.compute_run_id("4h", cfg_4h, base, htf)
            self.assertEqual(first, second)
            self.assertNotEqual(first, other)


class DataQualityTests(unittest.TestCase):
    def test_microsecond_and_second_timestamps_are_detected(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="2h", tz="UTC")
        for divisor, expected_unit in ((1_000, "us"), (1_000_000_000, "s")):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"bars_{expected_unit}.csv"
                write_ohlcv(make_ohlcv(idx), path, timestamp_divisor=divisor)
                frame = engine.read_ohlcv(path)
                self.assertEqual(str(frame.index.tz), "UTC")
                self.assertEqual(frame.attrs["data_quality"]["timestamp_unit"], expected_unit)
                self.assertEqual(len(frame), 2)

    def test_duplicate_timestamps_are_removed_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dupes.csv"
            pd.DataFrame({
                "timestamp": [1700000000000, 1700000000000, 1700007200000],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1.0, 2.0, 3.0],
            }).to_csv(path, index=False)
            frame = engine.read_ohlcv(path)
            self.assertEqual(len(frame), 2)
            self.assertEqual(frame.attrs["data_quality"]["duplicate_timestamps_removed"], 1)
            self.assertAlmostEqual(float(frame.iloc[0]["close"]), 101.5)

    def test_missing_candles_are_reported_without_fabrication(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="2h", tz="UTC", name="datetime")
        frame = make_ohlcv(idx)
        frame = frame.drop(frame.index[2])
        report = engine.detect_missing_candles(frame, "2h")
        self.assertEqual(len(frame), 5)
        self.assertEqual(report["missing_candle_count"], 1)
        self.assertEqual(report["gap_event_count"], 1)
        self.assertEqual(report["gap_events"][0]["missing_candles"], 1)

    def test_only_completed_higher_timeframe_candles_are_attached(self):
        htf_index = pd.date_range(
            "2024-01-01", periods=4, freq="1D", tz="UTC", name="datetime"
        )
        htf = pd.DataFrame({
            "open": [100.0, 200.0, 300.0, 400.0],
            "high": [101.0, 201.0, 301.0, 401.0],
            "low": [99.0, 199.0, 299.0, 399.0],
            "close": [100.0, 200.0, 300.0, 400.0],
            "volume": 1.0,
        }, index=htf_index)
        base_index = pd.date_range(
            "2024-01-01 00:00", periods=36, freq="2h", tz="UTC", name="datetime"
        )
        base = make_ohlcv(base_index, start=100.0, step=0.0)
        merged = engine.attach_htf_indicators(
            base, htf, htf_ema_period=1,
            data_cutoff=pd.Timestamp("2024-01-03 00:00", tz="UTC"),
        )
        before_close = pd.Timestamp("2024-01-02 20:00", tz="UTC")
        at_close = pd.Timestamp("2024-01-02 22:00", tz="UTC")
        self.assertAlmostEqual(float(merged.loc[before_close, "htf_close"]), 100.0)
        self.assertAlmostEqual(float(merged.loc[at_close, "htf_close"]), 200.0)


class ExecutionIntegrationTests(unittest.TestCase):
    def test_gap_through_target_fills_at_limit_price(self):
        frame = make_signal_frame(target_high=116.0, target_low=114.0,
                                  second_open=115.0, second_high=116.0,
                                  second_low=114.0, second_close=115.0)
        trades, _ = engine.simulate_trades(frame, engine.BASELINE_CONFIGS["2h"], "2h")
        self.assertEqual(trades[0]["exit_reason"], "GAP_TARGET_LIMIT")
        self.assertEqual(trades[0]["exit_fill"], 110.0)
        self.assertTrue(trades[0]["target_gap_flag"])

    def test_same_candle_stop_and_target_uses_stop_first(self):
        frame = make_signal_frame(target_high=115.0, target_low=90.0,
                                  second_high=115.0, second_low=90.0,
                                  second_close=100.0)
        trades, _ = engine.simulate_trades(frame, engine.BASELINE_CONFIGS["2h"], "2h")
        self.assertEqual(trades[0]["exit_reason"], "STOP_BOTH_TOUCHED_STOP_FIRST")
        self.assertEqual(trades[0]["exit_fill"], 95.0)
        self.assertTrue(trades[0]["stop_first_ambiguity"])

    def test_chandelier_trailing_stop_activates_on_next_candle(self):
        frame = make_signal_frame(target_high=101.0, target_low=99.0)
        frame.iloc[1, frame.columns.get_loc("high")] = 105.0
        frame.iloc[1, frame.columns.get_loc("close")] = 104.0
        frame.iloc[2, frame.columns.get_loc("open")] = 104.0
        frame.iloc[2, frame.columns.get_loc("high")] = 104.0
        frame.iloc[2, frame.columns.get_loc("low")] = 98.0
        frame.iloc[2, frame.columns.get_loc("close")] = 99.0
        trades, audit = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(trades[0]["exit_reason"], "TRAILING_STOP")
        self.assertEqual(trades[0]["exit_fill"], 99.0)
        self.assertTrue(any(
            item["source"] == "CHANDELIER_NEXT_BAR" and item["stop"] == 99.0
            for item in audit[0]["stop_history"]
        ))

    def test_no_funding_commission_or_slippage_is_included(self):
        frame = make_signal_frame(side="SHORT", entry=100.0, stop=105.0,
                                  target_high=101.0, target_low=89.0)
        frame.iloc[1, frame.columns.get_loc("open")] = 100.0
        frame.iloc[2, frame.columns.get_loc("open")] = 100.0
        frame.iloc[2, frame.columns.get_loc("high")] = 100.0
        frame.iloc[2, frame.columns.get_loc("low")] = 90.0
        frame.iloc[2, frame.columns.get_loc("close")] = 90.0
        trades, audit = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h", run_id="test-run"
        )
        trade = trades[0]
        self.assertIsNone(trade["fees"])
        self.assertIsNone(trade["funding"])
        self.assertEqual(trade["cost_model"], engine.COST_MODEL)
        self.assertEqual(trade["funding_model"], engine.FUNDING_MODEL)
        self.assertEqual(trade["run_id"], "test-run")
        self.assertIn("gross_R", trade)
        self.assertIn("gross_R_budget", trade)
        self.assertNotIn("net_R", trade)
        self.assertFalse(trade["short_executable"])
        self.assertEqual(
            audit[0]["cost_breakdown"],
            {"entry_fee": 0.0, "exit_fee": 0.0, "slippage": 0.0, "funding": 0.0},
        )
        self.assertEqual(audit[0]["funding_events"], [])


class OutputIntegrationTests(unittest.TestCase):
    def test_run_analysis_writes_per_timeframe_outputs_and_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.csv"
            htf = root / "htf.csv"
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=1400, freq="2h", tz="UTC"
            )), base)
            write_ohlcv(make_ohlcv(pd.date_range(
                "2023-01-01", periods=400, freq="1D", tz="UTC"
            )), htf)

            base_frame = engine.read_ohlcv(base)
            cutoff = base_frame.index[-1] + pd.Timedelta(2, unit="h")
            output = root / "results" / "v42" / "2h"
            result = engine.run_analysis("2h", base, htf, output_dir=output,
                                         data_cutoff=cutoff)
            self.assertEqual(result["output_directory"], output.resolve())
            for path in engine.result_paths(output, "2h").values():
                self.assertTrue(path.is_file(), path)

            summary = json.loads((output / "2h_summary.json").read_text())
            self.assertEqual(
                summary["run_id"],
                engine.compute_run_id(
                    "2h", engine.BASELINE_CONFIGS["2h"], base, htf,
                    data_cutoff=cutoff, cutoff_mode="strict",
                ),
            )
            self.assertEqual(summary["output_directory"], str(output.resolve()))
            self.assertIn("data_quality", summary)
            self.assertIn("missing_candles", summary["data_quality"]["base"])
            self.assertTrue(summary["data_cutoff_verified"])
            self.assertEqual(summary["cutoff_mode"], "strict")

            with self.assertRaises(FileExistsError):
                engine.run_analysis("2h", base, htf, output_dir=output)

            forced = engine.run_analysis("2h", base, htf, output_dir=output,
                                         force=True, data_cutoff=cutoff)
            self.assertEqual(forced["report"]["run_id"], summary["run_id"])

    def test_empty_trade_summary_is_json_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.csv"
            htf = root / "htf.csv"
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=10, freq="2h", tz="UTC"
            )), base)
            write_ohlcv(make_ohlcv(pd.date_range(
                "2024-01-01", periods=10, freq="1D", tz="UTC"
            )), htf)
            base_frame = engine.read_ohlcv(base)
            signals = pd.DataFrame({
                "signal": "WAIT",
                "wait_reason": "NO_DATA",
            }, index=base_frame.index)
            warmup = engine.WarmupResult(
                False, None, None, 600, 1, "NO_DATA: test", {}
            )
            report = engine.summarize(
                "2h", signals, [], warmup, base, htf
            )
            encoded = json.dumps(engine.json_safe(report), allow_nan=False)
            decoded = json.loads(encoded)
            self.assertIsNone(decoded["metrics"]["average_gross_R"])
            self.assertIsNone(decoded["metrics"]["win_rate_pct"])


if __name__ == "__main__":
    unittest.main()
