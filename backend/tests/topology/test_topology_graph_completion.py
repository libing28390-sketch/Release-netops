from __future__ import annotations

from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from api.topology import _filter_resolved_topology_links_to_scope, _resolve_graph_tenant
from database.migrations.m0105_ai_security_operations_graph import upgrade as upgrade_graph_base
from database.migrations.m0115_topology_graph_completion import upgrade as upgrade_graph_completion
from services import topology_graph_service as graph_service
from services.topology_graph_service import (
    build_graph,
    detect_topology_anchors,
    get_edge_evidence,
    get_graph,
    get_topology_history,
    layout_graph,
    normalize_observation,
    normalize_role,
    persist_graph,
)


def test_graph_tenant_is_a_data_selector_not_an_access_boundary_in_single_org_mode():
    operator = {"role": "Operator", "tenant_id": "tenant-a"}
    assert _resolve_graph_tenant(operator) == "tenant-default"
    assert _resolve_graph_tenant(operator, "tenant-a") == "tenant-a"
    assert _resolve_graph_tenant(operator, "tenant-b") == "tenant-b"
    assert _resolve_graph_tenant({"role": "Administrator"}, "tenant-b") == "tenant-b"


def test_resolved_topology_links_do_not_escape_authorized_device_scope():
    links = [
        {"source_device_id": "allowed-a", "target_device_id": "allowed-b"},
        {"source_device_id": "allowed-a", "target_device_id": "other-tenant-device"},
    ]

    assert _filter_resolved_topology_links_to_scope(links, ["allowed-a", "allowed-b"]) == [links[0]]
    assert _filter_resolved_topology_links_to_scope(links, None) == links


def test_relation_classification_keeps_protocols_out_of_physical_edges():
    assert normalize_observation({"source_node": "a", "target_node": "b", "source_type": "lldp"})[
        "relation_type"
    ] == "PHYSICAL"
    assert normalize_observation({"source_node": "a", "target_node": "b", "source_type": "ospf"})[
        "relation_type"
    ] == "L3_NEIGHBOR"
    assert normalize_observation({"source_node": "a", "target_node": "b", "protocol": "bgp", "metadata": {"session_type": "ebgp"}})[
        "relation_type"
    ] == "WAN"
    assert normalize_observation({"source_node": "a", "target_node": "b", "protocol": "interface_ip"})[
        "semantic_relation"
    ] == "L3_NEIGHBOR"
    assert normalize_observation({"source_node": "a", "target_node": "b", "protocol": "routing"})[
        "relation_type"
    ] == "LOGICAL"
    assert normalize_observation({"source_node": "a", "target_node": "b", "source_type": "stp"})[
        "relation_type"
    ] == "L2_NEIGHBOR"
    assert normalize_observation({
        "source_node": "a", "target_node": "b", "source_type": "ospf",
        "relation_type": "PHYSICAL",
    })["relation_type"] == "UNKNOWN"


def test_special_relations_and_unknown_direction_remain_lossless():
    ha = normalize_observation({
        "source_node": "fw-a", "target_node": "fw-b", "source_type": "ha_peer",
    })
    assert ha["relation_type"] == "HA_PEER"
    assert ha["direction"] == "undirected"
    unknown_direction = normalize_observation({
        "source_node": "sw-a", "target_node": "sw-b", "source_type": "lldp",
        "direction": "unknown",
    })
    assert unknown_direction["direction"] == "unknown"


def test_oob_unknown_site_and_group_facts_are_first_class_graph_objects():
    graph = build_graph(
        [
            {"id": "r1", "hostname": "R1", "role": "Firewall", "site_id": "bj", "zone": "LAN"},
            {"id": "r2", "hostname": "R2", "role": "Access Switch", "site_id": "sh", "zone": "WAN"},
        ],
        [
            {
                "source_device_id": "r1", "target_device_id": "r2", "source_type": "lldp",
                "source_interface": "Et0/1", "target_interface": "Et0/1", "confidence": 0.99,
            },
            {
                "source_device_id": "r1", "target_device_id": "oob-sw", "source_type": "lldp",
                "zone": "OOB", "confidence": 0.99,
            },
            {
                "source_device_id": "r1", "target_device_id": "stack-member-2", "source_type": "stack",
                "group_id": "stack-1", "group_type": "STACK", "metadata": {"member_role": "member"},
            },
            {"source_device_id": "r1", "target_device_id": "unknown-neighbor", "source_type": "lldp"},
        ],
    )

    relation_types = {edge["relation_type"] for edge in graph["edges"]}
    assert "PHYSICAL" in relation_types
    assert "OOB" in relation_types
    assert "INTER_SITE" in relation_types
    assert any(node["node_type"] == "UNKNOWN" for node in graph["nodes"])
    assert any(group["group_type"] == "STACK" for group in graph["groups"])
    assert any(member["group_id"] == "group:stack-1" for member in graph["group_members"])


