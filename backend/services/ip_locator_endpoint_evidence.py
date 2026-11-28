"""Read-only lookup for current, authorized SNMP endpoint location evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from database import get_db_connection
from services import ipam_discovery_service as discovery


_LOCATION_BASES = {"same_device_vlan_mac_access", "scoped_vlan_mac_access"}


def _id(value: Any) -> str:
    return str(value or "").strip()


def _authorized_ids(values: set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    if values is None:
        return set()
    return {_id(value) for value in values if _id(value)}


def _scope_matches(
    row: dict[str, Any], *, tenant_id: str, site_id: str,
    authorized_device_ids: set[str], start_device_id: str,
) -> bool:
    source_device_id = _id(row.get("source_device_id"))
    if (
        _id(row.get("tenant_id")) != tenant_id
        or (site_id and _id(row.get("site_id")) != site_id)
        or not source_device_id
        or source_device_id not in authorized_device_ids
        or (start_device_id and source_device_id != start_device_id)
    ):
        return False
    return True


def _load_statuses(conn, collector: str, device_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not device_ids:
        return {}
    placeholders = ", ".join("?" for _ in device_ids)
    rows = conn.execute(
        f"""SELECT device_id, status, transport, source, last_success_at,
                   coverage_total, coverage_supported, metadata_json
              FROM device_collection_status
             WHERE collector = ? AND device_id IN ({placeholders})""",
        (collector, *sorted(device_ids)),
    ).fetchall()
    return {_id(row["device_id"]): dict(row) for row in rows}


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _arp_transport_is_proven(row: dict[str, Any], status: dict[str, Any]) -> bool:
    source_run_id = _id(row.get("source_run_id"))
    return bool(
        _id(status.get("status")).lower() == "success"
        and _id(status.get("transport")).lower() == "snmp"
        and _id(status.get("source")) == "arp_sweep"
        and _id(row.get("source_status")).lower() == "success"
        and _id(row.get("coverage_status")).lower() == "complete"
        and row.get("coverage_complete") in (True, 1, "1", "true", "True")
        and source_run_id
        and _id(_metadata(status.get("metadata_json")).get("collection_run_id")) == source_run_id
    )


def _mac_status_is_proven(status: dict[str, Any]) -> bool:
    try:
        coverage_total = int(status.get("coverage_total") or 0)
        coverage_supported = int(status.get("coverage_supported") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        _id(status.get("status")).lower() == "success"
        and _id(status.get("transport")).lower() == "snmp"
        and _id(status.get("source")) == "endpoint_fact_sweep"
        and coverage_total > 0
        and coverage_supported > 0
    )


def _current_cross_device_fdb_path(
    conn, *, arp: dict[str, Any], first_fdb: dict[str, Any],
    allowed: set[str], tenant: str, mac: str, vlan: str,
) -> list[dict[str, Any]] | None:
    """Follow a strictly scoped, fresh, physical tagged VLAN path.

    Unknown routing contexts, aggregation, native VLAN translation, stale
    interfaces, incomplete generations and multiple links all fail closed.
    This deliberately handles only the subset for which current facts can
    establish every hop; unsupported paths continue through the CLI engine.
    """
    from core.interface_utils import normalize_interface_name
    from services.vlan_discovery_service import parse_vlan_values

    site = _id(arp.get("site_id"))
    space = _id(arp.get("address_space_id"))
    if not site or not space or arp.get("scope_status") != "resolved":
        return None
    if arp.get("source_vrf_context_status") not in {"global", "vrf"}:
        return None
    target_vlan = int(vlan)
    now = discovery._utc_now()
    max_age = timedelta(seconds=300)

    def fresh(value: Any) -> bool:
        _, stamp = _iso_utc(value)
        return stamp is not None and timedelta(0) <= now - stamp <= max_age

    def port_key(value: Any) -> str:
        return normalize_interface_name(_id(value)).strip().lower()

    def interface(device_id: str, port: str) -> dict[str, Any] | None:
        rows = [
            dict(row) for row in conn.execute(
                """SELECT id, interface_name, interface_type, switchport_mode,
                          access_vlan, native_vlan, allowed_vlans, admin_status,
                          oper_status, last_seen
                     FROM interfaces WHERE device_id = ?""", (device_id,),
            ).fetchall()
            if port_key(row.get("interface_name")) == port_key(port)
        ]
        if len(rows) != 1:
            return None
        row = rows[0]
        if (_id(row.get("interface_type")).lower() not in {"physical", "ethernet", "ethernet_port", "port", "access"}
                or _id(row.get("oper_status")).lower() != "up"
                or _id(row.get("admin_status")).lower() != "up"
                or not fresh(row.get("last_seen"))):
            return None
        return row

    def tagged(row: dict[str, Any] | None) -> bool:
        return bool(row and _id(row.get("switchport_mode")).lower() == "trunk"
                    and target_vlan in parse_vlan_values(row.get("allowed_vlans"))
                    and row.get("native_vlan") is not None
                    and str(row["native_vlan"]) != vlan)

    def interface_proof(row: dict[str, Any]) -> dict[str, Any]:
        return {key: _id(row.get(key)) for key in (
            "id", "interface_name", "interface_type", "switchport_mode",
            "access_vlan", "native_vlan", "allowed_vlans", "admin_status",
            "oper_status", "last_seen",
        )}

    if not fresh(arp.get("observed_at")):
        return None

    visited: set[str] = set()
    path: list[dict[str, Any]] = []
    current = first_fdb
    ingress = ""
    for _ in range(16):
        device = _id(current.get("source_device_id"))
        port = _id(current.get("switch_port"))
        if (not device or device in visited or device not in allowed
                or not port or port_key(port) == port_key(ingress)
                or _id(current.get("tenant_id")) != tenant
                or _id(current.get("site_id")) != site
                or _id(current.get("address_space_id")) != space
                or current.get("scope_status") != "resolved"
                or discovery._normalized_mac(current.get("mac")) != mac
                or discovery._normalize_vlan_number(current.get("vlan")) != vlan
                or _id(current.get("entry_type")).lower() != "dynamic"
                or not current.get("coverage_complete")
                or current.get("path_ambiguity") or current.get("virtual_gateway_mac")
                or _id(current.get("evidence_status")) != "recent"
                or _id(current.get("timestamp_status")) != "valid"
                or not fresh(current.get("observed_at"))):
            return None
        visited.add(device)
        row = interface(device, port)
        if row is None:
            return None
        record = dict(current)
        record["interface_proof"] = interface_proof(row)
        path.append(record)
        classification = _id(current.get("path_classification"))
        if classification == "access_edge":
            if (_id(row.get("switchport_mode")).lower() != "access"
                    or discovery._normalize_vlan_number(row.get("access_vlan")) != vlan):
                return None
            # Recheck the underlying topology instead of trusting a possibly
            # stale access-edge classification. Any live downstream link means
            # the learned MAC proves only a forwarding direction here.
            for raw in conn.execute(
                """SELECT * FROM topology_links
                    WHERE source_device_id = ? OR target_device_id = ?""",
                (device, device),
            ).fetchall():
                link = dict(raw)
                if _id(link.get("status")).lower() not in {"up", "degraded"}:
                    continue
                for side in ("source", "target"):
                    if (_id(link.get(f"{side}_device_id")) == device
                            and port_key(link.get(f"{side}_port_normalized") or link.get(f"{side}_port")) == port_key(port)):
                        return None
            return path if len(path) > 1 else None
        if classification != "trunk_tagged_interface" or not tagged(row):
            return None

        # Do not treat missing LLDP as proof of a terminal, or traverse LAGs.
        links = []
        for raw in conn.execute(
            """SELECT * FROM topology_links
                WHERE source_device_id = ? OR target_device_id = ?""",
            (device, device),
        ).fetchall():
            link = dict(raw)
            for side, other in (("source", "target"), ("target", "source")):
                if _id(link.get(f"{side}_device_id")) != device:
                    continue
                local = link.get(f"{side}_port_normalized") or link.get(f"{side}_port")
                if port_key(local) != port_key(port):
                    continue
                if _id(link.get("status")).lower() != "up":
                    continue
                if (_id(link.get("link_kind")).lower() != "physical"
                        or _id(link.get("discovery_source")).lower() not in {"lldp", "cdp"}
                        or link.get("is_inferred") or link.get("is_unmanaged")
                        or not _id(link.get("id"))
                        or link.get("source_aggregation_name") or link.get("target_aggregation_name")
                        or not fresh(link.get("last_seen"))):
                    return None
                links.append((link, other))
        if len(links) != 1:
            return None
        link, other = links[0]
        next_device = _id(link.get(f"{other}_device_id"))
        ingress = _id(link.get(f"{other}_port_normalized") or link.get(f"{other}_port"))
        if not next_device or next_device not in allowed or next_device in visited or not ingress:
            return None
        remote = interface(next_device, ingress)
        if not tagged(remote):
            return None
        record["transit"] = {
            "link_id": _id(link.get("id")), "last_seen": _id(link.get("last_seen")),
            "next_device_id": next_device, "next_port": ingress,
            "remote_interface": interface_proof(remote),
        }
        rows = [
            candidate for candidate in discovery._current_fdb_endpoint_projection(
                conn, device_id=next_device, target_mac=mac,
            )
            if discovery._normalized_mac(candidate.get("mac")) == mac
            and discovery._normalize_vlan_number(candidate.get("vlan")) == vlan
        ]
        if len(rows) != 1:
            return None
        current = rows[0]
    return None


def find_current_endpoint_evidence(
    target_ip: str,
    *,
    tenant_id: str,
    site_id: str = "",
    vrf: str = "default",
    authorized_device_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    start_device_id: str = "",
    network_domain_id: str = "",
    conn=None,
) -> dict[str, Any] | None:
    """Resolve an endpoint from current ARP/FDB generations without history.

    Unknown routing context is acceptable only for a unique same-device
    ARP MAC/VLAN -> FDB port match. The context remains unknown; this function
    never infers Global or a VRF from a VLAN number. Cross-device matches
    require explicit scope and a fresh, proven physical tagged VLAN chain.
    """
    normalized_ip = discovery._normalized_ip(target_ip)
    tenant = _id(tenant_id)
    site = _id(site_id)
    start = _id(start_device_id)
    allowed = _authorized_ids(authorized_device_ids)
    requested_vrf, is_default_vrf = _requested_vrf(vrf)
    if (
        not normalized_ip or not tenant or not allowed or _id(network_domain_id)
        or (start and start not in allowed)
    ):
        return None

    owns_connection = conn is None
    db_conn = conn if conn is not None else get_db_connection()
    try:
        allowed_ids = sorted(allowed)
        marks = ", ".join("?" for _ in allowed_ids)
        arp_sources = db_conn.execute(
            f"""SELECT DISTINCT observation.source_device_id
                  FROM ipam_current_endpoint_observations AS observation
                  JOIN ipam_endpoint_collection_states AS state
                    ON state.device_id = observation.source_device_id
                   AND state.observation_source = observation.observation_source
                   AND state.context_source = observation.context_source
                   AND state.context_type = observation.context_type
                   AND state.local_context_key = observation.local_context_key
                   AND state.last_success_generation = observation.generation
                  JOIN devices AS device ON device.id = observation.source_device_id
                 WHERE observation.observation_source = 'arp'
                   AND host(observation.ip_address) = ?
                   AND observation.source_device_id IN ({marks})
                   AND COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') = ?
                   AND (? = '' OR COALESCE(device.site_id, '') = ?)
                 ORDER BY observation.source_device_id""",
            (normalized_ip, *allowed_ids, tenant, site, site),
        ).fetchall()
        if not arp_sources:
            return None

        candidates: list[dict[str, Any]] = []
        for source in arp_sources:
            source_device_id = _id(source.get("source_device_id"))
            if not source_device_id or (start and source_device_id != start):
                continue
            arp_rows = [
                row for row in discovery._current_endpoint_projection(
                    db_conn,
                    device_id=source_device_id,
                    observation_source="arp", target_ip=normalized_ip,
                )
                if discovery._normalized_ip(row.get("ip")) == normalized_ip
                and _scope_matches(
                    row,
                    tenant_id=tenant,
                    site_id=site,
                    authorized_device_ids=allowed,
                    start_device_id=start,
                )
            ]
            # An unresolved in-scope ARP source must not disappear from the
            # uniqueness decision just because its FDB cannot confirm a port.
            # Multiple current IP/context identities are ambiguous even if
            # they happen to share the same MAC or physical port.
            if len(arp_rows) != 1:
                return None
            arp = arp_rows[0]
            mac = discovery._normalized_mac(arp.get("mac"))
            vlan = discovery._normalize_vlan_number(arp.get("vlan"))
            source_context = _id(arp.get("source_vrf_context_status")).lower() or "unknown"
            effective_context = _id(arp.get("vrf_context_status")).lower() or "unknown"
            if (
                not mac or not vlan or discovery._is_virtual_gateway_mac(mac)
                or not arp.get("coverage_complete")
                or _id(arp.get("evidence_status")).lower() != "recent"
                or _id(arp.get("timestamp_status")).lower() != "valid"
            ):
                return None

            if source_context == "unknown":
                if not is_default_vrf:
                    return None
            elif source_context == "global":
                if not is_default_vrf or effective_context != "explicit_global":
                    return None
            elif source_context == "vrf":
                if (
                    is_default_vrf or effective_context != "explicit_vrf"
                    or _id(arp.get("vrf_id")) != requested_vrf
                ):
                    return None
            else:
                return None

            fdb_rows = [
                row for row in discovery._current_fdb_endpoint_projection(
                    db_conn, device_id=source_device_id, target_mac=mac,
                )
                if _id(row.get("source_device_id")) == source_device_id
                and _id(row.get("tenant_id")) == tenant
                and (not site or _id(row.get("site_id")) == site)
                and discovery._normalized_mac(row.get("mac")) == mac
                and discovery._normalize_vlan_number(row.get("vlan")) == vlan
                and _id(row.get("context_source")) == _id(arp.get("context_source"))
                and _id(row.get("context_type")) == _id(arp.get("context_type"))
                and _id(row.get("local_context_key")) == _id(arp.get("local_context_key"))
            ]
            if len(fdb_rows) != 1:
                return None
            fdb = fdb_rows[0]
            fdb_path = [fdb]
            if _id(fdb.get("path_classification")).lower() != "access_edge":
                if len(arp_sources) != 1:
                    return None
                cross_path = _current_cross_device_fdb_path(
                    db_conn, arp=arp, first_fdb=fdb, allowed=allowed,
                    tenant=tenant, mac=mac, vlan=vlan,
                )
                if not cross_path:
                    return None
                fdb_path = cross_path
                fdb = cross_path[-1]
            terminal_device_id = _id(fdb.get("source_device_id"))
            if (
                not fdb.get("coverage_complete")
                or _id(fdb.get("evidence_status")).lower() != "recent"
                or _id(fdb.get("timestamp_status")).lower() != "valid"
                or fdb.get("path_ambiguity")
                or fdb.get("virtual_gateway_mac")
                or _id(fdb.get("path_classification")).lower() != "access_edge"
                or not _id(fdb.get("switch_port"))
            ):
                return None

            # The FDB path projector classifies an interface by port mode,
            # while this IP-to-port join also needs to prove that the learned
            # VLAN is the interface's configured access VLAN.
            from core.interface_utils import normalize_interface_name

            port_name = _id(fdb.get("switch_port"))
            port_key = normalize_interface_name(port_name).strip().lower()
            interface_rows = [
                dict(row)
                for row in db_conn.execute(
                    """SELECT interface_name, interface_type, switchport_mode, access_vlan
                         FROM interfaces WHERE device_id = ?""",
                    (terminal_device_id,),
                ).fetchall()
                if normalize_interface_name(_id(row.get("interface_name"))).strip().lower() == port_key
            ]
            if len(interface_rows) != 1:
                return None
            interface = interface_rows[0]
            if (
                _id(interface.get("interface_type")).lower()
                not in {"physical", "ethernet", "ethernet_port", "port", "access"}
                or _id(interface.get("switchport_mode")).lower() != "access"
                or discovery._normalize_vlan_number(interface.get("access_vlan")) != vlan
            ):
                return None

            arp_observed_at, _ = _iso_utc(arp.get("observed_at"))
            fdb_observed_at, _ = _iso_utc(fdb.get("observed_at"))
            timestamps = [value for value in (arp_observed_at, fdb_observed_at) if value]
            for hop in fdb_path:
                for observed in (
                    hop.get("observed_at"), (hop.get("interface_proof") or {}).get("last_seen"),
                    (hop.get("transit") or {}).get("last_seen"),
                    ((hop.get("transit") or {}).get("remote_interface") or {}).get("last_seen"),
                ):
                    stamp, _ = _iso_utc(observed)
                    if stamp:
                        timestamps.append(stamp)
            candidates.append({
                "location": {
                    "device_id": terminal_device_id,
                    "device": _id(fdb.get("switch_name") or fdb.get("source_device_name") or terminal_device_id),
                    "port": _id(fdb.get("switch_port")),
                    "mac": mac,
                    "vlan": str(vlan),
                },
                "arp_evidence": [{
                    "observation_id": _id(arp.get("observation_id") or arp.get("id")),
                    "device_id": source_device_id,
                    "source_device_id": source_device_id,
                    "device": _id(arp.get("source_device_name") or source_device_id),
                    "source_device": _id(arp.get("source_device_name") or source_device_id),
                    "interface": _id(arp.get("source_interface_name") or arp.get("interface_name")),
                    "ip": normalized_ip,
                    "mac": mac,
                    "vlan": str(vlan),
                    "site_id": _id(arp.get("site_id")),
                    "vrf_id": _id(arp.get("vrf_id")),
                    "vrf_context_status": effective_context,
                    "observed_at": _id(arp.get("observed_at")),
                }],
                "fdb_evidence": [{
                    "observation_id": _id(hop.get("observation_id") or hop.get("id")),
                    "device_id": _id(hop.get("source_device_id")),
                    "interface": _id(hop.get("switch_port")),
                    "mac": mac,
                    "vlan": str(vlan),
                    "entry_type": _id(hop.get("entry_type")),
                    "path_classification": _id(hop.get("path_classification")),
                    "path_evidence": _id(hop.get("path_evidence")),
                    "generation": int(hop.get("generation") or 0),
                    "observed_at": _id(hop.get("observed_at")),
                    **({"interface_proof": hop["interface_proof"]} if hop.get("interface_proof") else {}),
                    **({"transit": hop["transit"]} if hop.get("transit") else {}),
                } for hop in fdb_path],
                "evidence_collected_at": min(timestamps) if timestamps else "",
                "vrf_context_status": effective_context,
                "source_device_ids": sorted({_id(hop.get("source_device_id")) for hop in fdb_path} | {source_device_id}),
                "collection_source": _id(arp.get("context_source")),
            })

        return candidates[0] if len(candidates) == 1 else None
    finally:
        if owns_connection:
            db_conn.close()


def _current_snmp_mac_rows(conn, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep projected FDB rows that still exist in the latest SNMP table."""
    mac_rows = [
        row for row in rows
        if row.get("source_type") == "mac"
        and discovery._normalized_mac(row.get("mac"))
        and _id(row.get("source_device_id"))
    ]
    device_ids = {_id(row.get("source_device_id")) for row in mac_rows}
    statuses = _load_statuses(conn, "mac_table", device_ids)
    current_by_device: dict[str, dict[str, set[tuple[str, str, str, str]]]] = {}
    current_rows: list[dict[str, Any]] = []
    for row in mac_rows:
        device_id = _id(row.get("source_device_id"))
        mac = discovery._normalized_mac(row.get("mac"))
        status = statuses.get(device_id, {})
        if not _mac_status_is_proven(status):
            continue
        if device_id not in current_by_device:
            raw_rows = conn.execute(
                """SELECT device_id, mac_address, interface_name, vlan_id, last_updated
                     FROM mac_table
                    WHERE device_id = ?
                      AND LOWER(regexp_replace(mac_address, '[^0-9a-fA-F]', '', 'g')) = ?""",
                (device_id, mac.replace(":", "")),
            ).fetchall()
            current_by_device[device_id] = {}
            for raw in raw_rows:
                raw_item = dict(raw)
                raw_mac = discovery._normalized_mac(raw_item.get("mac_address"))
                if not raw_mac:
                    continue
                parsed, parsed_status = discovery._parse_time(raw_item.get("last_updated"))
                if not parsed or parsed_status != "valid":
                    continue
                current_by_device[device_id].setdefault(raw_mac, set()).add((
                    _id(raw_item.get("interface_name")),
                    discovery._normalize_vlan_number(raw_item.get("vlan_id")),
                    parsed.isoformat(),
                    raw_mac,
                ))
        parsed, parsed_status = discovery._parse_time(row.get("source_observed_at"))
        if not parsed or parsed_status != "valid":
            continue
        projected_key = (
            _id(row.get("interface_name")),
            discovery._normalize_vlan_number(row.get("vlan")),
            parsed.isoformat(),
            mac,
        )
        if projected_key in current_by_device[device_id].get(mac, set()):
            current_rows.append(row)
    return current_rows


