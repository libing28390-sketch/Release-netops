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
    never infers Global or a VRF from a VLAN number.
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
                   AND state.latest_attempt_generation = observation.generation
                   AND state.latest_status IN ('complete', 'scope_unknown')
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
                    observation_source="arp",
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
            # Multiple current IP/context identities are ambiguous even if
            # they happen to share the same MAC or physical port.
            if len(arp_rows) != 1:
                continue
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
                continue

            if source_context == "unknown":
                if not is_default_vrf:
                    continue
            elif source_context == "global":
                if not is_default_vrf or effective_context != "explicit_global":
                    continue
            elif source_context == "vrf":
                if (
                    is_default_vrf or effective_context != "explicit_vrf"
                    or _id(arp.get("vrf_id")) != requested_vrf
                ):
                    continue
            else:
                continue

            fdb_rows = [
                row for row in discovery._current_fdb_endpoint_projection(
                    db_conn, device_id=source_device_id,
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
                continue
            fdb = fdb_rows[0]
            if (
                not fdb.get("coverage_complete")
                or _id(fdb.get("evidence_status")).lower() != "recent"
                or _id(fdb.get("timestamp_status")).lower() != "valid"
                or fdb.get("path_ambiguity")
                or fdb.get("virtual_gateway_mac")
                or _id(fdb.get("path_classification")).lower() != "access_edge"
                or not _id(fdb.get("switch_port"))
            ):
                continue

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
                    (source_device_id,),
                ).fetchall()
                if normalize_interface_name(_id(row.get("interface_name"))).strip().lower() == port_key
            ]
            if len(interface_rows) != 1:
                continue
            interface = interface_rows[0]
            if (
                _id(interface.get("interface_type")).lower()
                not in {"physical", "ethernet", "ethernet_port", "port", "access"}
                or _id(interface.get("switchport_mode")).lower() != "access"
                or discovery._normalize_vlan_number(interface.get("access_vlan")) != vlan
            ):
                continue

            arp_observed_at, _ = _iso_utc(arp.get("observed_at"))
            fdb_observed_at, _ = _iso_utc(fdb.get("observed_at"))
            timestamps = [value for value in (arp_observed_at, fdb_observed_at) if value]
            candidates.append({
                "location": {
                    "device_id": source_device_id,
                    "device": _id(fdb.get("switch_name") or fdb.get("source_device_name") or source_device_id),
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
                    "observation_id": _id(fdb.get("observation_id") or fdb.get("id")),
                    "device_id": source_device_id,
                    "interface": _id(fdb.get("switch_port")),
                    "mac": mac,
                    "vlan": str(vlan),
                    "entry_type": _id(fdb.get("entry_type")),
                    "path_classification": _id(fdb.get("path_classification")),
                    "path_evidence": _id(fdb.get("path_evidence")),
                    "generation": int(fdb.get("generation") or 0),
                    "observed_at": _id(fdb.get("observed_at")),
                }],
                "evidence_collected_at": min(timestamps) if timestamps else "",
                "vrf_context_status": effective_context,
                "source_device_ids": [source_device_id],
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
