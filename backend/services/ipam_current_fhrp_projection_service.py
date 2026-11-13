"""Project current HSRP/VRRP observations against current interface snapshots."""

from __future__ import annotations

import hashlib
from typing import Any

from services.ipam_current_fhrp_observation_service import (
    get_current_fhrp_collection_states,
    list_current_fhrp_observations,
)
from services.ipam_fhrp_projection_service import resolve_current_fhrp_observation_scope


def list_current_fhrp_observation_projection(
    conn,
    *,
    device_id: str | None = None,
    device_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Return current FHRP facts with unique-or-pending address-space scope.

    Scope is resolved only by a matching device/interface/family in the
    latest-success CMDB interface snapshot. This function never reads an IPAM
    discovery-history table and never creates or updates formal VIP records.
    """
    rows = list_current_fhrp_observations(
        conn, device_id=device_id, device_ids=device_ids, protocol=protocol,
    )
    if not rows:
        return []

    from services.ipam_service import _current_cmdb_interface_ip_observations

    interface_rows = _current_cmdb_interface_ip_observations(conn)
    states = get_current_fhrp_collection_states(
        conn, device_id=device_id, device_ids=device_ids, protocol=protocol,
    )
    state_by_identity = {
        (str(state.get("device_id") or ""), str(state.get("protocol") or "")): state
        for state in states
    }
    device_ids = sorted({str(row.get("device_id") or "") for row in rows if row.get("device_id")})
    device_marks = ", ".join("?" for _ in device_ids)
    device_rows = conn.execute(
        f"""SELECT device.id, device.hostname,
                   COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS tenant_id,
                   COALESCE(device.site_id, '') AS device_site_id,
                   COALESCE(asset.site_id, '') AS asset_site_id,
                   COALESCE(site.site_name, site.site_code, '') AS site_name
              FROM devices AS device
              LEFT JOIN physical_assets AS asset ON asset.id = device.asset_id
              LEFT JOIN sites AS site ON site.id = COALESCE(asset.site_id, device.site_id)
             WHERE device.id IN ({device_marks})""",
        tuple(device_ids),
    ).fetchall()
    devices = {str(row["id"]): dict(row) for row in device_rows}

    projected: list[dict[str, Any]] = []
    for raw in rows:
        observation = dict(raw)
        source_device_id = str(observation.get("device_id") or "")
        device = devices.get(source_device_id)
        if not device:
            # An orphan current observation cannot convey a trustworthy scope.
            continue
        scope = resolve_current_fhrp_observation_scope(observation, interface_rows)
        state = state_by_identity.get((source_device_id, str(observation.get("protocol") or "")), {})
        latest_status = str(state.get("latest_status") or "")
        latest_generation = int(state.get("latest_attempt_generation") or 0)
        success_generation = int(state.get("last_success_generation") or 0)
        stable_identity = "|".join((
            source_device_id,
            str(observation.get("protocol") or ""),
            str(observation.get("address_family") or 0),
            str(observation.get("group_id") or ""),
            str(observation.get("normalized_interface_name") or ""),
            str(observation.get("virtual_ip_key") or ""),
        ))
        observed_ip = str(observation.get("virtual_ip_key") or "")
        projected.append({
            "id": hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:32],
            "source_type": "fhrp",
            "observation_source": "fhrp",
            "source_device_id": source_device_id,
            "source_device_name": str(device.get("hostname") or source_device_id),
            "device_id": source_device_id,
            "device_name": str(device.get("hostname") or source_device_id),
            "hostname": str(device.get("hostname") or ""),
            "tenant_id": str(scope.get("tenant_id") or device.get("tenant_id") or ""),
            "site_id": str(scope.get("site_id") or device.get("asset_site_id") or device.get("device_site_id") or ""),
            "site_name": str(device.get("site_name") or ""),
            "address_space_id": str(scope.get("address_space_id") or ""),
            "vrf_id": str(scope.get("vrf_id") or ""),
            "address_space_name": str(scope.get("address_space_name") or ""),
            "scope_status": str(scope.get("scope_status") or "scope_pending"),
            "scope_reason": str(scope.get("scope_reason") or ""),
            "protocol": str(observation.get("protocol") or ""),
            "group_id": int(observation.get("group_id") or 0),
            "address_family": int(observation.get("address_family") or 0),
            "interface_name": str(observation.get("interface_name") or ""),
            "normalized_interface_name": str(observation.get("normalized_interface_name") or ""),
            "priority": observation.get("priority"),
            "state": str(observation.get("state") or ""),
            "master_address": str(observation.get("master_address") or ""),
            "virtual_ip": observed_ip,
            "ip": observed_ip,
            "virtual_mac": str(observation.get("virtual_mac") or ""),
            "mac": str(observation.get("virtual_mac") or ""),
            "generation": int(observation.get("generation") or 0),
            "observed_at": str(observation.get("observed_at") or ""),
            "last_success_at": str(state.get("last_success_at") or ""),
            "collection_status": latest_status,
            "coverage_complete": bool(
                latest_status == "complete" and latest_generation == success_generation
            ),
            "evidence_status": "current_fhrp_observation",
        })
    return projected
