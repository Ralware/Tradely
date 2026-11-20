"""Isolate app import and API fixtures from the user's live portfolio database."""
import os
import tempfile
from pathlib import Path

_test_directory = tempfile.TemporaryDirectory(prefix="tradely-api-tests-", ignore_cleanup_errors=True)
os.environ["DATABASE_PATH"] = str(Path(_test_directory.name) / "tradely.sqlite3")
