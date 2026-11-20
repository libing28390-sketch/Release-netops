from concurrent.futures import ThreadPoolExecutor

import database
import pytest

from services.topology_graph_service import build_graph, persist_graph


def _graph(source_port="Vlan200", target_port=None):
    return build_graph(
        [{"id": "router-a", "hostname": "Router A"}, {"id": "router-b", "hostname": "Router B"}],
        [{
            "source_device_id": "router-a", "target_device_id": "router-b",
            "source_interface": source_port, "target_interface": target_port,
            "source_type": "routing", "confidence": 0.8,
        }],
    )


@pytest.mark.parametrize("ports", [("Vlan200", None), (None, None), ("", ""), ("Vlan200", "Gi0/1")])
def test_repeated_graph_with_nullable_ports_is_idempotent(isolated_db, ports):
    graph = _graph(*ports)
    for _ in range(3):
        assert persist_graph(graph)["edges"] == 1
    with database.get_db_connection() as conn:
        rows = conn.execute("SELECT id, status FROM topology_edges").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == graph["edges"][0]["id"]
        assert rows[0]["status"] == "active"
        assert conn.execute("SELECT COUNT(*) FROM topology_relations").fetchone()[0] == 1


def test_existing_edge_id_is_reused_without_spurious_stale_history(isolated_db):
    graph = _graph()
    # Model a legacy fact with a different stable identifier.
    graph["edges"][0]["id"] = "legacy-edge"
    persist_graph(graph)
    persist_graph(_graph())
    with database.get_db_connection() as conn:
        rows = conn.execute("SELECT id, status FROM topology_edges").fetchall()
        assert [(row["id"], row["status"]) for row in rows] == [("legacy-edge", "active")]
        assert conn.execute("SELECT COUNT(*) FROM topology_history WHERE event_type = 'edge_stale'").fetchone()[0] == 0


def test_parallel_nullable_port_graph_writes_share_one_fact(isolated_db):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: persist_graph(_graph()), range(2)))
    assert all(result["edges"] == 1 for result in results)
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM topology_edges").fetchone()[0] == 1


def test_distinct_relation_types_on_same_ports_are_retained(isolated_db):
    graph = _graph()
    physical = dict(graph["edges"][0], id="physical-edge", relation_type="PHYSICAL")
    graph["edges"].append(physical)
    persist_graph(graph)
    persist_graph(graph)
    with database.get_db_connection() as conn:
        rows = conn.execute("SELECT relation_type FROM topology_edges ORDER BY relation_type").fetchall()
        assert [row[0] for row in rows] == ["LOGICAL", "PHYSICAL"]


def test_legacy_id_cannot_overwrite_a_different_relation(isolated_db):
    graph = _graph()
    persist_graph(graph)
    graph["edges"][0]["relation_type"] = "PHYSICAL"
    with pytest.raises(ValueError, match="topology_edge_id_conflict"):
        persist_graph(graph)
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT relation_type FROM topology_edges").fetchone()[0] == "LOGICAL"


def test_edge_id_collision_cannot_update_another_tenant(isolated_db):
    original = _graph()
    persist_graph(original)
    other = build_graph(
        [{"id": "other-a"}, {"id": "other-b"}],
        [{"source_device_id": "other-a", "target_device_id": "other-b", "source_type": "routing"}],
        tenant_id="tenant-other",
    )
    other["edges"][0]["id"] = original["edges"][0]["id"]
    with pytest.raises(ValueError, match="topology_edge_id_conflict"):
        persist_graph(other)
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT tenant_id FROM topology_edges").fetchone()[0] == "tenant-default"
