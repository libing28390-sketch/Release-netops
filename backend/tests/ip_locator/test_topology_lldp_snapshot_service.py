from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from database import get_db_connection
from core.config import settings
from services.ip_locator_cache_service import IPLocatorCacheService
from services.topology_lldp_snapshot_service import (
    LLDPAttemptSuperseded,
    begin_lldp_snapshot_attempt,
    complete_lldp_snapshot_in_transaction,
    fail_lldp_snapshot_attempt,
    get_lldp_snapshot_marker,
    load_complete_lldp_snapshot,
    lldp_snapshot_versions,
    publish_completed_lldp_snapshot,
    _snapshot_cache_key,
)


class _FakeCache:
    def __init__(self):
        self.values = {}

    @staticmethod
    def scope_hash(value):
        from services.ip_locator_cache_service import IPLocatorCacheService

        return IPLocatorCacheService.scope_hash(value)

    @staticmethod
    def build_key(*parts):
        return "nexora:test:" + ":".join(str(part) for part in parts)

    @staticmethod
    def policy(kind):
        assert kind == "topology"
        return SimpleNamespace(fresh_seconds=172800, retain_seconds=259200)

    def get_json(self, key):
        return copy.deepcopy(self.values.get(key))

    def set_json(self, key, value, **_kwargs):
        self.values[key] = copy.deepcopy(value)
        return True

    @staticmethod
    def is_fresh(kind, collected_at):
        if kind != "topology":
            return False
        observed = datetime.fromisoformat(str(collected_at).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - observed.astimezone(timezone.utc) <= timedelta(hours=48)


def _create_device(isolated_db, *, site_id: str = "site-lldp-test") -> dict:
    device_id = f"lldp-cache-{uuid.uuid4().hex}"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, platform, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (device_id, device_id, "h3c_comware", site_id, "tenant-lldp-test"),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "id": device_id,
        "hostname": device_id,
        "platform": "h3c_comware",
        "site_id": site_id,
        "tenant_id": "tenant-lldp-test",
    }


def test_snapshot_fingerprint_accepts_string_and_legacy_tuple_commands(monkeypatch):
    from services import topology_service

    device = {"platform": "h3c_comware"}
    command = "display lldp neighbor-information list"

    monkeypatch.setitem(topology_service.DISCOVERY_COMMANDS, "h3c_comware", [command])
    string_versions = lldp_snapshot_versions(device)

    monkeypatch.setitem(topology_service.DISCOVERY_COMMANDS, "h3c_comware", [("lldp", command)])
    tuple_versions = lldp_snapshot_versions(device)

    assert string_versions == tuple_versions
    assert len(string_versions["action_version"]) == 64
    assert len(string_versions["parser_version"]) == 64


