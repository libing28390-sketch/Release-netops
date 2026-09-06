"""Evidence-first topology graph and relation engine.

The graph deliberately keeps four concerns separate:

* asset identity (role, function, site and zone);
* observed facts (protocol evidence);
* semantic relations (physical, peer, hierarchy, OOB, ...);
* visual layout (dynamic ranks and user overrides).

LLDP/CDP is the only automatic source that can create a PHYSICAL relation.
Other protocols create logical or semantic evidence and are never promoted to
physical links by name matching or by device role.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable

from database import get_db_connection

NODE_TYPES = {"DEVICE", "SITE", "EXTERNAL", "VIRTUAL", "GROUP", "UNKNOWN"}
ROLE_IDENTITIES = {
    "ROUTER", "FIREWALL", "CORE_SWITCH", "AGGREGATION_SWITCH", "ACCESS_SWITCH",
    "SERVER_SWITCH", "SWITCH", "WIRELESS_AC", "WIRELESS_AP", "AC", "AP",
    "LOAD_BALANCER", "WAF", "VPN_GATEWAY", "EDGE", "SDWAN_EDGE", "OOB_SWITCH",
    "SERVER", "OTHER", "UNKNOWN",
}
RELATION_TYPES = {
    "PHYSICAL", "HIERARCHICAL", "PEER", "HA", "HA_PEER", "VRRP_HSRP",
    "STACK", "IRF", "CSS", "VC", "MLAG_PEER", "VPC_PEER",
    "L2_NEIGHBOR", "L3_NEIGHBOR", "LOGICAL", "ENDPOINT", "TUNNEL",
    "WAN", "INTER_SITE", "CONTROL", "OOB", "BRANCH", "RING", "UNKNOWN",
}

SOURCE_PRIORITY = {
    "manual": 100,
    "lldp": 95,
    "cdp": 92,
    "lag": 85,
    "stp": 80,
    "ha": 75,
    "vrrp": 74,
    "hsrp": 74,
    "stack": 73,
    "irf": 73,
    "css": 73,
    "vc": 73,
    "mlag": 73,
    "vpc": 73,
    "ospf": 65,
    "isis": 65,
    "bgp": 62,
    "routing": 55,
    "route": 55,
    "interface_ip": 52,
    "description": 42,
    "interface_description": 42,
    "arp": 20,
    "mac": 20,
}

_EQUAL_RANK_RELATIONS = {
    "PEER", "L3_NEIGHBOR", "L2_NEIGHBOR", "HA", "HA_PEER", "VRRP_HSRP",
    "STACK", "IRF", "CSS", "VC", "MLAG_PEER", "VPC_PEER", "RING",
}
_RANK_EXCLUDED_RELATIONS = {
    "HA", "HA_PEER", "VRRP_HSRP", "STACK", "IRF", "CSS", "VC",
    "MLAG_PEER", "VPC_PEER", "OOB", "INTER_SITE", "UNKNOWN",
}
_DIRECTED_RELATIONS = {"HIERARCHICAL", "LOGICAL", "BRANCH", "TUNNEL", "WAN"}
_UNDIRECTED_RELATIONS = {
    "PHYSICAL", "PEER", "L2_NEIGHBOR", "ENDPOINT", "HA", "HA_PEER",
    "VRRP_HSRP", "STACK", "IRF", "CSS", "VC", "MLAG_PEER", "VPC_PEER",
    "INTER_SITE", "CONTROL", "OOB", "RING", "UNKNOWN",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _normalize_device_ids(device_ids: list[str] | None) -> list[str] | None:
    """Normalize an optional device scope without widening an empty scope."""

    if device_ids is None:
        return None
    return sorted({
        str(device_id).strip()
        for device_id in device_ids
        if device_id is not None and str(device_id).strip()
    })


def _table_exists(conn: Any, table_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table_name,),
        ).fetchone()
    )


def normalize_role(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "CORE": "CORE_SWITCH",
        "CORE_SWITCH": "CORE_SWITCH",
        "CORESWITCH": "CORE_SWITCH",
        "DISTRIBUTION": "AGGREGATION_SWITCH",
        "DIST": "AGGREGATION_SWITCH",
        "AGGREGATION": "AGGREGATION_SWITCH",
        "AGG": "AGGREGATION_SWITCH",
        "AGGREGATION_SWITCH": "AGGREGATION_SWITCH",
        "ACCESS": "ACCESS_SWITCH",
        "ACCESS_SWITCH": "ACCESS_SWITCH",
        "ACCESSSWITCH": "ACCESS_SWITCH",
        "SERVER_ACCESS": "SERVER_SWITCH",
        "SERVER_SWITCH": "SERVER_SWITCH",
        "AP_CONTROLLER": "WIRELESS_AC",
        "WIRELESS_CONTROLLER": "WIRELESS_AC",
        "WIRELESS_AC": "WIRELESS_AC",
        "WIRELESS_AP": "WIRELESS_AP",
        "LOADBALANCER": "LOAD_BALANCER",
        "SD_WAN_EDGE": "SDWAN_EDGE",
        "SDWAN": "SDWAN_EDGE",
        "OOB": "OOB_SWITCH",
        "OOB_SWITCH": "OOB_SWITCH",
        "ROUTING": "ROUTER",
        "OTHER_NETWORK": "OTHER",
        "OTHER": "OTHER",
    }
    return aliases.get(text, text if text in ROLE_IDENTITIES else "UNKNOWN")


def _node_id_for(tenant_id: str, canonical: str) -> str:
    return f"node_{hashlib.sha256(f'{tenant_id}:{canonical}'.encode()).hexdigest()[:20]}"


def normalize_node(raw: dict[str, Any], *, tenant_id: str = "tenant-default") -> dict[str, Any]:
    node_type = str(raw.get("node_type") or raw.get("type") or "").strip().upper()
    if not node_type:
        node_type = "EXTERNAL" if raw.get("is_external") else "DEVICE"
    if node_type not in NODE_TYPES:
        node_type = "UNKNOWN"
    canonical = str(
        raw.get("canonical_key")
        or raw.get("id")
        or raw.get("device_id")
        or raw.get("hostname")
        or raw.get("ip_address")
        or uuid.uuid4().hex
    ).strip()
    metadata = dict(raw.get("metadata") or {})
    if raw.get("ip_address"):
        metadata.setdefault("ip_address", raw.get("ip_address"))
    return {
        "id": str(raw.get("id") or _node_id_for(tenant_id, canonical)),
        "tenant_id": tenant_id,
        "node_type": node_type,
        "canonical_key": canonical,
        "display_name": str(raw.get("display_name") or raw.get("hostname") or canonical),
        "device_id": raw.get("device_id") or (canonical if node_type == "DEVICE" else None),
        "site_id": raw.get("site_id"),
        "role_identity": normalize_role(raw.get("role_identity") or raw.get("role")),
        # Role is identity only. Function and zone are separate semantic data.
        "function": str(raw.get("function") or "").strip() or None,
        "zone": str(raw.get("zone") or "").strip() or None,
        "status": str(raw.get("status") or "active").lower(),
        "metadata": metadata,
        "first_seen": raw.get("first_seen") or now_iso(),
        "last_seen": raw.get("last_seen") or now_iso(),
        "rank": raw.get("rank", 0),
        "layout_override": dict(raw.get("layout_override") or {}),
    }


def _explicit_relation(raw: dict[str, Any]) -> str:
    relation = str(raw.get("relation_type") or raw.get("relation") or "").strip().upper()
    aliases = {
        "L3": "L3_NEIGHBOR",
        "L3_PEER": "PEER",
        "L2": "L2_NEIGHBOR",
        "VRRP": "VRRP_HSRP",
        "HSRP": "VRRP_HSRP",
        "MLAG": "MLAG_PEER",
        "VPC": "VPC_PEER",
        "SITE": "INTER_SITE",
    }
    relation = aliases.get(relation, relation)
    return relation if relation in RELATION_TYPES else ""


def _is_oob(raw: dict[str, Any], protocol: str) -> bool:
    metadata = raw.get("metadata") or {}
    values = [
        raw.get("zone"), raw.get("network_zone"), raw.get("path"),
        metadata.get("zone"), metadata.get("network_zone"), metadata.get("path"),
        protocol, raw.get("source_type"), raw.get("source"),
    ]
    return any(str(value or "").strip().lower() in {"oob", "out_of_band", "management"} for value in values)


def _description_relation(raw: dict[str, Any]) -> tuple[str, str]:
    metadata = raw.get("metadata") or {}
    semantic = str(
        raw.get("semantic_relation")
        or metadata.get("semantic_relation")
        or metadata.get("relation")
        or ""
    ).strip().upper()
    if semantic in {"PARENT", "CHILD", "UPLINK", "DOWNLINK", "HIERARCHICAL"}:
        return "HIERARCHICAL", semantic
    description = str(raw.get("description") or metadata.get("description") or "").lower()
    if re_search := __import__("re").search(r"\b(?:parent|child|uplink|downlink|upstream|downstream)\b", description):
        return "HIERARCHICAL", re_search.group(0).upper()
    return "UNKNOWN", ""


def normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    source_type = str(raw.get("source_type") or raw.get("source") or "unknown").strip().lower()
    protocol = str(raw.get("protocol") or source_type).strip().lower()
    explicit = _explicit_relation(raw)
    semantic_relation = str(raw.get("semantic_relation") or "").strip().upper()
    metadata = dict(raw.get("metadata") or {})

    if _is_oob(raw, protocol):
        relation_type = "OOB"
        semantic_relation = semantic_relation or "OUT_OF_BAND"
    elif explicit:
        relation_type = explicit
    elif source_type in {"lldp", "cdp"} or protocol in {"lldp", "cdp"}:
        relation_type = "PHYSICAL"
    elif protocol in {"ha", "ha_peer", "firewall_ha", "cluster"} or source_type in {"ha", "ha_peer", "firewall_ha"}:
        relation_type = "HA_PEER"
    elif protocol in {"vrrp", "hsrp"}:
        relation_type = "VRRP_HSRP"
    elif protocol in {"stack", "irf", "css", "vc", "mlag", "vpc"}:
        relation_type = {
            "stack": "STACK", "irf": "IRF", "css": "CSS", "vc": "VC",
            "mlag": "MLAG_PEER", "vpc": "VPC_PEER",
        }[protocol]
    elif protocol in {"inter_site", "site_interconnect"} or source_type in {"inter_site", "site_interconnect"}:
        relation_type = "INTER_SITE"
    elif protocol in {"control", "ap_ac", "wireless_control"} or source_type in {"control", "ap_ac", "wireless_control"}:
        relation_type = "CONTROL"
    elif protocol in {"branch", "firewall_branch"} or source_type in {"branch", "firewall_branch"}:
        relation_type = "BRANCH"
    elif protocol in {"ring", "stp_ring"} or source_type in {"ring", "stp_ring"}:
        relation_type = "RING"
    elif protocol in {"tunnel", "vpn", "gre", "ipsec"} or source_type in {"tunnel", "vpn"}:
        relation_type = "TUNNEL"
    elif protocol in {"ospf", "isis", "bgp", "interface_ip"}:
        # Protocol adjacencies are logical L3 facts. BGP external sessions are
        # promoted to WAN semantics, but neither case asserts a physical link.
        relation_type = "L3_NEIGHBOR"
        semantic_relation = semantic_relation or "L3_NEIGHBOR"
        if protocol == "bgp" and str(metadata.get("session_type") or "").lower() in {"ebgp", "external"}:
            relation_type = "WAN"
            semantic_relation = "WAN"
    elif protocol in {"route", "routing", "routing_table"}:
        relation_type = "LOGICAL"
        semantic_relation = semantic_relation or "ROUTE_NEXT_HOP"
    elif source_type in {"stp", "mstp"} or protocol in {"stp", "mstp"}:
        relation_type = "L2_NEIGHBOR"
        semantic_relation = semantic_relation or "STP_ADJACENCY"
    elif source_type in {"arp", "mac", "mac_table"}:
        relation_type = "ENDPOINT"
        semantic_relation = semantic_relation or "ENDPOINT_LOCATION"
    elif source_type in {"description", "interface_description"}:
        relation_type, inferred_semantic = _description_relation(raw)
        semantic_relation = semantic_relation or inferred_semantic
    else:
        relation_type = "UNKNOWN"

    # Only LLDP/CDP/manual evidence may assert physical existence.
    if relation_type == "PHYSICAL" and source_type not in {"lldp", "cdp", "manual"} and protocol not in {"lldp", "cdp"}:
        relation_type = "UNKNOWN"
        semantic_relation = semantic_relation or "UNTRUSTED_PHYSICAL_ASSERTION"

    direction = str(raw.get("direction") or "").strip().lower()
    if direction not in {"directed", "undirected", "unknown"}:
        direction = "undirected" if relation_type in _UNDIRECTED_RELATIONS else "directed"

    source_node = str(raw.get("source_node") or raw.get("source_device_id") or "").strip() or "unknown"
    target_node = str(
        raw.get("target_node")
        or raw.get("target_device_id")
        or raw.get("target_identity")
        or raw.get("neighbor")
        or ""
    ).strip() or "unknown"
    metadata.setdefault("protocol", protocol)
    if raw.get("target_ip"):
        metadata.setdefault("target_ip", raw.get("target_ip"))
    if raw.get("state") is not None:
        metadata.setdefault("state", raw.get("state"))
    if raw.get("role") is not None:
        metadata.setdefault("role", raw.get("role"))
    if raw.get("instance") is not None:
        metadata.setdefault("instance", raw.get("instance"))

    return {
        "source_node": source_node,
        "target_node": target_node,
        "source_interface": raw.get("source_interface") or raw.get("source_port") or raw.get("local_interface"),
        "target_interface": raw.get("target_interface") or raw.get("target_port") or raw.get("remote_interface"),
        "source_type": source_type,
        "protocol": protocol,
        "relation_type": relation_type,
        "semantic_relation": semantic_relation,
        "direction": direction,
        "confidence": _safe_float(raw.get("confidence"), 0.5),
        "observed_at": raw.get("observed_at") or raw.get("collected_at") or now_iso(),
        "metadata": metadata,
        "is_manual": int(bool(raw.get("is_manual") or source_type == "manual")),
        "target_ip": raw.get("target_ip") or raw.get("neighbor_ip") or "",
        "group_id": raw.get("group_id") or metadata.get("group_id"),
        "group_type": raw.get("group_type") or metadata.get("group_type"),
    }


def canonical_edge_key(observation: dict[str, Any], *, tenant_id: str = "tenant-default") -> str:
    item = normalize_observation(observation)
    left = (str(item["source_node"]), str(item.get("source_interface") or ""))
    right = (str(item["target_node"]), str(item.get("target_interface") or ""))
    if item["direction"] in {"undirected", "unknown"} or item["relation_type"] in _UNDIRECTED_RELATIONS:
        left, right = sorted((left, right))
    raw = "|".join([tenant_id, left[0], left[1], right[0], right[1], item["relation_type"]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _confidence(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    weighted = sum(
        _safe_float(item.get("confidence"), 0.0)
        * SOURCE_PRIORITY.get(str(item.get("source_type") or "").lower(), 10)
        for item in evidence
    )
    total = sum(SOURCE_PRIORITY.get(str(item.get("source_type") or "").lower(), 10) for item in evidence)
    independent = len({str(item.get("source_type") or "").lower() for item in evidence})
    bonus = min(0.2, max(0, independent - 1) * 0.05)
    return round(min(1.0, (weighted / total if total else 0.0) + bonus), 4)


def _existence_confidence(evidence: list[dict[str, Any]]) -> float:
    remaining = 1.0
    for item in evidence:
        remaining *= 1.0 - _safe_float(item.get("confidence"), 0.0)
    return round(1.0 - remaining, 4)


def detect_topology_anchors(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find zero-or-more topology anchors from explicit semantic evidence.

    Anchors are navigation/layout hints, not parents and not rank sources. The
    detector intentionally uses function, zone, external-node type, route/WAN
    metadata, and manual flags; it never promotes a device role into a root.
    """
    node_list = list(nodes)
    node_map = {str(node.get("id")): node for node in node_list if node.get("id")}
    reasons: dict[str, set[str]] = defaultdict(set)
    for node in node_list:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        function = str(node.get("function") or metadata.get("function") or "").lower()
        zone = str(node.get("zone") or metadata.get("zone") or "").lower()
        node_type = str(node.get("node_type") or "").upper()
        if node_type == "EXTERNAL":
            reasons[node_id].add("external_node")
        if metadata.get("manual_anchor") or metadata.get("anchor"):
            reasons[node_id].add("manual")
        if metadata.get("default_route") or metadata.get("has_default_route"):
            reasons[node_id].add("default_route")
        if any(token in function for token in ("internet", "wan", "site_interconnect", "vpn_gateway", "mpls", "isp")):
            reasons[node_id].add("function")
        if any(token in zone for token in ("internet", "wan", "oob", "management")):
            reasons[node_id].add("zone")

    for edge in edges:
        relation = str(edge.get("relation_type") or "").upper()
        semantic = str(edge.get("semantic_relation") or "").upper()
        if relation not in {"WAN", "INTER_SITE"} and semantic not in {"WAN", "DEFAULT_ROUTE", "SITE_INTERCONNECT"}:
            continue
        left = str(edge.get("source_node_id") or "")
        right = str(edge.get("target_node_id") or "")
        for node_id in (left, right):
            if node_id in node_map:
                reasons[node_id].add("wan_or_site_relation")

    anchors: list[dict[str, Any]] = []
    for node_id, node_reasons in reasons.items():
        node = node_map.get(node_id, {})
        priority = 1.0 if "manual" in node_reasons else (
            0.95 if "external_node" in node_reasons else 0.75
        )
        anchors.append({
            "node_id": node_id,
            "display_name": node.get("display_name") or node_id,
            "anchor_type": "EXTERNAL" if str(node.get("node_type") or "").upper() == "EXTERNAL" else "BOUNDARY",
            "confidence": priority,
            "reasons": sorted(node_reasons),
        })
    return sorted(anchors, key=lambda item: (-float(item["confidence"]), str(item["node_id"])))


