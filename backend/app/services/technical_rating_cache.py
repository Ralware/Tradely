"""Bounded, thread-safe cache for completed TradingView Technical Rating snapshots.

The cache key is supplied by the caller and must include the canonical
instrument, timeframe, OHLCV fingerprint, source/dependency versions and any
history/provider parameters that affect the calculation.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any, Callable


class TechnicalRatingSnapshotCache:
    """A small in-process LRU/TTL cache with single-flight calculation.

    ``scope`` is normally the canonical instrument ID. Invalidating a scope
    also advances its generation, preventing an older in-flight calculation
    from repopulating the cache after a refresh.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        self.max_entries = max(1, max_entries)
        self._values: OrderedDict[tuple[Any, ...], tuple[float, str, dict[str, Any]]] = OrderedDict()
        self._inflight: dict[tuple[Any, ...], Future[dict[str, Any]]] = {}
        self._generation: dict[str, int] = {}
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    def get_or_compute(
        self,
        *,
        key: tuple[Any, ...],
        scope: str,
        ttl_seconds: int,
        compute: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        """Return (snapshot, cache_hit), deduplicating concurrent calculations."""
        with self._lock:
            now = time.monotonic()
            cached = self._values.get(key)
            if cached is not None:
                expires_at, cached_scope, payload = cached
                if expires_at > now:
                    self._values.move_to_end(key)
                    self._hits += 1
                    return copy.deepcopy(payload), True
                self._values.pop(key, None)

            future = self._inflight.get(key)
            is_owner = future is None
            if future is None:
                future = Future()
                self._inflight[key] = future
                generation = self._generation.get(scope, 0)
                self._misses += 1
            else:
                generation = self._generation.get(scope, 0)

        if not is_owner:
            return copy.deepcopy(future.result()), True

        try:
            payload = compute()
            stored = copy.deepcopy(payload)
            with self._lock:
                # Do not allow a pre-refresh calculation to repopulate cache.
                if self._generation.get(scope, 0) == generation:
                    # A newer fingerprint supersedes prior snapshots for the
                    # same instrument/timeframe; expiry remains a second guard.
                    for old_key, (_, old_scope, _) in list(self._values.items()):
                        if old_scope == scope and old_key[:2] == key[:2] and old_key != key:
                            self._values.pop(old_key, None)
                    self._values[key] = (
                        time.monotonic() + max(1, ttl_seconds), scope, stored,
                    )
                    self._values.move_to_end(key)
                    while len(self._values) > self.max_entries:
                        self._values.popitem(last=False)
            future.set_result(copy.deepcopy(payload))
            return payload, False
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)

    def invalidate(self, scope: str | None = None) -> None:
        """Invalidate one instrument or all snapshots."""
        with self._lock:
            if scope is None:
                scopes = {cached_scope for _, cached_scope, _ in self._values.values()}
                scopes.update(self._generation)
                for item in scopes:
                    self._generation[item] = self._generation.get(item, 0) + 1
                self._values.clear()
                self._inflight.clear()
                return
            self._generation[scope] = self._generation.get(scope, 0) + 1
            for key, (_, cached_scope, _) in list(self._values.items()):
                if cached_scope == scope:
                    self._values.pop(key, None)
            for key in list(self._inflight):
                if key and key[0] == scope:
                    self._inflight.pop(key, None)

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._values),
                "in_flight": len(self._inflight),
                "hits": self._hits,
                "misses": self._misses,
                "max_entries": self.max_entries,
            }


technical_rating_cache = TechnicalRatingSnapshotCache()
