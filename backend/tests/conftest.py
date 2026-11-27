"""Isolate app import and API fixtures from the user's live portfolio database."""
import os
import tempfile
from pathlib import Path

_test_directory = tempfile.TemporaryDirectory(prefix="tradely-api-tests-", ignore_cleanup_errors=True)
os.environ["DATABASE_PATH"] = str(Path(_test_directory.name) / "tradely.sqlite3")
# Never let test lifespans write portable backups into the real repository or
# touch the user's local backup directory.
os.environ["BACKUP_ENABLED"] = "false"
os.environ["BACKUP_GIT_DIR"] = str(Path(_test_directory.name) / "git-backups")
os.environ["BACKUP_LOCAL_DIR"] = str(Path(_test_directory.name) / "local-backups")
os.environ["BACKUP_ON_STARTUP"] = "false"
os.environ["BACKUP_ON_SHUTDOWN"] = "false"
os.environ["MAINTENANCE_VACUUM_ON_STARTUP"] = "false"
