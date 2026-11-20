from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import optimization_runtime as runtime
import pandas as pd
import pytest
import strategy_analyzer as engine
import v42_exhaustive_combination_tester as tester
from fixture_data import write_fixture


@pytest.fixture(scope="module")
def golden():
    with gzip.open(Path(__file__).parent / "fixtures/original_engine_golden.json.gz", "rt") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def datasets(tmp_path_factory):
    root = tmp_path_factory.mktemp("market_fixtures")
    return {tf: write_fixture(root, tf) for tf in ("2h", "4h", "1d")}


def assert_golden_fills(trades, original):
    equity = 1000.0
    assert len(trades) == len(original)
    for trade, expected in zip(trades, original):
        for key in ("side", "entry_time", "exit_time", "entry_fill", "exit_fill", "exit_reason",
                    "signal_time", "initial_stop", "target", "mae_R", "mfe_R"):
            assert trade[key] == expected[key]
        quantity = trade["quantity"]
        gross = quantity * (trade["exit_fill"] - trade["entry_fill"]) * (1 if trade["side"] == "LONG" else -1)
        maker = trade["exit_reason"] in ("TARGET", "GAP_TARGET_LIMIT")
        net = gross - quantity * (trade["entry_fill"] * .0002 + trade["exit_fill"] * (.0005 if maker else .0002))
        assert trade["equity_before"] == pytest.approx(equity, abs=1e-9)
        assert trade["net_pnl"] == pytest.approx(net, abs=1e-10)
        equity += net
        assert trade["equity_after"] == pytest.approx(equity, abs=1e-9)


def test_exact_original_sequential_equivalence(golden, datasets):
    prepared = {
        tf: engine.prepare_analysis_data(tf, *paths, cutoff_mode="diagnostic")
        for tf, paths in datasets.items()
    }
    for case in golden["cases"]:
        tf = case["timeframe"]
        data = prepared[tf]
        before = data.base.copy(deep=True)
        result = engine.run_analysis(
            tf,
            *datasets[tf],
            config_override=case["config"],
            cutoff_mode="diagnostic",
            run_id="equivalence",
            prepared_data=data,
            write_outputs=False,
        )
        assert_golden_fills(result["trades"], case["trades"])
        if case["audit"] is not None:
            assert [a["per_bar_state"] for a in engine.json_safe(result["audit"])] == [
                a["per_bar_state"] for a in case["audit"]]
        numeric = result["signals"][case["numeric_columns"]].to_numpy(dtype="float64")
        assert hashlib.sha256(numeric.tobytes()).hexdigest() == case["numeric_digest"]
        signals = result["signals"][["signal", "wait_reason"]].to_csv(index=False).encode()
        assert hashlib.sha256(signals).hexdigest() == case["signal_digest"]
        pd.testing.assert_frame_equal(data.base, before, check_exact=True)
        assert len(data.indicator_cache) <= 2


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_parallel_matches_original_trades_and_metrics(workers, golden, datasets, tmp_path):
    configs = list(itertools.islice(tester.iter_candidates("2h"), 20))
    audit_ids = [tester.config_id("2h", config) for config in configs]
    result = tester.run_search(
        timeframe="2h",
        base_path=datasets["2h"][0],
        htf_path=datasets["2h"][1],
        output_root=tmp_path,
        cutoff_mode="diagnostic",
        workers=workers,
        max_combinations=20,
        echo=False,
        audit_ids=audit_ids,
    )
    assert len(result["rows"]) == result["metadata"]["ok_count"] == 20
    assert result["metadata"]["error_count"] == 0
    cases = golden["cases"][1:21]
    for case, cid in zip(cases, audit_ids):
        row = result["rows"][cid]
        assert row["data_cutoff_verified"] is False
        assert row["total_gross_R"] == pytest.approx(case["metrics"]["total_gross_R"])
        audit = json.loads((Path(result["outputs"]["results_dir"]) / "audits" / f"{cid}.json").read_text())
        assert_golden_fills(audit, case["trades"])
        assert row["net_pnl"] == pytest.approx(sum(tr["net_pnl"] for tr in audit))
    rows = list(result["rows"].values())
    pids = {row["worker_pid"] for row in rows}
    if workers > 1:
        assert len(pids) == workers
        assert os.getpid() not in pids
        assert any(
            a["worker_pid"] != b["worker_pid"]
            and max(a["started_monotonic"], b["started_monotonic"])
            < min(a["finished_monotonic"], b["finished_monotonic"])
            for a in rows
            for b in rows
        )
    else:
        assert pids == {os.getpid()}


