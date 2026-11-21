from __future__ import annotations

from typing import Any

import pytest

from services import cmdb_cache_service as cmdb_cache_module
from services.cmdb_cache_service import CmdbCacheLock, CmdbQueryCache


class FakeRedis:
    def __init__(self) -> None:
        self.now = 100.0
        self.values: dict[str, tuple[str | bytes, float]] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, int, bool]] = []
        self.eval_calls: list[tuple[str, int, tuple[Any, ...]]] = []

    def get(self, key: str) -> str | bytes | None:
        self.get_calls.append(key)
        value = self.values.get(key)
        if value is None:
            return None
        payload, expires_at = value
        if self.now >= expires_at:
            self.values.pop(key, None)
            return None
        return payload

    def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool | None:
        self.set_calls.append((key, value, ex, nx))
        current = self.values.get(key)
        if current is not None and self.now >= current[1]:
            self.values.pop(key, None)
            current = None
        if nx and current is not None:
            return None
        self.values[key] = (value, self.now + ex)
        return True

    def eval(self, script: str, numkeys: int, *args: Any) -> int:
        self.eval_calls.append((script, numkeys, args))
        if numkeys != 1 or len(args) != 2:
            raise AssertionError("expected one key and one token")
        key, token = args
        current = self.values.get(key)
        if current is None:
            return 0
        value, expires_at = current
        if self.now >= expires_at:
            self.values.pop(key, None)
            return 0
        if value != token:
            return 0
        self.values.pop(key, None)
        return 1

    def inject(self, key: str, value: str | bytes, *, ttl: int = 60) -> None:
        self.values[key] = (value, self.now + ttl)


def test_json_round_trip_uses_hashed_generation_scope_and_query_key() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client, ttl_seconds=30)
    generation = {"inventory_rev": 7, "dependency_rev": 3}
    scope = {"site_ids": ["site-42"], "roles": ["cmdb-reader"]}
    query = {"page": 2, "search": "private hostname"}
    value = {"items": [{"name": "Gi0/1", "up": True}], "total": 1}

    assert cache.set_json(
        "interfaces", generation=generation, scope=scope, query=query, value=value
    )

    stored_key, stored_json, stored_ttl, stored_nx = redis_client.set_calls[0]
    assert stored_key.startswith("nexora:test:cmdb:v1:")
    assert "site-42" not in stored_key
    assert "private hostname" not in stored_key
    assert stored_ttl == 30
    assert stored_nx is False
    assert cache.get_json(
        "interfaces", generation=generation, scope=scope, query=query
    ) == value

    # Key identity is canonical across mapping order but changes with any
    # caller-provided revision, authorization scope, or query value.
    equivalent_key = cache.build_key(
        "interfaces",
        generation={"dependency_rev": 3, "inventory_rev": 7},
        scope={"roles": ["cmdb-reader"], "site_ids": ["site-42"]},
        query={"search": "private hostname", "page": 2},
    )
    assert equivalent_key == stored_key
    assert cache.get_json(
        "interfaces", generation={"inventory_rev": 8}, scope=scope, query=query
    ) is None
    assert cache.build_key(
        "interfaces", generation=generation, scope={"site_ids": ["site-99"]}, query=query
    ) != stored_key
    assert cache.build_key(
        "interfaces", generation=generation, scope=scope, query={"page": 3}
    ) != stored_key


def test_expired_entry_is_a_cache_miss() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client, ttl_seconds=5)
    key_parts = {
        "resource": "vlans",
        "generation": 4,
        "scope": {"site_ids": [1]},
        "query": {"page": 1},
    }

    assert cache.set_json(**key_parts, value={"items": [10, 20]})
    redis_client.now += 5

    assert cache.get_json(**key_parts) is None


