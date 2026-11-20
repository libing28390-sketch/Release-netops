from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from database import get_db_connection
from database import schema as database_schema
from services import cmdb_service, ipam_discovery_service, reconciliation_service
from services.ipam_address_space_service import create_address_space
from services.ipam_service import create_address, create_subnet


TENANT_ID = "tenant-default"
SITE_ID = "assignment-writer-site"
PREFIX = "198.51.100.0/24"


def _seed_ipam_address(*, interface_id: str | None = "writer-interface-a") -> dict:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants(id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
            (TENANT_ID, "Default"),
        )
        conn.execute(
            """INSERT INTO sites(id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
            (SITE_ID, SITE_ID.upper(), SITE_ID, TENANT_ID),
        )
        for suffix in ("a", "b"):
            device_id = f"writer-device-{suffix}"
            conn.execute(
                """INSERT INTO devices(id, hostname, tenant_id, site_id, status)
                   VALUES (?, ?, ?, ?, 'online') ON CONFLICT(id) DO NOTHING""",
                (device_id, device_id, TENANT_ID, SITE_ID),
            )
            conn.execute(
                """INSERT INTO interfaces(id, device_id, interface_name)
                   VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                (f"writer-interface-{suffix}", device_id, f"Ethernet{suffix}"),
            )
        conn.commit()

    address_space = create_address_space(
        name="Assignment Writer Compatibility Global",
        kind="global",
        vrf_id=None,
        security_tenant_id=TENANT_ID,
    )
    prefix = create_subnet(
        prefix=PREFIX,
        address_space_id=address_space["id"],
        site_id=SITE_ID,
        tenant_id=TENANT_ID,
        network_type="server",
    )
    return create_address(
        prefix["id"],
        address="198.51.100.10",
        device_id="writer-device-a",
        interface_name="Etherneta",
        interface_id=interface_id or "",
    )


def test_reconciliation_normalizes_blank_assignments_and_releases_to_null(isolated_db, monkeypatch):
    address = _seed_ipam_address()
    monkeypatch.setattr(reconciliation_service, "log_audit_event", lambda **_kwargs: None)

    with get_db_connection() as conn:
        reconciliation_service._apply_action(
            conn,
            {"id": "finding-blank-assignment", "target_id": address["id"], "target_type": "ip_address"},
            {
                "id": "action-blank-assignment",
                "action_type": "update_ip_metadata",
                "payload_json": json.dumps({"device_id": "", "interface_id": ""}),
            },
            "reviewer",
        )
        cleared = conn.execute(
            "SELECT device_id, interface_id, revision FROM ip_addresses WHERE id = ?",
            (address["id"],),
        ).fetchone()
        assert cleared["device_id"] is None
        assert cleared["interface_id"] is None
        assert cleared["revision"] == 2

        reconciliation_service._apply_action(
            conn,
            {"id": "finding-release", "target_id": address["id"], "target_type": "ip_address"},
            {"id": "action-release", "action_type": "release_ip", "payload_json": "{}"},
            "reviewer",
        )
        released = conn.execute(
            "SELECT status, device_id, interface_id, revision FROM ip_addresses WHERE id = ?",
            (address["id"],),
        ).fetchone()
        assert released["status"] == "released"
        assert released["device_id"] is None
        assert released["interface_id"] is None
        assert released["revision"] == 3

        with pytest.raises(ValueError, match="does not belong"):
            reconciliation_service._apply_action(
                conn,
                {"id": "finding-mismatch", "target_id": address["id"], "target_type": "ip_address"},
                {
                    "id": "action-mismatch",
                    "action_type": "update_ip_metadata",
                    "payload_json": json.dumps({
                        "device_id": "writer-device-a",
                        "interface_id": "writer-interface-b",
                    }),
                },
                "reviewer",
            )
        unchanged = conn.execute(
            "SELECT device_id, interface_id, revision FROM ip_addresses WHERE id = ?",
            (address["id"],),
        ).fetchone()
        assert unchanged["device_id"] is None
        assert unchanged["interface_id"] is None
        assert unchanged["revision"] == 3
        conn.commit()


def test_cmdb_interface_backfill_increments_ip_revision(isolated_db):
    address = _seed_ipam_address(interface_id=None)
    with get_db_connection() as conn:
        conn.execute("UPDATE ip_addresses SET revision = 7 WHERE id = ?", (address["id"],))
        conn.commit()

        result = cmdb_service.backfill_field_authority(conn)

        updated = conn.execute(
            """SELECT ip.device_id, ip.interface_id, ip.revision, i.device_id AS interface_device_id
                 FROM ip_addresses ip
                 JOIN interfaces i ON i.id = ip.interface_id
                WHERE ip.id = ?""",
            (address["id"],),
        ).fetchone()
        assert result["updated"]["ip_addresses_interface_id"] == 1
        assert updated["interface_id"] == "writer-interface-a"
        assert updated["interface_device_id"] == updated["device_id"] == "writer-device-a"
        assert updated["revision"] == 8
        conn.commit()


def test_legacy_ip_inventory_import_normalizes_blank_assignments_and_revisions_updates(isolated_db):
    address = _seed_ipam_address()
    with get_db_connection() as conn:
        conn.execute(
            """UPDATE ip_addresses
                  SET ip_address = ?, revision = 5
                WHERE id = ?""",
            ("198.51.100.10/32", address["id"]),
        )
        conn.execute(
            """INSERT INTO ip_inventory(ip, mask, device_id, interface, type, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("198.51.100.10", "255.255.255.0", "", "", "host", "2026-11-05T00:00:00+00:00"),
        )
        conn.commit()

        database_schema._init_db_logic(conn, allow_legacy_import=True)

        imported = conn.execute(
            "SELECT device_id, interface_id, revision FROM ip_addresses WHERE id = ?",
            (address["id"],),
        ).fetchone()
        assert imported["device_id"] is None
        assert imported["interface_id"] is None
        assert imported["revision"] == 6
        conn.commit()


def test_discovery_mac_calibration_increments_ip_revision(isolated_db):
    from backend.tests.ipam.test_ipam_discovery_evidence import (
        MAC,
        OTHER_MAC,
        _global_space_id,
        mark_run,
        raw_arp,
        seed,
    )

    seed()
    observed = datetime.now(timezone.utc) - timedelta(seconds=10)
    raw_arp(observed)
    mark_run(observed)
    ipam_discovery_service.run_ipam_discovery_projection()
    prefix = create_subnet(
        prefix="192.0.2.0/24",
        address_space_id=_global_space_id(),
        site_id="discovery-site-a",
        tenant_id=TENANT_ID,
    )
    address = create_address(
        prefix["id"],
        address="192.0.2.10",
        hostname="calibration-test-host",
        mac_address=OTHER_MAC,
        status="active",
    )
    observation = ipam_discovery_service.list_discovered_endpoints(kind="ip")["items"][0]
    assert observation["calibration_safe"]

    with get_db_connection() as conn:
        before = conn.execute(
            "SELECT revision FROM ip_addresses WHERE id = ?", (address["id"],)
        ).fetchone()["revision"]

    ipam_discovery_service.calibrate_ipam_mac(
        observation_id=observation["id"],
        ipam_address_id=address["id"],
        expected_observed_at=observation["observed_at"],
        expected_mac_address=OTHER_MAC,
        confirmed=True,
    )

    with get_db_connection() as conn:
        updated = conn.execute(
            "SELECT mac_address, revision FROM ip_addresses WHERE id = ?", (address["id"],)
        ).fetchone()
        assert updated["mac_address"] == MAC
        assert updated["revision"] == before + 1
