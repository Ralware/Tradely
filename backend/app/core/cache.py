from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    """Small in-process cache. Not a substitute for provider quota enforcement."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < time.monotonic():
                self._values.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            self._values[key] = (time.monotonic() + max(1, ttl_seconds), value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
