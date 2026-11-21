from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from database import get_db_connection
from services import ipam_service
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    _lock_prefixes_with_scopes,
    allocate_next_address,
    create_pool,
    create_subnet,
)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _RecordingConnection:
    def __init__(self, rows: dict[str, dict], events: list[tuple]):
        self.rows = rows
        self.events = events

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split())
        prefix_id = str(params[0])
        if normalized.startswith("SELECT id, tenant_id, address_space_id, vrf_id FROM prefixes"):
            self.events.append(("read_scope", prefix_id))
            return _FakeResult(self.rows.get(prefix_id))
        if normalized.startswith("SELECT * FROM prefixes") and "FOR UPDATE" in normalized:
            self.events.append(("lock_prefix", prefix_id))
            return _FakeResult(self.rows.get(prefix_id))
        raise AssertionError(f"Unexpected query in lock-order test: {normalized}")


def test_prefix_scope_advisories_are_sorted_before_prefix_row_locks(monkeypatch) -> None:
    rows = {
        "prefix-z": {
            "id": "prefix-z",
            "tenant_id": "tenant-z",
            "address_space_id": "space-z",
            "vrf_id": "",
        },
        "prefix-a": {
            "id": "prefix-a",
            "tenant_id": "tenant-a",
            "address_space_id": "space-a",
            "vrf_id": "",
        },
        "prefix-m": {
            "id": "prefix-m",
            "tenant_id": "tenant-a",
            "address_space_id": "space-b",
            "vrf_id": "",
        },
    }
    events: list[tuple] = []
    conn = _RecordingConnection(rows, events)

    def record_scope_lock(_conn, *, security_tenant_id, address_space_id=None, vrf_id=None):
        events.append(
            (
                "scope_lock",
                security_tenant_id,
                str(address_space_id or ""),
                str(vrf_id or ""),
            )
        )

    monkeypatch.setattr(ipam_service, "lock_ipam_scope", record_scope_lock)

    locked = _lock_prefixes_with_scopes(
        conn,
        {"prefix-z", "prefix-a", "prefix-m"},
        extra_scopes={("tenant-0", "space-0", "")},
    )

    expected_scopes = [
        ("tenant-0", "space-0", ""),
        ("tenant-a", "space-a", ""),
        ("tenant-a", "space-b", ""),
        ("tenant-z", "space-z", ""),
    ]
    assert [event[1:] for event in events if event[0] == "scope_lock"] == expected_scopes
    assert [event[1] for event in events if event[0] == "read_scope"] == [
        "prefix-a",
        "prefix-m",
        "prefix-z",
    ]
    assert [event[1] for event in events if event[0] == "lock_prefix"] == [
        "prefix-a",
        "prefix-m",
        "prefix-z",
    ]

    scope_positions = [index for index, event in enumerate(events) if event[0] == "scope_lock"]
    prefix_lock_positions = [index for index, event in enumerate(events) if event[0] == "lock_prefix"]
    assert max(index for index, event in enumerate(events) if event[0] == "read_scope") < min(scope_positions)
    assert max(scope_positions) < min(prefix_lock_positions)
    assert set(locked) == set(rows)


def test_concurrent_last_address_allocation_has_no_duplicate_or_hang(isolated_db, monkeypatch) -> None:
    del isolated_db
    space = create_address_space(
        name=f"Concurrent allocation {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="10.254.99.0/30",
        address_space_id=space["id"],
        gateway="10.254.99.1",
        network_type="management",
        name="IPAM write lock concurrency test",
    )

    original_get_db_connection = ipam_service.get_db_connection

    def get_connection_with_bounded_lock_wait():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '4s'")
        conn.execute("SET statement_timeout = '8s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", get_connection_with_bounded_lock_wait)

    start_together = Barrier(2)

    def allocate_last_address(worker_id: int) -> tuple[str, str]:
        start_together.wait(timeout=5)
        try:
            result = allocate_next_address(
                prefix["id"],
                hostname=f"concurrent-worker-{worker_id}",
                device_type="device",
                purpose="management",
            )
            return "allocated", str(result["address"])
        except ValueError as exc:
            if "No available IP addresses" not in str(exc):
                raise
            return "exhausted", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(allocate_last_address, worker_id) for worker_id in (1, 2)]
        outcomes = [future.result(timeout=15) for future in futures]

    assert sorted(outcome[0] for outcome in outcomes) == ["allocated", "exhausted"]
    assert [outcome[1] for outcome in outcomes if outcome[0] == "allocated"] == ["10.254.99.2"]

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT address FROM ip_addresses WHERE subnet_id = ? ORDER BY address",
            (prefix["id"],),
        ).fetchall()
    finally:
        conn.close()
    assert [str(row["address"]) for row in rows] == ["10.254.99.2"]


