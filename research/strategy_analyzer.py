#!/usr/bin/env python3
"""EMA Pullback V4.2 research simulator for completed OHLCV bars."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
from exit_paths import exit_paths, pullback_windows

# Standalone research CLI also uses the backend fill model.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.fills import PERPETUAL_FEES  # noqa: E402

# =============================================================================
# USER CONFIGURATION — EDIT THESE VALUES
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "research" / "data" / "BTCUSDT_USDM"
# Bug-fix revision outputs are deliberately written to a new root so the
# original V4.2 baseline under research/results/v42/ is never overwritten.
OUTPUT_DIRECTORY = PROJECT_ROOT / "research" / "results" / "v42_net"

# Choose one timeframe per run: "2h", "4h", or "1d".
TIMEFRAME_TO_TEST = "2h"

BASE_DATA_FILES = {
    "2h": DATA_DIRECTORY / "BTCUSDT_2hours.csv",
    "4h": DATA_DIRECTORY / "BTCUSDT_4hours.csv",
    "1d": DATA_DIRECTORY / "BTCUSDT_1day.csv",
}
HTF_DATA_FILES = {
    "2h": DATA_DIRECTORY / "BTCUSDT_1day.csv",
    "4h": DATA_DIRECTORY / "BTCUSDT_1day.csv",
    "1d": DATA_DIRECTORY / "BTCUSDT_1week.csv",
}

# V4.2 frozen baseline defaults.
BASELINE_CONFIGS: dict[str, dict[str, Any]] = {
    "2h": {
        "fast_ema": 20, "medium_ema": 50, "slow_ema": 200,
        "adx_period": 14, "adx_min": 24, "atr_period": 14,
        "htf_ema": 50, "pullback_n": 5, "pullback_depth_atr": 0.25,
        "trigger_close_long": 0.65, "trigger_close_short": 0.35,
        "stop_buffer_atr": 0.25, "min_stop_atr": 0.50,
        "max_stop_atr": 2.50, "chandelier_atr": 3.0,
        "target_r": 2.0, "time_stop": 30, "risk_pct": 0.005,
    },
    "4h": {
        "fast_ema": 20, "medium_ema": 50, "slow_ema": 200,
        "adx_period": 14, "adx_min": 22, "atr_period": 14,
        "htf_ema": 50, "pullback_n": 5, "pullback_depth_atr": 0.25,
        "trigger_close_long": 0.65, "trigger_close_short": 0.35,
        "stop_buffer_atr": 0.25, "min_stop_atr": 0.50,
        "max_stop_atr": 3.00, "chandelier_atr": 3.0,
        "target_r": 2.0, "time_stop": 30, "risk_pct": 0.0075,
    },
    "1d": {
        "fast_ema": 20, "medium_ema": 50, "slow_ema": 200,
        "adx_period": 14, "adx_min": 20, "atr_period": 14,
        "htf_ema": 50, "pullback_n": 5, "pullback_depth_atr": 0.25,
        "trigger_close_long": 0.65, "trigger_close_short": 0.35,
        "stop_buffer_atr": 0.25, "min_stop_atr": 0.50,
        "max_stop_atr": 3.00, "chandelier_atr": 3.0,
        "target_r": 2.0, "time_stop": 40, "risk_pct": 0.01,
    },
}

# V4.2 convergence/burn-in requirements.
BURN_IN_BASE_BARS = {"2h": 600, "4h": 300, "1d": 350}
POST_CONVERGENCE_BUFFER_BARS = 100
EMA_TOLERANCE_PRICE_FRACTION = 0.0005       # 0.05% of price
ATR_TOLERANCE_RELATIVE = 0.02               # 2.0%
ADX_DI_TOLERANCE_POINTS = 1.0
STARTING_EQUITY_USDT = 1_000.0
LEVERAGE_CAP = 1.0                          # no liquidation model at 1x

MAKER_RATE = PERPETUAL_FEES.maker
TAKER_RATE = PERPETUAL_FEES.taker
COST_MODEL = "PER_FILL_MAKER_5BPS_TAKER_2BPS_V1"
FUNDING_MODEL = "UNAVAILABLE_EXCLUDED_ZERO"

ENGINE_VERSION = "V4.2-net.1"
DATA_PROCESSING_VERSION = "V4.2-bugfix2"
# Production research must use an independently verified cutoff. Diagnostic
# mode may infer one, but it never claims verified completeness.
CUTOFF_MODE_STRICT = "strict"
CUTOFF_MODE_DIAGNOSTIC = "diagnostic"
CUTOFF_MODES = (CUTOFF_MODE_STRICT, CUTOFF_MODE_DIAGNOSTIC)
DEFAULT_CUTOFF_MODE = CUTOFF_MODE_STRICT
DIAGNOSTIC_WARNING = (
    "DIAGNOSTIC MODE: this run is NOT independently verified. The cutoff may be "
    "inferred or explicitly supplied, but diagnostic mode never asserts verified "
    "completeness. Incomplete final candles are excluded, but the results are not "
    "production-grade."
)
# Sizing validation is disabled by default. No exchange-specific BTCUSDT
# minimum quantity / precision / notional values are asserted here because no
# verified exchange constraint specification was supplied with the frozen
# strategy. Callers may supply explicit constraints at run time.
DEFAULT_EXECUTION_CONSTRAINTS: dict[str, Any] = {
    "min_quantity": None,
    "quantity_precision": None,
    "min_notional": None,
}
# Used only for data-quality gap detection. Missing candles are reported, never
# fabricated, and are not inserted into any indicator or signal calculation.
TIMEFRAME_INTERVALS = {
    "2h": pd.Timedelta(2, unit="h"),
    "4h": pd.Timedelta(4, unit="h"),
    "1d": pd.Timedelta(1, unit="D"),
    "1w": pd.Timedelta(7, unit="D"),
}
# Calendar timeframes cannot be represented by a fixed Timedelta (month length
# varies). They are supported by the HTF completion helpers through
# htf_period_end(); they are not base timeframes in this engine.
CALENDAR_TIMEFRAMES = {"1m": "calendar_month"}
HTF_TIMEFRAMES = {"2h": "1d", "4h": "1d", "1d": "1w"}


# =============================================================================
# DATA AND INDICATORS
# =============================================================================

@dataclass
class WarmupResult:
    passed: bool
    convergence_index: int | None
    evaluation_start_index: int | None
    burn_in_bars: int
    attempts: int
    reason: str
    details: dict[str, Any]


def read_ohlcv(path: Path, *, reject_suspicious: bool = False) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"OHLCV CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    rows_loaded = len(df)
    format_used = "header"

    # Binance headerless 12-column kline support.
    if not {"open", "high", "low", "close"}.issubset(df.columns):
        raw = pd.read_csv(path, header=None)
        if raw.shape[1] < 6:
            raise ValueError(f"{path.name}: expected at least six OHLCV columns")
        names = [
            "timestamp", "open", "high", "low", "close", "volume",
            "close_timestamp", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
        ]
        raw.columns = names[:raw.shape[1]]
        df = raw
        rows_loaded = len(df)
        format_used = "headerless_binance"

    if "timestamp" not in df.columns:
        candidates = [c for c in df.columns if "time" in c]
        if not candidates:
            raise ValueError(f"{path.name}: timestamp/open_time column missing")
        df = df.rename(columns={candidates[0]: "timestamp"})

    required = ["timestamp", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns: {missing}")

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df:
        df["volume"] = np.nan
    else:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    if reject_suspicious:
        numeric = df[["timestamp", "open", "high", "low", "close", "volume"]]
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"{path.name}: missing or non-finite OHLCV/timestamp values")
        if (df["volume"] < 0).any():
            raise ValueError(f"{path.name}: negative volume")
        if not df["timestamp"].is_monotonic_increasing or df["timestamp"].duplicated().any():
            raise ValueError(f"{path.name}: unordered or duplicate timestamps")
    df = df.dropna(subset=required).copy()
    rows_after_numeric = len(df)
    if df.empty:
        raise ValueError(f"{path.name}: no valid OHLCV rows")

    median_ts = float(df["timestamp"].median())
    unit: Literal["ns", "us", "ms", "s"]
    if median_ts > 10**17:
        unit = "ns"
    elif median_ts > 10**14:
        unit = "us"
    elif median_ts > 10**11:
        unit = "ms"
    else:
        unit = "s"
    df["datetime"] = pd.to_datetime(df["timestamp"], unit=unit, utc=True, errors="coerce")
    if reject_suspicious and df["datetime"].isna().any():
        raise ValueError(f"{path.name}: invalid UTC timestamps")
    df = df.dropna(subset=["datetime"]).sort_values("datetime")
    rows_after_timestamp = len(df)
    if df.empty:
        raise ValueError(f"{path.name}: no valid UTC timestamps")

    rows_before_dedupe = len(df)
    df = df.drop_duplicates("datetime", keep="last")
    duplicate_timestamps_removed = rows_before_dedupe - len(df)
    df = df.set_index("datetime")

    if not df.index.is_monotonic_increasing:
        raise ValueError(f"{path.name}: timestamps are not increasing")
    if df.index.has_duplicates:
        raise ValueError(f"{path.name}: duplicate timestamps remain")

    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{path.name}: non-positive OHLC price")
    bad = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    )
    if bad.any():
        raise ValueError(f"{path.name}: invalid OHLC relationship on {int(bad.sum())} rows")

    result = df[["open", "high", "low", "close", "volume"]].astype(float)
    if "funding_rate" in df or "funding_mark_price" in df:
        if not {"funding_rate", "funding_mark_price"}.issubset(df):
            raise ValueError("Funding requires a rate and settlement mark price at each event")
        rate = pd.to_numeric(df["funding_rate"], errors="raise")
        mark = pd.to_numeric(df["funding_mark_price"], errors="raise")
        events = rate.notna()
        if (not np.isfinite(rate[events]).all() or not np.isfinite(mark[events]).all()
                or (mark[events] <= 0).any() or mark[~events].notna().any()):
            raise ValueError("Invalid funding settlement")
        result["funding_rate"] = rate
        result["funding_mark_price"] = mark
    if "warmup_only" in df:
        mask = pd.to_numeric(df["warmup_only"], errors="raise")
        if not mask.isin([0, 1]).all() or not mask.is_monotonic_decreasing:
            raise ValueError("warmup_only must be a leading prefix of 1 followed by 0")
        result["warmup_only"] = mask.astype(bool)
    unit_fields = ["funding_open_per_unit", "funding_inside_per_unit"]
    if any(k in df for k in unit_fields):
        if not all(k in df for k in unit_fields) or "funding_rate" in df:
            raise ValueError("Supply one complete funding representation")
        result[unit_fields] = df[unit_fields].astype(float)
        if not np.isfinite(result[unit_fields].to_numpy()).all():
            raise ValueError("Funding payments must be finite")
    result.attrs["data_quality"] = {
        "source": str(path),
        "format": format_used,
        "rows_loaded": int(rows_loaded),
        "rows_after_numeric_validation": int(rows_after_numeric),
        "rows_dropped_invalid_numeric": int(rows_loaded - rows_after_numeric),
        "rows_dropped_invalid_timestamp": int(rows_after_numeric - rows_after_timestamp),
        "rows_usable": int(len(result)),
        "timestamp_unit": unit,
        "timestamps_utc": True,
        "sorted_chronologically": True,
        "duplicate_timestamps_removed": int(duplicate_timestamps_removed),
        "ohlc_valid": True,
        "first_candle": str(result.index.min()),
        "last_candle": str(result.index.max()),
    }
    return result


def detect_missing_candles(df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    """Report gaps in the observed candle sequence without fabricating candles."""
    expected = TIMEFRAME_INTERVALS.get(timeframe)
    if expected is None:
        return {
            "expected_interval": None,
            "missing_candle_count": 0,
            "gap_event_count": 0,
            "gap_events": [],
            "is_complete": None,
        }

    times = pd.DatetimeIndex(df.index)
    events: list[dict[str, Any]] = []
    missing_total = 0
    if len(times) > 1:
        deltas = times.to_series().diff().tolist()
        for pos in range(1, len(times)):
            delta = deltas[pos]
            if pd.isna(delta) or delta <= expected:
                continue
            missing = int(round(float(delta / expected))) - 1
            missing = max(missing, 1)
            missing_total += missing
            events.append({
                "previous_candle": str(times[pos - 1]),
                "next_candle": str(times[pos]),
                "observed_interval": str(delta),
                "missing_candles": missing,
            })

    return {
        "expected_interval": str(expected),
        "missing_candle_count": int(missing_total),
        "gap_event_count": int(len(events)),
        "gap_events": events,
        "is_complete": bool(missing_total == 0),
    }


def build_data_quality_report(df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    report = dict(df.attrs.get("data_quality", {}))
    report["missing_candles"] = detect_missing_candles(df, timeframe)
    return report


# =============================================================================
# TIMESTAMP COMPLETION HELPERS
# =============================================================================
# Candle completion is always derived from the *configured* timeframe duration.
# It is never inferred from the next observed candle. This is the core fix for
# higher-timeframe lookahead across missing base candles.

def ensure_utc_index(index: pd.Index, label: str) -> pd.DatetimeIndex:
    values = pd.DatetimeIndex(index)
    if values.tz is None:
        raise ValueError(f"{label}: timestamps must be UTC-aware")
    return values.tz_convert("UTC")


def timeframe_interval(timeframe: str) -> pd.Timedelta:
    try:
        return TIMEFRAME_INTERVALS[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe interval: {timeframe!r}") from exc


def as_utc_timestamp(value: Any, label: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp


def infer_timeframe_from_index(index: pd.Index) -> str:
    """Standalone-helper fallback only.

    Production runs always pass the configured timeframe explicitly. This
    fallback exists so low-level helpers remain usable in isolation and uses the
    median spacing only to select an interval label, never to time a candle
    close.
    """
    values = ensure_utc_index(index, "inferred timeframe")
    if len(values) < 2:
        raise ValueError("Cannot infer timeframe from fewer than two candles")
    median_delta = pd.Series(values).diff().dropna().median()
    candidates = [
        (name, interval) for name, interval in TIMEFRAME_INTERVALS.items()
        if interval == median_delta
    ]
    if not candidates:
        raise ValueError(f"Cannot infer a supported timeframe from spacing {median_delta}")
    return candidates[0][0]


def exchange_boundary_aligned(open_time: pd.Timestamp, timeframe: str) -> bool:
    """Check the observed open against the exchange candle boundary convention."""
    stamp = as_utc_timestamp(open_time, "HTF candle open")
    midnight = (
        stamp.hour == 0 and stamp.minute == 0
        and stamp.second == 0 and stamp.microsecond == 0
    )
    if timeframe in CALENDAR_TIMEFRAMES:
        return midnight and stamp.day == 1
    if timeframe == "1w":
        return midnight and stamp.weekday() == 0
    if timeframe == "1d":
        return midnight
    interval = timeframe_interval(timeframe)
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (stamp - epoch) % interval == pd.Timedelta(0)


def htf_period_end(open_time: Any, timeframe: str) -> pd.Timestamp:
    """Configured completion timestamp for a candle open.

    Fixed-duration timeframes add the configured duration. Calendar months use
    the next calendar month boundary, so February, leap years and year-end are
    handled by the calendar rather than by an approximate day count.
    """
    stamp = as_utc_timestamp(open_time, "candle open")
    if timeframe in CALENDAR_TIMEFRAMES:
        return stamp + pd.offsets.MonthBegin(1)
    return stamp + timeframe_interval(timeframe)


def timeframe_duration_label(timeframe: str) -> str:
    if timeframe in CALENDAR_TIMEFRAMES:
        return CALENDAR_TIMEFRAMES[timeframe]
    return str(timeframe_interval(timeframe))


def validate_cutoff_mode(mode: str) -> str:
    if mode not in CUTOFF_MODES:
        raise ValueError(
            f"Invalid cutoff mode {mode!r}. Expected one of {CUTOFF_MODES}."
        )
    return mode


def resolve_data_cutoff(base: pd.DataFrame, timeframe: str,
                        explicit_cutoff: Any = None,
                        mode: str = DEFAULT_CUTOFF_MODE) -> dict[str, Any]:
    """Resolve the verified/inferred data cutoff and candle-exclusion policy.

    Strict mode (default) requires an independently supplied cutoff. It never
    infers one from the expected close of the final base candle, because an
    expected close does not prove that the candle row was received or finalized.

    Diagnostic mode may infer a cutoff from the data, but it marks the cutoff as
    unverified and excludes the final observed base candle. Diagnostic mode
    remains unverified even when an explicit cutoff is supplied: selecting
    diagnostic mode means no independent verification is being asserted.
    """
    validate_cutoff_mode(mode)
    base_index = ensure_utc_index(base.index, "base data")
    if len(base_index) == 0:
        raise ValueError("base data is empty")
    interval = timeframe_interval(timeframe)
    last_open = base_index[-1]
    availability_end = last_open + interval

    if explicit_cutoff is not None:
        try:
            cutoff = as_utc_timestamp(explicit_cutoff, "data cutoff")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(
                f"Invalid data cutoff {explicit_cutoff!r}: {exc}"
            ) from exc
        if pd.isna(cutoff):
            raise ValueError(f"Invalid data cutoff: {explicit_cutoff!r} is NaT")
        if cutoff > availability_end:
            raise ValueError(
                "Data cutoff "
                f"{cutoff} extends beyond the last available base candle close "
                f"{availability_end}. A cutoff cannot certify data that is not "
                "present in the supplied dataset."
            )
        source = "explicit"
        # Only strict mode asserts independent verification. An explicit value
        # in diagnostic mode is still an exploratory, unverified input.
        verified = mode == CUTOFF_MODE_STRICT
    else:
        if mode == CUTOFF_MODE_STRICT:
            raise ValueError(
                "Strict cutoff mode requires an independently verified data "
                "cutoff. No --data-cutoff was supplied. The expected close of "
                "the final base candle is not proof that its data was received "
                "or finalized. Supply --data-cutoff <UTC ISO-8601 timestamp>, "
                "or explicitly select --cutoff-mode diagnostic for exploratory "
                "analysis."
            )
        # The final observed candle is treated as unverified. Verify nothing
        # beyond the moment that candle opened.
        cutoff = last_open
        source = "inferred_from_final_base_candle_open"
        verified = False

    close_times = base_index + interval
    included_mask = np.asarray(close_times <= cutoff)
    if not included_mask.any():
        raise ValueError(
            f"Data cutoff {cutoff} precedes completion of the first base candle "
            f"({base_index[0] + interval}). No usable base candles remain."
        )
    included_index = base_index[included_mask]
    excluded_index = base_index[~included_mask]
    last_included = included_index[-1]

    details: list[dict[str, Any]] = []
    for stamp in excluded_index:
        expected_close = stamp + interval
        if verified:
            reason = "completion_after_verified_data_cutoff"
        else:
            reason = "final_base_candle_completion_not_verified"
        details.append({
            "timestamp": str(stamp),
            "expected_close": str(expected_close),
            "reason": reason,
        })
    grouped: dict[str, list[str]] = {}
    for item in details:
        grouped.setdefault(item["reason"], []).append(item["timestamp"])
    excluded_reasons = [
        {"reason": reason, "count": len(stamps), "timestamps": stamps}
        for reason, stamps in grouped.items()
    ]

    return {
        "value": cutoff,
        "source": source,
        "verified": bool(verified),
        "mode": mode,
        "timeframe": timeframe,
        "input_availability_end": availability_end,
        "last_base_candle_timestamp": last_open,
        "last_base_candle_included": bool(last_open in included_index),
        "last_included_base_candle": last_included,
        "last_verified_base_candle": last_included if verified else None,
        "excluded_incomplete_candles": int(len(excluded_index)),
        "excluded_candle_reasons": excluded_reasons,
        "excluded_candle_details": details,
        "rule": (
            "A base candle is included only when open + configured timeframe "
            "duration <= data cutoff. An expected close alone never certifies a "
            "candle in strict mode."
        ),
    }


def derive_data_cutoff(base: pd.DataFrame, timeframe: str,
                       explicit_cutoff: Any = None,
                       mode: str = DEFAULT_CUTOFF_MODE
                       ) -> tuple[pd.Timestamp, str]:
    """Backward-compatible wrapper returning (cutoff, source)."""
    policy = resolve_data_cutoff(base, timeframe, explicit_cutoff, mode)
    return policy["value"], policy["source"]


def required_base_opens(htf_open: Any, htf_timeframe: str,
                        base_timeframe: str) -> list[pd.Timestamp]:
    """Expected base-timeframe candle opens covering one HTF interval."""
    start = as_utc_timestamp(htf_open, "HTF candle open")
    end = htf_period_end(start, htf_timeframe)
    step = timeframe_interval(base_timeframe)
    if end <= start:
        return []
    last_start = end - step
    if last_start < start:
        return []
    return list(pd.date_range(start=start, end=last_start, freq=step))


def base_coverage_for_htf(htf_open: Any, htf_timeframe: str,
                          base_timeframe: str,
                          base_opens: set[pd.Timestamp]) -> dict[str, Any]:
    required = required_base_opens(htf_open, htf_timeframe, base_timeframe)
    missing = [stamp for stamp in required if stamp not in base_opens]
    return {
        "required_base_candles": int(len(required)),
        "missing_base_candles": int(len(missing)),
        "missing_base_sample": [str(stamp) for stamp in missing[:5]],
        "sufficient": bool(required) and not missing,
    }


def htf_completion_frame(htf: pd.DataFrame, htf_timeframe: str,
                         data_cutoff: pd.Timestamp,
                         base: pd.DataFrame | None = None,
                         base_timeframe: str | None = None,
                         cutoff_source: str | None = None,
                         cutoff_verified: bool | None = None,
                         cutoff_mode: str | None = None
                         ) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Classify every HTF candle as COMPLETE, INCOMPLETE or UNKNOWN.

    A candle is complete only when all of the following hold:
    - its open is aligned to the exchange timeframe boundary;
    - its full configured duration has elapsed at or before the data cutoff;
    - its underlying base-timeframe candles are all present (when base data is
      supplied), including no uncertain/incomplete final base candle.
    Completion is never inferred from the next observed candle or from the mere
    existence of an OHLCV row.
    """
    cutoff = as_utc_timestamp(data_cutoff, "data cutoff")
    index = ensure_utc_index(htf.index, "HTF data")
    if base is not None and base_timeframe is None:
        raise ValueError(
            "base_timeframe must be supplied when base coverage is checked"
        )
    base_opens: set[pd.Timestamp] | None = None
    if base is not None:
        if base_timeframe not in TIMEFRAME_INTERVALS:
            raise ValueError(
                f"Unsupported base timeframe for HTF coverage: {base_timeframe!r}"
            )
        base_opens = set(ensure_utc_index(base.index, "base data"))

    rows: list[dict[str, Any]] = []
    for open_time in index:
        available_at = htf_period_end(open_time, htf_timeframe)
        aligned = exchange_boundary_aligned(open_time, htf_timeframe)
        coverage: dict[str, Any] = {}
        if not aligned:
            status = "UNKNOWN"
            reason = "open_not_aligned_to_exchange_timeframe_boundary"
        elif available_at > cutoff:
            status = "INCOMPLETE"
            reason = "completion_after_data_cutoff"
        else:
            if base_opens is not None:
                coverage = base_coverage_for_htf(
                    open_time, htf_timeframe, cast(str, base_timeframe), base_opens
                )
            if base_opens is not None and not coverage["sufficient"]:
                status = "INCOMPLETE"
                reason = "underlying_base_candles_missing_or_incomplete"
            else:
                status = "COMPLETE"
                reason = ""
        row = {
            "htf_open": open_time,
            "htf_available_at": available_at,
            "htf_completion_status": status,
            "htf_exclusion_reason": reason,
        }
        if base_opens is not None:
            row["required_base_candles"] = coverage.get("required_base_candles", 0)
            row["missing_base_candles"] = coverage.get("missing_base_candles", 0)
            row["missing_base_sample"] = coverage.get("missing_base_sample", [])
        rows.append(row)

    frame = pd.DataFrame(rows, index=index)
    frame.index.name = htf.index.name
    excluded = frame[frame["htf_completion_status"] != "COMPLETE"]
    complete = frame[frame["htf_completion_status"] == "COMPLETE"]
    report = {
        "htf_timeframe": htf_timeframe,
        "expected_interval": timeframe_duration_label(htf_timeframe),
        "data_cutoff": str(cutoff),
        "cutoff_source": cutoff_source or "unspecified",
        "cutoff_verified": bool(cutoff_verified) if cutoff_verified is not None else False,
        "cutoff_mode": cutoff_mode or "unspecified",
        "base_coverage_checked": bool(base is not None),
        "base_timeframe": base_timeframe,
        "complete_count": int(len(complete)),
        "incomplete_count": int(
            (frame["htf_completion_status"] == "INCOMPLETE").sum()
        ),
        "unknown_count": int(
            (frame["htf_completion_status"] == "UNKNOWN").sum()
        ),
        "excluded_candle_count": int(len(excluded)),
        "excluded_candles": [
            {
                "open": str(row["htf_open"]),
                "available_at": str(row["htf_available_at"]),
                "status": row["htf_completion_status"],
                "reason": row["htf_exclusion_reason"],
            }
            for _, row in excluded.iterrows()
        ],
        "last_complete_candle_open": (
            str(complete["htf_open"].iloc[-1]) if len(complete) else None
        ),
        "last_complete_available_at": (
            str(complete["htf_available_at"].iloc[-1]) if len(complete) else None
        ),
        "rule": (
            "Usable only when the open is exchange-boundary aligned, the full "
            "configured duration ends at or before the data cutoff, and all "
            "underlying base candles are present. UNKNOWN completion is excluded."
        ),
    }
    return frame, report



