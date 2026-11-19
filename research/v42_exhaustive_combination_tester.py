#!/usr/bin/env python3
"""EMA Pullback V4.2 exhaustive combination tester.

This module is a *search driver*, not a trading engine. Every candidate
configuration is evaluated through ``strategy_analyzer.run_analysis()`` so the
authoritative V4.2 indicators, signal generation, position sizing, stops,
targets, exits, candle-completion rules and PnL accounting stay in one place.

Key guarantees
--------------
* No duplicated backtesting logic.
* Gross-only accounting: the analyzer's no-fee / no-funding / no-slippage
  model is preserved and explicitly checked.
* Strict data-cutoff mode remains the default. A strict run requires an
  explicit ``--data-cutoff``; diagnostic runs are always recorded as
  unverified, exactly as the analyzer reports them.
* Deterministic candidate generation, deterministic configuration IDs and a
  deterministic search signature.
* Resumable, append-only checkpoints.
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
import itertools
import json
import math
import os
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

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

# Analyzer keys that would alter the gross-only accounting contract. The tester
# refuses to pass them even if a future caller tries to inject them.
FORBIDDEN_ANALYZER_KEYS = {
    "fee", "fees", "fee_pct", "commission", "funding", "funding_rate",
    "slippage", "slippage_pct", "spread", "borrow_rate",
}

RESULT_FIELDS = [
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
]
FAILED_FIELDS = [
    "config_id", "timeframe", "status", "configuration_json",
    "error_type", "error", "traceback", "timestamp",
]
RANK_METRICS = {
    "total_gross_R",
    "compounded_equity_return_pct",
    "average_gross_R",
    "profit_factor_gross_R",
}

TESTER_VERSION = "1.0.0"
DEFAULT_RANK_BY = "total_gross_R"


# =============================================================================
# ANALYZER IMPORT
# =============================================================================

RESEARCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RESEARCH_DIR.parent
OUTPUT_ROOT = RESEARCH_DIR / "optimization"

try:  # keeps the import error actionable when prerequisites are missing
    import strategy_analyzer as engine
except Exception as exc:  # pragma: no cover - exercised only on broken installs
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
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    return engine.json_safe(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
                progress: Optional[Callable[[str], None]] = None) -> None:
    line = f"{utc_now()} {message}"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    if echo:
        print(message)
    if progress is not None:
        progress(message)


# =============================================================================
# RANGE / CANDIDATE GENERATION
# =============================================================================

def range_values(name: str, spec: Mapping[str, Any],
                 timeframe: Optional[str] = None) -> list[Any]:
    """Return inclusive values for one range, enforcing approved bounds.

    The endpoint is included even when ``step`` does not divide the interval.
    Integer parameters are rounded and de-duplicated.
    """
    lo = float(spec["min"])
    hi = float(spec["max"])
    step = float(spec["step"])
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
               parameter_ranges: Optional[Mapping[str, Mapping[str, Any]]] = None
               ) -> tuple[list[str], list[list[Any]]]:
    if timeframe not in engine.BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")
    ranges = parameter_ranges if parameter_ranges is not None else PARAMETER_RANGES
    validate_parameter_ranges(ranges)
    names = list(ranges)
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
            "Gross-only accounting violated by forbidden keys: "
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
    if not math.isclose(target_r, FIXED_TARGET_R):
        raise ValueError(
            f"V4.2 target is fixed at {FIXED_TARGET_R}R (got {target_r})"
        )
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
    parameter_ranges: Optional[Mapping[str, Mapping[str, Any]]] = None,
    target_r_values: Optional[Iterable[float]] = None,
) -> Iterable[dict[str, Any]]:
    """Yield valid analyzer configurations in deterministic Cartesian order.

    Invalid EMA ordering and inconsistent stop bounds are filtered here, so the
    analyzer is never called with a configuration it would reject.
    """
    names, axes = build_axes(timeframe, parameter_ranges)
    targets = list(target_r_values if target_r_values is not None else TARGET_R_VALUES)
    for target in targets:
        if not math.isclose(float(target), FIXED_TARGET_R):
            raise ValueError(
                f"V4.2 target is fixed at {FIXED_TARGET_R}R (got {target})"
            )
    for values in itertools.product(*axes, targets):
        raw = dict(zip(names, values[:-1]))
        raw["target_r"] = values[-1]
        config = to_analyzer_config(raw)
        try:
            validate_candidate(timeframe, config)
        except ValueError:
            continue
        yield config


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
) -> dict[str, Any]:
    return {
        "tester_version": TESTER_VERSION,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(_json_safe(dict(row))) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _gross_model_error(report: Mapping[str, Any]) -> Optional[str]:
    checks = (
        ("cost_model", engine.COST_MODEL),
        ("funding_model", engine.FUNDING_MODEL),
    )
    for key, expected in checks:
        if key in report and report[key] != expected:
            return (
                f"{key}={report[key]!r} does not match the gross-only "
                f"constant {expected!r}"
            )
    return None


def make_row(
    *,
    timeframe: str,
    config: Mapping[str, Any],
    cid: str,
    sid: str,
    run_id: str,
    min_trades: int,
    status: str,
    report: Optional[Mapping[str, Any]] = None,
    error_type: str = "",
    error: str = "",
    tb: str = "",
    fallback_cutoff: str = "",
    fallback_verified: Optional[bool] = None,
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

    row["traceback"] = tb
    return row


def _rank_value(row: Mapping[str, Any], rank_by: str) -> float:
    value = _as_float(row.get(rank_by))
    return value if value is not None else float("-inf")


def ranked_rows(rows: Iterable[Mapping[str, Any]], rank_by: str,
                min_trades: int) -> list[Mapping[str, Any]]:
    rankable = [
        row for row in rows
        if row.get("status") == "ok"
        and int(row.get("trades") or 0) >= min_trades
    ]

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        total = _as_float(row.get("total_gross_R")) or float("-inf")
        drawdown = _as_float(row.get("max_drawdown_pct"))
        drawdown = drawdown if drawdown is not None else float("-inf")
        return (
            _rank_value(row, rank_by),
            total,
            drawdown,
            str(row.get("config_id", "")),
        )

    return sorted(rankable, key=key, reverse=True)


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

    base = engine.read_ohlcv(base_path)
    policy = engine.resolve_data_cutoff(base, timeframe, data_cutoff, cutoff_mode)
    return policy, engine.sha256_file(base_path), engine.sha256_file(htf_path)


def _existing_search_error(results_dir: Path, checkpoint_path: Path) -> None:
    if checkpoint_path.exists() or (results_dir / "run_metadata.json").exists():
        raise TesterError(
            "An existing search with the same deterministic search signature "
            f"was found at {results_dir}. Pass --resume to continue it, or "
            "change --output/parameter ranges for a separate search. Nothing "
            "was overwritten."
        )


def run_search(
    *,
    timeframe: str,
    output_root: Path | str = OUTPUT_ROOT,
    base_path: Path | str | None = None,
    htf_path: Path | str | None = None,
    data_cutoff: Any = None,
    cutoff_mode: str = engine.DEFAULT_CUTOFF_MODE,
    max_combinations: int = DEFAULT_MAX_COMBINATIONS,
    min_trades: int = MIN_TRADES_FOR_RANKING,
    resume: bool = False,
    retry_failed: bool = False,
    rank_by: str = DEFAULT_RANK_BY,
    parameter_ranges: Optional[Mapping[str, Mapping[str, Any]]] = None,
    target_r_values: Optional[Iterable[float]] = None,
    top_n: int = TOP_N_CONFIGS,
    progress_every: int = PROGRESS_EVERY,
    echo: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Run or resume one bounded search for one timeframe.

    ``max_combinations`` limits *newly evaluated valid combinations in this
    invocation*. Completed checkpoint entries are skipped and do not count
    toward the cap.
    """
    if max_combinations < 1:
        raise ValueError("max_combinations must be at least 1")
    if min_trades < 0:
        raise ValueError("min_trades must be non-negative")
    if rank_by not in RANK_METRICS:
        raise ValueError(f"rank_by must be one of {sorted(RANK_METRICS)}")
    if top_n < 0:
        raise ValueError("top_n must be non-negative")

    ranges = (dict(parameter_ranges) if parameter_ranges is not None
              else {name: dict(spec) for name, spec in PARAMETER_RANGES.items()})
    targets = [float(value) for value in
               (target_r_values if target_r_values is not None else TARGET_R_VALUES)]
    validate_parameter_ranges(ranges)
    if any(not math.isclose(value, FIXED_TARGET_R) for value in targets):
        raise ValueError(f"V4.2 target is fixed at {FIXED_TARGET_R}R")

    _, axes = build_axes(timeframe, ranges)
    upper_bound = cartesian_upper_bound(axes, targets)

    base = (Path(base_path) if base_path is not None
            else engine.BASE_DATA_FILES[timeframe])
    htf = (Path(htf_path) if htf_path is not None
           else engine.HTF_DATA_FILES[timeframe])
    base = base.expanduser().resolve()
    htf = htf.expanduser().resolve()

    policy, base_hash, htf_hash = _preflight(
        timeframe, base, htf, data_cutoff, cutoff_mode
    )
    engine_hash = engine.engine_source_hash()

    signature = search_signature(
        timeframe=timeframe,
        parameter_ranges=ranges,
        target_r_values=targets,
        min_trades=min_trades,
        engine_source_sha256=engine_hash,
        base_source_sha256=base_hash,
        htf_source_sha256=htf_hash,
        cutoff_policy=policy,
    )
    sid = search_id_from_signature(signature)

    root = Path(output_root).expanduser().resolve()
    results_dir = root / "results" / timeframe / sid
    configs_dir = root / "configs" / timeframe
    checkpoints_dir = root / "checkpoints" / timeframe
    logs_dir = root / "logs" / timeframe
    checkpoint_path = checkpoints_dir / f"{sid}.jsonl"
    log_path = logs_dir / f"{sid}.log"
    config_path = configs_dir / f"{sid}.json"
    manifest_path = results_dir / "run_metadata.json"

    if resume:
        if not manifest_path.exists():
            raise TesterError(
                f"Cannot resume: no run metadata found at {manifest_path}."
            )
        previous = read_json(manifest_path)
        previous_signature = previous.get("search_signature")
        if previous_signature != _json_safe(signature):
            raise TesterError(
                "Cannot resume: the search signature changed. Existing results "
                "would be mixed with a different engine, dataset, cutoff, "
                "ranges or minimum-trade threshold. Start a new search instead."
            )
        rows = load_checkpoint(checkpoint_path)
        if retry_failed:
            # Keep the old error rows visible in outputs until a retry replaces
            # them, but do not count them as completed.
            completed = {
                key for key, row in rows.items()
                if row.get("status") == "ok"
            }
        else:
            completed = set(rows)
        started_at = previous.get("started_at_utc", utc_now())
        resume_count = int(previous.get("resume_count", 0)) + 1
    else:
        _existing_search_error(results_dir, checkpoint_path)
        rows = {}
        completed = set()
        started_at = utc_now()
        resume_count = 0

    results_dir.mkdir(parents=True, exist_ok=True)
    configs_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "tester_version": TESTER_VERSION,
        "search_id": sid,
        "search_signature": _json_safe(signature),
        "timeframe": timeframe,
        "parameter_ranges": _json_safe(ranges),
        "target_r_values": targets,
        "analyzer_parameter_map": _json_safe(ANALYZER_PARAMETER_MAP),
        "approved_bounds": _json_safe(APPROVED_BOUNDS),
        "slow_ema_1d_cap": SLOW_EMA_1D_CAP,
        "min_trades": min_trades,
        "rank_by": rank_by,
        "max_combinations_per_invocation": max_combinations,
        "cartesian_upper_bound": upper_bound,
        "order": "deterministic Cartesian product in PARAMETER_RANGES key order",
    }
    write_json(config_path, snapshot)
    write_json(results_dir / "search_config.json", snapshot)

    newly_evaluated = 0
    skipped_completed = 0
    duplicate_skipped = 0
    interrupted = False
    cap_reached = False
    seen: set[str] = set()

    # Write a resumable manifest before any candidate runs. If the process is
    # killed hard, --resume still finds a signature-matched manifest.
    write_json(manifest_path, {
        "tester_version": TESTER_VERSION,
        "status": "running",
        "search_id": sid,
        "search_signature": _json_safe(signature),
        "timeframe": timeframe,
        "started_at_utc": started_at,
        "resumed": resume,
        "resume_count": resume_count,
        "max_combinations_this_invocation": max_combinations,
        "checkpoint_total": len(rows),
        "cartesian_upper_bound": upper_bound,
    })

    log_message(
        log_path,
        f"[{timeframe}] search {sid} started (resume={resume}, "
        f"cap={max_combinations}, upper_bound={upper_bound:,})",
        echo=echo, progress=progress,
    )

    try:
        for config in iter_candidates(timeframe, ranges, targets):
            cid = config_id(timeframe, config)
            if cid in seen:
                duplicate_skipped += 1
                continue
            seen.add(cid)
            if cid in completed:
                skipped_completed += 1
                continue
            if newly_evaluated >= max_combinations:
                cap_reached = True
                break

            run_id = f"opt_{timeframe}_{sid}_{cid}"
            try:
                validate_candidate(timeframe, config)
                with tempfile.TemporaryDirectory(
                    prefix=f"v42opt_{timeframe}_{cid}_"
                ) as temporary:
                    result = engine.run_analysis(
                        timeframe=timeframe,
                        base_path=base,
                        htf_path=htf,
                        config_override=config,
                        output_dir=Path(temporary),
                        run_id=run_id,
                        force=False,
                        data_cutoff=data_cutoff,
                        cutoff_mode=cutoff_mode,
                    )
                report = result["report"]
                model_error = _gross_model_error(report)
                if model_error:
                    raise TesterError(model_error)
                row = make_row(
                    timeframe=timeframe, config=config, cid=cid, sid=sid,
                    run_id=run_id, min_trades=min_trades, status="ok",
                    report=report,
                    fallback_cutoff=str(policy["value"]),
                    fallback_verified=bool(policy["verified"]),
                    fallback_mode=cutoff_mode,
                )
            except KeyboardInterrupt:
                interrupted = True
                break
            except Exception as exc:  # keep the search alive and logged
                row = make_row(
                    timeframe=timeframe, config=config, cid=cid, sid=sid,
                    run_id=run_id, min_trades=min_trades,
                    status="error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    tb=traceback.format_exc(),
                    fallback_cutoff=str(policy["value"]),
                    fallback_verified=bool(policy["verified"]),
                    fallback_mode=cutoff_mode,
                )
                log_message(
                    log_path,
                    f"[{timeframe}] ERROR {cid}: {type(exc).__name__}: {exc}",
                    echo=echo, progress=progress,
                )

            rows[cid] = row
            append_checkpoint(checkpoint_path, [row])
            newly_evaluated += 1

            if progress_every > 0 and (
                newly_evaluated % progress_every == 0
                or newly_evaluated == max_combinations
            ):
                ok_count = sum(1 for item in rows.values()
                               if item.get("status") == "ok")
                error_count = len(rows) - ok_count
                log_message(
                    log_path,
                    f"[{timeframe}] evaluated {newly_evaluated}/{max_combinations} "
                    f"this run; checkpoint={len(rows):,}, ok={ok_count:,}, "
                    f"errors={error_count:,}",
                    echo=echo, progress=progress,
                )
    except KeyboardInterrupt:
        interrupted = True

    # Rows are appended to the checkpoint immediately after each candidate.
    all_rows = sorted(rows.values(), key=lambda row: str(row.get("config_id", "")))
    ok_rows = [row for row in all_rows if row.get("status") == "ok"]
    error_rows = [row for row in all_rows if row.get("status") != "ok"]
    rankable_rows = ranked_rows(all_rows, rank_by, min_trades)
    top_rows = rankable_rows[:top_n]

    all_results_path = results_dir / "all_results.csv"
    top_path = results_dir / "top_configs.csv"
    failed_path = results_dir / "failed_combinations.csv"

    write_csv(all_results_path, all_rows, RESULT_FIELDS)
    write_csv(top_path, top_rows, RESULT_FIELDS)
    write_csv(failed_path, error_rows, FAILED_FIELDS)

    finished_at = utc_now()
    if interrupted:
        status = "interrupted"
    elif cap_reached:
        status = "paused_cap_reached"
    else:
        status = "complete"

    insufficient = sum(
        1 for row in ok_rows
        if int(row.get("trades") or 0) < min_trades
    )
    metadata = {
        "tester_version": TESTER_VERSION,
        "status": status,
        "interrupted": interrupted,
        "cap_reached": cap_reached,
        "search_id": sid,
        "search_signature": _json_safe(signature),
        "timeframe": timeframe,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "resumed": resume,
        "resume_count": resume_count,
        "max_combinations_this_invocation": max_combinations,
        "newly_evaluated": newly_evaluated,
        "skipped_completed": skipped_completed,
        "duplicate_skipped": duplicate_skipped,
        "checkpoint_total": len(rows),
        "ok_count": len(ok_rows),
        "error_count": len(error_rows),
        "insufficient_trade_count": insufficient,
        "rankable_count": len(rankable_rows),
        "min_trades": min_trades,
        "rank_by": rank_by,
        "top_n": top_n,
        "cartesian_upper_bound": upper_bound,
        "candidate_generation": (
            "deterministic Cartesian product; this prefix is biased toward the "
            "lowest values of each axis. Use broader coverage or multiple "
            "bounded runs before drawing conclusions."
        ),
        "accounting": {
            "gross_only": True,
            "cost_model": engine.COST_MODEL,
            "funding_model": engine.FUNDING_MODEL,
            "short_mode": "hypothetical/signal-only for Spot inputs",
        },
        "engine": {
            "engine_version": engine.ENGINE_VERSION,
            "data_processing_version": engine.DATA_PROCESSING_VERSION,
            "source_path": str(engine.engine_source_path()),
            "source_sha256": engine_hash,
        },
        "data": {
            "base_path": str(base),
            "htf_path": str(htf),
            "base_source_sha256": base_hash,
            "htf_source_sha256": htf_hash,
            "data_cutoff": str(policy["value"]),
            "data_cutoff_source": policy["source"],
            "data_cutoff_verified": bool(policy["verified"]),
            "cutoff_mode": policy["mode"],
            "excluded_incomplete_candles": policy["excluded_incomplete_candles"],
        },
        "parameter_ranges": _json_safe(ranges),
        "target_r_values": targets,
        "outputs": {
            "results_dir": str(results_dir),
            "all_results_csv": str(all_results_path),
            "top_configs_csv": str(top_path),
            "failed_combinations_csv": str(failed_path),
            "run_metadata_json": str(manifest_path),
            "search_config_json": str(results_dir / "search_config.json"),
            "config_snapshot_json": str(config_path),
            "checkpoint_jsonl": str(checkpoint_path),
            "log_file": str(log_path),
        },
        "best_rankable": [
            {
                "config_id": row.get("config_id"),
                "trades": row.get("trades"),
                "total_gross_R": row.get("total_gross_R"),
                "compounded_equity_return_pct": row.get(
                    "compounded_equity_return_pct"
                ),
                "max_drawdown_pct": row.get("max_drawdown_pct"),
            }
            for row in top_rows[:5]
        ],
    }
    write_json(manifest_path, metadata)

    log_message(
        log_path,
        f"[{timeframe}] search {sid} finished: status={status}, "
        f"new={newly_evaluated}, total={len(rows)}, ok={len(ok_rows)}, "
        f"errors={len(error_rows)}; results={results_dir}",
        echo=echo, progress=progress,
    )

    return {
        "metadata": metadata,
        "rows": rows,
        "interrupted": interrupted,
        "search_id": sid,
        "outputs": metadata["outputs"],
    }


