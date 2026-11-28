"""Collection-generation and stale-result publication tests, with mocked SQL rows."""
from copy import deepcopy

import pytest

from services import ip_locator_task_service as tasks


def fact(device, generation=7, context_type="global", local_context_key=""):
    return dict(device_id=device, generation=generation, context_source="snmp",
                context_type=context_type, local_context_key=local_context_key)


class Connection:
    def __init__(self, states):
        self.states = states
        self.queries = []

    def execute(self, sql, params):
        assert "FOR SHARE NOWAIT" in sql
        self.queries.append(params)
        self.row = self.states.get(params)
        return self

    def fetchone(self):
        return self.row


@pytest.fixture
def setup():
    expected = {"arp_evidence": [fact("z")], "fdb_evidence": [fact("z"), fact("a"), fact("b")]}
    states = {
        (row["device_id"], kind, "snmp", "global", ""): dict(
            latest_attempt_generation=7, last_success_generation=7, latest_status="complete",
        )
        for kind in ("arp", "fdb") for row in expected[kind + "_evidence"]
    }
    return expected, states


@pytest.mark.parametrize("change", [
    "none", "running", "failed", "partial", "unsupported", "new_attempt",
    "new_success", "missing", "unknown_ok", "old_attempt",
])
def test_generation_fence(setup, change):
    expected, states = setup
    key = ("a", "fdb", "snmp", "global", "")
    if change == "missing":
        del states[key]
    elif change == "new_attempt":
        states[key]["latest_attempt_generation"] = 8
    elif change == "new_success":
        states[key]["last_success_generation"] = 8
    elif change == "old_attempt":
        states[key]["latest_attempt_generation"] = 6
    elif change == "unknown_ok":
        states[key]["latest_status"] = "scope_unknown"
    elif change != "none":
        states[key]["latest_status"] = change
    conn = Connection(states)
    assert tasks._lock_current_collection_generations(conn, expected) == (change in ("none", "unknown_ok"))
    assert conn.queries == sorted(set(conn.queries))
    if change in ("none", "unknown_ok"):
        assert len(conn.queries) == 4


@pytest.mark.parametrize("change", [
    "empty", "missing_arp", "missing_key", "zero", "bool", "str", "float",
    "conflicting", "not_mapping", "no_context",
])
def test_invalid_manifest(setup, change):
    expected, states = setup
    if change == "empty":
        expected["fdb_evidence"] = []
    elif change == "missing_arp":
        del expected["arp_evidence"]
    elif change == "missing_key":
        del expected["fdb_evidence"][0]["local_context_key"]
    elif change == "conflicting":
        expected["fdb_evidence"].append(fact("z", 8))
    elif change == "not_mapping":
        expected["fdb_evidence"].append(None)
    elif change == "no_context":
        expected["fdb_evidence"][0]["context_type"] = ""
    else:
        expected["fdb_evidence"][0]["generation"] = {"zero": 0, "bool": True, "str": "7", "float": 7.0}[change]
    conn = Connection(states)
    assert not tasks._lock_current_collection_generations(conn, expected)
    assert not conn.queries


def test_duplicate_locks_once(setup):
    expected, states = setup
    expected["fdb_evidence"].append(fact("a"))
    conn = Connection(states)
    assert tasks._lock_current_collection_generations(conn, expected)
    assert len(conn.queries) == 4


@pytest.mark.parametrize("status", ["completed", "partial"])
@pytest.mark.parametrize("gap", [
    "dependency_changed:current_endpoint", "dependency_expired:observation:x", "dependency_manifest_missing",
])
def test_downgrade(status, gap):
    result = dict(
        status=status, found=True, conclusion="endpoint_evidence_confirmed", trace_status="terminal",
        location={"port": "GE1/0/2"}, locations=[{"port": "GE1/0/2"}],
        terminal_candidates=[{"port": "GE1/0/2"}], mac="00:11:22:33:44:55",
        mac_display="0011-2233-4455", arp_source={"device": "s1"}, mac_lookup={"status": "found"},
        coverage_gaps=["old", gap], arp_evidence=[{"mac": "00:11:22:33:44:55"}],
    )
    tasks._downgrade_stale_locator_result(result, [gap])
    assert not result["found"] and result["status"] == "partial" and result["conclusion"] == "dependency_changed"
    assert result["trace_status"] == "incomplete" and result["coverage_gaps"] == ["old", gap]
    assert result["dependency_fence"]["status"] == ("changed" if gap.startswith("dependency_changed:") else "incomplete")
    assert not result["locations"] and not result["terminal_candidates"]
    assert result["mac_lookup"] == {"status": "not_attempted"} and result["arp_evidence"]
    assert not set(("location", "mac", "mac_display", "arp_source")) & result.keys()


