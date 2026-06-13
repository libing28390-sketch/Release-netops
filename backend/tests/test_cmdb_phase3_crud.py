"""
CMDB Phase 3 — core entity CRUD (tenants / sites / vrfs / vlans).

Validates the new cmdb_service layer: create/list/update/delete, uniqueness
constraints, VLAN range/scoping rules, and referential-integrity guards.
"""

import pytest

from database import get_db_connection
from services import cmdb_service


def test_tenant_crud_and_default_protected(isolated_db):
    conn = get_db_connection()
    try:
        t = cmdb_service.create_tenant(conn, name="Acme Corp", description="test")
        assert t["name"] == "Acme Corp"

        # duplicate name rejected
        with pytest.raises(ValueError):
            cmdb_service.create_tenant(conn, name="Acme Corp")

        cmdb_service.update_tenant(conn, t["id"], description="updated")
        assert cmdb_service.get_tenant(conn, t["id"])["description"] == "updated"

        # default tenant (seeded) cannot be deleted
        with pytest.raises(ValueError):
            cmdb_service.delete_tenant(conn, "tenant-default")

        cmdb_service.delete_tenant(conn, t["id"])
        with pytest.raises(ValueError):
            cmdb_service.get_tenant(conn, t["id"])
    finally:
        conn.close()


def test_site_crud_and_unique_code(isolated_db):
    conn = get_db_connection()
    try:
        s = cmdb_service.create_site(conn, site_code="BJ-DC1", site_name="Beijing DC1", city="Beijing")
        assert s["site_code"] == "BJ-DC1"
        assert s["tenant_id"] == "tenant-default"

        with pytest.raises(ValueError):
            cmdb_service.create_site(conn, site_code="BJ-DC1", site_name="dup")

        cmdb_service.update_site(conn, s["id"], city="Shanghai", status="staging")
        got = cmdb_service.get_site(conn, s["id"])
        assert got["city"] == "Shanghai"
        assert got["status"] == "staging"

        cmdb_service.delete_site(conn, s["id"])
        assert all(x["id"] != s["id"] for x in cmdb_service.list_sites(conn))
    finally:
        conn.close()


def test_site_delete_blocked_by_rack(isolated_db):
    conn = get_db_connection()
    try:
        s = cmdb_service.create_site(conn, site_code="GZ-DC1", site_name="GZ")
        conn.execute(
            "INSERT INTO racks (id, site_id, rack_code, rack_name, name) VALUES (?, ?, ?, ?, ?)",
            ("rack-x", s["id"], "R01", "Rack 01", "Rack 01"),
        )
        conn.commit()
        with pytest.raises(ValueError):
            cmdb_service.delete_site(conn, s["id"])
    finally:
        conn.close()


def test_vrf_crud(isolated_db):
    conn = get_db_connection()
    try:
        v = cmdb_service.create_vrf(conn, vrf_name="CUSTOMER_A", rd="65000:1")
        assert v["rd"] == "65000:1"
        with pytest.raises(ValueError):
            cmdb_service.create_vrf(conn, vrf_name="CUSTOMER_A")
        cmdb_service.update_vrf(conn, v["id"], description="tenant A vrf")
        assert cmdb_service.get_vrf(conn, v["id"])["description"] == "tenant A vrf"
        cmdb_service.delete_vrf(conn, v["id"])
        with pytest.raises(ValueError):
            cmdb_service.get_vrf(conn, v["id"])
    finally:
        conn.close()


def test_vlan_crud_range_and_scope(isolated_db):
    conn = get_db_connection()
    try:
        site = cmdb_service.create_site(conn, site_code="SZ-DC1", site_name="SZ")

        # out-of-range rejected
        with pytest.raises(ValueError):
            cmdb_service.create_vlan(conn, vlan_id=5000, name="bad")

        v = cmdb_service.create_vlan(conn, vlan_id=100, name="users", site_id=site["id"])
        assert v["vlan_id"] == 100

        # duplicate vlan_id within same site rejected
        with pytest.raises(ValueError):
            cmdb_service.create_vlan(conn, vlan_id=100, name="dup", site_id=site["id"])

        # same vlan_id in a different (no) site is allowed
        v2 = cmdb_service.create_vlan(conn, vlan_id=100, name="global-100")
        assert v2["id"] != v["id"]

        cmdb_service.update_vlan(conn, v["id"], name="renamed", status="reserved")
        got = cmdb_service.get_vlan(conn, v["id"])
        assert got["name"] == "renamed"
        assert got["status"] == "reserved"

        listed = cmdb_service.list_vlans(conn, site_id=site["id"])
        assert len(listed) == 1

        cmdb_service.delete_vlan(conn, v["id"])
        cmdb_service.delete_vlan(conn, v2["id"])
    finally:
        conn.close()
