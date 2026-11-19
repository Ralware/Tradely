from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH))

import strategy_analyzer as engine


class DataTests(unittest.TestCase):
    def test_reads_millisecond_timestamp_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            frame = pd.DataFrame({
                "timestamp": [1700000000000, 1700007200000],
                "open": [100, 101], "high": [102, 103],
                "low": [99, 100], "close": [101, 102], "volume": [5, 6],
            })
            frame.to_csv(path, index=False)
            result = engine.read_ohlcv(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(str(result.index.tz), "UTC")

    def test_rejects_invalid_ohlc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            pd.DataFrame({
                "timestamp": [1700000000000],
                "open": [100], "high": [98], "low": [99], "close": [100],
            }).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                engine.read_ohlcv(path)


class IndicatorTests(unittest.TestCase):
    def test_wilder_rma_uses_sma_seed(self):
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = engine.wilder_rma(series, 3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[3], (2.0 * 2 + 4.0) / 3.0)

    def test_ema_order_validation(self):
        cfg = dict(engine.BASELINE_CONFIGS["2h"])
        cfg.update({"fast_ema": 50, "medium_ema": 20})
        idx = pd.date_range("2020-01-01", periods=10, freq="2h", tz="UTC")
        df = pd.DataFrame({
            "open": np.arange(100, 110), "high": np.arange(101, 111),
            "low": np.arange(99, 109), "close": np.arange(100, 110),
            "volume": 1.0,
        }, index=idx)
        hidx = pd.date_range("2019-01-01", periods=100, freq="1D", tz="UTC")
        htf = pd.DataFrame({
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": np.linspace(100, 120, 100), "volume": 1.0,
        }, index=hidx)
        with self.assertRaises(ValueError):
            engine.run_analysis("2h", Path("missing.csv"), Path("missing2.csv"), cfg)


class ExecutionTests(unittest.TestCase):
    def make_signal_frame(self, side="LONG", entry=100.0, stop=95.0,
                          target_high=111.0, target_low=99.0):
        idx = pd.date_range("2024-01-01", periods=4, freq="2h", tz="UTC", name="datetime")
        frame = pd.DataFrame({
            "open": [100.0, entry, 100.0, 100.0],
            "high": [101.0, 101.0, target_high, 101.0],
            "low": [99.0, 99.0, target_low, 99.0],
            "close": [100.0, 100.0, 105.0, 100.0],
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
        return frame

    def test_gap_stop_fills_at_open_without_costs(self):
        frame = self.make_signal_frame(target_high=106.0, target_low=90.0)
        # Entry at next bar open=100, active stop=95; next bar open=90 is gap-through.
        frame.iloc[2, frame.columns.get_loc("open")] = 90.0
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertEqual(trades[0]["exit_reason"], "GAP_STOP")
        self.assertEqual(trades[0]["exit_fill"], 90.0)
        self.assertIsNone(trades[0]["fees"])
        self.assertIsNone(trades[0]["funding"])

    def test_target_is_two_r_from_actual_entry(self):
        frame = self.make_signal_frame(target_high=111.0, target_low=99.0)
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        self.assertAlmostEqual(trades[0]["target"], 110.0)

    def test_r_budget_and_actual_r_are_both_reported(self):
        frame = self.make_signal_frame(target_high=111.0, target_low=99.0)
        trades, _ = engine.simulate_trades(
            frame, engine.BASELINE_CONFIGS["2h"], "2h"
        )
        trade = trades[0]
        self.assertIn("actual_initial_risk", trade)
        self.assertIn("risk_budget", trade)
        self.assertIn("gross_R", trade)
        self.assertIn("gross_R_budget", trade)


if __name__ == "__main__":
    unittest.main()
