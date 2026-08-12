from __future__ import annotations

import sqlite3

from services.topology_service import _route_table_graph_observations


def test_route_table_next_hop_projects_to_logical_edge_without_physical_relation():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT
        );
        CREATE TABLE interfaces (
            device_id TEXT,
            ip_address TEXT,
            primary_ip TEXT
        );
        CREATE TABLE ip_inventory (
            device_id TEXT,
            ip TEXT
        );
        CREATE TABLE route_table (
            device_id TEXT,
            next_hop TEXT,
            outgoing_interface TEXT,
            protocol TEXT,
            destination TEXT,
            vrf_name TEXT,
            metric INTEGER,
            preference INTEGER,
            active INTEGER DEFAULT 1,
            last_updated TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO devices (id, hostname, ip_address) VALUES (?, ?, ?)",
        [("device-a", "R-A", "192.0.2.1"), ("device-b", "R-B", "192.0.2.2")],
    )
    conn.execute(
        """
        INSERT INTO route_table (
            device_id, next_hop, outgoing_interface, protocol, destination,
            vrf_name, metric, preference, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "device-a", "192.0.2.2", "Gi0/0", "ospf", "10.10.0.0/16",
            "default", 10, 110, "2026-08-12T10:00:00+00:00",
        ),
    )

    observations = _route_table_graph_observations(conn, {"device-a", "device-b"})

    assert len(observations) == 1
    observation = observations[0]
    assert observation["target_device_id"] == "device-b"
    assert observation["source_interface"] == "Gi0/0"
    assert observation["relation_type"] == "LOGICAL"
    assert observation["semantic_relation"] == "ROUTE_NEXT_HOP"
    assert observation["source_type"] == "ospf"


def test_unresolved_route_next_hop_is_retained_as_logical_evidence():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE devices (id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT);
        CREATE TABLE interfaces (device_id TEXT, ip_address TEXT, primary_ip TEXT);
        CREATE TABLE ip_inventory (device_id TEXT, ip TEXT);
        CREATE TABLE route_table (
            device_id TEXT, next_hop TEXT, outgoing_interface TEXT, protocol TEXT,
            destination TEXT, vrf_name TEXT, metric INTEGER, preference INTEGER,
            active INTEGER DEFAULT 1,
            last_updated TEXT
        );
        """
    )
    conn.execute("INSERT INTO devices (id, hostname, ip_address) VALUES (?, ?, ?)", ("device-a", "R-A", "192.0.2.1"))
    conn.execute(
        """
        INSERT INTO route_table (
            device_id, next_hop, outgoing_interface, protocol, destination,
            vrf_name, metric, preference, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("device-a", "198.51.100.2", "Gi0/1", "bgp", "203.0.113.0/24", "default", 0, 20, "2026-08-12T10:00:00+00:00"),
    )

    observations = _route_table_graph_observations(conn, {"device-a"})

    assert len(observations) == 1
    assert observations[0]["target_device_id"] == "198.51.100.2"
    assert observations[0]["relation_type"] == "LOGICAL"
