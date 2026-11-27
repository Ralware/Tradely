"""Transactional restoration of portable Tradely backups."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.backup.portable import (
    BackupValidationError,
    load_and_validate,
    validate_envelope,
)
from app.backup.classification import TABLE_SPECS


def _table_columns(connection: Any, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _select_columns(connection: Any, table: str, row: dict[str, Any]) -> dict[str, Any]:
    columns = _table_columns(connection, table)
    return {key: value for key, value in row.items() if key in columns}


def _insert_row(
    connection: Any,
    table: str,
    row: dict[str, Any],
    *,
    id_column: str | None,
) -> bool:
    payload = _select_columns(connection, table, row)
    remapped = False
    if id_column and id_column in payload:
        exists = connection.execute(
            f'SELECT 1 FROM "{table}" WHERE "{id_column}"=?', (payload[id_column],)
        ).fetchone()
        if exists is not None:
            payload.pop(id_column, None)
            remapped = True
    if not payload:
        raise BackupValidationError(f"Nothing to insert into {table!r}")
    columns = ", ".join(f'"{column}"' for column in payload)
    placeholders = ", ".join("?" for _ in payload)
    connection.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
        tuple(payload.values()),
    )
    return remapped


def _update_row(
    connection: Any,
    table: str,
    row: dict[str, Any],
    *,
    key_columns: tuple[str, ...],
    id_column: str | None,
) -> None:
    payload = _select_columns(connection, table, row)
    if id_column:
        payload.pop(id_column, None)
    for key in key_columns:
        payload.pop(key, None)
    if not payload:
        return
    assignments = ", ".join(f'"{column}"=?' for column in payload)
    where = " AND ".join(f'"{column}"=?' for column in key_columns)
    values = tuple(payload.values()) + tuple(row[column] for column in key_columns)
    connection.execute(f'UPDATE "{table}" SET {assignments} WHERE {where}', values)


def _same_decimal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False


def _find_transaction(connection: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    key = str(row.get("idempotency_key") or "")
    if key:
        found = connection.execute(
            "SELECT * FROM holding_transactions WHERE idempotency_key=?", (key,)
        ).fetchone()
        if found is not None:
            return dict(found)
    candidates = connection.execute(
        """SELECT * FROM holding_transactions
           WHERE symbol=? AND market=? AND trade_time=? AND currency=?""",
        (
            row.get("symbol"),
            row.get("market"),
            row.get("trade_time"),
            row.get("currency"),
        ),
    ).fetchall()
    for candidate in candidates:
        existing = dict(candidate)
        if (
            str(existing.get("side") or "") == str(row.get("side") or "")
            and str(existing.get("intent") or "") == str(row.get("intent") or "")
            and _same_decimal(existing.get("quantity"), row.get("quantity"))
            and _same_decimal(existing.get("price"), row.get("price"))
            and _same_decimal(existing.get("fees"), row.get("fees"))
            and str(existing.get("notes") or "") == str(row.get("notes") or "")
        ):
            return existing
    return None


def _find_signal(connection: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    found = connection.execute(
        """SELECT * FROM signal_audit
           WHERE symbol=? AND market=? AND strategy=? AND strategy_version=?
             AND state=? AND COALESCE(as_of,'')=COALESCE(?,'') AND payload_json=?""",
        (
            row.get("symbol"),
            row.get("market"),
            row.get("strategy"),
            row.get("strategy_version"),
            row.get("state"),
            row.get("as_of"),
            row.get("payload_json"),
        ),
    ).fetchone()
    return dict(found) if found is not None else None


def _find_watchlist(connection: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    found = connection.execute(
        "SELECT * FROM watchlist WHERE symbol=? AND market=? AND exchange=?",
        (row.get("symbol"), row.get("market"), row.get("exchange")),
    ).fetchone()
    if found is not None:
        return dict(found)
    instrument_id = str(row.get("instrument_id") or "")
    if instrument_id:
        found = connection.execute(
            "SELECT * FROM watchlist WHERE instrument_id=?", (instrument_id,)
        ).fetchone()
        if found is not None:
            return dict(found)
    return None


def _empty_stats() -> dict[str, int]:
    return {"inserted": 0, "updated": 0, "skipped": 0, "remapped": 0, "conflicts": 0}


def _restore_instruments(
    connection: Any, rows: list[dict[str, Any]], *, overwrite: bool, stats: dict[str, int]
) -> None:
    for row in rows:
        instrument_id = row.get("instrument_id")
        existing = connection.execute(
            "SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)
        ).fetchone()
        if existing is None:
            _insert_row(connection, "instruments", row, id_column=None)
            stats["inserted"] += 1
        elif overwrite:
            _update_row(
                connection, "instruments", row,
                key_columns=("instrument_id",), id_column=None,
            )
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def _restore_aliases(
    connection: Any, rows: list[dict[str, Any]], *, stats: dict[str, int]
) -> None:
    for row in rows:
        existing = connection.execute(
            "SELECT 1 FROM instrument_aliases WHERE alias=? AND instrument_id=?",
            (row.get("alias"), row.get("instrument_id")),
        ).fetchone()
        if existing is not None:
            stats["skipped"] += 1
            continue
        _insert_row(connection, "instrument_aliases", row, id_column="id")
        stats["inserted"] += 1


def _restore_watchlist(
    connection: Any, rows: list[dict[str, Any]], *, overwrite: bool, stats: dict[str, int]
) -> None:
    for row in rows:
        existing = _find_watchlist(connection, row)
        if existing is None:
            remapped = _insert_row(connection, "watchlist", row, id_column="id")
            stats["inserted"] += 1
            stats["remapped"] += int(remapped)
            continue
        natural_match = (
            str(existing.get("symbol") or "") == str(row.get("symbol") or "")
            and str(existing.get("market") or "") == str(row.get("market") or "")
            and str(existing.get("exchange") or "") == str(row.get("exchange") or "")
        )
        if not natural_match:
            stats["conflicts"] += 1
            stats["skipped"] += 1
            continue
        if overwrite:
            _update_row(
                connection, "watchlist", row,
                key_columns=("symbol", "market", "exchange"), id_column="id",
            )
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def _restore_transactions(
    connection: Any, rows: list[dict[str, Any]], *, overwrite: bool, stats: dict[str, int]
) -> None:
    for row in rows:
        existing = _find_transaction(connection, row)
        if existing is None:
            remapped = _insert_row(connection, "holding_transactions", row, id_column="id")
            stats["inserted"] += 1
            stats["remapped"] += int(remapped)
            continue
        if overwrite:
            _update_row(
                connection, "holding_transactions", row,
                key_columns=("id",), id_column="id",
            )
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def _restore_signals(
    connection: Any, rows: list[dict[str, Any]], *, overwrite: bool, stats: dict[str, int]
) -> None:
    for row in rows:
        existing = _find_signal(connection, row)
        if existing is None:
            remapped = _insert_row(connection, "signal_audit", row, id_column="id")
            stats["inserted"] += 1
            stats["remapped"] += int(remapped)
            continue
        if overwrite:
            _update_row(connection, "signal_audit", row, key_columns=("id",), id_column="id")
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def _restore_key_value(
    connection: Any,
    table: str,
    rows: list[dict[str, Any]],
    *,
    overwrite: bool,
    stats: dict[str, int],
) -> None:
    for row in rows:
        existing = connection.execute(
            f'SELECT 1 FROM "{table}" WHERE "key"=?', (row.get("key"),)
        ).fetchone()
        if existing is None:
            _insert_row(connection, table, row, id_column=None)
            stats["inserted"] += 1
        elif overwrite:
            _update_row(connection, table, row, key_columns=("key",), id_column=None)
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def restore_backup(
    db: Any,
    envelope: dict[str, Any],
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    current_schema_version: int | None = None,
    allow_newer_schema: bool = False,
) -> dict[str, Any]:
    """Restore an already-validated envelope inside one SQLite transaction."""
    if current_schema_version is None:
        from app.core.database import SCHEMA_VERSION

        current_schema_version = SCHEMA_VERSION
    summary = validate_envelope(
        envelope,
        current_schema_version=current_schema_version,
        require_all=True,
        allow_newer_schema=allow_newer_schema,
    )
    data = envelope["data"]
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "overwrite": overwrite,
        "backup": summary,
        "tables": {},
        "conflicts": 0,
    }
    connection = db.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("PRAGMA defer_foreign_keys = ON")
        stats: dict[str, dict[str, int]] = {}
        for table, rows in data.items():
            stats[table] = _empty_stats()
            if not rows:
                continue
            if table == "instruments":
                _restore_instruments(connection, rows, overwrite=overwrite, stats=stats[table])
            elif table == "instrument_aliases":
                _restore_aliases(connection, rows, stats=stats[table])
            elif table == "watchlist":
                _restore_watchlist(connection, rows, overwrite=overwrite, stats=stats[table])
            elif table == "holding_transactions":
                _restore_transactions(connection, rows, overwrite=overwrite, stats=stats[table])
            elif table == "signal_audit":
                _restore_signals(connection, rows, overwrite=overwrite, stats=stats[table])
            elif table == "catalogue_meta":
                _restore_key_value(
                    connection, table, rows, overwrite=overwrite, stats=stats[table]
                )
            else:
                raise BackupValidationError(f"Unexpected essential table {table!r}")

        affected_instruments = {
            str(row.get("instrument_id"))
            for row in data.get("holding_transactions", [])
            if row.get("instrument_id")
        }
        for instrument_id in sorted(affected_instruments):
            db._validate_instrument_ledger(connection, instrument_id)

        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise BackupValidationError(
                "Restore would violate foreign keys: "
                + json.dumps([tuple(row) for row in foreign_key_errors])
            )

        report["tables"] = stats
        report["conflicts"] = sum(item["conflicts"] for item in stats.values())
        report["inserted"] = sum(item["inserted"] for item in stats.values())
        report["updated"] = sum(item["updated"] for item in stats.values())
        report["skipped"] = sum(item["skipped"] for item in stats.values())
        report["remapped"] = sum(item["remapped"] for item in stats.values())
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def restore_file(
    db: Any,
    path: Path | str,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    allow_newer_schema: bool = False,
    current_schema_version: int | None = None,
) -> dict[str, Any]:
    if current_schema_version is None:
        from app.core.database import SCHEMA_VERSION

        current_schema_version = SCHEMA_VERSION
    envelope, summary = load_and_validate(
        path,
        current_schema_version=current_schema_version,
        require_all=True,
        allow_newer_schema=allow_newer_schema,
    )
    result = restore_backup(
        db,
        envelope,
        overwrite=overwrite,
        dry_run=dry_run,
        current_schema_version=current_schema_version,
        allow_newer_schema=allow_newer_schema,
    )
    result["backup"] = summary
    result["path"] = str(path)
    return result
