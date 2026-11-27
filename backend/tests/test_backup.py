"""Tests for portable backups, restoration, retention and SQLite maintenance."""

from __future__ import annotations

import gzip
import importlib.util
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.backup.classification import ESSENTIAL_TABLE_NAMES, REGENERABLE_TABLES
from app.backup.manager import (
    BackupBusy,
    BackupLimitExceeded,
    BackupLimits,
    BackupManager,
)
from app.backup.portable import (
    BackupSchemaError,
    BackupValidationError,
    build_envelope,
    decode_envelope,
    encode_envelope,
    export_essential,
    load_and_validate,
    validate_envelope,
)
from app.backup.restore import restore_file
from app.core.config import Settings
from app.core.database import SCHEMA_VERSION, Database
from app.services.database_maintenance import (
    duplicate_candle_report,
    prune_analytics_snapshots,
    snapshot_storage_stats,
)

NOW = "2026-11-27T10:00:00+00:00"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=str(tmp_path / "active.sqlite3"),
        backup_git_dir=str(tmp_path / "git-backups"),
        backup_local_dir=str(tmp_path / "local-backups"),
        backup_on_startup=False,
        backup_on_shutdown=False,
        backup_lock_timeout_seconds=0.2,
    )


def _seed(db: Database) -> None:
    connection = db.connect()
    try:
        connection.execute(
            """INSERT INTO instruments (
                   instrument_id, symbol, name, market, exchange, currency,
                   asset_type, provider, provider_symbol, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "global:NASDAQ:MSFT", "MSFT", "Microsoft", "global", "NASDAQ",
                "USD", "equity", "tradingview", "NASDAQ:MSFT", NOW, NOW,
            ),
        )
        connection.execute(
            "INSERT INTO instrument_aliases (alias, instrument_id, kind, created_at) VALUES (?,?,?,?)",
            ("MICROSOFT", "global:NASDAQ:MSFT", "alias", NOW),
        )
        connection.execute(
            """INSERT INTO watchlist (
                   symbol, market, exchange, display_name, created_at, instrument_id,
                   currency, asset_type, provider, provider_symbol, resolution_status
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "MSFT", "global", "NASDAQ", "Microsoft", NOW, "global:NASDAQ:MSFT",
                "USD", "equity", "tradingview", "NASDAQ:MSFT", "resolved",
            ),
        )
        connection.execute(
            """INSERT INTO holding_transactions (
                   symbol, market, side, quantity, price, trade_time, currency, fees,
                   notes, instrument_id, instrument_name, exchange, asset_type, provider,
                   provider_symbol, amount, actual_amount, quote_provider, quote_time,
                   quote_type, quote_status, quote_currency, idempotency_key,
                   resolution_status, intent
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "MSFT", "global", "BUY", 0.1, 12345678.9012345, NOW, "USD",
                0.000000123456789, "first lot", "global:NASDAQ:MSFT", "Microsoft",
                "NASDAQ", "equity", "tradingview", "NASDAQ:MSFT",
                1234567.89012345, 1234567.89012345, "tradingview", NOW, "delayed",
                "ok", "USD", "seed-msft-1", "resolved", "BUY",
            ),
        )
        connection.execute(
            """INSERT INTO signal_audit (
                   symbol, market, strategy, strategy_version, state, as_of,
                   payload_json, created_at
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                "MSFT", "global", "trend_breakout", "v1", "BUY", NOW,
                '{"state":"BUY"}', NOW,
            ),
        )
        connection.execute(
            "INSERT INTO catalogue_meta (key, value, updated_at) VALUES (?,?,?)",
            ("version", "2026-11-27", NOW),
        )
        connection.commit()
    finally:
        connection.close()


def _manager(tmp_path: Path, **limit_overrides) -> tuple[Database, BackupManager]:
    settings = _settings(tmp_path)
    db = Database(Path(settings.database_path))
    _seed(db)
    limits = BackupLimits(**limit_overrides) if limit_overrides else BackupLimits()
    return db, BackupManager(db, settings, limits=limits)


def _create(manager: BackupManager, **kwargs):
    results = manager.create(targets=("local",), force=kwargs.pop("force", False), **kwargs)
    assert results
    assert results[0].error is None, results[0].error
    return results[0]


# 1. Selective export -------------------------------------------------------
def test_export_contains_only_essential_tables(tmp_path):
    db, _ = _manager(tmp_path)
    with db.connect() as connection:
        data = export_essential(connection)
    assert set(data) == set(ESSENTIAL_TABLE_NAMES)
    assert not (set(data) & set(REGENERABLE_TABLES))
    assert len(data["watchlist"]) == 1
    assert len(data["holding_transactions"]) == 1
    assert len(data["instruments"]) == 1


# 2. Compression ------------------------------------------------------------
def test_backup_is_gzip_compressed_json(tmp_path):
    _, manager = _manager(tmp_path)
    result = _create(manager)
    raw = Path(result.path).read_bytes()
    assert raw[:2] == b"\x1f\x8b"
    envelope = decode_envelope(raw)
    assert envelope["format"] == "tradely-portable-backup"
    assert len(raw) < len(json.dumps(envelope).encode())