def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_source_path() -> Path:
    return Path(__file__).resolve()


def engine_source_hash() -> str:
    return hashlib.sha256((sha256_file(engine_source_path()) + sha256_file(Path(__file__).with_name("exit_paths.py")) + sha256_file(PROJECT_ROOT / "backend/app/core/fills.py")).encode()).hexdigest()


def imported_execution_module_fingerprints() -> dict[str, Any]:
    """Fingerprint the execution stack that can alter numeric behaviour."""
    fingerprints: dict[str, Any] = {}
    for name, module in (("numpy", np), ("pandas", pd)):
        module_file = getattr(module, "__file__", None)
        fingerprints[name] = {
            "version": str(getattr(module, "__version__", "unknown")),
            "module_file": str(module_file) if module_file else None,
            "sha256": sha256_file(Path(module_file)) if module_file else None,
        }
    return fingerprints


def execution_model_settings() -> dict[str, Any]:
    return {
        "maker_rate": MAKER_RATE, "taker_rate": TAKER_RATE, "slippage_rate": 0.0,
        "entry_model": "NEXT_CANDLE_OPEN",
        "exit_priority": [
            "GAP_STOP",
            "GAP_TARGET_LIMIT",
            "STOP_BOTH_TOUCHED_STOP_FIRST",
            "INITIAL_STOP",
            "TRAILING_STOP",
            "TARGET",
            "TIME_STOP",
            "DATA_END",
        ],
        "gap_events_evaluated_at_open": True,
        "same_candle_stop_first": True,
        "trailing_stop_model": "CHANDELIER_AFTER_CLOSE_NEXT_CANDLE",
        "exit_fill_model": "open_for_gap_stop_stop_price_for_intrabar_target_price_for_limit",
        "intrabar_settlement_rule": "Open settlements before entry; intrabar exits precede later settlements; time/data-end exits settle at close.",
        "mae_mfe_model": "completed_bars_plus_exit_fill_excludes_post_exit_extremes",
        "leverage_cap": LEVERAGE_CAP,
        "starting_equity_usdt": STARTING_EQUITY_USDT,
        "market_mode": "binance_usdt_perpetual_simulation",
        "cost_model": COST_MODEL,
        "funding_model": FUNDING_MODEL,
        "data_processing_version": DATA_PROCESSING_VERSION,
    }


