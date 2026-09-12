"""PostgreSQL-fenced, Redis-projected full-device LLDP snapshots."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from database import get_db_connection

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = "topology-lldp-snapshot-v1"


class LLDPAttemptSuperseded(RuntimeError):
    """Raised when a slower collector loses ownership to a newer attempt."""


def _utc_iso(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _source_fingerprint(function: Any) -> str:
    if not callable(function):
        material = "missing"
    else:
        try:
            material = inspect.getsource(function)
        except (OSError, TypeError):
            code = getattr(function, "__code__", None)
            material = repr((
                getattr(function, "__module__", ""),
                getattr(function, "__qualname__", ""),
                getattr(code, "co_code", b"").hex(),
                getattr(code, "co_consts", ()),
            ))
    return hashlib.sha256(str(material).encode("utf-8")).hexdigest()


def lldp_snapshot_versions(device: Mapping[str, Any]) -> dict[str, str]:
    """Fingerprint the selected LLDP command/parser and the cache schema."""
    from services import topology_service
    from services.neighbor_collection_contract import classify_lldp_status, normalize_neighbor_record

    platform = topology_service.normalize_topology_platform(device.get("platform"))
    commands = topology_service.DISCOVERY_COMMANDS.get(platform) or []
    profile: dict[str, str] = {
        "platform_profile_id": str(device.get("platform_profile_id") or ""),
        "current_release_id": "",
        "release_checksum": "",
        "command_checksum": "",
        "parser_template_version_id": str(device.get("parser_template_version_id") or ""),
        "command": "",
    }
    device_id = str(device.get("id") or "").strip()
    if device_id and profile["platform_profile_id"]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT p.current_release_id, r.checksum AS release_checksum,
                          a.command_checksum, a.parser_template_version_id, a.command
                     FROM devices d
                     JOIN platform_profiles p ON p.id = d.platform_profile_id
                     LEFT JOIN platform_releases r ON r.id = p.current_release_id
                     LEFT JOIN platform_release_actions a
                       ON a.release_id = p.current_release_id
                      AND a.action_code = 'get_lldp_neighbors'
                    WHERE d.id = ?""",
                (device_id,),
            ).fetchone()
            if row is not None:
                for key in profile:
                    value = row.get(key) if hasattr(row, "get") else None
                    if value is None and hasattr(row, "keys") and key in row.keys():
                        value = row[key]
                    if value is not None:
                        profile[key] = str(value or "")
        except Exception:
            # The device/platform/profile fields still provide a stable fallback
            # for minimal test fixtures or a not-yet-published profile action.
            logger.debug("LLDP profile fingerprint lookup unavailable", exc_info=True)
        finally:
            conn.close()
    if not profile["command"]:
        profile["command"] = "|".join(command for _, command in commands)
    action_material = {
        "contract": "topology-lldp-action-v1",
        "platform": platform,
        "commands": [(str(kind), str(command)) for kind, command in commands],
        "profile": profile,
    }
    parser_functions = (
        topology_service._collect_device_observations,
        topology_service._collect_neighbors_with_netmiko,
        topology_service._extract_observation_fields,
        topology_service._deduplicate_observations,
        topology_service._parse_shared_lldp_output,
        topology_service._regex_parse_lldp_detail,
        classify_lldp_status,
        normalize_neighbor_record,
    )
    parser_material = {
        "contract": "topology-lldp-parser-v1",
        "platform": platform,
        "functions": [_source_fingerprint(function) for function in parser_functions],
    }
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "action_version": hashlib.sha256(encode(action_material).encode("utf-8")).hexdigest(),
        "parser_version": hashlib.sha256(encode(parser_material).encode("utf-8")).hexdigest(),
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
    }


