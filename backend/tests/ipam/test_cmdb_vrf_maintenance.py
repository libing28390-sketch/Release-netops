from __future__ import annotations

import uuid
import threading
import time

import pytest

from database import get_db_connection
from services.cmdb_service import create_vrf, delete_vrf, update_vrf
from services.ipam_address_space_service import create_address_space


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _create_vrf(name: str | None = None) -> dict:
    conn = get_db_connection()
    try:
        return create_vrf(
            conn,
            vrf_name=name or _id('vrf-maintenance'),
            tenant_id='tenant-default',
        )
    finally:
        conn.close()


def _prefix(
    conn,
    *,
    prefix_id: str,
    vrf_id: str | None,
    address_space_id: str | None,
    cidr: str = '10.247.0.0/24',
) -> None:
    conn.execute(
        """INSERT INTO prefixes
               (id, prefix, prefix_cidr, vrf_id, address_space_id,
                tenant_id, status, name, created_at, updated_at)
           VALUES (?, ?, ?::cidr, ?, ?, 'tenant-default', 'active', ?, 'now', 'now')""",
        (
            prefix_id,
            cidr,
            cidr,
            vrf_id,
            address_space_id,
            prefix_id,
        ),
    )


def test_rename_vrf_updates_canonical_address_space_in_same_transaction(isolated_db) -> None:
    vrf = _create_vrf()
    renamed = _id('renamed-vrf')
    conn = get_db_connection()
    try:
        before = conn.execute(
            "SELECT id, name, revision FROM ipam_address_spaces WHERE vrf_id = ?",
            (vrf['id'],),
        ).fetchone()

        result = update_vrf(conn, vrf['id'], vrf_name=renamed)

        after = conn.execute(
            "SELECT id, name, revision FROM ipam_address_spaces WHERE vrf_id = ?",
            (vrf['id'],),
        ).fetchone()
        assert result['vrf_name'] == renamed
        assert after['id'] == before['id']
        assert after['name'] == renamed
        assert after['revision'] == before['revision'] + 1
    finally:
        conn.close()


def test_rename_vrf_collision_rolls_back_vrf_and_address_space(isolated_db) -> None:
    vrf = _create_vrf()
    collision_name = _id('existing-space')
    create_address_space(
        name=collision_name,
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    conn = get_db_connection()
    try:
        with pytest.raises(ValueError, match='IPAM address-space name already exists'):
            update_vrf(conn, vrf['id'], vrf_name=collision_name)

        stored_vrf = conn.execute(
            "SELECT vrf_name FROM vrfs WHERE id = ?",
            (vrf['id'],),
        ).fetchone()
        stored_space = conn.execute(
            "SELECT name FROM ipam_address_spaces WHERE vrf_id = ?",
            (vrf['id'],),
        ).fetchone()
        assert stored_vrf['vrf_name'] == vrf['vrf_name']
        assert stored_space['name'] == vrf['vrf_name']
    finally:
        conn.close()


def test_delete_vrf_removes_its_unreferenced_canonical_address_space(isolated_db) -> None:
    vrf = _create_vrf()
    conn = get_db_connection()
    try:
        delete_vrf(conn, vrf['id'])
        assert conn.execute("SELECT 1 FROM vrfs WHERE id = ?", (vrf['id'],)).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM ipam_address_spaces WHERE vrf_id = ?",
            (vrf['id'],),
        ).fetchone() is None
    finally:
        conn.close()


def test_delete_vrf_rejects_prefix_ip_pool_vip_context_and_fhrp_references(isolated_db) -> None:
    vrf = _create_vrf()
    space_id = f"as-vrf:{vrf['id']}"
    prefix_id = _id('vrf-blocker-prefix')
    device_id = _id('vrf-blocker-device')
    now = '2026-01-01T00:00:00+00:00'
    conn = get_db_connection()
    try:
        _prefix(
            conn,
            prefix_id=prefix_id,
            vrf_id=vrf['id'],
            address_space_id=space_id,
        )
        conn.execute(
            """INSERT INTO ip_addresses
                   (id, subnet_id, address, address_inet, vrf_id, address_space_id,
                    created_at, updated_at)
               VALUES (?, ?, '10.247.0.10', '10.247.0.10'::inet, ?, ?, ?, ?)""",
            (_id('vrf-blocker-ip'), prefix_id, vrf['id'], space_id, now, now),
        )
        conn.execute(
            """INSERT INTO ipam_pools
                   (id, name, prefix_id, address_space_id, start_ip, end_ip,
                    tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, '10.247.0.20', '10.247.0.30',
                       'tenant-default', ?, ?)""",
            (_id('vrf-blocker-pool'), 'VRF maintenance pool', prefix_id, space_id, now, now),
        )
        conn.execute(
            """INSERT INTO ipam_vips
                   (id, address, address_inet, prefix_id, address_space_id,
                    vip_type, tenant_id, created_at, updated_at)
               VALUES (?, '10.247.0.40', '10.247.0.40'::inet, ?, ?,
                       'virtual', 'tenant-default', ?, ?)""",
            (_id('vrf-blocker-vip'), prefix_id, space_id, now, now),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id)
               VALUES (?, ?, '192.0.2.40', 'cisco_ios', 'online', 'tenant-default')""",
            (device_id, device_id),
        )
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id, status, revision,
                    created_at, updated_at)
               VALUES (?, ?, 'cli', 'vrf', 'tenant-vrf', 'Tenant VRF', ?,
                       'active', 1, ?, ?)""",
            (_id('vrf-blocker-context'), device_id, space_id, now, now),
        )
        conn.execute(
            """INSERT INTO ipam_fhrp_groups
                   (id, security_tenant_id, address_space_id, group_type, protocol,
                    group_id, address_family, display_name, status, revision,
                    created_at, updated_at)
               VALUES (?, 'tenant-default', ?, 'fhrp', 'vrrp', '40', 4,
                       'VRF gateway', 'active', 1, ?, ?)""",
            (_id('vrf-blocker-fhrp'), space_id, now, now),
        )
        conn.commit()

        with pytest.raises(ValueError, match='resources or contexts still reference it') as error:
            delete_vrf(conn, vrf['id'])

        message = str(error.value)
        for reference in (
            'prefixes.vrf_id',
            'prefixes.address_space_id',
            'ip_addresses.address_space_id',
            'ipam_pools.address_space_id',
            'ipam_vips.address_space_id',
            'ipam_device_routing_contexts.address_space_id',
            'ipam_fhrp_groups.address_space_id',
        ):
            assert reference in message
        assert conn.execute("SELECT 1 FROM vrfs WHERE id = ?", (vrf['id'],)).fetchone() is not None
        assert conn.execute(
            "SELECT 1 FROM ipam_address_spaces WHERE id = ?",
            (space_id,),
        ).fetchone() is not None
    finally:
        conn.close()


