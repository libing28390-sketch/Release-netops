from __future__ import annotations

from datetime import datetime, timezone

from database import get_db_connection
from services.topology_graph_service import get_graph
from services.topology_service import select_topology_discovery_devices


def _insert_topology_device(conn, *, device_id: str, hostname: str, platform: str, role: str, category: str) -> None:
    conn.execute(
        """INSERT INTO devices
           (id, hostname, ip_address, platform, status, compliance, role, device_category)
           VALUES (?, ?, ?, ?, 'online', 'unknown', ?, ?)""",
        (device_id, hostname, "192.0.2.10", platform, role, category),
    )


def test_server_assets_are_not_selected_for_topology_discovery(isolated_db):
    conn = get_db_connection()
    try:
        _insert_topology_device(conn, device_id="switch-1", hostname="SW-1", platform="h3c_comware", role="access", category="network_device")
        _insert_topology_device(conn, device_id="server-1", hostname="app-server", platform="linux", role="server", category="server")
        _insert_topology_device(conn, device_id="server-2", hostname="inventory-server", platform="h3c_comware", role="server", category="network_device")
        conn.commit()
    finally:
        conn.close()

    selection = select_topology_discovery_devices(
        "devices",
        device_ids=["switch-1", "server-1", "server-2"],
    )

    assert selection["device_ids"] == ["switch-1"]
    assert set(selection["excluded_device_ids"]) == {"server-1", "server-2"}


def test_existing_server_topology_nodes_and_edges_are_hidden(isolated_db):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        _insert_topology_device(conn, device_id="switch-1", hostname="SW-1", platform="h3c_comware", role="access", category="network_device")
        _insert_topology_device(conn, device_id="server-1", hostname="app-server", platform="linux", role="server", category="server")
        for node_id, device_id, hostname in (
            ("node-switch", "switch-1", "SW-1"),
            ("node-server", "server-1", "app-server"),
        ):
            conn.execute(
                """INSERT INTO topology_nodes
                   (id, tenant_id, node_type, canonical_key, display_name, device_id,
                    status, metadata_json, created_at, updated_at)
                   VALUES (?, 'tenant-default', 'DEVICE', ?, ?, ?, 'active', '{}', ?, ?)""",
                (node_id, node_id, hostname, device_id, now, now),
            )
        conn.commit()
    finally:
        conn.close()

    graph = get_graph(tenant_id="tenant-default")

    assert {node["device_id"] for node in graph["nodes"] if node.get("device_id")} == {"switch-1"}
    assert all("server" not in node["display_name"].casefold() for node in graph["nodes"])