def begin_lldp_snapshot_attempt(
    device: Mapping[str, Any],
    versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Increment the per-device attempt generation before any device I/O."""
    device_id = str(device.get("id") or "").strip()
    if not device_id:
        raise ValueError("device_id is required for an LLDP snapshot")
    selected_versions = dict(versions or lldp_snapshot_versions(device))
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            INSERT INTO topology_device_lldp_snapshots (
                device_id, generation, state, snapshot_complete, observation_count,
                started_at, completed_at, action_version, parser_version,
                schema_version, updated_at
            ) VALUES (?, 1, 'collecting', FALSE, 0, clock_timestamp(), NULL, ?, ?, ?, clock_timestamp())
            ON CONFLICT (device_id) DO UPDATE SET
                generation = topology_device_lldp_snapshots.generation + 1,
                state = 'collecting',
                snapshot_complete = FALSE,
                observation_count = 0,
                started_at = clock_timestamp(),
                completed_at = NULL,
                action_version = EXCLUDED.action_version,
                parser_version = EXCLUDED.parser_version,
                schema_version = EXCLUDED.schema_version,
                updated_at = clock_timestamp()
            RETURNING device_id, generation, state, snapshot_complete,
                      observation_count, started_at, completed_at,
                      action_version, parser_version, schema_version
            """,
            (
                device_id,
                selected_versions["action_version"],
                selected_versions["parser_version"],
                selected_versions["schema_version"],
            ),
        ).fetchone()
        conn.commit()
        return _marker_dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fail_lldp_snapshot_attempt(device_id: str, generation: int) -> bool:
    """Invalidate a failed attempt only if it still owns the current token."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE topology_device_lldp_snapshots
               SET state = 'failed', snapshot_complete = FALSE,
                   completed_at = clock_timestamp(), updated_at = clock_timestamp()
             WHERE device_id = ? AND generation = ? AND state = 'collecting'
            """,
            (str(device_id), int(generation)),
        )
        conn.commit()
        return int(getattr(cursor, "rowcount", 0) or 0) == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_lldp_snapshot_in_transaction(
    conn: Any,
    *,
    device_id: str,
    generation: int,
    observation_count: int,
) -> dict[str, Any]:
    """Atomically complete a snapshot alongside topology observation writes."""
    row = conn.execute(
        """SELECT generation, state FROM topology_device_lldp_snapshots
             WHERE device_id = ? FOR UPDATE""",
        (str(device_id),),
    ).fetchone()
    if row is None or int(row[0] or 0) != int(generation) or str(row[1] or "") != "collecting":
        raise LLDPAttemptSuperseded("LLDP snapshot attempt no longer owns this device")
    updated = conn.execute(
        """
        UPDATE topology_device_lldp_snapshots
           SET state = 'complete', snapshot_complete = TRUE,
               observation_count = ?, completed_at = clock_timestamp(),
               updated_at = clock_timestamp()
         WHERE device_id = ? AND generation = ? AND state = 'collecting'
        RETURNING device_id, generation, state, snapshot_complete,
                  observation_count, started_at, completed_at,
                  action_version, parser_version, schema_version
        """,
        (max(0, int(observation_count)), str(device_id), int(generation)),
    ).fetchone()
    if updated is None:
        raise LLDPAttemptSuperseded("LLDP snapshot attempt was superseded before commit")
    return _marker_dict(updated)


