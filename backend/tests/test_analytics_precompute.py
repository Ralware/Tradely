import sqlite3

import pytest
import numpy as np
import pandas as pd

from app.core.database import Database
from app.core.models import WatchlistItem
from app.services.analytics_precompute import AnalyticsPrecompute, _decode, _encode


class NoMarketCalls:
    def candles(self, *args, **kwargs):
        raise AssertionError("Queue-only tests must not call a market provider")


class FrameMarket:
    def __init__(self, frame):
        self.frame = frame
        self.kwargs = None

    def candles(self, *args, **kwargs):
        self.kwargs = kwargs
        return self.frame.copy(), "Mock provider"


def test_migration_creates_additive_analytics_tables(tmp_path):
    db = Database(tmp_path / "tradely.sqlite3")
    with db.connect() as connection:
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"market_bars", "market_analytics_snapshots", "strategy_snapshots", "analytics_jobs"} <= tables
    assert version >= 4
    assert db.get_watchlist() == []


def test_job_enqueue_is_idempotent_for_an_active_identity(tmp_path):
    engine = AnalyticsPrecompute(Database(tmp_path / "queue.sqlite3"), NoMarketCalls())
    first = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="INITIAL_COMPUTATION")
    second = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="INITIAL_COMPUTATION")
    assert first == second
    with engine.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analytics_jobs").fetchone()[0] == 1


def test_expired_worker_lease_is_reclaimed(tmp_path):
    engine = AnalyticsPrecompute(Database(tmp_path / "lease.sqlite3"), NoMarketCalls())
    job_id = engine.enqueue("global:NASDAQ:MSFT", "1d")
    first = engine._claim()
    assert first and first["job_id"] == job_id
    with engine.db.connect() as connection:
        connection.execute("UPDATE analytics_jobs SET lease_until='2000-01-01T00:00:00+00:00' WHERE job_id=?", (job_id,))
    second = engine._claim()
    assert second and second["job_id"] == job_id
    with engine.db.connect() as connection:
        row = connection.execute("SELECT status,attempts FROM analytics_jobs WHERE job_id=?", (job_id,)).fetchone()
    assert row["status"] == "RUNNING"
    assert row["attempts"] == 2


def test_compressed_snapshot_round_trip_and_checksum_rejection():
    source = {"schema_version": 1, "candles": [{"close": 12.5}], "nested": {"ready": True}}
    payload, checksum = _encode(source)
    assert _decode(payload, checksum) == source
    with pytest.raises(ValueError, match="checksum"):
        _decode(payload, "invalid")


def test_worker_publishes_coherent_market_and_strategy_variants(tmp_path):
    db = Database(tmp_path / "pipeline.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))
    index = pd.date_range("2024-01-01", periods=260, freq="D", tz="UTC")
    close = pd.Series(100 + np.arange(260) * 0.2 + np.sin(np.arange(260) / 5), index=index)
    frame = pd.DataFrame({"open": close - .1, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1000 + np.arange(260)}, index=index)
    frame.attrs["is_adjusted"] = True
    frame.attrs["last_bar_confirmed"] = True
    market = FrameMarket(frame)
    engine = AnalyticsPrecompute(db, market)

    engine._compute_and_publish(instrument.instrument_id, "1d")
    snapshot = engine.get_snapshot(instrument.instrument_id, "1d")

    assert market.kwargs["full_history"] is False
    assert market.kwargs["days"] <= 3650
    assert snapshot["fingerprint"] == snapshot["analysis"]["fingerprint"]
    assert len(snapshot["analysis"]["candles"]) == 260
    assert len(snapshot["strategy_variants"]) == 9
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 260
        assert connection.execute("SELECT COUNT(*) FROM strategy_snapshots WHERE status='READY'").fetchone()[0] == 9
        assert connection.execute("SELECT COUNT(*) FROM market_analytics_snapshots WHERE status='READY'").fetchone()[0] == 1
