"""Portable, Git-tracked user-data backups for Tradely.

Only essential, non-regenerable user data is exported.  Market candles,
analytics snapshots, news and quote caches stay local and are rebuilt by the
application, which keeps the tracked backup footprint far below the 100 MB
repository budget.
"""

from app.backup.classification import (
    ESSENTIAL_TABLES,
    REGENERABLE_TABLES,
    TEMPORARY_PATTERNS,
    table_category,
)
from app.backup.manager import (
    BackupBusy,
    BackupLimitExceeded,
    BackupLimits,
    BackupManager,
    BackupResult,
    storage_classification,
)
from app.backup.portable import (
    BACKUP_SUFFIX,
    FORMAT_NAME,
    FORMAT_VERSION,
    BackupError,
    BackupSchemaError,
    BackupValidationError,
)
from app.backup.restore import restore_backup, restore_file

__all__ = [
    "BACKUP_SUFFIX",
    "ESSENTIAL_TABLES",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "REGENERABLE_TABLES",
    "TEMPORARY_PATTERNS",
    "BackupBusy",
    "BackupError",
    "BackupLimitExceeded",
    "BackupLimits",
    "BackupManager",
    "BackupResult",
    "BackupSchemaError",
    "BackupValidationError",
    "restore_backup",
    "restore_file",
    "storage_classification",
    "table_category",
]