def get_lldp_snapshot_marker(device_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT device_id, generation, state, snapshot_complete,
                      observation_count, started_at, completed_at,
                      action_version, parser_version, schema_version
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""",
            (str(device_id),),
        ).fetchone()
        return _marker_dict(row) if row is not None else None
    finally:
        conn.close()


def _marker_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        item = {key: row[key] for key in row.keys()}
    else:
        item = dict(row)
    for key in ("started_at", "completed_at"):
        item[key] = _utc_iso(item.get(key)) if item.get(key) is not None else ""
    item["generation"] = int(item.get("generation") or 0)
    item["observation_count"] = int(item.get("observation_count") or 0)
    item["snapshot_complete"] = bool(item.get("snapshot_complete"))
    return item


def snapshot_dependency(marker: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "device_id": str(marker.get("device_id") or ""),
        "generation": int(marker.get("generation") or 0),
        "action_version": str(marker.get("action_version") or ""),
        "parser_version": str(marker.get("parser_version") or ""),
        "schema_version": str(marker.get("schema_version") or ""),
    }


def _snapshot_scope_hash(cache: Any, device: Mapping[str, Any]) -> str:
    return cache.scope_hash({
        "device_id": str(device.get("id") or ""),
        "site_id": str(device.get("site_id") or ""),
        "tenant_id": str(device.get("tenant_id") or ""),
        "snapshot": "lldp-full",
    })


def _snapshot_cache_key(cache: Any, device: Mapping[str, Any], generation: int) -> str:
    scope_hash = _snapshot_scope_hash(cache, device)
    return cache.build_key("topology_snapshot", scope_hash, str(generation)) if scope_hash else ""


def _snapshot_records(conn: Any, device_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT source_port_raw, source_port_normalized, neighbor_name_raw,
                  neighbor_ip_address, target_device_id, target_port_raw,
                  target_port_normalized, protocol
             FROM topology_observations
            WHERE source_device_id = ? AND protocol = 'lldp'
              AND COALESCE(is_active, 1) = 1
              AND COALESCE(status, 'active') = 'active'
            ORDER BY source_port_normalized, neighbor_name_normalized,
                     target_port_normalized, target_device_id""",
        (str(device_id),),
    ).fetchall()
    records = []
    for raw in rows:
        item = dict(raw) if hasattr(raw, "keys") else dict(raw)
        records.append({
            "local_interface": str(item.get("source_port_raw") or item.get("source_port_normalized") or ""),
            "neighbor": str(item.get("neighbor_name_raw") or ""),
            "neighbor_port": str(item.get("target_port_raw") or item.get("target_port_normalized") or ""),
            "neighbor_ip": str(item.get("neighbor_ip_address") or ""),
            "neighbor_id": str(item.get("target_device_id") or ""),
            "protocol": str(item.get("protocol") or "lldp"),
            "evidence": "topology_snapshot",
        })
    return records


def _snapshot_payload(marker: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generation": int(marker.get("generation") or 0),
        "snapshot_complete": True,
        "observation_count": int(marker.get("observation_count") or 0),
        "collected_at": str(marker.get("completed_at") or ""),
        "action_version": str(marker.get("action_version") or ""),
        "parser_version": str(marker.get("parser_version") or ""),
        "schema_version": str(marker.get("schema_version") or ""),
        "neighbors": records,
    }


def _marker_is_current_for_device(marker: Mapping[str, Any], device: Mapping[str, Any]) -> bool:
    if (
        str(marker.get("state") or "") != "complete"
        or not bool(marker.get("snapshot_complete"))
        or not str(marker.get("completed_at") or "")
        or int(marker.get("generation") or 0) <= 0
    ):
        return False
    try:
        versions = lldp_snapshot_versions(device)
    except Exception:
        return False
    return all(str(marker.get(key) or "") == str(versions.get(key) or "") for key in (
        "action_version", "parser_version", "schema_version",
    ))


