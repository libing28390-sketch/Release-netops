"""Protocol evidence collection for the evidence-first topology graph."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.topology_graph_service import normalize_observation

PROTOCOL_CATEGORIES = (
    "ospf",
    "isis",
    "bgp",
    "routing_table",
    "interface_description",
    "stp",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _value(record: dict[str, Any], *names: str) -> Any:
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).lower()): value
        for key, value in record.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized.get(key) not in (None, ""):
            return normalized[key]
    return ""


def _valid_target(value: Any, local_ip: str = "") -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.lower() in {"0.0.0.0", "::", "0", "none", "null", "-", "self", "local"}:
        return ""
    if local_ip and value == str(local_ip).strip():
        return ""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        # Router IDs and ISIS system IDs are not IP literals but are valid
        # stable identities.
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{2,128}", value):
            return ""
    return value


def _description_target(record: dict[str, Any]) -> str:
    description = str(_value(record, "description", "desc", "interface_description") or "")
    if not description:
        return ""
    match = re.search(
        r"(?:to|uplink|downlink|upstream|downstream|peer|parent|child)"
        r"\s*[:=\-]?\s*([A-Za-z0-9_.:/-]+)",
        description,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _target_identity(category: str, record: dict[str, Any], local_ip: str) -> tuple[str, str]:
    if category == "routing_table":
        target = _value(record, "next_hop", "nexthop", "gateway", "via")
    elif category == "interface_description":
        target = _value(
            record,
            "neighbor",
            "neighbor_id",
            "remote_device",
            "remote_hostname",
            "peer",
        ) or _description_target(record)
    elif category == "stp":
        target = _value(
            record,
            "neighbor",
            "neighbor_id",
            "designated_bridge",
            "root_bridge",
            "remote_device",
        )
    else:
        target = _value(
            record,
            "neighbor",
            "neighbor_id",
            "neighbor_ip",
            "peer",
            "peer_ip",
            "peer_address",
            "bgp_neighbor",
            "bgp_neigh",
            "address",
            "ip",
            "ip_address",
            "remote_address",
            "remote_router_id",
            "router_id",
            "remote_system_id",
            "system_id",
        )
    target = _valid_target(target, local_ip)
    if not target:
        return "", ""
    try:
        ipaddress.ip_address(target)
        return target, target
    except ValueError:
        return target, ""


def _resolve_target_device(conn: Any, identity: str, ip: str) -> str | None:
    if not identity and not ip:
        return None
    rows = conn.execute(
        "SELECT id, hostname, sys_name, ip_address, sn FROM devices"
    ).fetchall()
    identity_lower = str(identity or "").strip().lower()
    ip_lower = str(ip or "").strip().lower()
    for row in rows:
        values = {
            str(row[key] or "").strip().lower()
            for key in ("hostname", "sys_name", "ip_address", "sn")
            if key in row.keys()
        }
        if (ip_lower and ip_lower in values) or (identity_lower and identity_lower in values):
            return str(row["id"])
    return None


def _category_relation(category: str, record: dict[str, Any]) -> tuple[str, str, str]:
    if category in {"ospf", "isis", "bgp"}:
        session_state = str(_value(record, "state", "status", "peer_state", "session_state") or "").lower()
        session_type = str(_value(record, "session_type", "type", "external") or "").lower()
        local_as = _value(record, "local_as", "local_asn", "localas")
        remote_as = _value(record, "asn", "remote_as", "remote_asn", "neigh_as")
        is_external_bgp = session_type in {"ebgp", "external", "ebgp_multihop"}
        if category == "bgp" and not is_external_bgp and local_as and remote_as:
            try:
                is_external_bgp = int(str(local_as)) != int(str(remote_as))
            except (TypeError, ValueError):
                is_external_bgp = False
        is_wan = category == "bgp" and is_external_bgp
        semantic = "WAN" if is_wan else "L3_NEIGHBOR"
        metadata = {
            "state": session_state,
            "area": _value(record, "area", "area_id"),
            "level": _value(record, "level", "isis_level"),
            "local_as": local_as,
            "remote_as": remote_as,
            "session_type": session_type,
        }
        return ("WAN" if is_wan else "L3_NEIGHBOR"), semantic, "undirected"
    if category == "routing_table":
        return "LOGICAL", "ROUTE_NEXT_HOP", "directed"
    if category == "stp":
        return "L2_NEIGHBOR", "STP_ADJACENCY", "undirected"
    if category == "interface_description":
        description = str(_value(record, "description", "desc", "interface_description") or "").lower()
        semantic = "HIERARCHICAL" if re.search(
            r"\b(parent|child|uplink|downlink|upstream|downstream|to[-_ ]?(core|agg|aggregation|access|fw|firewall|isp|wan|mpls))\b",
            description,
        ) else ""
        return ("HIERARCHICAL" if semantic else "UNKNOWN"), semantic, "directed" if semantic else "undirected"
    return "UNKNOWN", "", "undirected"


def normalize_protocol_records(
    device: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert operational collector records into graph-safe evidence rows."""
    source_id = str(device.get("id") or "")
    local_ip = str(device.get("ip_address") or "")
    collected_at = str(payload.get("collected_at") or _now())
    normalized_rows: list[dict[str, Any]] = []
    for category_result in payload.get("categories") or []:
        category = str(category_result.get("key") or "").strip().lower()
        if category not in PROTOCOL_CATEGORIES or not category_result.get("success", True):
            continue
        for raw_record in category_result.get("records") or []:
            record = dict(raw_record or {})
            identity, target_ip = _target_identity(category, record, local_ip)
            # A route with no next-hop and an interface description with no
            # semantic target are still useful evidence only when they have an
            # explicit target. Do not create self/empty edges.
            if not identity:
                continue
            relation_type, semantic_relation, direction = _category_relation(category, record)
            source_interface = _value(record, "interface", "local_interface", "source_interface", "port")
            target_interface = _value(record, "remote_interface", "target_interface", "neighbor_interface")
            metadata = {
                "category": category,
                "state": _value(record, "state", "status", "peer_state", "session_state"),
                "role": _value(record, "role", "stp_role"),
                "instance": _value(record, "instance", "mst_instance", "vlan"),
                "area": _value(record, "area", "area_id"),
                "level": _value(record, "level", "isis_level"),
                "prefix": _value(record, "prefix", "network", "destination"),
                "metric": _value(record, "metric", "cost"),
                "remote_as": _value(record, "asn", "remote_as", "remote_asn"),
                "session_type": _value(record, "session_type", "type", "external"),
                "description": _value(record, "description", "desc", "interface_description"),
            }
            metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
            raw_observation = {
                "source_device_id": source_id,
                "target_device_id": None,
                "target_identity": identity,
                "target_ip": target_ip,
                "source_interface": str(source_interface or ""),
                "target_interface": str(target_interface or ""),
                "protocol": "routing" if category == "routing_table" else category,
                "relation_type": relation_type,
                "semantic_relation": semantic_relation,
                "direction": direction,
                "metadata": metadata,
                "observed_at": collected_at,
            }
            # Normalizing here enforces the LLDP-only PHYSICAL guard and keeps
            # the graph payload independent from parser field names.
            graph_observation = normalize_observation(raw_observation)
            normalized_rows.append({
                "source_device_id": source_id,
                "target_device_id": None,
                "target_identity": identity,
                "target_ip": target_ip,
                "source_interface": str(source_interface or ""),
                "target_interface": str(target_interface or ""),
                "protocol": graph_observation["protocol"],
                "relation_type": graph_observation["relation_type"],
                "direction": graph_observation["direction"],
                "semantic_relation": graph_observation.get("semantic_relation") or "",
                "observation": {
                    "category": category,
                    "metadata": graph_observation.get("metadata") or {},
                    "source_interface": graph_observation.get("source_interface") or "",
                    "target_interface": graph_observation.get("target_interface") or "",
                },
                "confidence": 0.75 if category in {"ospf", "isis", "bgp"} else 0.6,
                "observed_at": collected_at,
                "collector": "operational_data_service",
            })
    return normalized_rows


