r"""Opt-in PostgreSQL benchmark for the three CMDB list routes.

Run manually from the repository root with:

    $env:NETOPS_RUN_CMDB_LIST_PERFORMANCE = '1'
    .\.venv\Scripts\python.exe -m pytest -s backend/tests/vendor_audit/test_cmdb_list_performance.py
    Remove-Item Env:NETOPS_RUN_CMDB_LIST_PERFORMANCE

The test uses the shared isolated PostgreSQL fixture and mounts only the CMDB
router. It never starts the production app or creates a Redis client.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import cmdb as cmdb_api
import database
from services.cmdb_cache_service import CmdbQueryCache


_RUN_ENV = "NETOPS_RUN_CMDB_LIST_PERFORMANCE"
_SAMPLES_ENV = "NETOPS_CMDB_LIST_PERFORMANCE_SAMPLES"
_SITE_ID = "cmdb-perf-site"
_DEVICE_PREFIX = "cmdb-perf-device-"
_INTERFACE_PREFIX = "cmdb-perf-interface-"
_OBSERVED_VLAN_PREFIX = "cmdb-perf-vlan-"
_BINDING_PREFIX = "cmdb-perf-binding-"
_FIXTURE_TIME = "2026-01-01T00:00:00+00:00"
_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts"


def _sql_fingerprint(sql: Any) -> str:
    """Return a stable digest without retaining or exposing statement text."""
    normalized = str(sql)
    normalized = re.sub(r"/\*.*?\*/", " ", normalized, flags=re.DOTALL)
    normalized = re.sub(r"--[^\r\n]*", " ", normalized)
    normalized = re.sub(r"'(?:''|[^'])*'", "'?'", normalized)
    normalized = re.sub(r'"(?:""|[^"])*"', '"?"', normalized)
    normalized = re.sub(r"\$\d+", "?", normalized)
    normalized = re.sub(r"\b\d+\b", "?", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _sample_count() -> int:
    raw_value = os.environ.get(_SAMPLES_ENV, "10").strip()
    try:
        count = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{_SAMPLES_ENV} must be a positive integer; got {raw_value!r}") from exc
    if count < 1:
        raise ValueError(f"{_SAMPLES_ENV} must be at least 1; got {count}")
    return count


def _distribution(values: list[float | int]) -> dict[str, int | float]:
    """Summarize samples with the nearest-rank percentile convention."""
    if not values:
        raise ValueError("cannot summarize an empty sample")
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "sample_count": len(ordered),
        "median": round(float(statistics.median(ordered)), 3),
        "p95": round(float(ordered[p95_index]), 3),
        "max": round(float(ordered[-1]), 3),
    }


class _SqlStats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.execute_count = 0
        self.elapsed_seconds = 0.0
        self.by_fingerprint: dict[str, list[float | int]] = defaultdict(lambda: [0, 0.0])

    def record(self, sql: Any, elapsed_seconds: float) -> None:
        fingerprint = _sql_fingerprint(sql)
        self.execute_count += 1
        self.elapsed_seconds += elapsed_seconds
        self.by_fingerprint[fingerprint][0] += 1
        self.by_fingerprint[fingerprint][1] += elapsed_seconds

    def report(self) -> dict[str, Any]:
        return {
            "sql_execute_count": self.execute_count,
            "total_sql_elapsed_ms": round(self.elapsed_seconds * 1000, 3),
            "sql_fingerprints": [
                {
                    "fingerprint": fingerprint,
                    "execute_count": int(count_and_seconds[0]),
                    "elapsed_ms": round(float(count_and_seconds[1]) * 1000, 3),
                }
                for fingerprint, count_and_seconds in sorted(self.by_fingerprint.items())
            ],
        }


class _CountedConnection:
    """Transparent connection wrapper that records execute calls only."""

    def __init__(self, connection: Any, stats: _SqlStats) -> None:
        self._connection = connection
        self._stats = stats

    def execute(self, sql: Any, params: Any = None) -> Any:
        started = time.perf_counter()
        try:
            return self._connection.execute(sql, params)
        finally:
            self._stats.record(sql, time.perf_counter() - started)

    def executemany(self, sql: Any, params: Any) -> Any:
        started = time.perf_counter()
        try:
            return self._connection.executemany(sql, params)
        finally:
            self._stats.record(sql, time.perf_counter() - started)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _seed_benchmark_rows(connection: Any, viewer_id: str) -> dict[str, int]:
    """Insert deterministic rows into the isolated database using PostgreSQL."""
    connection.execute(
        """INSERT INTO sites (id, site_code, site_name, tenant_id)
           VALUES (?, ?, ?, ?)""",
        (_SITE_ID, "CMDB_PERF", "CMDB Performance Fixture", "tenant-default"),
    )
    connection.execute(
        """INSERT INTO user_resource_scopes (
               id, user_id, resource_type, scope_type, scope_id, actions_json, created_at
           ) VALUES (?, ?, 'asset', 'site', ?, '["view"]', ?)""",
        ("cmdb-perf-viewer-scope", viewer_id, _SITE_ID, _FIXTURE_TIME),
    )
    connection.execute(
        """INSERT INTO devices (
           id, hostname, ip_address, platform, status, role, site, site_id,
           tenant_id, device_category
           )
           SELECT 'cmdb-perf-device-' || lpad(n::text, 3, '0'),
                  'perf-node-' || lpad(n::text, 3, '0'),
                  '192.0.2.' || n::text,
                  'h3c_comware', 'online', 'Switch', 'CMDB Performance Fixture',
                  ?, 'tenant-default', 'other'
             FROM generate_series(1, 100) AS generated(n)""",
        (_SITE_ID,),
    )
    connection.execute(
        """INSERT INTO interfaces (
               id, device_id, interface_name, name_raw, name_display, description,
               admin_status, oper_status, mtu, speed, bandwidth, interface_type,
               switchport_mode, access_vlan, native_vlan, allowed_vlans,
               primary_ip, ip_address, ip_enabled, is_l3
           )
           SELECT 'cmdb-perf-interface-' || right(d.id, 3) || '-'
                      || lpad(port_no::text, 3, '0'),
                  d.id,
                  'GE0/0/' || lpad(port_no::text, 3, '0'),
                  'GE0/0/' || lpad(port_no::text, 3, '0'),
                  'GE0/0/' || lpad(port_no::text, 3, '0'),
                  'CMDB performance port ' || port_no::text,
                  'up', 'up', 1500, 1000000000, 1000000000,
                  'physical', 'access', 200 + ((port_no - 1) % 20), NULL, '',
                  '10.42.' || right(d.id, 3) || '.' || port_no::text,
                  '10.42.' || right(d.id, 3) || '.' || port_no::text,
                  1, FALSE
             FROM devices d
             CROSS JOIN generate_series(1, 100) AS generated(port_no)
            WHERE d.id LIKE 'cmdb-perf-device-%'"""
    )
    connection.execute(
        """INSERT INTO cmdb_collection_snapshots (
               device_id, domain, attempt_generation, successful_generation,
               attempt_status, run_id, last_attempt_at, last_success_at,
               observed_at, record_count
           )
           SELECT d.id, 'vlan_inventory', 1, 1, 'succeeded', 'cmdb-perf-run',
                  ?, ?, ?, 20
             FROM devices d
            WHERE d.id LIKE 'cmdb-perf-device-%'""",
        (_FIXTURE_TIME, _FIXTURE_TIME, _FIXTURE_TIME),
    )
    connection.execute(
        """INSERT INTO cmdb_device_vlan_observations (
               device_id, vlan_id, site_id, vlan_name, vlan_status,
               generation, observed_at, run_id
           )
           SELECT d.id,
                  CASE WHEN right(d.id, 3)::integer <= 50 THEN 200 ELSE 220 END + vlan_offset,
                  ?,
                  'cmdb-perf-vlan-' || lpad((
                      CASE WHEN right(d.id, 3)::integer <= 50 THEN 200 ELSE 220 END
                      + vlan_offset
                  )::text, 3, '0'),
                  'active', 1, ?, 'cmdb-perf-run'
             FROM devices d
             CROSS JOIN generate_series(0, 19) AS generated(vlan_offset)
            WHERE d.id LIKE 'cmdb-perf-device-%'""",
        (_SITE_ID, _FIXTURE_TIME),
    )
    connection.execute(
        """INSERT INTO vlan_business_bindings (
               id, site_id, vrf_id, vlan_id, business_system, department, owner,
               business_level, status, description, created_at, updated_at
           )
           SELECT 'cmdb-perf-binding-' || lpad(n::text, 3, '0'), ?, '',
                  200 + (n % 20),
                  'perf-service-' || lpad((n / 50)::text, 2, '0') || '-'
                      || lpad((n % 50)::text, 2, '0'),
                  'CMDB performance fixture', 'benchmark-owner', 'P3', 'active',
                  'Deterministic isolated benchmark row', ?, ?
             FROM generate_series(0, 499) AS generated(n)""",
        (_SITE_ID, _FIXTURE_TIME, _FIXTURE_TIME),
    )
    connection.commit()

    count_queries = {
        "devices": ("SELECT COUNT(*) FROM devices WHERE id LIKE ?", (_DEVICE_PREFIX + "%",)),
        "interfaces": ("SELECT COUNT(*) FROM interfaces WHERE id LIKE ?", (_INTERFACE_PREFIX + "%",)),
        "cmdb_device_vlan_observations": (
            "SELECT COUNT(*) FROM cmdb_device_vlan_observations WHERE device_id LIKE ?",
            (_DEVICE_PREFIX + "%",),
        ),
        "vlan_business_bindings": (
            "SELECT COUNT(*) FROM vlan_business_bindings WHERE id LIKE ?",
            (_BINDING_PREFIX + "%",),
        ),
    }
    return {
        table: int(connection.execute(sql, params).fetchone()[0])
        for table, (sql, params) in count_queries.items()
    }


def _assert_page(
    payload: Any,
    *,
    expected_total: int | None,
    expected_page: int,
    expected_page_size: int,
    expected_items: int,
) -> list[dict[str, Any]]:
    assert isinstance(payload, dict)
    assert payload.get("success") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    items = data.get("items")
    assert isinstance(items, list)
    actual_total = data.get("total")
    assert isinstance(actual_total, int) and actual_total >= 0
    if expected_total is not None:
        assert actual_total == expected_total
    assert data.get("page") == expected_page
    assert data.get("page_size") == expected_page_size
    if "total_pages" in data:
        assert data["total_pages"] == max(
            1, (actual_total + expected_page_size - 1) // expected_page_size
        )
    assert len(items) == expected_items
    assert all(isinstance(item, dict) for item in items)
    return items


@pytest.mark.skipif(
    os.environ.get(_RUN_ENV) != "1",
    reason=f"manual PostgreSQL benchmark; set {_RUN_ENV}=1 to run",
)
def test_manual_cmdb_list_performance_benchmark(isolated_db, make_user, monkeypatch) -> None:
    """Measure repeated synthetic HTTP list reads without SLA thresholds."""
    sample_count = _sample_count()
    viewer_record = make_user(
        "cmdb_list_performance_viewer",
        role="Viewer",
        tenant_id="tenant-default",
    )
    viewer = {
        **viewer_record,
        "id": viewer_record["user_id"],
        "role_profile": "Change Requester",
        "scope_mode": "restricted",
    }

    connection = database.get_db_connection()
    try:
        fixture_counts = _seed_benchmark_rows(connection, viewer["id"])
    finally:
        connection.close()

    expected_fixture_counts = {
        "devices": 100,
        "interfaces": 10000,
        "cmdb_device_vlan_observations": 2000,
        "vlan_business_bindings": 500,
    }
    assert fixture_counts == expected_fixture_counts

    stats = _SqlStats()
    original_get_db_connection = database.get_db_connection

    def counted_get_db_connection() -> _CountedConnection:
        return _CountedConnection(original_get_db_connection(), stats)

    # Both the router's imported alias and runtime database lookups (for the
    # Viewer scope) use the same isolated PostgreSQL connection source.
    monkeypatch.setattr(database.core, "get_db_connection", counted_get_db_connection)
    monkeypatch.setattr(cmdb_api, "get_db_connection", counted_get_db_connection)

    # Inject a disabled cache directly. This never invokes the default runtime
    # resolver and cannot construct or contact a Redis client.
    disabled_cache = CmdbQueryCache("cmdb-performance:disabled", None)
    monkeypatch.setattr(cmdb_api, "get_cmdb_query_cache", lambda: disabled_cache)

    app = FastAPI()
    app.include_router(cmdb_api.router, prefix="/api")
    # Newer FastAPI versions expose included routers lazily on app.routes.
    # Inspect the source router so every CMDB Viewer dependency is overridden.
    for route in cmdb_api.router.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                app.dependency_overrides[dependency.call] = lambda: viewer

    report_rows: list[dict[str, Any]] = []

    def request_page(
        label: str,
        path: str,
        *,
        expected_total: int,
        expected_page: int,
        expected_page_size: int,
        expected_items: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        last_total = 0
        for sample_index in range(1, sample_count + 1):
            stats.reset()
            started = time.perf_counter()
            response = client.get(path)
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert response.status_code == 200, f"{label} sample {sample_index} returned HTTP {response.status_code}"
            assert response.headers.get("X-CMDB-Cache") == "bypass"
            payload = response.json()
            items = _assert_page(
                payload,
                expected_total=expected_total,
                expected_page=expected_page,
                expected_page_size=expected_page_size,
                expected_items=expected_items,
            )
            last_total = payload["data"]["total"]
            samples.append({
                "sample": sample_index,
                "http_status": response.status_code,
                "total": last_total,
                "response_bytes": len(response.content),
                "elapsed_ms": round(elapsed_ms, 3),
                "cache_state": "bypass",
                **stats.report(),
            })

        row = {
            "request": label,
            "http_status": 200,
            "total": last_total,
            "cache_state": "bypass",
            "elapsed_ms": _distribution([sample["elapsed_ms"] for sample in samples]),
            "response_bytes": _distribution([sample["response_bytes"] for sample in samples]),
            "sql_execute_count": _distribution([sample["sql_execute_count"] for sample in samples]),
            "total_sql_elapsed_ms": _distribution([sample["total_sql_elapsed_ms"] for sample in samples]),
            "samples": samples,
        }
        report_rows.append(row)
        return items, row

    # The app contains only the CMDB router and has no production lifespan.
    with TestClient(app, raise_server_exceptions=False) as client:
        interfaces_first, _ = request_page(
            "interfaces.page1",
            "/api/cmdb/interfaces?has_ip=true&page=1&page_size=10",
            expected_total=10000,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        interfaces_search_first, _ = request_page(
            "interfaces.search.page1",
            "/api/cmdb/interfaces?has_ip=true&search=perf-node-042&page=1&page_size=10",
            expected_total=100,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        interfaces_search_second, _ = request_page(
            "interfaces.search.page2",
            "/api/cmdb/interfaces?has_ip=true&search=perf-node-042&page=2&page_size=10",
            expected_total=100,
            expected_page=2,
            expected_page_size=10,
            expected_items=10,
        )
        assert not {
            item.get("id") for item in interfaces_search_first
        }.intersection(item.get("id") for item in interfaces_search_second)
        assert all(item.get("interface_name") for item in interfaces_first)

        vlan_site = f"site_id={_SITE_ID}"
        vlans_first, vlan_first_report = request_page(
            "vlans.page1",
            f"/api/cmdb/vlans?{vlan_site}&page=1&page_size=10",
            expected_total=None,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        assert vlan_first_report["total"] >= 30
        vlans_search_first, vlan_search_report = request_page(
            "vlans.search.page1",
            f"/api/cmdb/vlans?{vlan_site}&q=cmdb-perf-vlan-&device_category=other&page=1&page_size=10",
            expected_total=None,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        vlan_search_total = vlan_search_report["total"]
        assert vlan_search_total >= 30
        vlans_search_second, _ = request_page(
            "vlans.search.page2",
            f"/api/cmdb/vlans?{vlan_site}&q=cmdb-perf-vlan-&device_category=other&page=2&page_size=10",
            expected_total=vlan_search_total,
            expected_page=2,
            expected_page_size=10,
            expected_items=10,
        )
        vlans_search_third, _ = request_page(
            "vlans.search.page3",
            f"/api/cmdb/vlans?{vlan_site}&q=cmdb-perf-vlan-&device_category=other&page=3&page_size=10",
            expected_total=vlan_search_total,
            expected_page=3,
            expected_page_size=10,
            expected_items=10,
        )
        vlan_page_ids = [
            {(item.get("device_id"), item.get("vlan_id")) for item in page}
            for page in (vlans_search_first, vlans_search_second, vlans_search_third)
        ]
        assert not vlan_page_ids[0].intersection(vlan_page_ids[1])
        assert not vlan_page_ids[0].intersection(vlan_page_ids[2])
        assert not vlan_page_ids[1].intersection(vlan_page_ids[2])
        assert all(item.get("vlan_id") for item in vlans_first)

        binding_site = f"site_id={_SITE_ID}"
        bindings_first, _ = request_page(
            "vlan_business_bindings.page1",
            f"/api/cmdb/vlan-business-bindings?{binding_site}&page=1&page_size=10",
            expected_total=500,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        bindings_search_first, _ = request_page(
            "vlan_business_bindings.search.page1",
            f"/api/cmdb/vlan-business-bindings?{binding_site}&q=perf-service-02&page=1&page_size=10",
            expected_total=50,
            expected_page=1,
            expected_page_size=10,
            expected_items=10,
        )
        bindings_search_second, _ = request_page(
            "vlan_business_bindings.search.page2",
            f"/api/cmdb/vlan-business-bindings?{binding_site}&q=perf-service-02&page=2&page_size=10",
            expected_total=50,
            expected_page=2,
            expected_page_size=10,
            expected_items=10,
        )
        assert not {
            item.get("id") for item in bindings_search_first
        }.intersection(item.get("id") for item in bindings_search_second)
        assert all(item.get("business_system") for item in bindings_first)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "manual isolated PostgreSQL HTTP benchmark",
        "router_scope": "CMDB router only, exercised in-process with TestClient; production app lifespan not started",
        "redis": "disabled adapter injected; no Redis client accessed",
        "cache_state": "bypass; no cold/warm cache claim",
        "measurement_limits": "Synthetic fixture and current checkout only; not a production SLA or a before/after comparison.",
        "sample_count_per_request": sample_count,
        "percentile_method": "nearest-rank; p95 index is ceil(0.95 * sample_count) - 1",
        "fixture_rows": fixture_counts,
        "requests": report_rows,
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = _ARTIFACTS_DIR / f"cmdb_list_performance_{timestamp}.json"
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "completed",
        "report_path": str(report_path),
        "sample_count_per_request": sample_count,
        "request_count": len(report_rows),
        "fixture_rows": fixture_counts,
        "requests": [
            {
                "request": row["request"],
                "elapsed_ms": row["elapsed_ms"],
                "response_bytes": row["response_bytes"],
                "sql_execute_count": row["sql_execute_count"],
                "total_sql_elapsed_ms": row["total_sql_elapsed_ms"],
            }
            for row in report_rows
        ],
    }, ensure_ascii=False, indent=2))