def test_missing_or_failing_redis_fails_open_and_tracks_safe_diagnostics() -> None:
    arguments = {
        "resource": "bindings",
        "generation": 1,
        "scope": {"all_sites": True},
        "query": {"page": 1},
    }
    disabled_cache = CmdbQueryCache("nexora:test:cmdb:v1", None)
    assert disabled_cache.get_json(**arguments) is None
    assert not disabled_cache.set_json(**arguments, value={"items": []})
    assert disabled_cache.failure_count == 0

    class UnavailableRedis:
        get_attempts = 0
        set_attempts = 0

        def get(self, key: str) -> None:
            self.get_attempts += 1
            raise ConnectionError("redis://user:secret@example.invalid")

        def set(self, key: str, value: str, *, ex: int) -> None:
            self.set_attempts += 1
            raise TimeoutError("redis://user:secret@example.invalid")

        def eval(self, script: str, numkeys: int, *args: Any) -> None:
            raise TimeoutError("redis://user:secret@example.invalid")

    unavailable_redis = UnavailableRedis()
    failing_cache = CmdbQueryCache("nexora:test:cmdb:v1", unavailable_redis, ttl_seconds=15)
    assert failing_cache.get_json(**arguments) is None
    assert not failing_cache.set_json(**arguments, value={"items": []})
    assert failing_cache.failure_count == 1
    assert failing_cache.is_cooling_down
    assert failing_cache.last_failure_kind == "ConnectionError"
    assert unavailable_redis.get_attempts == 1
    assert unavailable_redis.set_attempts == 0
    assert "secret" not in repr(failing_cache.last_failure_kind)

    set_failure_redis = UnavailableRedis()
    set_failing_cache = CmdbQueryCache(
        "nexora:test:cmdb:v1", set_failure_redis, ttl_seconds=15
    )
    assert not set_failing_cache.set_json(**arguments, value={"items": []})
    assert set_failing_cache.failure_count == 1
    assert set_failing_cache.is_cooling_down
    assert set_failing_cache.last_failure_kind == "TimeoutError"
    assert set_failing_cache.get_json(**arguments) is None
    assert set_failure_redis.set_attempts == 1
    assert set_failure_redis.get_attempts == 0


def test_invalid_json_is_a_miss_and_is_not_deleted() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "interfaces",
        "generation": 2,
        "scope": {"site_ids": ["site-1"]},
        "query": {"page": 1},
    }
    key = cache.build_key(**arguments)
    assert key is not None
    redis_client.inject(key, b'{"items":')

    assert cache.get_json(**arguments) is None
    assert key in redis_client.values
    assert redis_client.get_calls == [key]


def test_entry_size_and_json_safety_limits_skip_cache_writes() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache(
        "nexora:test:cmdb:v1", redis_client, max_entry_bytes=32
    )
    arguments = {
        "resource": "interfaces",
        "generation": 5,
        "scope": {"site_ids": [1]},
        "query": {"page": 1},
    }

    assert not cache.set_json(
        **arguments, value={"description": "x" * 100}
    )
    assert not cache.set_json(**arguments, value={"ratio": float("nan")})
    assert not cache.set_json(**arguments, value={1: "non-string JSON key"})
    assert not redis_client.set_calls

    key = cache.build_key(**arguments)
    assert key is not None
    redis_client.inject(key, b"x" * 33)
    assert cache.get_json(**arguments) is None


def test_ttl_and_entry_size_are_bounded_at_construction() -> None:
    redis_client = FakeRedis()

    for invalid_ttl in (0, 301):
        with pytest.raises(ValueError):
            CmdbQueryCache("nexora:test:cmdb:v1", redis_client, ttl_seconds=invalid_ttl)

    with pytest.raises(ValueError):
        CmdbQueryCache(
            "nexora:test:cmdb:v1", redis_client, max_entry_bytes=1024 * 1024 + 1
        )


