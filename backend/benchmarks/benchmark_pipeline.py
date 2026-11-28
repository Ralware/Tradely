"""Reproducible, offline benchmarks for the Tradely data pipeline.

Run from the repository root:

    .venv\\Scripts\\python.exe -m backend.benchmarks.benchmark_pipeline

The benchmark uses synthetic OHLCV data and a temporary SQLite database. It
never contacts TradingView, so request counts and timings are deterministic and
safe to compare across revisions.
"""
from __future__ import annotations

import gzip
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.core.database import Database
from app.core.models import WatchlistItem
from app.services.analytics_precompute import (AnalyticsPrecompute, SCHEMA_VERSION, INDICATOR_VERSION,
                                                RATING_DEPENDENCY, RATING_VERSION)
from app.services.indicators import compute_indicators
from app.services.market import MarketService
from app.services.portfolio import build_ledger
from app.services.tv_technical_rating import build_technical_summary


def timed(operation: Callable[[], Any], repeats: int = 7) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000.0)
    return round(statistics.median(samples), 3)


def synthetic_frame(periods: int = 600) -> pd.DataFrame:
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=periods, freq="D")
    close = pd.Series(100 + np.arange(periods) * 0.2 + np.sin(np.arange(periods) / 5), index=index)
    frame = pd.DataFrame({
        "open": close - 0.1,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000 + np.arange(periods),
    }, index=index)
    frame.attrs.update({"is_adjusted": True, "last_bar_confirmed": True})
    return frame


class FrameMarket:
    def __init__(self, frame: pd.DataFrame, settings: Settings):
        self.frame = frame
        self.settings = settings
        self.calls = 0
        self.kwargs: dict[str, Any] = {}

    def candles(self, *args: Any, **kwargs: Any):
        self.calls += 1
        self.kwargs = kwargs
        return self.frame.copy(), "benchmark-provider"

    def price_metadata(self, *args: Any, **kwargs: Any):
        return {}