def small_ranges():
    return {
        name: {"min": spec["min"], "max": spec["min"], "step": spec["step"]}
        for name, spec in tester.PARAMETER_RANGES.items()
    }


def test_exact_count_pruning_and_canonical_order():
    ranges = small_ranges()
    ranges["fast_ema"] = {"min": 20, "max": 40, "step": 10}
    ranges["medium_ema"] = {"min": 20, "max": 40, "step": 10}
    assert tester.valid_combination_count("2h", ranges) == 3
    first = list(tester.iter_candidates("2h", ranges))
    assert len(first) == 3
    assert first == list(tester.iter_candidates("2h", dict(reversed(list(ranges.items())))))
    ranges["fast_ema"] = {"min": 40, "max": 40, "step": 1}
    assert tester.valid_combination_count("2h", ranges) == 0
    assert list(tester.iter_candidates("2h", ranges)) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 5.2])
def test_nonfinite_fractional_periods_rejected(value):
    with pytest.raises(ValueError):
        tester.range_values("fast_ema", {"min": value, "max": 40, "step": 1})


def test_atomic_record_survives_replace_failure(tmp_path):
    store = runtime.ResultStore(tmp_path / "records")
    cid = "a" * 16
    store.put({"config_id": cid, "status": "error", "error": "first"})
    with mock.patch.object(runtime.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            store.put({"config_id": cid, "status": "ok"})
    recovered = runtime.ResultStore(tmp_path / "records")
    assert recovered[cid]["error"] == "first"
    assert recovered.ok == 0 and recovered.errors == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_resume_identity_and_missing_record(datasets, tmp_path):
    kwargs = dict(
        timeframe="2h",
        base_path=datasets["2h"][0],
        htf_path=datasets["2h"][1],
        output_root=tmp_path,
        cutoff_mode="diagnostic",
        workers=2,
        max_combinations=2,
        echo=False,
    )
    first = tester.run_search(**kwargs)
    second = tester.run_search(**kwargs, resume=True)
    assert len(second["rows"]) == 4
    assert second["metadata"]["skipped_completed"] == 2
    with pytest.raises(tester.TesterError, match="ranking"):
        tester.run_search(**kwargs, resume_run=first["search_id"], rank_by="average_gross_R")
    with pytest.raises(tester.TesterError, match="parameter_ranges"):
        tester.run_search(**kwargs, resume_run=first["search_id"], parameter_ranges=small_ranges())
    next(Path(second["outputs"]["checkpoint_records"]).glob("*/*.json")).unlink()
    with pytest.raises(tester.TesterError, match="missing"):
        tester.run_search(**kwargs, resume=True)


def test_data_reuse_and_no_worker_file_writes(datasets, tmp_path):
    config = next(iter(tester.iter_candidates("2h")))
    paths = datasets["2h"]
    with mock.patch.object(engine, "read_ohlcv", wraps=engine.read_ohlcv) as reader:
        data = engine.prepare_analysis_data("2h", *paths, cutoff_mode="diagnostic")
        with mock.patch.object(pd.DataFrame, "to_csv", side_effect=AssertionError("write")):
            for period in (config["fast_ema"], config["fast_ema"] + 1, config["fast_ema"] + 2):
                engine.run_analysis(
                    "2h",
                    *paths,
                    config_override={**config, "fast_ema": period},
                    cutoff_mode="diagnostic",
                    prepared_data=data,
                    run_id="test",
                    output_dir=tmp_path / "must_not_exist",
                    write_outputs=False,
                    collect_audit=False,
                )
        assert reader.call_count == 2
        assert len(data.indicator_cache) == 2
        assert not (tmp_path / "must_not_exist").exists()


@pytest.mark.parametrize(
    "parameter", ["fast_ema", "medium_ema", "slow_ema", "adx_period", "atr_period", "htf_ema"]
)
def test_cache_key_covers_every_indicator_parameter(parameter, datasets):
    paths = datasets["2h"]
    data = engine.prepare_analysis_data("2h", *paths, cutoff_mode="diagnostic")
    original = dict(engine.BASELINE_CONFIGS["2h"])
    engine.run_analysis(
        "2h",
        *paths,
        config_override=original,
        prepared_data=data,
        cutoff_mode="diagnostic",
        write_outputs=False,
        run_id="cache",
    )
    changed = {**original, parameter: original[parameter] + 1}
    cached = engine.run_analysis(
        "2h",
        *paths,
        config_override=changed,
        prepared_data=data,
        cutoff_mode="diagnostic",
        write_outputs=False,
        run_id="cache",
    )
    fresh = engine.run_analysis(
        "2h",
        *paths,
        config_override=changed,
        cutoff_mode="diagnostic",
        write_outputs=False,
        run_id="cache",
    )
    pd.testing.assert_frame_equal(cached["signals"], fresh["signals"], check_exact=True)
    assert engine.json_safe(cached["trades"]) == engine.json_safe(fresh["trades"])


@pytest.mark.parametrize("timeframe", ["4h", "1d"])
def test_other_timeframes_parallel_cutoff_and_golden(timeframe, golden, datasets, tmp_path):
    case = next(case for case in golden["cases"] if case["timeframe"] == timeframe)
    ranges = {
        name: {
            "min": case["config"][target if isinstance(target, str) else target[0]],
            "max": case["config"][target if isinstance(target, str) else target[0]],
            "step": tester.PARAMETER_RANGES[name]["step"],
        }
        for name, target in tester.ANALYZER_PARAMETER_MAP.items()
    }
    result = tester.run_search(
        timeframe=timeframe,
        base_path=datasets[timeframe][0],
        htf_path=datasets[timeframe][1],
        cutoff_mode="diagnostic",
        parameter_ranges=ranges,
        workers=2,
        output_root=tmp_path,
        max_combinations=1,
        echo=False,
    )
    row = next(iter(result["rows"].values()))
    assert row["trades"] == case["metrics"]["trades"]
    assert row["total_gross_R"] == case["metrics"]["total_gross_R"]
    assert row["data_cutoff_verified"] is False


def test_parallel_strict_cutoff_and_explicit_diagnostic(datasets, tmp_path):
    base, htf = datasets["2h"]
    cutoff = engine.read_ohlcv(base).index[-1]
    for mode, verified in (("strict", True), ("diagnostic", False)):
        result = tester.run_search(
            timeframe="2h",
            base_path=base,
            htf_path=htf,
            data_cutoff=str(cutoff),
            cutoff_mode=mode,
            max_combinations=2,
            workers=2,
            output_root=tmp_path / mode,
            echo=False,
        )
        assert all(row["data_cutoff_verified"] is verified for row in result["rows"].values())
        assert result["metadata"]["data"]["excluded_incomplete_candles"] == 1


@pytest.mark.parametrize(
    "damage", ["duplicate", "unordered", "nan", "inf", "negative_volume", "unaligned"]
)
def test_optimizer_rejects_suspicious_input(damage, datasets, tmp_path):
    base = pd.read_csv(datasets["2h"][0])
    if damage == "duplicate":
        base.loc[1, "timestamp"] = base.loc[0, "timestamp"]
    elif damage == "unordered":
        base = base.iloc[::-1]
    elif damage == "nan":
        base.loc[0, "close"] = np.nan
    elif damage == "inf":
        base.loc[0, "high"] = np.inf
    elif damage == "negative_volume":
        base.loc[0, "volume"] = -1
    else:
        base["timestamp"] += 1000
    path = tmp_path / "bad.csv"
    base.to_csv(path, index=False)
    with pytest.raises(ValueError):
        tester.run_search(
            timeframe="2h",
            base_path=path,
            htf_path=datasets["2h"][1],
            output_root=tmp_path / "output",
            cutoff_mode="diagnostic",
            echo=False,
        )
    assert not (tmp_path / "output").exists()


def test_worker_candidate_exception_and_hash_failure(datasets):
    base, htf = datasets["2h"]
    settings = runtime.WorkerSettings(
        "2h",
        base,
        htf,
        None,
        "diagnostic",
        engine.sha256_file(base),
        engine.sha256_file(htf),
        engine.engine_source_hash(),
        "s" * 16,
    )
    runtime.initialize_worker(settings, ignore_interrupt=False)
    result = runtime.evaluate_candidate({"fast_ema": 500}, "a" * 16)
    assert result.error_type == "ValueError"
    assert "EMA periods" in result.error and "Traceback" in result.traceback
    with pytest.raises(ValueError, match="Engine changed"):
        runtime.initialize_worker(
            runtime.WorkerSettings(
                "2h",
                base,
                htf,
                None,
                "diagnostic",
                settings.base_hash,
                settings.htf_hash,
                "bad",
                settings.search_id,
            ),
            ignore_interrupt=False,
        )


def test_graceful_parallel_interruption_resumes(datasets, tmp_path):
    calls = []

    def interrupt_after_commit(message):
        if "completed=" in message and not calls:
            calls.append(message)
            raise KeyboardInterrupt

    kwargs = dict(
        timeframe="2h",
        base_path=datasets["2h"][0],
        htf_path=datasets["2h"][1],
        output_root=tmp_path,
        cutoff_mode="diagnostic",
        workers=2,
        echo=False,
    )
    first = tester.run_search(**kwargs, max_combinations=100, progress=interrupt_after_commit)
    assert first["interrupted"] and first["metadata"]["ok_count"] > 0
    old = set(first["rows"])
    second = tester.run_search(**kwargs, max_combinations=2, resume=True)
    assert second["metadata"]["newly_evaluated"] == 2
    assert set(second["rows"]) > old


def test_process_crash_is_recorded_and_retryable(datasets, tmp_path):
    # A separate spawned process kills one initialized child; no in-process mock
    # can demonstrate this failure mode on Windows.
    script = tmp_path / "crash_probe.py"
    script.write_text(
        """import sys, threading, time, os
sys.path.insert(0, RESEARCH)
import psutil
import v42_exhaustive_combination_tester as t
def crash():
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        children=psutil.Process().children()
        if children:
            time.sleep(.4)
            children[0].kill()
            return
        time.sleep(.02)
if __name__ == '__main__':
    threading.Thread(target=crash, daemon=True).start()
    r=t.run_search(timeframe='2h',base_path=BASE,htf_path=HTF,output_root=OUTPUT,
                   cutoff_mode='diagnostic',workers=2,max_combinations=100,echo=False)
    assert r['metadata']['status']=='worker_pool_failed',r['metadata']['status']
    assert r['metadata']['error_count']>0
""".replace("RESEARCH", repr(str(Path(tester.__file__).parent)))
        .replace("BASE", repr(str(datasets["2h"][0])))
        .replace("HTF", repr(str(datasets["2h"][1])))
        .replace("OUTPUT", repr(str(tmp_path / "run")))
    )
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    retried = tester.run_search(
        timeframe="2h",
        base_path=datasets["2h"][0],
        htf_path=datasets["2h"][1],
        output_root=tmp_path / "run",
        cutoff_mode="diagnostic",
        workers=2,
        max_combinations=4,
        echo=False,
        resume=True,
        retry_failed=True,
    )
    assert retried["metadata"]["ok_count"] >= 4
    assert list(Path(retried["outputs"]["results_dir"]).joinpath("failures").glob("*.json"))


def test_writer_lock_excludes_second_parent(tmp_path):
    with runtime.writer_lock(tmp_path / "lock"):
        with pytest.raises(RuntimeError, match="Another parent"):
            with runtime.writer_lock(tmp_path / "lock"):
                pass


def test_cli_plan_quiet_and_resume(datasets, tmp_path, capsys):
    paths = datasets["2h"]
    args = [
        "--timeframe",
        "2h",
        "--base",
        str(paths[0]),
        "--htf",
        str(paths[1]),
        "--cutoff-mode",
        "diagnostic",
        "--output",
        str(tmp_path),
        "--max-combinations",
        "2",
        "--workers",
        "2",
    ]
    assert tester.main([*args, "--plan"]) == 0
    assert "Exact valid combinations" in capsys.readouterr().out
    assert tester.main([*args, "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert tester.main([*args, "--resume", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    manifest = next(tmp_path.glob("results/2h/*/run_metadata.json"))
    assert json.loads(manifest.read_text())["ok_count"] == 4


def test_ranking_gates_and_zero_tie_break(datasets, tmp_path):
    result = tester.run_search(
        timeframe="2h",
        base_path=datasets["2h"][0],
        htf_path=datasets["2h"][1],
        cutoff_mode="diagnostic",
        output_root=tmp_path,
        workers=1,
        max_combinations=2,
        min_trades=0,
        min_average_r=1000,
        echo=False,
    )
    assert result["metadata"]["ok_count"] == 2
    assert result["metadata"]["rankable_count"] == 0
    assert all(row["rankable"] is False for row in result["rows"].values())
    zero = {"config_id": "zero", "total_gross_R": 0, "average_gross_R": 1}
    negative = {"config_id": "negative", "total_gross_R": -1, "average_gross_R": 1}
    assert tester.ranking_key(zero, "average_gross_R") > tester.ranking_key(
        negative, "average_gross_R"
    )


def test_prepared_data_detects_changes_and_policy_mismatch(tmp_path):
    base, htf = write_fixture(tmp_path, bars=1500)
    data = engine.prepare_analysis_data("2h", base, htf, cutoff_mode="diagnostic")
    with pytest.raises(ValueError, match="Prepared data does not match"):
        engine.run_analysis(
            "2h", base, htf, cutoff_mode="strict", prepared_data=data, write_outputs=False
        )
    with base.open("a") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="Dataset changed"):
        engine.run_analysis(
            "2h", base, htf, cutoff_mode="diagnostic", prepared_data=data, write_outputs=False
        )
