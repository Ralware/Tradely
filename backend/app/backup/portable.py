"""Versioned, compressed, checksummed portable backup documents.

The document is a gzip-compressed JSON envelope.  Financial values are stored
as decimal strings so a round-trip through JSON cannot introduce binary
floating-point noise.  The checksum covers every metadata field and every row,
not just the data payload, so metadata tampering is detected as well.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterable

from app.backup.classification import (
    ESSENTIAL_TABLES,
    REGENERABLE_TABLES,
    REQUIRED_TABLE_NAMES,
    TABLE_SPECS,
)

FORMAT_NAME = "tradely-portable-backup"
FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = frozenset({1})
CHECKSUM_ALGORITHM = "sha256"
BACKUP_SUFFIX = ".json.gz"

_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "instruments": (
        "instrument_id", "symbol", "market", "exchange", "currency",
        "asset_type", "provider", "provider_symbol", "created_at", "updated_at",
    ),
    "instrument_aliases": ("alias", "instrument_id", "kind", "created_at"),
    "watchlist": ("symbol", "market", "exchange", "created_at"),
    "holding_transactions": (
        "symbol", "market", "side", "quantity", "price", "trade_time", "currency",
    ),
    "signal_audit": (
        "symbol", "market", "strategy", "strategy_version", "state",
        "payload_json", "created_at",
    ),
    "catalogue_meta": ("key", "value", "updated_at"),
}


class BackupError(RuntimeError):
    """Base class for backup failures."""


class BackupValidationError(BackupError):
    """The backup document is malformed, corrupted or incomplete."""


class BackupSchemaError(BackupValidationError):
    """The backup schema is newer than the running application."""


def application_version() -> str:
    """Best-effort application version without requiring installation."""
    try:
        return importlib_metadata.version("tradely")
    except importlib_metadata.PackageNotFoundError:
        return "0.1.0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _table_exists(connection: Any, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _table_columns(connection: Any, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _decimal_string(value: Any) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BackupValidationError(f"Invalid financial value: {value!r}") from exc
    if not decimal.is_finite():
        raise BackupValidationError(f"Non-finite financial value: {value!r}")
    # Fixed-point notation avoids scientific notation surprises in JSON.
    return format(decimal, "f")


def _encode_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        raise BackupValidationError("Non-finite float cannot be exported safely")
    return value


def _encode_row(row: Any, decimal_columns: Iterable[str]) -> dict[str, Any]:
    decimals = set(decimal_columns)
    encoded: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in decimals and value is not None:
            encoded[key] = _decimal_string(value)
        else:
            encoded[key] = _encode_value(value)
    return encoded


def excluded_record_counts(connection: Any) -> dict[str, int]:
    """Record counts for regenerable tables, used only as metadata."""
    counts: dict[str, int] = {}
    for table in REGENERABLE_TABLES:
        if not _table_exists(connection, table):
            continue
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        counts[table] = int(row[0] if row else 0)
    return counts


def export_essential(
    connection: Any,
    *,
    scope: str = "user",
    require_all: bool = True,
    include_optional: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Export only the classified essential tables.

    ``scope='pre_migration'`` relaxes required tables so a legacy database can
    be snapshotted before its schema is upgraded.
    """
    data: dict[str, list[dict[str, Any]]] = {}
    for spec in ESSENTIAL_TABLES:
        if not include_optional and not spec.required:
            continue
        if not _table_exists(connection, spec.name):
            if require_all and spec.required:
                raise BackupValidationError(
                    f"Essential table {spec.name!r} is missing from the database"
                )
            continue
        columns = _table_columns(connection, spec.name)
        order_by = spec.order_by if spec.order_by in columns else None
        query = f'SELECT * FROM "{spec.name}"'
        if order_by:
            query += f' ORDER BY "{order_by}"'
        rows = connection.execute(query).fetchall()
        data[spec.name] = [_encode_row(row, spec.decimal_columns) for row in rows]
    return data


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def data_fingerprint(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def _envelope_checksum(envelope: dict[str, Any]) -> str:
    payload = {key: value for key, value in envelope.items() if key != "checksum"}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_envelope(
    data: dict[str, Any],
    *,
    schema_version: int,
    excluded_counts: dict[str, int] | None = None,
    scope: str = "user",
    source_database: str = "tradely.sqlite3",
    created_at: str | None = None,
    app_version: str | None = None,
) -> dict[str, Any]:
    record_counts = {
        table: len(rows) for table, rows in sorted(data.items()) if isinstance(rows, list)
    }
    envelope: dict[str, Any] = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "created_at": created_at or _utc_now(),
        "application_version": app_version or application_version(),
        "schema_version": int(schema_version),
        "scope": scope,
        "source": {
            "database": source_database,
            "schema_version": int(schema_version),
        },
        "record_counts": record_counts,
        "excluded_record_counts": dict(sorted((excluded_counts or {}).items())),
        "data_fingerprint": data_fingerprint(data),
        "data": data,
    }
    envelope["checksum"] = {
        "algorithm": CHECKSUM_ALGORITHM,
        "value": _envelope_checksum(envelope),
    }
    return envelope


def encode_envelope(envelope: dict[str, Any]) -> bytes:
    raw = canonical_json_bytes(envelope)
    return gzip.compress(raw, compresslevel=9, mtime=0)