def test_external_pool_generation_and_allocation_do_not_claim_the_same_range_concurrently(
    isolated_db, monkeypatch,
) -> None:
    del isolated_db
    space = create_address_space(
        name=f"Concurrent Pool policy {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    original_get_db_connection = ipam_service.get_db_connection

    def get_connection_with_bounded_lock_wait():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '4s'")
        conn.execute("SET statement_timeout = '8s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", get_connection_with_bounded_lock_wait)

    # Repeat the same three-way race across five disjoint prefixes in one
    # address space. Each round still contends on the shared scope lock.
    for round_index in range(5):
        third_octet = 98 + round_index
        prefix_root = f"10.254.{third_octet}"
        prefix = create_subnet(
            prefix=f"{prefix_root}.0/24",
            address_space_id=space["id"],
            gateway=f"{prefix_root}.1",
            network_type="management",
            name=f"Pool/Allocation race prefix {round_index + 1}",
        )
        candidate_id = f"pool-generation-race-candidate-{round_index}"
        candidate = {
            "candidate_id": candidate_id,
            "prefix": f"{prefix_root}.0/25",
            "tenant_id": "tenant-default",
            "site_id": None,
            "address_space_id": space["id"],
            "vrf_id": None,
            "status": "to_create",
            "vrf_scope_pending": False,
            "vrf_scope_defaulted": False,
            "interfaces": [{
                "interface_id": None,
                "source_ref": f"synthetic-interface-pool-race-{round_index}",
                "device_id": "",
                "device_name": "SW-POOL-RACE",
                "interface_name": f"Vlan{98 + round_index}",
                "address": f"{prefix_root}.2",
            }],
        }

        def candidate_preview(_conn, **_kwargs):
            return {
                "source": "cmdb_interface_snapshot",
                "source_label": "current snapshot fixture",
                "candidate_count": 1,
                "existing_count": 0,
                "to_create_count": 1,
                "interface_count": 1,
                "scope_pending_count": 0,
                "vrf_pending_count": 0,
                "vrf_defaulted_count": 0,
                "skipped_count": 0,
                "candidates": [{**candidate, "interfaces": [dict(candidate["interfaces"][0])]}],
                "skipped": [],
                "skipped_truncated_count": 0,
            }

        monkeypatch.setattr(ipam_service, "_load_interface_prefix_candidates", candidate_preview)
        start_together = Barrier(3)

        def create_external_pool():
            start_together.wait(timeout=5)
            try:
                result = create_pool(
                    name=f"External DHCP race {uuid4().hex[:8]}",
                    prefix_id=prefix["id"],
                    start_ip=f"{prefix_root}.2",
                    end_ip=f"{prefix_root}.10",
                    management_mode="external_dhcp",
                    allocation_allowed=False,
                )
                return "created", result
            except ValueError as exc:
                if "active IP record" not in str(exc):
                    raise
                return "blocked", str(exc)

        def generate_from_interface():
            start_together.wait(timeout=5)
            return ipam_service.generate_interface_prefixes(candidate_ids=[candidate_id])

        def allocate_from_prefix():
            start_together.wait(timeout=5)
            result = allocate_next_address(prefix["id"], purpose="management")
            return str(result["address"])

        with ThreadPoolExecutor(max_workers=3) as executor:
            pool_future = executor.submit(create_external_pool)
            allocation_future = executor.submit(allocate_from_prefix)
            generation_future = executor.submit(generate_from_interface)
            pool_outcome = pool_future.result(timeout=20)
            allocated_address = allocation_future.result(timeout=20)
            generation_result = generation_future.result(timeout=20)

        conn = get_db_connection()
        try:
            pool_rows = conn.execute(
                "SELECT id FROM ipam_pools WHERE prefix_id = ?",
                (prefix["id"],),
            ).fetchall()
            address_rows = conn.execute(
                "SELECT address FROM ip_addresses WHERE address_space_id = ? ORDER BY address",
                (space["id"],),
            ).fetchall()
            generated_prefix = conn.execute(
                "SELECT id FROM prefixes WHERE prefix = ? AND address_space_id = ?",
                (f"{prefix_root}.0/25", space["id"]),
            ).fetchone()
        finally:
            conn.close()

        assert generation_result["ok"] is True
        assert generated_prefix
        occupied = {
            str(row["address"])
            for row in address_rows
            if str(row["address"]).startswith(f"{prefix_root}.")
        }
        if pool_rows:
            assert pool_outcome[0] == "created"
            assert allocated_address == f"{prefix_root}.11"
            assert occupied == {allocated_address}
        else:
            assert pool_outcome[0] == "blocked"
            assert f"{prefix_root}.2" in occupied
            assert allocated_address in {f"{prefix_root}.2", f"{prefix_root}.3"}
            assert not occupied.intersection({f"{prefix_root}.{value}" for value in range(4, 11)})


def test_pool_and_interface_generation_remain_exclusive_with_eight_concurrent_allocators(
    isolated_db, monkeypatch,
) -> None:
    del isolated_db
    space = create_address_space(
        name=f"Eight-worker IPAM race {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="198.18.100.0/28",
        address_space_id=space["id"],
        gateway="198.18.100.1",
        network_type="management",
        name="Eight-worker race parent",
    )
    candidate_id = "eight-worker-interface-candidate"
    candidate = {
        "candidate_id": candidate_id,
        "prefix": "198.18.100.0/29",
        "tenant_id": "tenant-default",
        "site_id": None,
        "address_space_id": space["id"],
        "vrf_id": None,
        "status": "to_create",
        "vrf_scope_pending": False,
        "vrf_scope_defaulted": False,
        "interfaces": [{
            "interface_id": None,
            "source_ref": "synthetic-eight-worker-interface",
            "device_id": "",
            "device_name": "SW-EIGHT-WORKER-RACE",
            "interface_name": "Vlan100",
            "address": "198.18.100.2",
        }],
    }

    def candidate_preview(_conn, **_kwargs):
        return {
            "source": "cmdb_interface_snapshot",
            "source_label": "current snapshot fixture",
            "candidate_count": 1,
            "existing_count": 0,
            "to_create_count": 1,
            "interface_count": 1,
            "scope_pending_count": 0,
            "vrf_pending_count": 0,
            "vrf_defaulted_count": 0,
            "skipped_count": 0,
            "candidates": [{**candidate, "interfaces": [dict(candidate["interfaces"][0])]}],
            "skipped": [],
            "skipped_truncated_count": 0,
        }

    original_get_db_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("SET statement_timeout = '10s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", bounded_connection)
    monkeypatch.setattr(ipam_service, "_load_interface_prefix_candidates", candidate_preview)
    start_together = Barrier(10)

    def allocate(worker_id: int) -> str:
        start_together.wait(timeout=8)
        result = allocate_next_address(
            prefix["id"],
            hostname=f"eight-worker-{worker_id}",
            purpose="management",
        )
        return str(result["address"])

    def create_external_pool():
        start_together.wait(timeout=8)
        try:
            result = create_pool(
                name=f"Eight-worker external pool {uuid4().hex[:8]}",
                prefix_id=prefix["id"],
                start_ip="198.18.100.2",
                end_ip="198.18.100.6",
                management_mode="external_dhcp",
                allocation_allowed=False,
            )
            return "created", result
        except ValueError as exc:
            if "active IP record" not in str(exc):
                raise
            return "blocked", str(exc)

    def generate_from_interface():
        start_together.wait(timeout=8)
        return ipam_service.generate_interface_prefixes(candidate_ids=[candidate_id])

    with ThreadPoolExecutor(max_workers=10) as executor:
        allocation_futures = [executor.submit(allocate, worker_id) for worker_id in range(8)]
        pool_future = executor.submit(create_external_pool)
        generation_future = executor.submit(generate_from_interface)
        allocated = [future.result(timeout=30) for future in allocation_futures]
        pool_outcome = pool_future.result(timeout=30)
        generation_result = generation_future.result(timeout=30)

    with get_db_connection() as conn:
        pool_rows = conn.execute(
            "SELECT id FROM ipam_pools WHERE prefix_id = ?",
            (prefix["id"],),
        ).fetchall()
        address_rows = conn.execute(
            "SELECT address FROM ip_addresses WHERE address_space_id = ? ORDER BY address",
            (space["id"],),
        ).fetchall()
        generated_prefix = conn.execute(
            "SELECT id FROM prefixes WHERE prefix = '198.18.100.0/29' AND address_space_id = ?",
            (space["id"],),
        ).fetchone()

    assert generation_result["ok"] is True
    assert generated_prefix
    assert len(allocated) == len(set(allocated)) == 8
    persisted_addresses = {str(row["address"]) for row in address_rows}
    assert set(allocated) <= persisted_addresses
    assert len(persisted_addresses) in {8, 9}
    if pool_rows:
        assert pool_outcome[0] == "created"
        assert not persisted_addresses.intersection(
            {f"198.18.100.{value}" for value in range(2, 7)}
        )
    else:
        assert pool_outcome[0] == "blocked"


def test_sixteen_concurrent_allocators_claim_unique_addresses_for_three_rounds(
    isolated_db, monkeypatch,
) -> None:
    del isolated_db
    worker_count = 16
    rounds = 3
    space = create_address_space(
        name=f"Sixteen-worker IPAM race {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="198.18.101.0/24",
        address_space_id=space["id"],
        gateway="198.18.101.1",
        network_type="management",
        name="Sixteen-worker allocator parent",
    )

    original_get_db_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("SET statement_timeout = '10s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", bounded_connection)
    allocated: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for round_number in range(rounds):
            start_together = Barrier(worker_count)

            def allocate(worker_id: int) -> str:
                start_together.wait(timeout=8)
                result = allocate_next_address(
                    prefix["id"],
                    hostname=f"sixteen-worker-r{round_number}-{worker_id}",
                    purpose="management",
                )
                return str(result["address"])

            futures = [
                executor.submit(allocate, worker_id)
                for worker_id in range(worker_count)
            ]
            allocated.extend(future.result(timeout=60) for future in futures)

    expected = {f"198.18.101.{host}" for host in range(2, 2 + worker_count * rounds)}
    assert len(allocated) == worker_count * rounds
    assert len(set(allocated)) == worker_count * rounds
    assert set(allocated) == expected


def test_thirty_two_concurrent_allocators_claim_unique_addresses_for_five_rounds(
    isolated_db, monkeypatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    del isolated_db
    worker_count = 32
    rounds = 5
    space = create_address_space(
        name=f"Thirty-two-worker IPAM race {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="198.18.103.0/24",
        address_space_id=space["id"],
        gateway="198.18.103.1",
        network_type="management",
        name="Thirty-two-worker allocator parent",
    )

    original_get_db_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '20s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", bounded_connection)
    allocated: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for round_number in range(rounds):
            start_together = Barrier(worker_count)

            def allocate(worker_id: int) -> str:
                start_together.wait(timeout=10)
                result = allocate_next_address(
                    prefix["id"],
                    hostname=f"thirty-two-worker-r{round_number}-{worker_id}",
                    purpose="management",
                )
                return str(result["address"])

            futures = [
                executor.submit(allocate, worker_id)
                for worker_id in range(worker_count)
            ]
            allocated.extend(future.result(timeout=90) for future in futures)

    expected = {
        f"198.18.103.{host}"
        for host in range(2, 2 + worker_count * rounds)
    }
    assert len(allocated) == worker_count * rounds
    assert len(set(allocated)) == worker_count * rounds
    assert set(allocated) == expected
    with get_db_connection() as conn:
        persisted_count = conn.execute(
            "SELECT COUNT(*) FROM ip_addresses WHERE subnet_id = ?",
            (prefix["id"],),
        ).fetchone()[0]
    assert persisted_count == worker_count * rounds

@pytest.mark.parametrize(
    "worker_count", [16, 32], ids=["16-workers", "32-workers"],
)
def test_concurrent_allocators_compete_with_pool_creation_and_interface_generation(
    isolated_db, monkeypatch, worker_count: int,
) -> None:
    del isolated_db
    participants = worker_count + 2
    space = create_address_space(
        name=f"{worker_count}-worker mixed IPAM race {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="198.18.102.0/26",
        address_space_id=space["id"],
        gateway="198.18.102.1",
        network_type="management",
        name=f"{worker_count}-worker mixed parent",
    )
    candidate_id = f"{worker_count}-worker-interface-candidate"
    candidate = {
        "candidate_id": candidate_id,
        "prefix": "198.18.102.0/27",
        "tenant_id": "tenant-default",
        "site_id": None,
        "address_space_id": space["id"],
        "vrf_id": None,
        "status": "to_create",
        "vrf_scope_pending": False,
        "vrf_scope_defaulted": False,
        "interfaces": [{
            "interface_id": None,
            "source_ref": f"synthetic-{worker_count}-worker-interface",
            "device_id": "",
            "device_name": f"SW-{worker_count}-WORKER-RACE",
            "interface_name": "Vlan102",
            "address": "198.18.102.20",
        }],
    }

    def candidate_preview(_conn, **_kwargs):
        return {
            "source": "cmdb_interface_snapshot",
            "source_label": "current snapshot fixture",
            "candidate_count": 1,
            "existing_count": 0,
            "to_create_count": 1,
            "interface_count": 1,
            "scope_pending_count": 0,
            "vrf_pending_count": 0,
            "vrf_defaulted_count": 0,
            "skipped_count": 0,
            "candidates": [{**candidate, "interfaces": [dict(candidate["interfaces"][0])]}],
            "skipped": [],
            "skipped_truncated_count": 0,
        }

    original_get_db_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '20s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", bounded_connection)
    monkeypatch.setattr(ipam_service, "_load_interface_prefix_candidates", candidate_preview)
    start_together = Barrier(participants)

    def allocate(worker_id: int) -> str:
        start_together.wait(timeout=10)
        result = allocate_next_address(
            prefix["id"],
            hostname=f"{worker_count}-mixed-worker-{worker_id}",
            purpose="management",
        )
        return str(result["address"])

    def create_external_pool():
        start_together.wait(timeout=10)
        try:
            result = create_pool(
                name=f"{worker_count}-worker external pool {uuid4().hex[:8]}",
                prefix_id=prefix["id"],
                start_ip="198.18.102.2",
                end_ip="198.18.102.10",
                management_mode="external_dhcp",
                allocation_allowed=False,
            )
            return "created", result
        except ValueError as exc:
            if "active IP record" not in str(exc):
                raise
            return "blocked", str(exc)

    def generate_from_interface():
        start_together.wait(timeout=10)
        return ipam_service.generate_interface_prefixes(candidate_ids=[candidate_id])

    with ThreadPoolExecutor(max_workers=participants) as executor:
        allocation_futures = [
            executor.submit(allocate, worker_id) for worker_id in range(worker_count)
        ]
        pool_future = executor.submit(create_external_pool)
        generation_future = executor.submit(generate_from_interface)
        allocated = [future.result(timeout=90) for future in allocation_futures]
        pool_outcome = pool_future.result(timeout=90)
        generation_result = generation_future.result(timeout=90)

    with get_db_connection() as conn:
        pool_rows = conn.execute(
            "SELECT id FROM ipam_pools WHERE prefix_id = ?", (prefix["id"],),
        ).fetchall()
        address_rows = conn.execute(
            "SELECT address FROM ip_addresses WHERE address_space_id = ? ORDER BY address",
            (space["id"],),
        ).fetchall()
        generated_prefix = conn.execute(
            "SELECT id FROM prefixes WHERE prefix = '198.18.102.0/27' AND address_space_id = ?",
            (space["id"],),
        ).fetchone()

    assert generation_result["ok"] is True
    assert generated_prefix
    assert len(allocated) == len(set(allocated)) == worker_count
    persisted_addresses = {str(row["address"]) for row in address_rows}
    assert set(allocated) <= persisted_addresses
    assert len(persisted_addresses) in {worker_count, worker_count + 1}
    if pool_rows:
        assert pool_outcome[0] == "created"
        assert not persisted_addresses.intersection(
            {f"198.18.102.{value}" for value in range(2, 11)}
        )
    else:
        assert pool_outcome[0] == "blocked"
        assert "198.18.102.2" in persisted_addresses




def test_thirty_two_mixed_pool_interface_allocators_compete_for_ten_rounds(
    isolated_db, monkeypatch,
) -> None:
    del isolated_db
    worker_count = 32
    rounds = 10
    participants = worker_count + 2
    space = create_address_space(
        name=f"Thirty-two mixed IPAM rounds {uuid4().hex}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    original_get_db_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_db_connection()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '20s'")
        return conn

    monkeypatch.setattr(ipam_service, "get_db_connection", bounded_connection)
    current_candidate: dict[str, dict] = {}

    def candidate_preview(_conn, **_kwargs):
        candidate = current_candidate["candidate"]
        return {
            "source": "cmdb_interface_snapshot",
            "source_label": "current snapshot fixture",
            "candidate_count": 1,
            "existing_count": 0,
            "to_create_count": 1,
            "interface_count": 1,
            "scope_pending_count": 0,
            "vrf_pending_count": 0,
            "vrf_defaulted_count": 0,
            "skipped_count": 0,
            "candidates": [{**candidate, "interfaces": [dict(candidate["interfaces"][0])]}],
            "skipped": [],
            "skipped_truncated_count": 0,
        }

    monkeypatch.setattr(ipam_service, "_load_interface_prefix_candidates", candidate_preview)
    all_allocated: list[str] = []

    with ThreadPoolExecutor(max_workers=participants) as executor:
        for round_number in range(rounds):
            third_octet = 160 + round_number * 2
            parent_prefix = f"198.18.{third_octet}.0/25"
            interface_prefix = f"198.18.{third_octet}.64/26"
            interface_address = f"198.18.{third_octet}.120"
            prefix = create_subnet(
                prefix=parent_prefix,
                address_space_id=space["id"],
                gateway=f"198.18.{third_octet}.1",
                network_type="management",
                name=f"32-worker mixed round {round_number} parent",
            )
            candidate_id = f"thirty-two-mixed-round-{round_number}"
            current_candidate["candidate"] = {
                "candidate_id": candidate_id,
                "prefix": interface_prefix,
                "tenant_id": "tenant-default",
                "site_id": None,
                "address_space_id": space["id"],
                "vrf_id": None,
                "status": "to_create",
                "vrf_scope_pending": False,
                "vrf_scope_defaulted": False,
                "interfaces": [{
                    "interface_id": None,
                    "source_ref": f"synthetic-32-worker-round-{round_number}",
                    "device_id": "",
                    "device_name": f"SW-32-WORKER-ROUND-{round_number}",
                    "interface_name": f"Vlan{160 + round_number * 2}",
                    "address": interface_address,
                }],
            }
            start_together = Barrier(participants)

            def allocate(worker_id: int) -> str:
                start_together.wait(timeout=10)
                result = allocate_next_address(
                    prefix["id"],
                    hostname=f"mixed-r{round_number}-worker-{worker_id}",
                    purpose="management",
                )
                return str(result["address"])

            def create_external_pool():
                start_together.wait(timeout=10)
                try:
                    result = create_pool(
                        name=f"32-worker mixed pool r{round_number} {uuid4().hex[:8]}",
                        prefix_id=prefix["id"],
                        start_ip=f"198.18.{third_octet}.2",
                        end_ip=f"198.18.{third_octet}.10",
                        management_mode="external_dhcp",
                        allocation_allowed=False,
                    )
                    return "created", result
                except ValueError as exc:
                    if "active IP record" not in str(exc):
                        raise
                    return "blocked", str(exc)

            def generate_from_interface():
                start_together.wait(timeout=10)
                return ipam_service.generate_interface_prefixes(candidate_ids=[candidate_id])

            allocation_futures = [
                executor.submit(allocate, worker_id) for worker_id in range(worker_count)
            ]
            pool_future = executor.submit(create_external_pool)
            generation_future = executor.submit(generate_from_interface)
            allocated = [future.result(timeout=90) for future in allocation_futures]
            pool_outcome = pool_future.result(timeout=90)
            generation_result = generation_future.result(timeout=90)
            all_allocated.extend(allocated)

            with get_db_connection() as conn:
                pool_rows = conn.execute(
                    "SELECT id FROM ipam_pools WHERE prefix_id = ?",
                    (prefix["id"],),
                ).fetchall()
                address_rows = conn.execute(
                    "SELECT address, subnet_id FROM ip_addresses WHERE address_space_id = ? ORDER BY address",
                    (space["id"],),
                ).fetchall()
                generated_prefix = conn.execute(
                    "SELECT id, prefix_cidr FROM prefixes WHERE prefix = ? AND address_space_id = ?",
                    (interface_prefix, space["id"]),
                ).fetchone()
                generated_address_rows = conn.execute(
                    "SELECT address, subnet_id FROM ip_addresses WHERE address_space_id = ? AND address = ?",
                    (space["id"], interface_address),
                ).fetchall()

            round_prefix = f"198.18.{third_octet}."
            round_rows = [
                row for row in address_rows
                if str(row["address"]).startswith(round_prefix)
            ]
            persisted_addresses = {str(row["address"]) for row in round_rows}
            pool_range = {f"198.18.{third_octet}.{value}" for value in range(2, 11)}
            assert generation_result["ok"] is True
            assert generation_result["created_prefixes"] == 1
            assert generation_result["created_addresses"] == 1
            assert generation_result["skipped_addresses"] == []
            assert generated_prefix
            assert str(generated_prefix["prefix_cidr"]) == interface_prefix
            assert len(generated_address_rows) == 1
            assert str(generated_address_rows[0]["subnet_id"]) == str(generated_prefix["id"])
            assert len(allocated) == len(set(allocated)) == worker_count
            assert set(allocated) <= persisted_addresses
            assert interface_address in persisted_addresses
            assert len(persisted_addresses) == worker_count + 1
            assert len(persisted_addresses) == len(round_rows)
            if pool_rows:
                assert pool_outcome[0] == "created"
                assert not persisted_addresses.intersection(pool_range)
            else:
                assert pool_outcome[0] == "blocked"
                assert persisted_addresses.intersection(pool_range)

    assert len(all_allocated) == worker_count * rounds
    assert len(set(all_allocated)) == worker_count * rounds
    with get_db_connection() as conn:
        persisted_total = conn.execute(
            "SELECT COUNT(*) FROM ip_addresses WHERE address_space_id = ?",
            (space["id"],),
        ).fetchone()[0]
    assert persisted_total == (worker_count + 1) * rounds