def test_unsafe_key_material_is_a_miss_or_write_skip() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments: dict[str, Any] = {
        "resource": "interfaces",
        "generation": 1,
        "scope": {"site_ids": {"not-json-safe"}},
        "query": {"page": 1},
    }

    assert cache.get_json(**arguments) is None
    assert not cache.set_json(**arguments, value={"items": []})
    assert not redis_client.get_calls
    assert not redis_client.set_calls


def test_rebuild_lock_is_exclusive_and_released_by_its_owner() -> None:
    redis_client = FakeRedis()
    first_worker = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    second_worker = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "interfaces",
        "generation": {"inventory_rev": 9},
        "scope": {"site_ids": ["site-secret"]},
        "query": {"page": 2, "search": "private query"},
    }

    handle = first_worker.acquire_rebuild_lock(**arguments, lease_seconds=10)
    assert handle is not None
    assert len(handle.token) == 32
    assert handle.token not in repr(handle)
    assert "site-secret" not in handle.key
    assert "private query" not in handle.key
    assert second_worker.acquire_rebuild_lock(**arguments, lease_seconds=10) is None

    lock_key, lock_token, lease_seconds, nx = redis_client.set_calls[-1]
    assert lock_key == handle.key
    assert lock_token != handle.token  # The competing SET attempt generated its own token.
    assert lease_seconds == 10
    assert nx is True

    assert first_worker.release_rebuild_lock(handle)
    assert redis_client.values.get(handle.key) is None
    assert not first_worker.release_rebuild_lock(handle)
    assert len(redis_client.eval_calls) == 2
    assert "redis.call('get'" in redis_client.eval_calls[0][0]
    assert "redis.call('del'" in redis_client.eval_calls[0][0]


def test_rebuild_lock_expiry_allows_new_owner_and_old_handle_cannot_release_it() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "vlans",
        "generation": 3,
        "scope": {"site_ids": ["site-1"]},
        "query": {"page": 1},
    }

    old_handle = cache.acquire_rebuild_lock(**arguments, lease_seconds=2)
    assert old_handle is not None
    redis_client.now += 2
    new_handle = cache.acquire_rebuild_lock(**arguments, lease_seconds=5)
    assert new_handle is not None
    assert new_handle.token != old_handle.token

    assert not cache.release_rebuild_lock(old_handle)
    assert redis_client.values[new_handle.key][0] == new_handle.token
    assert cache.release_rebuild_lock(new_handle)


def test_rebuild_lock_rejects_wrong_token_and_invalid_lease_inputs() -> None:
    redis_client = FakeRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "bindings",
        "generation": 1,
        "scope": {"all_sites": True},
        "query": {"page": 1},
    }
    handle = cache.acquire_rebuild_lock(**arguments, lease_seconds=5)
    assert handle is not None

    incorrect_handle = CmdbCacheLock(key=handle.key, token="A" * 32)
    assert not cache.release_rebuild_lock(incorrect_handle)
    assert redis_client.values[handle.key][0] == handle.token
    assert cache.release_rebuild_lock(handle)

    for invalid_lease in (0, 31):
        with pytest.raises(ValueError):
            cache.acquire_rebuild_lock(**arguments, lease_seconds=invalid_lease)
    with pytest.raises(TypeError):
        cache.acquire_rebuild_lock(**arguments, lease_seconds=True)


