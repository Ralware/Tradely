from __future__ import annotations

import copy
import gzip
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

import numpy as np
import pandas as pd

from app.core.database import Database
from app.providers.base import get_adjustment_status
from app.services.freshness import is_candle_stale
from app.services.indicators import compute_indicators
from app.services.strategy import STRATEGY_VERSION, evaluate_trend_breakout, suppress_actionable_strategy
from app.services.tv_technical_rating import (
    DEPENDENCY as RATING_DEPENDENCY,
    SOURCE_VERSION as RATING_VERSION,
    build_technical_summary,
    ohlcv_fingerprint,
)

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 2
INDICATOR_VERSION = "tradely-indicators-v1"
DIRECTIONS = ("long_only", "short_only", "long_short")
POSITIONS = (None, "LONG", "SHORT")
# Explicit bounded ranges; provider limits and session availability still apply.
HISTORY_DAYS = {"1m": 30, "3m": 90, "5m": 180, "15m": 365, "30m": 730,
                "45m": 730, "1h": 1095, "2h": 1095, "4h": 1825,
                "6h": 1825, "8h": 1825, "12h": 1825, "1d": 3650,
                "1wk": 3650, "1mo": 3650}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _encode(value: Any) -> tuple[bytes, str]:
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False, default=str).encode()
    return gzip.compress(raw, compresslevel=6), hashlib.sha256(raw).hexdigest()


def _decode(value: bytes, checksum: str) -> dict[str, Any]:
    raw = gzip.decompress(value)
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise ValueError("Analytics snapshot checksum mismatch")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Analytics snapshot payload is not an object")
    return parsed


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True)
    data.index.name = "timestamp"
    data = data.replace({float("nan"): None})
    return data.reset_index().assign(timestamp=lambda value: value.timestamp.astype(str)).to_dict("records")


def _stale(frame: pd.DataFrame, market: str, interval: str) -> bool:
    return is_candle_stale(frame, market, interval)


