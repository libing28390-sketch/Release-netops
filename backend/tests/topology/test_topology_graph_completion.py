from __future__ import annotations

import sqlite3

import pytest

from database.migrations.m0105_ai_security_operations_graph import upgrade as upgrade_graph_base
from database.migrations.m0115_topology_graph_completion import upgrade as upgrade_graph_completion
from services import topology_graph_service as graph_service
from services.topology_graph_service import (
    build_graph,
    calculate_dynamic_ranks,
    detect_topology_anchors,
    layout_graph,
    normalize_observation,
    normalize_role,
    persist_graph,
)


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


def test_dynamic_rank_uses_relation_constraints_not_role_names():
    nodes = [
        {"id": "fw", "role": "Firewall"},
        {"id": "core", "role": "Core Switch"},
        {"id": "access", "role": "Access Switch"},
        {"id": "oob", "role": "OOB Switch"},
    ]
    ranks = calculate_dynamic_ranks(nodes, [
        {"source_node_id": "fw", "target_node_id": "core", "relation_type": "PEER", "direction": "undirected"},
        {"source_node_id": "core", "target_node_id": "access", "relation_type": "HIERARCHICAL", "direction": "directed"},
        {"source_node_id": "oob", "target_node_id": "access", "relation_type": "OOB", "direction": "undirected", "rank_excluded": 1},
    ])
    assert ranks["fw"] == ranks["core"]
    assert ranks["access"] == ranks["core"] + 1
    assert ranks["oob"] == 0


def test_layout_uses_rank_and_manual_coordinates_without_role_tiers():
    graph = {
        "nodes": [
            {"id": "firewall", "display_name": "FW", "role_identity": "FIREWALL", "rank": 0},
            {"id": "access", "display_name": "ACCESS", "role_identity": "ACCESS_SWITCH", "rank": 2},
        ],
        "edges": [{
            "source_node_id": "firewall", "target_node_id": "access",
            "relation_type": "HIERARCHICAL", "direction": "directed", "rank_excluded": 0,
        }],
    }
    layout = layout_graph(graph, overrides={"firewall": {"x": 42, "y": 84}})
    assert layout["firewall"] == {"x": 42, "y": 84, "manual": 1.0}
    assert layout["access"]["y"] != layout["firewall"]["y"]


@pytest.fixture()
def graph_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE alert_events (id TEXT)")
    conn.execute("CREATE TABLE pam_sessions (id TEXT)")
    conn.execute("CREATE TABLE ai_model (model_code TEXT, name TEXT, thinking_supported INTEGER)")
    upgrade_graph_base(conn.cursor(), False)
    upgrade_graph_completion(conn.cursor(), False)
    conn.commit()
    monkeypatch.setattr(graph_service, "get_db_connection", lambda: conn)
    yield conn
    conn.close()


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
