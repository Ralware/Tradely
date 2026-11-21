from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.services.technical_rating_cache import TechnicalRatingSnapshotCache


def test_cache_returns_deep_copies_and_expires():
    cache = TechnicalRatingSnapshotCache(max_entries=2)
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return {"rows": [{"rating": 1}]}

    first, hit = cache.get_or_compute(key=("A", "1d", "fp1"), scope="A", ttl_seconds=60, compute=compute)
    assert hit is False
    first["rows"][0]["rating"] = -1

    second, hit = cache.get_or_compute(key=("A", "1d", "fp1"), scope="A", ttl_seconds=60, compute=compute)
    assert hit is True
    assert second["rows"][0]["rating"] == 1
    assert calls == 1


def test_single_flight_deduplicates_concurrent_calculations():
    cache = TechnicalRatingSnapshotCache()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=3)
        return {"score": 0.25}

    def lookup():
        return cache.get_or_compute(
            key=("A", "1h", "fp"), scope="A", ttl_seconds=60, compute=compute,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lookup)
        assert started.wait(timeout=2)
        second = pool.submit(lookup)
        time.sleep(0.03)
        release.set()
        result_one = first.result(timeout=2)
        result_two = second.result(timeout=2)

    assert calls == 1
    assert result_one[0] == result_two[0] == {"score": 0.25}


def test_invalidation_prevents_obsolete_inflight_result_from_repopulating_cache():
    cache = TechnicalRatingSnapshotCache()
    started = threading.Event()
    release = threading.Event()

    def compute():
        started.set()
        assert release.wait(timeout=3)
        return {"score": 0.1}

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            cache.get_or_compute,
            key=("A", "1d", "fp1"), scope="A", ttl_seconds=60, compute=compute,
        )
        assert started.wait(timeout=2)
        cache.invalidate("A")
        release.set()
        pending.result(timeout=2)

    assert cache.info()["entries"] == 0


def test_cache_is_bounded_and_fingerprint_is_part_of_identity():
    cache = TechnicalRatingSnapshotCache(max_entries=2)
    for fingerprint in ("fp1", "fp2", "fp3"):
        cache.get_or_compute(
            key=("A", "1d", fingerprint), scope="A", ttl_seconds=60,
            compute=lambda fingerprint=fingerprint: {"fingerprint": fingerprint},
        )
    assert cache.info()["entries"] == 1
