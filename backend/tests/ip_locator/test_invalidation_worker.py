from __future__ import annotations

from types import SimpleNamespace

from database import get_db_connection
from services import ip_locator_invalidation_service as worker
from services import ip_locator_task_service as tasks


class _Cache:
    backend = "redis"
    namespace = "nexora:test:locator:v1"
    settings = SimpleNamespace(REDIS_URL="redis://example.invalid:6379/0")

    def __init__(self, result=0):
        self.result = result
        self.deleted = []
        self.keys = []

    def build_key(self, kind, *parts):
        return f"{self.namespace}:{kind}:" + ":".join(str(part) for part in parts)

    def delete_prefix(self, prefix, *, batch_size):
        self.deleted.append((prefix, batch_size))
        if self.result is None:
            return None
        self.keys = [key for key in self.keys if not key.startswith(prefix)]
        return self.result


def _outbox_status(event_id: str):
    connection = get_db_connection()
    try:
        return connection.execute(
            "SELECT status, attempts, last_error FROM locator_invalidation_outbox WHERE id = ?",
            (event_id,),
        ).fetchone()
    finally:
        connection.close()


def test_invalidation_worker_deletes_only_the_target_result_prefix(isolated_db, monkeypatch):
    event = tasks.enqueue_locator_invalidation(
        event_key="test:arp:1",
        entity_type="locator_observation",
        entity_id="observation-1",
        event_type="fact_changed",
        tenant_id="tenant-default",
        scope_hash="scope-1",
        generation=2,
        payload={"observation_kind": "arp", "target_ip": "192.0.2.10"},
    )
    cache = _Cache(result=2)
    monkeypatch.setattr(worker, "get_locator_cache", lambda: cache)

    assert worker.process_pending_locator_invalidations(limit=1) == 1
    assert cache.deleted == [
        ("nexora:test:locator:v1:result:scope-1:192.0.2.10:", 100),
    ]
    assert _outbox_status(event["id"])[0] == "processed"


def test_invalidation_worker_retries_if_redis_is_unavailable(isolated_db, monkeypatch):
    event = tasks.enqueue_locator_invalidation(
        event_key="test:mac:1",
        entity_type="locator_observation",
        entity_id="observation-2",
        event_type="fact_changed",
        tenant_id="tenant-default",
        scope_hash="scope-2",
        generation=1,
        payload={"observation_kind": "mac", "target_mac": "001122334455"},
    )
    cache = _Cache(result=None)
    monkeypatch.setattr(worker, "get_locator_cache", lambda: cache)

    assert worker.process_pending_locator_invalidations(limit=1) == 1
    status, attempts, last_error = _outbox_status(event["id"])
    assert status == "pending"
    assert attempts == 1
    assert last_error == "ConnectionError"
    assert cache.deleted == [("nexora:test:locator:v1:result:scope-2:", 100)]


def test_fact_generation_key_survives_outbox_result_invalidation(isolated_db, monkeypatch):
    tasks.enqueue_locator_invalidation(
        event_key="test:route:post-write",
        entity_type="locator_observation",
        entity_id="observation-route-current",
        event_type="fact_changed",
        tenant_id="tenant-default",
        scope_hash="scope-current",
        generation=4,
        payload={"observation_kind": "route", "target_ip": "192.0.2.44"},
    )
    cache = _Cache(result=1)
    fact_key = cache.build_key("route", "scope-current", "device-a", "default", "192.0.2.44")
    result_key = cache.build_key("result", "scope-current", "192.0.2.44", "default", "auto")
    cache.keys = [fact_key, result_key]
    monkeypatch.setattr(worker, "get_locator_cache", lambda: cache)

    assert worker.process_pending_locator_invalidations(limit=1) == 1

    assert cache.keys == [fact_key]
    assert cache.deleted == [("nexora:test:locator:v1:result:scope-current:192.0.2.44:", 100)]


def test_non_redis_backend_acknowledges_cache_invalidation_without_redis(isolated_db, monkeypatch):
    event = tasks.enqueue_locator_invalidation(
        event_key="test:postgres:1",
        entity_type="locator_observation",
        entity_id="observation-3",
        event_type="fact_changed",
        tenant_id="tenant-default",
        scope_hash="scope-3",
        generation=1,
        payload={"observation_kind": "arp", "target_ip": "192.0.2.30"},
    )
    cache = _Cache()
    cache.backend = "postgres"
    cache.settings = SimpleNamespace(REDIS_URL="")
    monkeypatch.setattr(worker, "get_locator_cache", lambda: cache)

    assert worker.process_pending_locator_invalidations(limit=1) == 1
    assert cache.deleted == []
    assert _outbox_status(event["id"])[0] == "processed"
