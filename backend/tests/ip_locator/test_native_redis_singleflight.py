"""Native Redis lock/singleflight acceptance with synthetic device work.

Requires a dedicated loopback Redis instance and an explicit test URL.
Only random test-namespace keys are written/deleted. No device IO.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import pytest

from services.ip_locator_cache_service import IPLocatorCacheService
from services import ip_locator_trace_service as trace


@pytest.fixture
def native_cache():
    url = os.getenv("IP_LOCATOR_TEST_REDIS_URL", "")
    if not url:
        pytest.skip("set IP_LOCATOR_TEST_REDIS_URL for dedicated native Redis tests")
    parsed = urlsplit(url)
    assert parsed.scheme == "redis" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    cfg = SimpleNamespace(
        REDIS_URL=url, IP_LOCATOR_CACHE_BACKEND="redis",
        IP_LOCATOR_REDIS_NAMESPACE=f"nexora:pytest:{uuid.uuid4().hex}",
        IP_LOCATOR_RESULT_FRESH_SECONDS=30, IP_LOCATOR_RESULT_RETAIN_SECONDS=60,
        IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS=1, IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS=1,
    )
    cache = IPLocatorCacheService(cfg)
    assert cache.ping() is True
    try:
        yield cache
    finally:
        cache.delete_prefix(cache.namespace + ":")
        if cache._client is not None:
            cache._client.close()


def test_native_redis_only_one_lock_owner(native_cache):
    cache = native_cache
    key = cache.build_key("lock", "contention")
    barrier = threading.Barrier(16)

    def contender(i):
        barrier.wait(timeout=10)
        return cache.acquire_lock(key, ttl=30, token=f"owner-{i}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(contender, range(16)))
    winners = [token for token in results if token]
    assert len(winners) == 1
    assert cache.release_lock(key, "wrong-token") is False
    assert cache.get(key) == winners[0]
    assert cache.release_lock(key, winners[0]) is True
    assert cache.get(key) is None


def test_native_redis_expired_owner_cannot_delete_new_lock(native_cache):
    cache = native_cache
    key = cache.build_key("lock", "expiry")
    assert cache.acquire_lock(key, ttl=1, token="old") == "old"
    deadline = time.monotonic() + 5
    while cache.get(key) is not None and time.monotonic() < deadline:
        time.sleep(.05)
    assert cache.acquire_lock(key, ttl=30, token="new") == "new"
    assert cache.release_lock(key, "old") is False
    assert cache.get(key) == "new"
    assert cache.release_lock(key, "new") is True


def test_native_redis_100_same_ip_requests(native_cache, monkeypatch):
    cache = native_cache
    calls = []
    calls_lock = threading.Lock()
    ip = "192.0.2.10"
    key = cache.build_key("result", "test-scope", ip, "default", "auto")
    lock_key = cache.build_key("lock", "test-scope", ip, "default", "auto")
    monkeypatch.setattr(trace, "_cache_for_scope", lambda scope: (cache, "test-scope"))
    monkeypatch.setattr(trace, "_registered_ipam_vip_result", lambda *a, **kw: None)
    monkeypatch.setattr(trace, "_try_snmp_endpoint", lambda *a, **kw: None)
    # Exercise real orchestration/Redis; the device trace and PG authority
    # are synthetic in this test, separately covered by PG tests.
    monkeypatch.setattr(trace, "_manifest_is_current_for_code", lambda m: m == {"test": True})
    monkeypatch.setattr(trace, "_pending_fact_invalidation", lambda *a: False)
    monkeypatch.setattr(trace, "_set_cache_source", lambda *a, **kw: None)

    def synthetic_trace(target_ip, **kwargs):
        with calls_lock:
            calls.append(target_ip)
        time.sleep(.25)
        result = {"status": "completed", "found": True, "run_id": kwargs["durable_run_id"],
                  "target_ip": target_ip, "location": {"port": "GE1/0/2"},
                  "dependency_manifest": {"test": True},
                  "evidence_collected_at": datetime.now(timezone.utc).isoformat()}
        assert cache.set_json(key, result, ttl=30) is True
        return result

    monkeypatch.setattr(trace, "_trace_ip_uncached", synthetic_trace)

    def request(i):
        result = trace.trace_ip(ip, durable_run_id=f"run-{i}", deadline_seconds=15)
        assert result["found"] and result["run_id"] == f"run-{i}"
        assert result["location"]["port"] == "GE1/0/2"
        return result

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(request, range(100)))
    assert len(results) == 100
    assert calls == [ip]
    assert cache.get(lock_key) is None