def test_rebuild_lock_redis_failures_return_without_raising() -> None:
    class FailingRedis:
        set_attempts = 0
        eval_attempts = 0

        def set(
            self, key: str, value: str, *, ex: int, nx: bool = False
        ) -> None:
            self.set_attempts += 1
            raise ConnectionError("redis://user:secret@example.invalid")

        def eval(self, script: str, numkeys: int, *args: Any) -> None:
            self.eval_attempts += 1
            raise TimeoutError("redis://user:secret@example.invalid")

    redis_client = FakeRedis()
    working_cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "interfaces",
        "generation": 4,
        "scope": {"site_ids": ["site-1"]},
        "query": {"page": 1},
    }
    handle = working_cache.acquire_rebuild_lock(**arguments, lease_seconds=5)
    assert handle is not None

    failing_redis = FailingRedis()
    failing_cache = CmdbQueryCache("nexora:test:cmdb:v1", failing_redis)
    assert failing_cache.acquire_rebuild_lock(**arguments, lease_seconds=5) is None
    assert not failing_cache.release_rebuild_lock(handle)
    assert failing_cache.failure_count == 1
    assert failing_cache.is_cooling_down
    assert failing_cache.last_failure_kind == "ConnectionError"
    assert failing_redis.set_attempts == 1
    assert failing_redis.eval_attempts == 0
    assert "secret" not in repr(failing_cache.last_failure_kind)

    class EvalFailingRedis:
        def eval(self, script: str, numkeys: int, *args: Any) -> None:
            raise TimeoutError("redis://user:secret@example.invalid")

    eval_failing_cache = CmdbQueryCache(
        "nexora:test:cmdb:v1", EvalFailingRedis()
    )
    assert not eval_failing_cache.release_rebuild_lock(handle)
    assert eval_failing_cache.failure_count == 1
    assert eval_failing_cache.last_failure_kind == "TimeoutError"
    assert eval_failing_cache.is_cooling_down


def test_redis_failure_cooldown_short_circuits_then_recovers(monkeypatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(cmdb_cache_module, "_monotonic", lambda: clock["now"])

    class IntermittentRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.available = True
            self.get_attempts = 0
            self.set_attempts = 0
            self.eval_attempts = 0

        def get(self, key: str) -> str | bytes | None:
            self.get_attempts += 1
            if not self.available:
                raise ConnectionError("redis://user:secret@example.invalid")
            return super().get(key)

        def set(
            self, key: str, value: str, *, ex: int, nx: bool = False
        ) -> bool | None:
            self.set_attempts += 1
            if not self.available:
                raise ConnectionError("redis://user:secret@example.invalid")
            return super().set(key, value, ex=ex, nx=nx)

        def eval(self, script: str, numkeys: int, *args: Any) -> int:
            self.eval_attempts += 1
            if not self.available:
                raise TimeoutError("redis://user:secret@example.invalid")
            return super().eval(script, numkeys, *args)

    redis_client = IntermittentRedis()
    cache = CmdbQueryCache("nexora:test:cmdb:v1", redis_client)
    arguments = {
        "resource": "interfaces",
        "generation": 4,
        "scope": {"site_ids": ["site-1"]},
        "query": {"page": 1},
    }
    handle = cache.acquire_rebuild_lock(**arguments, lease_seconds=10)
    assert handle is not None

    redis_client.available = False
    assert cache.get_json(**arguments) is None
    assert cache.failure_count == 1
    assert cache.is_cooling_down
    assert cache.cooldown_remaining_seconds == 30.0
    attempts_after_failure = (
        redis_client.get_attempts,
        redis_client.set_attempts,
        redis_client.eval_attempts,
    )

    assert not cache.set_json(**arguments, value={"items": []})
    assert cache.acquire_rebuild_lock(**arguments, lease_seconds=5) is None
    assert not cache.release_rebuild_lock(handle)
    assert cache.get_json(**arguments) is None
    clock["now"] = 129.999
    assert cache.get_json(**arguments) is None
    assert (
        redis_client.get_attempts,
        redis_client.set_attempts,
        redis_client.eval_attempts,
    ) == attempts_after_failure

    redis_client.available = True
    clock["now"] = 130.0
    assert cache.get_json(**arguments) is None  # Successful miss clears the cooldown.
    assert not cache.is_cooling_down
    assert cache.cooldown_remaining_seconds == 0.0
    assert cache.last_failure_kind is None
    assert cache.failure_count == 1  # Diagnostic count remains cumulative.

    assert cache.set_json(**arguments, value={"items": ["ready"]})
    assert cache.release_rebuild_lock(handle)
    assert cache.acquire_rebuild_lock(**arguments, lease_seconds=5) is not None