def test_delete_vrf_rejects_legacy_ip_vrf_reference_without_a_foreign_key(isolated_db) -> None:
    vrf = _create_vrf()
    prefix_id = _id('legacy-unscoped-prefix')
    conn = get_db_connection()
    try:
        _prefix(
            conn,
            prefix_id=prefix_id,
            vrf_id=None,
            address_space_id=None,
            cidr='10.246.0.0/24',
        )
        conn.execute(
            """INSERT INTO ip_addresses
                   (id, subnet_id, address, address_inet, vrf_id, created_at, updated_at)
               VALUES (?, ?, '10.246.0.10', '10.246.0.10'::inet, ?, 'now', 'now')""",
            (_id('legacy-vrf-ip'), prefix_id, vrf['id']),
        )
        conn.commit()

        with pytest.raises(ValueError, match='ip_addresses.vrf_id'):
            delete_vrf(conn, vrf['id'])

        assert conn.execute("SELECT 1 FROM vrfs WHERE id = ?", (vrf['id'],)).fetchone() is not None
    finally:
        conn.close()


def test_delete_vrf_waits_for_concurrent_fk_insert_and_then_sees_reference(isolated_db) -> None:
    vrf = _create_vrf()
    writer = get_db_connection()
    prefix_id = _id('concurrent-vrf-prefix')
    _prefix(
        writer,
        prefix_id=prefix_id,
        vrf_id=vrf['id'],
        address_space_id=f"as-vrf:{vrf['id']}",
    )

    delete_started = threading.Event()
    delete_finished = threading.Event()
    worker_pid: dict[str, int] = {}
    worker_result: dict[str, Exception | None] = {'error': None}

    def _delete_in_worker() -> None:
        worker = get_db_connection()
        try:
            worker_pid['pid'] = int(worker.execute('SELECT pg_backend_pid()').fetchone()[0])
            delete_started.set()
            delete_vrf(worker, vrf['id'])
        except Exception as exc:  # returned to the test thread for assertions
            worker_result['error'] = exc
        finally:
            worker.close()
            delete_finished.set()

    worker_thread = threading.Thread(target=_delete_in_worker, daemon=True)
    worker_thread.start()
    try:
        assert delete_started.wait(timeout=2)
        deadline = time.monotonic() + 1.5
        waiting_for_lock = False
        while time.monotonic() < deadline:
            activity = writer.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = ?",
                (worker_pid['pid'],),
            ).fetchone()
            if activity and activity['wait_event_type'] == 'Lock':
                waiting_for_lock = True
                break
            time.sleep(0.01)
        assert waiting_for_lock, 'VRF deletion did not wait for the pending FK reference'

        writer.commit()
        assert delete_finished.wait(timeout=3)
        worker_thread.join(timeout=1)
        assert isinstance(worker_result['error'], ValueError)
        assert 'prefixes.address_space_id' in str(worker_result['error'])
        assert writer.execute("SELECT 1 FROM vrfs WHERE id = ?", (vrf['id'],)).fetchone() is not None
    finally:
        writer.rollback()
        writer.close()
        if worker_thread.is_alive():
            worker_thread.join(timeout=3)


def test_delete_vrf_retains_historical_discovery_evidence(isolated_db) -> None:
    vrf = _create_vrf()
    snapshot_id = _id('historical-vrf-snapshot')
    observation_id = _id('historical-vrf-observation')
    now = '2026-01-01T00:00:00+00:00'
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO ipam_discovery_snapshots
                   (id, collector, device_id, tenant_id, vrf_id, source_version,
                    projected_at)
               VALUES (?, 'test', 'historical-device', 'tenant-default', ?, 'v1', ?)""",
            (snapshot_id, vrf['id'], now),
        )
        conn.execute(
            """INSERT INTO ipam_discovery_observations
                   (id, snapshot_id, source_type, source_device_id, tenant_id,
                    vrf_id, source_identity_key, projected_at)
               VALUES (?, ?, 'arp', 'historical-device', 'tenant-default', ?, ?, ?)""",
            (observation_id, snapshot_id, vrf['id'], observation_id, now),
        )
        conn.commit()

        delete_vrf(conn, vrf['id'])

        snapshot = conn.execute(
            "SELECT vrf_id FROM ipam_discovery_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        observation = conn.execute(
            "SELECT vrf_id FROM ipam_discovery_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        assert snapshot['vrf_id'] == vrf['id']
        assert observation['vrf_id'] == vrf['id']
    finally:
        conn.close()