# =============================================================================
# CLI
# =============================================================================

def _print_plan(timeframe: str, ranges: Mapping[str, Mapping[str, Any]],
                targets: Iterable[float], data_cutoff: Any,
                cutoff_mode: str) -> None:
    _, axes = build_axes(timeframe, ranges)
    targets = list(targets)
    upper = cartesian_upper_bound(axes, targets)
    print(f"\n[{timeframe}] axis sizes:")
    for name, axis in zip(ranges, axes):
        print(f"  {name:<24} {len(axis):>4} values  {axis[:4]}"
              f"{' ...' if len(axis) > 4 else ''}")
    print(f"[{timeframe}] target_r values: {targets}")
    print(f"[{timeframe}] Cartesian upper bound: {upper:,}")
    print(f"[{timeframe}] EMA ordering and stop constraints reduce this count.")

    sample_count = 0
    for config in iter_candidates(timeframe, ranges, targets):
        if sample_count >= 5:
            break
        print(f"[{timeframe}] sample {sample_count + 1}: "
              f"{_canonical_json(_json_safe(config))}")
        sample_count += 1
    if sample_count == 0:
        print(f"[{timeframe}] no valid candidates under these ranges.")

    base = engine.BASE_DATA_FILES[timeframe]
    htf = engine.HTF_DATA_FILES[timeframe]
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


def main(argv: Optional[list[str]] = None) -> int:
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
    parser.add_argument("--min-trades", type=int,
                        default=MIN_TRADES_FOR_RANKING)
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
    print(MAX_COMBINATIONS_SAFETY_NOTE)

    exit_code = 0
    if args.plan:
        for timeframe in timeframes:
            try:
                _print_plan(
                    timeframe, PARAMETER_RANGES, TARGET_R_VALUES,
                    args.data_cutoff, args.cutoff_mode,
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
                max_combinations=args.max_combinations,
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
