"""Backup orchestration: limits, retention, atomic writes and restoration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.backup.classification import REGENERABLE_TABLES
from app.backup.portable import (
    BACKUP_SUFFIX,
    FORMAT_VERSION,
    BackupError,
    application_version,
    backup_filename,
    build_envelope,
    encode_envelope,
    excluded_record_counts,
    export_essential,
    load_and_validate,
    read_envelope,
    validate_envelope,
)
from app.backup.restore import restore_backup

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[3]


class BackupBusy(BackupError):
    """Another backup or restore operation is already running."""


class BackupLimitExceeded(BackupError):
    """A backup cannot be written without violating the configured limit."""


class BackupVerificationError(BackupError):
    """A written backup failed read-back validation."""


@dataclass(frozen=True)
class BackupLimits:
    max_total_bytes: int = 100 * 1024 * 1024
    warning_bytes: int = 75 * 1024 * 1024
    max_single_bytes: int = 90 * 1024 * 1024
    local_max_total_bytes: int = 400 * 1024 * 1024
    git_retention: int = 2
    local_retention: int = 10
    lock_timeout_seconds: float = 30.0
    lock_stale_seconds: float = 600.0
    temp_stale_seconds: float = 3600.0


@dataclass
class BackupResult:
    target: str
    path: Path | None = None
    skipped: bool = False
    reason: str = ""
    size_bytes: int = 0
    fingerprint: str | None = None
    record_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path) if self.path else None
        return payload


@dataclass
class _BackupItem:
    path: Path
    summary: dict[str, Any] | None
    created_at: datetime
    size_bytes: int


def _resolve_dir(value: str | Path | None, default: str) -> Path:
    raw = Path(value or default).expanduser()
    if not raw.is_absolute():
        raw = _REPO_ROOT / raw
    return raw.resolve()


def _parse_created_at(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mtime_datetime(value: float) -> datetime:
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return datetime.fromtimestamp(0, tz=UTC)


class BackupManager:
    """Owns portable backup creation, retention and restoration.

    The manager is deliberately independent of the FastAPI process so it can be
    used from the CLI and tests.  A cross-process lock file prevents overlapping
    operations, and every new snapshot is validated by reading it back before
    any older snapshot is pruned.
    """

    def __init__(
        self,
        db: Any,
        settings: Any | None = None,
        *,
        git_dir: str | Path | None = None,
        local_dir: str | Path | None = None,
        limits: BackupLimits | None = None,
        app_version: str | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.git_dir = _resolve_dir(
            git_dir or getattr(settings, "backup_git_dir", None), "backups/portable"
        )
        self.local_dir = _resolve_dir(
            local_dir or getattr(settings, "backup_local_dir", None), "data/local_backups"
        )
        self.limits = limits or self._limits_from_settings(settings)
        self.app_version = app_version or application_version()
        self._thread_lock = threading.RLock()
        self._lock_path = self.local_dir / ".backup.lock"

    @staticmethod
    def _limits_from_settings(settings: Any | None) -> BackupLimits:
        if settings is None:
            return BackupLimits()
        return BackupLimits(
            max_total_bytes=int(
                getattr(settings, "backup_max_total_bytes", BackupLimits.max_total_bytes)
            ),
            warning_bytes=int(
                getattr(settings, "backup_warning_bytes", BackupLimits.warning_bytes)
            ),
            max_single_bytes=int(
                getattr(settings, "backup_max_single_bytes", BackupLimits.max_single_bytes)
            ),
            local_max_total_bytes=int(
                getattr(
                    settings, "backup_local_max_total_bytes", BackupLimits.local_max_total_bytes
                )
            ),
            git_retention=int(
                getattr(settings, "backup_git_retention", BackupLimits.git_retention)
            ),
            local_retention=int(
                getattr(settings, "backup_local_retention", BackupLimits.local_retention)
            ),
            lock_timeout_seconds=float(
                getattr(settings, "backup_lock_timeout_seconds", BackupLimits.lock_timeout_seconds)
            ),
            lock_stale_seconds=float(
                getattr(settings, "backup_lock_stale_seconds", BackupLimits.lock_stale_seconds)
            ),
        )

    @property
    def current_schema_version(self) -> int:
        from app.core.database import SCHEMA_VERSION

        return int(SCHEMA_VERSION)

    @property
    def repo_root(self) -> Path:
        return _REPO_ROOT

    # ------------------------------------------------------------------
    # Locking and target helpers
    # ------------------------------------------------------------------
    def _lock_is_stale(self) -> bool:
        try:
            payload = json.loads(self._lock_path.read_text(encoding="utf-8"))
            created = _parse_created_at(payload.get("created_at"))
        except (OSError, ValueError, TypeError):
            try:
                created = datetime.fromtimestamp(self._lock_path.stat().st_mtime, tz=UTC)
            except OSError:
                return False
        return (datetime.now(UTC) - created).total_seconds() > self.limits.lock_stale_seconds

    @contextmanager
    def _lock(self) -> Iterator[None]:
        with self._thread_lock:
            self.local_dir.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + self.limits.lock_timeout_seconds
            while True:
                try:
                    descriptor = os.open(
                        self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                except FileExistsError:
                    if self._lock_is_stale():
                        self._lock_path.unlink(missing_ok=True)
                        continue
                    if time.monotonic() >= deadline:
                        raise BackupBusy(
                            f"Another backup operation holds {self._lock_path}"
                        )
                    time.sleep(0.05)
                else:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                        json.dump(
                            {
                                "pid": os.getpid(),
                                "created_at": datetime.now(UTC).isoformat(),
                            },
                            handle,
                        )
                        handle.flush()
                        os.fsync(handle.fileno())
                    break
            try:
                yield
            finally:
                self._lock_path.unlink(missing_ok=True)

    def _target_dir(self, target: str) -> Path:
        if target == "git":
            return self.git_dir
        if target == "local":
            return self.local_dir
        raise ValueError(f"Unknown backup target: {target!r}")

    @staticmethod
    def _normalize_targets(targets: str | Iterable[str]) -> tuple[str, ...]:
        if isinstance(targets, str):
            targets = (targets,)
        result: list[str] = []
        for target in targets:
            if target == "both":
                result.extend(("local", "git"))
            elif target in {"local", "git"}:
                result.append(target)
            else:
                raise ValueError(f"Unknown backup target: {target!r}")
        return tuple(dict.fromkeys(result))

    def _list_files(self, directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        return sorted(
            path
            for path in directory.glob(f"*{BACKUP_SUFFIX}")
            if path.is_file() and not path.name.startswith(".")
        )

    def _size_bytes(self, directory: Path) -> int:
        total = 0
        for path in self._list_files(directory):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def _scan(self, directory: Path) -> tuple[list[_BackupItem], list[_BackupItem]]:
        valid: list[_BackupItem] = []
        invalid: list[_BackupItem] = []
        for path in self._list_files(directory):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            try:
                envelope = read_envelope(path)
                summary = validate_envelope(
                    envelope,
                    current_schema_version=self.current_schema_version,
                    require_all=False,
                )
            except BackupError as exc:
                logger.warning("[BACKUP] invalid backup ignored path=%s error=%s", path, exc)
                invalid.append(_BackupItem(path, None, _mtime_datetime(path.stat().st_mtime), size))
                continue
            valid.append(
                _BackupItem(
                    path, summary, _parse_created_at(summary["created_at"]), size
                )
            )
        valid.sort(key=lambda item: item.created_at, reverse=True)
        invalid.sort(key=lambda item: item.created_at)
        return valid, invalid

    def _latest_valid(self, directory: Path) -> _BackupItem | None:
        valid, _ = self._scan(directory)
        return valid[0] if valid else None

    def _cleanup_temp_files(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        cutoff = time.time() - self.limits.temp_stale_seconds
        for path in directory.glob(".*.tmp"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    logger.info("[BACKUP] removed stale partial file %s", path)
            except OSError:
                continue

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def _export(self) -> tuple[dict[str, Any], dict[str, int]]:
        connection = self.db.connect()
        try:
            data = export_essential(
                connection, scope="user", require_all=True, include_optional=True
            )
            excluded = excluded_record_counts(connection)
        finally:
            connection.close()
        return data, excluded

    def _build_document(self) -> tuple[dict[str, Any], bytes, int]:
        data, excluded = self._export()
        envelope = build_envelope(
            data,
            schema_version=self.current_schema_version,
            excluded_counts=excluded,
            scope="user",
            source_database=Path(getattr(self.db, "file_path", "tradely.sqlite3")).name,
            app_version=self.app_version,
        )
        encoded = encode_envelope(envelope)
        return envelope, encoded, len(encoded)

    def _write_and_validate(
        self,
        directory: Path,
        encoded: bytes,
        filename: str,
        *,
        require_all: bool = True,
    ) -> tuple[Path, int]:
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = directory / f".{filename}.{uuid.uuid4().hex}.tmp"
        created_final: Path | None = None
        try:
            with open(temp_path, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            load_and_validate(
                temp_path,
                current_schema_version=self.current_schema_version,
                require_all=require_all,
            )
            final_path = directory / filename
            if final_path.exists():
                stem = final_path.name[: -len(BACKUP_SUFFIX)]
                final_path = directory / f"{stem}-{uuid.uuid4().hex[:8]}{BACKUP_SUFFIX}"
            os.replace(temp_path, final_path)
            created_final = final_path
            load_and_validate(
                final_path,
                current_schema_version=self.current_schema_version,
                require_all=require_all,
            )
            return final_path, len(encoded)
        except Exception:
            temp_path.unlink(missing_ok=True)
            if created_final is not None:
                created_final.unlink(missing_ok=True)
            raise

    def _quarantine_invalid(self, target: str, directory: Path, invalid: list[_BackupItem]) -> None:
        if target != "git" or not invalid:
            return
        quarantine = self.local_dir / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        for item in invalid:
            destination = quarantine / item.path.name
            if destination.exists():
                destination = quarantine / f"{item.path.stem}-{uuid.uuid4().hex[:8]}{item.path.suffix}"
            try:
                shutil.move(str(item.path), str(destination))
                logger.warning(
                    "[BACKUP] quarantined invalid Git backup %s -> %s",
                    item.path,
                    destination,
                )
            except OSError as exc:
                logger.error("[BACKUP] could not quarantine %s: %s", item.path, exc)

    def _prune_dir(
        self,
        target: str,
        directory: Path,
        *,
        retention: int,
        max_total_bytes: int,
        keep_path: Path | None,
    ) -> list[Path]:
        removed: list[Path] = []
        valid, invalid = self._scan(directory)
        self._quarantine_invalid(target, directory, invalid)
        if target == "git":
            valid, invalid = self._scan(directory)

        keep_count = max(1, retention)
        keep_paths = {item.path for item in valid[:keep_count]}
        protected = keep_path
        if protected is None and valid:
            # Manual pruning must never remove the newest valid snapshot.
            protected = valid[0].path
        if protected is not None:
            keep_paths.add(protected)
        for item in valid[keep_count:]:
            if item.path in keep_paths:
                continue
            try:
                item.path.unlink()
                removed.append(item.path)
            except OSError as exc:
                logger.warning("[BACKUP] could not remove old backup %s: %s", item.path, exc)

        total = self._size_bytes(directory)
        if total > max_total_bytes:
            valid, invalid = self._scan(directory)
            candidates = [
                item for item in valid if protected is None or item.path != protected
            ]
            candidates.sort(key=lambda item: item.created_at)
            candidates.extend(invalid)
            for item in candidates:
                if total <= max_total_bytes:
                    break
                try:
                    item.path.unlink()
                    total -= item.size_bytes
                    removed.append(item.path)
                    logger.info("[BACKUP] removed backup to satisfy size limit %s", item.path)
                except OSError as exc:
                    logger.warning("[BACKUP] could not remove %s: %s", item.path, exc)
            if total > max_total_bytes:
                raise BackupLimitExceeded(
                    f"Backup directory {directory} still exceeds {max_total_bytes} bytes"
                )
        return removed

    def create(
        self,
        *,
        force: bool = False,
        targets: str | Iterable[str] = ("local", "git"),
        reason: str = "manual",
    ) -> list[BackupResult]:
        with self._lock():
            return self._create_locked(force=force, targets=targets, reason=reason)

    def _create_locked(
        self,
        *,
        force: bool,
        targets: str | Iterable[str],
        reason: str,
    ) -> list[BackupResult]:
        normalized = self._normalize_targets(targets)
        for target in normalized:
            directory = self._target_dir(target)
            directory.mkdir(parents=True, exist_ok=True)
            self._cleanup_temp_files(directory)

        envelope, encoded, size = self._build_document()
        if size > self.limits.max_single_bytes:
            raise BackupLimitExceeded(
                f"Portable backup is {size} bytes; single-file limit is "
                f"{self.limits.max_single_bytes} bytes"
            )
        if size > self.limits.max_total_bytes:
            raise BackupLimitExceeded(
                f"Portable backup is {size} bytes; total Git limit is "
                f"{self.limits.max_total_bytes} bytes"
            )

        fingerprint = str(envelope["data_fingerprint"])
        results: list[BackupResult] = []
        for target in normalized:
            directory = self._target_dir(target)
            if not force:
                latest = self._latest_valid(directory)
                if latest is not None and latest.summary is not None:
                    if latest.summary.get("data_fingerprint") == fingerprint:
                        logger.info(
                            "[BACKUP] %s backup skipped (%s): essential data unchanged",
                            target,
                            reason,
                        )
                        results.append(
                            BackupResult(
                                target=target,
                                path=latest.path,
                                skipped=True,
                                reason="unchanged",
                                size_bytes=latest.size_bytes,
                                fingerprint=fingerprint,
                                record_counts=dict(envelope["record_counts"]),
                            )
                        )
                        continue
            filename = backup_filename(
                schema_version=self.current_schema_version,
                format_version=FORMAT_VERSION,
            )
            try:
                path, written = self._write_and_validate(
                    directory, encoded, filename, require_all=True
                )
            except Exception as exc:
                logger.exception("[BACKUP] %s backup failed (%s)", target, reason)
                results.append(
                    BackupResult(
                        target=target,
                        skipped=False,
                        reason=reason,
                        fingerprint=fingerprint,
                        record_counts=dict(envelope["record_counts"]),
                        error=str(exc),
                    )
                )
                continue

            warnings: list[str] = []
            if written >= self.limits.warning_bytes:
                warnings.append(
                    f"Backup file is {written} bytes, above the warning threshold "
                    f"of {self.limits.warning_bytes} bytes"
                )
            retention = (
                self.limits.git_retention if target == "git" else self.limits.local_retention
            )
            max_total = (
                self.limits.max_total_bytes
                if target == "git"
                else self.limits.local_max_total_bytes
            )
            try:
                self._prune_dir(
                    target,
                    directory,
                    retention=retention,
                    max_total_bytes=max_total,
                    keep_path=path,
                )
            except BackupLimitExceeded as exc:
                logger.error("[BACKUP] retention failed for %s: %s", target, exc)
                warnings.append(str(exc))
            total = self._size_bytes(directory)
            if total >= self.limits.warning_bytes:
                warnings.append(
                    f"{target} backup footprint is {total} bytes, above the warning "
                    f"threshold of {self.limits.warning_bytes} bytes"
                )
            logger.info(
                "[BACKUP] %s backup written path=%s bytes=%d records=%s reason=%s",
                target,
                path,
                written,
                envelope["record_counts"],
                reason,
            )
            results.append(
                BackupResult(
                    target=target,
                    path=path,
                    skipped=False,
                    reason=reason,
                    size_bytes=written,
                    fingerprint=fingerprint,
                    record_counts=dict(envelope["record_counts"]),
                    warnings=warnings,
                )
            )
        return results

    def maybe_backup(
        self,
        reason: str,
        *,
        targets: str | Iterable[str] = ("local", "git"),
        force: bool = False,
    ) -> list[BackupResult]:
        """Lifecycle-safe wrapper: never crashes the application."""
        if self.settings is not None and not bool(
            getattr(self.settings, "backup_enabled", True)
        ):
            logger.info("[BACKUP] disabled; skipping %s backup", reason)
            return []
        try:
            return self.create(force=force, targets=targets, reason=reason)
        except BackupBusy as exc:
            logger.info("[BACKUP] skipped %s backup: %s", reason, exc)
            return [
                BackupResult(
                    target=",".join(self._normalize_targets(targets)),
                    skipped=True,
                    reason="busy",
                    error=str(exc),
                )
            ]
        except BackupLimitExceeded as exc:
            logger.error("[BACKUP] refused %s backup: %s", reason, exc)
            return [
                BackupResult(
                    target=",".join(self._normalize_targets(targets)),
                    skipped=True,
                    reason="limit",
                    error=str(exc),
                )
            ]
        except Exception as exc:  # pragma: no cover - defensive lifecycle guard
            logger.exception("[BACKUP] %s backup failed", reason)
            return [
                BackupResult(
                    target=",".join(self._normalize_targets(targets)),
                    skipped=True,
                    reason="error",
                    error=str(exc),
                )
            ]

    # ------------------------------------------------------------------
    # Inspection, retention and restore
    # ------------------------------------------------------------------
    def verify(self, path: str | Path) -> dict[str, Any]:
        _, summary = load_and_validate(
            path,
            current_schema_version=self.current_schema_version,
            require_all=False,
        )
        summary["path"] = str(path)
        return summary

    def prune(self, *, targets: str | Iterable[str] = ("local", "git")) -> dict[str, list[str]]:
        with self._lock():
            removed: dict[str, list[str]] = {}
            for target in self._normalize_targets(targets):
                directory = self._target_dir(target)
                retention = (
                    self.limits.git_retention
                    if target == "git"
                    else self.limits.local_retention
                )
                max_total = (
                    self.limits.max_total_bytes
                    if target == "git"
                    else self.limits.local_max_total_bytes
                )
                removed[target] = [
                    str(path)
                    for path in self._prune_dir(
                        target,
                        directory,
                        retention=retention,
                        max_total_bytes=max_total,
                        keep_path=None,
                    )
                ]
            return removed

    def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "limits": asdict(self.limits),
            "targets": {},
            "database": self._database_files(),
        }
        for target in ("local", "git"):
            directory = self._target_dir(target)
            valid, invalid = self._scan(directory)
            total = self._size_bytes(directory)
            warnings: list[str] = []
            if total >= self.limits.warning_bytes:
                warnings.append(
                    f"{target} backup footprint is {total} bytes, above the warning "
                    f"threshold of {self.limits.warning_bytes} bytes"
                )
            latest = valid[0] if valid else None
            report["targets"][target] = {
                "directory": str(directory),
                "total_bytes": total,
                "file_count": len(valid),
                "invalid_count": len(invalid),
                "warnings": warnings,
                "latest": (
                    {
                        "path": str(latest.path),
                        "created_at": latest.summary.get("created_at")
                        if latest.summary
                        else None,
                        "size_bytes": latest.size_bytes,
                        "record_counts": latest.summary.get("record_counts")
                        if latest.summary
                        else {},
                        "data_fingerprint": latest.summary.get("data_fingerprint")
                        if latest.summary
                        else None,
                    }
                    if latest is not None
                    else None
                ),
            }
        return report

    def _database_files(self) -> dict[str, Any]:
        path = Path(getattr(self.db, "file_path", ""))
        files: dict[str, int] = {}
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{path}{suffix}")
            try:
                files[candidate.name] = candidate.stat().st_size
            except OSError:
                continue
        return {
            "path": str(path),
            "files": files,
            "total_bytes": sum(files.values()),
        }

    def restore(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
        dry_run: bool = False,
        create_safety: bool = True,
        allow_newer_schema: bool = False,
    ) -> dict[str, Any]:
        with self._lock():
            envelope, summary = load_and_validate(
                path,
                current_schema_version=self.current_schema_version,
                require_all=True,
                allow_newer_schema=allow_newer_schema,
            )
            safety: Path | None = None
            if create_safety and not dry_run:
                results = self._create_locked(
                    force=True, targets=("local",), reason="pre_restore_safety"
                )
                for result in results:
                    if result.error:
                        raise BackupError(
                            f"Safety snapshot failed; restore aborted: {result.error}"
                        )
                    if result.path is not None:
                        safety = result.path
            result = restore_backup(
                self.db,
                envelope,
                overwrite=overwrite,
                dry_run=dry_run,
                current_schema_version=self.current_schema_version,
                allow_newer_schema=allow_newer_schema,
            )
            result["backup"] = summary
            result["path"] = str(path)
            result["safety_backup"] = str(safety) if safety is not None else None
            logger.info(
                "[BACKUP] restore complete path=%s dry_run=%s inserted=%d updated=%d skipped=%d",
                path,
                dry_run,
                result.get("inserted", 0),
                result.get("updated", 0),
                result.get("skipped", 0),
            )
            return result


def storage_classification() -> dict[str, list[str]]:
    """Small helper for audit/status output."""
    return {
        "essential": [
            "instruments", "instrument_aliases", "watchlist",
            "holding_transactions", "catalogue_meta",
        ],
        "regenerable": list(REGENERABLE_TABLES),
        "temporary": ["*.sqlite3-wal", "*.sqlite3-shm", "*.sqlite3-journal", "*.tmp", "*.log"],
    }
