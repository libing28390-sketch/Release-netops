"""Isolated VRF scope and singleflight budget regressions; no device IO."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from services import ip_locator_endpoint_evidence as evidence
from services import ip_locator_trace_service as trace


@pytest.fixture
def vrf_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE vrfs(id TEXT, tenant_id TEXT, vrf_name TEXT)")
    conn.executemany("INSERT INTO vrfs VALUES (?,?,?)", [
        ("a", "t", "BLUE"), ("b", "t", "RED"), ("c", "other", "BLUE"),
        ("d", "t", "DUP"), ("e", "t", "dup"), ("f", "t", "a"),
    ])
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.parametrize("name,expected", [
    ("BLUE", "a"), ("blue", "a"), ("RED", "b"), ("b", "b"),
    ("dup", None), ("a", None), ("missing", None),
])
def test_vrf_alias(vrf_db, name, expected):
    assert evidence._resolve_current_vrf_id(vrf_db, "t", name) == expected


def _row(kind="vrf", vrf="a", space="sa", **kwargs):
    effective = {"vrf": "explicit_vrf", "global": "explicit_global", "unknown": "unknown"}[kind]
    return dict(source_vrf_context_status=kind, vrf_context_status=effective,
                scope_status="scope_pending" if kind == "unknown" else "resolved",
                address_space_id=space, vrf_id=vrf, **kwargs)


a = _row()
b = _row(vrf="b", space="sb")
g = _row("global", "", "sg")
u = _row("unknown", "", "")


@pytest.mark.parametrize("rows,requested,default,expected", [
    ([a, b], "a", False, [a]), ([a, b], "b", False, [b]),
    ([a, b], "c", False, []), ([a, g], "", True, [g]),
    ([a, u], "", True, [u]), ([a, u], "a", False, None),
    ([u, g], "", True, [u, g]), ([a, a], "a", False, [a, a]),
    ([g], "a", False, []), ([dict(a, scope_status="conflict")], "a", False, None),
    ([dict(b, scope_status="scope_pending"), a], "a", False, None),
    ([dict(a, ip_mac_conflict=True)], "a", False, None),
    ([dict(g, address_space_id="")], "", True, None),
    ([dict(u, vrf_context_status="explicit_global")], "", True, None),
])
def test_scope(rows, requested, default, expected):
    assert evidence._select_current_arp_scope(rows, requested, default) == expected


@pytest.mark.parametrize("arp,fdb,expected", [
    (a, dict(a, entry_type="dynamic"), True),
    (a, dict(b, entry_type="dynamic"), False),
    (a, dict(u, entry_type="dynamic"), False),
    (u, dict(u, entry_type="dynamic"), True),
    (u, dict(a, entry_type="dynamic"), False),
    (a, dict(a, entry_type="static"), False),
    (a, dict(a, entry_type=""), False),
    (a, dict(a, entry_type="dynamic", scope_status="scope_pending"), False),
])
def test_pair(arp, fdb, expected):
    assert evidence._current_facts_are_compatible(arp, fdb) == expected


@pytest.mark.parametrize("seconds,expected", [
    (0, True), (299, True), (300, True), (301, False),
    (7200, False), (-1, False), (None, False),
])
def test_fresh(monkeypatch, seconds, expected):
    now = datetime(2026, 11, 28, tzinfo=timezone.utc)
    monkeypatch.setattr(evidence, "_iso_utc",
                        lambda v: ("", None) if v is None else (v, datetime.fromisoformat(v)))
    stamp = None if seconds is None else (now - timedelta(seconds=seconds)).isoformat()
    assert evidence._current_fact_is_fresh({"observed_at": stamp}, now) == expected


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Cache:
    def __init__(self, clock, *, acquire_at=None, result_at=None, down_at=None):
        self.clock = clock
        self.acquire_at = acquire_at
        self.result_at = result_at
        self.down_at = down_at
        self.released = []
        self.acquire_count = 0

    def get_json(self, key):
        if self.result_at is not None and self.clock.now >= self.result_at:
            return {"status": "completed", "found": True,
                    "dependency_manifest": {}, "evidence_collected_at": "t"}

    def is_fresh(self, *args):
        return True

    def acquire_lock(self, key, ttl):
        self.acquire_count += 1
        if self.acquire_at is not None and self.clock.now >= self.acquire_at:
            return "token"

    def ping(self):
        return self.down_at is None or self.clock.now < self.down_at

    def release_lock(self, key, token):
        self.released.append((key, token))


@pytest.fixture
def env(monkeypatch):
    clock = Clock()
    calls = []

    def uncached(ip, **kwargs):
        calls.append((ip, kwargs["deadline_seconds"]))
        return {"status": "completed", "found": True}

    for name, value in {
        "time": clock, "_now_iso": lambda: "t",
        "_registered_ipam_vip_result": lambda *a, **k: None,
        "_try_snmp_endpoint": lambda *a, **k: None,
        "_trace_ip_uncached": uncached,
        "_normalise_vrf": lambda x: x, "_authorization_scope_hash": lambda x: "auth",
        "_cache_for_scope": lambda scope: (None, "scope"),
        "_cache_key": lambda cache, kind, *a: kind if cache else None,
        "_manifest_is_current_for_code": lambda x: True,
        "_pending_fact_invalidation": lambda *a: False,
        "_copy_cached_result_for_request": lambda x: dict(x),
        "_set_cache_source": lambda *a, **k: None,
    }.items():
        monkeypatch.setattr(trace, name, value)
    return clock, calls


def configure(monkeypatch, clock, **kwargs):
    cache = Cache(clock, **kwargs)
    monkeypatch.setattr(trace, "_cache_for_scope", lambda scope: (cache, "scope"))
    return cache


def test_cancel_before_fast_query(env, monkeypatch):
    monkeypatch.setattr(trace, "_registered_ipam_vip_result", lambda *a, **k: pytest.fail("must not query"))
    assert trace.trace_ip("192.0.2.1", cancel_check=lambda: True)["status"] == "cancelled"


def test_cancel_check_failure(env):
    def fail():
        raise RuntimeError("unavailable")
    assert trace.trace_ip("192.0.2.1", cancel_check=fail)["status"] == "cancelled"


def test_late_fast_result(env, monkeypatch):
    clock, calls = env

    def late(*args, **kwargs):
        clock.sleep(2)
        return {"found": True}

    monkeypatch.setattr(trace, "_registered_ipam_vip_result", late)
    result = trace.trace_ip("192.0.2.1", deadline_seconds=1)
    assert result["conclusion"] == "deadline_exceeded" and not result["found"] and not calls


def test_short_request_gets_remaining_budget(env, monkeypatch):
    clock, calls = env

    def slow(*args, **kwargs):
        clock.sleep(.25)

    monkeypatch.setattr(trace, "_try_snmp_endpoint", slow)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=1)["found"]
    assert calls == [("192.0.2.1", .75)]


def test_wait_then_lock(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock, acquire_at=.6)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=2)["found"]
    assert calls[0][1] == pytest.approx(1.4) and cache.released == [("lock", "token")]


def test_cancel_waiter(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=2,
                          cancel_check=lambda: clock.now >= .4)["status"] == "cancelled"
    assert not calls and not cache.released


def test_wait_timeout(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=1)["conclusion"] == "singleflight_timeout"
    assert clock.now == pytest.approx(1) and not calls and not cache.released


def test_shared_result(env, monkeypatch):
    clock, calls = env
    configure(monkeypatch, clock, result_at=.4)
    result = trace.trace_ip("192.0.2.1", deadline_seconds=2, durable_run_id="waiter")
    assert result["found"] and result["run_id"] == "waiter" and result["cache"]["result"] == "hit" and not calls


def test_redis_loss_during_wait(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock, down_at=.4)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=2)["found"]
    assert calls[0][1] == pytest.approx(1.6) and not cache.released


def test_invalidated_result_not_reused(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock, result_at=0, acquire_at=0)
    monkeypatch.setattr(trace, "_pending_fact_invalidation", lambda *a: True)
    assert trace.trace_ip("192.0.2.1", deadline_seconds=2)["found"]
    assert len(calls) == 1 and cache.released == [("lock", "token")]


def test_late_cli_result_rejected_and_lock_released(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock, acquire_at=0)

    def late(*args, **kwargs):
        clock.sleep(3)
        return {"found": True}

    monkeypatch.setattr(trace, "_trace_ip_uncached", late)
    result = trace.trace_ip("192.0.2.1", deadline_seconds=2)
    assert not result["found"] and result["conclusion"] == "deadline_exceeded"
    assert cache.released == [("lock", "token")]


def test_force_refresh_no_shared_lock(env, monkeypatch):
    clock, calls = env
    cache = configure(monkeypatch, clock, result_at=0)
    assert trace.trace_ip("192.0.2.1", force_refresh=True, deadline_seconds=2)["found"]
    assert len(calls) == 1 and cache.acquire_count == 0
