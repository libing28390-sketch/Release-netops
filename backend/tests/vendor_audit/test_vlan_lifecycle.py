from __future__ import annotations

import pytest

from database import get_db_connection
from services.cmdb_service import delete_vlan
from services.vlan_discovery_service import sync_observed_vlans


_OBSERVED_AT = "2026-10-28T01:00:00+00:00"


def _insert_site(conn, site_id: str) -> None:
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
           VALUES (?, ?, ?, 'active', 'tenant-default')""",
        (site_id, site_id.upper(), site_id,),
    )


def _insert_device(conn, device_id: str, site_id: str) -> None:
    conn.execute(
        """INSERT INTO devices (id, hostname, status, site_id, site)
           VALUES (?, ?, 'online', ?, ?)""",
        (device_id, device_id, site_id, site_id),
    )


def _insert_prefix(
    conn,
    prefix_id: str,
    site_id: str,
    vlan_pk: str,
    *,
    manual_override: int = 0,
    cidr: str = "10.40.0.0/24",
) -> None:
    conn.execute(
        """INSERT INTO prefixes
           (id, prefix, prefix_cidr, site_id, tenant_id, vlan_id, manual_override)
           VALUES (?, ?, ?::cidr, ?, 'tenant-default', ?, ?)""",
        (prefix_id, cidr, cidr, site_id, vlan_pk, manual_override),
    )


def test_sync_prunes_stale_auto_vlan_and_keeps_prefix_record(isolated_db):
    conn = get_db_connection()
    try:
        site_id = "vlan-lifecycle-prune-site"
        _insert_site(conn, site_id)
        _insert_device(conn, "vlan-lifecycle-prune-device", site_id)
        conn.execute(
            """INSERT INTO interfaces
               (id, device_id, interface_name, access_vlan, last_seen)
               VALUES (?, ?, ?, ?, ?)""",
            ("vlan-lifecycle-prune-interface", "vlan-lifecycle-prune-device", "GE0/0/1", 40, _OBSERVED_AT),
        )
        conn.commit()

        result = sync_observed_vlans(conn=conn, site_scope=site_id)
        assert result["created"] == 1
        vlan = conn.execute(
            "SELECT id, discovery_source FROM vlans WHERE site_id = ? AND vlan_id = 40",
            (site_id,),
        ).fetchone()
        assert vlan["discovery_source"] == "interface_vlan"
        _insert_prefix(conn, "vlan-lifecycle-prune-prefix", site_id, vlan["id"])

        conn.execute("DELETE FROM interfaces WHERE id = ?", ("vlan-lifecycle-prune-interface",))
        result = sync_observed_vlans(conn=conn, site_scope=site_id)

        assert result["deleted"] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM vlans WHERE id = ?", (vlan["id"],),
        ).fetchone()[0] == 0
        prefix = conn.execute(
            "SELECT id, prefix, vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-prune-prefix",),
        ).fetchone()
        assert tuple(prefix) == ("vlan-lifecycle-prune-prefix", "10.40.0.0/24", None)
    finally:
        conn.close()


def test_sync_preserves_manual_vlan_and_auto_rows_with_manual_references(isolated_db):
    conn = get_db_connection()
    try:
        site_id = "vlan-lifecycle-blocker-site"
        _insert_site(conn, site_id)
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-auto", 41, "auto", site_id, "interface_vlan"),
        )
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-override", 42, "override", site_id, "interface_svi"),
        )
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-bound", 43, "bound", site_id, "arp_table"),
        )
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-manual", 44, "manual", site_id, "manual"),
        )
        _insert_prefix(conn, "vlan-lifecycle-override-prefix", site_id, "vlan-lifecycle-override", manual_override=1)
        conn.execute(
            """INSERT INTO vlan_business_bindings
               (id, site_id, vrf_id, vlan_id, business_system, created_at, updated_at)
               VALUES (?, ?, '', ?, ?, ?, ?)""",
            ("vlan-lifecycle-binding", site_id, 43, "Finance", _OBSERVED_AT, _OBSERVED_AT),
        )
        conn.commit()

        result = sync_observed_vlans(conn=conn, site_scope=site_id)

        assert result["deleted"] == 1
        remaining = {
            row["id"] for row in conn.execute(
                "SELECT id FROM vlans WHERE site_id = ?", (site_id,),
            ).fetchall()
        }
        assert remaining == {
            "vlan-lifecycle-override",
            "vlan-lifecycle-bound",
            "vlan-lifecycle-manual",
        }
        assert conn.execute(
            "SELECT vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-override-prefix",),
        ).fetchone()[0] == "vlan-lifecycle-override"
        assert conn.execute(
            "SELECT COUNT(*) FROM vlan_business_bindings WHERE id = ?",
            ("vlan-lifecycle-binding",),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_delete_device_cascades_cli_snapshots_and_prunes_only_after_last_source(isolated_db, monkeypatch):
    from api import devices
    from services import collector_sync_service

    monkeypatch.setattr(collector_sync_service, "trigger_async_monitoring_sync", lambda: None)
    conn = get_db_connection()
    try:
        site_id = "vlan-lifecycle-device-site"
        _insert_site(conn, site_id)
        _insert_device(conn, "vlan-lifecycle-device-a", site_id)
        _insert_device(conn, "vlan-lifecycle-device-b", site_id)
        conn.execute(
            """INSERT INTO interfaces
               (id, device_id, interface_name, access_vlan, last_seen)
               VALUES (?, ?, ?, ?, ?)""",
            ("vlan-lifecycle-interface-b", "vlan-lifecycle-device-b", "GE0/0/2", 45, _OBSERVED_AT),
        )
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-device-vlan", 45, "observed", site_id, "cli_vlan"),
        )
        _insert_prefix(conn, "vlan-lifecycle-device-prefix", site_id, "vlan-lifecycle-device-vlan")
        conn.execute(
            """INSERT INTO cmdb_collection_snapshots
               (device_id, domain, attempt_generation, successful_generation,
                attempt_status, observed_at)
               VALUES (?, 'vlan_inventory', 1, 1, 'success', ?)""",
            ("vlan-lifecycle-device-a", _OBSERVED_AT),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations
               (device_id, vlan_id, site_id, vlan_name, generation, observed_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            ("vlan-lifecycle-device-a", 45, site_id, "USERS", _OBSERVED_AT),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_port_observations
               (device_id, vlan_id, normalized_interface_name, interface_name,
                generation, observed_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            ("vlan-lifecycle-device-a", 45, "ge0/0/1", "GE0/0/1", _OBSERVED_AT),
        )
        conn.commit()
    finally:
        conn.close()

    assert devices.delete_device("vlan-lifecycle-device-a")["status"] == "success"

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_collection_snapshots WHERE device_id = ?",
            ("vlan-lifecycle-device-a",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_observations WHERE device_id = ?",
            ("vlan-lifecycle-device-a",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_port_observations WHERE device_id = ?",
            ("vlan-lifecycle-device-a",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM vlans WHERE id = ?",
            ("vlan-lifecycle-device-vlan",),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-device-prefix",),
        ).fetchone()[0] == "vlan-lifecycle-device-vlan"
    finally:
        conn.close()

    assert devices.delete_device("vlan-lifecycle-device-b")["status"] == "success"

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM vlans WHERE id = ?",
            ("vlan-lifecycle-device-vlan",),
        ).fetchone()[0] == 0
        prefix = conn.execute(
            "SELECT id, prefix, vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-device-prefix",),
        ).fetchone()
        assert tuple(prefix) == ("vlan-lifecycle-device-prefix", "10.40.0.0/24", None)
    finally:
        conn.close()


def test_delete_vlan_detaches_only_automatic_prefix_link_and_honors_blockers(isolated_db):
    conn = get_db_connection()
    try:
        site_id = "vlan-lifecycle-delete-site"
        _insert_site(conn, site_id)
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-delete-auto", 46, "stale", site_id, "interface_vlan"),
        )
        _insert_prefix(conn, "vlan-lifecycle-delete-prefix", site_id, "vlan-lifecycle-delete-auto")
        conn.commit()

        delete_vlan(conn, "vlan-lifecycle-delete-auto")
        prefix = conn.execute(
            "SELECT id, prefix, vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-delete-prefix",),
        ).fetchone()
        assert tuple(prefix) == ("vlan-lifecycle-delete-prefix", "10.40.0.0/24", None)

        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-delete-override", 47, "override", site_id, "interface_svi"),
        )
        _insert_prefix(
            conn, "vlan-lifecycle-delete-manual-prefix", site_id,
            "vlan-lifecycle-delete-override", manual_override=1, cidr="10.41.0.0/24",
        )
        with pytest.raises(ValueError, match="manual override"):
            delete_vlan(conn, "vlan-lifecycle-delete-override")
        assert conn.execute(
            "SELECT vlan_id FROM prefixes WHERE id = ?",
            ("vlan-lifecycle-delete-manual-prefix",),
        ).fetchone()[0] == "vlan-lifecycle-delete-override"

        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-delete-bound", 48, "bound", site_id, "arp_table"),
        )
        conn.execute(
            """INSERT INTO vlan_business_bindings
               (id, site_id, vrf_id, vlan_id, business_system, created_at, updated_at)
               VALUES (?, ?, '', ?, ?, ?, ?)""",
            ("vlan-lifecycle-delete-binding", site_id, 48, "HR", _OBSERVED_AT, _OBSERVED_AT),
        )
        with pytest.raises(ValueError, match="vlan_business_bindings"):
            delete_vlan(conn, "vlan-lifecycle-delete-bound")
        assert conn.execute(
            "SELECT COUNT(*) FROM vlans WHERE id = ?",
            ("vlan-lifecycle-delete-bound",),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_delete_vlan_rejects_current_cli_snapshot_source(isolated_db):
    conn = get_db_connection()
    try:
        site_id = "vlan-lifecycle-cli-site"
        _insert_site(conn, site_id)
        _insert_device(conn, "vlan-lifecycle-cli-device", site_id)
        conn.execute(
            """INSERT INTO vlans
               (id, vlan_id, name, site_id, tenant_id, discovery_source)
               VALUES (?, ?, ?, ?, 'tenant-default', ?)""",
            ("vlan-lifecycle-cli-row", 49, "cli", site_id, "cli_vlan"),
        )
        conn.execute(
            """INSERT INTO cmdb_collection_snapshots
               (device_id, domain, attempt_generation, successful_generation, attempt_status)
               VALUES (?, 'vlan_inventory', 1, 1, 'success')""",
            ("vlan-lifecycle-cli-device",),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations
               (device_id, vlan_id, site_id, vlan_name, generation, observed_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            ("vlan-lifecycle-cli-device", 49, site_id, "CLI-49", _OBSERVED_AT),
        )
        result = sync_observed_vlans(conn=conn, site_scope=site_id)
        assert result["deleted"] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM vlans WHERE id = ?",
            ("vlan-lifecycle-cli-row",),
        ).fetchone()[0] == 1
        with pytest.raises(ValueError, match="active device observations"):
            delete_vlan(conn, "vlan-lifecycle-cli-row")
    finally:
        conn.close()
