import sqlite3
from concurrent.futures import ThreadPoolExecutor

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
        self.calls = 0

    def candles(self, *args, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        return self.frame.copy(), "Mock provider"


def test_migration_creates_additive_analytics_tables(tmp_path):
    db = Database(tmp_path / "tradely.sqlite3")
    with db.connect() as connection:
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"market_bars", "market_analytics_snapshots", "strategy_snapshots", "analytics_jobs"} <= tables
    assert "idx_strategy_snapshots_parent" in indexes
    assert version >= 4
    assert db.get_watchlist() == []


def test_job_enqueue_is_idempotent_for_an_active_identity(tmp_path):
    engine = AnalyticsPrecompute(Database(tmp_path / "queue.sqlite3"), NoMarketCalls())
    first = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="INITIAL_COMPUTATION")
    second = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="INITIAL_COMPUTATION")
    assert first == second
    with engine.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analytics_jobs").fetchone()[0] == 1


def test_active_jobs_deduplicate_across_job_types(tmp_path):
    engine = AnalyticsPrecompute(Database(tmp_path / "cross-type.sqlite3"), NoMarketCalls())
    first = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="WATCHLIST_PREFETCH")
    second = engine.enqueue("global:NASDAQ:MSFT", "1d", job_type="FULL_REFRESH")
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


def _valid_frame(periods=260):
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=periods, freq="D")
    close = pd.Series(100 + np.arange(periods) * 0.2 + np.sin(np.arange(periods) / 5), index=index)
    frame = pd.DataFrame({"open": close - .1, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1000 + np.arange(periods)}, index=index)
    frame.attrs.update({"is_adjusted": True, "last_bar_confirmed": True})
    return frame


