import math
from decimal import Decimal

import numpy as np
import pytest
import strategy_analyzer as engine
from app.core.fills import PERPETUAL_FEES, FeeSchedule
from exit_paths import exit_paths
from test_integration_v42 import make_signal_frame


@pytest.mark.parametrize("entry", ["maker", "taker"])
@pytest.mark.parametrize("exit", ["maker", "taker"])
def test_independent_partial_fills(entry, exit):
    rates = {"maker": Decimal(".0005"), "taker": Decimal(".0002")}
    fills = [("0.03", "101.123456", entry), ("0.07", "102.21", entry), ("0.1", "101", exit)]
    oracle = sum(Decimal(q) * Decimal(p) * rates[role] for q, p, role in fills)
    actual = sum(PERPETUAL_FEES.charge(float(q), float(p), role) for q, p, role in fills)
    assert actual == pytest.approx(float(oracle), abs=1e-15)


@pytest.mark.parametrize("invalid", [-0.01, 1.0, math.nan, math.inf])
def test_invalid_schedule(invalid):
    with pytest.raises(ValueError):
        FeeSchedule(maker=invalid)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("rate", [-0.001, 0.001])
def test_signed_funding_and_curve(side, rate):
    frame = make_signal_frame(side=side, target_high=101, target_low=99)
    frame["funding_rate"] = [np.nan, rate, rate, np.nan]
    frame["funding_mark_price"] = [np.nan, 100.0, 99.0, np.nan]
    cfg = dict(engine.BASELINE_CONFIGS["2h"])
    trades, audit = engine.simulate_trades(frame, cfg, "2h")
    trade = trades[0]
    sign = 1 if side == "LONG" else -1
    assert trade["funding"] == pytest.approx(sign * trade["quantity"] * rate * 99)
    assert trade["funding"] == sum(x["payment"] for x in audit[0]["funding_events"])
    curve, backend, _ = engine.marked_curve(frame, trades, "cpu")
    assert backend == "cpu"
    assert curve[1] == pytest.approx(1000 - 0.04 * trade["quantity"])
    assert curve[-1] == pytest.approx(1000 + trade["net_pnl"])
    fast, _ = engine.simulate_trades(frame, cfg, "2h", planned_exits=exit_paths(frame, cfg))
    assert fast == trades


@pytest.mark.parametrize(
    "reason,ohlc",
    [
        ("TARGET", [100, 112, 99, 103]),
        ("GAP_TARGET_LIMIT", [113, 115, 111, 114]),
        ("INITIAL_STOP", [100, 101, 94, 96]),
        ("GAP_STOP", [92, 95, 90, 94]),
        ("STOP_BOTH_TOUCHED_STOP_FIRST", [100, 115, 89, 99]),
        ("DATA_END", [100, 101, 99, 100]),
    ],
)
def test_batched_exit_reference(reason, ohlc):
    frame = make_signal_frame(target_high=101, target_low=99)
    frame.loc[frame.index[2], ["open", "high", "low", "close"]] = ohlc
    cfg = dict(engine.BASELINE_CONFIGS["2h"], chandelier_atr=20)
    trades, _ = engine.simulate_trades(frame, cfg, "2h")
    assert trades[0]["exit_reason"] == reason
    planned = exit_paths(frame, cfg, batch_size=1)
    fast, _ = engine.simulate_trades(frame, cfg, "2h", planned_exits=planned, collect_audit=False)
    assert fast == trades


def test_cuda_initialization_failure_falls_back(monkeypatch):
    def fail():
        raise RuntimeError("driver unavailable")

    monkeypatch.setattr(engine, "cuda_device", fail)
    frame = make_signal_frame()
    trades, _ = engine.simulate_trades(frame, engine.BASELINE_CONFIGS["2h"], "2h")
    gpu, backend, error = engine.marked_curve(frame, trades, "gpu")
    assert backend == "cpu" and "driver" in error
    np.testing.assert_array_equal(gpu, engine.marked_curve(frame, trades, "cpu")[0])


