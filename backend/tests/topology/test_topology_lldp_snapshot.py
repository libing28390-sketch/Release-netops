from __future__ import annotations

from datetime import datetime, timezone
import uuid

from database import get_db_connection
from services.topology_lldp_snapshot_service import (
    begin_lldp_snapshot_attempt,
    fail_lldp_snapshot_attempt,
    lldp_snapshot_versions,
)
from services.topology_service import _replace_device_observations


def _device(isolated_db) -> dict[str, str]:
    device_id = f"topology-lldp-source-{uuid.uuid4().hex}"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, platform, tenant_id) VALUES (?, ?, ?, ?)",
            (device_id, device_id, "h3c_comware", "tenant-lldp-test"),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": device_id, "hostname": device_id, "platform": "h3c_comware", "tenant_id": "tenant-lldp-test"}


def _insert_old_neighbor(device: dict[str, str]) -> str:
    observation_id = str(uuid.uuid4())
    collected_at = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO topology_observations (
                   id, source_device_id, source_hostname, source_port_raw,
                   source_port_normalized, neighbor_name_raw, neighbor_name_normalized,
                   target_port_raw, target_port_normalized, protocol, status,
                   raw_payload_json, collected_at, updated_at, match_status,
                   match_candidates_json, last_seen_at, miss_count, is_active
               ) VALUES (?, ?, ?, 'Gi1/0/48', 'gigabitethernet1/0/48',
                         'OLD-DIST', 'old-dist', 'Gi1/0/1', 'gigabitethernet1/0/1',
                         'lldp', 'active', '{}', ?, ?, 'unmatched', '[]', ?, 0, 1)""",
            (observation_id, device["id"], device["hostname"], collected_at, collected_at, collected_at),
        )
        conn.commit()
    finally:
        conn.close()
    return observation_id


def test_successful_empty_collection_stales_old_rows_and_completes_same_snapshot(isolated_db):
    device = _device(isolated_db)
    observation_id = _insert_old_neighbor(device)
    attempt = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))

    _replace_device_observations(
        device,
        [],
        None,
        snapshot_generation=attempt["generation"],
    )

    conn = get_db_connection()
    try:
        marker = conn.execute(
            """SELECT generation, state, snapshot_complete, observation_count
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""",
            (device["id"],),
        ).fetchone()
        old_observation = conn.execute(
            "SELECT status, is_active FROM topology_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    finally:
        conn.close()

    assert tuple(marker) == (attempt["generation"], "complete", True, 0)
    assert tuple(old_observation) == ("stale", False)


def test_failed_attempt_keeps_last_postgres_observation_but_fences_snapshot(isolated_db):
    device = _device(isolated_db)
    observation_id = _insert_old_neighbor(device)
    attempt = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))

    assert fail_lldp_snapshot_attempt(device["id"], attempt["generation"]) is True

    conn = get_db_connection()
    try:
        marker = conn.execute(
            "SELECT state, snapshot_complete FROM topology_device_lldp_snapshots WHERE device_id = ?",
            (device["id"],),
        ).fetchone()
        old_observation = conn.execute(
            "SELECT status, is_active FROM topology_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    finally:
        conn.close()

    assert tuple(marker) == ("failed", False)
    assert tuple(old_observation) == ("active", True)