def test_manifest_uses_snapshot_metadata_without_full_payload_validation(tmp_path, monkeypatch):
    db = Database(tmp_path / "manifest.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))
    engine = AnalyticsPrecompute(db, FrameMarket(_valid_frame()))
    engine._compute_and_publish(instrument.instrument_id, "1d")

    def reject_full_validation(*_args, **_kwargs):
        pytest.fail("The manifest must not decode every historical snapshot")

    monkeypatch.setattr(engine, "get_snapshot", reject_full_validation)
    item = next(row for row in engine.manifest()["items"] if row["interval"] == "1d")

    assert item["status"] == "READY"
    assert item["snapshot_id"]
    assert item["fingerprint"]


def test_search_miss_is_computed_persisted_and_reused_without_a_second_fetch(tmp_path):
    db = Database(tmp_path / "on-demand.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)

    first = engine.get_or_compute_snapshot(instrument.instrument_id, "1d")
    second = engine.get_or_compute_snapshot(instrument.instrument_id, "1d")

    assert first["fingerprint"] == second["fingerprint"]
    assert len(first["strategy_variants"]) == 9
    assert market.calls == 1
    assert db.get_watchlist() == []
    assert engine.get_snapshot(instrument.instrument_id, "1d") is not None
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_analytics_snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM analytics_jobs").fetchone()[0] == 0


def test_concurrent_search_cache_misses_coalesce_to_one_calculation(tmp_path):
    db = Database(tmp_path / "concurrent-load.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: engine.get_or_compute_snapshot(instrument.instrument_id, "1d"),
            range(4),
        ))
    assert len({result["fingerprint"] for result in results}) == 1
    assert market.calls == 1


def test_live_cache_miss_racing_watchlist_worker_uses_one_calculation(tmp_path):
    db = Database(tmp_path / "worker-race.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)
    engine.enqueue(instrument.instrument_id, "1d", job_type="WATCHLIST_PREFETCH")

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(engine.run_one)
        request = pool.submit(engine.get_or_compute_snapshot, instrument.instrument_id, "1d")
        assert worker.result()
        snapshot = request.result()

    assert snapshot["fingerprint"]
    assert market.calls == 1


def test_watchlist_promotion_reuses_valid_data_and_restart_reconciles_only_missing_work(tmp_path):
    db = Database(tmp_path / "promotion.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)
    engine._compute_and_publish(instrument.instrument_id, "1d")
    db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))

    registration = engine.register_watchlist_instrument(instrument.instrument_id)
    duplicate = engine.register_watchlist_instrument(instrument.instrument_id)
    with db.connect() as connection:
        jobs = connection.execute(
            "SELECT interval,status FROM analytics_jobs WHERE instrument_id=?",
            (instrument.instrument_id,),
        ).fetchall()
    assert registration["reused"] == 1
    assert registration["queued"] > 0
    assert duplicate["reused"] == 1
    assert len(jobs) == len({row["interval"] for row in jobs})
    assert all(row["interval"] != "1d" for row in jobs)

    while engine.run_one():
        pass
    restarted = AnalyticsPrecompute(db, market)
    assert restarted.enqueue_watchlist() == 0
    assert market.calls == len(jobs) + 1


def test_removing_watchlist_cancels_queued_prefetch_but_retains_snapshot(tmp_path):
    db = Database(tmp_path / "remove.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    db.add_watchlist(WatchlistItem(instrument_id=instrument.instrument_id))
    engine = AnalyticsPrecompute(db, NoMarketCalls())
    engine.register_watchlist_instrument(instrument.instrument_id)
    engine.market_service = FrameMarket(_valid_frame())
    engine._compute_and_publish(instrument.instrument_id, "1d")
    assert db.remove_watchlist_instrument(instrument.instrument_id)
    cancelled = engine.cancel_watchlist_jobs(instrument.instrument_id)
    assert cancelled > 0
    assert engine.get_snapshot(instrument.instrument_id, "1d") is not None
    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM analytics_jobs WHERE status='QUEUED' AND instrument_id=?",
            (instrument.instrument_id,),
        ).fetchone()[0] == 0


def test_incomplete_snapshot_is_not_ready_and_failed_refresh_preserves_last_good(tmp_path):
    db = Database(tmp_path / "last-good.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)
    engine._compute_and_publish(instrument.instrument_id, "1d")
    good = engine.get_snapshot(instrument.instrument_id, "1d")
    assert good is not None

    with db.connect() as connection:
        connection.execute(
            "DELETE FROM strategy_snapshots WHERE strategy_snapshot_id=("
            "SELECT strategy_snapshot_id FROM strategy_snapshots WHERE instrument_id=? "
            "AND interval=? LIMIT 1)", (instrument.instrument_id, "1d"),
        )
    assert engine.get_snapshot(instrument.instrument_id, "1d") is None

    market.frame = _valid_frame()
    market.frame.loc[market.frame.index[-1], "close"] = np.nan
    with pytest.raises(ValueError, match="missing values"):
        engine._compute_and_publish(instrument.instrument_id, "1d")
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_analytics_snapshots WHERE status='READY'").fetchone()[0] == 1


def test_failed_stale_refresh_returns_reference_only_copy_without_mutating_persisted_signals(tmp_path, monkeypatch):
    db = Database(tmp_path / "stale-fallback.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    engine = AnalyticsPrecompute(db, FrameMarket(_valid_frame()))
    engine._compute_and_publish(instrument.instrument_id, "1d")
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT strategy_snapshot_id,payload,payload_checksum FROM strategy_snapshots WHERE instrument_id=?",
            (instrument.instrument_id,),
        ).fetchall()
        for row in rows:
            blob, checksum = _encode({
                "state": "BUY", "direction": "LONG", "entry_reference": 100.0,
                "stop_reference": 95.0, "risk_per_unit": 5.0,
            })
            connection.execute(
                "UPDATE strategy_snapshots SET payload=?,payload_checksum=? WHERE strategy_snapshot_id=?",
                (blob, checksum, row["strategy_snapshot_id"]),
            )
        before = [tuple(row) for row in connection.execute(
            "SELECT payload,payload_checksum FROM strategy_snapshots WHERE instrument_id=? ORDER BY strategy_snapshot_id",
            (instrument.instrument_id,),
        ).fetchall()]
    monkeypatch.setattr(engine, "_snapshot_is_stale", lambda _payload: True)

    class FailingMarket:
        def candles(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    engine.market_service = FailingMarket()
    stale = engine.get_or_compute_snapshot(instrument.instrument_id, "1d")

    assert stale["analysis"]["is_stale"] is True
    assert stale["technical_ratings"]["is_stale"] is True
    assert stale["indicator_series"]["is_stale"] is True
    assert any("retained for reference only" in item for item in stale["analysis"]["warnings"])
    assert len(stale["strategy_variants"]) == 9
    for variant in stale["strategy_variants"].values():
        assert variant["state"] == "STALE_DATA"
        assert variant["direction"] is None
        assert variant["entry_reference"] is None
        assert variant["stop_reference"] is None
        assert variant["risk_per_unit"] is None
    with db.connect() as connection:
        after = [tuple(row) for row in connection.execute(
            "SELECT payload,payload_checksum FROM strategy_snapshots WHERE instrument_id=? ORDER BY strategy_snapshot_id",
            (instrument.instrument_id,),
        ).fetchall()]
    assert after == before
    persisted = engine.get_snapshot(instrument.instrument_id, "1d")
    assert all(item["state"] == "BUY" and item["entry_reference"] == 100.0
               for item in persisted["strategy_variants"].values())


def test_stale_reference_refresh_recovers_after_a_later_successful_fetch(tmp_path, monkeypatch):
    db = Database(tmp_path / "stale-recovery.sqlite3")
    instrument = db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    market = FrameMarket(_valid_frame())
    engine = AnalyticsPrecompute(db, market)
    engine._compute_and_publish(instrument.instrument_id, "1d")
    monkeypatch.setattr(engine, "_snapshot_is_stale", lambda _payload: True)

    class FailingMarket:
        def candles(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    engine.market_service = FailingMarket()
    fallback = engine.get_or_compute_snapshot(instrument.instrument_id, "1d")
    assert fallback["analysis"]["is_stale"] is True

    engine.market_service = market
    refreshed = engine.get_or_compute_snapshot(instrument.instrument_id, "1d")
    assert refreshed["analysis"]["is_stale"] is False
    assert refreshed["provenance"]["data_freshness"] == "fresh"
    assert all(item["state"] != "STALE_DATA" for item in refreshed["strategy_variants"].values())


def test_explicit_unknown_adjustment_status_is_not_promoted_by_legacy_boolean(tmp_path):
    db = Database(tmp_path / "unknown-adjustment.sqlite3")
    instrument = db.resolve_instrument("RELIANCE", "india", exchange="NSE")
    frame = _valid_frame()
    frame.attrs.update({"adjustment_status": "unknown", "is_adjusted": True})
    engine = AnalyticsPrecompute(db, FrameMarket(frame))

    engine._compute_and_publish(instrument.instrument_id, "1d")
    snapshot = engine.get_snapshot(instrument.instrument_id, "1d")

    assert snapshot["adjustment_status"] == "unknown"
    assert snapshot["is_adjusted"] is None
    assert all(item["state"] == "DATA_QUALITY_ERROR" for item in snapshot["strategy_variants"].values())
    assert all(item["direction"] is None and item["entry_reference"] is None
               and item["stop_reference"] is None and item["risk_per_unit"] is None
               for item in snapshot["strategy_variants"].values())