def test_device_out_of_memory_falls_back(monkeypatch):
    class Device:
        class cuda:
            class runtime:
                @staticmethod
                def memGetInfo():
                    raise MemoryError("device exhausted")

    monkeypatch.setattr(engine, "cuda_device", lambda: Device)
    frame = make_signal_frame()
    trades, _ = engine.simulate_trades(frame, engine.BASELINE_CONFIGS["2h"], "2h")
    values, backend, reason = engine.marked_curve(frame, trades, "gpu")
    assert backend == "cpu" and reason == "device exhausted"
    np.testing.assert_array_equal(values, engine.marked_curve(frame, trades, "cpu")[0])


def test_physical_cuda_parity():
    try:
        engine.cuda_device()
    except (ImportError, OSError, RuntimeError) as exc:
        pytest.skip(f"Physical CUDA unavailable: {exc}")
    args = ("2h", engine.BASE_DATA_FILES["2h"], engine.HTF_DATA_FILES["2h"])
    settings = dict(data_cutoff="2026-01-01T00:00:00Z", write_outputs=False, collect_audit=False)
    cpu = engine.run_analysis(*args, **settings, execution_mode="cpu")
    cuda = engine.run_analysis(*args, **settings, execution_mode="gpu")
    assert cuda["report"]["active_backend"] == "cuda" and not cuda["report"]["backend_fallback"]
    assert len(cpu["trades"]) > 0
    import pandas as pd

    pd.testing.assert_frame_equal(cpu["signals"], cuda["signals"], check_exact=True)
    assert cpu["trades"] == cuda["trades"]
    np.testing.assert_allclose(
        cpu["report"]["equity_curve"], cuda["report"]["equity_curve"], rtol=1e-12, atol=1e-9
    )
    for key in ("net_pnl", "net_win_rate_pct", "net_profit_factor", "max_drawdown_pct"):
        assert cpu["report"]["metrics"][key] == pytest.approx(
            cuda["report"]["metrics"][key], abs=1e-9
        )


def test_grid_with_45000_distinct_targets_and_stops():
    import v42_exhaustive_combination_tester as tester

    ranges = {
        k: dict(min=v["min"], max=v["min"], step=v["step"])
        for k, v in tester.PARAMETER_RANGES.items()
    }
    ranges.update(
        fast_ema=dict(min=5, max=24, step=1),
        medium_ema=dict(min=30, max=30, step=1),
        stop_buffer_atr=dict(min=0.10, max=0.80, step=0.05),
        chandelier_atr=dict(min=1.5, max=2.4, step=0.1),
    )
    rows = tester.iter_candidates("2h", ranges, [1 + k / 10 for k in range(15)])
    ids = {tester.config_id("2h", row) for row in rows}
    assert len(ids) == 45000


def test_metrics_reconcile_open_equity_and_fee_induced_loss(tmp_path):
    frame = make_signal_frame(target_high=101, target_low=99)
    frame["wait_reason"] = ""
    frame.loc[frame.index[-1], "close"] = 100.01
    cfg = dict(engine.BASELINE_CONFIGS["2h"], chandelier_atr=20)
    trades, _ = engine.simulate_trades(frame, cfg, "2h")
    warmup = engine.WarmupResult(True, 0, 0, 0, 1, "", {})
    report = engine.summarize("2h", frame, trades, warmup, tmp_path, tmp_path, ("base", "htf"))
    metrics = report["metrics"]
    quantity = trades[0]["quantity"]
    gross = 0.01 * quantity
    fees = (100 + 100.01) * quantity * 0.0002
    assert metrics["gross_pnl"] == pytest.approx(gross)
    assert metrics["net_expectancy"] == pytest.approx(gross - fees)
    assert metrics["total_taker_fees"] == pytest.approx(fees)
    assert metrics["net_profit_factor"] == 0 and metrics["gross_profit_factor"] == "infinite"
    assert metrics["net_win_rate_pct"] == 0 and metrics["gross_win_rate_pct"] == 100
    assert metrics["max_drawdown_pct"] == pytest.approx(-(0.04 * quantity) / 1000 * 100)
    returns = np.diff([1000] + report["equity_curve"]) / np.array(
        [1000] + report["equity_curve"][:-1]
    )
    annual = np.sqrt(365 * 12)
    assert metrics["sharpe"] == pytest.approx(annual * returns.mean() / returns.std(ddof=1))
    assert metrics["sortino"] == pytest.approx(
        annual * returns.mean() / np.sqrt(np.mean(np.minimum(returns, 0) ** 2))
    )


