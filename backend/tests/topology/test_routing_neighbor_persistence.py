from __future__ import annotations

import sqlite3

from services.scheduler_service import _persist_routing_neighbor_results


def _routing_neighbors_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE routing_neighbors (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            protocol TEXT NOT NULL,
            neighbor_id TEXT DEFAULT '',
            neighbor_ip TEXT DEFAULT '',
            local_interface TEXT DEFAULT '',
            state TEXT DEFAULT '',
            uptime TEXT DEFAULT '',
            local_as INTEGER DEFAULT 0,
            remote_as INTEGER DEFAULT 0,
            area_id TEXT DEFAULT '',
            last_updated TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO routing_neighbors (
            id, device_id, protocol, neighbor_id, neighbor_ip, local_interface,
            state, uptime, local_as, remote_as, area_id, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("old-a", "device-a", "ospf", "2.2.2.2", "192.0.2.2", "Gi0/0", "FULL", "", 0, 0, "0.0.0.0", "old"),
    )
    conn.commit()
    return conn


def test_failed_collection_preserves_last_known_neighbors():
    conn = _routing_neighbors_db()

    summary = _persist_routing_neighbor_results(
        conn,
        [{"device_id": "device-a", "success": False, "protocols": [], "neighbors": []}],
        "2026-08-12T10:00:00+00:00",
    )

    assert summary == {"updated_devices": 0, "updated_protocols": 0, "inserted_neighbors": 0}
    assert conn.execute("SELECT COUNT(*) FROM routing_neighbors").fetchone()[0] == 1


def test_successful_protocol_replaces_only_that_device_protocol():
    conn = _routing_neighbors_db()
    conn.execute(
        """
        INSERT INTO routing_neighbors (
            id, device_id, protocol, neighbor_id, neighbor_ip, local_interface,
            state, uptime, local_as, remote_as, area_id, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("old-b", "device-b", "bgp", "203.0.113.2", "203.0.113.2", "", "Established", "", 1, 2, "", "old"),
    )
    conn.commit()

    summary = _persist_routing_neighbor_results(
        conn,
        [{
            "device_id": "device-b",
            "success": True,
            "protocols": ["bgp"],
            "neighbors": [{
                "protocol": "bgp",
                "neighbor_id": "203.0.113.3",
                "neighbor_ip": "203.0.113.3",
                "local_interface": "",
                "state": "Established",
                "uptime": "",
                "local_as": 1,
                "remote_as": 3,
                "area_id": "",
            }],
        }],
        "2026-08-12T10:00:00+00:00",
    )

    assert summary == {"updated_devices": 1, "updated_protocols": 1, "inserted_neighbors": 1}
    assert conn.execute("SELECT COUNT(*) FROM routing_neighbors WHERE device_id = 'device-a'").fetchone()[0] == 1
    row = conn.execute("SELECT neighbor_ip FROM routing_neighbors WHERE device_id = 'device-b'").fetchone()
    assert row[0] == "203.0.113.3"
