from __future__ import annotations

from types import SimpleNamespace

from services.ip_locator_cache_service import IPLocatorCacheService


def _settings(**overrides):
    values = {
        "REDIS_URL": "redis://nexora:secret@example.test:6380/4",
        "IP_LOCATOR_CACHE_BACKEND": "redis",
        "IP_LOCATOR_REDIS_NAMESPACE": "nexora:test:locator:v1",
        "IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS": 1,
        "IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS": 1,
        "IP_LOCATOR_REDIS_FAILURE_COOLDOWN_SECONDS": 30,
        "IP_LOCATOR_ROUTE_FRESH_SECONDS": 300,
        "IP_LOCATOR_ROUTE_RETAIN_SECONDS": 1800,
        "IP_LOCATOR_ARP_FRESH_SECONDS": 300,
        "IP_LOCATOR_ARP_RETAIN_SECONDS": 1800,
        "IP_LOCATOR_MAC_FRESH_SECONDS": 120,
        "IP_LOCATOR_MAC_RETAIN_SECONDS": 900,
        "IP_LOCATOR_RESULT_FRESH_SECONDS": 120,
        "IP_LOCATOR_RESULT_RETAIN_SECONDS": 900,
        "IP_LOCATOR_SUBNET_FRESH_SECONDS": 900,
        "IP_LOCATOR_SUBNET_RETAIN_SECONDS": 86400,
        "IP_LOCATOR_TOPOLOGY_FRESH_SECONDS": 600,
        "IP_LOCATOR_TOPOLOGY_RETAIN_SECONDS": 86400,
        "IP_LOCATOR_NEGATIVE_CACHE_SECONDS": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.get_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.values.get(key)

    def set(self, key, value, ex, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        self.values.pop(key, None)
        return 1

    def ping(self):
        return True


def test_cache_key_includes_namespace_and_scope_hash_and_retention_is_remaining():
    fake = _FakeRedis()
    service = IPLocatorCacheService(_settings(), client=fake)
    scope = service.scope_hash(tenant_id="tenant-a", site_id="site-a", vrf="default")
    key = service.build_key("fact:arp", scope, "device-1", "default", "192.168.10.100")

    assert key.startswith("nexora:test:locator:v1:fact:arp:")
    ttl = service.ttl_for("arp", collected_at=1_000, now=1_100)
    assert service.set_json(
        key,
        {"ip": "192.168.10.100", "mac": "0011.2233.4455"},
        ttl=ttl,
    ) is True
    assert fake.ttls[key] == 1700


def test_redis_failure_isolated_and_health_summary_does_not_expose_url():
    class FailingRedis(_FakeRedis):
        def get(self, key):
            self.get_calls += 1
            raise ConnectionError("redis://nexora:secret@example.test")

    fake = FailingRedis()
    service = IPLocatorCacheService(_settings(), client=fake)
    key = service.build_key("fact", "scope", "target")

    assert service.get_json(key) is None
    # The short circuit avoids another network attempt during the cooldown.
    assert service.get_json(key) is None
    assert fake.get_calls == 1
    summary = service.health_summary(probe=True)
    assert summary["status"] == "cooldown"
    assert summary["host"] == "example.test"
    assert summary["port"] == 6380
    assert "secret" not in str(summary)


def test_postgres_backend_is_safe_noop():
    service = IPLocatorCacheService(_settings(IP_LOCATOR_CACHE_BACKEND="postgres"))
    assert service.get_json(service.build_key("fact", "one")) is None
    assert service.health_summary(probe=False)["status"] == "disabled"


def test_malformed_redis_url_is_reported_without_raising():
    service = IPLocatorCacheService(_settings(REDIS_URL="redis://user:secret@[broken"))
    summary = service.health_summary(probe=False)
    assert summary["available"] is False
    assert summary["host"] is None
    assert "secret" not in str(summary)


def test_health_summary_extracts_safe_endpoint_parts():
    service = IPLocatorCacheService(_settings())
    summary = service.health_summary(probe=False)
    assert summary["host"] == "example.test"
    assert summary["port"] == 6380
    assert summary["db"] == 4
    assert summary["tls"] is False
    assert "secret" not in str(summary)


def test_single_flight_lock_is_owner_checked():
    fake = _FakeRedis()
    service = IPLocatorCacheService(_settings(), client=fake)
    key = service.build_key("lock", "scope", "ip")
    first = service.acquire_lock(key, ttl=20, token="first")
    second = service.acquire_lock(key, ttl=20, token="second")

    assert first == "first"
    assert second is None
    assert service.release_lock(key, "second") is False
    assert service.release_lock(key, "first") is True