def decode_envelope(raw: bytes) -> dict[str, Any]:
    try:
        decompressed = gzip.decompress(raw)
    except (OSError, EOFError) as exc:
        raise BackupValidationError("Backup is not a valid gzip document") from exc
    try:
        parsed = json.loads(decompressed)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupValidationError("Backup JSON is invalid") from exc
    if not isinstance(parsed, dict):
        raise BackupValidationError("Backup root must be a JSON object")
    return parsed


def read_envelope(path: Path | str) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise BackupError(f"Cannot read backup {path}: {exc}") from exc
    return decode_envelope(raw)


def write_backup_bytes(path: Path | str, encoded: bytes) -> int:
    """Atomically write already-compressed bytes and return their size."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return len(encoded)


def write_backup_file(path: Path | str, envelope: dict[str, Any]) -> int:
    """Atomically write a compressed envelope and return its byte size."""
    return write_backup_bytes(path, encode_envelope(envelope))


def _parse_created_at(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise BackupValidationError("Backup created_at is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupValidationError("Backup created_at is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BackupValidationError("Backup created_at must include a timezone")


def validate_envelope(
    envelope: dict[str, Any],
    *,
    current_schema_version: int,
    require_all: bool = True,
    allow_newer_schema: bool = False,
) -> dict[str, Any]:
    """Validate format, checksum, schema compatibility and row structure."""
    if envelope.get("format") != FORMAT_NAME:
        raise BackupValidationError("Unrecognised backup format")
    version = envelope.get("format_version")
    if not isinstance(version, int) or version not in SUPPORTED_FORMAT_VERSIONS:
        raise BackupValidationError(f"Unsupported backup format version: {version!r}")
    _parse_created_at(envelope.get("created_at"))
    if not isinstance(envelope.get("application_version"), str):
        raise BackupValidationError("Backup application_version is missing")

    schema_version = envelope.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 0:
        raise BackupValidationError("Backup schema_version is invalid")
    if schema_version > current_schema_version and not allow_newer_schema:
        raise BackupSchemaError(
            f"Backup schema version {schema_version} is newer than the "
            f"application schema version {current_schema_version}"
        )

    checksum = envelope.get("checksum")
    if not isinstance(checksum, dict) or checksum.get("algorithm") != CHECKSUM_ALGORITHM:
        raise BackupValidationError("Backup checksum metadata is missing or unsupported")
    expected = checksum.get("value")
    if not isinstance(expected, str):
        raise BackupValidationError("Backup checksum value is missing")
    actual = _envelope_checksum(envelope)
    if not hmac.compare_digest(expected, actual):
        raise BackupValidationError("Backup checksum does not match its contents")

    data = envelope.get("data")
    if not isinstance(data, dict):
        raise BackupValidationError("Backup data payload is missing")
    record_counts = envelope.get("record_counts")
    if not isinstance(record_counts, dict):
        raise BackupValidationError("Backup record_counts is missing")

    if require_all:
        missing = [name for name in REQUIRED_TABLE_NAMES if name not in data]
        if missing:
            raise BackupValidationError(
                "Backup is missing essential tables: " + ", ".join(missing)
            )

    for table, rows in data.items():
        if not isinstance(rows, list):
            raise BackupValidationError(f"Backup table {table!r} is not a list")
        if int(record_counts.get(table, -1)) != len(rows):
            raise BackupValidationError(f"Record count mismatch for {table!r}")
        spec = TABLE_SPECS.get(table)
        required_columns = _REQUIRED_COLUMNS.get(table, ())
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise BackupValidationError(f"Row {index} in {table!r} is not an object")
            for column in required_columns:
                if column not in row:
                    raise BackupValidationError(
                        f"Row {index} in {table!r} is missing required column {column!r}"
                    )
            if spec is not None:
                for column in spec.decimal_columns:
                    value = row.get(column)
                    if value is None:
                        continue
                    if not isinstance(value, str):
                        raise BackupValidationError(
                            f"Financial value {table}.{column} must be a decimal string"
                        )
                    try:
                        parsed = Decimal(value)
                    except InvalidOperation as exc:
                        raise BackupValidationError(
                            f"Financial value {table}.{column} is not a decimal"
                        ) from exc
                    if not parsed.is_finite():
                        raise BackupValidationError(
                            f"Financial value {table}.{column} is not finite"
                        )

    fingerprint = envelope.get("data_fingerprint")
    if not isinstance(fingerprint, str) or not hmac.compare_digest(
        fingerprint, data_fingerprint(data)
    ):
        raise BackupValidationError("Backup data fingerprint does not match its rows")

    return {
        "format": FORMAT_NAME,
        "format_version": version,
        "created_at": envelope["created_at"],
        "application_version": envelope["application_version"],
        "schema_version": schema_version,
        "scope": envelope.get("scope", "user"),
        "record_counts": dict(record_counts),
        "excluded_record_counts": dict(envelope.get("excluded_record_counts") or {}),
        "data_fingerprint": fingerprint,
        "checksum": expected,
        "size_bytes": len(encode_envelope(envelope)),
    }


def load_and_validate(
    path: Path | str,
    *,
    current_schema_version: int,
    require_all: bool = True,
    allow_newer_schema: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = read_envelope(path)
    summary = validate_envelope(
        envelope,
        current_schema_version=current_schema_version,
        require_all=require_all,
        allow_newer_schema=allow_newer_schema,
    )
    return envelope, summary


def backup_filename(
    *,
    schema_version: int,
    created_at: datetime | None = None,
    format_version: int = FORMAT_VERSION,
) -> str:
    stamp = (created_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"tradely-backup-s{schema_version}-v{format_version}-{stamp}{BACKUP_SUFFIX}"
