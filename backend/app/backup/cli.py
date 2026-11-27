"""Command-line interface for Tradely portable backups.

Run from the repository root::

    python -m app.backup.cli status
    python -m app.backup.cli create --targets both
    python -m app.backup.cli verify backups/portable/<file>.json.gz
    python -m app.backup.cli restore backups/portable/<file>.json.gz --dry-run
    python -m app.backup.cli maintain --vacuum

When the backend package is not on ``PYTHONPATH``, use::

    python backend/app/backup/cli.py ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# Allow ``python backend/app/backup/cli.py`` as well as ``python -m app.backup.cli``.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.backup.manager import BackupManager, storage_classification  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import Database  # noqa: E402
from app.services.database_maintenance import (  # noqa: E402
    duplicate_candle_report,
    optimize_database,
    snapshot_storage_stats,
)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _context() -> tuple[Database, BackupManager]:
    settings = get_settings()
    db = Database(settings.database_file)
    return db, BackupManager(db, settings)


def _resolve(manager: BackupManager, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = manager.repo_root / candidate
    return candidate.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.backup.cli",
        description="Portable Tradely backups and safe SQLite maintenance.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show backup targets, sizes and latest snapshot.")
    sub.add_parser("classify", help="Show the A/B/C data classification.")
    sub.add_parser("stats", help="Show database and snapshot storage statistics.")

    create = sub.add_parser("create", help="Create a portable backup.")
    create.add_argument(
        "--targets", choices=("local", "git", "both"), default="both"
    )
    create.add_argument("--force", action="store_true", help="Write even if unchanged.")
    create.add_argument("--reason", default="manual")

    verify = sub.add_parser("verify", help="Validate a backup file.")
    verify.add_argument("path")

    restore = sub.add_parser("restore", help="Restore a backup into the active database.")
    restore.add_argument("path")
    restore.add_argument("--overwrite", action="store_true")
    restore.add_argument("--dry-run", action="store_true")
    restore.add_argument(
        "--no-safety",
        action="store_true",
        help="Do not create a local safety snapshot before restoring.",
    )
    restore.add_argument("--allow-newer-schema", action="store_true")

    sub.add_parser("prune", help="Apply retention and size limits to backups.")

    maintain = sub.add_parser(
        "maintain", help="Prune regenerable analytics snapshots and checkpoint the WAL."
    )
    maintain.add_argument("--keep", type=int, default=None, help="Snapshots per series.")
    maintain.add_argument("--min-age-hours", type=float, default=0.0)
    maintain.add_argument("--vacuum", action="store_true")
    maintain.add_argument("--dry-run", action="store_true")
    maintain.add_argument("--duplicates", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db, manager = _context()

    if args.command == "status":
        _print(manager.status())
    elif args.command == "classify":
        _print(storage_classification())
    elif args.command == "stats":
        _print(
            {
                "database": manager.status()["database"],
                "analytics_snapshots": snapshot_storage_stats(db),
                "duplicate_candles": duplicate_candle_report(db),
            }
        )
    elif args.command == "create":
        results = manager.create(
            force=args.force, targets=args.targets, reason=args.reason
        )
        _print({"results": [result.as_dict() for result in results]})
    elif args.command == "verify":
        _print(manager.verify(_resolve(manager, args.path)))
    elif args.command == "restore":
        result = manager.restore(
            _resolve(manager, args.path),
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            create_safety=not args.no_safety,
            allow_newer_schema=args.allow_newer_schema,
        )
        _print(result)
    elif args.command == "prune":
        _print(manager.prune())
    elif args.command == "maintain":
        settings = get_settings()
        _print(
            optimize_database(
                db,
                keep_per_series=args.keep
                or settings.analytics_snapshot_retention_per_series,
                min_age_hours=args.min_age_hours,
                vacuum_enabled=args.vacuum,
                dry_run=args.dry_run,
                min_free_bytes=settings.maintenance_vacuum_min_free_bytes,
                report_duplicates=args.duplicates,
            )
        )
    else:  # pragma: no cover - argparse enforces the choices
        raise SystemExit(f"Unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
