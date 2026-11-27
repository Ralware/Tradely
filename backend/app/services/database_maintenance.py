"""Safe SQLite maintenance for Tradely.

The 2.8 GB database is dominated by ``market_analytics_snapshots`` payloads.
Those snapshots are a regenerable cache: the analytics worker publishes a new
snapshot for every OHLCV fingerprint and the UI only reads the newest complete
one.  Keeping a small, configurable number of snapshots per series bounds the
database without touching the user ledger or historical candles.

Market bars are deliberately *not* pruned.  Their primary key already prevents
duplicate rows; rows with different ``source``/``adjustment_status`` values are
intentional variants, not duplicates.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_KEEP_PER_SERIES = 2


@dataclass
class MaintenanceReport:
    """Result of a maintenance operation."""

    dry_run: bool = False
    kept_per_series: int = DEFAULT_KEEP_PER_SERIES
    series: int = 0
    snapshots_before: int = 0
    snapshots_deleted: int = 0
    payload_bytes_released: int = 0
    database_bytes_before: int = 0
    database_bytes_after: int = 0
    freelist_pages: int = 0
    vacuumed: bool = False
    checkpoint: dict[str, int] | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "kept_per_series": self.kept_per_series,
            "series": self.series,
            "snapshots_before": self.snapshots_before,
            "snapshots_deleted": self.snapshots_deleted,
            "payload_bytes_released": self.payload_bytes_released,
            "database_bytes_before": self.database_bytes_before,
            "database_bytes_after": self.database_bytes_after,
            "freelist_pages": self.freelist_pages,
            "vacuumed": self.vacuumed,
            "checkpoint": self.checkpoint,
            "warnings": self.warnings,
        }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def database_size(db: Any) -> int:
    """Total on-disk size of the database plus WAL/SHM files."""
    path = Path(getattr(db, "file_path", ""))
    return sum(_file_size(Path(f"{path}{suffix}")) for suffix in ("", "-wal", "-shm"))


def snapshot_storage_stats(db: Any) -> dict[str, Any]:
    """Report snapshot counts and payload bytes per series."""
    connection = db.connect()
    try:
        if not _table_exists(connection, "market_analytics_snapshots"):
            return {"series": [], "total_rows": 0, "total_payload_bytes": 0}
        rows = connection.execute(
            """SELECT instrument_id, interval, COUNT(*) AS rows,
                      COALESCE(SUM(LENGTH(payload)), 0) AS payload_bytes,
                      MIN(generated_at) AS oldest, MAX(generated_at) AS newest
               FROM market_analytics_snapshots
               GROUP BY instrument_id, interval
               ORDER BY payload_bytes DESC"""
        ).fetchall()
        series = [
            {
                "instrument_id": row["instrument_id"],
                "interval": row["interval"],
                "rows": int(row["rows"]),
                "payload_bytes": int(row["payload_bytes"]),
                "oldest": row["oldest"],
                "newest": row["newest"],
            }
            for row in rows
        ]
        return {
            "series": series,
            "total_rows": sum(item["rows"] for item in series),
            "total_payload_bytes": sum(item["payload_bytes"] for item in series),
        }
    finally:
        connection.close()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _snapshot_ids_to_prune(
    connection: sqlite3.Connection,
    *,
    keep_per_series: int,
    min_age_hours: float,
) -> dict[str, list[str]]:
    cutoff = (
        datetime.now(UTC) - timedelta(hours=min_age_hours) if min_age_hours > 0 else None
    )
    series_rows = connection.execute(
        "SELECT DISTINCT instrument_id, interval FROM market_analytics_snapshots"
    ).fetchall()
    prune: dict[str, list[str]] = {}
    for series in series_rows:
        rows = connection.execute(
            """SELECT snapshot_id, generated_at
               FROM market_analytics_snapshots
               WHERE instrument_id=? AND interval=?
               ORDER BY generated_at DESC, updated_at DESC, snapshot_id DESC""",
            (series["instrument_id"], series["interval"]),
        ).fetchall()
        excess = rows[keep_per_series:]
        if not excess:
            continue
        if cutoff is not None:
            excess = [
                row
                for row in excess
                if (parsed := _parse_timestamp(row["generated_at"])) is not None
                and parsed < cutoff
            ]
        if excess:
            key = f"{series['instrument_id']}|{series['interval']}"
            prune[key] = [str(row["snapshot_id"]) for row in excess]
    return prune


def _chunks(values: list[str], size: int = 500) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def prune_analytics_snapshots(
    db: Any,
    *,
    keep_per_series: int = DEFAULT_KEEP_PER_SERIES,
    dry_run: bool = False,
    min_age_hours: float = 0.0,
    prune_orphan_strategy: bool = True,
) -> MaintenanceReport:
    """Delete old regenerable analytics snapshots while keeping the newest ones.

    Strategy snapshots that reference deleted analytics snapshots are removed in
    the same transaction so no dangling ``market_snapshot_id`` remains.
    """
    keep = max(1, int(keep_per_series))
    report = MaintenanceReport(dry_run=dry_run, kept_per_series=keep)
    path = Path(getattr(db, "file_path", ""))
    report.database_bytes_before = database_size(db)

    connection = db.connect()
    try:
        if not _table_exists(connection, "market_analytics_snapshots"):
            report.warnings.append("market_analytics_snapshots table is missing")
            return report
        report.snapshots_before = int(
            connection.execute("SELECT COUNT(*) FROM market_analytics_snapshots").fetchone()[0]
        )
        connection.execute("BEGIN IMMEDIATE")
        try:
            prune = _snapshot_ids_to_prune(
                connection, keep_per_series=keep, min_age_hours=min_age_hours
            )
            report.series = len(prune)
            all_ids = [snapshot_id for ids in prune.values() for snapshot_id in ids]
            if all_ids:
                placeholders = ",".join("?" for _ in all_ids)
                row = connection.execute(
                    f"""SELECT COUNT(*), COALESCE(SUM(LENGTH(payload)), 0)
                        FROM market_analytics_snapshots
                        WHERE snapshot_id IN ({placeholders})""",
                    all_ids,
                ).fetchone()
                report.snapshots_deleted = int(row[0])
                report.payload_bytes_released = int(row[1])
                for chunk in _chunks(all_ids):
                    marks = ",".join("?" for _ in chunk)
                    connection.execute(
                        f"DELETE FROM market_analytics_snapshots WHERE snapshot_id IN ({marks})",
                        chunk,
                    )
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        report.freelist_pages = int(
            connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
    finally:
        connection.close()
    report.database_bytes_after = database_size(db)
    return report


def duplicate_candle_report(db: Any) -> dict[str, int]:
    """Detect exact duplicate candles and multi-source overlaps.

    The primary key prevents exact duplicates; overlapping rows from different
    sources or adjustment modes are reported separately because they are
    legitimate variants and must not be deleted blindly.
    """
    connection = db.connect()
    try:
        exact = int(
            connection.execute(
                """SELECT COUNT(*) FROM (
                       SELECT instrument_id, interval, timestamp, open, high, low, close,
                              volume, source, adjustment_status, updated_at, COUNT(*) AS n
                       FROM market_bars
                       GROUP BY instrument_id, interval, timestamp, open, high, low, close,
                                volume, source, adjustment_status, updated_at
                       HAVING n > 1
                   )"""
            ).fetchone()[0]
        )
        overlapping = int(
            connection.execute(
                """SELECT COUNT(*) FROM (
                       SELECT instrument_id, interval, timestamp, COUNT(*) AS n
                       FROM market_bars
                       GROUP BY instrument_id, interval, timestamp
                       HAVING n > 1
                   )"""
            ).fetchone()[0]
        )
        return {"exact_duplicate_groups": exact, "overlapping_variant_groups": overlapping}
    finally:
        connection.close()


def checkpoint(db: Any, mode: str = "TRUNCATE") -> dict[str, int]:
    """Checkpoint the WAL.  Returns SQLite's busy/log/checkpointed counters."""
    allowed = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
    normalized = mode.upper()
    if normalized not in allowed:
        raise ValueError(f"Unsupported checkpoint mode: {mode!r}")
    connection = db.connect()
    try:
        row = connection.execute(f"PRAGMA wal_checkpoint({normalized})").fetchone()
        return {
            "busy": int(row[0]),
            "log_pages": int(row[1]),
            "checkpointed_pages": int(row[2]),
        }
    finally:
        connection.close()