def test_role_is_identity_and_anchor_detection_is_multi_root():
    assert normalize_role("Core") == "CORE_SWITCH"
    assert normalize_role("Access Switch") == "ACCESS_SWITCH"
    assert normalize_role("OOB Switch") == "OOB_SWITCH"
    assert normalize_role("WAF") == "WAF"
    assert normalize_role("VPN Gateway") == "VPN_GATEWAY"
    assert normalize_role("Edge") == "EDGE"
    assert normalize_role("Other Network") == "OTHER"
    nodes = [
        {"id": "fw", "node_type": "DEVICE", "function": "Internet Edge", "zone": "WAN"},
        {"id": "isp", "node_type": "EXTERNAL", "display_name": "ISP-A"},
        {"id": "core", "node_type": "DEVICE", "function": "Campus Core", "zone": "LAN"},
    ]
    anchors = detect_topology_anchors(nodes, [{
        "source_node_id": "fw", "target_node_id": "isp", "relation_type": "WAN",
    }])
    assert {item["node_id"] for item in anchors} == {"fw", "isp"}


def test_interface_ip_is_l3_only_even_for_point_to_point_prefixes():
    observation = normalize_observation({
        "source_node": "r1", "target_node": "r2", "source_type": "interface_ip",
        "protocol": "interface_ip", "metadata": {"prefix": "/31"},
    })
    assert observation["relation_type"] == "L3_NEIGHBOR"
    assert observation["relation_type"] != "PHYSICAL"


def test_layout_returns_only_explicit_coordinates():
    graph = {
        "nodes": [
            {"id": "firewall", "display_name": "FW", "role_identity": "FIREWALL"},
            {"id": "access", "display_name": "ACCESS", "role_identity": "ACCESS_SWITCH"},
        ]
    }
    layout = layout_graph(graph, overrides={"firewall": {"x": 42, "y": 84}})
    assert layout["firewall"] == {"x": 42, "y": 84, "manual": 1.0}
    assert "access" not in layout


def test_ring_group_tracks_both_edge_ends_without_calculating_layout():
    node_ids = ["ring-a", "ring-b", "ring-c", "ring-d"]
    observations = [
        {
            "source_device_id": source,
            "target_device_id": target,
            "source_type": "ring",
            "group_id": "campus-ring",
            "group_type": "RING",
        }
        for source, target in zip(node_ids, node_ids[1:] + node_ids[:1])
    ]
    graph = build_graph([{"id": node_id} for node_id in node_ids], observations)
    members = {
        member["node_id"] for member in graph["group_members"]
        if member["group_id"] == "group:campus-ring"
    }
    assert members == set(node_ids)
    assert len(graph["group_members"]) == 4


@pytest.fixture()
def graph_db(monkeypatch):
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.execute("CREATE TABLE alert_events (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE pam_sessions (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE ai_model (model_code TEXT PRIMARY KEY, name TEXT, thinking_supported INTEGER)"
    )
    upgrade_graph_base(conn.cursor(), True)
    upgrade_graph_completion(conn.cursor(), True)
    conn.commit()
    monkeypatch.setattr(graph_service, "get_db_connection", lambda: conn)
    yield conn
    conn.close()


def test_graph_read_model_excludes_reimported_device_ids(graph_db):
    graph_db.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
    graph_db.executemany(
        "INSERT INTO devices (id) VALUES (?)",
        [("current-a",), ("current-b",)],
    )
    graph = build_graph(
        [
            {"id": "old-a", "device_id": "old-a", "hostname": "A"},
            {"id": "old-b", "device_id": "old-b", "hostname": "B"},
            {"id": "current-a", "device_id": "current-a", "hostname": "A"},
            {"id": "current-b", "device_id": "current-b", "hostname": "B"},
        ],
        [
            {"source_device_id": "old-a", "target_device_id": "old-b", "source_type": "lldp"},
            {"source_device_id": "current-a", "target_device_id": "current-b", "source_type": "lldp"},
        ],
    )
    persist_graph(graph)

    physical = get_graph(view="physical")
    assert {node.get("device_id") for node in physical["nodes"] if node["node_type"] == "DEVICE"} == {
        "current-a",
        "current-b",
    }
    assert len(physical["edges"]) == 1
    assert {
        physical["edges"][0]["source_node_id"],
        physical["edges"][0]["target_node_id"],
    } == {"current-a", "current-b"}


