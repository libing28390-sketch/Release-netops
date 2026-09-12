from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from database import get_db_connection
from database.migrations import m0219_locator_v2_coordination as migration
from services import ip_locator_task_service as tasks


def _device_id() -> str:
    return f"locator-test-device-{uuid.uuid4().hex[:12]}"


def _dependency_manifest(
    observations: list[dict] | None = None,
    topology_snapshots: list[dict] | None = None,
) -> dict:
    topology = tasks.get_locator_dependency_generation("topology:global")
    assert topology is not None
    return {
        "version": 1,
        "contract_version": "test-contract-v1",
        "topology": {
            "key": topology["dependency_key"],
            "scope": topology["scope"],
            "generation": topology["generation"],
        },
        "observations": list(observations or []),
        "topology_snapshots": list(topology_snapshots or []),
    }


@pytest.fixture()
def device(isolated_db) -> str:
    device_id = _device_id()
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)", (device_id, device_id, "tenant-default"))
        conn.commit()
    finally:
        conn.close()
    return device_id


def test_m0219_is_additive_and_idempotent(isolated_db) -> None:
    conn = get_db_connection()
    try:
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = current_schema()
               AND table_name IN (
                   'locator_runs', 'locator_query_tasks', 'locator_run_tasks',
                   'locator_observations', 'network_device_access_slots',
                   'locator_history', 'locator_invalidation_outbox'
               )
             ORDER BY table_name
            """
        ).fetchall()
        assert [row[0] for row in rows] == [
            "locator_history",
            "locator_invalidation_outbox",
            "locator_observations",
            "locator_query_tasks",
            "locator_run_tasks",
            "locator_runs",
            "network_device_access_slots",
        ]
    finally:
        conn.close()


def test_query_key_dedup_and_shared_completion(device: str) -> None:
    first = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.10")
    second = tasks.create_locator_run(owner_id="user-b", target_ip="192.0.2.10")
    first_task = tasks.enqueue_locator_task(
        run_id=first["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
    )
    second_task = tasks.enqueue_locator_task(
        run_id=second["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
    )
    assert first_task["id"] == second_task["id"]
    assert second_task["deduplicated"] is True

    claimed = tasks.claim_locator_task(worker_id="worker-a")
    assert claimed is not None
    assert tasks.complete_locator_task(
        claimed["id"],
        worker_id="worker-a",
        lease_token=claimed["lease_token"],
        success=True,
        result={"mac": "0011.2233.4455"},
    ) is not None
    assert tasks.get_locator_run(first["id"], owner_id="user-a")["status"] == "completed"
    assert tasks.get_locator_run(second["id"], owner_id="user-b")["status"] == "completed"

    refreshed = tasks.enqueue_locator_task(
        run_id=first["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
        force_requeue=True,
    )
    assert refreshed["id"] == first_task["id"]
    assert refreshed["status"] == "pending"


def test_late_worker_cannot_complete_reclaimed_task(device: str) -> None:
    run = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.11")
    queued = tasks.enqueue_locator_task(
        run_id=run["id"],
        operation="route",
        device_id=device,
        target_ip="192.0.2.11",
    )
    claimed = tasks.claim_locator_task(worker_id="worker-a", lease_seconds=1)
    assert claimed and claimed["id"] == queued["id"]

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_query_tasks SET lease_until = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(seconds=1), queued["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    replacement = tasks.claim_locator_task(worker_id="worker-b")
    assert replacement and replacement["id"] == queued["id"]
    assert tasks.complete_locator_task(
        queued["id"],
        worker_id="worker-a",
        lease_token=claimed["lease_token"],
        success=True,
        result={"late": True},
    ) is None
    assert tasks.complete_locator_task(
        replacement["id"],
        worker_id="worker-b",
        lease_token=replacement["lease_token"],
        success=True,
        result={"current": True},
    ) is not None


def test_cancel_detaches_one_subscriber_without_cancelling_shared_task(device: str) -> None:
    first = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.12")
    second = tasks.create_locator_run(owner_id="user-b", target_ip="192.0.2.12")
    kwargs = {
        "operation": "mac",
        "device_id": device,
        "target_ip": "192.0.2.12",
        "target_mac": "0011.2233.4455",
    }
    first_task = tasks.enqueue_locator_task(run_id=first["id"], **kwargs)
    second_task = tasks.enqueue_locator_task(run_id=second["id"], **kwargs)
    assert first_task["id"] == second_task["id"]

    cancelled = tasks.cancel_locator_run(first["id"], owner_id="user-a")
    assert cancelled and cancelled["status"] == "cancelled"
    conn = get_db_connection()
    try:
        state = conn.execute("SELECT status FROM locator_query_tasks WHERE id = ?", (first_task["id"],)).fetchone()[0]
        assert state == "pending"
    finally:
        conn.close()


def test_observation_generation_ignores_late_fact(device: str) -> None:
    collected = datetime.now(timezone.utc).replace(microsecond=0)
    current = tasks.upsert_locator_observation(
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
        generation=2,
        collected_at=collected,
        records={"mac": "0011.2233.4455"},
    )
    stale = tasks.upsert_locator_observation(
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
        generation=1,
        collected_at=collected + timedelta(seconds=1),
        records={"mac": "0066.7788.99aa"},
    )
    assert current["generation"] == 2
    assert stale["stale_ignored"] is True
    assert stale["records"] == {"mac": "0011.2233.4455"}
    scoped = tasks.find_locator_observation(
        tenant_id="tenant-default",
        scope_hash="",
        network_domain_id="",
        site_id="",
        vrf_name="default",
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
    )
    assert scoped is not None
    assert scoped["records"] == {"mac": "0011.2233.4455"}
    assert tasks.find_locator_observation(
        tenant_id="other-tenant",
        scope_hash="",
        network_domain_id="",
        site_id="",
        vrf_name="default",
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
    ) is None


def test_changed_observations_increment_generation_and_enqueue_outbox_atomically(device: str) -> None:
    collected = datetime.now(timezone.utc).replace(microsecond=0)
    first = tasks.upsert_locator_observation(
        tenant_id="tenant-default",
        scope_hash="scope-invalidation",
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.77",
        collected_at=collected,
        records={"mac": "0011.2233.4455"},
    )
    unchanged = tasks.upsert_locator_observation(
        tenant_id="tenant-default",
        scope_hash="scope-invalidation",
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.77",
        collected_at=collected + timedelta(seconds=1),
        records={"mac": "0011.2233.4455"},
    )
    changed = tasks.upsert_locator_observation(
        tenant_id="tenant-default",
        scope_hash="scope-invalidation",
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.77",
        collected_at=collected + timedelta(seconds=2),
        records={"mac": "0066.7788.99aa"},
    )
    assert first["generation"] == 1
    assert unchanged["generation"] == 1
    assert changed["generation"] == 2
    assert tasks.has_pending_locator_invalidation(
        scope_hash="scope-invalidation",
        target_ip="192.0.2.77",
    ) is True

    conn = get_db_connection()
    try:
        events = conn.execute(
            """SELECT generation, event_type, payload_json->>'target_ip'
                 FROM locator_invalidation_outbox
                WHERE scope_hash = ?
                ORDER BY generation""",
            ("scope-invalidation",),
        ).fetchall()
    finally:
        conn.close()
    assert [int(row[0]) for row in events] == [1, 2]
    assert [row[1] for row in events] == ["fact_created", "fact_changed"]
    assert all(row[2] == "192.0.2.77" for row in events)


@pytest.mark.parametrize("kind", ["arp", "mac"])
def test_complete_locator_snapshot_tombstones_only_missing_facts_in_exact_scope(
    device: str,
    isolated_db,
    kind: str,
) -> None:
    collected_at = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot_at = collected_at + timedelta(seconds=5)
    action_version = "snapshot-action-v1"
    scope = {
        "tenant_id": "tenant-default",
        "scope_hash": "snapshot-reconcile-scope",
        "network_domain_id": "network-a",
        "site_id": "site-a",
        "vrf_name": "blue",
        "device_id": device,
        "observation_kind": kind,
        "action_version": action_version,
        "source": "ssh_cli",
    }
    present_target, missing_target = (
        ("192.0.2.78", "192.0.2.77")
        if kind == "arp"
        else ("001122334466", "001122334455")
    )

    def upsert_target(target: str, *, observed_at=collected_at, target_kind=kind, **scope_overrides):
        selected_scope = {**scope, "observation_kind": target_kind, **scope_overrides}
        target_fields = (
            {"target_ip": target, "records": {"ip": target, "mac": "00aabbccddee"}}
            if target_kind == "arp"
            else {"target_mac": target, "records": [{"mac": target, "port": "Gi1/0/1", "vlan": "10"}]}
        )
        return tasks.upsert_locator_observation(
            **selected_scope,
            **target_fields,
            collected_at=observed_at,
        )

    present = upsert_target(present_target)
    missing = upsert_target(missing_target)
    mismatch_specs = [
        {"tenant_id": "tenant-other"},
        {"scope_hash": "another-scope"},
        {"network_domain_id": "network-other"},
        {"site_id": "site-other"},
        {"vrf_name": "red"},
        {"action_version": "different-action-v1"},
        {"source": "another-source"},
    ]
    other_device = _device_id()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)",
            (other_device, other_device, "tenant-default"),
        )
        conn.commit()
    finally:
        conn.close()
    mismatch_specs.append({"device_id": other_device})
    mismatched = []
    for index, overrides in enumerate(mismatch_specs):
        target = (
            f"192.0.2.{120 + index}"
            if kind == "arp"
            else f"00112233{0xA100 + index:04x}"
        )
        mismatched.append(upsert_target(target, **overrides))
    other_kind = "mac" if kind == "arp" else "arp"
    other_action_target = "00112233a200" if other_kind == "mac" else "192.0.2.150"
    mismatched.append(upsert_target(other_action_target, target_kind=other_kind))
    newer_target = "192.0.2.119" if kind == "arp" else "001122334477"
    newer = upsert_target(newer_target, observed_at=snapshot_at + timedelta(seconds=1))

    snapshot_records = (
        [{"ip": present_target, "mac": "001122334466", "interface": "Vlan10"}]
        if kind == "arp"
        else [{"mac": present_target, "port": "Gi1/0/2", "vlan": "20"}]
    )
    tasks.upsert_locator_observation(
        **scope,
        records=snapshot_records,
        coverage="full",
        collected_at=snapshot_at,
    )

    result = tasks.reconcile_locator_snapshot_absences(
        tenant_id=scope["tenant_id"],
        scope_hash=scope["scope_hash"],
        network_domain_id=scope["network_domain_id"],
        site_id=scope["site_id"],
        vrf_name=scope["vrf_name"],
        device_id=device,
        observation_kind=kind,
        records=snapshot_records,
        snapshot_status={"status": "found", "coverage": "full"},
        collected_at=snapshot_at,
        action_version=action_version,
        source="ssh_cli",
    )

    assert result["applied"] is True
    assert result["revoked_count"] == 1
    revoked = tasks.get_locator_observation(missing["observation_key"], include_expired=True)
    retained = tasks.get_locator_observation(present["observation_key"], include_expired=True)
    assert revoked["generation"] == missing["generation"] + 1
    assert revoked["records"]["not_found"] is True
    assert revoked["records"]["prior_records"] == missing["records"]
    assert datetime.fromisoformat(revoked["retain_until"]) >= datetime.fromisoformat(missing["retain_until"])
    assert retained["generation"] == present["generation"]
    assert retained["records"] == present["records"]
    newer_current = tasks.get_locator_observation(newer["observation_key"], include_expired=True)
    assert newer_current["generation"] == newer["generation"]
    assert newer_current["records"] == newer["records"]
    for old_fact in mismatched:
        current = tasks.get_locator_observation(old_fact["observation_key"], include_expired=True)
        assert current["generation"] == old_fact["generation"]
        assert current["records"] == old_fact["records"]

    conn = get_db_connection()
    try:
        event = conn.execute(
            """SELECT generation, event_type, status, payload_json->>'reason'
                 FROM locator_invalidation_outbox
                WHERE entity_id = ? AND event_type = 'fact_invalidated'""",
            (missing["observation_key"],),
        ).fetchone()
    finally:
        conn.close()
    assert event is not None
    assert int(event[0]) == revoked["generation"]
    assert event[1] == "fact_invalidated"
    assert event[2] == "pending"
    assert event[3] == "missing_from_complete_full_snapshot"


@pytest.mark.parametrize("kind", ["arp", "mac"])
def test_empty_complete_not_found_snapshot_retracts_old_positive_facts(
    device: str,
    kind: str,
) -> None:
    collected_at = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot_at = collected_at + timedelta(seconds=3)
    target = "192.0.2.90" if kind == "arp" else "001122334499"
    scope = {
        "tenant_id": "tenant-default",
        "scope_hash": "empty-snapshot-scope",
        "network_domain_id": "network-empty",
        "site_id": "site-empty",
        "vrf_name": "default",
        "device_id": device,
        "observation_kind": kind,
        "action_version": "ip-locator-cli-v1",
        "source": "ssh_cli",
    }
    target_fields = (
        {"target_ip": target, "records": {"ip": target, "mac": "001122334499"}}
        if kind == "arp"
        else {"target_mac": target, "records": [{"mac": target, "port": "Gi1/0/1"}]}
    )
    old = tasks.upsert_locator_observation(
        **scope,
        **target_fields,
        collected_at=collected_at,
    )
    tasks.upsert_locator_observation(
        **scope,
        records=[],
        coverage="full",
        collected_at=snapshot_at,
    )

    result = tasks.reconcile_locator_snapshot_absences(
        tenant_id=scope["tenant_id"],
        scope_hash=scope["scope_hash"],
        network_domain_id=scope["network_domain_id"],
        site_id=scope["site_id"],
        vrf_name=scope["vrf_name"],
        device_id=device,
        observation_kind=kind,
        records=[],
        snapshot_status={"status": "not_found", "coverage": "full"},
        collected_at=snapshot_at,
        action_version=scope["action_version"],
        source="ssh_cli",
    )

    assert result["applied"] is True
    assert result["revoked_count"] == 1
    tombstone = tasks.get_locator_observation(old["observation_key"], include_expired=True)
    assert tombstone["generation"] == old["generation"] + 1
    assert tombstone["records"]["not_found"] is True
    assert tombstone["records"]["prior_records"] == old["records"]
    assert datetime.fromisoformat(tombstone["retain_until"]) >= datetime.fromisoformat(old["retain_until"])
    expected_audit_retain = timedelta(seconds=1800 if kind == "arp" else 900)
    assert datetime.fromisoformat(tombstone["retain_until"]) >= snapshot_at + expected_audit_retain


@pytest.mark.parametrize(
    "snapshot_status",
    [
        {"status": "found", "coverage": "targeted"},
        {"status": "found", "coverage": "partial"},
        {"status": "query_failed", "coverage": "full"},
        {"status": "parse_incomplete", "coverage": "full"},
        {},
    ],
)
def test_incomplete_or_targeted_snapshot_never_retracts_facts(
    device: str,
    snapshot_status: dict,
) -> None:
    collected_at = datetime.now(timezone.utc).replace(microsecond=0)
    scope = {
        "tenant_id": "tenant-default",
        "scope_hash": "incomplete-snapshot-scope",
        "network_domain_id": "network-incomplete",
        "site_id": "site-incomplete",
        "vrf_name": "default",
        "device_id": device,
        "observation_kind": "arp",
        "action_version": "ip-locator-cli-v1",
        "source": "ssh_cli",
    }
    old = tasks.upsert_locator_observation(
        **scope,
        target_ip="192.0.2.91",
        records={"ip": "192.0.2.91", "mac": "001122334491"},
        collected_at=collected_at,
    )

    result = tasks.reconcile_locator_snapshot_absences(
        tenant_id=scope["tenant_id"],
        scope_hash=scope["scope_hash"],
        network_domain_id=scope["network_domain_id"],
        site_id=scope["site_id"],
        vrf_name=scope["vrf_name"],
        device_id=device,
        observation_kind="arp",
        records=[{"ip": "192.0.2.92", "mac": "001122334492"}],
        snapshot_status=snapshot_status,
        collected_at=collected_at + timedelta(seconds=5),
        action_version=scope["action_version"],
        source="ssh_cli",
    )

    assert result["applied"] is False
    current = tasks.get_locator_observation(old["observation_key"], include_expired=True)
    assert current["generation"] == old["generation"]
    assert current["records"] == old["records"]
    conn = get_db_connection()
    try:
        events = conn.execute(
            "SELECT count(*) FROM locator_invalidation_outbox WHERE entity_id = ? AND event_type = 'fact_invalidated'",
            (old["observation_key"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert events == 0


def test_deployment_global_cli_slots_are_shared_and_token_guarded(isolated_db) -> None:
    first = tasks.acquire_global_access_lease(
        owner_id="locator-worker-a",
        run_id="run-a",
        capacity=1,
        lease_seconds=90,
    )
    second = tasks.acquire_global_access_lease(
        owner_id="locator-worker-b",
        run_id="run-b",
        capacity=1,
        lease_seconds=90,
    )

    assert first is not None
    assert second is None
    assert tasks.release_global_access_lease(
        owner_id="locator-worker-b",
        lease_token=first["lease_token"],
        slot_id=first["slot_id"],
    ) is False
    assert tasks.release_global_access_lease(
        owner_id="locator-worker-a",
        lease_token=first["lease_token"],
        slot_id=first["slot_id"],
    ) is True
    assert tasks.acquire_global_access_lease(
        owner_id="locator-worker-b",
        run_id="run-b",
        capacity=1,
        lease_seconds=90,
    ) is not None


def test_durable_run_claim_is_exclusive_and_completion_is_fenced(isolated_db) -> None:
    run = tasks.create_locator_run(owner_id="user-run-worker", target_ip="192.0.2.99")
    claimed = tasks.claim_locator_run(run["id"], worker_id="worker-a", lease_seconds=240)
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["claim_lease_token"]
    assert tasks.claim_locator_run(run["id"], worker_id="worker-b") is None

    completed = tasks.save_locator_run_result(
        run["id"],
        result={"conclusion": "arp_only"},
        status="partial",
        lease_owner="worker-a",
        lease_token=claimed["claim_lease_token"],
    )
    assert completed is not None
    assert completed["status"] == "partial"
    assert "lease_token" not in completed


def test_expired_run_lease_is_reclaimed_by_a_restarted_worker(isolated_db) -> None:
    run = tasks.create_locator_run(owner_id="user-run-restart", target_ip="192.0.2.111")
    first = tasks.claim_locator_run(run["id"], worker_id="worker-before-restart", lease_seconds=30)
    assert first is not None
    old_token = first["claim_lease_token"]
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_runs SET lease_until = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(seconds=1), run["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    reclaimed = tasks.claim_locator_run(
        run["id"],
        worker_id="worker-after-restart",
        lease_seconds=30,
    )

    assert reclaimed is not None
    assert reclaimed["status"] == "running"
    assert reclaimed["claim_lease_owner"] == "worker-after-restart"
    assert reclaimed["claim_lease_token"] != old_token


def test_run_completion_preserves_immutable_authorized_device_scope(isolated_db) -> None:
    run = tasks.create_locator_run(
        owner_id="user-run-scope",
        target_ip="192.0.2.100",
        tenant_id="tenant-run-scope",
        site_id="site-run-scope",
        initial_stats={"authorized_device_ids": ["core-1", "access-2"]},
    )
    claimed = tasks.claim_locator_run(run["id"], worker_id="worker-run-scope", lease_seconds=30)
    assert claimed is not None

    completed = tasks.save_locator_run_result(
        run["id"],
        result={
            "conclusion": "managed_access_confirmed",
            "dependency_manifest": _dependency_manifest(),
        },
        status="completed",
        stats={"conclusion": "managed_access_confirmed", "coverage_gaps": []},
        lease_owner="worker-run-scope",
        lease_token=claimed["claim_lease_token"],
    )

    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["dependency_manifest"]["topology"]["scope"] == "global"
    assert completed["stats"]["authorized_device_ids"] == ["core-1", "access-2"]
    assert completed["stats"]["conclusion"] == "managed_access_confirmed"


@pytest.mark.parametrize("changed_dependency", ["topology", "observation", "topology_snapshot"])
def test_completed_run_is_fenced_when_dependency_changes_during_execution(
    isolated_db,
    device: str,
    changed_dependency: str,
) -> None:
    observation = None
    observation_entry = None
    topology_snapshot_entry = None
    if changed_dependency == "observation":
        observation = tasks.upsert_locator_observation(
            scope_hash="scope-run-fence",
            device_id=device,
            observation_kind="route",
            target_ip="192.0.2.222",
            records=[{"next_hop": "192.0.2.1"}],
            action_version="action:1",
            parser_version="parser:1",
            schema_version="schema:1",
        )
        observation_entry = {
            "observation_key": observation["observation_key"],
            "generation": observation["generation"],
            "action_version": observation["action_version"],
            "parser_version": observation["parser_version"],
            "schema_version": observation["schema_version"],
        }
    elif changed_dependency == "topology_snapshot":
        topology_snapshot_entry = {
            "device_id": device,
            "generation": 4,
            "action_version": "topology-action:1",
            "parser_version": "topology-parser:1",
            "schema_version": "topology-schema:1",
        }
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO topology_device_lldp_snapshots (
                       device_id, generation, state, snapshot_complete,
                       observation_count, completed_at, action_version,
                       parser_version, schema_version, updated_at
                   ) VALUES (?, 4, 'complete', TRUE, 0, clock_timestamp(), ?, ?, ?, clock_timestamp())""",
                (
                    device,
                    topology_snapshot_entry["action_version"],
                    topology_snapshot_entry["parser_version"],
                    topology_snapshot_entry["schema_version"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    run = tasks.create_locator_run(owner_id="user-run-fence", target_ip="192.0.2.222")
    claimed = tasks.claim_locator_run(run["id"], worker_id="worker-run-fence", lease_seconds=30)
    assert claimed is not None
    manifest = _dependency_manifest(
        [observation_entry] if observation_entry else [],
        [topology_snapshot_entry] if topology_snapshot_entry else [],
    )

    if changed_dependency == "topology":
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO topology_links (id) VALUES (?)",
                (f"locator-fence:{uuid.uuid4().hex}",),
            )
            conn.commit()
        finally:
            conn.close()
    elif changed_dependency == "observation":
        assert observation is not None
        tasks.upsert_locator_observation(
            scope_hash="scope-run-fence",
            device_id=device,
            observation_kind="route",
            target_ip="192.0.2.222",
            records=[{"next_hop": "192.0.2.254"}],
            action_version="action:1",
            parser_version="parser:1",
            schema_version="schema:1",
        )
    else:
        conn = get_db_connection()
        try:
            conn.execute(
                """UPDATE topology_device_lldp_snapshots
                      SET generation = 5, state = 'collecting',
                          snapshot_complete = FALSE, updated_at = clock_timestamp()
                    WHERE device_id = ?""",
                (device,),
            )
            conn.commit()
        finally:
            conn.close()

    saved = tasks.save_locator_run_result(
        run["id"],
        result={"conclusion": "managed_access_confirmed", "dependency_manifest": manifest},
        status="completed",
        lease_owner="worker-run-fence",
        lease_token=claimed["claim_lease_token"],
    )

    assert saved is not None
    assert saved["status"] == "partial"
    assert saved["error_code"] == "DEPENDENCY_CHANGED"
    assert any(
        str(gap).startswith("dependency_changed:")
        for gap in saved["result"].get("coverage_gaps", [])
    )


def test_durable_run_worker_respects_deployment_active_run_limit(isolated_db) -> None:
    first = tasks.create_locator_run(owner_id="user-run-a", target_ip="192.0.2.101")
    second = tasks.create_locator_run(owner_id="user-run-b", target_ip="192.0.2.102")
    claimed = tasks.claim_locator_run(
        first["id"],
        worker_id="worker-cap-a",
        max_active_runs=1,
        lease_seconds=30,
    )
    assert claimed is not None
    assert tasks.claim_locator_run(
        second["id"],
        worker_id="worker-cap-b",
        max_active_runs=1,
        lease_seconds=30,
    ) is None
    tasks.save_locator_run_result(
        first["id"],
        result={"conclusion": "no_route"},
        status="failed",
        lease_owner="worker-cap-a",
        lease_token=claimed["claim_lease_token"],
    )
    assert tasks.claim_locator_run(
        second["id"],
        worker_id="worker-cap-b",
        max_active_runs=1,
        lease_seconds=30,
    ) is not None


def test_query_worker_can_claim_only_its_enqueued_task(device: str) -> None:
    first = tasks.enqueue_locator_task(
        operation="route",
        device_id=device,
        target_ip="192.0.2.201",
    )
    second = tasks.enqueue_locator_task(
        operation="route",
        device_id=device,
        target_ip="192.0.2.202",
    )

    claimed = tasks.claim_locator_task(
        worker_id="worker-specific-query",
        task_id=second["id"],
    )

    assert claimed is not None
    assert claimed["id"] == second["id"]
    assert tasks.get_locator_task(first["id"])["status"] == "pending"


def test_query_task_completed_output_is_shared_only_inside_grace(device: str) -> None:
    queued = tasks.enqueue_locator_task(
        operation="arp",
        device_id=device,
        target_ip="192.0.2.203",
    )
    claimed = tasks.claim_locator_task(
        worker_id="worker-query-output",
        task_id=queued["id"],
    )
    assert claimed is not None
    completed = tasks.complete_locator_task(
        queued["id"],
        worker_id="worker-query-output",
        lease_token=claimed["lease_token"],
        success=True,
        result={"value": {"ip": "192.0.2.203", "mac": "001122334455"}},
    )
    assert completed and completed["status"] == "succeeded"

    recent = tasks.enqueue_locator_task(
        operation="arp",
        device_id=device,
        target_ip="192.0.2.203",
        requeue_completed_after_seconds=10,
    )
    assert recent["id"] == queued["id"]
    assert recent["status"] == "succeeded"

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_query_tasks SET completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(seconds=15), queued["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    refreshed = tasks.enqueue_locator_task(
        operation="arp",
        device_id=device,
        target_ip="192.0.2.203",
        requeue_completed_after_seconds=10,
    )
    assert refreshed["id"] == queued["id"]
    assert refreshed["status"] == "pending"


def test_global_access_lease_can_be_renewed_without_losing_ownership(isolated_db) -> None:
    lease = tasks.acquire_global_access_lease(
        owner_id="locator-pool-a",
        run_id="locator-session-a",
        capacity=1,
        lease_seconds=1,
    )
    assert lease is not None
    assert tasks.renew_global_access_lease(
        owner_id="locator-pool-a",
        lease_token=lease["lease_token"],
        slot_id=lease["slot_id"],
        lease_seconds=30,
    ) is True
    assert tasks.acquire_global_access_lease(
        owner_id="locator-pool-b",
        run_id="locator-session-b",
        capacity=1,
        lease_seconds=1,
    ) is None


def test_cancelled_last_subscriber_does_not_persist_late_cli_output(device: str) -> None:
    run = tasks.create_locator_run(owner_id="user-cancel-query", target_ip="192.0.2.204")
    queued = tasks.enqueue_locator_task(
        run_id=run["id"],
        owner_id="user-cancel-query",
        required=False,
        operation="route",
        device_id=device,
        target_ip="192.0.2.204",
    )
    claimed = tasks.claim_locator_task(worker_id="worker-cancel-query", task_id=queued["id"])
    assert claimed is not None
    assert tasks.cancel_locator_run(run["id"], owner_id="user-cancel-query")["status"] == "cancelled"

    completed = tasks.complete_locator_task(
        queued["id"],
        worker_id="worker-cancel-query",
        lease_token=claimed["lease_token"],
        success=True,
        result={"value": "late route output"},
    )
    assert completed is not None
    assert completed["status"] == "cancelled"
    assert completed["result"] == {}


def test_locator_task_cleanup_scrubs_raw_results_then_prunes_old_detail(device: str) -> None:
    run = tasks.create_locator_run(owner_id="user-task-retention", target_ip="192.0.2.205")
    queued = tasks.enqueue_locator_task(
        run_id=run["id"],
        owner_id="user-task-retention",
        required=False,
        operation="route",
        device_id=device,
        target_ip="192.0.2.205",
    )
    claimed = tasks.claim_locator_task(worker_id="worker-task-retention", task_id=queued["id"])
    assert claimed is not None
    tasks.complete_locator_task(
        queued["id"],
        worker_id="worker-task-retention",
        lease_token=claimed["lease_token"],
        success=True,
        result={"value": "transient raw CLI output", "collected_at": "2026-09-12T00:00:00+00:00"},
    )

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_query_tasks SET completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(minutes=5), queued["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    scrubbed = tasks.cleanup_locator_tasks(result_retention_seconds=60, task_retention_days=7)
    assert scrubbed["results_scrubbed"] == 1
    assert scrubbed["tasks_deleted"] == 0
    assert tasks.get_locator_task(queued["id"])["result"] == {}

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_query_tasks SET completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(days=8), queued["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    pruned = tasks.cleanup_locator_tasks(result_retention_seconds=60, task_retention_days=7)
    assert pruned["tasks_deleted"] == 1
    assert tasks.get_locator_task(queued["id"]) is None
