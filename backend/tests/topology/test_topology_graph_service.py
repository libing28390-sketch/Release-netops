from __future__ import annotations

from services.topology_graph_service import build_graph, canonical_edge_key, layout_graph, normalize_observation


def test_lldp_is_physical_but_l3_and_arp_are_not_physical():
    assert normalize_observation({"source_node": "a", "target_node": "b", "source_type": "lldp"})["relation_type"] == "PHYSICAL"
    assert normalize_observation({"source_node": "a", "target_node": "b", "source_type": "ospf"})["relation_type"] == "L3_NEIGHBOR"
    assert normalize_observation({"source_node": "a", "target_node": "host", "source_type": "arp"})["relation_type"] == "ENDPOINT"


def test_graph_fuses_evidence_and_does_not_use_role_for_rank():
    graph = build_graph(
        [
            {"id": "a", "hostname": "edge-a", "role": "access", "site_id": "site-1"},
            {"id": "b", "hostname": "core-b", "role": "core", "site_id": "site-1"},
        ],
        [
            {"source_device_id": "a", "target_device_id": "b", "source_type": "lldp", "confidence": 0.9},
            {"source_device_id": "a", "target_device_id": "b", "source_type": "description", "confidence": 0.4},
        ],
    )
    assert any(node["node_type"] == "SITE" for node in graph["nodes"])
    assert len(graph["edges"]) == 2
    physical = next(edge for edge in graph["edges"] if edge["relation_type"] == "PHYSICAL")
    assert physical["semantic_confidence"] > 0.8
    assert all(node["rank"] == 0 for node in graph["nodes"])


def test_server_assets_and_links_are_excluded_from_topology_graph():
    graph = build_graph(
        [
            {"id": "switch-1", "device_id": "switch-1", "hostname": "SW-1", "role": "access", "platform": "h3c_comware"},
            {"id": "server-1", "device_id": "server-1", "hostname": "app-server", "role": "server", "platform": "linux"},
        ],
        [{"source_device_id": "switch-1", "target_device_id": "server-1", "source_type": "lldp"}],
    )

    assert all(node.get("device_id") != "server-1" for node in graph["nodes"])
    assert graph["edges"] == []


def test_layout_override_wins_without_role_layer_heuristics():
    graph = {"nodes": [{"id": "a", "rank": 3, "role_identity": "SWITCH"}]}
    layout = layout_graph(graph, overrides={"a": {"x": 42, "y": 84}})
    assert layout["a"]["x"] == 42
    assert layout["a"]["y"] == 84
    assert layout["a"]["manual"] == 1


def test_reverse_undirected_observations_share_one_physical_edge_key():
    forward = canonical_edge_key({
        "source_node_id": "a", "target_node_id": "b",
        "source_interface": "Gi1/0/1", "target_interface": "Gi1/0/2",
        "source_type": "lldp",
    })
    reverse = canonical_edge_key({
        "source_node_id": "b", "target_node_id": "a",
        "source_interface": "Gi1/0/2", "target_interface": "Gi1/0/1",
        "source_type": "lldp",
    })
    assert forward == reverse