def test_historical_snapshot_matches_audited_sequential_replay():
    args = ("2h", engine.BASE_DATA_FILES["2h"], engine.HTF_DATA_FILES["2h"])
    opts = dict(data_cutoff="2026-01-01T00:00:00Z", write_outputs=False, execution_mode="cpu")
    reference = engine.run_analysis(*args, **opts)
    batch = engine.run_analysis(*args, **opts, collect_audit=False)
    assert len(reference["trades"]) > 0
    assert reference["report"]["funding_model"] == "HISTORICAL_SETTLEMENTS"
    assert reference["trades"] == batch["trades"]
    np.testing.assert_array_equal(
        reference["report"]["equity_curve"], batch["report"]["equity_curve"]
    )


@pytest.mark.parametrize("timeframe", ["2h", "4h", "1d"])
def test_reconcile_perpetual_ledger_to_original_exchange_settlements(timeframe):
    import json

    import pandas as pd

    source = json.loads((engine.DATA_DIRECTORY / "sources.json").read_text())
    events = [
        (
            pd.Timestamp(item["fundingTime"], unit="ms", tz="UTC").floor("h"),
            Decimal(item["fundingRate"]) * Decimal(item["markPrice"]),
        )
        for item in source["funding_events"]
    ]
    result = engine.run_analysis(
        timeframe,
        engine.BASE_DATA_FILES[timeframe],
        engine.HTF_DATA_FILES[timeframe],
        data_cutoff=source["cutoff"],
        write_outputs=False,
        collect_audit=False,
    )
    balance = Decimal(1000)
    assert result["report"]["warmup"]["passed"] and result["trades"]
    for trade in result["trades"]:
        start, end = pd.Timestamp(trade["entry_time"]), pd.Timestamp(trade["exit_time"])
        assert start >= pd.Timestamp(source["start"])
        closing = trade["exit_reason"] in ("TIME_STOP", "DATA_END")
        boundary = end + engine.timeframe_interval(timeframe) if closing else end
        cash = sum(
            value
            for ts, value in events
            if start < ts and (ts < boundary if closing else ts <= boundary)
        )
        qty = Decimal(str(trade["quantity"]))
        sign = 1 if trade["side"] == "LONG" else -1
        entry, exit_price = Decimal(str(trade["entry_fill"])), Decimal(str(trade["exit_fill"]))
        fee = (
            Decimal(".0005")
            if trade["exit_reason"] in ("TARGET", "GAP_TARGET_LIMIT")
            else Decimal(".0002")
        )
        paid = sign * qty * cash
        balance += (
            sign * qty * (exit_price - entry)
            - qty * (entry * Decimal(".0002") + exit_price * fee)
            - paid
        )
        assert trade["funding"] == pytest.approx(float(paid), abs=1e-10)
        assert trade["equity_after"] == pytest.approx(float(balance), rel=1e-12, abs=1e-9)
    assert result["report"]["metrics"]["net_pnl"] == pytest.approx(float(balance - 1000), abs=1e-9)


def test_rolling_signal_windows_equal_pandas_across_batches():
    import pandas as pd
    from exit_paths import pullback_windows

    rng = np.random.default_rng(79)
    frame = pd.DataFrame(
        rng.uniform(80, 120, (400, 6)),
        columns=["low", "high", "close", "ema_fast", "ema_mid", "atr"],
    )
    cfg = dict(engine.BASELINE_CONFIGS["2h"], pullback_n=5)
    n = cfg["pullback_n"]

    def previous(predicate):
        return predicate.shift().rolling(n).max().eq(1)

    expected = [
        previous(frame.low <= frame.ema_fast)
        & ~previous(frame.close < frame.ema_mid - cfg["pullback_depth_atr"] * frame.atr),
        previous(frame.high >= frame.ema_fast)
        & ~previous(frame.close > frame.ema_mid + cfg["pullback_depth_atr"] * frame.atr),
        frame.low.rolling(n + 1).min() - cfg["stop_buffer_atr"] * frame.atr,
        frame.high.rolling(n + 1).max() + cfg["stop_buffer_atr"] * frame.atr,
    ]
    for actual, reference in zip(pullback_windows(frame, cfg, np, chunk_size=13), expected):
        np.testing.assert_array_equal(actual, reference)