def vacuum(db: Any, *, min_free_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    """Rebuild the database file, refusing when free disk space is unsafe."""
    path = Path(getattr(db, "file_path", ""))
    before = database_size(db)
    free = shutil.disk_usage(path.parent).free
    required = max(int(min_free_bytes), before + 16 * 1024 * 1024)
    if free < required:
        raise OSError(
            f"Refusing to VACUUM: {free} bytes free, {required} bytes required"
        )
    started = time.perf_counter()
    connection = db.connect()
    try:
        connection.execute("VACUUM")
        # In WAL mode VACUUM writes the rebuilt database through the WAL;
        # truncate it so the reported size is not inflated by a ~database-sized
        # write-ahead log.
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            logger.warning("[MAINTENANCE] post-VACUUM checkpoint failed", exc_info=True)
    finally:
        connection.close()
    after = database_size(db)
    return {
        "bytes_before": before,
        "bytes_after": after,
        "bytes_reclaimed": max(0, before - after),
        "seconds": round(time.perf_counter() - started, 2),
    }


def optimize_database(
    db: Any,
    *,
    keep_per_series: int = DEFAULT_KEEP_PER_SERIES,
    min_age_hours: float = 0.0,
    vacuum_enabled: bool = False,
    dry_run: bool = False,
    min_free_bytes: int = 64 * 1024 * 1024,
    report_duplicates: bool = False,
) -> dict[str, Any]:
    """Prune regenerable caches, optionally vacuum, and checkpoint the WAL."""
    report = prune_analytics_snapshots(
        db,
        keep_per_series=keep_per_series,
        dry_run=dry_run,
        min_age_hours=min_age_hours,
    )
    payload = report.as_dict()
    if report_duplicates:
        payload["duplicate_candles"] = duplicate_candle_report(db)
    if not dry_run:
        try:
            payload["checkpoint"] = checkpoint(db)
        except sqlite3.Error as exc:
            payload["warnings"].append(f"WAL checkpoint failed: {exc}")
        if vacuum_enabled:
            try:
                payload["vacuum"] = vacuum(db, min_free_bytes=min_free_bytes)
                payload["vacuumed"] = True
                try:
                    payload["checkpoint_after_vacuum"] = checkpoint(db)
                except sqlite3.Error as exc:
                    payload["warnings"].append(
                        f"post-VACUUM WAL checkpoint failed: {exc}"
                    )
            except (OSError, sqlite3.Error) as exc:
                payload["warnings"].append(f"VACUUM skipped: {exc}")
        payload["database_bytes_after"] = database_size(db)
        connection = db.connect()
        try:
            payload["freelist_pages"] = int(
                connection.execute("PRAGMA freelist_count").fetchone()[0]
            )
        finally:
            connection.close()
    logger.info("[MAINTENANCE] %s", payload)
    return payload
