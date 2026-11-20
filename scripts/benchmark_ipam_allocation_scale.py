#!/usr/bin/env python3
"""Measure IPAM allocation latency on a disposable local PostgreSQL database.

The benchmark seeds 100,000 formal IP records and 1,000 child Prefixes, then
records repeated service latency and SQL statement counts. It never connects to
the configured application database or queries historical observation tables.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from statistics import median
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

from backend.tests.pg_test_utils import (  # noqa: E402
    capture_database_state,
    create_test_database,
    drop_test_database,
    restore_database_state,
    switch_database,
)
from database import core as database_core  # noqa: E402
from database import get_db_connection, init_db, schema as database_schema  # noqa: E402
from services import ipam_service  # noqa: E402
from services.ipam_address_space_service import create_address_space  # noqa: E402
from services.ipam_service import allocate_next_address, create_subnet, get_next_available_prefix  # noqa: E402


FORMAL_IP_COUNT = 100_000
CHILD_PREFIX_COUNT = 1_000
SAMPLE_COUNT = 25
INITIAL_P95_TARGET_MS = 1_000.0


class _CountingConnection:
    def __init__(self, connection, counter: dict[str, int]):
        self._connection = connection
        self._counter = counter

    def execute(self, *args, **kwargs):
        self._counter["statements"] += 1
        sql = " ".join(str(args[0]).split()) if args else "<unknown SQL>"
        started = time.perf_counter()
        try:
            cursor = self._connection.execute(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            profile = self._counter["queries"].setdefault(
                sql,
                {"sql": sql, "count": 0, "execute_ms": 0.0, "fetch_ms": 0.0, "rows": 0},
            )
            profile["count"] += 1
            profile["execute_ms"] += elapsed_ms
        return _CountingCursor(cursor, profile)

    def executemany(self, *args, **kwargs):
        self._counter["statements"] += 1
        return self._connection.executemany(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _CountingCursor:
    def __init__(self, cursor, profile: dict):
        self._cursor = cursor
        self._profile = profile

    def fetchall(self):
        started = time.perf_counter()
        rows = self._cursor.fetchall()
        self._profile["fetch_ms"] += (time.perf_counter() - started) * 1000
        self._profile["rows"] += len(rows)
        return rows

    def fetchone(self):
        started = time.perf_counter()
        row = self._cursor.fetchone()
        self._profile["fetch_ms"] += (time.perf_counter() - started) * 1000
        self._profile["rows"] += int(row is not None)
        return row

    def fetchmany(self, *args, **kwargs):
        started = time.perf_counter()
        rows = self._cursor.fetchmany(*args, **kwargs)
        self._profile["fetch_ms"] += (time.perf_counter() - started) * 1000
        self._profile["rows"] += len(rows)
        return rows

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _measure(service_call, original_get_connection) -> dict:
    durations_ms: list[float] = []
    statement_counts: list[int] = []
    results = []
    for sample_index in range(SAMPLE_COUNT):
        counter = {"statements": 0, "queries": {}}

        def counted_connection():
            return _CountingConnection(original_get_connection(), counter)

        ipam_service.get_db_connection = counted_connection
        started = time.perf_counter()
        try:
            results.append(service_call(sample_index))
        finally:
            durations_ms.append((time.perf_counter() - started) * 1000)
            statement_counts.append(counter["statements"])
            ipam_service.get_db_connection = original_get_connection
    slow_sql = sorted(
        (
            {
                "sql": profile["sql"],
                "count": profile["count"],
                "rows_total": profile["rows"],
                "execute_ms_total": round(profile["execute_ms"], 2),
                "fetch_ms_total": round(profile["fetch_ms"], 2),
            }
            for profile in counter["queries"].values()
        ),
        key=lambda item: item["execute_ms_total"] + item["fetch_ms_total"],
        reverse=True,
    )[:8]
    return {
        "samples": SAMPLE_COUNT,
        "p50_ms": round(median(durations_ms), 2),
        "p95_ms": round(_percentile(durations_ms, 0.95), 2),
        "max_ms": round(max(durations_ms), 2),
        "p95_sql_statements": int(_percentile([float(value) for value in statement_counts], 0.95)),
        "slow_sql": slow_sql,
        "results": results,
    }


def run_benchmark() -> dict:
    original_state = capture_database_state()
    source = None
    project_root = database_core.PROJECT_ROOT
    schema_root = database_schema.PROJECT_ROOT
    completed = False
    try:
        source = create_test_database(original_state.url, purpose="ipam_scale_benchmark")
        switch_database(source.url, initialized=False)
        with tempfile.TemporaryDirectory(prefix="nexora-ipam-scale-root-") as temporary_root:
            database_core.PROJECT_ROOT = temporary_root
            database_schema.PROJECT_ROOT = temporary_root
            init_db()

            ip_space = create_address_space(
                name=f"100k-IP benchmark {uuid4().hex[:8]}",
                kind="global",
                vrf_id=None,
                security_tenant_id="tenant-default",
            )
            ip_prefix = create_subnet(
                prefix="10.80.0.0/14",
                address_space_id=ip_space["id"],
                tenant_id="tenant-default",
                name="100k-IP benchmark prefix",
            )
            network = ipaddress.ip_network(ip_prefix["prefix"])
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            with get_db_connection() as conn:
                batch = []
                for offset in range(1, FORMAL_IP_COUNT + 1):
                    address = str(ipaddress.ip_address(int(network.network_address) + offset))
                    batch.append((
                        f"ipam-bench-ip-{offset:06d}", ip_prefix["id"], address, address,
                        ip_space["id"], "tenant-default", "", "active", timestamp, timestamp,
                    ))
                    if len(batch) == 5_000:
                        conn.executemany(
                            """INSERT INTO ip_addresses
                                   (id, subnet_id, address, address_inet, address_space_id,
                                    tenant_id, site_id, status, created_at, updated_at)
                               VALUES (?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?)""",
                            batch,
                        )
                        batch.clear()
                if batch:
                    conn.executemany(
                        """INSERT INTO ip_addresses
                               (id, subnet_id, address, address_inet, address_space_id,
                                tenant_id, site_id, status, created_at, updated_at)
                           VALUES (?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?)""",
                        batch,
                    )
                conn.commit()

            prefix_space = create_address_space(
                name=f"1k-Prefix benchmark {uuid4().hex[:8]}",
                kind="global",
                vrf_id=None,
                security_tenant_id="tenant-default",
            )
            parent = create_subnet(
                prefix="10.88.0.0/14",
                address_space_id=prefix_space["id"],
                tenant_id="tenant-default",
                name="1k-Prefix benchmark parent",
            )
            parent_network = ipaddress.ip_network(parent["prefix"])
            child_rows = []
            for index, child in enumerate(parent_network.subnets(new_prefix=26)):
                if index >= CHILD_PREFIX_COUNT:
                    break
                cidr = str(child)
                child_rows.append((
                    f"ipam-bench-child-{index:04d}", cidr, cidr, prefix_space["id"],
                    "tenant-default", timestamp, timestamp,
                ))
            if len(child_rows) != CHILD_PREFIX_COUNT:
                raise RuntimeError("The parent network cannot hold 1,000 /26 child Prefixes")
            with get_db_connection() as conn:
                conn.executemany(
                    """INSERT INTO prefixes
                           (id, prefix, prefix_cidr, address_space_id, tenant_id,
                            status, name, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'active', 'benchmark child', ?, ?)""",
                    child_rows,
                )
                conn.commit()

            original_get_connection = ipam_service.get_db_connection
            ip_samples = _measure(
                lambda index: allocate_next_address(
                    ip_prefix["id"],
                    hostname=f"ipam-benchmark-worker-{index}",
                    purpose="management",
                )["address"],
                original_get_connection,
            )
            expected_ip = str(ipaddress.ip_address(int(network.network_address) + FORMAL_IP_COUNT + 1))
            if len(set(map(str, ip_samples["results"]))) != SAMPLE_COUNT:
                raise RuntimeError("Concurrent-safety check failed: allocation results were repeated")
            if str(ip_samples["results"][0]) != expected_ip:
                raise RuntimeError(
                    f"100k-IP benchmark returned {ip_samples['results'][0]}, expected {expected_ip}"
                )

            expected_child = str(next(iter(list(parent_network.subnets(new_prefix=26))[CHILD_PREFIX_COUNT:CHILD_PREFIX_COUNT + 1])))
            prefix_samples = _measure(
                lambda _index: get_next_available_prefix(parent["id"], 26),
                original_get_connection,
            )
            if set(map(str, prefix_samples["results"])) != {expected_child}:
                raise RuntimeError(
                    f"1k-Prefix benchmark did not consistently return {expected_child}"
                )

            result = {
                "status": "measured",
                "database": "disposable local PostgreSQL",
                "configured_application_database_opened": False,
                "historical_observation_tables_queried": False,
                "ip_allocation": {
                    "formal_ip_rows_before_samples": FORMAL_IP_COUNT,
                    **{key: value for key, value in ip_samples.items() if key != "results"},
                    "returned_unique_addresses": SAMPLE_COUNT,
                    "first_result": str(ip_samples["results"][0]),
                    "initial_p95_target_ms": INITIAL_P95_TARGET_MS,
                    "initial_p95_target_met": ip_samples["p95_ms"] <= INITIAL_P95_TARGET_MS,
                },
                "prefix_candidate": {
                    "existing_child_prefixes": CHILD_PREFIX_COUNT,
                    **{key: value for key, value in prefix_samples.items() if key != "results"},
                    "candidate": expected_child,
                    "initial_p95_target_ms": INITIAL_P95_TARGET_MS,
                    "initial_p95_target_met": prefix_samples["p95_ms"] <= INITIAL_P95_TARGET_MS,
                },
            }
        completed = True
        return result
    finally:
        database_core.PROJECT_ROOT = project_root
        database_schema.PROJECT_ROOT = schema_root
        restore_database_state(original_state)
        if source is not None:
            drop_test_database(source)
        if not completed:
            print(
                json.dumps({"status": "failed", "temporary_source_database_dropped": True}),
                file=sys.stderr,
            )


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2))
