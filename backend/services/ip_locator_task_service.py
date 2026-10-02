"""Durable PostgreSQL coordination for the V2 IP locator.

The trace engine does network I/O; this module owns the state around that I/O.
It keeps runs separate from shared query tasks, so two authorized requests can
subscribe to one device query without one request being able to cancel the
other.  Every race-sensitive transition is committed in a short PostgreSQL
transaction and uses row locks.  No database transaction is held while a
worker talks to a network device.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import uuid
from typing import Any, Iterable, Mapping

from database import _USE_PG, get_db_connection


logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "tenant-default"
DEFAULT_VRF_NAME = "default"
DEFAULT_TASK_LEASE_SECONDS = 90
DEFAULT_DEVICE_LEASE_SECONDS = 90
DEFAULT_RUN_DEADLINE_SECONDS = 180
DEFAULT_RESULT_FRESH_SECONDS = 120
DEFAULT_RESULT_RETAIN_SECONDS = 900
DEFAULT_HISTORY_RETAIN_SECONDS = 30 * 24 * 60 * 60
DEFAULT_ARP_FRESH_SECONDS = 300
DEFAULT_ARP_RETAIN_SECONDS = 1800
DEFAULT_MAC_RETAIN_SECONDS = 900

RUN_TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "needs_context"}
TASK_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


class LocatorTaskError(RuntimeError):
    """Base error for coordination failures."""


class LocatorPermissionError(PermissionError, LocatorTaskError):
    """Raised when a run is accessed by a different owner."""


class LocatorLeaseLost(LocatorTaskError):
    """Raised when a worker tries to update a lease it no longer owns."""


def _require_postgres() -> None:
    if not _USE_PG:
        raise RuntimeError("The V2 IP locator task service requires PostgreSQL")


@contextmanager
def _transaction():
    """Yield a connection and rollback on errors.

    The caller controls the commit point.  Keeping this helper small makes it
    possible for tests to replace ``get_db_connection`` with a disposable
    PostgreSQL connection while preserving production transaction semantics.
    """

    _require_postgres()
    conn = get_db_connection()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            logger.debug("Unable to rollback locator transaction", exc_info=True)
        raise
    finally:
        conn.close()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _as_utc(value: datetime | str | None, *, fallback: datetime | None = None) -> datetime:
    if value is None:
        return fallback or _utc_now()
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid UTC timestamp: {value!r}") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | str | None, *, fallback: datetime | None = None) -> str:
    return _as_utc(value, fallback=fallback).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return list(value) if isinstance(value, tuple) else value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _public_row(row: Any) -> dict[str, Any]:
    """Convert a PostgreSQL row into a JSON-safe service result."""

    result = _row_dict(row)
    for key in (
        "deadline_at", "available_at", "lease_until", "created_at", "updated_at",
        "started_at", "completed_at", "cancel_requested_at", "collected_at",
        "fresh_until", "retain_until", "generated_at", "processed_at",
        "last_acquired_at",
    ):
        if key in result and result[key] is not None:
            result[key] = _iso(result[key])
    for key in (
        "result_json", "stats_json", "target_json", "payload_json", "records_json",
        "dependency_manifest_json",
    ):
        if key in result:
            result[key[:-5] if key.endswith("_json") else key] = _decode_json(result.pop(key), {})
    return result


def _non_empty(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _dependency_manifest_current_in_transaction(
    conn,
    manifest: Mapping[str, Any],
    *,
    lock: bool,
) -> tuple[bool, list[str]]:
    """Compare a captured topology/observation manifest with PG authority."""

    gaps: list[str] = []
    topology = manifest.get("topology")
    if not isinstance(topology, Mapping):
        return False, ["dependency_manifest_missing_topology"]
    if (
        _non_empty(topology.get("key")) != "topology:global"
        or _non_empty(topology.get("scope")) != "global"
    ):
        gaps.append("dependency_manifest_invalid_topology_scope")
    try:
        expected_topology_generation = int(topology.get("generation"))
    except (TypeError, ValueError):
        expected_topology_generation = 0
    if expected_topology_generation <= 0:
        gaps.append("dependency_manifest_missing_topology_generation")
    else:
        suffix = " FOR UPDATE" if lock else ""
        row = conn.execute(
            "SELECT generation FROM locator_dependency_generations "
            "WHERE dependency_key = ?" + suffix,
            ("topology:global",),
        ).fetchone()
        if row is None or int(row[0] or 0) != expected_topology_generation:
            gaps.append("dependency_changed:topology:global")

    observations = manifest.get("observations")
    if not isinstance(observations, list):
        gaps.append("dependency_manifest_invalid_observations")
        observations = []
    seen: set[str] = set()
    for dependency in sorted(
        (item for item in observations if isinstance(item, Mapping)),
        key=lambda item: _non_empty(item.get("observation_key")),
    ):
        key = _non_empty(dependency.get("observation_key"))
        if not key or key in seen:
            gaps.append("dependency_manifest_invalid_observation_key")
            continue
        seen.add(key)
        try:
            expected_generation = int(dependency.get("generation"))
        except (TypeError, ValueError):
            expected_generation = 0
        expected_versions = tuple(
            _non_empty(dependency.get(name))
            for name in ("action_version", "parser_version", "schema_version")
        )
        if expected_generation <= 0 or not all(expected_versions):
            gaps.append(f"dependency_manifest_incomplete_observation:{key}")
            continue
        suffix = " FOR UPDATE" if lock else ""
        current = conn.execute(
            """SELECT generation, action_version, parser_version, schema_version
                 FROM locator_observations WHERE observation_key = ?""" + suffix,
            (key,),
        ).fetchone()
        if current is None or (
            int(current[0] or 0) != expected_generation
            or tuple(_non_empty(current[index]) for index in (1, 2, 3)) != expected_versions
        ):
            gaps.append(f"dependency_changed:observation:{key}")
    if any(not isinstance(item, Mapping) for item in observations):
        gaps.append("dependency_manifest_invalid_observation_entry")

    topology_snapshots = manifest.get("topology_snapshots", [])
    if not isinstance(topology_snapshots, list):
        gaps.append("dependency_manifest_invalid_topology_snapshots")
        topology_snapshots = []
    seen_snapshot_devices: set[str] = set()
    for dependency in sorted(
        (item for item in topology_snapshots if isinstance(item, Mapping)),
        key=lambda item: _non_empty(item.get("device_id")),
    ):
        device_id = _non_empty(dependency.get("device_id"))
        if not device_id or device_id in seen_snapshot_devices:
            gaps.append("dependency_manifest_invalid_topology_snapshot_device")
            continue
        seen_snapshot_devices.add(device_id)
        try:
            expected_generation = int(dependency.get("generation"))
        except (TypeError, ValueError):
            expected_generation = 0
        expected_versions = tuple(
            _non_empty(dependency.get(name))
            for name in ("action_version", "parser_version", "schema_version")
        )
        if expected_generation <= 0 or not all(expected_versions):
            gaps.append(f"dependency_manifest_incomplete_topology_snapshot:{device_id}")
            continue
        suffix = " FOR UPDATE" if lock else ""
        current = conn.execute(
            """SELECT generation, state, snapshot_complete,
                      action_version, parser_version, schema_version
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""" + suffix,
            (device_id,),
        ).fetchone()
        if current is None or (
            int(current[0] or 0) != expected_generation
            or str(current[1] or "") != "complete"
            or not bool(current[2])
            or tuple(_non_empty(current[index]) for index in (3, 4, 5)) != expected_versions
        ):
            gaps.append(f"dependency_changed:topology_snapshot:{device_id}")
    return not gaps, gaps


def get_locator_dependency_generation(
    dependency_key: str = "topology:global",
) -> dict[str, Any] | None:
    """Read the PostgreSQL-owned dependency generation for cache fencing."""

    key = _non_empty(dependency_key)
    with _transaction() as conn:
        row = conn.execute(
            "SELECT dependency_key, scope, generation, updated_at "
            "FROM locator_dependency_generations WHERE dependency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        result = _public_row(row)
        return result


def locator_dependency_manifest_is_current(manifest: Mapping[str, Any]) -> bool:
    """Best-effort currentness check used before reusing Redis projections.

    Run finalization repeats the same comparison while locking the dependency
    rows in the transaction that publishes the result.
    """

    if not isinstance(manifest, Mapping):
        return False
    try:
        with _transaction() as conn:
            valid, _ = _dependency_manifest_current_in_transaction(conn, manifest, lock=False)
            return valid
    except Exception:
        return False


def _normalize_vrf(value: Any) -> str:
    return _non_empty(value, DEFAULT_VRF_NAME)


def _normalize_vlan(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        vlan = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid VLAN id: {value!r}") from exc
    if vlan < 0 or vlan > 4_294_967_295:
        raise ValueError(f"Invalid VLAN id: {value!r}")
    return vlan


def build_locator_query_key(
    *,
    operation: str,
    deployment_id: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    start_device_id: str = "",
    device_id: str = "",
    target_ip: str = "",
    target_mac: str = "",
    bridge_domain: str = "",
    vlan_id: int | str | None = None,
    mode: str = "normal",
    authorization_scope_hash: str = "",
    action_version: str = "",
    parser_version: str = "",
    target: Mapping[str, Any] | None = None,
) -> str:
    """Build a stable, scoped task deduplication key.

    Authorization scope is part of the key.  This prevents an accidentally
    broad shared task from exposing evidence across tenants or user scopes;
    each run still performs its own authorization check when reading results.
    """

    operation = _non_empty(operation).lower()
    if operation not in {"route", "arp", "mac", "topology", "interface", "neighbor"}:
        raise ValueError(f"Unsupported locator operation: {operation!r}")
    selected_mode = _non_empty(mode, "normal").lower()
    if selected_mode not in {"normal", "force_refresh"}:
        raise ValueError(f"Unsupported locator task mode: {selected_mode!r}")
    material = {
        "version": "locator-v2",
        "deployment_id": _non_empty(deployment_id),
        "tenant_id": _non_empty(tenant_id, DEFAULT_TENANT_ID),
        "scope_hash": _non_empty(scope_hash),
        "network_domain_id": _non_empty(network_domain_id),
        "site_id": _non_empty(site_id),
        "vrf_name": _normalize_vrf(vrf_name),
        "start_device_id": _non_empty(start_device_id),
        "device_id": _non_empty(device_id),
        "operation": operation,
        "target_ip": _non_empty(target_ip),
        "target_mac": _non_empty(target_mac).lower(),
        "bridge_domain": _non_empty(bridge_domain),
        "vlan_id": _normalize_vlan(vlan_id),
        "mode": selected_mode,
        "authorization_scope_hash": _non_empty(authorization_scope_hash),
        "action_version": _non_empty(action_version),
        "parser_version": _non_empty(parser_version),
        "target": dict(target or {}),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "locator-v2:" + sha256(encoded.encode("utf-8")).hexdigest()


def _run_result(row: Any) -> dict[str, Any]:
    result = _public_row(row)
    # Run lease ownership is worker-internal and is never returned by GET APIs.
    result.pop("lease_owner", None)
    result.pop("lease_token", None)
    result.pop("lease_until", None)
    return result


def _fetch_run(conn, run_id: str, *, owner_id: str | None = None, lock: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute("SELECT * FROM locator_runs WHERE id = ?" + suffix, (_non_empty(run_id),)).fetchone()
    if row is None:
        return None
    result = _run_result(row)
    if owner_id is not None and str(result.get("owner_id") or "") != _non_empty(owner_id):
        raise LocatorPermissionError("The locator run is not owned by this user")
    return result


def create_locator_run(
    *,
    owner_id: str,
    target_ip: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    start_device_id: str = "",
    mode: str = "normal",
    force_refresh: bool = False,
    authorization_scope_hash: str = "",
    deployment_id: str = "",
    deadline_seconds: int = DEFAULT_RUN_DEADLINE_SECONDS,
    deadline_at: datetime | str | None = None,
    run_id: str | None = None,
    initial_stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an owner-scoped run idempotently by its explicit run id."""

    owner = _non_empty(owner_id)
    ip = _non_empty(target_ip)
    if not owner:
        raise ValueError("owner_id is required")
    if not ip:
        raise ValueError("target_ip is required")
    selected_mode = "force_refresh" if force_refresh else _non_empty(mode, "normal").lower()
    if selected_mode not in {"normal", "force_refresh"}:
        raise ValueError(f"Unsupported locator run mode: {selected_mode!r}")
    seconds = int(deadline_seconds)
    if seconds <= 0:
        raise ValueError("deadline_seconds must be positive")
    now = _utc_now()
    due = _as_utc(deadline_at, fallback=now + timedelta(seconds=seconds))
    if due <= now:
        raise ValueError("deadline_at must be in the future")
    identifier = _non_empty(run_id) or f"locator-run:{uuid.uuid4().hex}"

    with _transaction() as conn:
        conn.execute(
            """
            INSERT INTO locator_runs (
                id, owner_id, deployment_id, tenant_id, scope_hash, network_domain_id, site_id,
                vrf_name, target_ip, start_device_id, mode, force_refresh,
                authorization_scope_hash, status, deadline_at, result_json,
                stats_json, error_code, error_message, version, created_at,
                started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, '{}'::jsonb,
                      ?::jsonb, '', '', 1, ?, NULL, NULL, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                identifier,
                owner,
                _non_empty(deployment_id),
                _non_empty(tenant_id, DEFAULT_TENANT_ID),
                _non_empty(scope_hash),
                _non_empty(network_domain_id),
                _non_empty(site_id),
                _normalize_vrf(vrf_name),
                ip,
                _non_empty(start_device_id),
                selected_mode,
                bool(force_refresh),
                _non_empty(authorization_scope_hash),
                due,
                _json(initial_stats or {}),
                now,
                now,
            ),
        )
        result = _fetch_run(conn, identifier, owner_id=owner)
        if result is None:
            raise LocatorTaskError("Unable to create locator run")
        conn.commit()
        return result


def get_locator_run(run_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    with _transaction() as conn:
        return _fetch_run(conn, run_id, owner_id=owner_id)


def renew_locator_run_lease(
    run_id: str,
    *,
    worker_id: str,
    lease_token: str,
    lease_seconds: int = 30,
) -> bool:
    now = _utc_now()
    next_until = now + timedelta(seconds=max(1, int(lease_seconds)))
    with _transaction() as conn:
        row = conn.execute(
            "SELECT deadline_at FROM locator_runs WHERE id = ? AND status = 'running' "
            "AND lease_owner = ? AND lease_token = ? FOR UPDATE",
            (_non_empty(run_id), _non_empty(worker_id), _non_empty(lease_token)),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        deadline = _as_utc(row[0], fallback=now)
        if deadline <= now:
            conn.rollback()
            return False
        next_until = min(next_until, deadline)
        updated = conn.execute(
            """UPDATE locator_runs SET lease_until = ?, updated_at = ?
                 WHERE id = ? AND status = 'running'
                   AND lease_owner = ? AND lease_token = ?""",
            (next_until, now, _non_empty(run_id), _non_empty(worker_id), _non_empty(lease_token)),
        ).rowcount
        conn.commit()
        return bool(updated)


def claim_locator_runs(
    *,
    worker_id: str,
    limit: int = 1,
    max_active_runs: int = 5,
    lease_seconds: int = 240,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Claim queued durable runs and reclaim workers whose leases expired."""
    worker = _non_empty(worker_id)
    if not worker:
        raise ValueError("worker_id is required")
    now = _utc_now()
    due = now + timedelta(seconds=max(1, int(lease_seconds)))
    selected_limit = max(1, int(limit))
    active_limit = max(1, int(max_active_runs))
    with _transaction() as conn:
        # Serialize claimers around the deployment-wide active-run count so
        # two workers cannot both observe the same free capacity.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('nexora:ip_locator_run_claim'))")
        conn.execute(
            """UPDATE locator_runs
                  SET status = 'failed', error_code = 'deadline_exceeded',
                      error_message = '定位任务超过截止时间', completed_at = COALESCE(completed_at, ?),
                      lease_owner = '', lease_token = '', lease_until = NULL,
                      updated_at = ?, version = version + 1
                WHERE status IN ('queued', 'running') AND deadline_at <= ?""",
            (now, now, now),
        )
        conn.execute(
            """UPDATE locator_runs
                  SET status = 'queued', lease_owner = '', lease_token = '',
                      lease_until = NULL, updated_at = ?, version = version + 1
                WHERE status = 'running' AND deadline_at > ?
                  AND (lease_until IS NULL OR lease_until <= ?)""",
            (now, now, now),
        )
        active_row = conn.execute(
            "SELECT COUNT(*) FROM locator_runs WHERE status = 'running' AND lease_until > ?",
            (now,),
        ).fetchone()
        active_count = int(active_row[0] or 0) if active_row else 0
        available_run_slots = max(0, active_limit - active_count)
        if available_run_slots <= 0:
            conn.commit()
            return []
        selected_limit = min(selected_limit, available_run_slots)
        if run_id:
            rows = conn.execute(
                """SELECT * FROM locator_runs
                    WHERE id = ? AND status = 'queued' AND deadline_at > ?
                    FOR UPDATE SKIP LOCKED""",
                (_non_empty(run_id), now),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM locator_runs
                    WHERE status = 'queued' AND deadline_at > ?
                    ORDER BY created_at, id
                    LIMIT ? FOR UPDATE SKIP LOCKED""",
                (now, selected_limit),
            ).fetchall()
        claims: list[dict[str, Any]] = []
        for row in rows:
            run = _row_dict(row)
            token = uuid.uuid4().hex
            identifier = _non_empty(run.get("id"))
            conn.execute(
                """UPDATE locator_runs
                      SET status = 'running', started_at = COALESCE(started_at, ?),
                          lease_owner = ?, lease_token = ?, lease_until = ?,
                          updated_at = ?, version = version + 1
                    WHERE id = ? AND status = 'queued'""",
                (now, worker, token, due, now, identifier),
            )
            claimed = _row_dict(conn.execute("SELECT * FROM locator_runs WHERE id = ?", (identifier,)).fetchone())
            public = _run_result(claimed)
            public["claim_lease_token"] = token
            public["claim_lease_owner"] = worker
            public["claim_lease_until"] = due.isoformat()
            claims.append(public)
        conn.commit()
        return claims


def claim_locator_run(
    run_id: str,
    *,
    worker_id: str,
    max_active_runs: int = 5,
    lease_seconds: int = 240,
) -> dict[str, Any] | None:
    claims = claim_locator_runs(
        worker_id=worker_id,
        limit=1,
        max_active_runs=max_active_runs,
        lease_seconds=lease_seconds,
        run_id=run_id,
    )
    return claims[0] if claims else None


def list_locator_run_tasks(run_id: str, *, owner_id: str | None = None) -> list[dict[str, Any]]:
    with _transaction() as conn:
        run = _fetch_run(conn, run_id, owner_id=owner_id)
        if run is None:
            return []
        rows = conn.execute(
            """
            SELECT r.*, t.query_key, t.operation, t.device_id, t.target_ip,
                   t.target_mac, t.status AS task_status, t.result_json,
                   t.error_code AS task_error_code, t.error_message AS task_error_message
              FROM locator_run_tasks r
              JOIN locator_query_tasks t ON t.id = r.task_id
             WHERE r.run_id = ?
             ORDER BY r.created_at, r.task_id
            """,
            (_non_empty(run_id),),
        ).fetchall()
        return [_public_row(row) for row in rows]


def _task_for_key(conn, query_key: str, *, lock: bool = False) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute("SELECT * FROM locator_query_tasks WHERE query_key = ?" + suffix, (query_key,)).fetchone()
    return _public_row(row) if row is not None else None


def get_locator_task(task_id: str, *, query_key: str | None = None) -> dict[str, Any] | None:
    """Read one shared task by id or its deterministic query key."""

    with _transaction() as conn:
        if query_key:
            row = conn.execute(
                "SELECT * FROM locator_query_tasks WHERE query_key = ?",
                (_non_empty(query_key),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM locator_query_tasks WHERE id = ?",
                (_non_empty(task_id),),
            ).fetchone()
        return _public_row(row) if row is not None else None


def subscribe_locator_run(
    run_id: str,
    task_id: str,
    *,
    owner_id: str | None = None,
    relation_role: str = "required",
    required: bool = True,
) -> bool:
    """Attach an existing shared task to a run without creating a task."""

    now = _utc_now()
    with _transaction() as conn:
        run = _fetch_run(conn, run_id, owner_id=owner_id, lock=True)
        if run is None or str(run.get("status") or "") == "cancelled":
            return False
        task = conn.execute(
            "SELECT id, status FROM locator_query_tasks WHERE id = ? FOR UPDATE",
            (_non_empty(task_id),),
        ).fetchone()
        if task is None:
            return False
        task_status = str(task[1] or "")
        relation_status = (
            "fulfilled" if task_status == "succeeded"
            else "failed" if task_status in {"failed", "expired"}
            else "subscribed"
        )
        conn.execute(
            """
            INSERT INTO locator_run_tasks
                (run_id, task_id, relation_role, required, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, task_id) DO UPDATE SET
                relation_role = excluded.relation_role,
                required = excluded.required,
                status = CASE
                    WHEN locator_run_tasks.status = 'detached' THEN excluded.status
                    ELSE locator_run_tasks.status
                END,
                updated_at = excluded.updated_at
            """,
            (_non_empty(run_id), _non_empty(task_id), _non_empty(relation_role, "required"), bool(required), relation_status, now, now),
        )
        if relation_status in {"fulfilled", "failed"}:
            _refresh_subscriber_runs(conn, _non_empty(task_id), now)
        conn.commit()
        return True


def _task_insert_values(
    *,
    task_id: str,
    query_key: str,
    operation: str,
    deployment_id: str,
    tenant_id: str,
    scope_hash: str,
    network_domain_id: str,
    site_id: str,
    vrf_name: str,
    start_device_id: str,
    device_id: str,
    target_ip: str,
    target_mac: str,
    bridge_domain: str,
    vlan_id: int | None,
    target: Mapping[str, Any] | None,
    authorization_scope_hash: str,
    action_version: str,
    parser_version: str,
    priority: int,
    available_at: datetime,
    deadline_at: datetime,
    payload: Mapping[str, Any] | None,
    now: datetime,
) -> tuple[Any, ...]:
    return (
        task_id,
        query_key,
        _non_empty(deployment_id),
        _non_empty(tenant_id, DEFAULT_TENANT_ID),
        _non_empty(scope_hash),
        _non_empty(network_domain_id),
        _non_empty(site_id),
        _normalize_vrf(vrf_name),
        _non_empty(start_device_id),
        operation,
        _non_empty(device_id) or None,
        _non_empty(target_ip),
        _non_empty(target_mac).lower(),
        _non_empty(bridge_domain),
        vlan_id,
        _json(target or {}),
        _non_empty(authorization_scope_hash),
        _non_empty(action_version),
        _non_empty(parser_version),
        max(0, int(priority)),
        available_at,
        deadline_at,
        _json(payload or {}),
        now,
        now,
    )


def _ensure_task_in_transaction(
    conn,
    *,
    run_id: str | None,
    owner_id: str | None,
    relation_role: str,
    required: bool,
    operation: str,
    mode: str,
    deployment_id: str,
    tenant_id: str,
    scope_hash: str,
    network_domain_id: str,
    site_id: str,
    vrf_name: str,
    start_device_id: str,
    device_id: str,
    target_ip: str,
    target_mac: str,
    bridge_domain: str,
    vlan_id: int | str | None,
    target: Mapping[str, Any] | None,
    authorization_scope_hash: str,
    action_version: str,
    parser_version: str,
    priority: int,
    available_at: datetime | str | None,
    deadline_at: datetime | str | None,
    deadline_seconds: int,
    payload: Mapping[str, Any] | None,
    query_key: str | None,
    force_requeue: bool,
    requeue_completed_after_seconds: int | None,
) -> tuple[dict[str, Any], bool]:
    normalized_operation = _non_empty(operation).lower()
    if normalized_operation not in {"route", "arp", "mac", "topology", "interface", "neighbor"}:
        raise ValueError(f"Unsupported locator operation: {normalized_operation!r}")
    vlan = _normalize_vlan(vlan_id)
    target_ip = _non_empty(target_ip)
    target_mac = _non_empty(target_mac).lower()
    key = query_key or build_locator_query_key(
        operation=normalized_operation,
        deployment_id=deployment_id,
        tenant_id=tenant_id,
        scope_hash=scope_hash,
        network_domain_id=network_domain_id,
        site_id=site_id,
        vrf_name=vrf_name,
        start_device_id=start_device_id,
        device_id=device_id,
        target_ip=target_ip,
        target_mac=target_mac,
        bridge_domain=bridge_domain,
        vlan_id=vlan,
        mode=mode,
        authorization_scope_hash=authorization_scope_hash,
        action_version=action_version,
        parser_version=parser_version,
        target=target,
    )
    if not _non_empty(key):
        raise ValueError("query_key is required")

    now = _utc_now()
    available = _as_utc(available_at, fallback=now)
    seconds = int(deadline_seconds)
    if seconds <= 0:
        raise ValueError("deadline_seconds must be positive")
    due = _as_utc(deadline_at, fallback=now + timedelta(seconds=seconds))
    if due <= now:
        raise ValueError("Task deadline must be in the future")
    inserted_id = f"locator-task:{uuid.uuid4().hex}"
    values = _task_insert_values(
        task_id=inserted_id,
        query_key=key,
        operation=normalized_operation,
        deployment_id=deployment_id,
        tenant_id=tenant_id,
        scope_hash=scope_hash,
        network_domain_id=network_domain_id,
        site_id=site_id,
        vrf_name=vrf_name,
        start_device_id=start_device_id,
        device_id=device_id,
        target_ip=target_ip,
        target_mac=target_mac,
        bridge_domain=bridge_domain,
        vlan_id=vlan,
        target=target,
        authorization_scope_hash=authorization_scope_hash,
        action_version=action_version,
        parser_version=parser_version,
        priority=priority,
        available_at=available,
        deadline_at=due,
        payload=payload,
        now=now,
    )
    conn.execute(
        """
        INSERT INTO locator_query_tasks (
            id, query_key, deployment_id, tenant_id, scope_hash, network_domain_id,
            site_id, vrf_name, start_device_id, operation, device_id, target_ip,
            target_mac, bridge_domain, vlan_id, target_json, authorization_scope_hash,
            action_version, parser_version, priority, status, available_at, deadline_at,
            lease_owner, lease_token, lease_until, attempt, max_attempts, generation,
            payload_json, result_json, error_code, error_message, cancel_requested_at,
            created_at, started_at, completed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?,
                  'pending', ?, ?, '', '', NULL, 0, 2, 0, ?::jsonb, '{}'::jsonb,
                  '', '', NULL, ?, NULL, NULL, ?)
        ON CONFLICT (query_key) DO NOTHING
        """,
        values,
    )
    existing = _task_for_key(conn, key, lock=True)
    if existing is None:
        raise LocatorTaskError("Unable to create locator query task")
    deduplicated = existing["id"] != inserted_id

    status = str(existing.get("status") or "pending")
    lease_until = existing.get("lease_until")
    lease_active = status == "running" and lease_until is not None and _as_utc(lease_until) > now
    completed_reusable = status in {"succeeded", "failed"} and not force_requeue
    if requeue_completed_after_seconds is not None and status in {"succeeded", "failed"}:
        grace_seconds = max(0, int(requeue_completed_after_seconds))
        completed_at = _as_utc(existing.get("completed_at") or existing.get("updated_at"), fallback=now)
        completed_reusable = not force_requeue and (now - completed_at).total_seconds() <= grace_seconds
    if not lease_active and not completed_reusable:
        if force_requeue or status in {"cancelled", "expired", "failed", "succeeded"}:
            conn.execute(
                """
                UPDATE locator_query_tasks
                   SET status = 'pending', priority = ?, available_at = ?,
                       deadline_at = ?, lease_owner = '', lease_token = '',
                       lease_until = NULL, attempt = 0, payload_json = ?::jsonb,
                       result_json = '{}'::jsonb, error_code = '', error_message = '',
                       cancel_requested_at = NULL, started_at = NULL,
                       completed_at = NULL, updated_at = ?
                 WHERE id = ?
                """,
                (max(0, int(priority)), available, due, _json(payload or {}), now, existing["id"]),
            )
        else:
            # Pending tasks can receive an earlier availability time and a
            # larger deadline from a newly subscribed run, but never lose a
            # higher priority request.
            old_available = _as_utc(existing.get("available_at"), fallback=available)
            old_deadline = _as_utc(existing.get("deadline_at"), fallback=due)
            conn.execute(
                """
                UPDATE locator_query_tasks
                   SET priority = LEAST(priority, ?), available_at = ?,
                       deadline_at = ?, updated_at = ?
                 WHERE id = ? AND status = 'pending'
                """,
                (max(0, int(priority)), min(old_available, available), max(old_deadline, due), now, existing["id"]),
            )

    task = _task_for_key(conn, key, lock=False)
    if task is None:
        raise LocatorTaskError("Locator task disappeared during enqueue")

    if run_id:
        run = _fetch_run(conn, run_id, owner_id=owner_id, lock=True)
        if run is None:
            raise LocatorTaskError(f"Locator run not found: {run_id}")
        if str(run.get("status") or "") == "cancelled":
            raise LocatorTaskError("Cannot subscribe a cancelled locator run")
        relation_status = (
            "fulfilled" if str(task.get("status") or "") == "succeeded"
            else "failed" if str(task.get("status") or "") in {"failed", "expired"}
            else "subscribed"
        )
        conn.execute(
            """
            INSERT INTO locator_run_tasks
                (run_id, task_id, relation_role, required, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, task_id) DO UPDATE SET
                relation_role = excluded.relation_role,
                required = excluded.required,
                status = CASE
                    WHEN locator_run_tasks.status = 'detached' THEN excluded.status
                    ELSE locator_run_tasks.status
                END,
                updated_at = excluded.updated_at
            """,
            (_non_empty(run_id), task["id"], _non_empty(relation_role, "required"), bool(required), relation_status, now, now),
        )
        if force_requeue:
            conn.execute(
                """
                UPDATE locator_run_tasks
                   SET status = 'subscribed', updated_at = ?
                 WHERE run_id = ? AND task_id = ?
                   AND status IN ('detached', 'fulfilled', 'failed')
                """,
                (now, _non_empty(run_id), task["id"]),
            )
            conn.execute(
                """
                UPDATE locator_runs
                   SET status = 'queued', completed_at = NULL, cancel_requested_at = NULL,
                       error_code = '', error_message = '', updated_at = ?, version = version + 1
                 WHERE id = ? AND status <> 'cancelled'
                """,
                (now, _non_empty(run_id)),
            )
        if relation_status in {"fulfilled", "failed"}:
            _refresh_subscriber_runs(conn, str(task["id"]), now)
    return task, deduplicated


def enqueue_locator_task(
    *,
    run_id: str | None = None,
    owner_id: str | None = None,
    relation_role: str = "required",
    required: bool = True,
    operation: str,
    mode: str = "normal",
    deployment_id: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    start_device_id: str = "",
    device_id: str = "",
    target_ip: str = "",
    target_mac: str = "",
    bridge_domain: str = "",
    vlan_id: int | str | None = None,
    target: Mapping[str, Any] | None = None,
    authorization_scope_hash: str = "",
    action_version: str = "",
    parser_version: str = "",
    priority: int = 100,
    available_at: datetime | str | None = None,
    deadline_at: datetime | str | None = None,
    deadline_seconds: int = DEFAULT_RUN_DEADLINE_SECONDS,
    payload: Mapping[str, Any] | None = None,
    query_key: str | None = None,
    force_requeue: bool = False,
    requeue_completed_after_seconds: int | None = None,
) -> dict[str, Any]:
    """Create or reuse one shared query task and optionally subscribe a run."""

    with _transaction() as conn:
        task, deduplicated = _ensure_task_in_transaction(
            conn,
            run_id=run_id,
            owner_id=owner_id,
            relation_role=relation_role,
            required=required,
            operation=operation,
            mode=mode,
            deployment_id=deployment_id,
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf_name=vrf_name,
            start_device_id=start_device_id,
            device_id=device_id,
            target_ip=target_ip,
            target_mac=target_mac,
            bridge_domain=bridge_domain,
            vlan_id=vlan_id,
            target=target,
            authorization_scope_hash=authorization_scope_hash,
            action_version=action_version,
            parser_version=parser_version,
            priority=priority,
            available_at=available_at,
            deadline_at=deadline_at,
            deadline_seconds=deadline_seconds,
            payload=payload,
            query_key=query_key,
            force_requeue=force_requeue,
            requeue_completed_after_seconds=requeue_completed_after_seconds,
        )
        conn.commit()
        task["deduplicated"] = deduplicated
        return task


def enqueue_locator_tasks(
    run_id: str,
    task_specs: Iterable[Mapping[str, Any]],
    *,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    """Atomically enqueue a run's task graph."""

    specs = list(task_specs)
    with _transaction() as conn:
        run = _fetch_run(conn, run_id, owner_id=owner_id, lock=True)
        if run is None:
            raise LocatorTaskError(f"Locator run not found: {run_id}")
        if str(run.get("status") or "") == "cancelled":
            raise LocatorTaskError("Cannot enqueue tasks for a cancelled locator run")
        results: list[dict[str, Any]] = []
        for spec in specs:
            task, deduplicated = _ensure_task_in_transaction(
                conn,
                run_id=run_id,
                owner_id=owner_id,
                relation_role=str(spec.get("relation_role") or "required"),
                required=bool(spec.get("required", True)),
                operation=str(spec.get("operation") or ""),
                mode=str(spec.get("mode") or "normal"),
                deployment_id=str(spec.get("deployment_id") or run.get("deployment_id") or ""),
                tenant_id=str(spec.get("tenant_id") or run.get("tenant_id") or DEFAULT_TENANT_ID),
                scope_hash=str(spec.get("scope_hash") or run.get("scope_hash") or ""),
                network_domain_id=str(spec.get("network_domain_id") or run.get("network_domain_id") or ""),
                site_id=str(spec.get("site_id") or run.get("site_id") or ""),
                vrf_name=str(spec.get("vrf_name") or run.get("vrf_name") or DEFAULT_VRF_NAME),
                start_device_id=str(spec.get("start_device_id") or run.get("start_device_id") or ""),
                device_id=str(spec.get("device_id") or ""),
                target_ip=str(spec.get("target_ip") or run.get("target_ip") or ""),
                target_mac=str(spec.get("target_mac") or ""),
                bridge_domain=str(spec.get("bridge_domain") or ""),
                vlan_id=spec.get("vlan_id"),
                target=spec.get("target") if isinstance(spec.get("target"), Mapping) else {},
                authorization_scope_hash=str(spec.get("authorization_scope_hash") or run.get("authorization_scope_hash") or ""),
                action_version=str(spec.get("action_version") or ""),
                parser_version=str(spec.get("parser_version") or ""),
                priority=int(spec.get("priority", 100)),
                available_at=spec.get("available_at"),
                deadline_at=spec.get("deadline_at") or run.get("deadline_at"),
                deadline_seconds=int(spec.get("deadline_seconds", DEFAULT_RUN_DEADLINE_SECONDS)),
                payload=spec.get("payload") if isinstance(spec.get("payload"), Mapping) else {},
                query_key=str(spec.get("query_key") or "") or None,
                force_requeue=bool(spec.get("force_requeue", False)),
                requeue_completed_after_seconds=(
                    int(spec["requeue_completed_after_seconds"])
                    if spec.get("requeue_completed_after_seconds") is not None else None
                ),
            )
            task["deduplicated"] = deduplicated
            results.append(task)
        conn.commit()
        return results


def claim_locator_task(
    *,
    worker_id: str,
    task_id: str | None = None,
    lease_seconds: int = DEFAULT_TASK_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Claim one due task using PostgreSQL row locking.

    Expired leases become eligible again with a new ownership token.  A late
    worker therefore cannot overwrite the replacement worker's result.
    """

    worker = _non_empty(worker_id)
    if not worker:
        raise ValueError("worker_id is required")
    seconds = max(1, int(lease_seconds))
    now = _utc_now()
    task_scope = " AND id = ?" if task_id else ""
    task_scope_params: tuple[Any, ...] = (_non_empty(task_id),) if task_id else ()
    with _transaction() as conn:
        conn.execute(
            """
            UPDATE locator_query_tasks
               SET status = 'expired', lease_owner = '', lease_token = '',
                   lease_until = NULL, completed_at = COALESCE(completed_at, ?),
                   error_code = CASE WHEN error_code = '' THEN 'deadline_exceeded' ELSE error_code END,
                   updated_at = ?
             WHERE status IN ('pending', 'running') AND deadline_at <= ?
            """ + task_scope,
            (now, now, now, *task_scope_params),
        )
        expired_rows = conn.execute(
            """
            SELECT id FROM locator_query_tasks
             WHERE status = 'expired'
               AND updated_at = ?
            """ + task_scope,
            (now, *task_scope_params),
        ).fetchall()
        for expired in expired_rows:
            expired_id = _non_empty(expired[0])
            conn.execute(
                "UPDATE locator_run_tasks SET status = 'failed', updated_at = ? WHERE task_id = ? AND status = 'subscribed'",
                (now, expired_id),
            )
            _refresh_subscriber_runs(conn, expired_id, now)
        conn.execute(
            """
            UPDATE locator_query_tasks
               SET status = 'failed', lease_owner = '', lease_token = '',
                   lease_until = NULL, error_code = 'lease_exhausted',
                   error_message = 'worker lease expired after maximum attempts',
                   completed_at = COALESCE(completed_at, ?), updated_at = ?
             WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?
               AND deadline_at > ? AND attempt >= max_attempts
            """ + task_scope,
            (now, now, now, now, *task_scope_params),
        )
        exhausted_rows = conn.execute(
            """
            SELECT id FROM locator_query_tasks
             WHERE status = 'failed' AND error_code = 'lease_exhausted'
               AND updated_at = ?
            """ + task_scope,
            (now, *task_scope_params),
        ).fetchall()
        for exhausted in exhausted_rows:
            exhausted_id = _non_empty(exhausted[0])
            conn.execute(
                "UPDATE locator_run_tasks SET status = 'failed', updated_at = ? WHERE task_id = ? AND status = 'subscribed'",
                (now, exhausted_id),
            )
            _refresh_subscriber_runs(conn, exhausted_id, now)
        conn.execute(
            """
            UPDATE locator_query_tasks
               SET status = 'pending', lease_owner = '', lease_token = '',
                   lease_until = NULL, updated_at = ?
             WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?
               AND deadline_at > ? AND attempt < max_attempts
            """ + task_scope,
            (now, now, now, *task_scope_params),
        )
        row = conn.execute(
            """
            SELECT * FROM locator_query_tasks
             WHERE status = 'pending' AND available_at <= ?
               AND deadline_at > ? AND attempt < max_attempts
            """ + task_scope + """
             ORDER BY priority, available_at, id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (now, now, *task_scope_params),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        task = _row_dict(row)
        task_id = _non_empty(task.get("id"))
        token = uuid.uuid4().hex
        lease_until = min(_as_utc(task.get("deadline_at"), fallback=now), now + timedelta(seconds=seconds))
        conn.execute(
            """
            UPDATE locator_query_tasks
               SET status = 'running', lease_owner = ?, lease_token = ?,
                   lease_until = ?, attempt = attempt + 1,
                   started_at = COALESCE(started_at, ?), updated_at = ?
             WHERE id = ? AND status = 'pending'
            """,
            (worker, token, lease_until, now, now, task_id),
        )
        conn.execute(
            """
            UPDATE locator_runs r
               SET status = CASE WHEN r.status = 'queued' THEN 'running' ELSE r.status END,
                   started_at = COALESCE(r.started_at, ?), updated_at = ?, version = r.version + 1
             WHERE EXISTS (
                 SELECT 1 FROM locator_run_tasks rt
                  WHERE rt.run_id = r.id AND rt.task_id = ? AND rt.status = 'subscribed'
             ) AND r.status = 'queued'
            """,
            (now, now, task_id),
        )
        conn.commit()
        task = _row_dict(conn.execute("SELECT * FROM locator_query_tasks WHERE id = ?", (task_id,)).fetchone())
        task.update({"lease_owner": worker, "lease_token": token, "lease_until": lease_until, "status": "running"})
        return _public_row(task)


def renew_locator_task(
    task_id: str,
    *,
    worker_id: str,
    lease_token: str,
    lease_seconds: int = DEFAULT_TASK_LEASE_SECONDS,
) -> bool:
    now = _utc_now()
    seconds = max(1, int(lease_seconds))
    with _transaction() as conn:
        row = conn.execute(
            "SELECT deadline_at FROM locator_query_tasks "
            "WHERE id = ? AND status = 'running' AND lease_owner = ? "
            "AND lease_token = ? FOR UPDATE",
            (_non_empty(task_id), _non_empty(worker_id), _non_empty(lease_token)),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        due = min(_as_utc(row[0], fallback=now), now + timedelta(seconds=seconds))
        updated = conn.execute(
            """
            UPDATE locator_query_tasks
               SET lease_until = ?, updated_at = ?
             WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_token = ?
            """,
            (due, now, _non_empty(task_id), _non_empty(worker_id), _non_empty(lease_token)),
        ).rowcount
        conn.commit()
        return bool(updated)


def _refresh_subscriber_runs(conn, task_id: str, now: datetime) -> None:
    run_rows = conn.execute(
        "SELECT DISTINCT run_id FROM locator_run_tasks WHERE task_id = ? AND status <> 'detached'",
        (_non_empty(task_id),),
    ).fetchall()
    for run_row in run_rows:
        run_id = _non_empty(run_row[0])
        run = conn.execute("SELECT status FROM locator_runs WHERE id = ? FOR UPDATE", (run_id,)).fetchone()
        if run is None or str(run[0]) == "cancelled":
            continue
        counts = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE rt.required) AS required_count,
                COUNT(*) FILTER (WHERE rt.required AND rt.status = 'fulfilled') AS fulfilled_count,
                COUNT(*) FILTER (WHERE rt.required AND rt.status = 'failed') AS failed_count,
                COUNT(*) FILTER (WHERE rt.required AND rt.status = 'subscribed') AS subscribed_count,
                COUNT(*) FILTER (WHERE rt.required AND t.status = 'running') AS running_count
              FROM locator_run_tasks rt
              JOIN locator_query_tasks t ON t.id = rt.task_id
             WHERE rt.run_id = ? AND rt.status <> 'detached'
            """,
            (run_id,),
        ).fetchone()
        required_count = int(counts[0] or 0)
        fulfilled_count = int(counts[1] or 0)
        failed_count = int(counts[2] or 0)
        subscribed_count = int(counts[3] or 0)
        running_count = int(counts[4] or 0)
        if required_count and fulfilled_count == required_count:
            status = "completed"
            completed_at = now
        elif failed_count and not subscribed_count and not running_count:
            status = "partial" if fulfilled_count else "failed"
            completed_at = now
        else:
            status = "running"
            completed_at = None
        conn.execute(
            """
            UPDATE locator_runs
               SET status = ?, completed_at = COALESCE(?, completed_at),
                   updated_at = ?, version = version + 1
             WHERE id = ? AND status NOT IN ('cancelled', 'completed', 'partial', 'failed', 'needs_context')
            """,
            (status, completed_at, now, run_id),
        )


def complete_locator_task(
    task_id: str,
    *,
    worker_id: str,
    lease_token: str,
    success: bool,
    result: Mapping[str, Any] | None = None,
    error_code: str = "",
    error_message: str = "",
    retry_at: datetime | str | None = None,
    device_id: str | None = None,
    device_lease_token: str | None = None,
) -> dict[str, Any] | None:
    """Finish a task only when the worker still owns its lease."""

    now = _utc_now()
    with _transaction() as conn:
        row = conn.execute(
            "SELECT * FROM locator_query_tasks WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_token = ? FOR UPDATE",
            (_non_empty(task_id), _non_empty(worker_id), _non_empty(lease_token)),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        task = _row_dict(row)
        deadline = _as_utc(task.get("deadline_at"), fallback=now)
        subscribed = conn.execute(
            "SELECT 1 FROM locator_run_tasks WHERE task_id = ? AND status = 'subscribed' LIMIT 1",
            (_non_empty(task_id),),
        ).fetchone()
        cancelled_without_subscribers = bool(task.get("cancel_requested_at") and subscribed is None)
        requested_retry = _as_utc(retry_at, fallback=now) if retry_at is not None else None
        can_retry = (
            not success
            and not cancelled_without_subscribers
            and requested_retry is not None
            and requested_retry < deadline
            and int(task.get("attempt") or 0) < int(task.get("max_attempts") or 1)
        )
        next_status = (
            "cancelled" if cancelled_without_subscribers
            else "succeeded" if success
            else ("pending" if can_retry else "failed")
        )
        available = requested_retry if can_retry else now
        conn.execute(
            """
            UPDATE locator_query_tasks
               SET status = ?, available_at = ?, lease_owner = '', lease_token = '',
                   lease_until = NULL, result_json = ?::jsonb,
                   error_code = ?, error_message = ?,
                   completed_at = CASE WHEN ? = 'pending' THEN NULL ELSE ? END,
                   updated_at = ?
             WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_token = ?
            """,
            (
                next_status,
                available,
                _json({} if cancelled_without_subscribers else (result or {})),
                "cancelled" if cancelled_without_subscribers else _non_empty(error_code)[:80],
                "定位任务已取消" if cancelled_without_subscribers else _non_empty(error_message)[:1000],
                next_status,
                now,
                now,
                _non_empty(task_id),
                _non_empty(worker_id),
                _non_empty(lease_token),
            ),
        )
        if device_id and device_lease_token:
            conn.execute(
                """
                UPDATE network_device_access_slots
                   SET lease_owner = '', lease_token = '', task_id = NULL,
                       lease_until = NULL, connection_state = 'idle', updated_at = ?
                 WHERE canonical_device_id = ? AND lease_owner = ? AND lease_token = ?
                """,
                (now, _non_empty(device_id), _non_empty(worker_id), _non_empty(device_lease_token)),
            )
        conn.execute(
            """
            UPDATE locator_run_tasks
               SET status = CASE WHEN ? = 'succeeded' THEN 'fulfilled'
                                 WHEN ? = 'failed' THEN 'failed'
                                 ELSE status END,
                   updated_at = ?
             WHERE task_id = ? AND status = 'subscribed'
            """,
            (next_status, next_status, now, _non_empty(task_id)),
        )
        if next_status != "pending":
            _refresh_subscriber_runs(conn, _non_empty(task_id), now)
        conn.commit()
        updated = _row_dict(conn.execute("SELECT * FROM locator_query_tasks WHERE id = ?", (_non_empty(task_id),)).fetchone())
        return _public_row(updated)


def cancel_locator_run(run_id: str, *, owner_id: str) -> dict[str, Any] | None:
    """Detach a run; shared tasks continue for other subscribers."""

    now = _utc_now()
    with _transaction() as conn:
        run = _fetch_run(conn, run_id, owner_id=owner_id, lock=True)
        if run is None:
            return None
        if str(run.get("status") or "") in RUN_TERMINAL_STATUSES:
            conn.commit()
            return run
        task_rows = conn.execute(
            "SELECT task_id FROM locator_run_tasks WHERE run_id = ? AND status = 'subscribed' FOR UPDATE",
            (_non_empty(run_id),),
        ).fetchall()
        conn.execute(
            """
            UPDATE locator_runs
               SET status = 'cancelled', cancel_requested_at = ?, completed_at = ?,
                   lease_owner = '', lease_token = '', lease_until = NULL,
                   updated_at = ?, version = version + 1
             WHERE id = ? AND status NOT IN ('completed', 'partial', 'failed', 'cancelled', 'needs_context')
            """,
            (now, now, now, _non_empty(run_id)),
        )
        conn.execute(
            """
            UPDATE locator_run_tasks
               SET status = 'detached', updated_at = ?
             WHERE run_id = ? AND status = 'subscribed'
            """,
            (now, _non_empty(run_id)),
        )
        for task_row in task_rows:
            task_id = _non_empty(task_row[0])
            subscriber = conn.execute(
                "SELECT 1 FROM locator_run_tasks WHERE task_id = ? AND status = 'subscribed' LIMIT 1",
                (task_id,),
            ).fetchone()
            if subscriber:
                continue
            conn.execute(
                """
                UPDATE locator_query_tasks
                   SET status = CASE WHEN status = 'pending' THEN 'cancelled' ELSE status END,
                       completed_at = CASE WHEN status = 'pending' THEN ? ELSE completed_at END,
                       cancel_requested_at = CASE WHEN status = 'running' THEN ? ELSE cancel_requested_at END,
                       updated_at = ?
                 WHERE id = ? AND status IN ('pending', 'running')
                """,
                (now, now, now, task_id),
            )
        conn.commit()
        return _fetch_run(conn, run_id, owner_id=owner_id)


def cleanup_locator_tasks(
    *,
    result_retention_seconds: int = 180,
    task_retention_days: int = 7,
    batch_limit: int = 500,
) -> dict[str, int]:
    """Scrub raw shared CLI output quickly and prune terminal task detail later."""
    now = _utc_now()
    result_cutoff = now - timedelta(seconds=max(1, int(result_retention_seconds)))
    task_cutoff = now - timedelta(days=max(1, int(task_retention_days)))
    selected_limit = max(1, min(int(batch_limit), 5000))
    with _transaction() as conn:
        scrubbed = conn.execute(
            """
            WITH expired AS (
                SELECT id FROM locator_query_tasks
                 WHERE status IN ('succeeded', 'failed', 'cancelled', 'expired')
                   AND completed_at IS NOT NULL AND completed_at <= ?
                   AND result_json <> '{}'::jsonb
                 ORDER BY completed_at
                 LIMIT ?
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE locator_query_tasks AS task
               SET result_json = '{}'::jsonb, updated_at = ?
              FROM expired
             WHERE task.id = expired.id
            """,
            (result_cutoff, selected_limit, now),
        ).rowcount
        deleted = conn.execute(
            """
            WITH expired AS (
                SELECT task.id FROM locator_query_tasks AS task
                 WHERE task.status IN ('succeeded', 'failed', 'cancelled', 'expired')
                   AND COALESCE(task.completed_at, task.updated_at) <= ?
                   AND NOT EXISTS (
                       SELECT 1 FROM locator_run_tasks AS relation
                        WHERE relation.task_id = task.id AND relation.status = 'subscribed'
                   )
                 ORDER BY COALESCE(task.completed_at, task.updated_at)
                 LIMIT ?
                 FOR UPDATE SKIP LOCKED
            )
            DELETE FROM locator_query_tasks AS task
             USING expired
             WHERE task.id = expired.id
            """,
            (task_cutoff, selected_limit),
        ).rowcount
        conn.commit()
        return {
            "results_scrubbed": max(0, int(scrubbed or 0)),
            "tasks_deleted": max(0, int(deleted or 0)),
        }


def save_locator_run_result(
    run_id: str,
    *,
    result: Mapping[str, Any],
    status: str = "completed",
    owner_id: str | None = None,
    stats: Mapping[str, Any] | None = None,
    error_code: str = "",
    error_message: str = "",
    generated_at: datetime | str | None = None,
    fresh_until: datetime | str | None = None,
    retain_until: datetime | str | None = None,
    source: str = "ssh_cli",
    lease_owner: str | None = None,
    lease_token: str | None = None,
) -> dict[str, Any] | None:
    """Persist a trace result and optionally append bounded history."""

    selected_status = _non_empty(status).lower()
    if selected_status not in {"queued", "running", *RUN_TERMINAL_STATUSES}:
        raise ValueError(f"Unsupported locator run status: {selected_status!r}")
    now = _utc_now()
    generated = _as_utc(generated_at, fallback=now)
    fresh = _as_utc(fresh_until, fallback=generated + timedelta(seconds=DEFAULT_RESULT_FRESH_SECONDS))
    retain = _as_utc(retain_until, fallback=generated + timedelta(seconds=DEFAULT_HISTORY_RETAIN_SECONDS))
    if fresh < generated or retain < fresh:
        raise ValueError("Run result freshness windows are invalid")
    result_payload = dict(result)
    dependency_manifest = result_payload.get("dependency_manifest")
    dependency_gaps: list[str] = []
    with _transaction() as conn:
        run = _fetch_run(conn, run_id, owner_id=owner_id, lock=True)
        if run is None:
            return None
        if lease_owner is not None or lease_token is not None:
            if not lease_owner or not lease_token:
                raise ValueError("lease_owner and lease_token must be provided together")
            lease = conn.execute(
                "SELECT lease_owner, lease_token FROM locator_runs WHERE id = ?",
                (_non_empty(run_id),),
            ).fetchone()
            if (
                lease is None
                or str(lease[0] or "") != _non_empty(lease_owner)
                or str(lease[1] or "") != _non_empty(lease_token)
            ):
                raise LocatorLeaseLost("Locator run lease is no longer owned by this worker")
        if str(run.get("status") or "") == "cancelled" and selected_status != "cancelled":
            return run
        if selected_status in {"completed", "partial"}:
            if not isinstance(dependency_manifest, Mapping):
                dependency_gaps = ["dependency_manifest_missing"]
            else:
                _, dependency_gaps = _dependency_manifest_current_in_transaction(
                    conn,
                    dependency_manifest,
                    lock=True,
                )
            if dependency_gaps:
                gaps = result_payload.get("coverage_gaps")
                if not isinstance(gaps, list):
                    gaps = []
                    result_payload["coverage_gaps"] = gaps
                for gap in dependency_gaps:
                    if gap not in gaps:
                        gaps.append(gap)
                result_payload["dependency_fence"] = {
                    "status": "changed" if any(gap.startswith("dependency_changed:") for gap in dependency_gaps) else "incomplete",
                    "scope": "global",
                }
                if selected_status == "completed":
                    selected_status = "partial"
                    error_code = "DEPENDENCY_CHANGED"
                    error_message = "定位依赖在执行期间发生变化，请重试"
            elif isinstance(dependency_manifest, Mapping):
                result_payload["dependency_fence"] = {"status": "current", "scope": "global"}
        # Authorization inputs captured when a run was created are immutable.
        # Result statistics are refreshed by the worker, so merge them without
        # dropping the device scope needed for reauthorization on later reads.
        initial_stats = run.get("stats") if isinstance(run.get("stats"), Mapping) else {}
        merged_stats = dict(initial_stats)
        merged_stats.update(dict(stats or {}))
        if "authorized_device_ids" in initial_stats:
            merged_stats["authorized_device_ids"] = list(initial_stats.get("authorized_device_ids") or [])
        lease_release = (
            "lease_owner = CASE WHEN ? IN ('completed', 'partial', 'failed', 'cancelled', 'needs_context') THEN '' ELSE lease_owner END, "
            "lease_token = CASE WHEN ? IN ('completed', 'partial', 'failed', 'cancelled', 'needs_context') THEN '' ELSE lease_token END, "
            "lease_until = CASE WHEN ? IN ('completed', 'partial', 'failed', 'cancelled', 'needs_context') THEN NULL ELSE lease_until END, "
        )
        lease_where = ""
        lease_params: tuple[Any, ...] = ()
        if lease_owner is not None and lease_token is not None:
            lease_where = " AND lease_owner = ? AND lease_token = ?"
            lease_params = (_non_empty(lease_owner), _non_empty(lease_token))
        conn.execute(
            f"""
            UPDATE locator_runs
               SET status = ?, result_json = ?::jsonb, stats_json = ?::jsonb,
                   dependency_manifest_json = ?::jsonb,
                   error_code = ?, error_message = ?,
                   started_at = COALESCE(started_at, ?),
                   completed_at = CASE WHEN ? IN (
                       'completed', 'partial', 'failed', 'cancelled', 'needs_context'
                   ) THEN COALESCE(completed_at, ?) ELSE completed_at END,
                   {lease_release}
                   updated_at = ?, version = version + 1
             WHERE id = ?{lease_where}
            """,
            (
                selected_status,
                _json(result_payload),
                _json(merged_stats),
                _json(dependency_manifest if isinstance(dependency_manifest, Mapping) else {}),
                _non_empty(error_code)[:80],
                _non_empty(error_message)[:1000],
                generated,
                selected_status,
                now,
                selected_status,
                selected_status,
                selected_status,
                now,
                _non_empty(run_id),
                *lease_params,
            ),
        )
        if selected_status in RUN_TERMINAL_STATUSES:
            conn.execute(
                """
                INSERT INTO locator_history (
                    id, run_id, tenant_id, scope_hash, network_domain_id, site_id,
                    vrf_name, target_ip, outcome, result_json, source,
                    generated_at, fresh_until, retain_until, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?)
                """,
                (
                    f"locator-history:{uuid.uuid4().hex}",
                    _non_empty(run_id),
                    run["tenant_id"],
                    run["scope_hash"],
                    run["network_domain_id"],
                    run["site_id"],
                    run["vrf_name"],
                    run["target_ip"],
                    selected_status,
                    _json(result_payload),
                    _non_empty(source, "ssh_cli"),
                    generated,
                    fresh,
                    retain,
                    now,
                ),
            )
        conn.commit()
        return _fetch_run(conn, run_id, owner_id=owner_id)


def set_locator_run_status(
    run_id: str,
    status: str,
    *,
    owner_id: str | None = None,
    error_code: str = "",
    error_message: str = "",
) -> dict[str, Any] | None:
    run = get_locator_run(run_id, owner_id=owner_id)
    if run is None:
        return None
    return save_locator_run_result(
        run_id,
        result=_decode_json(run.get("result"), {}),
        status=status,
        owner_id=owner_id,
        stats=_decode_json(run.get("stats"), {}),
        error_code=error_code,
        error_message=error_message,
    )


def ensure_device_access_slots(
    canonical_device_id: str,
    *,
    capacity: int = 1,
    purpose: str = "ip_locator",
) -> int:
    device = _non_empty(canonical_device_id)
    count = max(1, int(capacity))
    purpose = _non_empty(purpose, "ip_locator")
    now = _utc_now()
    with _transaction() as conn:
        for slot_id in range(count):
            conn.execute(
                """
                INSERT INTO network_device_access_slots
                    (canonical_device_id, purpose, slot_id, lease_owner,
                     lease_token, task_id, lease_until, connection_state,
                     last_acquired_at, updated_at)
                VALUES (?, ?, ?, '', '', NULL, NULL, 'idle', NULL, ?)
                ON CONFLICT (canonical_device_id, purpose, slot_id) DO NOTHING
                """,
                (device, purpose, slot_id, now),
            )
        conn.commit()
        return count


def ensure_global_access_slots(*, capacity: int = 5, purpose: str = "ip_locator") -> int:
    selected_purpose = _non_empty(purpose, "ip_locator")
    count = max(1, int(capacity))
    now = _utc_now()
    with _transaction() as conn:
        for slot_id in range(count):
            conn.execute(
                """
                INSERT INTO locator_global_access_slots
                    (purpose, slot_id, lease_owner, lease_token, run_id, lease_until, updated_at)
                VALUES (?, ?, '', '', '', NULL, ?)
                ON CONFLICT (purpose, slot_id) DO NOTHING
                """,
                (selected_purpose, slot_id, now),
            )
        conn.commit()
    return count


def acquire_global_access_lease(
    *,
    owner_id: str,
    run_id: str = "",
    capacity: int = 5,
    purpose: str = "ip_locator",
    lease_seconds: int = DEFAULT_DEVICE_LEASE_SECONDS,
) -> dict[str, Any] | None:
    owner = _non_empty(owner_id)
    if not owner:
        raise ValueError("owner_id is required")
    selected_purpose = _non_empty(purpose, "ip_locator")
    count = ensure_global_access_slots(capacity=capacity, purpose=selected_purpose)
    now = _utc_now()
    due = now + timedelta(seconds=max(1, int(lease_seconds)))
    with _transaction() as conn:
        row = conn.execute(
            """
            SELECT slot_id FROM locator_global_access_slots
             WHERE purpose = ? AND slot_id < ?
               AND (lease_until IS NULL OR lease_until <= ?)
             ORDER BY slot_id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (selected_purpose, count, now),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        token = uuid.uuid4().hex
        slot_id = int(row[0])
        conn.execute(
            """
            UPDATE locator_global_access_slots
               SET lease_owner = ?, lease_token = ?, run_id = ?,
                   lease_until = ?, updated_at = ?
             WHERE purpose = ? AND slot_id = ?
            """,
            (owner, token, _non_empty(run_id), due, now, selected_purpose, slot_id),
        )
        conn.commit()
        return {
            "purpose": selected_purpose,
            "slot_id": slot_id,
            "lease_owner": owner,
            "lease_token": token,
            "lease_until": due.isoformat(),
        }


def release_global_access_lease(
    *,
    owner_id: str,
    lease_token: str,
    slot_id: int,
    purpose: str = "ip_locator",
) -> bool:
    now = _utc_now()
    with _transaction() as conn:
        updated = conn.execute(
            """
            UPDATE locator_global_access_slots
               SET lease_owner = '', lease_token = '', run_id = '',
                   lease_until = NULL, updated_at = ?
             WHERE purpose = ? AND slot_id = ?
               AND lease_owner = ? AND lease_token = ?
            """,
            (now, _non_empty(purpose, "ip_locator"), int(slot_id), _non_empty(owner_id), _non_empty(lease_token)),
        ).rowcount
        conn.commit()
        return bool(updated)


def renew_global_access_lease(
    *,
    owner_id: str,
    lease_token: str,
    slot_id: int,
    purpose: str = "ip_locator",
    lease_seconds: int = DEFAULT_DEVICE_LEASE_SECONDS,
) -> bool:
    now = _utc_now()
    due = now + timedelta(seconds=max(1, int(lease_seconds)))
    with _transaction() as conn:
        updated = conn.execute(
            """
            UPDATE locator_global_access_slots
               SET lease_until = ?, updated_at = ?
             WHERE purpose = ? AND slot_id = ?
               AND lease_owner = ? AND lease_token = ?
            """,
            (
                due,
                now,
                _non_empty(purpose, "ip_locator"),
                int(slot_id),
                _non_empty(owner_id),
                _non_empty(lease_token),
            ),
        ).rowcount
        conn.commit()
        return bool(updated)


def acquire_device_access_lease(
    canonical_device_id: str,
    *,
    owner_id: str,
    task_id: str | None = None,
    capacity: int = 1,
    purpose: str = "ip_locator",
    lease_seconds: int = DEFAULT_DEVICE_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically claim one slot for a canonical device.

    The caller must keep the returned token and release/renew it around the
    network session.  Expired slots are reclaimable; active slots are skipped.
    """

    device = _non_empty(canonical_device_id)
    owner = _non_empty(owner_id)
    if not device or not owner:
        raise ValueError("canonical_device_id and owner_id are required")
    count = max(1, int(capacity))
    purpose = _non_empty(purpose, "ip_locator")
    now = _utc_now()
    lease_until = now + timedelta(seconds=max(1, int(lease_seconds)))
    with _transaction() as conn:
        for slot_id in range(count):
            conn.execute(
                """
                INSERT INTO network_device_access_slots
                    (canonical_device_id, purpose, slot_id, lease_owner,
                     lease_token, task_id, lease_until, connection_state,
                     last_acquired_at, updated_at)
                VALUES (?, ?, ?, '', '', NULL, NULL, 'idle', NULL, ?)
                ON CONFLICT (canonical_device_id, purpose, slot_id) DO NOTHING
                """,
                (device, purpose, slot_id, now),
            )
        row = conn.execute(
            """
            SELECT * FROM network_device_access_slots
             WHERE canonical_device_id = ? AND purpose = ?
               AND connection_state <> 'draining'
               AND (lease_until IS NULL OR lease_until <= ?)
             ORDER BY slot_id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (device, purpose, now),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        slot = _row_dict(row)
        token = uuid.uuid4().hex
        conn.execute(
            """
            UPDATE network_device_access_slots
               SET lease_owner = ?, lease_token = ?, task_id = ?, lease_until = ?,
                   connection_state = 'leased', last_acquired_at = ?, updated_at = ?
             WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?
            """,
            (
                owner,
                token,
                _non_empty(task_id) or None,
                lease_until,
                now,
                now,
                device,
                purpose,
                int(slot["slot_id"]),
            ),
        )
        conn.commit()
        updated = _row_dict(
            conn.execute(
                "SELECT * FROM network_device_access_slots WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?",
                (device, purpose, int(slot["slot_id"])),
            ).fetchone()
        )
        updated["lease_token"] = token
        updated["lease_owner"] = owner
        return _public_row(updated)


def renew_device_access_lease(
    canonical_device_id: str,
    *,
    owner_id: str,
    lease_token: str,
    purpose: str = "ip_locator",
    lease_seconds: int = DEFAULT_DEVICE_LEASE_SECONDS,
) -> bool:
    now = _utc_now()
    due = now + timedelta(seconds=max(1, int(lease_seconds)))
    with _transaction() as conn:
        count = conn.execute(
            """
            UPDATE network_device_access_slots
               SET lease_until = ?, updated_at = ?
             WHERE canonical_device_id = ? AND purpose = ?
               AND lease_owner = ? AND lease_token = ?
               AND connection_state = 'leased'
            """,
            (due, now, _non_empty(canonical_device_id), _non_empty(purpose, "ip_locator"), _non_empty(owner_id), _non_empty(lease_token)),
        ).rowcount
        conn.commit()
        return bool(count)


def release_device_access_lease(
    canonical_device_id: str,
    *,
    owner_id: str,
    lease_token: str,
    purpose: str = "ip_locator",
    draining: bool = False,
) -> bool:
    now = _utc_now()
    state = "draining" if draining else "idle"
    with _transaction() as conn:
        count = conn.execute(
            """
            UPDATE network_device_access_slots
               SET lease_owner = '', lease_token = '', task_id = NULL,
                   lease_until = NULL, connection_state = ?, updated_at = ?
             WHERE canonical_device_id = ? AND purpose = ?
               AND lease_owner = ? AND lease_token = ?
            """,
            (state, now, _non_empty(canonical_device_id), _non_empty(purpose, "ip_locator"), _non_empty(owner_id), _non_empty(lease_token)),
        ).rowcount
        conn.commit()
        return bool(count)


# Short aliases keep the call site readable in the trace and worker services.
acquire_device_lease = acquire_device_access_lease
renew_device_lease = renew_device_access_lease
release_device_lease = release_device_access_lease


def _observation_key(
    *,
    tenant_id: str,
    scope_hash: str,
    network_domain_id: str,
    site_id: str,
    vrf_name: str,
    device_id: str,
    observation_kind: str,
    target_ip: str,
    target_mac: str,
    bridge_domain: str,
    vlan_id: int | None,
) -> str:
    material = {
        "version": "locator-v2-observation",
        "tenant_id": _non_empty(tenant_id, DEFAULT_TENANT_ID),
        "scope_hash": _non_empty(scope_hash),
        "network_domain_id": _non_empty(network_domain_id),
        "site_id": _non_empty(site_id),
        "vrf_name": _normalize_vrf(vrf_name),
        "device_id": _non_empty(device_id),
        "observation_kind": _non_empty(observation_kind).lower(),
        "target_ip": _non_empty(target_ip),
        "target_mac": _non_empty(target_mac).lower(),
        "bridge_domain": _non_empty(bridge_domain),
        "vlan_id": vlan_id,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "observation-v2:" + sha256(encoded.encode("utf-8")).hexdigest()


def upsert_locator_observation(
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    device_id: str,
    observation_kind: str,
    target_ip: str = "",
    target_mac: str = "",
    bridge_domain: str = "",
    vlan_id: int | str | None = None,
    records: Mapping[str, Any] | list[Any] | None = None,
    coverage: str = "targeted",
    source: str = "ssh_cli",
    collected_at: datetime | str | None = None,
    fresh_until: datetime | str | None = None,
    retain_until: datetime | str | None = None,
    fresh_seconds: int = DEFAULT_ARP_FRESH_SECONDS,
    retain_seconds: int = DEFAULT_ARP_RETAIN_SECONDS,
    generation: int | None = None,
    action_version: str = "",
    parser_version: str = "",
    schema_version: str = "locator-v2",
    query_task_id: str | None = None,
    observation_key: str | None = None,
) -> dict[str, Any]:
    kind = _non_empty(observation_kind).lower()
    if kind not in {"route", "arp", "mac", "interface", "neighbor", "topology", "path"}:
        raise ValueError(f"Unsupported observation kind: {kind!r}")
    selected_coverage = _non_empty(coverage, "targeted").lower()
    if selected_coverage not in {"targeted", "full", "partial", "failed"}:
        raise ValueError(f"Unsupported observation coverage: {selected_coverage!r}")
    vlan = _normalize_vlan(vlan_id)
    if generation is not None and int(generation) < 0:
        raise ValueError("generation must be non-negative")
    now = _utc_now()
    collected = _as_utc(collected_at, fallback=now)
    fresh = _as_utc(fresh_until, fallback=collected + timedelta(seconds=max(1, int(fresh_seconds))))
    retain = _as_utc(retain_until, fallback=collected + timedelta(seconds=max(1, int(retain_seconds))))
    if fresh < collected or retain < fresh:
        raise ValueError("Observation freshness windows are invalid")
    key = observation_key or _observation_key(
        tenant_id=tenant_id,
        scope_hash=scope_hash,
        network_domain_id=network_domain_id,
        site_id=site_id,
        vrf_name=vrf_name,
        device_id=device_id,
        observation_kind=kind,
        target_ip=target_ip,
        target_mac=target_mac,
        bridge_domain=bridge_domain,
        vlan_id=vlan,
    )
    records_json = _json(records if records is not None else {})
    with _transaction() as conn:
        existing_row = conn.execute(
            "SELECT * FROM locator_observations WHERE observation_key = ? FOR UPDATE",
            (_non_empty(key),),
        ).fetchone()
        changed = existing_row is None
        next_generation = max(0, int(generation or 0))
        if existing_row is not None:
            existing = _row_dict(existing_row)
            existing_generation = int(existing.get("generation") or 0)
            existing_collected = _as_utc(existing.get("collected_at"), fallback=collected)
            existing_records = _decode_json(existing.get("records_json"), {})
            existing_records_json = _json(existing_records)
            changed = (
                existing_records_json != records_json
                or _non_empty(existing.get("coverage"), "targeted") != selected_coverage
            )
            if collected < existing_collected or (
                generation is not None and int(generation) < existing_generation
            ):
                conn.rollback()
                result = _public_row(existing)
                result["stale_ignored"] = True
                return result
            next_generation = max(
                int(generation) if generation is not None else existing_generation,
                existing_generation + (1 if changed else 0),
            )
            observation_id = _non_empty(existing.get("id"))
        else:
            next_generation = max(1, int(generation or 0))
            observation_id = f"locator-observation:{uuid.uuid4().hex}"
        if existing_row is None:
            conn.execute(
                """
                INSERT INTO locator_observations (
                    id, observation_key, tenant_id, scope_hash, network_domain_id,
                    site_id, vrf_name, device_id, observation_kind, target_ip,
                    target_mac, bridge_domain, vlan_id, records_json, coverage,
                    source, collected_at, fresh_until, retain_until, generation,
                    action_version, parser_version, schema_version, query_task_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    _non_empty(key),
                    _non_empty(tenant_id, DEFAULT_TENANT_ID),
                    _non_empty(scope_hash),
                    _non_empty(network_domain_id),
                    _non_empty(site_id),
                    _normalize_vrf(vrf_name),
                    _non_empty(device_id),
                    kind,
                    _non_empty(target_ip),
                    _non_empty(target_mac).lower(),
                    _non_empty(bridge_domain),
                    vlan,
                    records_json,
                    selected_coverage,
                    _non_empty(source, "ssh_cli"),
                    collected,
                    fresh,
                    retain,
                    next_generation,
                    _non_empty(action_version),
                    _non_empty(parser_version),
                    _non_empty(schema_version, "locator-v2"),
                    _non_empty(query_task_id) or None,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE locator_observations
                   SET records_json = ?::jsonb, coverage = ?, source = ?,
                       collected_at = ?, fresh_until = ?, retain_until = ?,
                       generation = ?, action_version = ?, parser_version = ?,
                       schema_version = ?, query_task_id = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    records_json,
                    selected_coverage,
                    _non_empty(source, "ssh_cli"),
                    collected,
                    fresh,
                    retain,
                    next_generation,
                    _non_empty(action_version),
                    _non_empty(parser_version),
                    _non_empty(schema_version, "locator-v2"),
                    _non_empty(query_task_id) or None,
                    now,
                    observation_id,
                ),
            )
        if changed and _non_empty(scope_hash):
            event_generation = next_generation
            event_key = f"observation:{_non_empty(key)}:{event_generation}"
            payload = {
                "observation_key": _non_empty(key),
                "observation_kind": kind,
                "device_id": _non_empty(device_id),
                "target_ip": _non_empty(target_ip),
                "target_mac": _non_empty(target_mac).lower(),
                "bridge_domain": _non_empty(bridge_domain),
                "vlan_id": vlan,
            }
            conn.execute(
                """
                INSERT INTO locator_invalidation_outbox (
                    id, event_key, tenant_id, scope_hash, entity_type, entity_id,
                    event_type, generation, payload_json, status, attempts,
                    available_at, lease_owner, lease_until, last_error,
                    created_at, processed_at, updated_at
                ) VALUES (?, ?, ?, ?, 'locator_observation', ?, ?, ?, ?::jsonb,
                          'pending', 0, ?, '', NULL, '', ?, NULL, ?)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (
                    f"locator-invalidation:{uuid.uuid4().hex}",
                    event_key,
                    _non_empty(tenant_id, DEFAULT_TENANT_ID),
                    _non_empty(scope_hash),
                    _non_empty(key),
                    "fact_created" if existing_row is None else "fact_changed",
                    event_generation,
                    _json(payload),
                    now,
                    now,
                    now,
                ),
            )
        conn.commit()
        result = _public_row(conn.execute("SELECT * FROM locator_observations WHERE id = ?", (observation_id,)).fetchone())
        result["stale_ignored"] = False
        return result


def reconcile_locator_snapshot_absences(
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str,
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    device_id: str,
    observation_kind: str,
    records: list[Mapping[str, Any]],
    snapshot_status: Mapping[str, Any],
    collected_at: datetime | str,
    query_task_id: str | None = None,
    action_version: str = "",
    parser_version: str = "",
    schema_version: str = "",
    source: str = "ssh_cli",
    retain_seconds: int | None = None,
) -> dict[str, Any]:
    """Tombstone older target facts omitted by an explicitly complete snapshot.

    The full-snapshot observation must already be committed. Missing target
    rows and their Redis invalidation events are then updated atomically in a
    second PostgreSQL transaction. No observation or audit evidence is deleted.
    """
    kind = _non_empty(observation_kind).lower()
    if not isinstance(snapshot_status, Mapping):
        return {"applied": False, "reason": "snapshot_status_missing", "revoked_count": 0}
    status = _non_empty(snapshot_status.get("status")).lower()
    coverage = _non_empty(snapshot_status.get("coverage")).lower()
    snapshot_records = list(records or [])
    if kind not in {"arp", "mac"}:
        raise ValueError("Only ARP and MAC snapshots can reconcile locator facts")
    if status not in {"found", "not_found"} or coverage != "full":
        return {"applied": False, "reason": "snapshot_not_complete", "revoked_count": 0}
    if (status == "not_found" and snapshot_records) or (
        status == "found" and not snapshot_records
    ):
        return {"applied": False, "reason": "snapshot_status_mismatch", "revoked_count": 0}
    if any(not isinstance(record, Mapping) for record in snapshot_records):
        return {"applied": False, "reason": "snapshot_records_invalid", "revoked_count": 0}
    if not _non_empty(scope_hash) or not _non_empty(device_id):
        return {"applied": False, "reason": "snapshot_scope_missing", "revoked_count": 0}

    def _mac_identity(value: Any) -> str:
        return "".join(
            character
            for character in _non_empty(value).lower()
            if character in "0123456789abcdef"
        )

    if kind == "arp":
        present_targets = {
            _non_empty(record.get("ip")) for record in snapshot_records
        }
        if status == "found" and (not present_targets or "" in present_targets):
            return {"applied": False, "reason": "snapshot_records_invalid", "revoked_count": 0}
    else:
        present_targets = {
            _mac_identity(record.get("mac")) for record in snapshot_records
        }
        if status == "found" and (not present_targets or "" in present_targets):
            return {"applied": False, "reason": "snapshot_records_invalid", "revoked_count": 0}

    selected_tenant = _non_empty(tenant_id, DEFAULT_TENANT_ID)
    selected_scope_hash = _non_empty(scope_hash)
    selected_network_domain = _non_empty(network_domain_id)
    selected_site = _non_empty(site_id)
    selected_vrf = _normalize_vrf(vrf_name)
    selected_device = _non_empty(device_id)
    selected_action = _non_empty(action_version)
    selected_parser = _non_empty(parser_version)
    selected_schema = _non_empty(schema_version)
    selected_source = _non_empty(source, "ssh_cli")
    snapshot_time = _as_utc(collected_at)
    default_snapshot_retain = (
        DEFAULT_ARP_RETAIN_SECONDS if kind == "arp" else DEFAULT_MAC_RETAIN_SECONDS
    )
    snapshot_retain_until = snapshot_time + timedelta(
        seconds=max(15, int(retain_seconds if retain_seconds is not None else default_snapshot_retain))
    )
    snapshot_key = _observation_key(
        tenant_id=selected_tenant,
        scope_hash=selected_scope_hash,
        network_domain_id=selected_network_domain,
        site_id=selected_site,
        vrf_name=selected_vrf,
        device_id=selected_device,
        observation_kind=kind,
        target_ip="",
        target_mac="",
        bridge_domain="",
        vlan_id=None,
    )
    snapshot_task = _non_empty(query_task_id) or None
    now = _utc_now()
    invalidated = 0

    with _transaction() as conn:
        snapshot_row = conn.execute(
            "SELECT * FROM locator_observations WHERE observation_key = ? FOR UPDATE",
            (snapshot_key,),
        ).fetchone()
        current_snapshot = _row_dict(snapshot_row)
        if (
            not current_snapshot
            or _non_empty(current_snapshot.get("coverage")).lower() != "full"
            or _as_utc(current_snapshot.get("collected_at"), fallback=snapshot_time) != snapshot_time
            or _non_empty(current_snapshot.get("tenant_id"), DEFAULT_TENANT_ID) != selected_tenant
            or _non_empty(current_snapshot.get("scope_hash")) != selected_scope_hash
            or _non_empty(current_snapshot.get("network_domain_id")) != selected_network_domain
            or _non_empty(current_snapshot.get("site_id")) != selected_site
            or _normalize_vrf(current_snapshot.get("vrf_name")) != selected_vrf
            or _non_empty(current_snapshot.get("device_id")) != selected_device
            or _non_empty(current_snapshot.get("observation_kind")).lower() != kind
            or _non_empty(current_snapshot.get("action_version")) != selected_action
            or (selected_parser and _non_empty(current_snapshot.get("parser_version")) != selected_parser)
            or (selected_schema and _non_empty(current_snapshot.get("schema_version")) != selected_schema)
            or _non_empty(current_snapshot.get("source"), "ssh_cli") != selected_source
            or (snapshot_task and _non_empty(current_snapshot.get("query_task_id")) != snapshot_task)
            or _decode_json(current_snapshot.get("records_json"), None) != snapshot_records
        ):
            conn.rollback()
            return {"applied": False, "reason": "snapshot_not_current", "revoked_count": 0}

        if selected_parser and selected_schema:
            version_filter = "parser_version = ? AND schema_version = ?"
            version_params = (selected_parser, selected_schema)
        else:
            # Preserve the historical exact-action comparison for callers
            # without parser/schema fences. New V2 callers always supply all
            # three actual versions from the committed snapshot observation.
            version_filter = "action_version = ?"
            version_params = (selected_action,)
        rows = conn.execute(
            """
            SELECT *
              FROM locator_observations
             WHERE tenant_id = ? AND scope_hash = ? AND network_domain_id = ?
               AND site_id = ? AND vrf_name = ? AND device_id = ?
               AND observation_kind = ? AND """ + version_filter + """ AND source = ?
               AND coverage IN ('targeted', 'full') AND collected_at <= ?
               AND ((observation_kind = 'arp' AND target_ip <> '')
                 OR (observation_kind = 'mac' AND target_mac <> ''))
             ORDER BY observation_key
             FOR UPDATE
            """,
            (
                selected_tenant,
                selected_scope_hash,
                selected_network_domain,
                selected_site,
                selected_vrf,
                selected_device,
                kind,
                *version_params,
                selected_source,
                snapshot_time,
            ),
        ).fetchall()
        fresh_until = snapshot_time + timedelta(seconds=15)
        for raw_row in rows:
            old = _row_dict(raw_row)
            target = (
                _non_empty(old.get("target_ip"))
                if kind == "arp"
                else _mac_identity(old.get("target_mac"))
            )
            old_records = _decode_json(old.get("records_json"), {})
            if (
                not target
                or target in present_targets
                or (isinstance(old_records, Mapping) and old_records.get("not_found") is True)
                or not old_records
            ):
                continue

            previous_generation = max(0, int(old.get("generation") or 0))
            next_generation = previous_generation + 1
            retain_until = max(
                _as_utc(old.get("retain_until"), fallback=snapshot_time),
                snapshot_retain_until,
            )
            observation_key = _non_empty(old.get("observation_key"))
            tombstone = {
                "not_found": True,
                "status": "not_found",
                "source": "full_snapshot",
                "revocation_reason": "missing_from_complete_full_snapshot",
                "snapshot_observation_key": snapshot_key,
                "snapshot_collected_at": snapshot_time.isoformat(),
                "snapshot_query_task_id": snapshot_task,
                "prior_generation": previous_generation,
                "prior_records": old_records,
            }
            updated = conn.execute(
                """
                UPDATE locator_observations
                   SET records_json = ?::jsonb, coverage = 'targeted',
                       source = ?, collected_at = ?, fresh_until = ?, retain_until = ?,
                       generation = ?, action_version = ?, parser_version = ?,
                       schema_version = ?, query_task_id = ?, updated_at = ?
                 WHERE id = ? AND generation = ?
                """,
                (
                    _json(tombstone),
                    selected_source,
                    snapshot_time,
                    fresh_until,
                    retain_until,
                    next_generation,
                    selected_action,
                    selected_parser or _non_empty(old.get("parser_version")),
                    selected_schema or _non_empty(old.get("schema_version")),
                    snapshot_task or _non_empty(old.get("query_task_id")) or None,
                    now,
                    _non_empty(old.get("id")),
                    previous_generation,
                ),
            )
            if not updated.rowcount:
                continue

            event_key = f"observation:{observation_key}:{next_generation}"
            payload = {
                "observation_key": observation_key,
                "observation_kind": kind,
                "device_id": selected_device,
                "target_ip": _non_empty(old.get("target_ip")),
                "target_mac": _non_empty(old.get("target_mac")).lower(),
                "bridge_domain": _non_empty(old.get("bridge_domain")),
                "vlan_id": old.get("vlan_id"),
                "reason": "missing_from_complete_full_snapshot",
                "snapshot_observation_key": snapshot_key,
                "snapshot_collected_at": snapshot_time.isoformat(),
                "snapshot_query_task_id": snapshot_task,
                "previous_generation": previous_generation,
            }
            conn.execute(
                """
                INSERT INTO locator_invalidation_outbox (
                    id, event_key, tenant_id, scope_hash, entity_type, entity_id,
                    event_type, generation, payload_json, status, attempts,
                    available_at, lease_owner, lease_until, last_error,
                    created_at, processed_at, updated_at
                ) VALUES (?, ?, ?, ?, 'locator_observation', ?, 'fact_invalidated',
                          ?, ?::jsonb, 'pending', 0, ?, '', NULL, '', ?, NULL, ?)
                ON CONFLICT (event_key) DO NOTHING
                """,
                (
                    f"locator-invalidation:{uuid.uuid4().hex}",
                    event_key,
                    selected_tenant,
                    selected_scope_hash,
                    observation_key,
                    next_generation,
                    _json(payload),
                    now,
                    now,
                    now,
                ),
            )
            invalidated += 1
        conn.commit()

    return {
        "applied": True,
        "reason": "complete_snapshot_reconciled",
        "revoked_count": invalidated,
        "snapshot_observation_key": snapshot_key,
    }


def get_locator_observation(
    observation_key: str,
    *,
    include_expired: bool = False,
) -> dict[str, Any] | None:
    with _transaction() as conn:
        clause = "" if include_expired else " AND retain_until > ?"
        params: tuple[Any, ...] = (_non_empty(observation_key),) if include_expired else (_non_empty(observation_key), _utc_now())
        row = conn.execute(
            "SELECT * FROM locator_observations WHERE observation_key = ?" + clause,
            params,
        ).fetchone()
        return _public_row(row) if row is not None else None


def find_locator_observation(
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    network_domain_id: str = "",
    site_id: str = "",
    vrf_name: str = DEFAULT_VRF_NAME,
    device_id: str,
    observation_kind: str,
    target_ip: str = "",
    target_mac: str = "",
    bridge_domain: str = "",
    vlan_id: int | str | None = None,
    action_version: str | None = None,
    parser_version: str | None = None,
    schema_version: str | None = None,
) -> dict[str, Any] | None:
    """Read the newest still-fresh observation for one exact scope/target."""
    now = _utc_now()
    clauses = [
        "tenant_id = ?",
        "scope_hash = ?",
        "network_domain_id = ?",
        "site_id = ?",
        "vrf_name = ?",
        "device_id = ?",
        "observation_kind = ?",
        "target_ip = ?",
        "target_mac = ?",
        "bridge_domain = ?",
        "vlan_id IS NOT DISTINCT FROM ?",
        "coverage IN ('targeted', 'full')",
        "fresh_until > ?",
        "retain_until > ?",
    ]
    params = (
        _non_empty(tenant_id, DEFAULT_TENANT_ID),
        _non_empty(scope_hash),
        _non_empty(network_domain_id),
        _non_empty(site_id),
        _normalize_vrf(vrf_name),
        _non_empty(device_id),
        _non_empty(observation_kind).lower(),
        _non_empty(target_ip),
        _non_empty(target_mac).lower(),
        _non_empty(bridge_domain),
        _normalize_vlan(vlan_id),
        now,
        now,
    )
    for column, version in (
        ("action_version", action_version),
        ("parser_version", parser_version),
        ("schema_version", schema_version),
    ):
        if version is not None:
            clauses.append(f"{column} = ?")
            params += (_non_empty(version),)
    with _transaction() as conn:
        row = conn.execute(
            "SELECT * FROM locator_observations WHERE " + " AND ".join(clauses) +
            " ORDER BY collected_at DESC, generation DESC LIMIT 1",
            params,
        ).fetchone()
        return _public_row(row) if row is not None else None


def enqueue_locator_invalidation(
    *,
    event_key: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    scope_hash: str = "",
    generation: int = 0,
    payload: Mapping[str, Any] | None = None,
    available_at: datetime | str | None = None,
) -> dict[str, Any]:
    if int(generation) < 0:
        raise ValueError("generation must be non-negative")
    now = _utc_now()
    available = _as_utc(available_at, fallback=now)
    with _transaction() as conn:
        identifier = f"locator-invalidation:{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO locator_invalidation_outbox (
                id, event_key, tenant_id, scope_hash, entity_type, entity_id,
                event_type, generation, payload_json, status, attempts,
                available_at, lease_owner, lease_until, last_error,
                created_at, processed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, 'pending', 0, ?, '', NULL, '', ?, NULL, ?)
            ON CONFLICT (event_key) DO NOTHING
            """,
            (
                identifier,
                _non_empty(event_key),
                _non_empty(tenant_id, DEFAULT_TENANT_ID),
                _non_empty(scope_hash),
                _non_empty(entity_type),
                _non_empty(entity_id),
                _non_empty(event_type),
                int(generation),
                _json(payload or {}),
                available,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM locator_invalidation_outbox WHERE event_key = ?",
            (_non_empty(event_key),),
        ).fetchone()
        conn.commit()
        return _public_row(row)


def claim_locator_invalidation(
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_TASK_LEASE_SECONDS,
) -> dict[str, Any] | None:
    now = _utc_now()
    with _transaction() as conn:
        conn.execute(
            """
            UPDATE locator_invalidation_outbox
               SET status = 'pending', lease_owner = '', lease_token = '', lease_until = NULL,
                   updated_at = ?
             WHERE status = 'processing' AND lease_until IS NOT NULL AND lease_until <= ?
            """,
            (now, now),
        )
        row = conn.execute(
            """
            SELECT * FROM locator_invalidation_outbox
             WHERE status = 'pending' AND available_at <= ?
             ORDER BY available_at, created_at, id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (now,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        event = _row_dict(row)
        token = uuid.uuid4().hex
        due = now + timedelta(seconds=max(1, int(lease_seconds)))
        conn.execute(
            """
            UPDATE locator_invalidation_outbox
               SET status = 'processing', lease_owner = ?, lease_token = ?, lease_until = ?,
                   attempts = attempts + 1, updated_at = ?
             WHERE id = ? AND status = 'pending'
            """,
            (_non_empty(worker_id), token, due, now, event["id"]),
        )
        conn.commit()
        event.update({"status": "processing", "lease_owner": _non_empty(worker_id), "lease_token": token, "lease_until": due})
        return _public_row(event)


def has_pending_locator_invalidation(*, scope_hash: str, target_ip: str) -> bool:
    """Return whether a committed fact change may invalidate this cached trace."""
    scope = _non_empty(scope_hash)
    if not scope:
        return True
    with _transaction() as conn:
        row = conn.execute(
            """
            SELECT 1
              FROM locator_invalidation_outbox
             WHERE scope_hash = ?
               AND status IN ('pending', 'processing')
               AND (
                    COALESCE(payload_json->>'target_ip', '') = ''
                    OR payload_json->>'target_ip' = ?
               )
             LIMIT 1
            """,
            (scope, _non_empty(target_ip)),
        ).fetchone()
        return row is not None


def complete_locator_invalidation(
    event_id: str,
    *,
    worker_id: str,
    success: bool,
    lease_token: str | None = None,
    error_message: str = "",
    retry_at: datetime | str | None = None,
) -> bool:
    now = _utc_now()
    next_status = "processed" if success else ("pending" if retry_at is not None else "failed")
    available = _as_utc(retry_at, fallback=now) if retry_at is not None else now
    with _transaction() as conn:
        count = conn.execute(
            """
            UPDATE locator_invalidation_outbox
               SET status = ?, available_at = ?, lease_owner = '', lease_token = '', lease_until = NULL,
                   processed_at = CASE WHEN ? = 'processed' THEN ? ELSE processed_at END,
                   last_error = ?, updated_at = ?
             WHERE id = ? AND status = 'processing' AND lease_owner = ?
               AND (? = '' OR lease_token = ?)
            """,
            (
                next_status,
                available,
                next_status,
                now,
                _non_empty(error_message)[:1000],
                now,
                _non_empty(event_id),
                _non_empty(worker_id),
                _non_empty(lease_token),
                _non_empty(lease_token),
            ),
        ).rowcount
        conn.commit()
        return bool(count)


# Compatibility aliases used by workers that name the outbox explicitly.
enqueue_invalidation_event = enqueue_locator_invalidation
claim_invalidation_event = claim_locator_invalidation
complete_invalidation_event = complete_locator_invalidation


__all__ = [
    "DEFAULT_TENANT_ID",
    "DEFAULT_VRF_NAME",
    "LocatorLeaseLost",
    "LocatorPermissionError",
    "LocatorTaskError",
    "acquire_device_access_lease",
    "acquire_global_access_lease",
    "acquire_device_lease",
    "build_locator_query_key",
    "cancel_locator_run",
    "claim_locator_run",
    "claim_locator_runs",
    "claim_invalidation_event",
    "claim_locator_invalidation",
    "has_pending_locator_invalidation",
    "claim_locator_task",
    "cleanup_locator_tasks",
    "complete_invalidation_event",
    "complete_locator_invalidation",
    "complete_locator_task",
    "create_locator_run",
    "enqueue_invalidation_event",
    "enqueue_locator_invalidation",
    "enqueue_locator_task",
    "enqueue_locator_tasks",
    "ensure_device_access_slots",
    "ensure_global_access_slots",
    "find_locator_observation",
    "get_locator_dependency_generation",
    "get_locator_observation",
    "get_locator_run",
    "get_locator_task",
    "list_locator_run_tasks",
    "locator_dependency_manifest_is_current",
    "release_device_access_lease",
    "release_global_access_lease",
    "renew_global_access_lease",
    "release_device_lease",
    "renew_device_access_lease",
    "renew_device_lease",
    "renew_locator_task",
    "renew_locator_run_lease",
    "save_locator_run_result",
    "set_locator_run_status",
    "subscribe_locator_run",
    "upsert_locator_observation",
]