# 3. Checksum ---------------------------------------------------------------
def test_checksum_detects_tampering(tmp_path):
    db, _ = _manager(tmp_path)
    with db.connect() as connection:
        data = export_essential(connection)
    envelope = build_envelope(data, schema_version=SCHEMA_VERSION)
    envelope["data"]["watchlist"][0]["symbol"] = "EVIL"
    with pytest.raises(BackupValidationError, match="checksum"):
        validate_envelope(envelope, current_schema_version=SCHEMA_VERSION)


# 4. Restore ----------------------------------------------------------------
def test_restore_into_fresh_database(tmp_path):
    _, manager = _manager(tmp_path)
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    report = restore_file(target, result.path)
    assert report["inserted"] >= 5
    assert report["backup"]["format_version"] == 1
    assert len(target.get_watchlist()) == 1
    assert len(target.list_transactions()) == 1
    assert target.catalogue_version() == "2026-11-27"


# 5. Decimal precision ------------------------------------------------------
def test_financial_values_round_trip_without_float_noise(tmp_path):
    db, manager = _manager(tmp_path)
    with db.connect() as connection:
        data = export_essential(connection)
    row = data["holding_transactions"][0]
    assert isinstance(row["quantity"], str)
    assert row["quantity"] == "0.1"
    assert row["price"] == "12345678.9012345"
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    restore_file(target, result.path)
    restored = target.list_transactions()[0]
    assert restored["quantity"] == 0.1
    assert restored["price"] == 12345678.9012345
    assert restored["fees"] == 0.000000123456789


# 6. Foreign keys and validation -------------------------------------------
def test_restore_preserves_instrument_links_and_rejects_missing_tables(tmp_path):
    _, manager = _manager(tmp_path)
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    restore_file(target, result.path)
    transaction = target.list_transactions()[0]
    assert target.get_instrument(transaction["instrument_id"]) is not None
    assert target.get_watchlist()[0]["instrument_id"] == transaction["instrument_id"]

    envelope = decode_envelope(Path(result.path).read_bytes())
    filtered = {
        key: value for key, value in envelope["data"].items() if key != "watchlist"
    }
    incomplete = build_envelope(filtered, schema_version=SCHEMA_VERSION)
    with pytest.raises(BackupValidationError, match="missing essential tables"):
        validate_envelope(incomplete, current_schema_version=SCHEMA_VERSION)