def test_lock_contention_recovers_savepoint(setup, monkeypatch):
    from services import ip_locator_endpoint_evidence as evidence

    expected, _ = setup
    statements = []

    class Conn:
        def execute(self, sql, params=None):
            if "FOR SHARE NOWAIT" in sql:
                statements.append("lock")
                raise RuntimeError("simulated row lock contention")
            statements.append(sql)

    monkeypatch.setattr(evidence, "find_current_endpoint_evidence", lambda *a, **kw: pytest.fail("contended generation must not be used"))
    manifest = {
        "type": "current_endpoint", "version": 1, "target_ip": "192.0.2.1",
        "context": {"authorized_device_ids": ["z", "a", "b"]},
        "evidence": deepcopy(expected),
    }
    assert tasks._dependency_manifest_current_in_transaction(Conn(), manifest, lock=True) == (
        False, ["dependency_changed:current_endpoint"],
    )
    assert statements == [
        "SAVEPOINT locator_current_fence", "lock",
        "ROLLBACK TO SAVEPOINT locator_current_fence", "RELEASE SAVEPOINT locator_current_fence",
    ]

def test_native_postgresql_collector_lock_and_savepoint(isolated_db, monkeypatch):
    """Use two independent PG transactions; never substitute a mock SQL engine."""
    from database import get_db_connection
    from psycopg2.errors import LockNotAvailable
    from services import ip_locator_endpoint_evidence as evidence

    device = "native-pg-fence-test"
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute("INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, 'tenant-default')", (device, device))
        for kind in ("arp", "fdb"):
            conn.execute(
                """INSERT INTO ipam_endpoint_collection_states
                   (device_id, observation_source, context_source, context_type,
                    local_context_key, latest_attempt_generation, last_success_generation, latest_status)
                   VALUES (?, ?, 'snmp', 'unknown', '', 7, 7, 'scope_unknown')""",
                (device, kind),
            )
        conn.commit()

    expected = {"arp_evidence": [fact(device, context_type="unknown")],
                "fdb_evidence": [fact(device, context_type="unknown")]}
    manifest = {"type": "current_endpoint", "version": 1, "target_ip": "192.0.2.1",
                "context": {"authorized_device_ids": [device]}, "evidence": expected}
    monkeypatch.setattr(evidence, "find_current_endpoint_evidence", lambda *a, **kw: deepcopy(expected))

    collector = get_db_connection()
    publisher = get_db_connection()
    try:
        # A real FOR UPDATE blocks the publisher's FOR SHARE NOWAIT.
        collector.execute(
            "SELECT * FROM ipam_endpoint_collection_states WHERE device_id=? AND observation_source='arp' FOR UPDATE",
            (device,),
        ).fetchone()
        assert tasks._dependency_manifest_current_in_transaction(publisher, manifest, lock=True) == (
            False, ["dependency_changed:current_endpoint"],
        )
        # The savepoint must restore the transaction after the PG lock error.
        assert publisher.execute("SELECT 1").fetchone()[0] == 1
        publisher.rollback()
        collector.rollback()

        assert tasks._dependency_manifest_current_in_transaction(publisher, manifest, lock=True) == (True, [])
        # The publication fence must prevent a collector from acquiring an
        # exclusive lock until publication commits or rolls back.
        with pytest.raises(LockNotAvailable):
            collector.execute(
                "SELECT * FROM ipam_endpoint_collection_states WHERE device_id=? AND observation_source='arp' FOR UPDATE NOWAIT",
                (device,),
            ).fetchone()
        collector.rollback()
        publisher.commit()
        collector.execute(
            """UPDATE ipam_endpoint_collection_states
               SET latest_attempt_generation=8, latest_status='running'
               WHERE device_id=? AND observation_source='arp'""", (device,),
        )
        collector.commit()
        assert tasks._dependency_manifest_current_in_transaction(publisher, manifest, lock=True) == (
            False, ["dependency_changed:current_endpoint"],
        )
    finally:
        publisher.rollback()
        collector.rollback()
        publisher.close()
        collector.close()