def _requested_vrf(vrf: str) -> tuple[str, bool]:
    value = _id(vrf).lower()
    if value in {"", "default", "global"}:
        return "", True
    return _id(vrf), False


def _vrf_matches(item: dict[str, Any], requested_vrf: str, is_default: bool) -> bool:
    source_status = _id(item.get("source_vrf_context_status")).lower() or "unknown"
    effective_status = _id(item.get("vrf_context_status")).lower() or source_status
    if is_default:
        if source_status == "explicit_global":
            return effective_status == "explicit_global" and not _id(item.get("vrf_id"))
        if source_status == "unknown":
            return (
                effective_status == "unknown"
                and _id(item.get("switch_location_basis")) == "same_device_vlan_mac_access"
            )
        return False
    return (
        source_status == "explicit_vrf"
        and effective_status == "explicit_vrf"
        and _id(item.get("vrf_id")) == requested_vrf
    )


def _iso_utc(value: Any) -> tuple[str, datetime | None]:
    parsed, state = discovery._parse_time(value)
    if not parsed or state != "valid":
        return "", None
    return parsed.isoformat(), parsed


def endpoint_source_device_ids(
    target_ip: str,
    *,
    tenant_id: str,
    site_id: str = "",
    vrf: str = "default",
    authorized_device_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    start_device_id: str = "",
    network_domain_id: str = "",
) -> list[str]:
    """Return authorized ARP source devices for an exact IP, including stale rows.

    These IDs are refresh candidates only; VRF validity is enforced by
    ``find_endpoint_evidence`` before any location can be returned.
    """
    normalized_ip = discovery._normalized_ip(target_ip)
    tenant = _id(tenant_id)
    site = _id(site_id)
    start = _id(start_device_id)
    allowed = _authorized_ids(authorized_device_ids)
    if (
        not normalized_ip or not tenant or not allowed or _id(network_domain_id)
        or (start and start not in allowed)
    ):
        return []

    conn = get_db_connection()
    try:
        rows = discovery._load_projected_observations(conn, ip=normalized_ip)
        source_ids = {
            _id(row.get("source_device_id"))
            for row in rows
            if row.get("source_type") == "arp"
            and discovery._normalized_ip(row.get("ip")) == normalized_ip
            and _scope_matches(
                row,
                tenant_id=tenant,
                site_id=site,
                authorized_device_ids=allowed,
                start_device_id=start,
            )
        }
        return sorted(source_ids)
    finally:
        conn.close()