class AnalyticsPrecompute:
    """SQLite-backed idempotent queue and atomic, versioned snapshot publisher."""

    def __init__(self, db: Database, market_service: Any):
        self.db = db
        self.market_service = market_service
        self.worker_id = f"analytics-{uuid.uuid4().hex[:12]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = 0
        self._last_error: str | None = None
        self._provider_requests = 0
        self._load_locks: dict[tuple[str, str], tuple[threading.Lock, int]] = {}
        self._load_locks_guard = threading.Lock()

    @contextmanager
    def _snapshot_load_lock(self, identity: tuple[str, str]) -> Iterator[None]:
        with self._load_locks_guard:
            current = self._load_locks.get(identity)
            lock = current[0] if current else threading.Lock()
            self._load_locks[identity] = (lock, (current[1] + 1) if current else 1)
        try:
            with lock:
                yield
        finally:
            with self._load_locks_guard:
                current = self._load_locks.get(identity)
                if current and current[0] is lock:
                    if current[1] <= 1:
                        self._load_locks.pop(identity, None)
                    else:
                        self._load_locks[identity] = (lock, current[1] - 1)

    def enqueue(self, instrument_id: str, interval: str, *, priority: int = 0,
                job_type: str = "FULL_REFRESH") -> str:
        now = _now()
        job_id = uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT job_id FROM analytics_jobs WHERE instrument_id=? AND interval=? "
                "AND status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT 1",
                (instrument_id, interval),
            ).fetchone()
            if active:
                conn.commit()
                return str(active["job_id"])
            conn.execute(
                """INSERT OR IGNORE INTO analytics_jobs
                   (job_id,instrument_id,interval,job_type,priority,status,scheduled_at,
                    created_at,updated_at) VALUES(?,?,?,?,?,'QUEUED',?,?,?)""",
                (job_id, instrument_id, interval, job_type, priority, now, now, now),
            )
            row = conn.execute(
                "SELECT job_id FROM analytics_jobs WHERE instrument_id=? AND interval=? "
                "AND job_type=? AND status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT 1",
                (instrument_id, interval, job_type),
            ).fetchone()
        return str(row["job_id"] if row else job_id)

    def enqueue_watchlist(self) -> int:
        count = 0
        for instrument in self.db.get_watchlist():
            identity = instrument.get("instrument_id")
            if not identity:
                continue
            count += self.register_watchlist_instrument(str(identity))["queued"]
        return count

    def register_watchlist_instrument(self, instrument_id: str) -> dict[str, Any]:
        """Reconcile one persisted watchlist member without recomputing valid data."""
        instrument = self.db.instrument_for_id(instrument_id)
        if instrument is None:
            raise ValueError(f"Unknown instrument: {instrument_id}")
        configured = instrument.get("supported_intervals") or []
        if isinstance(configured, str):
            try:
                configured = json.loads(configured)
            except ValueError:
                configured = []
        intervals = [value for value in (configured or ("1d", "1wk", "1mo")) if value in HISTORY_DAYS]
        queued = 0
        reused = 0
        for interval in intervals:
            snapshot = self.get_snapshot(instrument_id, interval)
            if snapshot is not None and not self._snapshot_is_stale(snapshot):
                reused += 1
                continue
            self.enqueue(
                instrument_id, interval, priority=10,
                job_type="WATCHLIST_REFRESH" if snapshot is not None else "WATCHLIST_PREFETCH",
            )
            queued += 1
        logger.info(
            "[PREFETCH] registration complete instrument=%s reused=%d queued=%d",
            instrument_id, reused, queued,
        )
        return {"instrument_id": instrument_id, "registered": True,
                "intervals": intervals, "reused": reused, "queued": queued}

    def cancel_watchlist_jobs(self, instrument_id: str) -> int:
        """Cancel queued watchlist-specific jobs while retaining all cached data."""
        with self.db.connect() as conn:
            cursor = conn.execute(
                "UPDATE analytics_jobs SET status='CANCELLED',updated_at=? "
                "WHERE instrument_id=? AND job_type IN ('INITIAL_COMPUTATION','WATCHLIST_PREFETCH',"
                "'WATCHLIST_REFRESH') AND status='QUEUED'",
                (_now(), instrument_id),
            )
        return cursor.rowcount

    def _claim(self) -> sqlite3.Row | None:
        now = datetime.now(UTC)
        lease = (now + timedelta(minutes=5)).isoformat()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE analytics_jobs SET status='QUEUED',worker_id=NULL,lease_until=NULL,
                   updated_at=? WHERE status='RUNNING' AND lease_until < ?""",
                (now.isoformat(), now.isoformat()),
            )
            row = conn.execute(
                """SELECT * FROM analytics_jobs WHERE status='QUEUED' AND scheduled_at<=?
                   ORDER BY priority DESC,created_at LIMIT 1""", (now.isoformat(),)
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """UPDATE analytics_jobs SET status='RUNNING',worker_id=?,started_at=?,
                   lease_until=?,attempts=attempts+1,updated_at=? WHERE job_id=? AND status='QUEUED'""",
                (self.worker_id, now.isoformat(), lease, now.isoformat(), row["job_id"]),
            )
            conn.commit()
            return row

    def run_one(self) -> bool:
        job = self._claim()
        if job is None:
            return False
        self._active += 1
        try:
            if str(job["job_type"]) in {"INITIAL_COMPUTATION", "WATCHLIST_PREFETCH", "WATCHLIST_REFRESH"}:
                watched = any(item.get("instrument_id") == job["instrument_id"] for item in self.db.get_watchlist())
                if not watched:
                    with self.db.connect() as conn:
                        conn.execute(
                            "UPDATE analytics_jobs SET status='CANCELLED',lease_until=NULL,updated_at=? WHERE job_id=?",
                            (_now(), job["job_id"]),
                        )
                    return True
            identity = (str(job["instrument_id"]), str(job["interval"]))
            with self._snapshot_load_lock(identity):
                existing = self.get_snapshot(*identity)
                if (str(job["job_type"]) in {"INITIAL_COMPUTATION", "WATCHLIST_PREFETCH", "WATCHLIST_REFRESH"}
                        and existing is not None and not self._snapshot_is_stale(existing)):
                    logger.info("[PREFETCH] skipped valid dataset instrument=%s interval=%s", *identity)
                else:
                    self._compute_and_publish(*identity)
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE analytics_jobs SET status='COMPLETED',completed_at=?,lease_until=NULL,updated_at=? WHERE job_id=?",
                    (_now(), _now(), job["job_id"]),
                )
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            attempts = int(job["attempts"]) + 1
            retry = attempts < int(job["max_attempts"])
            delay = min(3600, 15 * (2 ** max(0, attempts - 1)))
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE analytics_jobs SET status=?,last_error=?,lease_until=NULL,
                       scheduled_at=?,updated_at=? WHERE job_id=?""",
                    ("QUEUED" if retry else "FAILED",
                     str(exc)[:2000], (datetime.now(UTC)+timedelta(seconds=delay)).isoformat(), _now(), job["job_id"]),
                )
            logger.exception("analytics job failed id=%s instrument=%s interval=%s", job["job_id"], job["instrument_id"], job["interval"])
        finally:
            self._active -= 1
        return True

    def _compute_and_publish(self, instrument_id: str, interval: str, *, bypass_cache: bool = True) -> None:
        instrument = self.db.instrument_for_id(instrument_id)
        if not instrument:
            raise ValueError(f"Unknown instrument: {instrument_id}")
        price_metadata: dict[str, Any] = {}
        try:
            price_metadata = self.market_service.price_metadata(
                instrument["symbol"], instrument.get("exchange")
            )
        except Exception:  # metadata is optional; never block analytics
            logger.debug("[MARKET] price metadata unavailable for %s", instrument_id)
        days = HISTORY_DAYS[interval]
        frame, source = self.market_service.candles(
            instrument["symbol"], market=instrument["market"], exchange=instrument.get("exchange"),
            interval=interval, days=days, provider="auto", full_history=False, bypass_cache=bypass_cache,
        )
        self._provider_requests += 1
        if frame.empty:
            raise ValueError("Provider returned no candles")
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
            raise ValueError("OHLCV contains missing values")
        if not np.isfinite(frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)).all():
            raise ValueError("OHLCV contains non-finite values")
        if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
                (frame["low"] > frame[["open", "close", "high"]].min(axis=1)) |
                (frame["volume"] < 0)).any():
            raise ValueError("OHLCV validation failed")
        adjustment_status = get_adjustment_status(frame)
        is_adjusted = True if adjustment_status == "adjusted" else False if adjustment_status == "unadjusted" else None
        frame.attrs.update({"source": source, "adjustment_status": adjustment_status, "is_adjusted": is_adjusted})
        fingerprint = ohlcv_fingerprint(frame)
        adjusted = adjustment_status
        now = _now()
        indicators = compute_indicators(frame)
        technical = build_technical_summary(frame)
        if indicators.empty or technical.get("summary", {}).get("overall", {}).get("available", 0) <= 0:
            raise ValueError("Analytics calculations are incomplete for the retrieved candle history")
        if len(indicators) != len(frame):
            raise ValueError("Indicator series is incomplete for the retrieved candle history")
        latest = indicators.iloc[-1]
        values = {column: (None if pd.isna(value) else float(value))
                  for column, value in latest.items() if column not in {"open","high","low","close","volume"}}
        stale = _stale(frame, instrument["market"], interval)
        warnings: list[str] = []
        if stale:
            warnings.append("Latest candle is stale for this market; actionable signal output is suppressed.")
        if instrument["market"] == "india" and adjustment_status != "adjusted":
            if adjustment_status == "unknown":
                warnings.append("Historical corporate-action adjustment status could not be verified. Indian-equity strategy output is suppressed.")
            else:
                warnings.append("Indian equity candles are known to be unadjusted. Corporate actions can distort long-term indicators; strategy output is suppressed.")
        history_truncated = bool(frame.attrs.get("history_truncated", False))
        history_pages = frame.attrs.get("history_pages")
        last_bar_confirmed = frame.attrs.get("last_bar_confirmed")
        forming_bar_excluded = bool(frame.attrs.get("forming_bar_excluded", False))
        if history_truncated:
            warnings.append("The provider returned the maximum requested bar count; older history may exist.")
        instrument_view = {**instrument, **price_metadata}
        strategies: dict[str, Any] = {}
        for direction in DIRECTIONS:
            for position in POSITIONS:
                result = evaluate_trend_breakout(
                    frame, symbol=instrument["symbol"], market=instrument["market"], source=source,
                    direction_mode=direction, position_side=position, indicators=indicators,
                ).model_dump(mode="json")
                if stale or (instrument["market"] == "india" and adjustment_status != "adjusted"):
                    result = suppress_actionable_strategy(
                        result, state="STALE_DATA" if stale else "DATA_QUALITY_ERROR",
                        explanation=(
                            "Strategy signal suppressed because fresh market data could not be retrieved."
                            if stale else
                            "Strategy signal suppressed because historical corporate-action adjustment status could not be verified."
                            if adjustment_status == "unknown" else
                            "Strategy signal suppressed because the Indian-equity history is known to be unadjusted."
                        ),
                    )
                strategies[f"{direction}:{position or 'NONE'}"] = result
        payload = {
            "schema_version": SCHEMA_VERSION,
            "symbol": instrument["symbol"], "market": instrument["market"],
            "exchange": instrument.get("exchange"), "instrument": instrument_view,
            "price_metadata": price_metadata,
            "interval": interval, "source": source, "is_adjusted": is_adjusted, "adjustment_status": adjustment_status,
            "fingerprint": fingerprint, "generated_at": now,
            "history_truncated": history_truncated, "history_pages": history_pages,
            "last_candle_confirmed": last_bar_confirmed,
            "forming_bar_excluded": forming_bar_excluded,
            "analysis": {"symbol": instrument["symbol"], "market": instrument["market"],
                "exchange": instrument.get("exchange"), "instrument": instrument_view, "interval": interval,
                "source": source, "is_adjusted": is_adjusted, "adjustment_status": adjustment_status, "is_stale": stale,
                "history_truncated": history_truncated, "history_pages": history_pages,
                "last_candle_confirmed": last_bar_confirmed,
                "forming_bar_excluded": forming_bar_excluded,
                "price_metadata": price_metadata,
                "as_of": frame.index[-1].isoformat(), "fingerprint": fingerprint,
                "latest": {key: float(latest[key]) for key in ("open","high","low","close","volume")},
                "indicators": values, "candles": _records(frame), "warnings": warnings},
            "indicator_series": {"interval": interval, "source": source, "fingerprint": fingerprint,
                "instrument": instrument_view, "price_metadata": price_metadata,
                "count": len(indicators), "series": _records(indicators)},
            "technical_ratings": {"source": source, "interval": interval,
                "instrument": instrument_view, "price_metadata": price_metadata,
                "is_adjusted": is_adjusted, "adjustment_status": adjustment_status, "is_stale": stale, "as_of": frame.index[-1].isoformat(),
                "fingerprint": fingerprint, **technical},
            "strategy_variants": strategies,
            "provenance": {"instrument_id": instrument_id, "source": source, "interval": interval,
                "is_adjusted": is_adjusted, "adjustment_status": adjustment_status, "ohlcv_fingerprint": fingerprint,
                "candle_count": len(frame), "latest_candle_timestamp": frame.index[-1].isoformat(),
                "last_candle_confirmed": last_bar_confirmed,
                "candle_status": ("confirmed" if last_bar_confirmed is True
                                  else "unconfirmed" if last_bar_confirmed is False else "unknown"),
                "forming_bar_excluded": forming_bar_excluded,
                "history_truncated": history_truncated, "history_pages": history_pages,
                "price_metadata": price_metadata,
                "snapshot_generated_at": now, "data_freshness": "stale" if stale else "fresh"},
        }
        blob, checksum = _encode(payload)
        identity = hashlib.sha256(f"{instrument_id}|{interval}|{fingerprint}|{SCHEMA_VERSION}".encode()).hexdigest()[:32]
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Bar upserts and snapshot publication share one short transaction.
            rows = [(instrument_id, interval, pd.Timestamp(ts).tz_convert("UTC").isoformat(),
                     float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume),
                     source, adjusted, now) for ts, r in frame.iterrows()]
            conn.executemany(
                """INSERT INTO market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id,interval,timestamp,adjustment_status,source) DO UPDATE SET
                   open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
                   volume=excluded.volume,updated_at=excluded.updated_at""", rows,
            )
            conn.execute(
                """INSERT INTO market_analytics_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id,interval,ohlcv_fingerprint,schema_version) DO UPDATE SET
                   generated_at=excluded.generated_at,updated_at=excluded.updated_at,status='READY',
                   payload=excluded.payload,payload_checksum=excluded.payload_checksum""",
                (identity,instrument_id,interval,fingerprint,INDICATOR_VERSION,RATING_DEPENDENCY,
                 RATING_VERSION,source,source,adjusted,frame.index[-1].isoformat(),len(frame),now,now,
                 SCHEMA_VERSION,"READY",blob,checksum),
            )
            for key, value in strategies.items():
                direction, position = key.split(":",1)
                strategy_blob, strategy_checksum = _encode(value)
                strategy_id = hashlib.sha256(f"{identity}|{STRATEGY_VERSION}|{direction}|{position}".encode()).hexdigest()[:32]
                conn.execute(
                    """INSERT INTO strategy_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(instrument_id,interval,ohlcv_fingerprint,strategy_version,
                         strategy_configuration_hash,direction_mode,position_side) DO UPDATE SET
                         market_snapshot_id=excluded.market_snapshot_id,generated_at=excluded.generated_at,
                         status='READY',payload=excluded.payload,payload_checksum=excluded.payload_checksum""",
                    (strategy_id,identity,instrument_id,interval,fingerprint,STRATEGY_VERSION,
                     "default-v1",direction,position,now,"READY",strategy_blob,strategy_checksum),
                )
            conn.commit()

    def get_snapshot(self, instrument_id: str, interval: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM market_analytics_snapshots WHERE instrument_id=? AND interval=?
                   AND status='READY' ORDER BY generated_at DESC""", (instrument_id, interval)
            )
            for row in rows:
                variants = conn.execute(
                    "SELECT * FROM strategy_snapshots WHERE market_snapshot_id=? AND status='READY'",
                    (row["snapshot_id"],),
                ).fetchall()
                if any(variant["strategy_version"] != STRATEGY_VERSION
                       or variant["strategy_configuration_hash"] != "default-v1"
                       or variant["ohlcv_fingerprint"] != row["ohlcv_fingerprint"]
                       for variant in variants):
                    logger.warning("[CACHE] strategy version mismatch instrument=%s interval=%s",
                                   instrument_id, interval)
                    continue
                try:
                    payload = _decode(row["payload"], row["payload_checksum"])
                    variants = {
                        f"{variant['direction_mode']}:{variant['position_side']}":
                        _decode(variant["payload"], variant["payload_checksum"])
                        for variant in variants
                    }
                    payload["strategy_variants"] = variants
                    if self._snapshot_complete(payload, instrument_id, interval, row):
                        return payload
                    logger.warning("[CACHE] incomplete snapshot skipped instrument=%s interval=%s", instrument_id, interval)
                except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError):
                    logger.exception("[CACHE] invalid snapshot skipped instrument=%s interval=%s", instrument_id, interval)
        return None

    @staticmethod
    def _snapshot_complete(payload: dict[str, Any], instrument_id: str, interval: str,
                           row: sqlite3.Row | dict[str, Any] | None = None) -> bool:
        try:
            if payload.get("schema_version") != SCHEMA_VERSION or payload.get("interval") != interval:
                return False
            if payload.get("provenance", {}).get("instrument_id") != instrument_id:
                return False
            fingerprint = payload.get("fingerprint")
            candles = payload["analysis"]["candles"]
            series = payload["indicator_series"]["series"]
            ratings = payload["technical_ratings"]
            variants = payload.get("strategy_variants", {})
            expected_variants = {
                f"{direction}:{position or 'NONE'}"
                for direction in DIRECTIONS for position in POSITIONS
            }
            if (not fingerprint or not candles or len(series) != len(candles)
                    or payload["indicator_series"].get("count") != len(candles)
                    or payload.get("provenance", {}).get("candle_count") != len(candles)):
                return False
            if payload.get("adjustment_status") not in {"adjusted", "unadjusted", "unknown"}:
                return False
            if ratings.get("fingerprint") != fingerprint:
                return False
            if payload["analysis"].get("fingerprint") != fingerprint:
                return False
            if set(variants) != expected_variants:
                return False
            if ratings.get("summary", {}).get("overall", {}).get("available", 0) <= 0:
                return False
            latest = payload["analysis"]["latest"]
            if not all(np.isfinite(float(latest[key])) for key in ("open", "high", "low", "close", "volume")):
                return False
            if row is not None and (
                row["schema_version"] != SCHEMA_VERSION
                or row["indicator_version"] != INDICATOR_VERSION
                or row["indicator_dependency_version"] != RATING_DEPENDENCY
                or row["rating_version"] != RATING_VERSION
                or row["ohlcv_fingerprint"] != fingerprint
                or row["adjustment_status"] != payload.get("adjustment_status")
                or row["candle_count"] != len(candles)
            ):
                return False
            return all(isinstance(value, dict) and value for value in variants.values())
        except (KeyError, TypeError, AttributeError):
            return False

    def get_or_compute_snapshot(self, instrument_id: str, interval: str) -> dict[str, Any]:
        """Load valid local data, or compute/publish one live snapshot on a miss."""
        if interval not in HISTORY_DAYS:
            raise ValueError(f"Unsupported interval: {interval}")
        cached = self.get_snapshot(instrument_id, interval)
        if cached is not None and not self._snapshot_is_stale(cached):
            return cached
        identity = (instrument_id, interval)
        with self._snapshot_load_lock(identity):
            cached = self.get_snapshot(instrument_id, interval)
            if cached is not None and not self._snapshot_is_stale(cached):
                return cached
            logger.info("[CACHE] %s instrument=%s interval=%s",
                        "stale" if cached is not None else "miss", instrument_id, interval)
            try:
                self._compute_and_publish(instrument_id, interval, bypass_cache=False)
            except Exception:
                if cached is None:
                    raise
                logger.exception("[CACHE] refresh failed; retaining last-known-good instrument=%s interval=%s",
                                 instrument_id, interval)
                return self._stale_reference_snapshot(cached)
            result = self.get_snapshot(instrument_id, interval)
            if result is None:
                raise ValueError("Analytics calculation did not produce a complete snapshot")
            return result

    @staticmethod
    def _stale_reference_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a detached reference-only copy with every cached signal invalidated."""
        result = copy.deepcopy(payload)
        result["is_stale"] = True
        warning = ("Fresh market data could not be obtained. Strategy output is suppressed; "
                   "this analytical snapshot is retained for reference only and requires a successful refresh.")
        analysis = result.setdefault("analysis", {})
        analysis["is_stale"] = True
        warnings = analysis.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
            analysis["warnings"] = warnings
        if warning not in warnings:
            warnings.append(warning)
        result.setdefault("technical_ratings", {})["is_stale"] = True
        series = result.get("indicator_series")
        if isinstance(series, dict):
            series["is_stale"] = True
        result.setdefault("provenance", {})["data_freshness"] = "stale"
        variants = result.get("strategy_variants")
        if not isinstance(variants, dict):
            variants = {}
            result["strategy_variants"] = variants
        for key, value in list(variants.items()):
            variant = value if isinstance(value, dict) else {}
            variants[key] = suppress_actionable_strategy(
                variant, state="STALE_DATA",
                explanation="Strategy signal suppressed because fresh market data could not be retrieved. The displayed analytical snapshot is retained for reference only.",
            )
        return result

    @staticmethod
    def _snapshot_is_stale(payload: dict[str, Any]) -> bool:
        try:
            provenance = payload["provenance"]
            timestamp = pd.to_datetime(provenance["latest_candle_timestamp"], utc=True)
            interval = str(payload["interval"])
            market = str(payload["market"])
            probe = pd.DataFrame({"close": [0.0]}, index=pd.DatetimeIndex([timestamp]))
            return _stale(probe, market, interval)
        except (KeyError, TypeError, ValueError):
            return True

    def manifest(self) -> dict[str, Any]:
        """Return a cheap index without decoding historical analytics BLOBs.

        Individual snapshot requests still verify payload checksums and completeness;
        this application-wide manifest needs only indexed metadata to decide what to hydrate.
        """
        result = []
        watchlist = self.db.get_watchlist()
        with self.db.connect() as conn:
            for instrument in watchlist:
                instrument_id = instrument.get("instrument_id")
                if not instrument_id:
                    continue
                registry_entry = self.db.instrument_for_id(str(instrument_id)) or instrument
                configured = registry_entry.get("supported_intervals")
                if isinstance(configured, str):
                    try: configured = json.loads(configured)
                    except ValueError: configured = []
                for interval in configured or ("1d", "1wk", "1mo"):
                    if interval not in HISTORY_DAYS: continue
                    snapshot = conn.execute(
                        """SELECT snapshot_id,ohlcv_fingerprint,latest_candle_at,candle_count,
                                  generated_at,schema_version,indicator_version,
                                  indicator_dependency_version,rating_version,adjustment_status
                           FROM market_analytics_snapshots WHERE instrument_id=? AND interval=?
                             AND status='READY' ORDER BY generated_at DESC LIMIT 1""",
                        (instrument_id, interval),
                    ).fetchone()
                    job = conn.execute(
                        "SELECT status,last_error FROM analytics_jobs WHERE instrument_id=? AND interval=? ORDER BY created_at DESC LIMIT 1",
                        (instrument_id, interval),
                    ).fetchone()
                    if snapshot:
                        strategy_count = conn.execute(
                            """SELECT COUNT(*) FROM strategy_snapshots
                               WHERE market_snapshot_id=? AND status='READY'
                                 AND strategy_version=? AND strategy_configuration_hash='default-v1'
                                 AND ohlcv_fingerprint=?""",
                            (snapshot["snapshot_id"], STRATEGY_VERSION, snapshot["ohlcv_fingerprint"]),
                        ).fetchone()[0]
                        metadata_matches = (
                            snapshot["schema_version"] == SCHEMA_VERSION
                            and snapshot["indicator_version"] == INDICATOR_VERSION
                            and snapshot["indicator_dependency_version"] == RATING_DEPENDENCY
                            and snapshot["rating_version"] == RATING_VERSION
                            and snapshot["adjustment_status"] in {"adjusted", "unadjusted", "unknown"}
                        )
                        if not metadata_matches or strategy_count != len(DIRECTIONS) * len(POSITIONS):
                            snapshot = None
                    job_status = str(job["status"]) if job else "MISSING"
                    if not snapshot and job_status not in {"QUEUED", "RUNNING", "FAILED"}:
                        job_status = "MISSING"
                    result.append({"instrument_id":instrument_id,"interval":interval,
                        "status":"READY" if snapshot else job_status,
                        "snapshot_id":snapshot["snapshot_id"] if snapshot else None,
                        "fingerprint":snapshot["ohlcv_fingerprint"] if snapshot else None,
                        "latest_candle_at":snapshot["latest_candle_at"] if snapshot else None,
                        "candle_count":snapshot["candle_count"] if snapshot else 0,
                        "generated_at":snapshot["generated_at"] if snapshot else None,
                        "last_error":job["last_error"] if job else None})
        return {"items":result,"as_of":_now()}

    def status(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            counts = {row["status"]:row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM analytics_jobs GROUP BY status")}
        return {"worker_id":self.worker_id,"running_workers":self._active,"jobs":counts,
                "last_error":self._last_error,"provider_requests":self._provider_requests,
                "scheduler_running":bool(self._thread and self._thread.is_alive())}

    def start(self, *, poll_seconds: float = 2.0) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, args=(poll_seconds,), daemon=True, name="analytics-worker")
        self._thread.start()

    def _serve(self, poll_seconds: float) -> None:
        while not self._stop.is_set():
            if not self.run_one(): self._stop.wait(poll_seconds)

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout)
        with self.db.connect() as conn:
            conn.execute("UPDATE analytics_jobs SET status='QUEUED',worker_id=NULL,lease_until=NULL,updated_at=? WHERE status='RUNNING' AND worker_id=?",
                         (_now(), self.worker_id))