def persist_protocol_observations(
    device: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    protocols: list[str] | None = None,
) -> int:
    source_device_id = str(device.get("id") or "")
    tenant_id = str(device.get("tenant_id") or "tenant-default")
    now = _now()
    protocol_set = {
        str(protocol or "").strip().lower()
        for protocol in (protocols or [])
        if str(protocol or "").strip()
    }
    protocol_set.update(
        str(item.get("protocol") or "").strip().lower()
        for item in observations
        if str(item.get("protocol") or "").strip()
    )
    collected_protocols = sorted(protocol_set)
    if not source_device_id or not collected_protocols:
        return 0
    with get_db_connection() as conn:
        active_ids: set[str] = set()
        for item in observations:
            stable = "|".join([
                tenant_id,
                source_device_id,
                str(item.get("protocol") or ""),
                str(item.get("target_identity") or ""),
                str(item.get("target_ip") or ""),
                str(item.get("source_interface") or ""),
                str(item.get("target_interface") or ""),
                str(item.get("relation_type") or ""),
            ])
            observation_id = "protocol_obs_" + hashlib.sha256(stable.encode()).hexdigest()[:32]
            active_ids.add(observation_id)
            target_device_id = _resolve_target_device(
                conn,
                str(item.get("target_identity") or ""),
                str(item.get("target_ip") or ""),
            )
            item["target_device_id"] = target_device_id
            conn.execute(
                """
                INSERT INTO topology_protocol_observations (
                    id, tenant_id, discovery_run_id, source_device_id, target_device_id,
                    target_identity, target_ip, source_interface, target_interface,
                    protocol, relation_type, direction, observation_json, confidence,
                    status, first_seen, last_seen, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    discovery_run_id = excluded.discovery_run_id,
                    target_device_id = excluded.target_device_id,
                    target_identity = excluded.target_identity,
                    target_ip = excluded.target_ip,
                    source_interface = excluded.source_interface,
                    target_interface = excluded.target_interface,
                    relation_type = excluded.relation_type,
                    direction = excluded.direction,
                    observation_json = excluded.observation_json,
                    confidence = excluded.confidence,
                    status = 'active',
                    last_seen = excluded.last_seen,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    observation_id, tenant_id, run_id, source_device_id,
                    target_device_id, item.get("target_identity") or "",
                    item.get("target_ip") or "", item.get("source_interface") or "",
                    item.get("target_interface") or "", item.get("protocol") or "",
                    item.get("relation_type") or "UNKNOWN", item.get("direction") or "undirected",
                    __import__("json").dumps({
                        **(item.get("observation") or {}),
                        "semantic_relation": item.get("semantic_relation") or "",
                    }, ensure_ascii=False),
                    float(item.get("confidence") or 0),
                    item.get("observed_at") or now, item.get("observed_at") or now,
                    now, now,
                ),
            )
        if collected_protocols:
            placeholders = ",".join("?" for _ in collected_protocols)
            if active_ids:
                id_placeholders = ",".join("?" for _ in active_ids)
                conn.execute(
                    f"""
                    UPDATE topology_protocol_observations
                    SET is_active = 0, status = 'stale', updated_at = ?
                    WHERE tenant_id = ? AND source_device_id = ?
                      AND protocol IN ({placeholders})
                      AND id NOT IN ({id_placeholders})
                    """,
                    (now, tenant_id, source_device_id, *collected_protocols, *active_ids),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE topology_protocol_observations
                    SET is_active = 0, status = 'stale', updated_at = ?
                    WHERE tenant_id = ? AND source_device_id = ?
                      AND protocol IN ({placeholders})
                    """,
                    (now, tenant_id, source_device_id, *collected_protocols),
                )
        conn.commit()
    return len(observations)


