import math

import pytest
import strategy_analyzer as engine
from validation_workloads import bootstrap_trade_returns, portfolio_replay, walk_forward


def test_walk_forward_selects_on_training_only_and_limits_entries():
    timeframe = "2h"
    base, htf = engine.BASE_DATA_FILES[timeframe], engine.HTF_DATA_FILES[timeframe]
    config = {"target_r": 1.6}
    start, end = "2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z"
    train_pnl = [
        engine.run_analysis(
            timeframe,
            base,
            htf,
            c,
            data_cutoff=start,
            write_outputs=False,
            collect_audit=False,
        )["report"]["metrics"]["net_pnl"]
        for c in ({}, config)
    ]
    out = walk_forward(timeframe, base, htf, [start, end], [{}, config])
    (fold,) = out["folds"]
    assert fold["configuration"]["target_r"] == (2.0 if train_pnl[0] >= train_pnl[1] else 1.6)
    assert fold["training_net_pnl"] == max(train_pnl)
    assert engine.as_utc_timestamp(start, "start") <= engine.as_utc_timestamp(
        fold["first_entry"], "entry"
    )
    assert engine.as_utc_timestamp(fold["last_exit"], "exit") < engine.as_utc_timestamp(end, "end")
    assert out["combined_return_pct"] == pytest.approx(fold["net_pnl"] / 10)


def test_bootstrap_preserves_known_path_and_reports_drawdown_from_initial_balance():
    one = bootstrap_trade_returns([-0.1, 0.1, -0.2], paths=32, block_size=3, seed=8)
    assert one["terminal_return_pct"] == pytest.approx([-20.8] * 3)
    flat = bootstrap_trade_returns([-0.05] * 8, paths=32, block_size=2)
    assert flat["drawdown_pct"] == pytest.approx([100 * (0.95**8 - 1)] * 3)
    assert flat["loss_probability"] == 1


def test_bootstrap_gpu_fallback_preserves_sampling(monkeypatch):
    def fail():
        raise RuntimeError("No CUDA device")

    monkeypatch.setattr(engine, "cuda_device", fail)
    options = dict(paths=128, block_size=2, seed=9)
    reference = bootstrap_trade_returns([0.02, -0.1, 0.05, 0.12, -0.02], **options)
    actual = bootstrap_trade_returns([0.02, -0.1, 0.05, 0.12, -0.02], mode="gpu", **options)
    assert actual == {**reference, "fallback_reason": "No CUDA device"}


def trade(entry, exit_, notional, pnl, starting=1000):
    return dict(
        entry_time=f"2025-01-0{entry}T00:00:00Z",
        exit_time=f"2025-01-0{exit_}T00:00:00Z",
        entry_notional=notional,
        net_pnl=pnl,
        equity_before=starting,
    )


def test_portfolio_never_spends_same_bar_sale_proceeds_on_new_entry():
    trades = {
        "B": [trade(1, 2, 800, 80)],
        "A": [trade(1, 1, 800, -80)],
        "C": [trade(2, 3, 1000, 100)],
        "D": [trade(3, 4, 1000, 100)],
    }
    result = portfolio_replay(trades)
    a, b, c, d = result["trades"]
    assert [a["reserved_notional"], b["reserved_notional"]] == [800, 200]
    assert c["reserved_notional"] == pytest.approx(720)
    assert d["reserved_notional"] == pytest.approx(220)
    assert result["net_pnl"] == pytest.approx(34)
    assert math.isclose(result["realized_max_drawdown_pct"], -8)


def test_portfolio_skips_unfunded_and_rejects_overlap():
    result = portfolio_replay({"A": [trade(1, 2, 1000, 10)], "B": [trade(1, 2, 5, 1)]})
    assert result["skipped_trades"] == 1
    assert result["ending_capital"] == 1010
    with pytest.raises(ValueError, match="overlapping"):
        portfolio_replay({"A": [trade(1, 2, 1000, 10), trade(2, 3, 200, -10)]})


def test_portfolio_backtest_one_symbol_reconciles_to_strategy_ledger():
    from validation_workloads import portfolio_backtest

    timeframe = "2h"
    result = portfolio_backtest(
        timeframe,
        {
            "BTCUSDT": {
                "base": engine.BASE_DATA_FILES[timeframe],
                "htf": engine.HTF_DATA_FILES[timeframe],
            }
        },
        "2026-01-01T00:00:00Z",
        mode="cpu",
    )
    assert result["net_pnl"] == pytest.approx(2.0591542134275187)
    assert result["skipped_trades"] == 0
    assert len(result["trades"]) == 69
    assert result["datasets"]["BTCUSDT"]["execution_backend"] == "cpu"


def test_physical_cuda_bootstrap_parity():
    try:
        engine.cuda_device()
    except (ImportError, OSError, RuntimeError) as exc:
        pytest.skip(f"Physical CUDA unavailable: {exc}")
    returns = [0.05, -0.02, 0, 0.1, -0.06, -0.015, 0.008]
    options = dict(paths=4096, seed=18, block_size=3)
    reference = bootstrap_trade_returns(returns, mode="cpu", **options)
    actual = bootstrap_trade_returns(returns, mode="gpu", **options)
    assert actual["execution_backend"] == "cuda"
    assert actual["terminal_return_pct"] == pytest.approx(
        reference["terminal_return_pct"], abs=1e-10
    )
    assert actual["drawdown_pct"] == pytest.approx(reference["drawdown_pct"], abs=1e-10)
    # Roundoff around a path with exactly zero net return can change the loss predicate.
    assert actual["loss_probability"] == reference["loss_probability"]


def test_snapshot_candle_only_mode_does_not_claim_funding(tmp_path, monkeypatch):
    import json

    import build_perpetual_snapshot as snapshot
    import pandas as pd

    start, end = pd.to_datetime(["2025-01-01", "2025-02-01"], utc=True)
    index = pd.date_range(start, end, inclusive="left", freq="2h")
    bars = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0}, index=index
    )

    def month_data(month, symbol):
        assert month == start and symbol == "ETHUSDT"
        return bars, {"sha256": "fixture"}

    def unavailable(*args):
        raise ConnectionError("Funding endpoint unavailable")

    monkeypatch.setattr(snapshot, "month_data", month_data)
    monkeypatch.setattr(snapshot, "funding_history", unavailable)
    with pytest.raises(ConnectionError, match="Funding endpoint unavailable"):
        snapshot.build("ETHUSDT", tmp_path, start, start, end)
    snapshot.build("ETHUSDT", tmp_path, start, start, end, include_funding=False)
    frame = engine.read_ohlcv(tmp_path / "ETHUSDT_2hours.csv")
    assert len(frame) == len(index)
    assert engine.funding_model(frame) == "UNAVAILABLE_EXCLUDED_ZERO"
    with (tmp_path / "sources.json").open() as handle:
        source = json.load(handle)
    assert source["symbol"] == "ETHUSDT"
    assert source["funding_model"] == "UNAVAILABLE_EXCLUDED_ZERO"
    assert not source["funding_events"]