class _DisjointSet:
    def __init__(self, items: Iterable[str]):
        self.parent = {str(item): str(item) for item in items}

    def find(self, item: str) -> str:
        item = str(item)
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def calculate_dynamic_ranks(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    """Calculate stable ranks from relation constraints, never from role labels.

    Directed cycles are collapsed into strongly connected components before
    ranks are propagated.  This makes a loop a single equal-rank unit instead
    of allowing bounded relaxation to produce order-dependent values.
    """
    node_ids = sorted({str(node["id"]) for node in nodes})
    node_id_set = set(node_ids)
    dsu = _DisjointSet(node_ids)
    for edge in edges:
        relation = str(edge.get("relation_type") or "").upper()
        source_id = str(edge.get("source_node_id") or "")
        target_id = str(edge.get("target_node_id") or "")
        if (
            source_id in node_id_set
            and target_id in node_id_set
            and relation in _EQUAL_RANK_RELATIONS
            and not int(edge.get("rank_excluded") or 0)
        ):
            dsu.union(source_id, target_id)

    components = {dsu.find(node_id) for node_id in node_ids}
    component_rank = {component: 0 for component in components}
    for node in nodes:
        try:
            component_rank[dsu.find(str(node["id"]))] = max(
                component_rank[dsu.find(str(node["id"]))], int(float(node.get("rank") or 0)),
            )
        except (TypeError, ValueError):
            pass

    adjacency: dict[str, set[str]] = {component: set() for component in components}
    for edge in edges:
        relation = str(edge.get("relation_type") or "").upper()
        source_id = str(edge.get("source_node_id") or "")
        target_id = str(edge.get("target_node_id") or "")
        if (
            edge.get("direction") == "directed"
            and relation in _DIRECTED_RELATIONS
            and not int(edge.get("rank_excluded") or 0)
            and relation not in _RANK_EXCLUDED_RELATIONS
            and source_id in node_id_set
            and target_id in node_id_set
        ):
            source_component = dsu.find(source_id)
            target_component = dsu.find(target_id)
            if source_component == target_component:
                continue
            adjacency.setdefault(source_component, set()).add(target_component)

    # Tarjan SCC traversal is sorted at every boundary so node/edge input
    # order cannot change either the components or their final ranks.
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    strongly_connected: list[tuple[str, ...]] = []

    def visit(component: str) -> None:
        nonlocal index
        indices[component] = index
        lowlinks[component] = index
        index += 1
        stack.append(component)
        on_stack.add(component)
        for target in sorted(adjacency.get(component, set())):
            if target not in indices:
                visit(target)
                lowlinks[component] = min(lowlinks[component], lowlinks[target])
            elif target in on_stack:
                lowlinks[component] = min(lowlinks[component], indices[target])
        if lowlinks[component] != indices[component]:
            return
        members: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            members.append(member)
            if member == component:
                break
        strongly_connected.append(tuple(sorted(members)))

    for component in sorted(components):
        if component not in indices:
            visit(component)
    strongly_connected.sort()
    scc_by_component = {
        component: scc_index
        for scc_index, members in enumerate(strongly_connected)
        for component in members
    }
    scc_rank = {
        scc_index: max((component_rank.get(component, 0) for component in members), default=0)
        for scc_index, members in enumerate(strongly_connected)
    }
    scc_adjacency: dict[int, set[int]] = {index: set() for index in range(len(strongly_connected))}
    indegree = {index: 0 for index in range(len(strongly_connected))}
    for source_component, targets in adjacency.items():
        source_scc = scc_by_component[source_component]
        for target_component in targets:
            target_scc = scc_by_component[target_component]
            if source_scc == target_scc or target_scc in scc_adjacency[source_scc]:
                continue
            scc_adjacency[source_scc].add(target_scc)
            indegree[target_scc] += 1

    ready = sorted(index for index, degree in indegree.items() if degree == 0)
    while ready:
        source_scc = ready.pop(0)
        for target_scc in sorted(scc_adjacency[source_scc]):
            scc_rank[target_scc] = max(scc_rank[target_scc], min(20, scc_rank[source_scc] + 1))
            indegree[target_scc] -= 1
            if indegree[target_scc] == 0:
                ready.append(target_scc)
                ready.sort()

    return {
        node_id: int(scc_rank[scc_by_component[dsu.find(node_id)]])
        for node_id in node_ids
    }


def _resolve_node(
    raw_key: str,
    node_map: dict[str, dict[str, Any]],
    key_to_id: dict[str, str],
    *,
    tenant_id: str,
    target: bool = False,
) -> str:
    key = str(raw_key or "unknown").strip() or "unknown"
    if key in key_to_id:
        return key_to_id[key]
    # Observations commonly use a bare device id while nodes use device:<id>.
    for candidate in (f"device:{key}", f"node:{key}"):
        if candidate in node_map:
            key_to_id[key] = candidate
            return candidate
        if candidate in key_to_id:
            key_to_id[key] = key_to_id[candidate]
            return key_to_id[candidate]
    node_type = "UNKNOWN" if target else "DEVICE"
    node_id = f"unknown:{hashlib.sha256(f'{tenant_id}:{key}'.encode()).hexdigest()[:20]}" if target else key
    if node_id not in node_map:
        node_map[node_id] = normalize_node({
            "id": node_id,
            "canonical_key": key,
            "display_name": key,
            "node_type": node_type,
            "metadata": {"unresolved_identity": key},
        }, tenant_id=tenant_id)
    key_to_id[key] = node_id
    return node_id


def _site_node(site_id: str, tenant_id: str) -> dict[str, Any]:
    return normalize_node({
        "id": f"site:{site_id}",
        "canonical_key": f"site:{site_id}",
        "display_name": site_id,
        "node_type": "SITE",
        "site_id": site_id,
    }, tenant_id=tenant_id)


def build_graph(
    nodes: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]],
    *,
    tenant_id: str = "tenant-default",
) -> dict[str, Any]:
    node_map: dict[str, dict[str, Any]] = {}
    key_to_id: dict[str, str] = {}
    for raw in nodes:
        node = normalize_node(raw, tenant_id=tenant_id)
        node_map[node["id"]] = node
        for key in (node["id"], node["canonical_key"], node.get("device_id"), node.get("display_name")):
            if key:
                key_to_id[str(key)] = node["id"]
        if node.get("site_id"):
            site_id = str(node["site_id"])
            site = _site_node(site_id, tenant_id)
            node_map.setdefault(site["id"], site)
            key_to_id.setdefault(site_id, site["id"])

    grouped: dict[str, dict[str, Any]] = {}
    group_defs: dict[str, dict[str, Any]] = {}
    group_members: list[dict[str, Any]] = []

    for raw in observations:
        item = normalize_observation(dict(raw))
        source_id = _resolve_node(item["source_node"], node_map, key_to_id, tenant_id=tenant_id)
        target_id = _resolve_node(item["target_node"], node_map, key_to_id, tenant_id=tenant_id, target=True)
        if source_id == target_id:
            continue
        item["source_node_id"] = source_id
        item["target_node_id"] = target_id
        edge_key = canonical_edge_key(
            {**item, "source_node": source_id, "target_node": target_id},
            tenant_id=tenant_id,
        )
        edge = grouped.setdefault(edge_key, {
            "id": f"edge_{edge_key[:20]}",
            "tenant_id": tenant_id,
            "source_node_id": source_id,
            "target_node_id": target_id,
            "source_interface": item.get("source_interface"),
            "target_interface": item.get("target_interface"),
            "relation_type": item["relation_type"],
            "semantic_relation": item.get("semantic_relation") or "",
            "direction": item["direction"],
            "existence": "observed",
            "status": "active",
            "is_manual": int(item.get("is_manual") or 0),
            "rank_excluded": int(item["relation_type"] in _RANK_EXCLUDED_RELATIONS),
            "evidence": [],
        })
        edge["is_manual"] = max(int(edge.get("is_manual") or 0), int(item.get("is_manual") or 0))
        edge["evidence"].append(item)
        if item.get("semantic_relation"):
            edge["semantic_relation"] = item["semantic_relation"]

        group_id = item.get("group_id")
        if group_id:
            group_key = str(group_id)
            group_node_id = f"group:{group_key}"
            if group_node_id not in node_map:
                group_node = normalize_node({
                    "id": group_node_id,
                    "canonical_key": group_node_id,
                    "display_name": group_key,
                    "node_type": "GROUP",
                    "metadata": {"group_type": item.get("group_type") or "logical"},
                }, tenant_id=tenant_id)
                node_map[group_node_id] = group_node
            group_defs[group_node_id] = {
                "id": group_node_id,
                "node_id": group_node_id,
                "group_type": item.get("group_type") or "logical",
                "display_name": node_map[group_node_id]["display_name"],
                "metadata": {"source": item.get("protocol")},
            }
            for member_id, member_side in ((source_id, "source"), (target_id, "target")):
                group_members.append({
                    "group_id": group_node_id,
                    "node_id": member_id,
                    "member_role": item.get("metadata", {}).get(f"{member_side}_member_role")
                    or item.get("metadata", {}).get("member_role")
                    or "",
                    "metadata": {**(item.get("metadata") or {}), "observation_side": member_side},
                })

    edges: list[dict[str, Any]] = []
    for edge in grouped.values():
        edge["semantic_confidence"] = _confidence(edge["evidence"])
        edge["existence_confidence"] = _existence_confidence(edge["evidence"])
        edge["last_seen"] = max((str(item["observed_at"]) for item in edge["evidence"]), default=now_iso())
        edge["first_seen"] = min((str(item["observed_at"]) for item in edge["evidence"]), default=edge["last_seen"])
        edge["metadata"] = {
            "evidence_count": len(edge["evidence"]),
            "source_types": sorted({str(item.get("source_type") or "") for item in edge["evidence"]}),
            "protocols": sorted({str(item.get("protocol") or "") for item in edge["evidence"]}),
            "semantic_relation": edge.get("semantic_relation") or "",
        }
        edges.append(edge)

    # Cross-site connectivity is represented by a separate site relation.
    # The device-level physical/logical edge remains intact.
    site_edge_keys: set[str] = set()
    for edge in list(edges):
        source = node_map.get(edge["source_node_id"], {})
        target = node_map.get(edge["target_node_id"], {})
        source_site, target_site = source.get("site_id"), target.get("site_id")
        if not source_site or not target_site or str(source_site) == str(target_site):
            continue
        left, right = f"site:{source_site}", f"site:{target_site}"
        site_key = canonical_edge_key({
            "source_node": left,
            "target_node": right,
            "source_type": "site_interconnect",
            "protocol": "inter_site",
            "relation_type": "INTER_SITE",
        }, tenant_id=tenant_id)
        if site_key in site_edge_keys:
            continue
        site_edge_keys.add(site_key)
        for site_id in (str(source_site), str(target_site)):
            site = _site_node(site_id, tenant_id)
            node_map.setdefault(site["id"], site)
        edges.append({
            "id": f"edge_{site_key[:20]}",
            "tenant_id": tenant_id,
            "source_node_id": left,
            "target_node_id": right,
            "source_interface": None,
            "target_interface": None,
            "relation_type": "INTER_SITE",
            "semantic_relation": "INTER_SITE",
            "direction": "undirected",
            "existence": "observed",
            "existence_confidence": edge.get("existence_confidence", 0),
            "semantic_confidence": edge.get("semantic_confidence", 0),
            "status": "active",
            "is_manual": 0,
            "rank_excluded": 1,
            "metadata": {"derived_from_edge": edge["id"], "source_sites": [source_site, target_site]},
            "evidence": [{
                "source_type": "site_interconnect",
                "protocol": "inter_site",
                "confidence": edge.get("existence_confidence", 0),
                "observed_at": edge.get("last_seen") or now_iso(),
                "metadata": {"derived_from_edge": edge["id"]},
            }],
            "first_seen": edge.get("first_seen"),
            "last_seen": edge.get("last_seen"),
        })

    anchors = detect_topology_anchors(list(node_map.values()), edges)
    anchor_by_id = {str(item["node_id"]): item for item in anchors}
    for node in node_map.values():
        anchor = anchor_by_id.get(str(node["id"]))
        if anchor:
            node.setdefault("metadata", {})["is_anchor"] = True
            node["metadata"]["anchor_type"] = anchor["anchor_type"]
            node["metadata"]["anchor_reasons"] = anchor["reasons"]

    ranks = calculate_dynamic_ranks(list(node_map.values()), edges)
    for node in node_map.values():
        node["rank"] = ranks.get(node["id"], 0)
    deduplicated_members: dict[tuple[str, str], dict[str, Any]] = {}
    for member in group_members:
        key = (str(member["group_id"]), str(member["node_id"]))
        existing = deduplicated_members.get(key)
        if not existing or (not existing.get("member_role") and member.get("member_role")):
            deduplicated_members[key] = member

    return {
        "nodes": list(node_map.values()),
        "edges": edges,
        "ranks": ranks,
        "groups": list(group_defs.values()),
        "group_members": list(deduplicated_members.values()),
        "anchors": anchors,
    }