def load_complete_lldp_snapshot(
    device: Mapping[str, Any],
    *,
    cache: Any = None,
    marker: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read a current Redis snapshot, rebuilding it from committed PG facts on miss."""
    device_id = str(device.get("id") or "").strip()
    if not device_id:
        return None
    selected_marker = dict(marker or get_lldp_snapshot_marker(device_id) or {})
    if not _marker_is_current_for_device(selected_marker, device):
        return None

    try:
        from core.config import settings

        freshness_seconds = int(getattr(settings, "IP_LOCATOR_TOPOLOGY_FRESH_SECONDS", 172800))
        age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(
            str(selected_marker.get("completed_at")).replace("Z", "+00:00")
        )).total_seconds()))
        if age > freshness_seconds:
            return None
    except (TypeError, ValueError, OverflowError):
        return None

    cache_key = _snapshot_cache_key(cache, device, int(selected_marker["generation"])) if cache is not None else ""
    if cache is not None and cache_key:
        cached = cache.get_json(cache_key)
        if isinstance(cached, dict) and all(
            cached.get(key) == expected
            for key, expected in (
                ("generation", int(selected_marker["generation"])),
                ("snapshot_complete", True),
                ("observation_count", int(selected_marker["observation_count"])),
                ("collected_at", str(selected_marker["completed_at"])),
                ("action_version", str(selected_marker["action_version"])),
                ("parser_version", str(selected_marker["parser_version"])),
                ("schema_version", str(selected_marker["schema_version"])),
            )
        ) and isinstance(cached.get("neighbors"), list) and len(cached["neighbors"]) == int(selected_marker["observation_count"]):
            try:
                if cache.is_fresh("topology", cached.get("collected_at")):
                    current = get_lldp_snapshot_marker(device_id)
                    if current and int(current.get("generation") or 0) == int(selected_marker["generation"]) and current.get("state") == "complete":
                        return {**cached, "source": "redis", "marker": selected_marker}
            except Exception:
                pass

    conn = get_db_connection()
    try:
        before = conn.execute(
            """SELECT device_id, generation, state, snapshot_complete,
                      observation_count, started_at, completed_at,
                      action_version, parser_version, schema_version
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""",
            (device_id,),
        ).fetchone()
        before_marker = _marker_dict(before) if before is not None else {}
        if (
            not before_marker
            or int(before_marker.get("generation") or 0) != int(selected_marker["generation"])
            or before_marker.get("state") != "complete"
            or not before_marker.get("snapshot_complete")
        ):
            return None
        records = _snapshot_records(conn, device_id)
        after = conn.execute(
            """SELECT generation, state, snapshot_complete, observation_count
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""",
            (device_id,),
        ).fetchone()
        if (
            after is None
            or int(after[0] or 0) != int(selected_marker["generation"])
            or str(after[1] or "") != "complete"
            or not bool(after[2])
            or int(after[3] or 0) != len(records)
            or len(records) != int(selected_marker["observation_count"])
        ):
            return None
    finally:
        conn.close()

    payload = _snapshot_payload(selected_marker, records)
    redis_written = False
    redis_write_attempted = bool(
        cache is not None
        and cache_key
        and str(getattr(cache, "backend", "redis") or "redis").strip().lower() == "redis"
    )
    if redis_write_attempted:
        try:
            policy = cache.policy("topology")
            redis_written = cache.set_json(
                cache_key,
                payload,
                kind="topology",
                collected_at=payload["collected_at"],
                retain_seconds=int(policy.retain_seconds) if policy else None,
            ) is True
        except Exception as exc:
            logger.debug("LLDP Redis projection skipped (%s)", type(exc).__name__)
    return {
        **payload,
        "source": "postgres",
        "redis_write_attempted": redis_write_attempted,
        "redis_written": redis_written,
        "marker": selected_marker,
    }


def publish_completed_lldp_snapshot(
    device: Mapping[str, Any],
    *,
    generation: int,
    cache: Any = None,
) -> bool:
    """Prime one generation-qualified Redis key after the PG commit succeeds."""
    if cache is None:
        try:
            from services.ip_locator_cache_service import get_locator_cache

            cache = get_locator_cache()
        except Exception:
            return False
    marker = get_lldp_snapshot_marker(str(device.get("id") or ""))
    if (
        not marker
        or int(marker.get("generation") or 0) != int(generation)
        or not _marker_is_current_for_device(marker, device)
    ):
        return False
    snapshot = load_complete_lldp_snapshot(device, cache=cache, marker=marker)
    if not snapshot:
        return False
    return snapshot.get("source") == "redis" or snapshot.get("redis_written") is True


__all__ = [
    "LLDPAttemptSuperseded",
    "SNAPSHOT_SCHEMA_VERSION",
    "begin_lldp_snapshot_attempt",
    "complete_lldp_snapshot_in_transaction",
    "fail_lldp_snapshot_attempt",
    "get_lldp_snapshot_marker",
    "load_complete_lldp_snapshot",
    "lldp_snapshot_versions",
    "publish_completed_lldp_snapshot",
    "snapshot_dependency",
]