def seed_manifest(db: Database, count: int) -> list[tuple[str, str]]:
    identities: list[tuple[str, str]] = []
    for index in range(count):
        instrument = db.resolve_instrument(f"BENCH{index}", "global", exchange="NASDAQ")
        db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))
        with db.connect() as connection:
            connection.execute(
                "UPDATE instruments SET supported_intervals=? WHERE instrument_id=?",
                ('["1d","1wk","1mo"]', instrument.instrument_id),
            )
        for interval in ("1d", "1wk", "1mo"):
            identities.append((instrument.instrument_id, interval))
    now = "2026-01-01T00:00:00+00:00"
    with db.connect() as connection:
        for index, (instrument_id, interval) in enumerate(identities):
            snapshot_id = f"snapshot-{index}"
            connection.execute(
                """INSERT INTO market_analytics_snapshots
                   (snapshot_id,instrument_id,interval,ohlcv_fingerprint,
                    indicator_version,indicator_dependency_version,rating_version,
                    provider_identity,source_identity,adjustment_status,latest_candle_at,
                    candle_count,generated_at,updated_at,schema_version,status,payload,
                    payload_checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, instrument_id, interval, f"fp-{index}", INDICATOR_VERSION, RATING_DEPENDENCY, RATING_VERSION,
                 "p", "s", "adjusted", now, 100, now, now, SCHEMA_VERSION, "READY", b"", "checksum"),
            )
    return identities


def legacy_manifest(db: Database, identities: list[tuple[str, str]]) -> dict[str, Any]:
    """The previous per-identity query pattern, retained only for comparison."""
    result = []
    with db.connect() as connection:
        for instrument_id, interval in identities:
            snapshot = connection.execute(
                """SELECT snapshot_id,ohlcv_fingerprint,latest_candle_at,candle_count,
                          generated_at,schema_version,indicator_version,
                          indicator_dependency_version,rating_version,adjustment_status
                   FROM market_analytics_snapshots WHERE instrument_id=? AND interval=?
                     AND status='READY' ORDER BY generated_at DESC LIMIT 1""",
                (instrument_id, interval),
            ).fetchone()
            job = connection.execute(
                "SELECT status,last_error FROM analytics_jobs WHERE instrument_id=? "
                "AND interval=? ORDER BY created_at DESC LIMIT 1",
                (instrument_id, interval),
            ).fetchone()
            if snapshot:
                result.append({"instrument_id": instrument_id, "interval": interval,
                               "status": "READY"})
    return {"items": result}


def benchmark_manifest(db: Database, identities: list[tuple[str, str]]) -> dict[str, Any]:
    engine = AnalyticsPrecompute(db, FrameMarket(synthetic_frame(10), Settings(_env_file=None)))
    original_connect = db.connect

    def statements(operation: Callable[[], Any]) -> tuple[float, int]:
        counts = {"sql": 0}

        def connect():
            connection = original_connect()
            connection.set_trace_callback(
                lambda _sql: counts.__setitem__("sql", counts["sql"] + 1)
            )
            return connection

        db.connect = connect  # type: ignore[method-assign]
        try:
            elapsed = timed(operation, repeats=5)
        finally:
            db.connect = original_connect  # type: ignore[method-assign]
        return elapsed, counts["sql"] // 5

    legacy_ms, legacy_sql = statements(lambda: legacy_manifest(db, identities))
    batched_ms, batched_sql = statements(lambda: engine.manifest())
    return {
        "identities": len(identities),
        "legacy_ms": legacy_ms,
        "batched_ms": batched_ms,
        "legacy_sql_statements": legacy_sql,
        "batched_sql_statements": batched_sql,
    }


def benchmark_candles() -> dict[str, Any]:
    settings = Settings(_env_file=None)
    service = MarketService(settings)
    frame = synthetic_frame(600)
    calls = {"count": 0}

    def fetch(*args: Any, **kwargs: Any) -> pd.DataFrame:
        calls["count"] += 1
        return frame.copy()

    service.tradingview.fetch_candles = fetch  # type: ignore[method-assign]
    cold_ms = timed(lambda: service.candles(
        "BENCH", market="global", exchange="NASDAQ", interval="1d",
        days=365, full_history=False,
    ), repeats=1)
    warm_ms = timed(lambda: service.candles(
        "BENCH", market="global", exchange="NASDAQ", interval="1d",
        days=365, full_history=False,
    ))
    service._refresh_after_seconds = lambda _interval: 0  # type: ignore[method-assign]
    incremental_ms = timed(lambda: service.candles(
        "BENCH", market="global", exchange="NASDAQ", interval="1d",
        days=365, full_history=False,
    ))
    return {
        "cold_ms": round(cold_ms, 3),
        "warm_ms": warm_ms,
        "incremental_ms": incremental_ms,
        "provider_calls": calls["count"],
        "metrics": service.metrics(),
    }


def benchmark_compute_and_reads(db: Database, periods: int) -> dict[str, Any]:
    frame = synthetic_frame(periods)
    market = FrameMarket(frame, Settings(_env_file=None))
    engine = AnalyticsPrecompute(db, market)
    instrument = db.resolve_instrument(f"BENCH{periods}", "global", exchange="NASDAQ")
    publish_ms = timed(lambda: engine._compute_and_publish(instrument.instrument_id, "1d"), repeats=3)
    read = lambda: engine.get_snapshot(instrument.instrument_id, "1d")
    payload = read()
    assert payload is not None and len(payload["analysis"]["candles"]) == periods
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return {
        "candles": periods,
        "publish_snapshot_ms": publish_ms,
        "read_snapshot_ms": timed(read, repeats=3),
        "indicator_ms": timed(lambda: compute_indicators(frame), repeats=3),
        "rating_ms": timed(lambda: build_technical_summary(frame), repeats=3),
        "json_bytes": len(encoded),
        "gzip_bytes": len(gzip.compress(encoded, compresslevel=3)),
        "market_provider_calls": market.calls,
    }


def benchmark_portfolio(count: int) -> dict[str, Any]:
    transactions = [
        {"id": i, "symbol": "BENCH", "market": "global", "exchange": "NASDAQ",
         "currency": "USD", "intent": "BUY" if i % 2 == 0 else "SELL",
         "price": 100 + i % 17, "quantity": 0.25, "fees": 0.01,
         "trade_time": "2026-01-01T00:00:00+00:00"}
        for i in range(count)
    ]
    return {"transactions": count, "fifo_ms": timed(lambda: build_ledger(transactions))}


def benchmark_queue(db: Database, jobs: int = 40) -> dict[str, Any]:
    engine = AnalyticsPrecompute(db, FrameMarket(synthetic_frame(10), Settings(_env_file=None)))
    for index in range(jobs):
        engine.enqueue(f"global:NASDAQ:QUEUE{index}", "1d", job_type="WATCHLIST_PREFETCH")
    claim_ms = timed(lambda: [engine._claim(f"worker-{index % 2}") for index in range(jobs)], repeats=1)
    with db.connect() as connection:
        claimed = connection.execute(
            "SELECT COUNT(*) FROM analytics_jobs WHERE status='RUNNING'"
        ).fetchone()[0]
    return {"jobs": jobs, "claim_all_ms": claim_ms, "claimed": claimed}


def main() -> None:
    directory = tempfile.mkdtemp(prefix="tradely-bench-")
    try:
        path = Path(directory) / "bench.sqlite3"
        db = Database(path)
        identities = seed_manifest(db, 30)
        results = {
            "manifest": benchmark_manifest(db, identities),
            "candles": benchmark_candles(),
            "compute": [benchmark_compute_and_reads(db, n) for n in (600, 5000, 20000)],
            "portfolio": [benchmark_portfolio(n) for n in (100, 1000, 10000)],
            "queue": benchmark_queue(db),
        }
        print(json.dumps(results, indent=2, default=str))
    finally:
        # SQLite keeps the benchmark file open on Windows; cleanup is best-effort.
        import shutil

        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
