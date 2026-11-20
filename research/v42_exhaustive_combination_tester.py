#!/usr/bin/env python3
"""EMA Pullback V4.2 exhaustive combination tester.

This module is a *search driver*, not a trading engine. Every candidate
configuration is evaluated through ``strategy_analyzer.run_analysis()`` so the
authoritative V4.2 indicators, signal generation, position sizing, stops,
targets, exits, candle-completion rules and PnL accounting stay in one place.

Key guarantees
--------------
* No duplicated backtesting logic.
* Per-fill net accounting and funding provenance are recorded with every result.
* Strict data-cutoff mode remains the default. A strict run requires an
  explicit ``--data-cutoff``; diagnostic runs are always recorded as
  unverified, exactly as the analyzer reports them.
* Deterministic candidate generation, deterministic configuration IDs and a
  deterministic search signature.
* Resumable, atomic per-configuration checkpoints.
* Results, checkpoints, logs, configuration snapshots and metadata are stored
  per timeframe under ``research/optimization/``.

The search space is enormous if every range below is used at a fine step. A
run is therefore capped by ``--max-combinations`` (default 20) and never
starts automatically on import.

Usage (from the project root)
-----------------------------
Smoke test, 20 newly evaluated combinations::

    python research/v42_exhaustive_combination_tester.py \
        --timeframe 2h --data-cutoff 2026-11-19T00:00:00Z \
        --max-combinations 20

Inspect the plan without running anything::

    python research/v42_exhaustive_combination_tester.py \
        --timeframe 2h --data-cutoff 2026-11-19T00:00:00Z --plan

Resume an interrupted search::

    python research/v42_exhaustive_combination_tester.py \
        --timeframe 2h --data-cutoff 2026-11-19T00:00:00Z \
        --max-combinations 200 --resume
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import itertools
import json
import logging
import math
import os
import platform
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# =============================================================================
# USER CONFIGURATION - EDIT SEARCH RANGES HERE
# Keys use the tester's public names. ``ANALYZER_PARAMETER_MAP`` below performs
# the explicit mapping into strategy_analyzer configuration keys.
# Ranges are inclusive: [min, max] with ``step``. If the step does not land on
# ``max`` the endpoint is still included as the final value.
# =============================================================================

PARAMETER_RANGES: dict[str, dict[str, Any]] = {
    "fast_ema":                {"min": 5,    "max": 40,  "step": 5},
    "medium_ema":              {"min": 20,   "max": 100, "step": 10},
    "slow_ema":                {"min": 100,  "max": 365, "step": 25},  # 1D capped at 250
    "adx_period":              {"min": 7,    "max": 28,  "step": 3},
    "adx_min":                 {"min": 15,   "max": 30,  "step": 3},
    "atr_period":              {"min": 7,    "max": 28,  "step": 3},
    "htf_ema":                 {"min": 20,   "max": 100, "step": 10},
    "pullback_n":              {"min": 2,    "max": 10,  "step": 2},
    "pullback_depth_atr":      {"min": 0.0,  "max": 1.0, "step": 0.1},
    "trigger_close_location": {"min": 0.55, "max": 0.80, "step": 0.05},
    "stop_buffer_atr":         {"min": 0.10, "max": 1.0, "step": 0.10},
    "min_stop_atr":            {"min": 0.25, "max": 1.0, "step": 0.25},
    "max_stop_atr":            {"min": 1.5,  "max": 4.0, "step": 0.5},
    "chandelier_atr":          {"min": 1.5,  "max": 5.0, "step": 0.5},
    "time_stop":               {"min": 10,   "max": 60,  "step": 10},
}

# V4.2 fixes the target at 2R. This list is kept explicit so it is obvious that
# the target is not being optimized.
TARGET_R_VALUES: list[float] = [2.0]

MIN_TRADES_FOR_RANKING = 10
DEFAULT_MAX_COMBINATIONS = 20
MAX_COMBINATIONS_SAFETY_NOTE = (
    "A Cartesian product of these ranges is enormous. --max-combinations caps "
    "the number of newly evaluated valid combinations in one invocation; use "
    "--resume to continue."
)
TOP_N_CONFIGS = 100
PROGRESS_EVERY = 10

# Tester public name -> analyzer configuration key(s).
# Every mapping is explicit so a tester name can never silently alias a
# different analyzer parameter.
ANALYZER_PARAMETER_MAP: dict[str, Any] = {
    "fast_ema": "fast_ema",
    "medium_ema": "medium_ema",
    "slow_ema": "slow_ema",
    "adx_period": "adx_period",
    "adx_min": "adx_min",
    "atr_period": "atr_period",
    "htf_ema": "htf_ema",
    "pullback_n": "pullback_n",
    "pullback_depth_atr": "pullback_depth_atr",
    "trigger_close_location": ("trigger_close_long", "trigger_close_short"),
    "stop_buffer_atr": "stop_buffer_atr",
    "min_stop_atr": "min_stop_atr",
    "max_stop_atr": "max_stop_atr",
    "chandelier_atr": "chandelier_atr",
    "time_stop": "time_stop",
}

INTEGER_PARAMETERS = {
    "fast_ema", "medium_ema", "slow_ema", "adx_period", "adx_min",
    "atr_period", "htf_ema", "pullback_n", "time_stop",
}

# Inclusive approved bounds from the V4.2 integration specification.
APPROVED_BOUNDS: dict[str, tuple[float, float]] = {
    "fast_ema": (5, 40),
    "medium_ema": (20, 100),
    "slow_ema": (100, 365),
    "adx_period": (7, 28),
    "adx_min": (15, 30),
    "atr_period": (7, 28),
    "htf_ema": (20, 100),
    "pullback_n": (2, 10),
    "pullback_depth_atr": (0.0, 1.0),
    "trigger_close_location": (0.55, 0.80),
    "stop_buffer_atr": (0.10, 1.0),
    "min_stop_atr": (0.25, 1.0),
    "max_stop_atr": (1.5, 4.0),
    "chandelier_atr": (1.5, 5.0),
    "time_stop": (10, 60),
}
SLOW_EMA_1D_CAP = 250
FIXED_TARGET_R = 2.0

# Analyzer keys that would alter the fixed execution contract. The tester
# refuses to pass them even if a future caller tries to inject them.
FORBIDDEN_ANALYZER_KEYS = {
    "fee", "fees", "fee_pct", "commission", "funding", "funding_rate",
    "slippage", "slippage_pct", "spread", "borrow_rate",
}

FINANCIAL_FIELDS = """gross_pnl net_pnl total_maker_fees total_taker_fees total_fees
total_funding total_slippage gross_return_pct net_return_pct gross_profit_factor net_profit_factor
gross_win_rate_pct net_win_rate_pct net_expectancy average_net_win average_net_loss average_duration_hours
sharpe sortino drawdown_adjusted_return maker_rate taker_rate starting_equity_usdt slippage_rate""".split()
RESULT_FIELDS = FINANCIAL_FIELDS + ["execution_mode", "active_backend", "backend_fallback",
    "config_id", "search_id", "timeframe", "status",
    "trades", "wins", "losses", "win_rate_pct", "total_gross_R",
    "average_gross_R", "profit_factor_gross_R",
    "compounded_equity_return_pct", "max_drawdown_pct",
    "long_trades", "short_trades", "long_expectancy_gross_R",
    "short_expectancy_gross_R", "gap_uncertain_trades",
    "insufficient_trades", "rankable",
    # flattened tester parameters
    "fast_ema", "medium_ema", "slow_ema", "adx_period", "adx_min",
    "atr_period", "htf_ema", "pullback_n", "pullback_depth_atr",
    "trigger_close_location", "stop_buffer_atr", "min_stop_atr",
    "max_stop_atr", "chandelier_atr", "time_stop", "target_r",
    # provenance
    "data_cutoff", "data_cutoff_source", "data_cutoff_verified", "cutoff_mode",
    "base_source_sha256", "htf_source_sha256", "engine_source_sha256",
    "engine_version", "data_processing_version",
    "cost_model", "funding_model", "market_mode",
    "run_id", "configuration_json", "error_type", "error", "timestamp",
    "worker_pid", "elapsed_seconds", "started_monotonic", "finished_monotonic",
]
FAILED_FIELDS = [
    "config_id", "timeframe", "status", "configuration_json", "search_id", "cost_model",
    "funding_model", "market_mode", "maker_rate", "taker_rate", "slippage_rate", "starting_equity_usdt",
    "base_source_sha256", "htf_source_sha256",
    "error_type", "error", "traceback", "timestamp",
]
RANK_METRICS = {
    "net_pnl", "net_return_pct", "net_profit_factor", "sharpe", "net_expectancy", "drawdown_adjusted_return",
    "total_gross_R",
    "compounded_equity_return_pct",
    "average_gross_R",
    "profit_factor_gross_R",
    "max_drawdown_pct",
    "win_rate_pct",
}

TESTER_VERSION = "3.0.0"
DEFAULT_WORKERS = 4
DEFAULT_RANK_BY = "net_pnl"


# =============================================================================
# ANALYZER IMPORT
# =============================================================================

RESEARCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RESEARCH_DIR.parent
OUTPUT_ROOT = RESEARCH_DIR / "optimization"

try:  # keeps the import error actionable when prerequisites are missing
    import optimization_runtime as runtime
    import strategy_analyzer as engine
except ImportError as exc:  # pragma: no cover - exercised only on broken installs
    raise SystemExit(
        "Could not import strategy_analyzer.py. Place this file in the same "
        "research/ directory as strategy_analyzer.py and install "
        "requirements.txt.\n"
        f"Import error: {exc}"
    )




class TesterError(RuntimeError):
    """Raised for invalid tester state or unsafe overwrite attempts."""


# =============================================================================
# SMALL UTILITIES
# =============================================================================

def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    return engine.json_safe(value)


def write_json(path: Path, payload: Any) -> None:
    runtime.atomic_json(path, payload)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]],
              fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    os.replace(temporary, path)


def log_message(log_path: Path, message: str, echo: bool = True,
                progress: Callable[[str], None] | None = None,
                level: int = logging.INFO) -> None:
    logger = logging.getLogger(f"v42.{log_path}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    console = logging.StreamHandler(sys.stdout) if echo else None
    if console is not None:
        console.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console)
    try:
        logger.log(level, message)
    finally:
        logger.removeHandler(handler)
        handler.close()
        if console is not None:
            logger.removeHandler(console)
            console.close()
    if progress is not None:
        progress(message)


# =============================================================================
# RANGE / CANDIDATE GENERATION
# =============================================================================

def range_values(name: str, spec: Mapping[str, Any],
                 timeframe: str | None = None) -> list[Any]:
    """Return inclusive values for one range, enforcing approved bounds.

    The endpoint is included even when ``step`` does not divide the interval.
    Integer parameters are rounded and de-duplicated.
    """
    lo = float(spec["min"])
    hi = float(spec["max"])
    step = float(spec["step"])
    if not all(math.isfinite(value) for value in (lo, hi, step)):
        raise ValueError(f"{name}: min, max and step must be finite")
    if name in INTEGER_PARAMETERS and any(value != int(value) for value in (lo, hi, step)):
        raise ValueError(f"{name}: integer parameters require integer bounds and step")
    if step <= 0:
        raise ValueError(f"{name}: step must be positive, got {spec['step']!r}")
    if hi < lo:
        raise ValueError(f"{name}: max must be >= min")
    if name in APPROVED_BOUNDS:
        approved_lo, approved_hi = APPROVED_BOUNDS[name]
        if lo < approved_lo or hi > approved_hi:
            raise ValueError(
                f"{name}: range [{lo:g}, {hi:g}] is outside approved bounds "
                f"[{approved_lo:g}, {approved_hi:g}]"
            )

    raw: list[float] = []
    count = int(math.floor((hi - lo) / step + 1e-9))
    if count > 1_000_000:
        raise ValueError(f"{name}: more than one million axis values; increase step")
    for index in range(count + 1):
        raw.append(lo + index * step)
    if not raw or raw[-1] < hi - 1e-9:
        raw.append(hi)
    raw = [value for value in raw if value <= hi + 1e-9]

    if name in INTEGER_PARAMETERS:
        if abs(step - round(step)) > 1e-9:
            raise ValueError(
                f"{name}: integer parameter requires an integer step, got {step!r}"
            )
        values: list[Any] = []
        for value in raw:
            integer = int(round(value))
            if integer not in values:
                values.append(integer)
    else:
        values = []
        for value in raw:
            rounded = round(value, 10)
            if rounded not in values:
                values.append(rounded)

    if timeframe == "1d" and name == "slow_ema":
        values = [value for value in values if value <= SLOW_EMA_1D_CAP]
        if (lo <= SLOW_EMA_1D_CAP <= hi
                and SLOW_EMA_1D_CAP not in values):
            values.append(SLOW_EMA_1D_CAP)
            values.sort()
    return values


def validate_parameter_ranges(ranges: Mapping[str, Mapping[str, Any]]) -> None:
    if set(ranges) != set(PARAMETER_RANGES):
        missing = sorted(set(PARAMETER_RANGES) - set(ranges))
        extra = sorted(set(ranges) - set(PARAMETER_RANGES))
        raise ValueError(
            "Parameter range keys must match PARAMETER_RANGES exactly. "
            f"Missing={missing}, extra={extra}"
        )
    for name, spec in ranges.items():
        for key in ("min", "max", "step"):
            if key not in spec:
                raise ValueError(f"{name}: missing {key!r}")
        # Validate by generating values; also enforces integer steps/bounds.
        range_values(name, spec, timeframe="1d")


def build_axes(timeframe: str,
               parameter_ranges: Mapping[str, Mapping[str, Any]] | None = None
               ) -> tuple[list[str], list[list[Any]]]:
    if timeframe not in engine.BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")
    ranges = parameter_ranges if parameter_ranges is not None else PARAMETER_RANGES
    validate_parameter_ranges(ranges)
    names = list(ANALYZER_PARAMETER_MAP)
    axes = [range_values(name, ranges[name], timeframe) for name in names]
    return names, axes


def cartesian_upper_bound(axes: list[list[Any]],
                          target_values: Iterable[float]) -> int:
    return math.prod(len(axis) for axis in axes) * len(list(target_values))


def to_analyzer_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Map tester names to analyzer configuration keys explicitly."""
    config: dict[str, Any] = {}
    for name, target in ANALYZER_PARAMETER_MAP.items():
        if name not in raw:
            raise ValueError(f"Missing tester parameter {name!r}")
        value = raw[name]
        if isinstance(target, tuple):
            long_key, short_key = target
            trigger = float(value)
            config[long_key] = trigger
            config[short_key] = round(1.0 - trigger, 10)
        else:
            config[target] = value
    config["target_r"] = float(raw.get("target_r", FIXED_TARGET_R))
    return config