V42_SPEC_PARITY_REPORT: dict[str, Any] = {
    "frozen_specification_file_found": False,
    "parity_certified": False,
    "confirmed_discrepancy": None,
    "implemented_conditions_observed": {
        "long_ema_hierarchy": "ema_fast > ema_mid and close > ema_slow and ema_mid > ema_slow",
        "short_ema_hierarchy": "ema_fast < ema_mid and close < ema_slow and ema_mid < ema_slow",
        "long_di_filter": "plus_di > minus_di",
        "short_di_filter": "minus_di > plus_di",
    },
    "note": (
        "No frozen V4.2 strategy specification document was found in the project. "
        "The implemented EMA hierarchy and directional DI filters were inspected and "
        "left unchanged because there is no authoritative frozen text to compare "
        "against. Parity therefore cannot be certified; no requirement was invented."
    ),
}


def compute_run_id(timeframe: str, cfg: dict[str, Any], base_path: Path,
                   htf_path: Path, data_cutoff: Any = None,
                   execution_constraints: dict[str, Any] | None = None,
                   engine_source_sha256: str | None = None,
                   cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                   data_cutoff_verified: bool | None = None,
                   cutoff_policy: dict[str, Any] | None = None) -> str:
    """Deterministic identifier for an engine/data/configuration combination.

    The identity includes cutoff provenance and the candle-completion policy, so
    verified and inferred cutoffs (or strict and diagnostic modes) can never
    share a run ID.
    """
    constraints = dict(DEFAULT_EXECUTION_CONSTRAINTS)
    if execution_constraints:
        constraints.update(execution_constraints)
    mode = validate_cutoff_mode(cutoff_mode)
    if cutoff_policy is not None:
        cutoff_value = cutoff_policy.get("value")
        cutoff_source = cutoff_policy.get("source")
        verified = bool(cutoff_policy.get("verified", False))
        mode = str(cutoff_policy.get("mode", mode))
    else:
        cutoff_value = data_cutoff
        cutoff_source = "explicit" if data_cutoff is not None else None
        if data_cutoff_verified is None:
            verified = bool(data_cutoff is not None and mode == CUTOFF_MODE_STRICT)
        else:
            verified = bool(data_cutoff_verified)
    payload = {
        "engine": "EMA Pullback V4.2 OHLCV-only",
        "engine_version": ENGINE_VERSION,
        "engine_source_sha256": engine_source_sha256 or engine_source_hash(),
        "imported_execution_modules": imported_execution_module_fingerprints(),
        "data_processing_version": DATA_PROCESSING_VERSION,
        "timeframe": timeframe,
        "configuration": cfg,
        "execution_model": execution_model_settings(),
        "execution_constraints": constraints,
        "base_source_sha256": sha256_file(base_path),
        "htf_source_sha256": sha256_file(htf_path),
        "cutoff_policy": {
            "mode": mode,
            "data_cutoff": (
                str(as_utc_timestamp(cutoff_value, "data cutoff"))
                if cutoff_value is not None else None
            ),
            "source": cutoff_source,
            "verified": verified,
            "base_candle_inclusion": (
                "open_plus_configured_duration_lte_data_cutoff"
            ),
            "incomplete_base_candles": "excluded_from_indicators_signals_trades",
            "htf_completion": (
                "exchange_boundary_aligned_and_full_duration_lte_cutoff_"
                "and_underlying_base_coverage_complete"
            ),
            "completion_basis": "verified_cutoff_not_expected_close",
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def default_output_directory(timeframe: str) -> Path:
    return OUTPUT_DIRECTORY / timeframe


def result_paths(output_dir: Path, timeframe: str) -> dict[str, Path]:
    return {
        "signals": output_dir / f"{timeframe}_signals.csv",
        "trades": output_dir / f"{timeframe}_trades.csv",
        "audit": output_dir / f"{timeframe}_trade_audit.jsonl",
        "summary": output_dir / f"{timeframe}_summary.json",
        "metrics": output_dir / f"{timeframe}_metrics.csv",
    }


def json_safe(value: Any) -> Any:
    """Convert numpy/pandas scalars and non-finite floats to JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    return value


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder RMA seeded with the first period's SMA, then recursive smoothing."""
    period = int(period)
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=series.index, name=series.name)
    seed_end = None
    for end in range(period - 1, len(values)):
        window = values[end - period + 1:end + 1]
        if np.isfinite(window).all():
            seed_end = end
            out[end] = float(window.mean())
            break
    if seed_end is None:
        return pd.Series(out, index=series.index, name=series.name)
    for i in range(seed_end + 1, len(values)):
        if not np.isfinite(values[i]):
            out[i] = np.nan
        elif np.isfinite(out[i - 1]):
            out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return pd.Series(out, index=series.index, name=series.name)


def add_indicators(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    x = df.copy()
    x["ema_fast"] = ema(x["close"], cfg["fast_ema"])
    x["ema_mid"] = ema(x["close"], cfg["medium_ema"])
    x["ema_slow"] = ema(x["close"], cfg["slow_ema"])

    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            x["high"] - x["low"],
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr"] = wilder_rma(tr, cfg["atr_period"])

    up = x["high"].diff()
    down = -x["low"].diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=x.index
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=x.index
    )
    atr_for_di = x["atr"].replace(0, np.nan)
    x["plus_di"] = 100.0 * wilder_rma(plus_dm, cfg["adx_period"]) / atr_for_di
    x["minus_di"] = 100.0 * wilder_rma(minus_dm, cfg["adx_period"]) / atr_for_di
    denom = (x["plus_di"] + x["minus_di"]).replace(0, np.nan)
    dx = 100.0 * (x["plus_di"] - x["minus_di"]).abs() / denom
    x["adx"] = wilder_rma(dx, cfg["adx_period"])
    return x


def attach_htf_indicators(base: pd.DataFrame, htf: pd.DataFrame,
                          htf_ema_period: int,
                          timeframe: str | None = None,
                          htf_timeframe: str | None = None,
                          data_cutoff: Any = None,
                          cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                          cutoff_policy: dict[str, Any] | None = None,
                          completion: pd.DataFrame | None = None
                          ) -> pd.DataFrame:
    """Attach only HTF candles that were verifiably complete at each decision.

    Completion comes from the configured timeframe duration, an independently
    verified cutoff and full underlying base-candle coverage. It is never
    inferred from the next observed candle or from the existence of an OHLCV row.

    ``cutoff_policy`` may carry an already-resolved policy from ``run_analysis``.
    It is used when the base frame has already been truncated to the cutoff, so
    the cutoff must not be re-validated against the shorter frame.
    """
    base_tf = timeframe or infer_timeframe_from_index(base.index)
    htf_tf = htf_timeframe or infer_timeframe_from_index(htf.index)
    if cutoff_policy is not None:
        policy = cutoff_policy
        cutoff = as_utc_timestamp(policy["value"], "data cutoff")
    else:
        policy = resolve_data_cutoff(base, base_tf, data_cutoff, cutoff_mode)
        cutoff = policy["value"]

    if completion is None:
        completion, _ = htf_completion_frame(
            htf, htf_tf, cutoff,
            base=base, base_timeframe=base_tf,
            cutoff_source=policy["source"],
            cutoff_verified=policy["verified"],
            cutoff_mode=policy["mode"],
        )
    complete_mask = completion["htf_completion_status"] == "COMPLETE"

    # Compute the HTF EMA only from complete HTF candles, so excluded/incomplete
    # candles cannot influence later lower-timeframe indicator values.
    higher = htf[["close"]].copy()
    higher["htf_ema"] = np.nan
    if complete_mask.any():
        higher.loc[complete_mask, "htf_ema"] = ema(
            htf.loc[complete_mask, "close"], htf_ema_period
        )
    higher = higher.join(
        completion[["htf_available_at", "htf_completion_status", "htf_exclusion_reason"]]
    )
    higher = higher.reset_index(names="htf_open")
    usable = higher[complete_mask.to_numpy()].copy()
    usable = usable.sort_values("htf_available_at")

    left = base.reset_index(names="base_open")
    base_open = ensure_utc_index(pd.DatetimeIndex(left["base_open"]), "base data")
    left["base_close_time"] = base_open + timeframe_interval(base_tf)

    right_columns = ["htf_available_at", "close", "htf_ema", "htf_completion_status"]
    right = usable[right_columns].rename(columns={"close": "htf_close"})
    merged = pd.merge_asof(
        left.sort_values("base_close_time"),
        right,
        left_on="base_close_time",
        right_on="htf_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    merged = merged.set_index("base_open").drop(columns=["htf_available_at"])
    merged.index.name = base.index.name
    # Rows completing after the resolved cutoff are uncertain and must not
    # receive an HTF attachment, even if the caller passed untruncated data.
    beyond_cutoff = merged["base_close_time"] > cutoff
    if bool(beyond_cutoff.any()):
        merged.loc[beyond_cutoff, "htf_close"] = np.nan
        merged.loc[beyond_cutoff, "htf_ema"] = np.nan
        merged.loc[beyond_cutoff, "htf_completion_status"] = None
    # Preserve the caller's original row order exactly.
    merged = merged.reindex(base.index)
    return merged


def indicator_snapshot(df: pd.DataFrame, htf: pd.DataFrame,
                       cfg: dict[str, Any], index: int,
                       timeframe: str,
                       data_cutoff: Any = None,
                       cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                       cutoff_policy: dict[str, Any] | None = None,
                       completion: pd.DataFrame | None = None
                       ) -> dict[str, float]:
    """Recompute indicators from a later initialisation point for convergence."""
    # The second initialisation point is fixed one burn-in block after the
    # beginning of the dataset. As candidate advances, both calculations gain
    # more post-initialisation history and can converge.
    base_cut_start = BURN_IN_BASE_BARS[timeframe]
    base_cut = df.iloc[base_cut_start: index + 1]
    calc = add_indicators(base_cut, cfg).iloc[-1]

    # Base close is derived from the configured timeframe duration. The final
    # base candle is handled explicitly and is never extended to a later candle.
    base_time = as_utc_timestamp(df.index[index], "base candle")
    base_close_time = base_time + timeframe_interval(timeframe)

    htf_tf = HTF_TIMEFRAMES[timeframe]
    if cutoff_policy is not None:
        policy = cutoff_policy
        cutoff = as_utc_timestamp(policy["value"], "data cutoff")
    else:
        policy = resolve_data_cutoff(df, timeframe, data_cutoff, cutoff_mode)
        cutoff = policy["value"]
    if base_close_time > cutoff:
        return {}
    if completion is None:
        completion, _ = htf_completion_frame(
            htf, htf_tf, cutoff,
            base=df, base_timeframe=timeframe,
            cutoff_source=policy["source"],
            cutoff_verified=policy["verified"],
            cutoff_mode=policy["mode"],
        )
    usable = completion[
        (completion["htf_completion_status"] == "COMPLETE")
        & (completion["htf_available_at"] <= base_close_time)
    ]
    # Begin the independent HTF initialisation at the first HTF candle whose
    # open is at or after the base burn-in boundary.
    htf_cut_start = df.index[base_cut_start]
    eligible = usable.index[usable.index >= htf_cut_start]
    if len(eligible) == 0:
        return {}
    htf_usable = htf.loc[usable.index]
    htf_cut = htf_usable.loc[eligible[0]:eligible[-1]]
    if len(htf_cut) == 0:
        return {}
    htf_ema_value = ema(htf_cut["close"], cfg["htf_ema"]).iloc[-1]

    return {
        "ema_fast": float(calc["ema_fast"]),
        "ema_mid": float(calc["ema_mid"]),
        "ema_slow": float(calc["ema_slow"]),
        "atr": float(calc["atr"]),
        "adx": float(calc["adx"]),
        "plus_di": float(calc["plus_di"]),
        "minus_di": float(calc["minus_di"]),
        "htf_ema": float(htf_ema_value),
    }


def check_convergence(df: pd.DataFrame, htf: pd.DataFrame, cfg: dict[str, Any],
                      timeframe: str,
                      data_cutoff: Any = None,
                      cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                      cutoff_policy: dict[str, Any] | None = None,
                      indicator_frame: pd.DataFrame | None = None,
                      completion: pd.DataFrame | None = None
                      ) -> WarmupResult:
    burn = BURN_IN_BASE_BARS[timeframe]
    full = indicator_frame if indicator_frame is not None else add_indicators(df, cfg)
    merged = indicator_frame if indicator_frame is not None else attach_htf_indicators(
        df, htf, cfg["htf_ema"], timeframe=timeframe,
        htf_timeframe=HTF_TIMEFRAMES[timeframe], data_cutoff=data_cutoff,
        cutoff_mode=cutoff_mode, cutoff_policy=cutoff_policy, completion=completion,
    )
    attempts = 0
    details: dict[str, Any] = {}

    # Candidate evaluation point is tested against an independently initialised
    # indicator set whose history begins one burn-in block later.
    candidate = 2 * burn
    while candidate < len(df) - POST_CONVERGENCE_BUFFER_BARS - 2:
        attempts += 1
        reference = full.iloc[candidate]
        alternate = indicator_snapshot(
            df, htf, cfg, candidate, timeframe, data_cutoff=data_cutoff,
            cutoff_mode=cutoff_mode, cutoff_policy=cutoff_policy, completion=completion,
        )
        if not alternate:
            candidate += burn
            continue

        checks: dict[str, bool] = {}
        for key in ("ema_fast", "ema_mid", "ema_slow"):
            a = float(reference[key])
            b = alternate[key]
            checks[key] = (
                np.isfinite(a) and np.isfinite(b)
                and abs(a - b) / max(abs(float(df["close"].iloc[candidate])), 1e-12)
                <= EMA_TOLERANCE_PRICE_FRACTION
            )
        checks["htf_ema"] = (
            np.isfinite(float(merged["htf_ema"].iloc[candidate]))
            and np.isfinite(alternate["htf_ema"])
            and abs(float(merged["htf_ema"].iloc[candidate]) - alternate["htf_ema"])
            / max(abs(float(merged["htf_close"].iloc[candidate])), 1e-12)
            <= EMA_TOLERANCE_PRICE_FRACTION
        )
        checks["atr"] = (
            np.isfinite(float(reference["atr"])) and np.isfinite(alternate["atr"])
            and float(reference["atr"]) > 0
            and abs(float(reference["atr"]) - alternate["atr"])
            / max(abs(float(reference["atr"])), 1e-12) <= ATR_TOLERANCE_RELATIVE
        )
        for key in ("adx", "plus_di", "minus_di"):
            a = float(reference[key])
            b = alternate[key]
            checks[key] = np.isfinite(a) and np.isfinite(b) and abs(a - b) <= ADX_DI_TOLERANCE_POINTS

        nonfinite = [
            key for key in ("ema_fast", "ema_mid", "ema_slow", "atr", "adx", "plus_di", "minus_di")
            if not np.isfinite(float(reference[key]))
        ]
        nonfinite += ["htf_ema"] if not np.isfinite(float(merged["htf_ema"].iloc[candidate])) else []
        passed = all(checks.values()) and not nonfinite
        details = {
            "checks": checks,
            "nonfinite": nonfinite,
            "candidate_time": str(df.index[candidate]),
            "attempt": attempts,
        }
        if passed:
            eval_start = candidate + POST_CONVERGENCE_BUFFER_BARS
            if "warmup_only" in df:
                eval_start = max(eval_start, int(df["warmup_only"].sum()))
                if eval_start >= len(df) - 1:
                    return WarmupResult(False, candidate, None, burn, attempts, "NO_DATA: warmup-only history", details)
            return WarmupResult(
                True, candidate, eval_start, burn, attempts,
                "CONVERGENCE_PASSED", details,
            )
        candidate += burn

    return WarmupResult(
        False, None, None, burn, attempts,
        "NO_DATA: convergence did not pass before data exhaustion", details,
    )


# =============================================================================
# SIGNAL ENGINE
# =============================================================================

def build_signals(base: pd.DataFrame, htf: pd.DataFrame, cfg: dict[str, Any],
                  timeframe: str, warmup: WarmupResult,
                  data_cutoff: Any = None,
                  cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                  cutoff_policy: dict[str, Any] | None = None,
                  indicator_frame: pd.DataFrame | None = None, execution_mode: str = "cpu"
                  ) -> pd.DataFrame:
    x = indicator_frame.copy() if indicator_frame is not None else attach_htf_indicators(
        add_indicators(base, cfg), htf, cfg["htf_ema"], timeframe=timeframe,
        htf_timeframe=HTF_TIMEFRAMES[timeframe], data_cutoff=data_cutoff,
        cutoff_mode=cutoff_mode, cutoff_policy=cutoff_policy,
    )
    x["signal"] = "WAIT"
    x["wait_reason"] = "NO_DATA"
    x["evaluation_enabled"] = False
    if not warmup.passed or warmup.evaluation_start_index is None:
        return x

    start = warmup.evaluation_start_index
    x.iloc[start:, cast(int, x.columns.get_loc("evaluation_enabled"))] = True

    n = int(cfg["pullback_n"])
    # Previous N bars only; trigger candle is excluded. Each historical candle
    # is compared to its own contemporaneous EMA20/ATR/EMA50.
    device_windows = None
    if execution_mode == "gpu" or (execution_mode == "auto" and len(x) >= 100_000):
        try:
            device = cuda_device()
            free, _ = device.cuda.runtime.memGetInfo()
            device_windows = pullback_windows(x, cfg, device, max(1, free // (256 * (n + 1))))
            x.attrs["signal_backend"] = "cuda"
        except (ImportError, OSError, RuntimeError, MemoryError) as exc:
            x.attrs["signal_fallback"] = str(exc)
    if device_windows is None:
        pb_touch_long = (x["low"] <= x["ema_fast"]).shift(1).rolling(n, min_periods=n).max().eq(1)
        pb_touch_short = (x["high"] >= x["ema_fast"]).shift(1).rolling(n, min_periods=n).max().eq(1)

        depth_floor_long = x["ema_mid"] - cfg["pullback_depth_atr"] * x["atr"]
        depth_ceiling_short = x["ema_mid"] + cfg["pullback_depth_atr"] * x["atr"]
        pb_window_close_below = (
            (x["close"] < depth_floor_long).shift(1).rolling(n, min_periods=n).max().eq(1)
        )
        pb_window_close_above = (
            (x["close"] > depth_ceiling_short).shift(1).rolling(n, min_periods=n).max().eq(1)
        )
        pullback_long = pb_touch_long & ~pb_window_close_below
        pullback_short = pb_touch_short & ~pb_window_close_above

        stop_window = n + 1
        x["long_stop"] = x["low"].rolling(stop_window, min_periods=stop_window).min() - cfg["stop_buffer_atr"] * x["atr"]
        x["short_stop"] = x["high"].rolling(stop_window, min_periods=stop_window).max() + cfg["stop_buffer_atr"] * x["atr"]
    else:
        pullback_long, pullback_short, x["long_stop"], x["short_stop"] = device_windows

    loc_range = (x["high"] - x["low"])
    x["close_location"] = np.where(
        loc_range > 0, (x["close"] - x["low"]) / loc_range, np.nan
    )
    valid_data = (
        x[["ema_fast", "ema_mid", "ema_slow", "atr", "adx", "plus_di",
           "minus_di", "htf_close", "htf_ema"]].notna().all(axis=1)
        & (x["atr"] > 0)
    )
    long_alignment = (
        (x["close"] > x["ema_slow"])
        & (x["ema_mid"] > x["ema_slow"])
        & (x["ema_fast"] > x["ema_mid"])
    )
    short_alignment = (
        (x["close"] < x["ema_slow"])
        & (x["ema_mid"] < x["ema_slow"])
        & (x["ema_fast"] < x["ema_mid"])
    )
    trend_strength = x["adx"] > cfg["adx_min"]
    long_direction = x["plus_di"] > x["minus_di"]
    short_direction = x["minus_di"] > x["plus_di"]
    htf_long = x["htf_close"] > x["htf_ema"]
    htf_short = x["htf_close"] < x["htf_ema"]

    long_trigger = (
        (loc_range > 0) & (x["close"] > x["ema_fast"])
        & (x["close"] > x["high"].shift(1))
        & (x["close"] > x["open"])
        & (x["close_location"] >= cfg["trigger_close_long"])
    )
    short_trigger = (
        (loc_range > 0) & (x["close"] < x["ema_fast"])
        & (x["close"] < x["low"].shift(1))
        & (x["close"] < x["open"])
        & (x["close_location"] <= cfg["trigger_close_short"])
    )

    x["long_stop_distance_atr_signal"] = (x["close"] - x["long_stop"]) / x["atr"]
    x["short_stop_distance_atr_signal"] = (x["short_stop"] - x["close"]) / x["atr"]

    x.loc[x["evaluation_enabled"], "wait_reason"] = "NO_TREND"
    evaluated = x["evaluation_enabled"]
    x.loc[evaluated & ~valid_data, "wait_reason"] = "NO_DATA"
    x.loc[evaluated & valid_data & (x["adx"] <= cfg["adx_min"]), "wait_reason"] = "CHOP"

    long_base = evaluated & valid_data & trend_strength & long_alignment
    short_base = evaluated & valid_data & trend_strength & short_alignment

    x.loc[long_base & ~(long_direction & htf_long), "wait_reason"] = "HTF_CONFLICT"
    x.loc[short_base & ~(short_direction & htf_short), "wait_reason"] = "HTF_CONFLICT"

    long_confirmed = long_base & long_direction & htf_long
    short_confirmed = short_base & short_direction & htf_short
    x.loc[long_confirmed & ~pullback_long, "wait_reason"] = "NO_PULLBACK"
    x.loc[short_confirmed & ~pullback_short, "wait_reason"] = "NO_PULLBACK"

    long_pb = long_confirmed & pullback_long
    short_pb = short_confirmed & pullback_short
    x.loc[long_pb & ~long_trigger, "wait_reason"] = "NO_TRIGGER"
    x.loc[short_pb & ~short_trigger, "wait_reason"] = "NO_TRIGGER"

    long_candidate = long_pb & long_trigger
    short_candidate = short_pb & short_trigger
    long_distance = x["long_stop_distance_atr_signal"]
    short_distance = x["short_stop_distance_atr_signal"]
    long_stop_valid = (
        (long_distance >= cfg["min_stop_atr"])
        & (long_distance <= cfg["max_stop_atr"])
        & (long_distance > 0)
    )
    short_stop_valid = (
        (short_distance >= cfg["min_stop_atr"])
        & (short_distance <= cfg["max_stop_atr"])
        & (short_distance > 0)
    )
    x.loc[long_candidate & ~long_stop_valid, "wait_reason"] = "STOP_INVALID"
    x.loc[short_candidate & ~short_stop_valid, "wait_reason"] = "STOP_INVALID"
    x.loc[long_candidate & long_stop_valid, ["signal", "wait_reason"]] = ["LONG", ""]
    x.loc[short_candidate & short_stop_valid, ["signal", "wait_reason"]] = ["SHORT", ""]
    return x


# =============================================================================
# EXECUTION SIMULATOR — GROSS ONLY, NO FEES/FUNDING/SLIPPAGE
# =============================================================================

def classify_gap_intersection(entry_time: pd.Timestamp, exit_time: pd.Timestamp,
                              gap_events: list[dict[str, Any]] | None,
                              timeframe: str) -> tuple[int, list[dict[str, Any]]]:
    """Return missing-candle count and intervals intersected by a trade."""
    expected = timeframe_interval(timeframe)
    missing_total = 0
    intervals: list[dict[str, Any]] = []
    for event in gap_events or []:
        previous = as_utc_timestamp(event["previous_candle"], "gap previous candle")
        following = as_utc_timestamp(event["next_candle"], "gap next candle")
        missing_start = previous + expected
        missing_end = following
        if entry_time < missing_end and exit_time > missing_start:
            count = int(event.get("missing_candles", 0))
            missing_total += count
            intervals.append({
                "missing_start": str(missing_start),
                "missing_end": str(missing_end),
                "previous_candle": str(previous),
                "next_candle": str(following),
                "missing_candles": count,
            })
    return missing_total, intervals


def simulate_trades(signals: pd.DataFrame, cfg: dict[str, Any], timeframe: str,
                    market_mode: str = "binance_usdt_perpetual_simulation",
                    run_id: str | None = None,
                    execution_constraints: dict[str, Any] | None = None,
                    rejection_log: list[dict[str, Any]] | None = None,
                    gap_events: list[dict[str, Any]] | None = None,
                    collect_audit: bool = True, planned_exits=None
                    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trades: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    rows = signals.reset_index()
    signal_values = rows["signal"].to_numpy(copy=False)
    if gap_events is None:
        gap_events = detect_missing_candles(signals, timeframe)["gap_events"]

    constraints = dict(DEFAULT_EXECUTION_CONSTRAINTS)
    if execution_constraints:
        constraints.update(execution_constraints)
    min_quantity = constraints.get("min_quantity")
    quantity_precision = constraints.get("quantity_precision")
    min_notional = constraints.get("min_notional")

    open_payment, inside_payment = funding_per_unit(signals)
    def log_rejection(sig: pd.Series, entry_bar: pd.Series, reason: str,
                      details: dict[str, Any]) -> None:
        if rejection_log is None:
            return
        rejection_log.append({
            "timeframe": timeframe,
            "signal_time": str(sig["datetime"]),
            "entry_time": str(entry_bar["datetime"]),
            "side": str(sig["signal"]),
            "reason": reason,
            "details": details,
        })

    equity = STARTING_EQUITY_USDT
    i = 0
    while i < len(rows) - 1:
        side = signal_values[i]
        if side not in ("LONG", "SHORT"):
            i += 1
            continue

        sig = rows.iloc[i]
        entry_i = i + 1
        entry_bar = rows.iloc[entry_i]
        entry = float(entry_bar["open"])
        stop = float(sig["long_stop"] if side == "LONG" else sig["short_stop"])
        atr_signal = float(sig["atr"])
        direction = 1 if side == "LONG" else -1
        stop_distance = (entry - stop) if direction == 1 else (stop - entry)

        if not np.isfinite(atr_signal) or atr_signal <= 0:
            i += 1
            continue
        if not np.isfinite(stop_distance) or stop_distance <= 0 or not np.isfinite(entry):
            i += 1
            continue
        distance_atr_entry = stop_distance / atr_signal
        if not (cfg["min_stop_atr"] <= distance_atr_entry <= cfg["max_stop_atr"]):
            i += 1
            continue
        if (direction == 1 and entry <= stop) or (direction == -1 and entry >= stop):
            i += 1
            continue

        risk_budget = equity * cfg["risk_pct"]
        quantity_raw = risk_budget / stop_distance
        max_notional = equity * LEVERAGE_CAP
        notional_raw = quantity_raw * entry
        notional_capped = notional_raw > max_notional
        quantity_after_cap = min(quantity_raw, max_notional / entry)
        quantity = quantity_after_cap
        precision_applied = False
        if quantity_precision is not None:
            factor = 10 ** int(quantity_precision)
            quantity = math.floor(quantity * factor) / factor
            precision_applied = True

        notional_after_constraints = quantity * entry
        rejection_reason = None
        if quantity <= 0:
            rejection_reason = "QUANTITY_NON_POSITIVE_OR_BELOW_PRECISION"
        elif min_quantity is not None and quantity < float(min_quantity):
            rejection_reason = "BELOW_MIN_QUANTITY"
        elif min_notional is not None and notional_after_constraints < float(min_notional):
            rejection_reason = "BELOW_MIN_NOTIONAL"

        if rejection_reason is not None:
            log_rejection(sig, entry_bar, rejection_reason, {
                "quantity_before_constraints": quantity_after_cap,
                "quantity_after_constraints": quantity,
                "notional_before_constraints": quantity_after_cap * entry,
                "notional_after_constraints": notional_after_constraints,
                "min_quantity": min_quantity,
                "quantity_precision": quantity_precision,
                "min_notional": min_notional,
            })
            i += 1
            continue

        funding = 0.0
        settlements = []
        trade_id = len(trades) + 1
        actual_initial_risk = quantity * stop_distance
        target = entry + direction * cfg["target_r"] * stop_distance
        active_stop = stop
        trailing_stop = stop
        best_high = entry
        best_low = entry
        stop_history = [{
            "time": str(entry_bar["datetime"]),
            "stop": stop,
            "source": "INITIAL_STOP",
        }]
        per_bar_state = []
        mae_r = 0.0
        mfe_r = 0.0
        exit_price = None
        exit_i = None
        exit_reason = None
        target_gap = False
        stop_first_ambiguity = False

        def signed_move(price: float) -> float:
            return direction * (price - entry) / stop_distance

        last_bar = min(len(rows) - 1, entry_i + int(cfg["time_stop"]) - 1)
        if planned_exits is not None:
            exit_idx, exit_price, reason, active_stop, mae_r, mfe_r = planned_exits[i]
            exit_i = int(exit_idx)
            exit_reason = ("GAP_STOP", "GAP_TARGET_LIMIT", "STOP_BOTH_TOUCHED_STOP_FIRST", "INITIAL_STOP",
                           "TRAILING_STOP", "TARGET", "TIME_STOP", "DATA_END")[int(reason)]
            target_gap = exit_reason == "GAP_TARGET_LIMIT"
            stop_first_ambiguity = exit_reason == "STOP_BOTH_TOUCHED_STOP_FIRST"
        for j in range(entry_i, last_bar + 1) if planned_exits is None else ():
            bar = rows.iloc[j]
            op, hi, lo, cl = map(float, (bar["open"], bar["high"], bar["low"], bar["close"]))
            current_atr = float(bar["atr"])
            old_active_stop = active_stop
            event_order: list[str] = []

            # Gap events are evaluated at the open before any intrabar range
            # check. Excursions on a gap exit must not use the later high/low.
            event_order.append("GAP_STOP_CHECK")
            gap_stop = (
                (direction == 1 and op <= active_stop)
                or (direction == -1 and op >= active_stop)
            )
            if gap_stop:
                exit_price, exit_i, exit_reason = op, j, "GAP_STOP"
                open_move = signed_move(op)
                mae_r = min(mae_r, open_move)
                mfe_r = max(mfe_r, open_move)
                event_order.append("GAP_STOP_TRIGGERED")
            else:
                event_order.append("GAP_TARGET_CHECK")
                gap_target = (
                    (direction == 1 and op >= target)
                    or (direction == -1 and op <= target)
                )
                if gap_target:
                    exit_price, exit_i, exit_reason = target, j, "GAP_TARGET_LIMIT"
                    target_gap = True
                    mfe_r = max(mfe_r, signed_move(target))
                    mae_r = min(mae_r, signed_move(op))
                    event_order.append("GAP_TARGET_TRIGGERED")
                else:
                    event_order.append("INTRABAR_STOP_CHECK")
                    stop_hit = (lo <= active_stop) if direction == 1 else (hi >= active_stop)
                    event_order.append("INTRABAR_TARGET_CHECK")
                    target_hit = (hi >= target) if direction == 1 else (lo <= target)

                    if stop_hit and target_hit:
                        exit_price, exit_i = active_stop, j
                        exit_reason = "STOP_BOTH_TOUCHED_STOP_FIRST"
                        stop_first_ambiguity = True
                        # Stop-first rule: only the binding stop excursion is used.
                        mae_r = min(mae_r, signed_move(active_stop))
                        event_order.append("STOP_FIRST_AMBIGUITY")
                    elif stop_hit:
                        exit_price, exit_i = active_stop, j
                        exit_reason = "TRAILING_STOP" if active_stop != stop else "INITIAL_STOP"
                        mae_r = min(mae_r, signed_move(active_stop))
                    elif target_hit:
                        exit_price, exit_i, exit_reason = target, j, "TARGET"
                        mfe_r = max(mfe_r, signed_move(target))
                    else:
                        # No exit: the full bar range is a valid excursion.
                        adverse_extreme = lo if direction == 1 else hi
                        favorable_extreme = hi if direction == 1 else lo
                        mae_r = min(mae_r, signed_move(adverse_extreme))
                        mfe_r = max(mfe_r, signed_move(favorable_extreme))
                        best_high = max(best_high, hi)
                        best_low = min(best_low, lo)

                        if np.isfinite(current_atr) and current_atr > 0:
                            if direction == 1:
                                proposed = best_high - cfg["chandelier_atr"] * current_atr
                                new_trail = max(trailing_stop, proposed)
                                active_stop = max(stop, new_trail)
                            else:
                                proposed = best_low + cfg["chandelier_atr"] * current_atr
                                new_trail = min(trailing_stop, proposed)
                                active_stop = min(stop, new_trail)

                        if j == last_bar:
                            exit_price, exit_i = cl, j
                            exit_reason = (
                                "TIME_STOP"
                                if j == entry_i + cfg["time_stop"] - 1
                                else "DATA_END"
                            )
                            event_order.append("TIME_STOP_CHECK")

            if active_stop != old_active_stop:
                trailing_stop = active_stop
                stop_update_event = "CHANDELIER_NEXT_BAR"
                stop_history.append({
                    "time": str(bar["datetime"]),
                    "stop": float(active_stop),
                    "source": "CHANDELIER_NEXT_BAR",
                })
            else:
                stop_update_event = "NONE"

            if exit_price is not None:
                event_order.append(f"EXIT:{exit_reason}")

            bar_exit_stop_type = None
            if exit_price is not None and exit_reason in (
                "GAP_STOP", "INITIAL_STOP", "TRAILING_STOP",
                "STOP_BOTH_TOUCHED_STOP_FIRST",
            ):
                bar_exit_stop_type = (
                    "INITIAL_STOP" if active_stop == stop else "TRAILING_STOP"
                )

            if collect_audit:
                per_bar_state.append({
                    "trade_id": trade_id,
                    "bar_index": j,
                    "time": str(bar["datetime"]),
                    "open": op, "high": hi, "low": lo, "close": cl,
                    "direction": side,
                    "entry_price": entry,
                    "initial_stop": stop,
                    "active_stop": float(active_stop),
                    "trailing_stop": float(trailing_stop),
                    "target": target,
                    "atr": current_atr,
                    "adx": float(bar["adx"]),
                    "mae_R": float(mae_r),
                    "mfe_R": float(mfe_r),
                    "stop_update_event": stop_update_event,
                    "exit_event_order": event_order,
                    "is_exit_candle": exit_price is not None,
                    "exit_reason": exit_reason if exit_price is not None else None,
                    "exit_stop_type": bar_exit_stop_type,
                    "exit_fill": float(exit_price) if exit_price is not None else None,
                    "exit_time": str(bar["datetime"]) if exit_price is not None else None,
                })

            if exit_price is not None:
                break

        if exit_price is None:
            # Defensive fallback; the loop always evaluates the final bar.
            exit_i = min(len(rows) - 1, entry_i)
            exit_price = float(rows.iloc[exit_i]["close"])
            exit_reason = "DATA_END"

        assert exit_i is not None  # Every exit path binds its candle index.
        entry_time = as_utc_timestamp(entry_bar["datetime"], "entry time")
        exit_time = as_utc_timestamp(rows.iloc[exit_i]["datetime"], "exit time")
        missing_crossed, affected_intervals = classify_gap_intersection(
            entry_time, exit_time, gap_events, timeframe
        )
        crosses_data_gap = bool(affected_intervals)

        gross_pnl = quantity * (exit_price - entry) * direction
        actual_initial_risk = quantity * stop_distance
        gross_r = gross_pnl / actual_initial_risk if actual_initial_risk else np.nan
        gross_r_budget = gross_pnl / risk_budget if risk_budget else np.nan
        maker_exit = exit_reason in ("TARGET", "GAP_TARGET_LIMIT")
        entry_fee = PERPETUAL_FEES.charge(quantity, entry, "taker")
        exit_fee = PERPETUAL_FEES.charge(quantity, exit_price, "maker" if maker_exit else "taker")
        close_exit = exit_reason in ("DATA_END", "TIME_STOP")
        if open_payment is not None:
            for j in range(entry_i, exit_i + 1):
                paid = (open_payment[j] if j > entry_i else 0.) + (
                    inside_payment[j] if j < exit_i or close_exit else 0.)
                if paid:
                    payment = direction * quantity * paid
                    funding += payment
                    if collect_audit:
                        settlements.append({"bar_open": str(signals.index[j]), "payment": payment})
        net = gross_pnl - entry_fee - exit_fee - funding
        equity_after = equity + net
        realised_loss = -gross_pnl if gross_pnl < 0 else 0.0
        exit_stop_type = None
        if exit_reason in (
            "GAP_STOP", "INITIAL_STOP", "TRAILING_STOP",
            "STOP_BOTH_TOUCHED_STOP_FIRST",
        ):
            exit_stop_type = (
                "INITIAL_STOP" if active_stop == stop else "TRAILING_STOP"
            )

        trade = {
            "run_id": run_id,
            "trade_id": trade_id,
            "timeframe": timeframe,
            "market_mode": market_mode,
            "side": side,
            "signal_time": str(sig["datetime"]),
            "signal_close": float(sig["close"]),
            "signal_atr": atr_signal,
            "entry_time": str(entry_bar["datetime"]),
            "entry_fill": entry,
            "initial_stop": stop,
            "initial_stop_distance_atr_signal": float(sig["long_stop_distance_atr_signal"] if side == "LONG" else sig["short_stop_distance_atr_signal"]),
            "initial_stop_distance_atr_at_entry": distance_atr_entry,
            "actual_initial_risk": actual_initial_risk,
            "actual_initial_risk_pct_of_equity": actual_initial_risk / equity * 100.0 if equity else np.nan,
            "risk_budget": risk_budget,
            "notional_capped": bool(notional_capped),
            "quantity_before_constraints": quantity_after_cap,
            "quantity_after_constraints": quantity,
            "quantity_precision_applied": bool(precision_applied),
            "quantity": quantity,
            "notional_at_entry": quantity * entry,
            "execution_rejection_reason": None,
            "target": target,
            "target_gap_flag": bool(target_gap),
            "exit_time": str(rows.iloc[exit_i]["datetime"]),
            "exit_fill": exit_price,
            "exit_reason": exit_reason,
            "exit_stop_type": exit_stop_type,
            "stop_first_ambiguity": bool(stop_first_ambiguity),
            "bars_held": int(exit_i - entry_i + 1),
            "crosses_data_gap": crosses_data_gap,
            "missing_candles_crossed": int(missing_crossed),
            "data_gap_intervals": affected_intervals,
            "outcome_uncertain": bool(crosses_data_gap),
            "outcome_uncertainty_reason": (
                "Holding period intersects missing candles; intragap stop/target "
                "path cannot be verified from the supplied data."
                if crosses_data_gap else None
            ),
            "gross_pnl": gross_pnl,
            "entry_notional": quantity * entry, "exit_notional": quantity * exit_price,
            "entry_liquidity": "taker", "exit_liquidity": "maker" if maker_exit else "taker",
            "entry_fee": entry_fee, "exit_fee": exit_fee, "fees": entry_fee + exit_fee,
            "maker_fees": exit_fee if maker_exit else 0.0,
            "taker_fees": entry_fee if maker_exit else entry_fee + exit_fee,
            "funding": funding, "slippage": 0.0, "net_pnl": net,
            "net_return_pct": 100 * net / (quantity * entry),
            "holding_hours": (exit_time - entry_time).total_seconds() / 3600
                + (timeframe_interval(timeframe).total_seconds() / 3600 if exit_reason in ("DATA_END", "TIME_STOP") else 0),
            "maker_rate": MAKER_RATE, "taker_rate": TAKER_RATE,
            "starting_equity_usdt": STARTING_EQUITY_USDT,
            "gross_R": gross_r,
            "gross_R_budget": gross_r_budget,
            "equity_before": equity,
            "equity_after": equity_after,
            "mae_R": mae_r,
            "mfe_R": mfe_r,
            "realised_loss_ratio_vs_actual": realised_loss / actual_initial_risk if actual_initial_risk else 0.0,
            "realised_loss_ratio_vs_budget": realised_loss / risk_budget if risk_budget else 0.0,
            "slippage_rate": 0.,
            "cost_model": COST_MODEL,
            "funding_model": funding_model(signals),
            "short_executable": True,
        }
        trades.append(trade)
        if collect_audit:
            audit.append({
                **trade,
                "indicator_snapshot": {
                    key: (float(sig[key]) if pd.notna(sig[key]) else None)
                    for key in ("ema_fast", "ema_mid", "ema_slow", "atr", "adx", "plus_di", "minus_di", "htf_close", "htf_ema")
                },
                "per_bar_state": per_bar_state,
                "stop_history": stop_history,
                "funding_events": settlements,
                "cost_breakdown": {"entry_fee": entry_fee, "exit_fee": exit_fee, "slippage": 0.0, "funding": funding},
            })
        equity = equity_after
        i = exit_i + 1

    return trades, audit


# =============================================================================
# REPORTING
# =============================================================================

def funding_per_unit(frame):
    if "funding_open_per_unit" in frame:
        return frame["funding_open_per_unit"].to_numpy(), frame["funding_inside_per_unit"].to_numpy()
    if "funding_rate" in frame:
        return (frame["funding_rate"] * frame["funding_mark_price"]).fillna(0).to_numpy(), np.zeros(len(frame))
    return None, None


def funding_model(frame):
    if "funding_open_per_unit" in frame:
        return "HISTORICAL_SETTLEMENTS"
    return "BAR_OPEN_SETTLEMENTS" if "funding_rate" in frame else FUNDING_MODEL


def cuda_device():
    """Initialize the runtime lazily so CPU installations need only NumPy."""
    import cupy as cp
    if not cp.cuda.runtime.getDeviceCount():
        raise RuntimeError("No CUDA device")
    cp.zeros(1).sum().item()
    return cp


def marked_curve(signals, trades, mode):
    """Price independent end-of-bar positions concurrently after serial fills."""
    if mode not in ("auto", "cpu", "gpu"):
        raise ValueError("execution_mode must be auto, cpu or gpu")
    xp: Any = np
    fallback = None
    if mode == "gpu" or (mode == "auto" and len(signals) >= 100_000):
        try:
            xp = cuda_device()
        except (ImportError, OSError, RuntimeError, MemoryError) as exc:
            fallback = str(exc)
    if not trades:
        return np.full(len(signals), STARTING_EQUITY_USDT), "cpu", fallback
    entries = signals.index.get_indexer(pd.to_datetime([t["entry_time"] for t in trades], format="ISO8601", utc=True))
    exits = signals.index.get_indexer(pd.to_datetime([t["exit_time"] for t in trades], format="ISO8601", utc=True))
    settlements = np.zeros(len(signals))
    opened, inside = funding_per_unit(signals)
    if opened is not None:
        settlements = np.cumsum(opened + inside)
    closes = signals["close"].to_numpy()

    def calculate(lib, size):
        result = np.empty(len(closes))
        end = lib.asarray(exits)
        qty, price, balance, entry_fee, realized, sign = [
            lib.asarray(values) for values in (
                [t["quantity"] for t in trades], [t["entry_fill"] for t in trades],
                [t["equity_before"] for t in trades], [t["entry_fee"] for t in trades],
                [t["equity_after"] for t in trades], [1 if t["side"] == "LONG" else -1 for t in trades])]
        entry_settlement = lib.asarray(settlements[entries] - (inside[entries] if inside is not None else 0))
        for start in range(0, len(result), size):
            stop = min(len(result), start + size)
            bars = lib.arange(start, stop)
            idx = lib.asarray(np.searchsorted(entries, np.arange(start, stop), side="right") - 1)
            prices = lib.asarray(closes[start:stop])
            funding = lib.asarray(settlements[start:stop]) - entry_settlement[idx]
            marks = (balance[idx] - entry_fee[idx] + sign[idx] * qty[idx]
                     * (prices - price[idx] - funding) - qty[idx] * prices * TAKER_RATE)
            values = lib.where(idx < 0, STARTING_EQUITY_USDT, lib.where(bars >= end[idx], realized[idx], marks))
            result[start:stop] = values if lib is np else lib.asnumpy(values)
        return result

    if xp is not np:
        try:
            free, _ = xp.cuda.runtime.memGetInfo()
            return calculate(xp, max(1, min(len(closes), free // 512))), "cuda", None
        except (MemoryError, RuntimeError) as exc:
            fallback = str(exc)
    return calculate(np, max(1, len(closes))), "cpu", fallback


def summarize(timeframe: str, signals: pd.DataFrame, trades: list[dict[str, Any]],
              warmup: WarmupResult, source: Path, htf_source: Path,
              source_hashes: tuple[str, str] | None = None, execution_mode: str = "auto") -> dict[str, Any]:
    t = pd.DataFrame(trades)

    def subset_metrics(subset: pd.DataFrame) -> dict[str, Any]:
        if subset.empty:
            return {
                "trades": 0,
                "win_rate_pct": None,
                "profit_factor_gross_R": None,
                "average_gross_R": None,
                "total_gross_R": 0.0,
                "compounded_return_pct": 0.0,
            }
        wins = int((subset["net_pnl"] > 0).sum())
        gains = float(subset.loc[subset["gross_R"] > 0, "gross_R"].sum())
        losses = float(abs(subset.loc[subset["gross_R"] < 0, "gross_R"].sum()))
        compounded = float(
            cast(Any, (1.0 + subset["net_pnl"] / subset["equity_before"]).prod()) - 1.0
        )
        return {
            "trades": int(len(subset)),
            "win_rate_pct": float(wins / len(subset) * 100.0),
            "profit_factor_gross_R": float(gains / losses) if losses else None,
            "average_gross_R": float(subset["gross_R"].mean()),
            "total_gross_R": float(subset["gross_R"].sum()),
            "compounded_return_pct": compounded * 100.0,
        }

    metrics: dict[str, Any]
    if t.empty:
        metrics = {
            "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": np.nan,
            "profit_factor_gross_R": np.nan, "average_gross_R": np.nan,
            "total_gross_R": 0.0, "compounded_equity_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "gap_affected_trades": 0,
            "gap_unaffected_trades": 0,
            "gap_affected_total_gross_R": 0.0,
            "gap_unaffected_total_gross_R": 0.0,
            "gap_affected_compounded_return_pct": 0.0,
            "gap_unaffected_compounded_return_pct": 0.0,
            "gap_uncertain_trades": 0,
        }
        affected = t
        unaffected = t
    else:
        wins = int((t["gross_R"] > 0).sum())
        gains = t.loc[t["gross_R"] > 0, "gross_R"].sum()
        losses = abs(t.loc[t["gross_R"] < 0, "gross_R"].sum())
        eq = pd.concat(
            [pd.Series([1.0]), t["equity_after"].reset_index(drop=True) / STARTING_EQUITY_USDT],
            ignore_index=True,
        )
        peak = eq.cummax()
        affected = t[t["crosses_data_gap"].eq(True)] if "crosses_data_gap" in t else t.iloc[0:0]
        unaffected = t[t["crosses_data_gap"].eq(False)] if "crosses_data_gap" in t else t
        affected_metrics = subset_metrics(affected)
        unaffected_metrics = subset_metrics(unaffected)
        metrics = {
            "trades": len(t),
            "wins": wins,
            "losses": len(t) - wins,
            "win_rate_pct": wins / len(t) * 100.0,
            "profit_factor_gross_R": gains / losses if losses else np.inf,
            "average_gross_R": float(t["gross_R"].mean()),
            "total_gross_R": float(t["gross_R"].sum()),
            "compounded_equity_return_pct": float((eq.iloc[-1] - 1.0) * 100.0),
            "max_drawdown_pct": float(((eq / peak) - 1.0).min() * 100.0),
            "long_trades": int((t["side"] == "LONG").sum()),
            "short_trades": int((t["side"] == "SHORT").sum()),
            "long_expectancy_gross_R": float(t.loc[t["side"] == "LONG", "gross_R"].mean()) if (t["side"] == "LONG").any() else np.nan,
            "short_expectancy_gross_R": float(t.loc[t["side"] == "SHORT", "gross_R"].mean()) if (t["side"] == "SHORT").any() else np.nan,
            "mean_realised_loss_ratio_vs_actual": float(t.loc[t["gross_pnl"] < 0, "realised_loss_ratio_vs_actual"].mean()) if (t["gross_pnl"] < 0).any() else 0.0,
            "p95_realised_loss_ratio_vs_actual": float(t.loc[t["gross_pnl"] < 0, "realised_loss_ratio_vs_actual"].quantile(0.95)) if (t["gross_pnl"] < 0).any() else 0.0,
            "mean_realised_loss_ratio_vs_budget": float(t.loc[t["gross_pnl"] < 0, "realised_loss_ratio_vs_budget"].mean()) if (t["gross_pnl"] < 0).any() else 0.0,
            "p95_realised_loss_ratio_vs_budget": float(t.loc[t["gross_pnl"] < 0, "realised_loss_ratio_vs_budget"].quantile(0.95)) if (t["gross_pnl"] < 0).any() else 0.0,
            "gap_affected_trades": int(len(affected)),
            "gap_unaffected_trades": int(len(unaffected)),
            "gap_affected_total_gross_R": affected_metrics["total_gross_R"],
            "gap_unaffected_total_gross_R": unaffected_metrics["total_gross_R"],
            "gap_affected_compounded_return_pct": affected_metrics["compounded_return_pct"],
            "gap_unaffected_compounded_return_pct": unaffected_metrics["compounded_return_pct"],
            "gap_uncertain_trades": int(t["outcome_uncertain"].sum()) if "outcome_uncertain" in t else 0,
        }

    # Mark open positions to an immediate taker close. An exit bar uses its
    # actual fill. Flat bars carry the last settled balance.
    curve, active_backend, fallback = marked_curve(signals, trades, execution_mode)
    net_equity = np.r_[STARTING_EQUITY_USDT, curve]
    risk_equity = net_equity[warmup.evaluation_start_index or 0:]
    returns = np.diff(risk_equity) / risk_equity[:-1]
    periods = (365 * 86400) / timeframe_interval(timeframe).total_seconds()
    downside = np.sqrt(np.square(np.minimum(returns, 0)).mean()) if returns.size else 0.
    volatility = returns.std(ddof=1) if returns.size > 1 else 0.
    drawdown = float(np.min(net_equity / np.maximum.accumulate(net_equity) - 1) * 100)
    metrics.update(max_drawdown_pct=drawdown,
                   sharpe=float(np.sqrt(periods) * returns.mean() / volatility) if volatility > 0 else None,
                   sortino=float(np.sqrt(periods) * returns.mean() / downside) if downside > 0 else None)
    for key in ("maker_fees", "taker_fees", "fees", "slippage", "funding"):
        metrics["total_" + key] = sum(tr[key] for tr in trades)
    for basis in ("gross", "net"):
        values = [tr[basis + "_pnl"] for tr in trades]
        positive_values = [v for v in values if v > 0]
        negative_values = [v for v in values if v < 0]
        metrics[basis + "_pnl"] = math.fsum(values)
        metrics[basis + "_return_pct"] = 100 * math.fsum(values) / STARTING_EQUITY_USDT
        metrics[basis + "_win_rate_pct"] = 100 * len(positive_values) / len(values) if values else None
        metrics[basis + "_profit_factor"] = sum(positive_values) / -sum(negative_values) if negative_values else ("infinite" if positive_values else None)
    metrics.update(wins=len(positive_values), losses=len(negative_values), win_rate_pct=metrics["net_win_rate_pct"])
    metrics.update(net_expectancy=np.mean(values) if values else None,
                   average_net_win=np.mean(positive_values) if positive_values else None,
                   average_net_loss=np.mean(negative_values) if negative_values else None,
                   average_duration_hours=t["holding_hours"].mean() if trades else None,
                   drawdown_adjusted_return=metrics["net_return_pct"] / abs(drawdown) if drawdown else None)
    wait_counts = signals.loc[signals["signal"] == "WAIT", "wait_reason"].value_counts()
    for reason in ("NO_DATA", "CHOP", "NO_TREND", "HTF_CONFLICT", "NO_PULLBACK", "NO_TRIGGER", "STOP_INVALID"):
        metrics[f"wait_{reason.lower()}"] = int(wait_counts.get(reason, 0))

    gap_sensitivity = {
        "description": (
            "Sensitivity view only. Unaffected trades are summarised separately; "
            "affected trades remain in the baseline and are NOT removed."
        ),
        "affected": subset_metrics(affected),
        "unaffected": subset_metrics(unaffected),
    }

    return {
        "strategy": "EMA Pullback V4.2 OHLCV-only",
        "timeframe": timeframe,
        "base_source": str(source),
        "base_source_sha256": source_hashes[0] if source_hashes else sha256_file(source),
        "htf_source": str(htf_source),
        "htf_source_sha256": source_hashes[1] if source_hashes else sha256_file(htf_source),
        "first_candle": str(signals.index.min()),
        "last_candle": str(signals.index.max()),
        "bars": len(signals),
        "warmup": asdict(warmup),
        "active_backend": active_backend, "backend_fallback": fallback,
        "execution_mode": execution_mode,
        "equity_curve": curve.tolist(),
        "duration_basis": "Open timestamp for intrabar fills, close boundary for time and data-end exits",
        "metrics": metrics,
        "gap_sensitivity": gap_sensitivity,
    }


@dataclass(frozen=True)
class PreparedAnalysisData:
    """Worker-local validated snapshot; frames are read-only by contract.

    The bounded indicator cache is scoped to these exact datasets and cutoff.
    The last signal frame is retained for adjacent exit-only variations.
    """
    timeframe: str
    base_path: Path
    htf_path: Path
    requested_cutoff: str
    base_hash: str
    htf_hash: str
    source_stats: tuple[tuple[int, int], tuple[int, int]]
    base: pd.DataFrame
    htf: pd.DataFrame
    policy: dict[str, Any]
    completion: pd.DataFrame
    htf_completion: dict[str, Any]
    data_quality: dict[str, Any]
    signal_cache: Any = field(default_factory=dict, compare=False, repr=False)
    indicator_cache: Any = field(default_factory=OrderedDict, compare=False, repr=False)

    def verify_sources(self) -> None:
        if self.source_stats != (_source_stat(self.base_path), _source_stat(self.htf_path)):
            raise ValueError("Dataset changed after preparation; start a new run")


def _source_stat(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def prepare_analysis_data(timeframe: str, base_path: Path, htf_path: Path,
                          data_cutoff: Any = None,
                          cutoff_mode: str = DEFAULT_CUTOFF_MODE, *,
                          reject_suspicious: bool = False) -> PreparedAnalysisData:
    if timeframe not in BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")
    base_path, htf_path = Path(base_path).resolve(), Path(htf_path).resolve()
    before = _source_stat(base_path), _source_stat(htf_path)
    hashes = sha256_file(base_path), sha256_file(htf_path)
    base_full = read_ohlcv(base_path, reject_suspicious=reject_suspicious)
    htf = read_ohlcv(htf_path, reject_suspicious=reject_suspicious)

    # Resolve cutoff provenance before any indicator or signal work. Strict mode
    # raises here when no independently verified cutoff was supplied.
    policy = resolve_data_cutoff(base_full, timeframe, data_cutoff, cutoff_mode)
    cutoff = policy["value"]
    htf_timeframe = HTF_TIMEFRAMES[timeframe]

    # Exclude every base candle that cannot be certified complete at the cutoff.
    # The excluded rows never reach indicators, signals or trade simulation.
    base_index = ensure_utc_index(base_full.index, "base data")
    included_mask = np.asarray(
        base_index + timeframe_interval(timeframe) <= cutoff
    )
    base = base_full.loc[included_mask].copy()
    if base.empty:
        raise ValueError(
            "No verified base candles remain at the resolved data cutoff."
        )

    completion_frame, htf_completion = htf_completion_frame(
        htf, htf_timeframe, cutoff,
        base=base, base_timeframe=timeframe,
        cutoff_source=policy["source"],
        cutoff_verified=policy["verified"],
        cutoff_mode=policy["mode"],
    )

    if reject_suspicious:
        for frame, tf, path in ((base_full, timeframe, base_path),
                                (htf, htf_timeframe, htf_path)):
            if any(not exchange_boundary_aligned(ts, tf) for ts in frame.index):
                raise ValueError(f"{path.name}: timestamps not aligned to {tf} boundaries")
    data_quality = {
        "base": build_data_quality_report(base_full, timeframe),
        "htf": build_data_quality_report(htf, htf_timeframe),
    }
    data_quality["base"]["cutoff_application"] = {
        "cutoff": str(cutoff),
        "cutoff_source": policy["source"],
        "cutoff_verified": policy["verified"],
        "included_candles": int(len(base)),
        "excluded_incomplete_candles": policy["excluded_incomplete_candles"],
        "last_included_base_candle": str(policy["last_included_base_candle"]),
        "excluded_candle_reasons": policy["excluded_candle_reasons"],
    }
    data_quality["htf"]["completion"] = htf_completion
    if before != (_source_stat(base_path), _source_stat(htf_path)):
        raise ValueError("Dataset changed while loading")
    return PreparedAnalysisData(
        timeframe, base_path, htf_path, str(data_cutoff), *hashes, before,
        base, htf, policy, completion_frame, htf_completion, data_quality,
    )


def run_analysis(timeframe: str, base_path: Path, htf_path: Path,
                 config_override: dict[str, Any] | None = None,
                 output_dir: Path | None = None,
                 run_id: str | None = None,
                 force: bool = False,
                 data_cutoff: Any = None,
                 cutoff_mode: str = DEFAULT_CUTOFF_MODE,
                 execution_constraints: dict[str, Any] | None = None,
                 *, prepared_data: PreparedAnalysisData | None = None, execution_mode: str = "auto",
                 write_outputs: bool = True, collect_audit: bool = True
                 ) -> dict[str, Any]:
    if timeframe not in BASELINE_CONFIGS:
        raise ValueError("Timeframe must be 2h, 4h or 1d")
    validate_cutoff_mode(cutoff_mode)
    cfg = dict(BASELINE_CONFIGS[timeframe])
    if config_override:
        cfg.update(config_override)

    if not (cfg["fast_ema"] < cfg["medium_ema"] < cfg["slow_ema"]):
        raise ValueError("EMA periods must satisfy fast < medium < slow")
    if cfg["trigger_close_long"] <= 0.5 or cfg["trigger_close_short"] >= 0.5:
        raise ValueError("Trigger close-location thresholds are invalid")
    if not math.isfinite(cfg["target_r"]) or cfg["target_r"] <= 0:
        raise ValueError("Target R must be finite and positive")
    if cfg["min_stop_atr"] >= cfg["max_stop_atr"]:
        raise ValueError("Minimum stop distance must be below maximum stop distance")

    base_path = Path(base_path).expanduser().resolve()
    htf_path = Path(htf_path).expanduser().resolve()

    if output_dir is None:
        output_dir = default_output_directory(timeframe)
    else:
        output_dir = Path(output_dir).expanduser().resolve()
    paths = result_paths(output_dir, timeframe)
    existing = [path for path in paths.values() if path.exists()]
    if write_outputs and existing and not force:
        raise FileExistsError(
            "Refusing to overwrite existing results in "
            f"{output_dir}: {', '.join(path.name for path in existing)}. "
            "Pass --force to overwrite explicitly, or use --output to select "
            "another experiment directory."
        )

    prepared = prepared_data or prepare_analysis_data(
        timeframe, base_path, htf_path, data_cutoff, cutoff_mode,
    )
    if (prepared.timeframe, prepared.base_path, prepared.htf_path,
            prepared.requested_cutoff, prepared.policy["mode"]) != (
            timeframe, base_path, htf_path, str(data_cutoff), cutoff_mode):
        raise ValueError("Prepared data does not match timeframe, paths or cutoff policy")
    prepared.verify_sources()
    base, htf = prepared.base, prepared.htf
    policy, cutoff = prepared.policy, prepared.policy["value"]
    htf_completion, data_quality = prepared.htf_completion, prepared.data_quality

    constraints = dict(DEFAULT_EXECUTION_CONSTRAINTS)
    if execution_constraints:
        constraints.update(execution_constraints)
    for key in ("min_quantity", "min_notional"):
        value = constraints.get(key)
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError(f"{key} must be non-negative or None")
    precision_value = constraints.get("quantity_precision")
    if precision_value is not None and (not math.isfinite(float(precision_value)) or not float(precision_value).is_integer() or not 0 <= precision_value <= 15):
        raise ValueError("quantity_precision must be non-negative or None")

    if run_id is None:
        run_id = compute_run_id(
            timeframe, cfg, base_path, htf_path,
            data_cutoff=cutoff,
            execution_constraints=execution_constraints,
            cutoff_mode=cutoff_mode,
            data_cutoff_verified=policy["verified"],
            cutoff_policy=policy,
        )

    # Every input affecting these indicators/warm-up is present in the key;
    # data, cutoff, coverage and engine settings are fixed by this snapshot.
    cache_key = tuple(cfg[key] for key in (
        "fast_ema", "medium_ema", "slow_ema", "adx_period", "atr_period", "htf_ema",
    ))
    cached = prepared.indicator_cache.get(cache_key)
    if cached is None:
        indicators = attach_htf_indicators(
            add_indicators(base, cfg), htf, cfg["htf_ema"], timeframe=timeframe,
            htf_timeframe=HTF_TIMEFRAMES[timeframe], data_cutoff=cutoff,
            cutoff_mode=cutoff_mode, cutoff_policy=policy, completion=prepared.completion,
        )
        warmup = check_convergence(
            base, htf, cfg, timeframe, data_cutoff=cutoff,
            cutoff_mode=cutoff_mode, cutoff_policy=policy,
            indicator_frame=indicators, completion=prepared.completion,
        )
        if len(prepared.indicator_cache) >= 2:
            prepared.indicator_cache.popitem(last=False)
        prepared.indicator_cache[cache_key] = indicators, warmup
    else:
        indicators, warmup = cached
        prepared.indicator_cache.move_to_end(cache_key)
    signal_key = (execution_mode,) + tuple(sorted((k, v) for k, v in cfg.items()
                              if k not in ("chandelier_atr", "time_stop", "target_r", "risk_pct")))
    signals = prepared.signal_cache.get(signal_key)
    if signals is None:
        signals = build_signals(
            base, htf, cfg, timeframe, warmup, data_cutoff=cutoff,
            cutoff_mode=cutoff_mode, cutoff_policy=policy, indicator_frame=indicators, execution_mode=execution_mode,
        )
        prepared.signal_cache.clear()
        prepared.signal_cache[signal_key] = signals
    execution_rejections: list[dict[str, Any]] = []
    planned = None
    path_backend = "cpu"
    path_fallback = None
    if not collect_audit:
        lib = np
        if execution_mode == "gpu" or (execution_mode == "auto" and len(signals) >= 100_000):
            try:
                lib = cuda_device()
            except (ImportError, RuntimeError, OSError, MemoryError) as exc:
                path_fallback = str(exc)
        try:
            planned = exit_paths(signals, cfg, lib)
            path_backend = "cuda" if lib is not np else "cpu"
        except (RuntimeError, MemoryError) as exc:
            if lib is np:
                raise
            path_fallback = str(exc)
            planned = exit_paths(signals, cfg)
    trades, audit = simulate_trades(
        signals, cfg, timeframe, run_id=run_id, planned_exits=planned,
        execution_constraints=execution_constraints,
        rejection_log=execution_rejections,
        gap_events=data_quality["base"]["missing_candles"]["gap_events"],
        collect_audit=collect_audit,
    )

    report = summarize(timeframe, signals, trades, warmup, base_path, htf_path,
                       source_hashes=(prepared.base_hash, prepared.htf_hash), execution_mode=execution_mode)
    if path_backend == "cuda" or signals.attrs.get("signal_backend") == "cuda":
        report["active_backend"] = "cuda"
    report["backend_fallback"] = path_fallback or signals.attrs.get("signal_fallback") or report["backend_fallback"]
    report["run_id"] = run_id
    report["engine_version"] = ENGINE_VERSION
    report["engine_source_path"] = str(engine_source_path())
    report["engine_source_sha256"] = engine_source_hash()
    report["imported_execution_modules"] = imported_execution_module_fingerprints()
    report["data_processing_version"] = DATA_PROCESSING_VERSION
    report["execution_model"] = execution_model_settings()
    report["execution_constraints"] = constraints
    report["execution_rejections"] = execution_rejections
    report["configuration"] = cfg
    report["market_mode"] = "binance_usdt_perpetual_simulation"
    report["dataset_venue_warning"] = None if base_path == BASE_DATA_FILES[timeframe] else "OHLCV columns alone do not establish perpetual contract provenance."
    report["funding_model"] = funding_model(base)
    report["execution_model"]["funding_model"] = report["funding_model"]
    report["cost_model"] = COST_MODEL
    report["data_quality"] = data_quality
    if htf_completion["complete_count"] == 0:
        htf_status = "NO_COMPLETE_HTF_CANDLES"
    elif htf_completion["excluded_candle_count"] == 0:
        htf_status = "ALL_HTF_CANDLES_COMPLETE"
    else:
        htf_status = "INCOMPLETE_HTF_CANDLES_EXCLUDED"
    report["data_cutoff"] = str(cutoff)
    report["data_cutoff_source"] = policy["source"]
    report["data_cutoff_verified"] = policy["verified"]
    report["cutoff_mode"] = policy["mode"]
    report["last_base_candle_timestamp"] = str(policy["last_base_candle_timestamp"])
    report["last_base_candle_included"] = policy["last_base_candle_included"]
    report["last_included_base_candle"] = str(policy["last_included_base_candle"])
    report["excluded_incomplete_candles"] = policy["excluded_incomplete_candles"]
    report["excluded_candle_reasons"] = policy["excluded_candle_reasons"]
    report["last_verified_base_candle"] = (
        str(policy["last_verified_base_candle"])
        if policy["last_verified_base_candle"] is not None else None
    )
    report["last_verified_htf_candle"] = htf_completion["last_complete_candle_open"]
    report["htf_completion_status"] = htf_status
    report["data_cutoff_policy"] = policy
    report["diagnostic_warning"] = (
        DIAGNOSTIC_WARNING if policy["mode"] == CUTOFF_MODE_DIAGNOSTIC else None
    )
    report["htf_completion"] = htf_completion
    report["spec_parity"] = dict(V42_SPEC_PARITY_REPORT)
    report["output_directory"] = str(output_dir)
    report["metrics"].update({k: report["execution_model"][k] for k in ("maker_rate", "taker_rate", "starting_equity_usdt", "market_mode", "slippage_rate", "funding_model")})
    report["metrics"]["run_id"] = run_id
    report["metrics"]["engine_version"] = ENGINE_VERSION
    report["metrics"]["engine_source_sha256"] = report["engine_source_sha256"]
    report["metrics"]["data_processing_version"] = DATA_PROCESSING_VERSION
    report["metrics"]["data_cutoff"] = str(cutoff)
    report["metrics"]["data_cutoff_verified"] = policy["verified"]
    report["metrics"]["cutoff_mode"] = policy["mode"]
    report["metrics"]["excluded_incomplete_candles"] = policy["excluded_incomplete_candles"]


    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        provenance = {key: report["execution_model"][key] for key in (
            "cost_model", "funding_model", "maker_rate", "taker_rate", "slippage_rate",
            "starting_equity_usdt", "market_mode")}
        signals.reset_index().assign(run_id=run_id, **provenance).to_csv(paths["signals"], index=False)
        pd.DataFrame(trades).assign(**provenance).to_csv(paths["trades"], index=False)
        with paths["audit"].open("w", encoding="utf-8") as f:
            for item in audit:
                f.write(json.dumps(json_safe(item), sort_keys=True, allow_nan=False) + "\n")
        paths["summary"].write_text(
            json.dumps(json_safe(report), indent=2, allow_nan=False), encoding="utf-8"
        )
        pd.DataFrame([report["metrics"]]).to_csv(paths["metrics"], index=False)

    return {
        "signals": signals.copy() if prepared_data is not None else signals,
        "trades": trades,
        "audit": audit,
        "report": report,
        "output_directory": output_dir,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EMA Pullback V4.2 OHLCV-only research analysis.")
    parser.add_argument("--timeframe", choices=["2h", "4h", "1d"], default=TIMEFRAME_TO_TEST)
    parser.add_argument("--base", type=Path, default=None, help="Override base OHLCV CSV path.")
    parser.add_argument("--htf", type=Path, default=None, help="Override higher-timeframe OHLCV CSV path.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Experiment output directory. Defaults to research/results/v42_bugfix_2/<timeframe>.")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Optional reproducible experiment identifier. Defaults to a deterministic hash.")
    parser.add_argument("--force", action="store_true",
                        help="Explicitly allow overwriting existing result files.")
    parser.add_argument("--data-cutoff", type=str, default=None,
                        help="Independently verified UTC cutoff (ISO-8601) for candle completion. Required in strict mode.")
    parser.add_argument("--cutoff-mode", choices=list(CUTOFF_MODES),
                        default=DEFAULT_CUTOFF_MODE,
                        help="strict (default, requires --data-cutoff) or diagnostic (infers an unverified cutoff).")
    parser.add_argument("--min-quantity", type=float, default=None,
                        help="Optional execution constraint. Disabled when omitted.")
    parser.add_argument("--quantity-precision", type=int, default=None,
                        help="Optional decimal places for quantity. Disabled when omitted.")
    parser.add_argument("--min-notional", type=float, default=None,
                        help="Optional minimum entry notional. Disabled when omitted.")
    args = parser.parse_args()

    tf = args.timeframe
    base_path = (args.base or BASE_DATA_FILES[tf]).expanduser().resolve()
    htf_path = (args.htf or HTF_DATA_FILES[tf]).expanduser().resolve()
    output_dir = (args.output.expanduser().resolve() if args.output
                  else default_output_directory(tf))
    execution_constraints = {
        "min_quantity": args.min_quantity,
        "quantity_precision": args.quantity_precision,
        "min_notional": args.min_notional,
    }
    print("=" * 72)
    print("EMA PULLBACK V4.2 - OHLCV-ONLY RESEARCH ENGINE (BUGFIX 2)")
    print(f"TIMEFRAME   : {tf.upper()}")
    print(f"CUTOFF MODE : {args.cutoff_mode.upper()}")
    print(f"BASE DATA   : {base_path}")
    print(f"HTF DATA    : {htf_path}")
    print("Maker 5 bps / taker 2 bps per fill")

    print("Starting capital 1,000 USDT")
    print("=" * 72)

    result = run_analysis(
        tf, base_path, htf_path, output_dir=output_dir,
        run_id=args.run_id, force=args.force,
        data_cutoff=args.data_cutoff,
        cutoff_mode=args.cutoff_mode,
        execution_constraints=execution_constraints,
    )
    report = result["report"]
    print(json.dumps(json_safe(report["metrics"]), indent=2))
    print(f"\nRun ID: {report['run_id']}")
    print(f"Engine SHA-256: {report['engine_source_sha256']}")
    print(f"Data cutoff: {report['data_cutoff']} "
          f"(source={report['data_cutoff_source']}, "
          f"verified={report['data_cutoff_verified']}, "
          f"mode={report['cutoff_mode']})")
    print(f"Warm-up: {report['warmup']['reason']}")
    print(f"Base gaps reported: {report['data_quality']['base']['missing_candles']['missing_candle_count']}")
    print(f"HTF gaps reported : {report['data_quality']['htf']['missing_candles']['missing_candle_count']}")
    print(f"Excluded incomplete base candles: {report['excluded_incomplete_candles']}")
    print(f"HTF completion: {report['htf_completion_status']} "
          f"(incomplete={report['htf_completion']['incomplete_count']}, "
          f"unknown={report['htf_completion']['unknown_count']})")
    print(f"Gap-affected trades: {report['metrics']['gap_affected_trades']}")
    if report["diagnostic_warning"]:
        print("")
        print("WARNING: " + report["diagnostic_warning"])
    print(f"Reports saved to: {result['output_directory']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