def collect_protocol_evidence(
    device: dict[str, Any],
    *,
    run_id: str | None = None,
    platform_action_session: Any = None,
) -> dict[str, Any]:
    """Collect OSPF/ISIS/BGP/routes/descriptions/STP and persist only facts."""
    from services.operational_data_service import collect_operational_data

    try:
        payload = collect_operational_data(
            device,
            categories=list(PROTOCOL_CATEGORIES),
            policy_override_categories=set(PROTOCOL_CATEGORIES),
            _platform_action_session=platform_action_session,
        )
        observations = normalize_protocol_records(device, payload)
        collected_protocols = [
            ("routing" if str(item.get("key") or "") == "routing_table" else str(item.get("key") or "").lower())
            for item in payload.get("categories") or []
            if item.get("success")
        ]
        count = persist_protocol_observations(
            device,
            observations,
            run_id=run_id,
            protocols=collected_protocols,
        )
        return {
            "success": True,
            "observations_count": count,
            "protocols": sorted({str(item.get("protocol") or "") for item in observations}),
            "categories": [
                {
                    "key": item.get("key"),
                    "success": bool(item.get("success")),
                    "count": int(item.get("count") or 0),
                    "parse_status": item.get("parse_status"),
                }
                for item in payload.get("categories") or []
            ],
        }
    except Exception as exc:
        return {
            "success": False,
            "observations_count": 0,
            "protocols": [],
            "error": str(exc)[:500],
        }


def get_active_protocol_observations(
    *,
    tenant_id: str = "tenant-default",
) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT source_device_id, target_device_id, target_identity, target_ip,
                   source_interface, target_interface, protocol, relation_type,
                   direction, observation_json, confidence, last_seen
            FROM topology_protocol_observations
            WHERE tenant_id = ? AND is_active = 1
            ORDER BY last_seen DESC
            """,
            (tenant_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            observation = {}
            try:
                import json
                observation = json.loads(item.pop("observation_json") or "{}")
            except Exception:
                pass
            result.append({**item, "observation": observation})
        return result
