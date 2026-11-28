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
from app.services.tv_technical_rating import (
    DEPENDENCY as RATING_DEPENDENCY,
    SOURCE_VERSION as RATING_VERSION,
    build_technical_summary,
    ohlcv_fingerprint,
)

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 3
INDICATOR_VERSION = "tradely-indicators-v1"
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
        settings = getattr(market_service, "settings", None)
        self.worker_concurrency = max(
            1, int(getattr(settings, "analytics_worker_concurrency", 1))
        )
        self.lease_seconds = max(
            30, int(getattr(settings, "analytics_worker_lease_seconds", 300))
        )
        self.poll_seconds = max(
            0.1, float(getattr(settings, "analytics_worker_poll_seconds", 2.0))
        )
        self.snapshot_retention_enabled = bool(
            getattr(settings, "analytics_snapshot_retention_enabled", True)
        )
        self.snapshot_retention = max(
            1, int(getattr(settings, "analytics_snapshot_retention_per_series", 2))
        )
        self._worker_ids = [
            self.worker_id if index == 0 else f"{self.worker_id}-{index}"
            for index in range(self.worker_concurrency)
        ]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Retained for callers/tests that only need the primary worker handle.
        self._thread: threading.Thread | None = None
        self._active = 0
        self._active_lock = threading.Lock()
        self._last_error: str | None = None
        self._provider_requests = 0
        self._load_locks: dict[tuple[str, str], tuple[threading.Lock, int]] = {}
        self._load_locks_guard = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._metrics: dict[str, float] = {
            "enqueued": 0,
            "deduplicated": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "queue_wait_seconds": 0.0,
            "compute_seconds": 0.0,
        }

    def _record(self, name: str, amount: float = 1.0) -> None:
        with self._metrics_lock:
            self._metrics[name] = self._metrics.get(name, 0.0) + amount

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
                "SELECT job_id,job_type,status FROM analytics_jobs "
                "WHERE instrument_id=? AND interval=? "
                "AND status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT 1",
                (instrument_id, interval),
            ).fetchone()
            if active:
                # Explicit refresh must not be swallowed by an ordinary queued
                # prefetch. Promote the existing queued job instead of creating
                # a duplicate, so request deduplication is preserved while the
                # eventual computation still performs a full provider refresh.
                if job_type == "FULL_REFRESH" and active["job_type"] != "FULL_REFRESH":
                    if active["status"] == "QUEUED":
                        try:
                            conn.execute(
                                "UPDATE analytics_jobs SET job_type='FULL_REFRESH',"
                                "priority=MAX(priority,?),updated_at=? WHERE job_id=?",
                                (priority, now, active["job_id"]),
                            )
                        except sqlite3.IntegrityError:
                            # Another full-refresh row already holds the
                            # identity; fall through to the lookup below.
                            pass
                        conn.commit()
                        self._record("deduplicated")
                        return str(active["job_id"])
                    # The ordinary job is already running. Queue a distinct
                    # full refresh so the explicit request is still honoured
                    # once the in-flight computation finishes; the unique
                    # partial index permits one active row per job type.
                    conn.execute(
                        """INSERT OR IGNORE INTO analytics_jobs
                           (job_id,instrument_id,interval,job_type,priority,status,
                            scheduled_at,created_at,updated_at)
                           VALUES(?,?,?,?,?,'QUEUED',?,?,?)""",
                        (job_id, instrument_id, interval, job_type, priority, now, now, now),
                    )
                    row = conn.execute(
                        "SELECT job_id FROM analytics_jobs WHERE instrument_id=? "
                        "AND interval=? AND job_type='FULL_REFRESH' "
                        "AND status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT 1",
                        (instrument_id, interval),
                    ).fetchone()
                    conn.commit()
                    self._record("enqueued")
                    return str(row["job_id"] if row else active["job_id"])
                conn.commit()
                self._record("deduplicated")
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
        self._record("enqueued")
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

    def _claim(self, worker_id: str | None = None) -> sqlite3.Row | None:
        worker_id = worker_id or self.worker_id
        now = datetime.now(UTC)
        lease = (now + timedelta(seconds=self.lease_seconds)).isoformat()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Recover leases from crashed processes. A live worker renews its
            # lease while computing, so only genuinely expired work is requeued.
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
            updated = conn.execute(
                """UPDATE analytics_jobs SET status='RUNNING',worker_id=?,started_at=?,
                   lease_until=?,attempts=attempts+1,updated_at=?
                   WHERE job_id=? AND status='QUEUED'""",
                (worker_id, now.isoformat(), lease, now.isoformat(), row["job_id"]),
            )
            conn.commit()
            if updated.rowcount != 1:
                # Another worker won the claim between SELECT and UPDATE.
                return None
            self._record("claimed")
            try:
                scheduled = datetime.fromisoformat(str(row["scheduled_at"]))
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=UTC)
                self._record(
                    "queue_wait_seconds",
                    max(0.0, (now - scheduled).total_seconds()),
                )
            except (TypeError, ValueError):
                pass
            return row

    def _renew_lease(self, job_id: str, worker_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE analytics_jobs SET lease_until=?,updated_at=? "
                "WHERE job_id=? AND status='RUNNING' AND worker_id=?",
                (
                    (datetime.now(UTC) + timedelta(seconds=self.lease_seconds)).isoformat(),
                    _now(),
                    job_id,
                    worker_id,
                ),
            )

    def _lease_heartbeat(self, job_id: str, worker_id: str) -> threading.Event:
        stop = threading.Event()
        interval = max(5.0, self.lease_seconds / 3.0)

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    self._renew_lease(job_id, worker_id)
                except Exception:  # lease renewal must not crash the worker
                    logger.debug("[QUEUE] lease renewal failed job=%s", job_id)

        threading.Thread(target=beat, daemon=True, name="analytics-lease").start()
        return stop

    def run_one(self, worker_id: str | None = None) -> bool:
        worker_id = worker_id or self.worker_id
        job = self._claim(worker_id)
        if job is None:
            return False
        with self._active_lock:
            self._active += 1
        job_id = str(job["job_id"])
        job_type = str(job["job_type"])
        heartbeat = self._lease_heartbeat(job_id, worker_id)
        started = time.perf_counter()
        try:
            if job_type in {"INITIAL_COMPUTATION", "WATCHLIST_PREFETCH", "WATCHLIST_REFRESH"}:
                watched = any(item.get("instrument_id") == job["instrument_id"] for item in self.db.get_watchlist())
                if not watched:
                    with self.db.connect() as conn:
                        conn.execute(
                            "UPDATE analytics_jobs SET status='CANCELLED',lease_until=NULL,updated_at=? WHERE job_id=?",
                            (_now(), job_id),
                        )
                    self._record("cancelled")
                    return True
            identity = (str(job["instrument_id"]), str(job["interval"]))
            with self._snapshot_load_lock(identity):
                existing = self.get_snapshot(*identity)
                if (job_type in {"INITIAL_COMPUTATION", "WATCHLIST_PREFETCH", "WATCHLIST_REFRESH"}
                        and existing is not None and not self._snapshot_is_stale(existing)):
                    logger.info("[PREFETCH] skipped valid dataset instrument=%s interval=%s", *identity)
                else:
                    # Normal background refresh reuses the cached historical
                    # frame and only merges the newest tail. Only an explicit
                    # FULL_REFRESH job bypasses the provider cache.
                    self._compute_and_publish(
                        *identity,
                        bypass_cache=job_type == "FULL_REFRESH",
                    )
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE analytics_jobs SET status='COMPLETED',completed_at=?,lease_until=NULL,updated_at=? WHERE job_id=?",
                    (_now(), _now(), job_id),
                )
            self._record("completed")
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
                     str(exc)[:2000], (datetime.now(UTC)+timedelta(seconds=delay)).isoformat(), _now(), job_id),
                )
            self._record("failed")
            logger.exception("analytics job failed id=%s instrument=%s interval=%s", job_id, job["instrument_id"], job["interval"])
        finally:
            heartbeat.set()
            self._record("compute_seconds", time.perf_counter() - started)
            with self._active_lock:
                self._active -= 1
        return True

    def _compute_and_publish(
        self, instrument_id: str, interval: str, *, bypass_cache: bool = False,
        refresh_latest: bool = False,
    ) -> None:
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
            interval=interval, days=days, provider="auto", full_history=False,
            bypass_cache=bypass_cache, refresh_latest=refresh_latest,
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
            warnings.append("Latest candle is stale for this market; refresh to retrieve current technical data.")
        if instrument["market"] == "india" and adjustment_status != "adjusted":
            if adjustment_status == "unknown":
                warnings.append("Historical corporate-action adjustment status could not be verified.")
            else:
                warnings.append("Indian equity candles are known to be unadjusted. Corporate actions can distort long-term indicators.")
        history_truncated = bool(frame.attrs.get("history_truncated", False))
        history_pages = frame.attrs.get("history_pages")
        last_bar_confirmed = frame.attrs.get("last_bar_confirmed")
        forming_bar_excluded = bool(frame.attrs.get("forming_bar_excluded", False))
        if history_truncated:
            warnings.append("The provider returned the maximum requested bar count; older history may exist.")
        instrument_view = {**instrument, **price_metadata}
        payload = {
            "schema_version": SCHEMA_VERSION,
            "symbol": instrument["symbol"], "market": instrument["market"],
            "exchange": instrument.get("exchange"), "instrument": instrument_view,
            "forming_candle": frame.attrs.get("forming_candle"),
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
        identity_parts = (instrument_id, interval, fingerprint, source, adjusted, INDICATOR_VERSION,
                          RATING_DEPENDENCY, RATING_VERSION, SCHEMA_VERSION)
        identity = hashlib.sha256(json.dumps(identity_parts).encode()).hexdigest()[:32]
        payload["snapshot_id"] = identity
        blob, checksum = _encode(payload)
        bar_columns = ["open", "high", "low", "close", "volume"]
        rows = [
            (instrument_id, interval, ts.isoformat(), op, high, low, close, volume, source, adjusted, now)
            for ts, op, high, low, close, volume in frame[bar_columns].astype(float).tz_convert("UTC").itertuples(name=None)
        ]
        write_started = time.perf_counter()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """INSERT INTO market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id,interval,timestamp,adjustment_status,source) DO UPDATE SET
                   open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
                   volume=excluded.volume,updated_at=excluded.updated_at
                   WHERE market_bars.open != excluded.open OR market_bars.high != excluded.high
                      OR market_bars.low != excluded.low OR market_bars.close != excluded.close
                      OR market_bars.volume != excluded.volume""", rows,
            )
            conn.execute(
                """INSERT INTO market_analytics_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(instrument_id,interval,ohlcv_fingerprint,schema_version) DO UPDATE SET
                   snapshot_id=excluded.snapshot_id,indicator_version=excluded.indicator_version,
                   indicator_dependency_version=excluded.indicator_dependency_version,
                   rating_version=excluded.rating_version,provider_identity=excluded.provider_identity,
                   source_identity=excluded.source_identity,adjustment_status=excluded.adjustment_status,
                   generated_at=excluded.generated_at,updated_at=excluded.updated_at,status='READY',
                   payload=excluded.payload,payload_checksum=excluded.payload_checksum""",
                (identity,instrument_id,interval,fingerprint,INDICATOR_VERSION,RATING_DEPENDENCY,
                 RATING_VERSION,source,source,adjusted,frame.index[-1].isoformat(),len(frame),now,now,
                 SCHEMA_VERSION,"READY",blob,checksum),
            )
            conn.commit()
        self._record("snapshot_writes")
        self._record("snapshot_write_seconds", time.perf_counter() - write_started)
        self._prune_series_snapshots(instrument_id, interval)

    def _prune_series_snapshots(self, instrument_id: str, interval: str) -> None:
        """Bound regenerable snapshot growth for one instrument/interval series.

        The newest snapshots are kept as a fallback for ``get_snapshot``; older
        rows are deleted together so the local cache remains bounded.
        """
        if not self.snapshot_retention_enabled:
            return
        connection = self.db.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            ids = [
                str(row[0])
                for row in connection.execute(
                    """SELECT snapshot_id FROM market_analytics_snapshots
                       WHERE instrument_id=? AND interval=?
                       ORDER BY generated_at DESC, updated_at DESC, snapshot_id DESC
                       LIMIT -1 OFFSET ?""",
                    (instrument_id, interval, self.snapshot_retention),
                )
            ]
            if ids:
                marks = ",".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM market_analytics_snapshots WHERE snapshot_id IN ({marks})",
                    ids,
                )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            logger.warning(
                "[CACHE] snapshot retention failed instrument=%s interval=%s",
                instrument_id,
                interval,
                exc_info=True,
            )
        finally:
            connection.close()

    @staticmethod
    def _candle_timestamp_is_stale(
        timestamp: Any, market: str, interval: str
    ) -> bool:
        try:
            value = pd.to_datetime(timestamp, utc=True)
            probe = pd.DataFrame({"close": [0.0]}, index=pd.DatetimeIndex([value]))
            return _stale(probe, market, interval)
        except (TypeError, ValueError):
            return True

    def get_snapshot(self, instrument_id: str, interval: str) -> dict[str, Any] | None:
        started = time.perf_counter()
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT * FROM market_analytics_snapshots WHERE instrument_id=? AND interval=?
                       AND status='READY' ORDER BY generated_at DESC""", (instrument_id, interval)
                )
                for row in rows:
                    try:
                        payload = _decode(row["payload"], row["payload_checksum"])
                        if self._snapshot_complete(payload, instrument_id, interval, row):
                            return {**payload, "snapshot_id": row["snapshot_id"]}
                        logger.warning("[CACHE] incomplete snapshot skipped instrument=%s interval=%s", instrument_id, interval)
                    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError):
                        logger.exception("[CACHE] invalid snapshot skipped instrument=%s interval=%s", instrument_id, interval)
            return None
        finally:
            self._record("snapshot_reads")
            self._record("snapshot_read_seconds", time.perf_counter() - started)

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
            if (not fingerprint or not candles or len(series) != len(candles)
                    or payload["indicator_series"].get("count") != len(candles)
                    or payload.get("provenance", {}).get("candle_count") != len(candles)):
                return False
            if payload.get("adjustment_status") not in {"adjusted", "unadjusted", "unknown"}:
                return False
            if ratings.get("fingerprint") != fingerprint:
                return False
            if (payload["analysis"].get("fingerprint") != fingerprint
                    or payload["indicator_series"].get("fingerprint") != fingerprint
                    or payload["provenance"].get("ohlcv_fingerprint") != fingerprint):
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
            return True
        except (KeyError, TypeError, AttributeError):
            return False

    def get_or_compute_snapshot(
        self, instrument_id: str, interval: str, *, refresh_latest: bool = False,
    ) -> dict[str, Any]:
        """Load valid local data, or compute/publish one live snapshot on a miss."""
        if interval not in HISTORY_DAYS:
            raise ValueError(f"Unsupported interval: {interval}")
        cached = self.get_snapshot(instrument_id, interval)
        if cached is not None and not self._snapshot_is_stale(cached) and not refresh_latest:
            return cached
        identity = (instrument_id, interval)
        with self._snapshot_load_lock(identity):
            cached = self.get_snapshot(instrument_id, interval)
            if cached is not None and not self._snapshot_is_stale(cached) and not refresh_latest:
                return cached
            logger.info("[CACHE] %s instrument=%s interval=%s",
                        "stale" if cached is not None else "miss", instrument_id, interval)
            try:
                self._compute_and_publish(
                    instrument_id, interval, bypass_cache=False,
                    refresh_latest=refresh_latest,
                )
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
        """Return a detached reference-only copy when a refresh fails."""
        result = copy.deepcopy(payload)
        result["is_stale"] = True
        warning = ("Fresh market data could not be obtained; this analytical snapshot is retained "
                   "for reference only and requires a successful refresh.")
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

    def manifest(
        self, *, limit: int | None = None, offset: int = 0
    ) -> dict[str, Any]:
        """Return a cheap index without decoding historical analytics BLOBs.

        Individual snapshot requests still verify payload checksums and completeness;
        this application-wide manifest needs only indexed metadata to decide what to hydrate.
        The queries are batched by watchlist identity instead of running two
        statements per instrument/timeframe, which keeps manifest latency flat as
        the watchlist grows.
        """
        started = time.perf_counter()
        watchlist = self.db.get_watchlist()
        identities: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for instrument in watchlist:
            instrument_id = instrument.get("instrument_id")
            if not instrument_id:
                continue
            configured = instrument.get("supported_intervals")
            if isinstance(configured, str):
                try:
                    configured = json.loads(configured)
                except ValueError:
                    configured = []
            for interval in configured or ("1d", "1wk", "1mo"):
                if interval not in HISTORY_DAYS:
                    continue
                identity = (str(instrument_id), str(interval))
                if identity not in seen:
                    seen.add(identity)
                    identities.append(identity)
        if not identities:
            self._record("manifest_calls")
            self._record("manifest_seconds", time.perf_counter() - started)
            return {"items": [], "as_of": _now(), "total": 0, "offset": offset, "limit": limit}

        instrument_ids = sorted({identity[0] for identity in identities})
        intervals = sorted({identity[1] for identity in identities})
        instrument_placeholders = ",".join("?" for _ in instrument_ids)
        interval_placeholders = ",".join("?" for _ in intervals)
        parameters = (*instrument_ids, *intervals)

        with self.db.connect() as conn:
            snapshot_rows = conn.execute(
                f"""SELECT * FROM (
                        SELECT snapshot_id,instrument_id,interval,ohlcv_fingerprint,
                               latest_candle_at,candle_count,generated_at,schema_version,
                               indicator_version,indicator_dependency_version,rating_version,
                               adjustment_status,
                               ROW_NUMBER() OVER (
                                   PARTITION BY instrument_id,interval
                                   ORDER BY generated_at DESC
                               ) AS row_number
                        FROM market_analytics_snapshots
                        WHERE status='READY'
                          AND instrument_id IN ({instrument_placeholders})
                          AND interval IN ({interval_placeholders})
                    ) WHERE row_number=1""",
                parameters,
            ).fetchall()
            job_rows = conn.execute(
                f"""SELECT * FROM (
                        SELECT instrument_id,interval,status,last_error,
                               ROW_NUMBER() OVER (
                                   PARTITION BY instrument_id,interval
                                   ORDER BY created_at DESC
                               ) AS row_number
                        FROM analytics_jobs
                        WHERE instrument_id IN ({instrument_placeholders})
                          AND interval IN ({interval_placeholders})
                    ) WHERE row_number=1""",
                parameters,
            ).fetchall()
            snapshots = {
                (str(row["instrument_id"]), str(row["interval"])): row
                for row in snapshot_rows
            }
            jobs = {
                (str(row["instrument_id"]), str(row["interval"])): row
                for row in job_rows
            }
        result = []
        for identity in identities:
            instrument_id, interval = identity
            snapshot = snapshots.get(identity)
            job = jobs.get(identity)
            if snapshot:
                metadata_matches = (
                    snapshot["schema_version"] == SCHEMA_VERSION
                    and snapshot["indicator_version"] == INDICATOR_VERSION
                    and snapshot["indicator_dependency_version"] == RATING_DEPENDENCY
                    and snapshot["rating_version"] == RATING_VERSION
                    and snapshot["adjustment_status"] in {"adjusted", "unadjusted", "unknown"}
                )
                if not metadata_matches:
                    snapshot = None
            job_status = str(job["status"]) if job else "MISSING"
            if not snapshot and job_status not in {"QUEUED", "RUNNING", "FAILED"}:
                job_status = "MISSING"
            result.append({
                "instrument_id": instrument_id,
                "interval": interval,
                "status": "READY" if snapshot else job_status,
                "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
                "fingerprint": snapshot["ohlcv_fingerprint"] if snapshot else None,
                "latest_candle_at": snapshot["latest_candle_at"] if snapshot else None,
                "candle_count": snapshot["candle_count"] if snapshot else 0,
                "generated_at": snapshot["generated_at"] if snapshot else None,
                "last_error": job["last_error"] if job else None,
            })
        total = len(result)
        start = max(0, offset)
        result = result[start:]
        if limit is not None:
            result = result[: max(0, limit)]
        self._record("manifest_calls")
        self._record("manifest_seconds", time.perf_counter() - started)
        return {
            "items": result,
            "as_of": _now(),
            "total": total,
            "offset": start,
            "limit": limit,
        }

    def status(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            counts = {row["status"]: row["count"] for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM analytics_jobs GROUP BY status"
            )}
        with self._metrics_lock:
            metrics = dict(self._metrics)
            metrics["average_queue_wait_seconds"] = (
                metrics["queue_wait_seconds"] / metrics["claimed"]
                if metrics["claimed"] else 0.0
            )
            metrics["average_compute_seconds"] = (
                metrics["compute_seconds"] / (metrics["completed"] + metrics["failed"])
                if (metrics["completed"] + metrics["failed"]) else 0.0
            )
            metrics["average_manifest_seconds"] = (
                metrics.get("manifest_seconds", 0.0) / metrics["manifest_calls"]
                if metrics.get("manifest_calls") else 0.0
            )
            metrics["average_snapshot_read_seconds"] = (
                metrics.get("snapshot_read_seconds", 0.0) / metrics["snapshot_reads"]
                if metrics.get("snapshot_reads") else 0.0
            )
            metrics["average_snapshot_write_seconds"] = (
                metrics.get("snapshot_write_seconds", 0.0) / metrics["snapshot_writes"]
                if metrics.get("snapshot_writes") else 0.0
            )
        market_metrics = None
        try:
            market_metrics = self.market_service.metrics()
        except Exception:
            market_metrics = None
        with self._active_lock:
            active = self._active
        return {
            "worker_id": self.worker_id,
            "worker_concurrency": self.worker_concurrency,
            "running_workers": active,
            "jobs": counts,
            "last_error": self._last_error,
            "provider_requests": self._provider_requests,
            "scheduler_running": any(thread.is_alive() for thread in self._threads),
            "metrics": metrics,
            "market": market_metrics,
        }

    def start(self, *, poll_seconds: float | None = None) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        poll = max(
            0.1,
            float(poll_seconds if poll_seconds is not None else self.poll_seconds),
        )
        self._threads = [
            threading.Thread(
                target=self._serve,
                args=(poll, worker_id),
                daemon=True,
                name=f"analytics-worker-{index}",
            )
            for index, worker_id in enumerate(self._worker_ids)
        ]
        self._thread = self._threads[0]
        for thread in self._threads:
            thread.start()

    def _serve(self, poll_seconds: float, worker_id: str) -> None:
        while not self._stop.is_set():
            if not self.run_one(worker_id):
                self._stop.wait(poll_seconds)

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout)
        self._threads.clear()
        self._thread = None
        placeholders = ",".join("?" for _ in self._worker_ids)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE analytics_jobs SET status='QUEUED',worker_id=NULL,lease_until=NULL,"
                f"updated_at=? WHERE status='RUNNING' AND worker_id IN ({placeholders})",
                (_now(), *self._worker_ids),
            )