def _complete(device: dict, generation: int, count: int) -> dict:
    conn = get_db_connection()
    try:
        marker = complete_lldp_snapshot_in_transaction(
            conn,
            device_id=device["id"],
            generation=generation,
            observation_count=count,
        )
        conn.commit()
        return marker
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _insert_observation(device: dict) -> None:
    collected_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO topology_observations (
                   id, source_device_id, source_hostname, source_port_raw,
                   source_port_normalized, neighbor_name_raw, neighbor_name_normalized,
                   neighbor_ip_address, target_port_raw, target_port_normalized,
                   protocol, confidence, status, raw_payload_json, collected_at,
                   updated_at, source_site_id, match_status, match_candidates_json,
                   last_seen_at, miss_count, is_active
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'lldp', 0.9, 'active',
                         '{}', ?, ?, ?, 'unmatched', '[]', ?, 0, 1)""",
            (
                str(uuid.uuid4()),
                device["id"],
                device["hostname"],
                "Ten-GigabitEthernet1/0/49",
                "xgigabitethernet1/0/49",
                "S6850-3",
                "s6850-3",
                "192.0.2.3",
                "Ten-GigabitEthernet1/0/49",
                "xgigabitethernet1/0/49",
                collected_at,
                collected_at,
                device["site_id"],
                collected_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_complete_positive_snapshot_is_published_and_read_from_redis(isolated_db):
    device = _create_device(isolated_db)
    versions = lldp_snapshot_versions(device)
    attempt = begin_lldp_snapshot_attempt(device, versions)
    _insert_observation(device)
    marker = _complete(device, attempt["generation"], 1)
    cache = _FakeCache()

    assert publish_completed_lldp_snapshot(
        device,
        generation=attempt["generation"],
        cache=cache,
    ) is True

    result = load_complete_lldp_snapshot(device, cache=cache, marker=marker)

    assert result is not None
    assert result["source"] == "redis"
    assert result["snapshot_complete"] is True
    assert result["neighbors"] == [{
        "local_interface": "Ten-GigabitEthernet1/0/49",
        "neighbor": "S6850-3",
        "neighbor_port": "Ten-GigabitEthernet1/0/49",
        "neighbor_ip": "192.0.2.3",
        "neighbor_id": "",
        "protocol": "lldp",
        "evidence": "topology_snapshot",
    }]

    cache.values.clear()
    fallback = load_complete_lldp_snapshot(device, cache=cache)
    assert fallback is not None
    assert fallback["source"] == "postgres"
    assert fallback["redis_write_attempted"] is True
    assert fallback["redis_written"] is True

    cached = load_complete_lldp_snapshot(device, cache=cache)
    assert cached is not None
    assert cached["source"] == "redis"
    assert cached["generation"] == attempt["generation"]


def test_postgres_cache_backend_does_not_claim_lldp_redis_write(isolated_db):
    device = _create_device(isolated_db)
    attempt = begin_lldp_snapshot_attempt(device)
    marker = _complete(device, attempt["generation"], 0)

    class _PostgresCache(_FakeCache):
        backend = "postgres"

        def set_json(self, *_args, **_kwargs):
            raise AssertionError("PostgreSQL cache backend must not attempt a Redis SET")

    result = load_complete_lldp_snapshot(device, cache=_PostgresCache(), marker=marker)

    assert result is not None
    assert result["source"] == "postgres"
    assert result["redis_write_attempted"] is False
    assert result["redis_written"] is False


def test_complete_empty_snapshot_is_cacheable_but_failed_attempt_invalidates_it(isolated_db):
    device = _create_device(isolated_db)
    first = begin_lldp_snapshot_attempt(device)
    _complete(device, first["generation"], 0)
    cache = _FakeCache()

    empty = load_complete_lldp_snapshot(device, cache=cache)
    assert empty is not None
    assert empty["neighbors"] == []
    assert empty["snapshot_complete"] is True

    second = begin_lldp_snapshot_attempt(device)
    assert second["generation"] > first["generation"]
    assert load_complete_lldp_snapshot(device, cache=cache) is None
    assert fail_lldp_snapshot_attempt(device["id"], second["generation"]) is True
    assert load_complete_lldp_snapshot(device, cache=cache) is None


def test_slow_collector_cannot_complete_over_a_newer_generation(isolated_db):
    device = _create_device(isolated_db)
    stale_attempt = begin_lldp_snapshot_attempt(device)
    current_attempt = begin_lldp_snapshot_attempt(device)
    assert current_attempt["generation"] > stale_attempt["generation"]

    with pytest.raises(LLDPAttemptSuperseded):
        _complete(device, stale_attempt["generation"], 0)

    current = get_lldp_snapshot_marker(device["id"])
    assert current is not None
    assert current["generation"] == current_attempt["generation"]
    assert current["state"] == "collecting"


@pytest.mark.skipif(
    os.environ.get("NETOPS_VERIFY_LIVE_REDIS") != "1",
    reason="requires explicit authorization for a short-lived key in the configured Redis",
)
def test_published_snapshot_round_trips_through_configured_redis(isolated_db):
    device = _create_device(isolated_db, site_id=f"site-live-test-{uuid.uuid4().hex}")
    cache = IPLocatorCacheService(settings_obj=settings)
    cache_key = ""
    try:
        assert cache.health_summary(probe=True)["available"] is True
        attempt = begin_lldp_snapshot_attempt(device)
        _insert_observation(device)
        _complete(device, attempt["generation"], 1)
        cache_key = _snapshot_cache_key(cache, device, attempt["generation"])

        assert publish_completed_lldp_snapshot(
            device,
            generation=attempt["generation"],
            cache=cache,
        ) is True
        stored = cache.get_json(cache_key)
        assert stored is not None
        assert stored["snapshot_complete"] is True
        assert stored["generation"] == attempt["generation"]
        assert len(stored["neighbors"]) == 1

        loaded = load_complete_lldp_snapshot(device, cache=cache)
        assert loaded is not None
        assert loaded["source"] == "redis"
        assert loaded["neighbors"] == stored["neighbors"]
    finally:
        if cache_key:
            deleted = cache.delete(cache_key)
            assert deleted is True
            assert cache.get_json(cache_key) is None
        cache.close()
