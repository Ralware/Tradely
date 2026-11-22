from __future__ import annotations

import gzip
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from app.core.database import Database
from app.services.indicators import compute_indicators
from app.services.strategy import STRATEGY_VERSION, evaluate_trend_breakout
from app.services.tv_technical_rating import (
    DEPENDENCY as RATING_DEPENDENCY,
    SOURCE_VERSION as RATING_VERSION,
    build_technical_summary,
    ohlcv_fingerprint,
)

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
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
    if frame.empty:
        return True
    age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(frame.index[-1])
    if interval == "1wk":
        threshold = pd.Timedelta(days=14)
    elif interval == "1mo":
        threshold = pd.Timedelta(days=62)
    else:
        threshold = pd.Timedelta(hours=48 if market == "crypto" else 120)
    return age > threshold


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

    def enqueue(self, instrument_id: str, interval: str, *, priority: int = 0,
                job_type: str = "FULL_REFRESH") -> str:
        now = _now()
        job_id = uuid.uuid4().hex
        with self.db.connect() as conn:
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
            registry_entry = self.db.instrument_for_id(str(identity)) or instrument
            configured = registry_entry.get("supported_intervals")
            if isinstance(configured, str):
                try:
                    configured = json.loads(configured)
                except ValueError:
                    configured = []
            intervals = configured or ("1d", "1wk", "1mo")
            for interval in intervals:
                if interval in HISTORY_DAYS:
                    self.enqueue(identity, interval, priority=10, job_type="INITIAL_COMPUTATION")
                    count += 1
        return count

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
            self._compute_and_publish(str(job["instrument_id"]), str(job["interval"]))
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

    def _compute_and_publish(self, instrument_id: str, interval: str) -> None:
        instrument = self.db.instrument_for_id(instrument_id)
        if not instrument:
            raise ValueError(f"Unknown instrument: {instrument_id}")
        days = HISTORY_DAYS[interval]
        frame, source = self.market_service.candles(
            instrument["symbol"], market=instrument["market"], exchange=instrument.get("exchange"),
            interval=interval, days=days, provider="auto", full_history=False, bypass_cache=True,
        )
        self._provider_requests += 1
        if frame.empty:
            raise ValueError("Provider returned no candles")
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
            raise ValueError("OHLCV contains missing values")
        if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
                (frame["low"] > frame[["open", "close", "high"]].min(axis=1)) |
                (frame["volume"] < 0)).any():
            raise ValueError("OHLCV validation failed")
        frame.attrs.update({"source": source, "is_adjusted": bool(frame.attrs.get("is_adjusted", False))})
        fingerprint = ohlcv_fingerprint(frame)
        adjusted = "adjusted" if frame.attrs["is_adjusted"] else "unadjusted"
        now = _now()
        indicators = compute_indicators(frame)
        technical = build_technical_summary(frame)
        latest = indicators.iloc[-1]
        values = {column: (None if pd.isna(value) else float(value))
                  for column, value in latest.items() if column not in {"open","high","low","close","volume"}}
        stale = _stale(frame, instrument["market"], interval)
        warnings: list[str] = []
        if stale:
            warnings.append("Latest candle is stale for this market; actionable signal output is suppressed.")
        if instrument["market"] == "india" and not frame.attrs["is_adjusted"]:
            warnings.append("Indian equity candles are unadjusted. Corporate actions can distort long-term indicators; do not treat strategy output as actionable.")
        strategies: dict[str, Any] = {}
        for direction in DIRECTIONS:
            for position in POSITIONS:
                result = evaluate_trend_breakout(
                    frame, symbol=instrument["symbol"], market=instrument["market"], source=source,
                    direction_mode=direction, position_side=position, indicators=indicators,
                ).model_dump(mode="json")
                if stale or (instrument["market"] == "india" and not frame.attrs["is_adjusted"]):
                    result.update({"state": "STALE_DATA" if stale else "DATA_QUALITY_ERROR",
                                   "entry_reference": None, "stop_reference": None,
                                   "risk_per_unit": None, "direction": None,
                                   "explanation": "Signal suppressed because the prepared market data is stale or its adjustment status is not verified."})
                strategies[f"{direction}:{position or 'NONE'}"] = result
        payload = {
            "schema_version": SCHEMA_VERSION,
            "symbol": instrument["symbol"], "market": instrument["market"],
            "exchange": instrument.get("exchange"), "instrument": instrument,
            "interval": interval, "source": source, "is_adjusted": frame.attrs["is_adjusted"],
            "fingerprint": fingerprint, "generated_at": now,
            "analysis": {"symbol": instrument["symbol"], "market": instrument["market"],
                "exchange": instrument.get("exchange"), "instrument": instrument, "interval": interval,
                "source": source, "is_adjusted": frame.attrs["is_adjusted"], "is_stale": stale,
                "as_of": frame.index[-1].isoformat(), "fingerprint": fingerprint,
                "latest": {key: float(latest[key]) for key in ("open","high","low","close","volume")},
                "indicators": values, "candles": _records(frame), "warnings": warnings},
            "indicator_series": {"interval": interval, "source": source, "fingerprint": fingerprint,
                "count": len(indicators), "series": _records(indicators)},
            "technical_ratings": {"source": source, "interval": interval,
                "is_adjusted": frame.attrs["is_adjusted"], "is_stale": stale, "as_of": frame.index[-1].isoformat(),
                "fingerprint": fingerprint, **technical},
            "strategy_variants": strategies,
            "provenance": {"instrument_id": instrument_id, "source": source, "interval": interval,
                "is_adjusted": frame.attrs["is_adjusted"], "ohlcv_fingerprint": fingerprint,
                "candle_count": len(frame), "latest_candle_timestamp": frame.index[-1].isoformat(),
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
            row = conn.execute(
                """SELECT * FROM market_analytics_snapshots WHERE instrument_id=? AND interval=?
                   AND status='READY' ORDER BY generated_at DESC LIMIT 1""", (instrument_id, interval)
            ).fetchone()
            if not row:
                return None
            strategy_rows = conn.execute(
                "SELECT * FROM strategy_snapshots WHERE market_snapshot_id=? AND status='READY'", (row["snapshot_id"],)
            ).fetchall()
        payload = _decode(row["payload"], row["payload_checksum"])
        variants = {}
        for variant in strategy_rows:
            variants[f"{variant['direction_mode']}:{variant['position_side']}"] = _decode(variant["payload"], variant["payload_checksum"])
        payload["strategy_variants"] = variants
        return payload

    def manifest(self) -> dict[str, Any]:
        result = []
        for instrument in self.db.get_watchlist():
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
                with self.db.connect() as conn:
                    snapshot = conn.execute(
                        "SELECT snapshot_id,ohlcv_fingerprint,latest_candle_at,candle_count,generated_at FROM market_analytics_snapshots WHERE instrument_id=? AND interval=? AND status='READY' ORDER BY generated_at DESC LIMIT 1",
                        (instrument_id, interval),
                    ).fetchone()
                    job = conn.execute(
                        "SELECT status,last_error FROM analytics_jobs WHERE instrument_id=? AND interval=? ORDER BY created_at DESC LIMIT 1",
                        (instrument_id, interval),
                    ).fetchone()
                result.append({"instrument_id":instrument_id,"interval":interval,
                    "status":"READY" if snapshot else (job["status"] if job else "MISSING"),
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
