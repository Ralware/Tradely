"""Bounded spawn execution and parent-owned durable result storage.

This module contains no strategy rules. Workers call the analyzer's public API.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any
from uuid import uuid4

import strategy_analyzer as engine


def atomic_json(path: Path, payload: Any) -> None:
    """A killed writer leaves either the previous or the entire new JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(
                engine.json_safe(payload),
                handle,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(path: Path):
    """OS-owned advisory lock, released even after a hard process termination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another parent is writing this run: {path}") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ResultStore(Mapping[str, dict[str, Any]]):
    """Disk-backed mapping: one atomic commit per configuration, bounded RAM.

    CSV/JSONL files are derived exports; these records are the recovery source.
    Sharding limits directory size. Temporary files never count as completed.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.ok = 0
        self.errors = 0
        for row in self.values():
            if row["status"] == "ok":
                self.ok += 1
            else:
                self.errors += 1

    def path(self, cid: str) -> Path:
        if len(cid) != 16 or any(c not in "0123456789abcdef" for c in cid):
            raise ValueError(f"Invalid configuration ID: {cid!r}")
        return self.directory / cid[:2] / f"{cid}.json"

    def __getitem__(self, cid: str) -> dict[str, Any]:
        path = self.path(cid)
        if not path.exists():
            raise KeyError(cid)
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt checkpoint record: {path}") from exc
        if row.get("config_id") != cid or row.get("status") not in {"ok", "error"}:
            raise ValueError(f"Invalid checkpoint record: {path}")
        return row

    def __iter__(self) -> Iterator[str]:
        if self.directory.exists():
            for shard in sorted(self.directory.iterdir()):
                if shard.is_dir():
                    for path in sorted(shard.glob("*.json")):
                        yield path.stem

    def __len__(self) -> int:
        return self.ok + self.errors

    def put(self, row: dict[str, Any]) -> None:
        cid = row["config_id"]
        old = self.get(cid)
        if old is not None and old["status"] == "ok":
            raise ValueError(f"Refusing to replace completed candidate {cid}")
        atomic_json(self.path(cid), row)
        if old is not None:
            self.errors -= 1
        if row["status"] == "ok":
            self.ok += 1
        else:
            self.errors += 1
            # Retain every failed attempt even after a successful retry.
            atomic_json(self.directory.parent / "failures" / f"{cid}_{uuid4().hex}.json", row)


@dataclass(frozen=True)
class WorkerSettings:
    timeframe: str
    base_path: Path
    htf_path: Path
    data_cutoff: Any
    cutoff_mode: str
    base_hash: str
    htf_hash: str
    engine_hash: str
    search_id: str
    audit_ids: tuple[str, ...] = ()
    execution_mode: str = "auto"
    batch_size: int = 2


@dataclass
class Evaluation:
    config: dict[str, Any]
    config_id: str
    report: dict[str, Any] | None
    elapsed_seconds: float
    worker_pid: int
    initialized_seconds: float
    started_monotonic: float
    finished_monotonic: float
    error_type: str = ""
    error: str = ""
    traceback: str = ""
    audit: list[dict[str, Any]] | None = None


_worker = threading.local()


def initialize_worker(settings: WorkerSettings, ignore_interrupt: bool = True) -> None:
    _worker.__dict__.clear()
    start = time.perf_counter()
    if ignore_interrupt:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Settings and hashes bind the immutable worker-local snapshot to this run.
    if engine.engine_source_hash() != settings.engine_hash:
        raise ValueError("Engine changed between preflight and worker initialization")
    _inputs = engine.prepare_analysis_data(
        settings.timeframe,
        settings.base_path,
        settings.htf_path,
        settings.data_cutoff,
        settings.cutoff_mode,
        reject_suspicious=True,
    )
    if (_inputs.base_hash, _inputs.htf_hash) != (settings.base_hash, settings.htf_hash):
        raise ValueError("Dataset changed between preflight and worker initialization")
    _worker.settings = settings
    _worker.inputs = _inputs
    _worker.seconds = time.perf_counter() - start


def evaluate_candidate(config: dict[str, Any], cid: str) -> Evaluation:
    """Top-level picklable worker; returns compact metrics, never writes files."""
    start = time.perf_counter()
    report = None
    audit = None
    error_type = error = tb = ""
    _settings = getattr(_worker, "settings", None)
    _inputs = getattr(_worker, "inputs", None)
    try:
        if _settings is None or _inputs is None:
            raise RuntimeError("Worker not initialized")
        if engine.engine_source_hash() != _settings.engine_hash:
            raise ValueError("Engine source changed during the run")
        detailed = cid in _settings.audit_ids
        result = engine.run_analysis(
            timeframe=_settings.timeframe,
            base_path=_settings.base_path,
            htf_path=_settings.htf_path,
            config_override=config,
            data_cutoff=_settings.data_cutoff,
            cutoff_mode=_settings.cutoff_mode,
            run_id=f"opt_{_settings.timeframe}_{_settings.search_id}_{cid}",
            prepared_data=_inputs,
            execution_mode=_settings.execution_mode,
            write_outputs=False,
            collect_audit=detailed,
        )
        source = result["report"]
        if source.get("cost_model") != engine.COST_MODEL or source.get("funding_model") not in (
            engine.FUNDING_MODEL,
            "BAR_OPEN_SETTLEMENTS",
            "HISTORICAL_SETTLEMENTS",
        ):
            raise ValueError("Analyzer returned unknown accounting assumptions")
        report = {
            key: source[key]
            for key in (
                "metrics",
                "active_backend",
                "backend_fallback",
                "execution_mode",
                "data_cutoff",
                "data_cutoff_source",
                "data_cutoff_verified",
                "cutoff_mode",
                "base_source_sha256",
                "htf_source_sha256",
                "engine_source_sha256",
                "engine_version",
                "data_processing_version",
                "cost_model",
                "funding_model",
                "market_mode",
            )
            if key in source
        }
        if detailed:
            audit = engine.json_safe(result["audit"])
    except Exception as exc:  # Candidate boundary: serialize failure, never suppress it.
        error_type, error, tb = type(exc).__name__, str(exc), traceback.format_exc()
    end = time.perf_counter()
    return Evaluation(
        config,
        cid,
        report,
        end - start,
        os.getpid(),
        getattr(_worker, "seconds", 0.0),
        start,
        end,
        error_type,
        error,
        tb,
        audit,
    )


THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


@contextmanager
def single_threaded_children():
    previous = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    try:
        for name in THREAD_VARIABLES:
            os.environ[name] = "1"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def evaluate_batch(batch):
    return [evaluate_candidate(config, cid) for config, cid in batch]


def execute_candidates(
    candidates: Iterator[tuple[dict[str, Any], str]],
    settings: WorkerSettings,
    workers: int,
    on_result: Callable[[Evaluation], None],
    on_progress: Callable[[int], None],
    *,
    in_flight: int | None = None,
) -> tuple[bool, bool]:
    """Return (interrupted, pool_broken). Drain submitted work on first Ctrl+C.

    One worker is the in-process reference path. Two or more use spawn on every
    OS. The queue never exceeds twice the worker count. Hard termination leaves
    atomic result records intact; uncommitted tasks are retried on resume.
    """
    if multiprocessing.current_process().name != "MainProcess":
        raise RuntimeError("Nested optimization executors are not supported")
    if workers == 1:
        try:
            initialize_worker(settings, ignore_interrupt=False)
            for config, cid in candidates:
                on_result(evaluate_candidate(config, cid))
                on_progress(0)
        except KeyboardInterrupt:
            return True, False
        finally:
            _worker.__dict__.clear()
        return False, False

    interrupted = broken = exhausted = False
    pending: dict[Future, list] = {}
    with single_threaded_children():
        pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize_worker,
            initargs=(settings,),
        )
        try:
            while pending or not exhausted:
                try:
                    while not (exhausted or interrupted or broken) and len(pending) < (
                        in_flight or workers * 2
                    ):
                        batch = list(islice(candidates, settings.batch_size))
                        if not batch:
                            exhausted = True
                            break
                        try:
                            pending[pool.submit(evaluate_batch, batch)] = batch
                        except BrokenProcessPool as exc:
                            now = time.perf_counter()
                            for config, cid in batch:
                                on_result(
                                    Evaluation(
                                        config,
                                        cid,
                                        None,
                                        0,
                                        0,
                                        0,
                                        now,
                                        now,
                                        type(exc).__name__,
                                        str(exc),
                                        traceback.format_exc(),
                                    )
                                )
                            broken = exhausted = True
                            break
                    if not pending:
                        break
                    done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in done:
                        batch = pending[future]
                        if future.cancelled():
                            del pending[future]
                            continue
                        try:
                            results = future.result()
                        except (
                            Exception
                        ) as exc:  # Infrastructure failure still belongs to its candidate.
                            now = time.perf_counter()
                            results = [
                                Evaluation(
                                    config,
                                    cid,
                                    None,
                                    0,
                                    0,
                                    0,
                                    now,
                                    now,
                                    type(exc).__name__,
                                    str(exc),
                                    traceback.format_exc(),
                                )
                                for config, cid in batch
                            ]
                            if isinstance(exc, BrokenProcessPool):
                                broken = exhausted = True
                        # Keep the future until its result is durably committed.
                        while results:
                            on_result(results[0])
                            del results[0]
                        del pending[future]
                    on_progress(len(pending))
                except KeyboardInterrupt:
                    interrupted = exhausted = True
                    for future in pending:
                        future.cancel()
                    # Subsequent interrupts do not discard already finished futures.
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    return interrupted, broken