def validate_candidate(timeframe: str, config: Mapping[str, Any]) -> None:
    """Reject invalid or disallowed candidate configurations before execution."""
    if timeframe not in engine.BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")

    forbidden = set(config) & FORBIDDEN_ANALYZER_KEYS
    if forbidden:
        raise ValueError(
            "Fixed accounting violated by forbidden keys: "
            f"{sorted(forbidden)}"
        )

    allowed = {
        value for value in ANALYZER_PARAMETER_MAP.values()
        if isinstance(value, str)
    }
    for key in ("trigger_close_long", "trigger_close_short", "target_r"):
        allowed.add(key)
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"Unknown analyzer configuration keys: {sorted(unknown)}")

    try:
        fast = int(config["fast_ema"])
        medium = int(config["medium_ema"])
        slow = int(config["slow_ema"])
        min_stop = float(config["min_stop_atr"])
        max_stop = float(config["max_stop_atr"])
        trigger_long = float(config["trigger_close_long"])
        trigger_short = float(config["trigger_close_short"])
        target_r = float(config["target_r"])
    except KeyError as exc:
        raise ValueError(f"Missing analyzer configuration key: {exc}") from exc

    if not (fast < medium < slow):
        raise ValueError(
            "EMA periods must satisfy fast < medium < slow "
            f"(got {fast}, {medium}, {slow})"
        )
    if timeframe == "1d" and slow > SLOW_EMA_1D_CAP:
        raise ValueError(
            f"1D slow EMA is capped at {SLOW_EMA_1D_CAP} (got {slow})"
        )
    if min_stop >= max_stop:
        raise ValueError(
            "min_stop_atr must be below max_stop_atr "
            f"(got {min_stop}, {max_stop})"
        )
    if min_stop <= 0 or max_stop <= 0:
        raise ValueError("Stop distances must be positive")
    if trigger_long <= 0.5 or trigger_short >= 0.5:
        raise ValueError(
            "Trigger close-location thresholds are invalid: "
            f"long={trigger_long}, short={trigger_short}"
        )
    if not math.isfinite(target_r) or target_r <= 0:
        raise ValueError("Target R must be finite and positive")
    if not math.isclose(trigger_short, 1.0 - trigger_long, abs_tol=1e-10):
        raise ValueError("Short trigger must complement long trigger")
    for name in INTEGER_PARAMETERS:
        if float(config[name]) != int(config[name]):
            raise ValueError(f"{name} must be an integer")
    if int(config["time_stop"]) < 1:
        raise ValueError("time_stop must be at least 1 candle")
    if int(config["pullback_n"]) < 1:
        raise ValueError("pullback_n must be at least 1")
    if float(config["chandelier_atr"]) <= 0:
        raise ValueError("chandelier_atr must be positive")
    if float(config["pullback_depth_atr"]) < 0:
        raise ValueError("pullback_depth_atr must be non-negative")

    # Every rounded value must stay inside the approved inclusive bounds.
    for name, target in ANALYZER_PARAMETER_MAP.items():
        if isinstance(target, str):
            value = float(config[target])
        else:
            value = float(config[target[0]])
        lo, hi = APPROVED_BOUNDS[name]
        if not (lo - 1e-9 <= value <= hi + 1e-9):
            raise ValueError(
                f"{name}={value:g} is outside approved bounds [{lo:g}, {hi:g}]"
            )