# 7. Schema compatibility ---------------------------------------------------
def test_newer_schema_is_rejected_and_older_is_accepted(tmp_path):
    db, _ = _manager(tmp_path)
    with db.connect() as connection:
        data = export_essential(connection)
    newer = build_envelope(data, schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(BackupSchemaError):
        validate_envelope(newer, current_schema_version=SCHEMA_VERSION)
    older = build_envelope(data, schema_version=max(0, SCHEMA_VERSION - 1))
    summary = validate_envelope(older, current_schema_version=SCHEMA_VERSION)
    assert summary["schema_version"] == max(0, SCHEMA_VERSION - 1)


# 8. Interrupted backup -----------------------------------------------------
def test_interrupted_write_leaves_no_partial_or_final_file(tmp_path, monkeypatch):
    _, manager = _manager(tmp_path)
    import app.backup.manager as manager_module

    def explode(*args, **kwargs):
        raise BackupValidationError("simulated interruption")

    monkeypatch.setattr(manager_module, "load_and_validate", explode)
    envelope = manager._build_document()[0]
    directory = tmp_path / "git-backups"
    with pytest.raises(BackupValidationError):
        manager._write_and_validate(
            directory, encode_envelope(envelope), "tradely-backup.json.gz"
        )
    assert list(directory.glob("*.json.gz")) == []
    assert list(directory.glob("*.tmp")) == []


# 9. Concurrency ------------------------------------------------------------
def test_concurrent_backup_is_rejected_while_lock_is_held(tmp_path):
    _, manager = _manager(tmp_path)
    with manager._lock():
        with pytest.raises(BackupBusy):
            manager.create(targets=("local",))


# 10. Duplicate detection ---------------------------------------------------
def test_restoring_twice_does_not_duplicate_rows(tmp_path):
    _, manager = _manager(tmp_path)
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    restore_file(target, result.path)
    restore_file(target, result.path)
    assert len(target.get_watchlist()) == 1
    assert len(target.list_transactions()) == 1
    assert len(target.list_aliases()) == 1


# 11. Oversized rejection ---------------------------------------------------
def test_oversized_backup_is_rejected(tmp_path):
    _, manager = _manager(
        tmp_path, max_single_bytes=10, max_total_bytes=100, warning_bytes=5
    )
    with pytest.raises(BackupLimitExceeded):
        manager.create(targets=("local",), force=True)


# 12. Retention -------------------------------------------------------------
def test_retention_keeps_newest_and_never_deletes_the_only_valid_backup(tmp_path):
    _, manager = _manager(tmp_path, git_retention=2, local_retention=2)
    for _ in range(3):
        _create(manager, force=True)
        time.sleep(0.01)
    files = sorted((tmp_path / "local-backups").glob("*.json.gz"))
    assert len(files) == 2
    status = manager.status()["targets"]["local"]
    assert status["latest"] is not None

    _, single = _manager(tmp_path / "single", local_retention=1)
    _create(single, force=True)
    removed = single.prune(targets=("local",))
    assert removed["local"] == []
    assert len(list((tmp_path / "single" / "local-backups").glob("*.json.gz"))) == 1


# 13. Data preservation -----------------------------------------------------
def test_all_essential_fields_survive_round_trip(tmp_path):
    db, manager = _manager(tmp_path)
    with db.connect() as connection:
        before = export_essential(connection)
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    restore_file(target, result.path)
    with target.connect() as connection:
        after = export_essential(connection)
    assert after == before


# 14. Post-restore functionality -------------------------------------------
def test_application_reads_work_after_restore(tmp_path):
    _, manager = _manager(tmp_path)
    result = _create(manager)
    target = Database(tmp_path / "restored.sqlite3")
    restore_file(target, result.path)
    watchlist = target.get_watchlist()
    assert watchlist[0]["symbol"] == "MSFT"
    assert target.available_quantity("global:NASDAQ:MSFT", "USD", NOW) == 0.1
    assert target.list_instruments()[0]["symbol"] == "MSFT"
    assert target.search_instruments("MSFT")


# Maintenance ---------------------------------------------------------------
def _insert_snapshot(
    db: Database, snapshot_id: str, generated_at: str, payload: bytes = b"x" * 1024
) -> None:
    connection = db.connect()
    try:
        connection.execute(
            """INSERT INTO market_analytics_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_id, "global:NASDAQ:MSFT", "1d", snapshot_id, "ind-v1",
                "dep-v1", "rating-v1", "provider", "source", "adjusted", NOW, 10,
                generated_at, generated_at, 2, "READY", payload, "checksum",
            ),
        )
        connection.execute(
            """INSERT INTO strategy_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"strategy-{snapshot_id}", snapshot_id, "global:NASDAQ:MSFT", "1d",
                snapshot_id, "v1", "default-v1", "long_only", "LONG",
                generated_at, "READY", b"strategy", "checksum",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_snapshot_retention_keeps_newest_and_removes_orphans(tmp_path):
    db = Database(tmp_path / "maintenance.sqlite3")
    _insert_snapshot(db, "old", "2026-11-20T10:00:00+00:00")
    _insert_snapshot(db, "new", "2026-11-27T10:00:00+00:00")
    report = prune_analytics_snapshots(db, keep_per_series=1)
    assert report.snapshots_deleted == 1
    assert report.strategy_snapshots_deleted == 1
    with db.connect() as connection:
        remaining = [row[0] for row in connection.execute("SELECT snapshot_id FROM market_analytics_snapshots")]
        strategies = connection.execute("SELECT COUNT(*) FROM strategy_snapshots").fetchone()[0]
    assert remaining == ["new"]
    assert strategies == 1
    stats = snapshot_storage_stats(db)
    assert stats["total_rows"] == 1


def test_duplicate_candle_report_distinguishes_variants(tmp_path):
    db = Database(tmp_path / "candles.sqlite3")
    with db.connect() as connection:
        row = (
            "global:NASDAQ:MSFT", "1d", NOW, 1.0, 2.0, 0.5, 1.5, 100.0,
            "tradingview", "adjusted", NOW,
        )
        connection.execute("INSERT INTO market_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
        connection.execute(
            "INSERT INTO market_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (*row[:9], "unknown", NOW),
        )
        connection.commit()
    report = duplicate_candle_report(db)
    assert report["exact_duplicate_groups"] == 0
    assert report["overlapping_variant_groups"] == 1


# Git guard -----------------------------------------------------------------
def _load_guard():
    import sys

    path = Path(__file__).resolve().parents[2] / "scripts" / "check_backup_limits.py"
    spec = importlib.util.spec_from_file_location("check_backup_limits", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_git_guard_rejects_forbidden_paths_and_oversized_backups(tmp_path, monkeypatch):
    guard = _load_guard()
    assert guard.forbidden_reason(".env") is not None
    assert guard.forbidden_reason(".env.example") is None
    assert guard.forbidden_reason("data/tradely.sqlite3-wal") is not None
    assert guard.forbidden_reason("node_modules/pkg/index.js") is not None
    assert guard.forbidden_reason("backups/portable/ok.json.gz") is None

    monkeypatch.setattr(guard, "MAX_TOTAL_BACKUP_BYTES", 10)
    monkeypatch.setattr(guard, "WARN_TOTAL_BACKUP_BYTES", 5)
    backup = tmp_path / "backups" / "portable" / "big.json.gz"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"0" * 11)
    report = guard.check(tmp_path, ["backups/portable/big.json.gz"])
    assert not report.ok
    assert report.backup_total > guard.MAX_TOTAL_BACKUP_BYTES
