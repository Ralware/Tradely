"""Reproducible limited optimizer benchmark; never starts an exhaustive search."""

from __future__ import annotations

import argparse
import cProfile
import importlib.util
import itertools
import json
import os
import platform
import pstats
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psutil
import strategy_analyzer as engine
import v42_exhaustive_combination_tester as tester


class ProcessMonitor:
    """Sample RSS and cumulative CPU for this process and its children."""

    def __init__(self):
        self.process = psutil.Process()
        self.initial_cpu = sum(self.process.cpu_times()[:2])
        self.cpu: dict[int, float] = {}
        self.peak_rss = 0
        self.peak_children = 0
        self.gpu = shutil.which("nvidia-smi")
        self.peak_gpu_memory = self.peak_gpu_utilization = None
        self.last_gpu_sample = 0.0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample_loop, daemon=True)

    def sample(self):
        if self.gpu and time.monotonic() - self.last_gpu_sample >= 1:
            self.last_gpu_sample = time.monotonic()
            try:
                usage = subprocess.check_output(
                    [
                        self.gpu,
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=2,
                )
                for line in usage.splitlines():
                    util, memory = map(float, line.split(","))
                    self.peak_gpu_utilization = max(self.peak_gpu_utilization or 0.0, util)
                    self.peak_gpu_memory = max(self.peak_gpu_memory or 0.0, memory)
            except (ValueError, OSError, subprocess.SubprocessError):
                self.gpu = None
        rss = 0
        children = self.process.children(recursive=True)
        self.peak_children = max(self.peak_children, len(children))
        for process in [self.process, *children]:
            try:
                rss += process.memory_info().rss
                self.cpu[process.pid] = sum(process.cpu_times()[:2])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self.peak_rss = max(self.peak_rss, rss)

    def sample_loop(self):
        while not self.stop.wait(0.05):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread.start()
        self.started = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.sample()
        self.elapsed = time.perf_counter() - self.started

    def report(self, count):
        cpu_seconds = sum(self.cpu.values()) - self.initial_cpu
        return {
            "total_seconds": self.elapsed,
            "peak_device_memory_mib": self.peak_gpu_memory,
            "peak_device_utilization_pct": self.peak_gpu_utilization,
            "configs_per_second": count / self.elapsed,
            "seconds_per_configuration": self.elapsed / count,
            "configurations_per_minute": count * 60 / self.elapsed,
            "sampled_peak_aggregate_rss_mb": self.peak_rss / 1024**2,
            "sampled_cpu_seconds": cpu_seconds,
            "average_cpu_core_equivalents": cpu_seconds / self.elapsed,
            "machine_cpu_percent": 100 * cpu_seconds / self.elapsed / (os.cpu_count() or 1),
            "peak_child_processes": self.peak_children,
        }


def profile_one(module, timeframe, base, htf, config, directory):
    profile = cProfile.Profile()
    profile.enable()
    result = module.run_analysis(
        timeframe,
        base,
        htf,
        config_override=config,
        cutoff_mode="diagnostic",
        output_dir=directory / "profile_output",
        run_id="profile",
    )
    profile.disable()
    profile.dump_stats(str(directory / "profile.prof"))
    with (directory / "profile.txt").open("w", encoding="utf-8") as handle:
        pstats.Stats(profile, stream=handle).sort_stats("cumulative").print_stats(45)
    stats = pstats.Stats(profile)
    stages = {}
    for (_, _, name), values in cast(Any, stats).stats.items():
        if name in {
            "read_ohlcv",
            "prepare_analysis_data",
            "resolve_data_cutoff",
            "htf_completion_frame",
            "build_data_quality_report",
            "add_indicators",
            "check_convergence",
            "build_signals",
            "simulate_trades",
            "summarize",
            "to_csv",
            "run_analysis",
        }:
            stages[name] = {"calls": values[1], "cumulative_seconds": values[3]}
    return {"stages_inclusive_not_additive": stages, "trades": len(result["trades"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--htf", type=Path)
    parser.add_argument("--timeframe", choices=["2h", "4h", "1d"], default="2h")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--fixture-bars", type=int, default=6000)
    parser.add_argument(
        "--baseline-source", type=Path, help="Optional pre-change analyzer snapshot"
    )
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "benchmarks")
    parser.add_argument("--mode", choices=["cpu", "gpu", "auto"], default="auto")
    args = parser.parse_args()
    if args.count < 1 or args.fixture_bars < 1:
        parser.error("count and fixture-bars must be positive")
    if bool(args.base) != bool(args.htf):
        parser.error("Supply both --base and --htf")
    directory = args.output.resolve() / f"run_{uuid4().hex[:12]}"
    directory.mkdir(parents=True)
    synthetic = args.base is None
    if synthetic:
        sys.path.insert(0, str(Path(__file__).parent / "tests"))
        from fixture_data import write_fixture

        base, htf = write_fixture(directory / "synthetic_data", args.timeframe, args.fixture_bars)
    else:
        base, htf = args.base.resolve(), args.htf.resolve()
    configs = list(itertools.islice(tester.iter_candidates(args.timeframe), args.count))
    report = {
        "label": "SYNTHETIC TEST DATA - NOT MARKET PERFORMANCE" if synthetic else "Supplied OHLCV",
        "cutoff_mode": "diagnostic",
        "data_cutoff_verified": False,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "system_ram_gb": psutil.virtual_memory().total / 1024**3,
        "numpy": engine.np.__version__,
        "pandas": engine.pd.__version__,
        "engine_sha256": engine.engine_source_hash(),
        "count": args.count,
        "base_sha256": engine.sha256_file(base),
        "htf_sha256": engine.sha256_file(htf),
        "configuration_ids": [tester.config_id(args.timeframe, config) for config in configs],
        "measurements": [],
        "measurement_notes": "CPU/RSS sampled every 50ms; aggregate RSS may double-count shared pages. "
        "Process startup and all parent output are included. Single repetition; no affinity changes.",
    }
    if args.baseline_source:
        spec = importlib.util.spec_from_file_location("original_analyzer", args.baseline_source)
        if spec is None or spec.loader is None:
            raise ValueError("Cannot load the supplied baseline source")
        original = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = original
        spec.loader.exec_module(original)
        baseline_dir = directory / "original"
        baseline_dir.mkdir()
        report["original_profile"] = profile_one(
            original, args.timeframe, base, htf, configs[0], baseline_dir
        )
        with ProcessMonitor() as monitor:
            for config in configs:
                original.run_analysis(
                    args.timeframe,
                    base,
                    htf,
                    config_override=config,
                    cutoff_mode="diagnostic",
                    output_dir=baseline_dir / "candidate",
                    force=True,
                    run_id="baseline",
                )
        report["original_sequential"] = monitor.report(len(configs))
        report["original_sha256"] = original.engine_source_hash()
        print("original", json.dumps(report["original_sequential"]), flush=True)
    profile_dir = directory / "refactored_profile"
    profile_dir.mkdir()
    report["refactored_profile"] = profile_one(
        engine, args.timeframe, base, htf, configs[0], profile_dir
    )
    candle_count = len(engine.read_ohlcv(base))
    for workers in (1, 2, 4):
        with ProcessMonitor() as monitor:
            result = tester.run_search(
                timeframe=args.timeframe,
                base_path=base,
                htf_path=htf,
                output_root=directory / f"workers_{workers}",
                cutoff_mode="diagnostic",
                workers=workers,
                execution_mode=args.mode,
                max_combinations=args.count,
                echo=False,
            )
        if result["metadata"]["ok_count"] != args.count or result["metadata"]["error_count"]:
            raise RuntimeError(f"Benchmark had failed or missing evaluations: {result['metadata']}")
        measurement = {
            "workers": workers,
            "requested_mode": args.mode,
            "active_backends": sorted({row["active_backend"] for row in result["rows"].values()}),
            "candles_per_second": candle_count * args.count / monitor.elapsed,
            **monitor.report(args.count),
            "preflight_seconds": result["metadata"]["preflight_seconds"],
            "worker_initialization": result["metadata"]["worker_initialization"],
            "export_seconds": result["metadata"]["export_seconds"],
            "search_id": result["search_id"],
        }
        report["measurements"].append(measurement)
        measurement["speedup_vs_one_worker"] = (
            report["measurements"][0]["total_seconds"] / measurement["total_seconds"]
        )
        if "original_sequential" in report:
            measurement["speedup_vs_original"] = (
                report["original_sequential"]["total_seconds"] / measurement["total_seconds"]
            )
        print("workers", workers, json.dumps(measurement), flush=True)
        tester.write_json(directory / "benchmark.json", report)
    print("Benchmark report:", directory / "benchmark.json", flush=True)


if __name__ == "__main__":
    main()