def iter_candidates(
    timeframe: str,
    parameter_ranges: Mapping[str, Mapping[str, Any]] | None = None,
    target_r_values: Iterable[float] | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield valid analyzer configurations in deterministic Cartesian order.

    Invalid EMA ordering and inconsistent stop bounds are filtered here, so the
    analyzer is never called with a configuration it would reject.
    """
    names, axes = build_axes(timeframe, parameter_ranges)
    targets = list(dict.fromkeys(float(value) for value in (
        target_r_values if target_r_values is not None else TARGET_R_VALUES
    )))
    if not targets or any(not math.isfinite(r) or r <= 0 for r in targets):
        raise ValueError("Target values must be finite and positive")

    def walk(index: int, raw: dict[str, Any]):
        if index == len(names):
            for target in targets:
                config = to_analyzer_config({**raw, "target_r": target})
                validate_candidate(timeframe, config)
                yield config
            return
        name = names[index]
        for value in axes[index]:
            raw[name] = value
            # Prune before visiting the enormous suffix of an invalid EMA tuple.
            if name == "medium_ema" and raw["fast_ema"] >= value:
                continue
            if name == "slow_ema" and raw["medium_ema"] >= value:
                continue
            if name == "max_stop_atr" and raw["min_stop_atr"] >= value:
                continue
            yield from walk(index + 1, raw)

    yield from walk(0, {"target_r": FIXED_TARGET_R})


def valid_combination_count(timeframe: str, parameter_ranges=None) -> int:
    names, axes = build_axes(timeframe, parameter_ranges)
    by_name = dict(zip(names, axes))
    emas = sum(f < m < slow for f, m, slow in itertools.product(
        by_name["fast_ema"], by_name["medium_ema"], by_name["slow_ema"],
    ))
    stops = sum(lo < hi for lo, hi in itertools.product(
        by_name["min_stop_atr"], by_name["max_stop_atr"],
    ))
    dependent = {"fast_ema", "medium_ema", "slow_ema", "min_stop_atr", "max_stop_atr"}
    return emas * stops * math.prod(len(by_name[name]) for name in names if name not in dependent)


def config_id(timeframe: str, config: Mapping[str, Any]) -> str:
    payload = {"timeframe": timeframe, "configuration": _json_safe(config)}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def search_signature(
    *,
    timeframe: str,
    parameter_ranges: Mapping[str, Mapping[str, Any]],
    target_r_values: Iterable[float],
    min_trades: int,
    engine_source_sha256: str,
    base_source_sha256: str,
    htf_source_sha256: str,
    cutoff_policy: Mapping[str, Any],
    rank_by: str = DEFAULT_RANK_BY,
    max_drawdown: float | None = None,
    min_average_r: float | None = None,
) -> dict[str, Any]:
    return {
        "tester_version": TESTER_VERSION,
        "optimizer_hashes": {path.name: engine.sha256_file(path) for path in (
            Path(__file__).resolve(), Path(runtime.__file__).resolve(),
        )},
        "environment": {"python": platform.python_version(),
                        "numpy": engine.np.__version__, "pandas": engine.pd.__version__},
        "methodology": "exhaustive",
        "ranking": {"rank_by": rank_by, "max_drawdown": max_drawdown,
                    "min_average_r": min_average_r, "min_trades": min_trades},
        "axis_order": list(ANALYZER_PARAMETER_MAP),
        "timeframe": timeframe,
        "parameter_ranges": _json_safe(dict(parameter_ranges)),
        "target_r_values": [float(value) for value in target_r_values],
        "min_trades": int(min_trades),
        "engine_source_sha256": engine_source_sha256,
        "base_source_sha256": base_source_sha256,
        "htf_source_sha256": htf_source_sha256,
        "data_cutoff": str(cutoff_policy["value"]),
        "data_cutoff_source": cutoff_policy["source"],
        "data_cutoff_verified": bool(cutoff_policy["verified"]),
        "cutoff_mode": cutoff_policy["mode"],
    }


def search_id_from_signature(signature: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(signature).encode("utf-8")).hexdigest()[:16]


# =============================================================================
# CHECKPOINT / MANIFEST
# =============================================================================

def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    """Load a JSONL checkpoint keyed by config_id (last row wins)."""
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TesterError(
                    f"Corrupt checkpoint line {line_number} in {path}: {exc}"
                ) from exc
            if "config_id" not in row:
                raise TesterError(
                    f"Checkpoint line {line_number} in {path} has no config_id"
                )
            rows[str(row["config_id"])] = row
    return rows


def append_checkpoint(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    # Backward-compatible JSONL helper. Runtime commits individual records;
    # callers of this older API still receive atomic replacement semantics.
    existing = load_checkpoint(path)
    for row in rows:
        existing[str(row["config_id"])] = dict(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in existing.values():
                handle.write(_canonical_json(_json_safe(row)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# =============================================================================
# RESULT ROWS
# =============================================================================

def _numeric(value: Any) -> Any:
    value = engine.json_safe(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def make_row(
    *,
    timeframe: str,
    config: Mapping[str, Any],
    cid: str,
    sid: str,
    run_id: str,
    min_trades: int,
    status: str,
    report: Mapping[str, Any] | None = None,
    error_type: str = "",
    error: str = "",
    tb: str = "",
    fallback_cutoff: str = "",
    fallback_verified: bool | None = None,
    fallback_mode: str = "",
) -> dict[str, Any]:
    metrics = dict(report.get("metrics", {})) if report else {}
    trades = _numeric(metrics.get("trades"))
    trades_int = int(trades) if isinstance(trades, (int, float)) else None

    row: dict[str, Any] = {
        "config_id": cid,
        "search_id": sid,
        "timeframe": timeframe,
        "status": status,
        "trades": trades_int,
        "wins": _numeric(metrics.get("wins")),
        "losses": _numeric(metrics.get("losses")),
        "win_rate_pct": _numeric(metrics.get("win_rate_pct")),
        "total_gross_R": _numeric(metrics.get("total_gross_R")),
        "average_gross_R": _numeric(metrics.get("average_gross_R")),
        "profit_factor_gross_R": _numeric(metrics.get("profit_factor_gross_R")),
        "compounded_equity_return_pct": _numeric(
            metrics.get("compounded_equity_return_pct",
                       metrics.get("compounded_return_pct"))
        ),
        "max_drawdown_pct": _numeric(metrics.get("max_drawdown_pct")),
        "long_trades": _numeric(metrics.get("long_trades")),
        "short_trades": _numeric(metrics.get("short_trades")),
        "long_expectancy_gross_R": _numeric(metrics.get("long_expectancy_gross_R")),
        "short_expectancy_gross_R": _numeric(metrics.get("short_expectancy_gross_R")),
        "gap_uncertain_trades": _numeric(metrics.get("gap_uncertain_trades")),
        "insufficient_trades": (
            bool(trades_int is not None and trades_int < min_trades)
            if status == "ok" else None
        ),
        "rankable": bool(
            status == "ok" and trades_int is not None and trades_int >= min_trades
        ),
        "data_cutoff": "",
        "data_cutoff_source": "",
        "data_cutoff_verified": fallback_verified,
        "cutoff_mode": fallback_mode,
        "base_source_sha256": "",
        "htf_source_sha256": "",
        "engine_source_sha256": "",
        "engine_version": "",
        "data_processing_version": "",
        "cost_model": "",
        "funding_model": "",
        "market_mode": "",
        "run_id": run_id,
        "configuration_json": _canonical_json(_json_safe(dict(config))),
        "error_type": error_type,
        "error": error,
        "timestamp": utc_now(),
    }

    for name, target in ANALYZER_PARAMETER_MAP.items():
        if isinstance(target, tuple):
            row[name] = _numeric(config.get(target[0]))
        else:
            row[name] = _numeric(config.get(target))
    row["target_r"] = _numeric(config.get("target_r"))

    if report:
        row["data_cutoff"] = report.get("data_cutoff", fallback_cutoff)
        row["data_cutoff_source"] = report.get("data_cutoff_source", "")
        if "data_cutoff_verified" in report:
            row["data_cutoff_verified"] = bool(report["data_cutoff_verified"])
        row["cutoff_mode"] = report.get("cutoff_mode", fallback_mode)
        row["base_source_sha256"] = report.get("base_source_sha256", "")
        row["htf_source_sha256"] = report.get("htf_source_sha256", "")
        row["engine_source_sha256"] = report.get("engine_source_sha256", "")
        row["engine_version"] = report.get("engine_version", "")
        row["data_processing_version"] = report.get("data_processing_version", "")
        row["cost_model"] = report.get("cost_model", "")
        row["funding_model"] = report.get("funding_model", "")
        row["market_mode"] = report.get("market_mode", "")
    else:
        row["data_cutoff"] = fallback_cutoff

    row.update({key: metrics.get(key) for key in FINANCIAL_FIELDS})
    for key in ("active_backend", "execution_mode", "backend_fallback"):
        row[key] = (report or {}).get(key)
    row["traceback"] = tb
    return row


def _rank_value(row: Mapping[str, Any], rank_by: str) -> float:
    if row.get(rank_by) == "infinite":
        return math.inf
    value = _as_float(row.get(rank_by))
    return value if value is not None else float("-inf")


def ranked_rows(rows: Iterable[Mapping[str, Any]], rank_by: str,
                min_trades: int) -> list[Mapping[str, Any]]:
    rankable = [
        row for row in rows
        if row.get("status") == "ok"
        and int(row.get("trades") or 0) >= min_trades
    ]

    return sorted(rankable, key=lambda row: ranking_key(row, rank_by), reverse=True)


def ranking_key(row: Mapping[str, Any], rank_by: str) -> tuple[Any, ...]:
    total, drawdown = _as_float(row.get("net_pnl")), _as_float(row.get("max_drawdown_pct"))
    return (_rank_value(row, rank_by), total if total is not None else -math.inf,
            drawdown if drawdown is not None else -math.inf, str(row.get("config_id", "")))


# =============================================================================
# SEARCH
# =============================================================================

def _preflight(timeframe: str, base_path: Path, htf_path: Path,
               data_cutoff: Any, cutoff_mode: str) -> tuple[dict[str, Any], str, str]:
    if timeframe not in engine.BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")
    engine.validate_cutoff_mode(cutoff_mode)
    if cutoff_mode == engine.CUTOFF_MODE_STRICT and data_cutoff is None:
        raise ValueError(
            "Strict cutoff mode requires an explicit, independently verified "
            "--data-cutoff. Diagnostic mode must be selected explicitly."
        )
    if not base_path.is_file():
        raise TesterError(f"Base data file not found: {base_path}")
    if not htf_path.is_file():
        raise TesterError(f"HTF data file not found: {htf_path}")

    prepared = engine.prepare_analysis_data(
        timeframe, base_path, htf_path, data_cutoff, cutoff_mode, reject_suspicious=True,
    )
    return {**prepared.policy, "funding_model": engine.funding_model(prepared.base)}, prepared.base_hash, prepared.htf_hash


def _existing_search_error(results_dir: Path, checkpoint_path: Path) -> None:
    if checkpoint_path.exists() or (results_dir / "run_metadata.json").exists():
        raise TesterError(
            "An existing search with the same deterministic search signature "
            f"was found at {results_dir}. Pass --resume to continue it, or "
            "change --output/parameter ranges for a separate search. Nothing "
            "was overwritten."
        )


def run_search(
    *, timeframe: str, output_root: Path | str = OUTPUT_ROOT,
    base_path: Path | str | None = None, htf_path: Path | str | None = None,
    data_cutoff: Any = None, cutoff_mode: str = engine.DEFAULT_CUTOFF_MODE,
    max_combinations: int | None = DEFAULT_MAX_COMBINATIONS,
    min_trades: int = MIN_TRADES_FOR_RANKING, resume: bool = False,
    retry_failed: bool = False, rank_by: str = DEFAULT_RANK_BY,
    parameter_ranges: Mapping[str, Mapping[str, Any]] | None = None,
    target_r_values: Iterable[float] | None = None, top_n: int = TOP_N_CONFIGS,
    progress_every: int = PROGRESS_EVERY, echo: bool = True,
    progress: Callable[[str], None] | None = None,
    workers: int = DEFAULT_WORKERS, resume_run: str | None = None,
    checkpoint_every: int = 10, max_drawdown: float | None = None,
    min_average_r: float | None = None, audit_ids: Iterable[str] = (),
    log_level: str = "INFO", execution_mode: str = "auto", batch_size: int = 2, cancel_file: Path | None = None,
) -> dict[str, Any]:
    """Evaluate a bounded deterministic prefix; None explicitly requests all.

    Workers own immutable snapshots; the parent exclusively commits results.
    Returned rows are a disk-backed Mapping, not an in-memory result archive.
    """
    if execution_mode not in ("auto", "gpu", "cpu") or batch_size < 1:
        raise ValueError("Invalid execution mode or batch size")
    if workers < 1 or workers > 61:
        raise ValueError("workers must be between 1 and 61 (Windows-compatible limit)")
    if max_combinations is not None and max_combinations < 1:
        raise ValueError("max_combinations must be at least 1")
    if min_trades < 0 or top_n < 0 or checkpoint_every < 1:
        raise ValueError("min_trades/top_n must be non-negative; checkpoint_every positive")
    if rank_by not in RANK_METRICS:
        raise ValueError(f"rank_by must be one of {sorted(RANK_METRICS)}")
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Invalid log level")
    for name, value in (("max_drawdown", max_drawdown), ("min_average_r", min_average_r)):
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if max_drawdown is not None and max_drawdown < 0:
        raise ValueError("max_drawdown is an absolute non-negative percentage")
    if retry_failed and not (resume or resume_run):
        raise ValueError("retry_failed requires resume")
    ranges = {name: dict(spec) for name, spec in (
        parameter_ranges if parameter_ranges is not None else PARAMETER_RANGES
    ).items()}
    names, axes = build_axes(timeframe, ranges)
    targets = list(dict.fromkeys(float(value) for value in (
        target_r_values if target_r_values is not None else TARGET_R_VALUES
    )))
    if not targets or any(not math.isfinite(r) or r <= 0 for r in targets):
        raise ValueError("Target values must be finite and positive")
    upper_bound = cartesian_upper_bound(axes, targets)
    valid_count = valid_combination_count(timeframe, ranges) * len(targets)
    base = Path(base_path or engine.BASE_DATA_FILES[timeframe]).expanduser().resolve()
    htf = Path(htf_path or engine.HTF_DATA_FILES[timeframe]).expanduser().resolve()
    started_clock = time.perf_counter()
    policy, base_hash, htf_hash = _preflight(timeframe, base, htf, data_cutoff, cutoff_mode)
    preflight_seconds = time.perf_counter() - started_clock
    engine_hash = engine.engine_source_hash()
    signature = search_signature(
        timeframe=timeframe, parameter_ranges=ranges, target_r_values=targets,
        min_trades=min_trades, engine_source_sha256=engine_hash,
        base_source_sha256=base_hash, htf_source_sha256=htf_hash, cutoff_policy=policy,
        rank_by=rank_by, max_drawdown=max_drawdown, min_average_r=min_average_r,
    )
    sid = search_id_from_signature(signature)
    if resume_run:
        if len(resume_run) != 16 or any(c not in "0123456789abcdef" for c in resume_run):
            raise ValueError("resume_run must be a 16-character search ID")
        sid, resume = resume_run, True
    root = Path(output_root).expanduser().resolve()
    results_dir = root / "results" / timeframe / sid
    manifest_path = results_dir / "run_metadata.json"
    checkpoint_path = root / "checkpoints" / timeframe / f"{sid}.jsonl"
    state_path = results_dir / "checkpoint.json"
    config_path = root / "configs" / timeframe / f"{sid}.json"
    log_path = root / "logs" / timeframe / f"{sid}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with runtime.writer_lock(results_dir / ".writer.lock"):
        previous = {}
        if resume:
            if not manifest_path.exists():
                raise TesterError("Cannot resume: no matching metadata; timeframe, engine, data, "
                                  "cutoff, ranges or ranking may differ. Use --resume-run ID to "
                                  "compare against a specific original run.")
            previous = read_json(manifest_path)
            old_signature = previous.get("search_signature", {})
            differences = [key for key in set(old_signature) | set(signature)
                           if old_signature.get(key) != _json_safe(signature.get(key))]
            if differences:
                raise TesterError("Cannot resume: incompatible " + ", ".join(sorted(differences)))
        else:
            _existing_search_error(results_dir, checkpoint_path)
        log_path.touch(exist_ok=True)
        rows = runtime.ResultStore(results_dir / "records")
        for cid, row in rows.items():
            if row.get("search_id") != sid or config_id(timeframe, json.loads(row["configuration_json"])) != cid:
                raise TesterError(f"Checkpoint identity mismatch for {cid}")
        if resume and previous.get("checkpoint_total", 0) > len(rows):
            raise TesterError("Checkpoint records are missing; refusing an incomplete recovery")
        snapshot = {
            "tester_version": TESTER_VERSION, "search_id": sid,
            "search_signature": signature, "parameter_ranges": ranges,
            "target_r_values": targets, "analyzer_parameter_map": ANALYZER_PARAMETER_MAP,
            "approved_bounds": APPROVED_BOUNDS, "slow_ema_1d_cap": SLOW_EMA_1D_CAP,
            "cartesian_upper_bound": upper_bound, "valid_combinations": valid_count,
            "order": names, "methodology": "exhaustive", "ranking": signature["ranking"],
        }
        if not resume:
            write_json(config_path, snapshot)
            write_json(results_dir / "search_config.json", snapshot)
        metadata = {
            "tester_version": TESTER_VERSION, "status": "running", "search_id": sid,
            "search_signature": signature, "timeframe": timeframe,
            "started_at_utc": previous.get("started_at_utc", utc_now()),
            "resumed": resume, "resume_count": int(previous.get("resume_count", -1)) + 1,
            "max_combinations_this_invocation": max_combinations,
            "checkpoint_total": len(rows), "cartesian_upper_bound": upper_bound,
            "valid_combinations": valid_count, "workers": workers,
            "start_method": "spawn" if workers > 1 else "in_process",
            "execution_mode": execution_mode, "batch_size": batch_size,
            "max_in_flight": batch_size * 2 * workers if workers > 1 else 1,
            "numerical_threads_per_child": 1, "preflight_seconds": preflight_seconds,
            "min_trades": min_trades, "rank_by": rank_by, "top_n": top_n,
            "engine": {"source_sha256": engine_hash, "engine_version": engine.ENGINE_VERSION,
                       "data_processing_version": engine.DATA_PROCESSING_VERSION},
            "data": {"base_path": str(base), "htf_path": str(htf),
                     "base_source_sha256": base_hash, "htf_source_sha256": htf_hash,
                     "data_cutoff": str(policy["value"]), "data_cutoff_source": policy["source"],
                     "data_cutoff_verified": policy["verified"], "cutoff_mode": policy["mode"],
                     "excluded_incomplete_candles": policy["excluded_incomplete_candles"]},
            "accounting": {**engine.execution_model_settings(), "gross_only": False, "cost_model": engine.COST_MODEL,
                           "funding_model": policy["funding_model"],
                           "data_venue": "Binance USD-M" if base == engine.BASE_DATA_FILES[timeframe] and htf == engine.HTF_DATA_FILES[timeframe] else "user supplied"},
            "candidate_generation": "Deterministic exhaustive prefix, biased toward low axis values; not a random sample.",
            "parameter_ranges": ranges, "target_r_values": targets,
        }
        write_json(manifest_path, metadata)
        counters = {"new": 0, "submitted": 0, "skipped": 0, "duplicates": 0}
        pending_ids: set[str] = set()
        timing = {"seconds": 0.0, "last_progress": 0.0}
        worker_info: dict[int, dict[str, Any]] = {}
        cap_reached = False

        def log(message: str, level: str = "INFO") -> None:
            if logging.getLevelNamesMapping()[level] >= logging.getLevelNamesMapping()[log_level]:
                log_message(log_path, message, echo=echo, progress=progress,
                            level=logging.getLevelNamesMapping()[level])

        def checkpoint() -> None:
            write_json(state_path, {"active_backend": metadata.get("active_backend"), "backend_fallback": metadata.get("backend_fallback"), "search_id": sid, "ok_count": rows.ok,
                       "error_count": rows.errors, "checkpoint_total": len(rows),
                       "updated_at_utc": utc_now(), "records_directory": str(rows.directory)})

        def candidates():
            nonlocal cap_reached
            for config in iter_candidates(timeframe, ranges, targets):
                if cancel_file is not None and cancel_file.exists():
                    return
                cid = config_id(timeframe, config)
                if cid in pending_ids:
                    counters["duplicates"] += 1
                    continue
                old = rows.get(cid)
                if old is not None and json.loads(old["configuration_json"]) != _json_safe(config):
                    raise TesterError(f"Configuration ID collision for {cid}")
                if old is not None and (old["status"] == "ok" or not retry_failed):
                    counters["skipped"] += 1
                    # An occurrence committed during this invocation is a duplicate.
                    if old.get("invocation_started") == metadata["invocation_started"]:
                        counters["duplicates"] += 1
                    continue
                if max_combinations is not None and counters["submitted"] >= max_combinations:
                    cap_reached = True
                    break
                pending_ids.add(cid)
                counters["submitted"] += 1
                yield config, cid

        def rankable(row: Mapping[str, Any]) -> bool:
            if row.get("status") != "ok" or int(row.get("trades") or 0) < min_trades:
                return False
            drawdown, average = _as_float(row.get("max_drawdown_pct")), _as_float(row.get("average_gross_R"))
            if max_drawdown is not None and (drawdown is None or abs(drawdown) > max_drawdown):
                return False
            if min_average_r is not None and (average is None or average < min_average_r):
                return False
            return True

        def collect(result: runtime.Evaluation) -> None:
            cid = result.config_id
            # Handles a Ctrl+C between durable commit and bookkeeping safely.
            old = rows.get(cid)
            if old is not None and old.get("invocation_started") == metadata["invocation_started"]:
                pending_ids.discard(cid)
                return
            row = make_row(
                timeframe=timeframe, config=result.config, cid=cid, sid=sid,
                run_id=f"opt_{timeframe}_{sid}_{cid}", min_trades=min_trades,
                status="error" if result.error_type else "ok", report=result.report,
                error_type=result.error_type, error=result.error, tb=result.traceback,
                fallback_cutoff=str(policy["value"]), fallback_verified=policy["verified"],
                fallback_mode=cutoff_mode,
            )
            row.update(worker_pid=result.worker_pid, elapsed_seconds=result.elapsed_seconds,
                       started_monotonic=result.started_monotonic, finished_monotonic=result.finished_monotonic,
                       invocation_started=metadata["invocation_started"])
            if result.error_type:
                row.update(base_source_sha256=base_hash, htf_source_sha256=htf_hash,
                           cost_model=engine.COST_MODEL, funding_model=policy["funding_model"],
                           market_mode=metadata["accounting"]["market_mode"],
                           maker_rate=engine.MAKER_RATE, taker_rate=engine.TAKER_RATE,
                           slippage_rate=0., starting_equity_usdt=engine.STARTING_EQUITY_USDT)
            row["rankable"] = rankable(row)
            if result.audit is not None:
                write_json(results_dir / "audits" / f"{cid}.json", result.audit)
            metadata["active_backend"] = row.get("active_backend")
            metadata["backend_fallback"] = row.get("backend_fallback")
            if row.get("funding_model"):
                metadata["accounting"]["funding_model"] = row["funding_model"]
            rows.put(row)
            pending_ids.discard(cid)
            counters["new"] += 1
            timing["seconds"] += result.elapsed_seconds
            worker_info[result.worker_pid] = {"initialization_seconds": result.initialized_seconds}
            metadata["current_configuration_id"] = cid
            if result.error_type:
                log(f"ERROR {cid} pid={result.worker_pid}: {result.error_type}: {result.error}", "ERROR")
            if counters["new"] % checkpoint_every == 0:
                checkpoint()

        def show_progress(active: int) -> None:
            elapsed = time.perf_counter() - started_clock
            if elapsed - timing["last_progress"] < 1.0:
                return
            timing["last_progress"] = elapsed
            rate = counters["new"] / elapsed if elapsed else 0.0
            remaining = max(0, valid_count - rows.ok)
            budget_left = remaining if max_combinations is None else max(0, max_combinations - counters["new"])
            eta = min(remaining, budget_left) / rate if rate else None
            if progress_every > 0:
                log(f"[{timeframe}] completed={rows.ok:,} failed={rows.errors:,} active_or_queued={active} "
                    f"remaining={remaining:,} workers={workers} elapsed={elapsed:.1f}s "
                    f"avg={timing['seconds'] / max(1, counters['new']):.3f}s rate={rate * 60:.1f}/min "
                    f"invocation_ETA={eta if eta is not None else 'unknown'}s "
                    f"config={metadata.get('current_configuration_id', '-')}")

        metadata["invocation_started"] = utc_now()
        log(f"[{timeframe}] search={sid} total={upper_bound:,} valid={valid_count:,} "
            f"workers={workers} cap={max_combinations}; cutoff_verified={policy['verified']}")
        if policy["mode"] == "diagnostic":
            log(engine.DIAGNOSTIC_WARNING, "WARNING")
        settings = runtime.WorkerSettings(timeframe, base, htf, data_cutoff, cutoff_mode,
                                          base_hash, htf_hash, engine_hash, sid, tuple(audit_ids), execution_mode, batch_size)
        interrupted, broken = runtime.execute_candidates(
            iter(candidates()), settings, workers, collect, show_progress,
        )
        checkpoint()
        # Stream complete exports and retain only the bounded top-N heap.
        export_start = time.perf_counter()
        all_results_path, top_path = results_dir / "all_results.csv", results_dir / "top_configs.csv"
        failed_path = results_dir / "failed_combinations.csv"
        write_csv(all_results_path, rows.values(), RESULT_FIELDS)
        write_csv(failed_path, (row for row in rows.values() if row["status"] == "error"), FAILED_FIELDS)
        rankable_count = insufficient = 0

        def eligible():
            nonlocal rankable_count, insufficient
            for row in rows.values():
                if row["status"] == "ok" and int(row.get("trades") or 0) < min_trades:
                    insufficient += 1
                if rankable(row):
                    rankable_count += 1
                    yield row

        top_rows = heapq.nlargest(top_n, eligible(), key=lambda row: ranking_key(row, rank_by)) if top_n else []
        if not top_n:
            for _ in eligible():
                pass
        write_csv(top_path, top_rows, RESULT_FIELDS)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows.values():
                handle.write(_canonical_json(_json_safe(row)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, checkpoint_path)
        interrupted = interrupted or (cancel_file is not None and cancel_file.exists())
        status = ("interrupted" if interrupted else "worker_pool_failed" if broken else
                  "paused_cap_reached" if cap_reached else "complete_with_errors" if rows.errors else "complete")
        metadata.update(
            status=status, interrupted=interrupted, cap_reached=cap_reached,
            finished_at_utc=utc_now(), newly_evaluated=counters["new"],
            skipped_completed=counters["skipped"], duplicate_skipped=counters["duplicates"],
            checkpoint_total=len(rows), ok_count=rows.ok, error_count=rows.errors,
            insufficient_trade_count=insufficient, rankable_count=rankable_count,
            elapsed_seconds=time.perf_counter() - started_clock,
            evaluation_seconds=timing["seconds"], worker_initialization=worker_info,
            export_seconds=time.perf_counter() - export_start,
            best_rankable=[{key: row[key] for key in ("config_id", "trades", "net_pnl", "total_gross_R",
                           "compounded_equity_return_pct", "max_drawdown_pct")} for row in top_rows[:5]],
            outputs={"results_dir": str(results_dir), "all_results_csv": str(all_results_path),
                     "top_configs_csv": str(top_path), "failed_combinations_csv": str(failed_path),
                     "run_metadata_json": str(manifest_path), "search_config_json": str(results_dir / "search_config.json"),
                     "config_snapshot_json": str(config_path), "checkpoint_jsonl": str(checkpoint_path),
                     "checkpoint_json": str(state_path), "checkpoint_records": str(rows.directory),
                     "log_file": str(log_path)},
        )
        write_json(manifest_path, metadata)
        log(f"[{timeframe}] {status}: completed={rows.ok} failed={rows.errors}; results={results_dir}")
        return {"metadata": metadata, "rows": rows, "interrupted": interrupted,
                "search_id": sid, "outputs": metadata["outputs"]}


# =============================================================================
# CLI
# =============================================================================

def _print_plan(timeframe: str, ranges: Mapping[str, Mapping[str, Any]],
                targets: Iterable[float], data_cutoff: Any,
                cutoff_mode: str, base_path: Path | None = None,
                htf_path: Path | None = None) -> None:
    _, axes = build_axes(timeframe, ranges)
    targets = list(targets)
    upper = cartesian_upper_bound(axes, targets)
    print(f"\n[{timeframe}] axis sizes:")
    for name, axis in zip(ANALYZER_PARAMETER_MAP, axes):
        print(f"  {name:<24} {len(axis):>4} values  {axis[:4]}"
              f"{' ...' if len(axis) > 4 else ''}")
    print(f"[{timeframe}] target_r values: {targets}")
    print(f"[{timeframe}] Cartesian upper bound: {upper:,}")
    print(f"[{timeframe}] Exact valid combinations: {valid_combination_count(timeframe, ranges) * len(targets):,}")

    sample_count = 0
    for config in iter_candidates(timeframe, ranges, targets):
        if sample_count >= 5:
            break
        print(f"[{timeframe}] sample {sample_count + 1}: "
              f"{_canonical_json(_json_safe(config))}")
        sample_count += 1
    if sample_count == 0:
        print(f"[{timeframe}] no valid candidates under these ranges.")

    base = base_path or engine.BASE_DATA_FILES[timeframe]
    htf = htf_path or engine.HTF_DATA_FILES[timeframe]
    if base.is_file() and htf.is_file():
        policy, _, _ = _preflight(
            timeframe, base.resolve(), htf.resolve(), data_cutoff, cutoff_mode
        )
        print(
            f"[{timeframe}] cutoff={policy['value']} "
            f"source={policy['source']} verified={policy['verified']} "
            f"mode={policy['mode']}"
        )
    else:
        print(f"[{timeframe}] data files missing; cutoff not validated.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded exhaustive parameter search driven by the authoritative "
            "EMA Pullback V4.2 analyzer."
        )
    )
    parser.add_argument("--timeframe", choices=["2h", "4h", "1d", "all"],
                        default="2h")
    parser.add_argument("--data-cutoff", default=None,
                        help="Explicit UTC cutoff. Required in strict mode.")
    parser.add_argument("--cutoff-mode", choices=list(engine.CUTOFF_MODES),
                        default=engine.DEFAULT_CUTOFF_MODE)
    parser.add_argument("--max-combinations", type=int,
                        default=DEFAULT_MAX_COMBINATIONS,
                        help=("Maximum newly evaluated valid combinations in "
                              "this invocation (default 20)."))
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--base", type=Path, help="Override base OHLCV CSV")
    parser.add_argument("--htf", type=Path, help="Override HTF OHLCV CSV")
    parser.add_argument("--ranges", type=Path, help="JSON containing all 15 min/max/step ranges")
    parser.add_argument("--full-search", action="store_true", help="Explicitly remove the invocation cap")
    parser.add_argument("--resume-run", help="Original search ID; verify exact compatibility")
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--max-drawdown", type=float, help="Maximum absolute drawdown percent for ranking")
    parser.add_argument("--min-average-r", type=float, help="Minimum average gross R for ranking")
    parser.add_argument("--audit-config", action="append", default=[], help="Config ID whose detailed audit is retained")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--min-trades", type=int,
                        default=MIN_TRADES_FOR_RANKING)
    parser.add_argument("--execution-mode", choices=["auto", "cpu", "gpu"], default="auto")
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--target-r", type=float, nargs="+", default=TARGET_R_VALUES)
    parser.add_argument("--rank-by", choices=sorted(RANK_METRICS),
                        default=DEFAULT_RANK_BY)
    parser.add_argument("--top-n", type=int, default=TOP_N_CONFIGS)
    parser.add_argument("--resume", action="store_true",
                        help="Resume the checkpoint for this exact search signature.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry combinations previously recorded as errors.")
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT,
                        help="Optimization root (default research/optimization).")
    parser.add_argument("--progress-every", type=int, default=PROGRESS_EVERY)
    parser.add_argument("--plan", action="store_true",
                        help="Print ranges, bounds, sample candidates and cutoff; run nothing.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    args = parser.parse_args(argv)

    if args.max_combinations < 1:
        parser.error("--max-combinations must be at least 1")
    if args.cutoff_mode == engine.CUTOFF_MODE_STRICT and not args.data_cutoff:
        parser.error(
            "strict mode (the default) requires --data-cutoff. Diagnostic mode "
            "must be requested explicitly with --cutoff-mode diagnostic."
        )

    timeframes = ["2h", "4h", "1d"] if args.timeframe == "all" else [args.timeframe]
    if not args.quiet:
        print(MAX_COMBINATIONS_SAFETY_NOTE)
    ranges = read_json(args.ranges) if args.ranges else PARAMETER_RANGES

    exit_code = 0
    if args.plan:
        for timeframe in timeframes:
            try:
                _print_plan(
                    timeframe, ranges, args.target_r,
                    args.data_cutoff, args.cutoff_mode, args.base, args.htf,
                )
            except (TesterError, ValueError, FileNotFoundError) as exc:
                print(f"[{timeframe}] ERROR: {exc}")
                exit_code = 2
        return exit_code

    for timeframe in timeframes:
        try:
            result = run_search(
                timeframe=timeframe,
                output_root=args.output,
                data_cutoff=args.data_cutoff,
                cutoff_mode=args.cutoff_mode,
                max_combinations=None if args.full_search else args.max_combinations,
                workers=args.workers, execution_mode=args.execution_mode, batch_size=args.batch_size, cancel_file=args.cancel_file, base_path=args.base, htf_path=args.htf,
                parameter_ranges=ranges, target_r_values=args.target_r, resume_run=args.resume_run,
                checkpoint_every=args.checkpoint_every, max_drawdown=args.max_drawdown,
                min_average_r=args.min_average_r, audit_ids=args.audit_config,
                log_level=args.log_level,
                min_trades=args.min_trades,
                resume=args.resume,
                retry_failed=args.retry_failed,
                rank_by=args.rank_by,
                top_n=args.top_n,
                progress_every=args.progress_every,
                echo=not args.quiet,
            )
        except KeyboardInterrupt:
            print(f"[{timeframe}] interrupted by user; completed results are "
                  "preserved in the checkpoint.")
            return 130
        except (TesterError, ValueError, FileNotFoundError) as exc:
            print(f"[{timeframe}] ERROR: {exc}")
            exit_code = 2
            continue

        metadata = result["metadata"]
        if metadata["interrupted"]:
            return 130
        if metadata["error_count"] or metadata["status"] == "worker_pool_failed":
            exit_code = 1
        if args.quiet:
            continue
        print(
            f"\n[{timeframe}] {metadata['status']}: "
            f"new={metadata['newly_evaluated']}, "
            f"checkpoint={metadata['checkpoint_total']}, "
            f"rankable={metadata['rankable_count']}"
        )
        print(f"[{timeframe}] full results: {result['outputs']['all_results_csv']}")
        print(f"[{timeframe}] top configs : {result['outputs']['top_configs_csv']}")
        print(f"[{timeframe}] metadata    : {result['outputs']['run_metadata_json']}")
        if metadata["cap_reached"]:
            print(
                f"[{timeframe}] cap reached. Continue with the same command "
                "plus --resume."
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