def _visual_rank_map(graph: dict[str, Any]) -> dict[str, int]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ranks = {str(node["id"]): max(0, int(float(node.get("rank") or 0))) for node in nodes}
    if any(value > 0 for value in ranks.values()):
        return ranks

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        relation = str(edge.get("relation_type") or "").upper()
        if relation in {"OOB", "INTER_SITE"} or int(edge.get("rank_excluded") or 0):
            continue
        left, right = str(edge["source_node_id"]), str(edge["target_node_id"])
        if left in ranks and right in ranks:
            adjacency[left].add(right)
            adjacency[right].add(left)
    visited: set[str] = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        distances = {start: 0}
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            for neighbor in sorted(adjacency[current]):
                if neighbor in distances:
                    continue
                distances[neighbor] = min(20, distances[current] + 1)
                visited.add(neighbor)
                queue.append(neighbor)
        for node_id, distance in distances.items():
            ranks[node_id] = distance
    return ranks


def layout_graph(
    graph: dict[str, Any],
    *,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, float]]:
    """Create a stable layered layout with no role-based fixed tiers.

    Explicit relation ranks win. For an unconstrained physical component, a
    topology-derived BFS depth is used only as a visual seed; role labels are
    never inspected. A small barycentre pass makes peer/mesh crossings less
    severe while manual coordinates always win.
    """
    overrides = overrides or {}
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    visual_ranks = _visual_rank_map(graph)
    by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    node_map = {str(node["id"]): node for node in nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if str(edge.get("relation_type") or "").upper() in {"OOB", "INTER_SITE"}:
            continue
        left, right = str(edge["source_node_id"]), str(edge["target_node_id"])
        adjacency[left].add(right)
        adjacency[right].add(left)
    for node in nodes:
        by_rank[visual_ranks.get(str(node["id"]), 0)].append(node)

    # Stable order followed by two barycentre sweeps.
    for rank, layer in by_rank.items():
        layer.sort(key=lambda item: (
            str(item.get("site_id") or ""),
            str(item.get("zone") or ""),
            -len(adjacency.get(str(item["id"]), set())),
            str(item.get("display_name") or item["id"]),
        ))
    for _ in range(2):
        for rank in sorted(by_rank):
            if rank == min(by_rank):
                continue
            previous = {str(node["id"]): index for index, node in enumerate(by_rank[rank - 1])}
            by_rank[rank].sort(key=lambda node: (
                sum(previous.get(neighbor, 0) for neighbor in adjacency.get(str(node["id"]), set()))
                / max(1, len([neighbor for neighbor in adjacency.get(str(node["id"]), set()) if neighbor in previous])),
                str(node.get("display_name") or node["id"]),
            ))

    layout: dict[str, dict[str, float]] = {}
    site_lanes = {site: index for index, site in enumerate(sorted({
        str(node.get("site_id") or "") for node in nodes if node.get("site_id")
    }))}
    for rank in sorted(by_rank):
        for row, node in enumerate(by_rank[rank]):
            node_id = str(node["id"])
            override = overrides.get(node_id) or node.get("layout_override") or {}
            try:
                x, y = float(override["x"]), float(override["y"])
                if math.isfinite(x) and math.isfinite(y):
                    layout[node_id] = {"x": x, "y": y, "manual": 1.0}
                    continue
            except (KeyError, TypeError, ValueError):
                pass
            site_lane = site_lanes.get(str(node.get("site_id") or ""), 0)
            zone = str(node.get("zone") or "").lower()
            zone_offset = 700 if zone in {"oob", "out_of_band", "management"} else 0
            node_offset = 100 if str(node.get("node_type") or "") in {"SITE", "GROUP"} else 0
            layout[node_id] = {
                "x": float(rank * 280 + site_lane * 1100 + zone_offset + node_offset),
                "y": float(row * 120),
                "manual": 0.0,
            }

    # Ring groups are semantic objects, so render their members as a stable
    # circle instead of letting the generic layered seed flatten the loop.
    group_members_by_id: dict[str, set[str]] = defaultdict(set)
    for member in graph.get("group_members") or []:
        group_members_by_id[str(member.get("group_id") or "")].add(str(member.get("node_id") or ""))
    for group in sorted(graph.get("groups") or [], key=lambda item: str(item.get("id") or "")):
        if str(group.get("group_type") or "").upper() != "RING":
            continue
        group_id = str(group.get("id") or "")
        members = sorted(
            (member_id for member_id in group_members_by_id.get(group_id, set()) if member_id in layout),
            key=lambda member_id: (
                str(node_map.get(member_id, {}).get("display_name") or member_id),
                member_id,
            ),
        )
        if len(members) < 3:
            continue
        center_x = sum(layout[member_id]["x"] for member_id in members) / len(members)
        center_y = sum(layout[member_id]["y"] for member_id in members) / len(members)
        radius = min(320.0, max(150.0, len(members) * 42.0))
        for member_index, member_id in enumerate(members):
            if layout[member_id].get("manual"):
                continue
            angle = -math.pi / 2 + 2 * math.pi * member_index / len(members)
            layout[member_id] = {
                "x": center_x + math.cos(angle) * radius,
                "y": center_y + math.sin(angle) * radius,
                "manual": 0.0,
            }
        if group_id in layout and not layout[group_id].get("manual"):
            layout[group_id] = {"x": center_x, "y": center_y, "manual": 0.0}
    return layout


def apply_relation_override(edge: dict[str, Any], *, relation_type: str, actor: str) -> dict[str, Any]:
    relation = str(relation_type or "").strip().upper()
    relation = {"L3": "L3_NEIGHBOR", "L2": "L2_NEIGHBOR"}.get(relation, relation)
    if relation not in RELATION_TYPES:
        raise ValueError("unsupported topology relation type")
    before = dict(edge)
    edge["relation_type"] = relation
    edge["semantic_relation"] = edge.get("semantic_relation") or relation
    edge["is_manual"] = 1
    edge["manual_confirmed"] = 1
    edge["rank_excluded"] = int(relation in _RANK_EXCLUDED_RELATIONS)
    edge["metadata"] = {
        **dict(edge.get("metadata") or {}),
        "relation_override_by": actor,
        "relation_override_at": now_iso(),
    }
    edge["before_override"] = before
    return edge


def apply_layout_override(layout: dict[str, Any], *, x: float, y: float) -> dict[str, float]:
    if not math.isfinite(float(x)) or not math.isfinite(float(y)):
        raise ValueError("layout coordinates must be finite")
    return {"x": float(x), "y": float(y), "manual": 1.0}


def mark_stale_edges(edges: list[dict[str, Any]], *, active_edge_keys: set[str]) -> list[dict[str, Any]]:
    for edge in edges:
        if str(edge.get("id", "")).removeprefix("edge_") not in active_edge_keys and not edge.get("is_manual"):
            edge["status"] = "stale"
            edge["existence"] = "historical"
            edge["stale_at"] = now_iso()
    return edges


def _history_id(entity_type: str, entity_id: str, event_type: str, before: Any, after: Any) -> str:
    raw = json.dumps([entity_type, entity_id, event_type, before, after], ensure_ascii=False, sort_keys=True, default=str)
    return "topology_history_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _record_history(
    conn: Any,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    before: Any,
    after: Any,
    source: str = "system",
    actor: str = "system",
    edge_id: str | None = None,
) -> None:
    history_id = _history_id(entity_type, entity_id, event_type, before, after)
    before_json = json.dumps(before, ensure_ascii=False, sort_keys=True, default=str) if before is not None else None
    after_json = json.dumps(after, ensure_ascii=False, sort_keys=True, default=str) if after is not None else None
    created_at = now_iso()
    conn.execute(
        """
        INSERT INTO topology_history
            (id, tenant_id, entity_type, entity_id, event_type, before_json, after_json, source, actor, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (history_id, tenant_id, entity_type, entity_id, event_type, before_json, after_json, source, actor, created_at),
    )
    if edge_id:
        conn.execute(
            """
            INSERT INTO topology_edge_history
                (id, tenant_id, edge_id, event_type, before_json, after_json, source, actor, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (history_id + "_edge", tenant_id, edge_id, event_type, before_json, after_json, source, actor, created_at),
        )
    try:
        conn.execute(
            """
            INSERT INTO topology_change_events
                (id, tenant_id, entity_type, entity_id, event_type, before_json, after_json, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (history_id + "_change", tenant_id, entity_type, entity_id, event_type, before_json, after_json, source, created_at),
        )
    except Exception:
        # Compatibility with an installation where m0105 is still rolling out.
        pass


def _safe_edge_snapshot(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "relation_type": edge.get("relation_type"),
        "semantic_relation": edge.get("semantic_relation"),
        "direction": edge.get("direction"),
        "status": edge.get("status"),
        "is_manual": int(edge.get("is_manual") or 0),
        "existence_confidence": edge.get("existence_confidence"),
        "semantic_confidence": edge.get("semantic_confidence"),
    }


def persist_graph(graph: dict[str, Any]) -> dict[str, int]:
    """Upsert the graph while retaining stale facts and change history."""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    tenant_id = str((nodes[0].get("tenant_id") if nodes else graph.get("tenant_id")) or "tenant-default")
    with get_db_connection() as conn:
        for node in nodes:
            existing = conn.execute(
                "SELECT id, rank, layout_override_json, role_identity, function, zone, status FROM topology_nodes WHERE tenant_id = ? AND canonical_key = ?",
                (tenant_id, node["canonical_key"]),
            ).fetchone()
            created_at = now_iso()
            conn.execute(
                """
                INSERT INTO topology_nodes
                    (id, tenant_id, node_type, canonical_key, display_name, device_id,
                     site_id, role_identity, function, zone, status, metadata_json,
                     rank, first_seen, last_seen, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, canonical_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    device_id = excluded.device_id,
                    site_id = excluded.site_id,
                    role_identity = excluded.role_identity,
                    function = excluded.function,
                    zone = excluded.zone,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    rank = excluded.rank,
                    last_seen = excluded.last_seen,
                    updated_at = excluded.updated_at
                """,
                (
                    node["id"], tenant_id, node["node_type"], node["canonical_key"],
                    node["display_name"], node.get("device_id"), node.get("site_id"),
                    node.get("role_identity"), node.get("function"), node.get("zone"),
                    node.get("status", "active"), json.dumps(node.get("metadata") or {}, ensure_ascii=False),
                    node.get("rank", 0), node.get("first_seen") or created_at,
                    node.get("last_seen") or created_at, created_at, created_at,
                ),
            )
            if existing is None:
                _record_history(
                    conn, tenant_id=tenant_id, entity_type="node", entity_id=str(node["id"]),
                    event_type="node_created", before=None, after={
                        "node_type": node.get("node_type"), "canonical_key": node.get("canonical_key"),
                    },
                )

        existing_rows = conn.execute(
            "SELECT * FROM topology_edges WHERE tenant_id = ? AND status = 'active' AND is_manual = 0",
            (tenant_id,),
        ).fetchall()
        active_ids = {str(edge["id"]) for edge in edges}
        for row in existing_rows:
            if str(row["id"]) not in active_ids:
                before = _safe_edge_snapshot(dict(row))
                conn.execute(
                    "UPDATE topology_edges SET status = 'stale', existence = 'historical', stale_at = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                    (now_iso(), now_iso(), row["id"], tenant_id),
                )
                _record_history(
                    conn, tenant_id=tenant_id, entity_type="edge", entity_id=str(row["id"]),
                    event_type="edge_stale", before=before,
                    after={**before, "status": "stale"}, edge_id=str(row["id"]),
                )

        stored_edges: list[dict[str, Any]] = []
        for raw_edge in edges:
            edge = dict(raw_edge)
            # A manually confirmed relation survives a later discovery pass
            # even when discovery classifies the same endpoints differently.
            existing = conn.execute(
                """
                SELECT * FROM topology_edges
                WHERE tenant_id = ? AND source_node_id = ? AND target_node_id = ?
                  AND COALESCE(source_interface, '') = COALESCE(?, '')
                  AND COALESCE(target_interface, '') = COALESCE(?, '')
                ORDER BY is_manual DESC, updated_at DESC LIMIT 1
                """,
                (
                    tenant_id, edge["source_node_id"], edge["target_node_id"],
                    edge.get("source_interface"), edge.get("target_interface"),
                ),
            ).fetchone()
            if existing is None and edge.get("direction") == "undirected":
                # A manual relation may have been saved from the opposite
                # observation direction. Treat its endpoint pair and ports as
                # the same fact so the next discovery pass cannot duplicate
                # or override the confirmed relation.
                existing = conn.execute(
                    """
                    SELECT * FROM topology_edges
                    WHERE tenant_id = ? AND source_node_id = ? AND target_node_id = ?
                      AND COALESCE(source_interface, '') = COALESCE(?, '')
                      AND COALESCE(target_interface, '') = COALESCE(?, '')
                    ORDER BY is_manual DESC, updated_at DESC LIMIT 1
                    """,
                    (
                        tenant_id, edge["target_node_id"], edge["source_node_id"],
                        edge.get("target_interface"), edge.get("source_interface"),
                    ),
                ).fetchone()
            if existing is not None and int(existing["is_manual"] or 0):
                old = dict(existing)
                edge["id"] = old["id"]
                edge["relation_type"] = old["relation_type"]
                edge["semantic_relation"] = old.get("semantic_relation") or edge.get("semantic_relation") or ""
                edge["is_manual"] = 1
                edge["rank_excluded"] = int(old.get("rank_excluded") or 0)
                edge["metadata"] = {
                    **dict(edge.get("metadata") or {}),
                    **(_json_load(old.get("metadata_json"), {}) or {}),
                }
            before = _safe_edge_snapshot(dict(existing)) if existing is not None else None
            created_at = now_iso()
            conn.execute(
                """
                INSERT INTO topology_edges
                    (id, tenant_id, source_node_id, target_node_id, source_interface,
                     target_interface, relation_type, direction, existence,
                     existence_confidence, semantic_confidence, status, is_manual,
                     manual_confirmed, semantic_relation, rank_excluded, metadata_json,
                     first_seen, last_seen, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, source_node_id, target_node_id, source_interface, target_interface, relation_type)
                DO UPDATE SET
                    existence = excluded.existence,
                    existence_confidence = excluded.existence_confidence,
                    semantic_confidence = excluded.semantic_confidence,
                    status = excluded.status,
                    is_manual = CASE
                        WHEN topology_edges.is_manual > excluded.is_manual
                        THEN topology_edges.is_manual ELSE excluded.is_manual END,
                    manual_confirmed = CASE
                        WHEN topology_edges.manual_confirmed > excluded.manual_confirmed
                        THEN topology_edges.manual_confirmed ELSE excluded.manual_confirmed END,
                    semantic_relation = excluded.semantic_relation,
                    rank_excluded = excluded.rank_excluded,
                    metadata_json = excluded.metadata_json,
                    last_seen = excluded.last_seen,
                    stale_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    edge["id"], tenant_id, edge["source_node_id"], edge["target_node_id"],
                    edge.get("source_interface"), edge.get("target_interface"),
                    edge["relation_type"], edge.get("direction") or "undirected",
                    edge.get("existence", "observed"), edge.get("existence_confidence", 0),
                    edge.get("semantic_confidence", 0), edge.get("status", "active"),
                    int(edge.get("is_manual") or 0), int(edge.get("manual_confirmed") or edge.get("is_manual") or 0),
                    edge.get("semantic_relation") or "", int(edge.get("rank_excluded") or 0),
                    json.dumps(edge.get("metadata") or {}, ensure_ascii=False),
                    edge.get("first_seen") or created_at, edge.get("last_seen") or created_at,
                    created_at, created_at,
                ),
            )
            after = _safe_edge_snapshot(edge)
            if existing is None:
                _record_history(
                    conn, tenant_id=tenant_id, entity_type="edge", entity_id=str(edge["id"]),
                    event_type="edge_created", before=None, after=after, edge_id=str(edge["id"]),
                )
            elif before != after:
                _record_history(
                    conn, tenant_id=tenant_id, entity_type="edge", entity_id=str(edge["id"]),
                    event_type="edge_updated", before=before, after=after, edge_id=str(edge["id"]),
                )

            try:
                edge_id = str(edge["id"])
                relation_id = f"relation_{hashlib.sha256(f'{tenant_id}:{edge_id}'.encode()).hexdigest()[:24]}"
                conn.execute(
                    """
                    INSERT INTO topology_relations
                        (id, tenant_id, edge_id, relation_type, semantic_relation, direction,
                         existence_confidence, semantic_confidence, rank_excluded, is_manual,
                         status, metadata_json, first_seen, last_seen, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, edge_id) DO UPDATE SET
                        relation_type = excluded.relation_type,
                        semantic_relation = excluded.semantic_relation,
                        direction = excluded.direction,
                        existence_confidence = excluded.existence_confidence,
                        semantic_confidence = excluded.semantic_confidence,
                        rank_excluded = excluded.rank_excluded,
                        is_manual = CASE
                            WHEN topology_relations.is_manual > excluded.is_manual
                            THEN topology_relations.is_manual ELSE excluded.is_manual END,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        last_seen = excluded.last_seen,
                        updated_at = excluded.updated_at
                    """,
                    (
                        relation_id, tenant_id, edge["id"], edge["relation_type"],
                        edge.get("semantic_relation") or "", edge.get("direction") or "undirected",
                        edge.get("existence_confidence", 0), edge.get("semantic_confidence", 0),
                        int(edge.get("rank_excluded") or 0), int(edge.get("is_manual") or 0),
                        edge.get("status", "active"), json.dumps(edge.get("metadata") or {}, ensure_ascii=False),
                        edge.get("first_seen"), edge.get("last_seen"), created_at, created_at,
                    ),
                )
            except Exception:
                pass

            for evidence in edge.get("evidence") or []:
                evidence_payload = {
                    "source_interface": evidence.get("source_interface"),
                    "target_interface": evidence.get("target_interface"),
                    "protocol": evidence.get("protocol"),
                    "relation_type": evidence.get("relation_type"),
                    "semantic_relation": evidence.get("semantic_relation"),
                    "direction": evidence.get("direction"),
                    "metadata": evidence.get("metadata") or {},
                }
                evidence_id = "evidence_" + hashlib.sha256(
                    json.dumps({"edge": edge["id"], "evidence": evidence_payload}, sort_keys=True, default=str).encode()
                ).hexdigest()[:24]
                conn.execute(
                    """
                    INSERT INTO topology_edge_evidence
                        (id, edge_id, source_type, source_id, protocol, observation_json,
                         priority, confidence, observed_at, evidence_type, source_device_id,
                         source_interface, first_seen, last_seen, collector)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        observation_json = excluded.observation_json,
                        priority = excluded.priority,
                        confidence = excluded.confidence,
                        observed_at = excluded.observed_at,
                        evidence_type = excluded.evidence_type,
                        source_device_id = excluded.source_device_id,
                        source_interface = excluded.source_interface,
                        last_seen = excluded.last_seen,
                        collector = excluded.collector
                    """,
                    (
                        evidence_id, edge["id"], evidence.get("source_type") or "",
                        evidence.get("source_id") or evidence.get("source_node_id"),
                        evidence.get("protocol") or "", json.dumps(evidence_payload, ensure_ascii=False),
                        SOURCE_PRIORITY.get(str(evidence.get("source_type") or "").lower(), 10),
                        evidence.get("confidence", 0), evidence.get("observed_at") or created_at,
                        evidence.get("evidence_type") or evidence.get("source_type") or "",
                        evidence.get("source_device_id") or evidence.get("source_node_id") or "",
                        evidence.get("source_interface") or "", evidence.get("observed_at") or created_at,
                        evidence.get("observed_at") or created_at, evidence.get("collector") or "",
                    ),
                )
            stored_edges.append(edge)

        for group in graph.get("groups") or []:
            group_id = str(group.get("id") or group.get("node_id"))
            try:
                conn.execute(
                    """
                    INSERT INTO topology_groups
                        (id, tenant_id, node_id, group_type, display_name, status, metadata_json, first_seen, last_seen, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, node_id) DO UPDATE SET
                        group_type = excluded.group_type,
                        display_name = excluded.display_name,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        last_seen = excluded.last_seen,
                        updated_at = excluded.updated_at
                    """,
                    (
                        group_id, tenant_id, group.get("node_id") or group_id,
                        group.get("group_type") or "logical", group.get("display_name") or group_id,
                        group.get("status") or "active", json.dumps(group.get("metadata") or {}, ensure_ascii=False),
                        group.get("first_seen") or now_iso(), group.get("last_seen") or now_iso(),
                        now_iso(), now_iso(),
                    ),
                )
            except Exception:
                pass
        for member in graph.get("group_members") or []:
            try:
                member_id = "group_member_" + hashlib.sha256(
                    f'{tenant_id}:{member.get("group_id")}:{member.get("node_id")}'.encode()
                ).hexdigest()[:24]
                group_row = conn.execute(
                    "SELECT id FROM topology_groups WHERE tenant_id = ? AND node_id = ?",
                    (tenant_id, member.get("group_id")),
                ).fetchone()
                if group_row:
                    conn.execute(
                        """
                        INSERT INTO topology_group_members
                            (id, tenant_id, group_id, node_id, member_role, status, metadata_json, first_seen, last_seen, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                        ON CONFLICT(tenant_id, group_id, node_id) DO UPDATE SET
                            member_role = excluded.member_role,
                            status = excluded.status,
                            metadata_json = excluded.metadata_json,
                            last_seen = excluded.last_seen,
                            updated_at = excluded.updated_at
                        """,
                        (
                            member_id, tenant_id, group_row["id"], member.get("node_id"),
                            member.get("member_role") or "", json.dumps(member.get("metadata") or {}, ensure_ascii=False),
                            now_iso(), now_iso(), now_iso(), now_iso(),
                        ),
                    )
            except Exception:
                pass
        conn.commit()
    return {"nodes": len(nodes), "edges": len(stored_edges) if "stored_edges" in locals() else len(edges)}


def _graph_rows(
    conn: Any,
    tenant_id: str,
    view: str,
    site_id: str | None,
    limit: int,
    include_stale: bool,
    device_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    view_relation_types = {
        "physical": {"PHYSICAL", "STACK", "IRF", "CSS", "VC"},
        "l2": {"PHYSICAL", "L2_NEIGHBOR", "ENDPOINT", "RING", "STACK", "IRF", "CSS", "VC", "MLAG_PEER", "VPC_PEER"},
        "l3": {"L3_NEIGHBOR", "WAN", "LOGICAL", "TUNNEL", "HIERARCHICAL", "BRANCH", "PEER"},
        "logical": {
            "LOGICAL", "PEER", "L3_NEIGHBOR", "L2_NEIGHBOR", "WAN", "TUNNEL",
            "HIERARCHICAL", "BRANCH", "HA", "HA_PEER", "VRRP_HSRP", "STACK",
            "IRF", "CSS", "VC", "MLAG_PEER", "VPC_PEER", "CONTROL", "RING",
        },
        "site": {"HIERARCHICAL", "INTER_SITE"},
        "external": {"ENDPOINT", "WAN", "TUNNEL", "UNKNOWN"},
        "oob": {"OOB"},
    }
    node_where = ["tenant_id = ?", "status = 'active'"]
    node_params: list[Any] = [tenant_id]
    if site_id:
        node_where.append("(site_id = ? OR id = ? OR node_type = 'SITE')")
        node_params.extend([site_id, f"site:{site_id}"])
    if device_ids is not None:
        normalized_device_ids = _normalize_device_ids(device_ids) or []
        if not normalized_device_ids:
            return [], []
        device_placeholders = ",".join("?" for _ in normalized_device_ids)
        node_where.append(f"device_id IN ({device_placeholders})")
        node_params.extend(normalized_device_ids)
    rows = conn.execute(
        "SELECT id, tenant_id, node_type, canonical_key, display_name, device_id, site_id, role_identity, function, zone, status, metadata_json, layout_override_json, rank, first_seen, last_seen FROM topology_nodes WHERE "
        + " AND ".join(node_where) + " ORDER BY display_name LIMIT ?",
        (*node_params, limit),
    ).fetchall()
    nodes = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _json_load(item.pop("metadata_json", None), {}) or {}
        item["layout_override"] = _json_load(item.pop("layout_override_json", None), {}) or {}
        nodes.append(item)
    # A re-import can recreate a managed device with a new primary key while
    # historical discovery evidence still references the old key.  Never
    # expose those orphaned DEVICE nodes as part of the active read model.
    # During a rolling upgrade the inventory table may not exist yet. Probe
    # PostgreSQL metadata first so absence does not abort the read transaction.
    if _table_exists(conn, "devices"):
        current_device_ids = {
            str(row["id"])
            for row in conn.execute("SELECT id FROM devices").fetchall()
        }
        nodes = [
            item for item in nodes
            if str(item.get("node_type") or "").upper() != "DEVICE"
            or str(item.get("device_id") or "") in current_device_ids
        ]
    node_ids = {str(item["id"]) for item in nodes}
    if not node_ids:
        return nodes, []
    placeholders = ",".join("?" for _ in node_ids)
    edge_where = [
        "tenant_id = ?",
        ("status IN ('active', 'stale')" if include_stale else "status = 'active'"),
        f"source_node_id IN ({placeholders})",
        f"target_node_id IN ({placeholders})",
    ]
    edge_params: list[Any] = [tenant_id, *node_ids, *node_ids]
    relation_types = view_relation_types.get(view)
    if relation_types:
        relation_placeholders = ",".join("?" for _ in relation_types)
        edge_where.append(f"relation_type IN ({relation_placeholders})")
        edge_params.extend(sorted(relation_types))
    edge_rows = conn.execute(
        "SELECT topology_edges.id, source_node_id, target_node_id, source_interface, target_interface, relation_type, direction, existence, existence_confidence, semantic_confidence, status, is_manual, manual_confirmed, semantic_relation, rank_excluded, metadata_json, first_seen, last_seen, stale_at, COALESCE(evidence_counts.evidence_count, 0) AS evidence_count FROM topology_edges LEFT JOIN (SELECT edge_id, COUNT(*) AS evidence_count FROM topology_edge_evidence GROUP BY edge_id) AS evidence_counts ON evidence_counts.edge_id = topology_edges.id WHERE "
        + " AND ".join(edge_where) + " ORDER BY last_seen DESC LIMIT ?",
        (*edge_params, limit),
    ).fetchall()
    edges = []
    for row in edge_rows:
        item = dict(row)
        item["metadata"] = _json_load(item.pop("metadata_json", None), {}) or {}
        item["evidence_count"] = int(item.get("evidence_count") or 0)
        edges.append(item)
    return nodes, edges


def get_graph(
    *,
    tenant_id: str = "tenant-default",
    view: str = "all",
    site_id: str | None = None,
    limit: int = 5000,
    include_stale: bool = False,
    device_ids: list[str] | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 20_000))
    with get_db_connection() as conn:
        nodes, edges = _graph_rows(conn, tenant_id, view, site_id, safe_limit, include_stale, device_ids)
        graph = {"nodes": nodes, "edges": edges}
        groups: list[dict[str, Any]] = []
        group_members: list[dict[str, Any]] = []
        try:
            normalized_device_ids = _normalize_device_ids(device_ids)
            group_where = "tenant_id = ? AND status = 'active'"
            group_params: list[Any] = [tenant_id]
            member_scope_sql = ""
            member_scope_params: list[Any] = []
            if normalized_device_ids is not None:
                if not normalized_device_ids:
                    normalized_device_ids = []
                    group_where = "1 = 0"
                else:
                    device_placeholders = ",".join("?" for _ in normalized_device_ids)
                    group_where += (
                        " AND EXISTS ("
                        "SELECT 1 FROM topology_group_members gm_scope "
                        "JOIN topology_nodes gn_scope "
                        "ON gn_scope.id = gm_scope.node_id "
                        "AND gn_scope.tenant_id = gm_scope.tenant_id "
                        "WHERE gm_scope.group_id = topology_groups.id "
                        "AND gm_scope.tenant_id = topology_groups.tenant_id "
                        f"AND gn_scope.device_id IN ({device_placeholders})"
                        ")"
                    )
                    group_params.extend(normalized_device_ids)
                    member_scope_sql = f" AND n_scope.device_id IN ({device_placeholders})"
                    member_scope_params.extend(normalized_device_ids)
            group_rows = conn.execute(
                "SELECT id, node_id, group_type, display_name, status, metadata_json "
                f"FROM topology_groups WHERE {group_where} LIMIT ?",
                (*group_params, safe_limit),
            ).fetchall()
            for row in group_rows:
                item = dict(row)
                item["metadata"] = _json_load(item.pop("metadata_json", None), {}) or {}
                groups.append(item)
            member_rows = conn.execute(
                f"""
                SELECT m.group_id, m.node_id, m.member_role, m.status, m.metadata_json
                FROM topology_group_members m
                JOIN topology_groups g ON g.id = m.group_id AND g.tenant_id = m.tenant_id
                LEFT JOIN topology_nodes n_scope
                  ON n_scope.id = m.node_id AND n_scope.tenant_id = m.tenant_id
                WHERE m.tenant_id = ? AND m.status = 'active' AND g.status = 'active'
                {member_scope_sql}
                LIMIT ?
                """,
                (tenant_id, *member_scope_params, safe_limit),
            ).fetchall()
            for row in member_rows:
                item = dict(row)
                item["metadata"] = _json_load(item.pop("metadata_json", None), {}) or {}
                group_members.append(item)
        except Exception:
            pass
        graph["groups"] = groups
        graph["group_members"] = group_members
        return {
            **graph,
            "anchors": detect_topology_anchors(nodes, edges),
            "layout": layout_graph(graph),
            "view": view,
            "include_stale": include_stale,
            "truncated": len(nodes) >= safe_limit or len(edges) >= safe_limit,
        }


def get_edge_evidence(
    edge_id: str,
    *,
    tenant_id: str = "tenant-default",
    limit: int = 200,
    device_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_device_ids = _normalize_device_ids(device_ids)
    if normalized_device_ids is not None and not normalized_device_ids:
        return []
    with get_db_connection() as conn:
        scope_sql = ""
        scope_params: list[Any] = []
        if normalized_device_ids is not None:
            placeholders = ",".join("?" for _ in normalized_device_ids)
            scope_sql = f"""
              AND EXISTS (
                    SELECT 1 FROM topology_nodes source_node
                     WHERE source_node.id = g.source_node_id
                       AND source_node.tenant_id = g.tenant_id
                       AND source_node.device_id IN ({placeholders})
              )
              AND EXISTS (
                    SELECT 1 FROM topology_nodes target_node
                     WHERE target_node.id = g.target_node_id
                       AND target_node.tenant_id = g.tenant_id
                       AND target_node.device_id IN ({placeholders})
              )
            """
            scope_params.extend(normalized_device_ids)
            scope_params.extend(normalized_device_ids)
        rows = conn.execute(
            f"""
            SELECT e.id, e.edge_id, e.source_type, e.source_id, e.protocol,
                   e.observation_json, e.priority, e.confidence, e.observed_at,
                   e.evidence_type, e.source_device_id, e.source_interface,
                   e.first_seen, e.last_seen, e.collector
            FROM topology_edge_evidence e
            JOIN topology_edges g ON g.id = e.edge_id AND g.tenant_id = ?
            WHERE e.edge_id = ?
            {scope_sql}
            ORDER BY e.priority DESC, e.observed_at DESC LIMIT ?
            """,
            (tenant_id, edge_id, *scope_params, max(1, min(int(limit), 1000))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["observation"] = _json_load(item.pop("observation_json", None), {}) or {}
            result.append(item)
        return result


def get_topology_history(
    *,
    tenant_id: str = "tenant-default",
    edge_id: str | None = None,
    node_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    device_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized_device_ids = _normalize_device_ids(device_ids)
    if normalized_device_ids is not None and not normalized_device_ids:
        safe_limit = max(1, min(int(limit), 1000))
        return {"items": [], "limit": safe_limit, "offset": max(0, int(offset))}
    clauses = ["h.tenant_id = ?"]
    params: list[Any] = [tenant_id]
    if edge_id:
        clauses.append("(h.entity_id = ? OR h.entity_type = 'edge' AND h.entity_id = ?)")
        params.extend([edge_id, edge_id])
    if node_id:
        clauses.append("h.entity_id = ?")
        params.append(node_id)
    if event_type:
        clauses.append("h.event_type = ?")
        params.append(event_type)
    if normalized_device_ids is not None:
        placeholders = ",".join("?" for _ in normalized_device_ids)
        clauses.append(
            "("
            "(h.entity_type = 'edge' AND EXISTS ("
            "SELECT 1 FROM topology_edges history_edge "
            "JOIN topology_nodes history_source "
            "ON history_source.id = history_edge.source_node_id "
            "AND history_source.tenant_id = history_edge.tenant_id "
            "JOIN topology_nodes history_target "
            "ON history_target.id = history_edge.target_node_id "
            "AND history_target.tenant_id = history_edge.tenant_id "
            "WHERE history_edge.id = h.entity_id "
            "AND history_edge.tenant_id = h.tenant_id "
            f"AND history_source.device_id IN ({placeholders}) "
            f"AND history_target.device_id IN ({placeholders})"
            ")) OR (h.entity_type = 'node' AND EXISTS ("
            "SELECT 1 FROM topology_nodes history_node "
            "WHERE history_node.id = h.entity_id "
            "AND history_node.tenant_id = h.tenant_id "
            f"AND history_node.device_id IN ({placeholders})"
            ")))"
        )
        params.extend(normalized_device_ids)
        params.extend(normalized_device_ids)
        params.extend(normalized_device_ids)
    safe_limit = max(1, min(int(limit), 1000))
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT h.id, h.tenant_id, h.entity_type, h.entity_id, h.event_type, h.before_json, h.after_json, h.source, h.actor, h.created_at FROM topology_history h WHERE "
            + " AND ".join(clauses) + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, safe_limit, max(0, int(offset))),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["before"] = _json_load(item.pop("before_json", None), None)
            item["after"] = _json_load(item.pop("after_json", None), None)
            items.append(item)
        return {"items": items, "limit": safe_limit, "offset": max(0, int(offset))}


def record_manual_relation_override(
    edge_id: str,
    *,
    tenant_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    actor: str,
) -> None:
    with get_db_connection() as conn:
        _record_history(
            conn, tenant_id=tenant_id, entity_type="edge", entity_id=edge_id,
            event_type="relation_manual_confirmed", before=before, after=after,
            source="manual", actor=actor, edge_id=edge_id,
        )
        conn.commit()


def record_manual_layout_override(
    node_id: str,
    *,
    tenant_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    actor: str,
) -> None:
    with get_db_connection() as conn:
        _record_history(
            conn, tenant_id=tenant_id, entity_type="node", entity_id=node_id,
            event_type="layout_manual_override", before=before, after=after,
            source="manual", actor=actor,
        )
        conn.commit()


def get_physical_links(
    *,
    tenant_id: str = "tenant-default",
    site_id: str | None = None,
    limit: int = 5000,
    include_stale: bool = False,
    device_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    graph = get_graph(
        tenant_id=tenant_id, view="physical", site_id=site_id,
        limit=limit, include_stale=include_stale, device_ids=device_ids,
    )
    node_map = {str(node["id"]): node for node in graph.get("nodes") or []}
    links = []
    for edge in graph.get("edges") or []:
        source = node_map.get(str(edge["source_node_id"]), {})
        target = node_map.get(str(edge["target_node_id"]), {})
        source_id = str(source.get("device_id") or "").strip()
        target_id = str(target.get("device_id") or "").strip()
        # Unmanaged/unknown neighbors are returned by the dedicated unmanaged
        # read model.  Keeping them here would make this managed-link response
        # non-empty and prevent the API from falling back to topology_links.
        if not source_id or not target_id:
            continue
        source_types = (edge.get("metadata") or {}).get("source_types") or []
        links.append({
            "id": edge["id"],
            "link_key": edge["id"],
            "source_device_id": source_id,
            "target_device_id": target_id,
            "source_hostname": source.get("display_name") or source.get("canonical_key") or source["id"],
            "target_hostname": target.get("display_name") or target.get("canonical_key") or target["id"],
            "source_port": edge.get("source_interface") or "",
            "target_port": edge.get("target_interface") or "",
            "source_port_normalized": edge.get("source_interface") or "",
            "target_port_normalized": edge.get("target_interface") or "",
            "source_site_id": source.get("site_id") or "",
            "target_site_id": target.get("site_id") or "",
            "discovery_source": source_types[0] if source_types else "lldp",
            "discovery_sources": source_types,
            "confidence": edge.get("existence_confidence", 0),
            "semantic_confidence": edge.get("semantic_confidence", 0),
            "evidence_count": edge.get("evidence_count", 0),
            "relation_type": edge.get("relation_type"),
            "semantic_relation": edge.get("semantic_relation") or (edge.get("metadata") or {}).get("semantic_relation", ""),
            "existence": edge.get("existence", "observed"),
            "status": edge.get("status", "active"),
            "is_manual": edge.get("is_manual", 0),
            "manual_confirmed": edge.get("manual_confirmed", 0),
            "operational_state": "stale" if edge.get("status") == "stale" else "up",
            "topology_rank": source.get("rank", 0),
            "source_topology_rank": source.get("rank", 0),
            "target_topology_rank": target.get("rank", 0),
            "topology_node_type": source.get("node_type", "DEVICE"),
        })
    return links
