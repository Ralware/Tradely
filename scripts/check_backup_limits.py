#!/usr/bin/env python3
"""Reject oversized or unsafe files before they enter Git history.

Run manually with ``python scripts/check_backup_limits.py`` or automatically via
the pre-commit hook in ``.githooks/pre-commit``.

The check operates on the Git index, i.e. exactly what the next commit would
contain.  It enforces:

* combined tracked ``backups/portable/*.json.gz`` size <= 100 MB
* warning at 75 MB (preferred steady state 50-75 MB)
* no single backup above 90 MB
* no single tracked file above 100 MB
* no secrets, SQLite databases/WAL/SHM, node_modules, bundles or research data
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

MIB = 1024 * 1024
MAX_TOTAL_BACKUP_BYTES = 100 * MIB
WARN_TOTAL_BACKUP_BYTES = 75 * MIB
MAX_SINGLE_BACKUP_BYTES = 90 * MIB
MAX_ANY_FILE_BYTES = 100 * MIB
BACKUP_PREFIX = "backups/portable/"
BACKUP_SUFFIX = ".json.gz"


@dataclass
class Report:
    backup_files: list[tuple[str, int]] = field(default_factory=list)
    forbidden: list[tuple[str, str]] = field(default_factory=list)
    oversized: list[tuple[str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def backup_total(self) -> int:
        return sum(size for _, size in self.backup_files)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "backup_total_bytes": self.backup_total,
            "backup_total_mib": round(self.backup_total / MIB, 2),
            "backup_files": [
                {"path": path, "bytes": size} for path, size in self.backup_files
            ],
            "forbidden": [
                {"path": path, "reason": reason} for path, reason in self.forbidden
            ],
            "oversized": [
                {"path": path, "bytes": size} for path, size in self.oversized
            ],
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.decode("utf-8", "surrogateescape")


def tracked_files(root: Path) -> list[str]:
    output = _git(root, "ls-files", "-z")
    return [item for item in output.split("\0") if item]


def forbidden_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if normalized in {".env"} or (
        normalized.startswith(".env.") and normalized != ".env.example"
    ):
        return "environment file may contain secrets"
    if normalized.startswith(("node_modules/", ".work/", ".manus/")):
        return "generated dependency/work directory"
    if "/node_modules/" in normalized:
        return "generated dependency directory"
    if normalized.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal")):
        return "SQLite database or journal file"
    if normalized.endswith((".zip", ".bundle")):
        return "archive or bundle"
    if normalized.startswith("research/") and normalized.endswith((".csv", ".jsonl")):
        return "large research dataset"
    if name.startswith(".") and name.endswith(".tmp"):
        return "partial backup write"
    return None


def check(root: Path, files: Iterable[str] | None = None) -> Report:
    report = Report()
    paths = list(files) if files is not None else tracked_files(root)
    for path in paths:
        normalized = path.replace("\\", "/")
        full_path = root / normalized
        try:
            size = full_path.stat().st_size
        except OSError:
            size = 0
        if normalized.startswith(BACKUP_PREFIX) and normalized.endswith(BACKUP_SUFFIX):
            report.backup_files.append((normalized, size))
            if size > MAX_SINGLE_BACKUP_BYTES:
                report.oversized.append((normalized, size))
                report.errors.append(
                    f"{normalized} is {size} bytes; single backup limit is "
                    f"{MAX_SINGLE_BACKUP_BYTES} bytes"
                )
        if size > MAX_ANY_FILE_BYTES:
            report.oversized.append((normalized, size))
            report.errors.append(
                f"{normalized} is {size} bytes; no tracked file may exceed "
                f"{MAX_ANY_FILE_BYTES} bytes"
            )
        reason = forbidden_reason(normalized)
        if reason is not None:
            report.forbidden.append((normalized, reason))
            report.errors.append(f"{normalized}: {reason}")

    total = report.backup_total
    if total > MAX_TOTAL_BACKUP_BYTES:
        report.errors.append(
            f"tracked portable backups total {total} bytes; hard limit is "
            f"{MAX_TOTAL_BACKUP_BYTES} bytes"
        )
    elif total >= WARN_TOTAL_BACKUP_BYTES:
        report.warnings.append(
            f"tracked portable backups total {total} bytes, above the "
            f"{WARN_TOTAL_BACKUP_BYTES}-byte warning threshold"
        )
    return report


def print_report(report: Report) -> None:
    print(
        f"[backup-guard] portable backups: {len(report.backup_files)} file(s), "
        f"{report.backup_total} bytes ({report.backup_total / MIB:.2f} MiB) "
        f"of {MAX_TOTAL_BACKUP_BYTES // MIB} MiB"
    )
    for path, size in report.backup_files:
        print(f"  {size:>12,}  {path}")
    for warning in report.warnings:
        print(f"[backup-guard] WARNING: {warning}")
    for path, reason in report.forbidden:
        print(f"[backup-guard] FORBIDDEN: {path} ({reason})")
    for error in report.errors:
        if "forbidden" not in error.lower():
            print(f"[backup-guard] ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (defaults to the current directory).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Accepted for hook compatibility; the Git index is always checked.",
    )
    args = parser.parse_args(argv)
    report = check(Path(args.root).resolve())
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