def find_endpoint_evidence(
    target_ip: str,
    *,
    tenant_id: str,
    site_id: str = "",
    vrf: str = "default",
    authorized_device_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    start_device_id: str = "",
    network_domain_id: str = "",
    conn=None,
) -> dict[str, Any] | None:
    """Find one current, authorized physical endpoint location from SNMP evidence."""
    normalized_ip = discovery._normalized_ip(target_ip)
    tenant = _id(tenant_id)
    site = _id(site_id)
    start = _id(start_device_id)
    allowed = _authorized_ids(authorized_device_ids)
    requested_vrf, is_default_vrf = _requested_vrf(vrf)
    if (
        not normalized_ip or not tenant or not allowed or _id(network_domain_id)
        or (start and start not in allowed)
    ):
        return None

    owns_connection = conn is None
    db_conn = conn if conn is not None else get_db_connection()
    try:
        loaded_arp = discovery._load_projected_observations(db_conn, ip=normalized_ip)
        # Scope and device authorization are applied before decoration so no
        # unauthorized MAC or switch provenance can enter a returned result.
        arp_rows = [
            row for row in loaded_arp
            if row.get("source_type") == "arp"
            and discovery._normalized_ip(row.get("ip")) == normalized_ip
            and _scope_matches(
                row,
                tenant_id=tenant,
                site_id=site,
                authorized_device_ids=allowed,
                start_device_id=start,
            )
        ]
        if not arp_rows:
            return None

        now = discovery._utc_now()
        current_arp_rows = []
        for row in arp_rows:
            if _id(row.get("timestamp_status")).lower() != "valid":
                continue
            observed_at, timestamp_status = discovery._parse_time(row.get("source_observed_at"))
            if (
                timestamp_status == "valid"
                and observed_at is not None
                and timedelta(0) <= now - observed_at <= timedelta(minutes=discovery._recent_minutes())
            ):
                current_arp_rows.append(row)
        if not current_arp_rows:
            return None

        arps_by_mac: dict[str, list[dict[str, Any]]] = {}
        for row in current_arp_rows:
            mac = discovery._normalized_mac(row.get("mac"))
            if mac:
                arps_by_mac.setdefault(mac, []).append(row)

        mac_rows: list[dict[str, Any]] = []
        arp_sites = {_id(row.get("site_id")) for row in current_arp_rows}
        for mac in sorted(arps_by_mac):
            loaded_mac = discovery._load_projected_observations(db_conn, mac=mac)
            mac_rows.extend(
                row for row in loaded_mac
                if row.get("source_type") == "mac"
                and discovery._normalized_mac(row.get("mac")) == mac
                and _scope_matches(
                    row,
                    tenant_id=tenant,
                    site_id=site,
                    authorized_device_ids=allowed,
                    start_device_id="",
                )
                and _id(row.get("site_id")) in arp_sites
            )
        mac_rows = _current_snmp_mac_rows(db_conn, mac_rows)

        arp_device_ids = {_id(row.get("source_device_id")) for row in current_arp_rows}
        arp_statuses = _load_statuses(db_conn, "arp", arp_device_ids)
        if any(
            not _arp_transport_is_proven(row, arp_statuses.get(_id(row.get("source_device_id")), {}))
            for row in current_arp_rows
        ):
            return None

        decorated = discovery._decorate_observations(
            [*current_arp_rows, *mac_rows], db_conn, now, {},
        )
        decorated_arp = [
            item for item in decorated
            if item.get("source_type") == "arp"
            and discovery._normalized_ip(item.get("ip")) == normalized_ip
        ]
        if len(decorated_arp) != len(current_arp_rows):
            return None

        # Keep every recent ARP candidate in uniqueness checks, including
        # candidates whose decorator could not prove a physical port.
        recent_arp: list[dict[str, Any]] = []
        for item in decorated_arp:
            if item.get("evidence_status") != "recent" or item.get("timestamp_status") != "valid":
                return None
            if (
                _id(item.get("tenant_id")) != tenant
                or (site and _id(item.get("site_id")) != site)
                or _id(item.get("source_device_id")) not in allowed
                or (start and _id(item.get("source_device_id")) != start)
            ):
                return None
            recent_arp.append(item)
        if not recent_arp:
            return None

        macs = {discovery._normalized_mac(item.get("mac")) for item in recent_arp}
        vlans = {discovery._normalize_vlan_number(item.get("vlan")) for item in recent_arp}
        sites = {_id(item.get("site_id")) for item in recent_arp}
        if "" in macs or len(macs) != 1 or "" in vlans or len(vlans) != 1 or "" in sites or len(sites) != 1:
            return None

        locations: set[tuple[str, str]] = set()
        for item in recent_arp:
            if not _vrf_matches(item, requested_vrf, is_default_vrf):
                return None
            if (
                item.get("switch_location_status") != "matched"
                or _id(item.get("switch_location_basis")) not in _LOCATION_BASES
                or not _id(item.get("switch_port"))
            ):
                return None
            switch_id = _id(item.get("switch_id"))
            port = _id(item.get("switch_port"))
            if not switch_id or switch_id not in allowed:
                return None
            locations.add((switch_id, port))
        if len(locations) != 1:
            return None

        switch_id, port = next(iter(locations))
        first = recent_arp[0]
        context_statuses = {
            _id(item.get("source_vrf_context_status")).lower() or "unknown"
            for item in recent_arp
        }
        result_vrf_status = "unknown" if "unknown" in context_statuses else (
            "explicit_global" if is_default_vrf else "explicit_vrf"
        )
        timestamps = [
            timestamp
            for item in recent_arp
            for value in (item.get("observed_at"), item.get("mac_observed_at"))
            for _text, timestamp in [_iso_utc(value)]
            if timestamp is not None
        ]
        evidence_collected_at = min(timestamps).isoformat() if timestamps else ""
        arp_evidence = [
            {
                "observation_id": _id(item.get("observation_id") or item.get("id")),
                "device_id": _id(item.get("source_device_id")),
                "source_device_id": _id(item.get("source_device_id")),
                "device": _id(item.get("source_device_name") or item.get("source_device_id")),
                "source_device": _id(item.get("source_device_name") or item.get("source_device_id")),
                "interface": _id(item.get("source_interface_name") or item.get("interface_name")),
                "ip": normalized_ip,
                "mac": next(iter(macs)),
                "vlan": next(iter(vlans)),
                "site_id": _id(item.get("site_id")),
                "vrf_id": _id(item.get("vrf_id")),
                "vrf_context_status": _id(item.get("source_vrf_context_status")).lower() or "unknown",
                "observed_at": _id(item.get("observed_at")),
            }
            for item in sorted(recent_arp, key=lambda value: (
                _id(value.get("source_device_id")), _id(value.get("observation_id") or value.get("id")),
            ))
        ]
        return {
            "location": {
                "device_id": switch_id,
                "device": _id(first.get("switch_name") or switch_id),
                "port": port,
                "mac": next(iter(macs)),
                "vlan": next(iter(vlans)),
            },
            "arp_evidence": arp_evidence,
            "evidence_collected_at": evidence_collected_at,
            "vrf_context_status": result_vrf_status,
            "source_device_ids": sorted({_id(item.get("source_device_id")) for item in recent_arp}),
        }
    finally:
        if owns_connection:
            db_conn.close()