def test_persist_graph_preserves_manual_relation_and_writes_history(graph_db):
    graph = build_graph(
        [{"id": "a", "hostname": "A"}, {"id": "b", "hostname": "B"}],
        [{
            "source_device_id": "a", "target_device_id": "b", "source_type": "lldp",
            "source_interface": "Gi1/0/1", "target_interface": "Gi1/0/2", "confidence": 0.99,
        }],
    )
    persist_graph(graph)
    edge_id = graph_db.execute("SELECT id FROM topology_edges WHERE relation_type = 'PHYSICAL'").fetchone()[0]
    graph_db.execute(
        "UPDATE topology_edges SET relation_type = 'PEER', semantic_relation = 'MANUAL_PEER', is_manual = 1, manual_confirmed = 1 WHERE id = ?",
        (edge_id,),
    )
    graph_db.commit()

    persist_graph(graph)
    rows = graph_db.execute("SELECT id, relation_type, is_manual, manual_confirmed FROM topology_edges").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == edge_id
    assert rows[0]["relation_type"] == "PEER"
    assert rows[0]["is_manual"] == 1
    assert rows[0]["manual_confirmed"] == 1
    assert graph_db.execute("SELECT COUNT(*) FROM topology_history").fetchone()[0] >= 1


def test_persisted_graph_returns_special_views_groups_members_and_evidence_counts(graph_db):
    graph = build_graph(
        [{"id": "fw-a"}, {"id": "fw-b"}, {"id": "ac"}, {"id": "ap"}],
        [
            {
                "source_device_id": "fw-a", "target_device_id": "fw-b", "source_type": "ha_peer",
                "group_id": "fw-ha", "group_type": "HA",
            },
            {
                "source_device_id": "ac", "target_device_id": "ap", "source_type": "wireless_control",
            },
        ],
    )
    persist_graph(graph)

    logical = get_graph(view="logical")
    relations = {edge["relation_type"] for edge in logical["edges"]}
    assert {"HA_PEER", "CONTROL"}.issubset(relations)
    assert {member["node_id"] for member in logical["group_members"]} == {"fw-a", "fw-b"}
    assert all(edge["evidence_count"] >= 1 for edge in logical["edges"])


def test_route_evidence_is_visible_in_l3_but_never_in_physical_view(graph_db):
    graph = build_graph(
        [{"id": "router-a"}, {"id": "router-b"}],
        [
            {
                "source_device_id": "router-a",
                "target_device_id": "router-b",
                "source_type": "lldp",
                "source_interface": "Gi0/0",
                "target_interface": "Gi0/1",
            },
            {
                "source_device_id": "router-a",
                "target_device_id": "router-b",
                "source_type": "ospf",
                "protocol": "ospf",
                "relation_type": "LOGICAL",
                "semantic_relation": "ROUTE_NEXT_HOP",
                "direction": "directed",
            },
        ],
    )
    persist_graph(graph)

    physical_relations = {edge["relation_type"] for edge in get_graph(view="physical")["edges"]}
    l3_relations = {edge["relation_type"] for edge in get_graph(view="l3")["edges"]}

    assert physical_relations == {"PHYSICAL"}
    assert "LOGICAL" in l3_relations


def test_graph_evidence_history_and_groups_honor_device_scope(graph_db):
    graph = build_graph(
        [{"id": "scoped-a"}, {"id": "scoped-b"}, {"id": "hidden-c"}],
        [
            {
                "source_device_id": "scoped-a", "target_device_id": "scoped-b",
                "source_type": "lldp", "source_interface": "Gi0/1",
                "target_interface": "Gi0/2",
            },
            {
                "source_device_id": "hidden-c", "target_device_id": "scoped-b",
                "source_type": "lldp", "source_interface": "Gi0/3",
                "target_interface": "Gi0/4",
            },
        ],
    )
    persist_graph(graph)
    edge_ids = {
        str(row["id"]): (str(row["source_node_id"]), str(row["target_node_id"]))
        for row in graph_db.execute("SELECT id, source_node_id, target_node_id FROM topology_edges").fetchall()
    }
    visible_edge_id = next(
        edge_id for edge_id, endpoints in edge_ids.items()
        if set(endpoints) == {"scoped-a", "scoped-b"}
    )
    hidden_edge_id = next(
        edge_id for edge_id, endpoints in edge_ids.items()
        if "hidden-c" in endpoints
    )

    scoped = get_graph(device_ids=["scoped-a", "scoped-b"])
    assert {item["device_id"] for item in scoped["nodes"]} == {"scoped-a", "scoped-b"}
    assert {item["id"] for item in scoped["edges"]} == {visible_edge_id}
    assert {item["node_id"] for item in scoped["group_members"]} <= {"scoped-a", "scoped-b"}

    assert get_edge_evidence(hidden_edge_id, device_ids=["scoped-a", "scoped-b"]) == []
    assert get_edge_evidence(visible_edge_id, device_ids=["scoped-a", "scoped-b"])
    history = get_topology_history(device_ids=["scoped-a", "scoped-b"])
    assert all(
        item["entity_id"] != hidden_edge_id
        for item in history["items"]
    )
