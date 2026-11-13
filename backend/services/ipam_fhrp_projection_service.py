"""Resolve current FHRP observations only through matching CMDB interface rows."""

from __future__ import annotations

import ipaddress
from typing import Any

from core.interface_utils import normalize_interface_name


def resolve_current_fhrp_observation_scope(
    observation: dict[str, Any],
    interface_ip_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a group interface only when its latest CMDB interface scope is unique.

    The FHRP brief commands report the local interface but not a trustworthy
    tenant/VRF mapping. This helper therefore uses only matching rows from the
    latest-success CMDB interface snapshot. An absent or mixed mapping remains
    pending; it never infers Global from a blank VRF or a familiar alias.
    """
    device_id = str(
        observation.get("source_device_id") or observation.get("device_id") or ""
    ).strip()
    interface_name = str(
        observation.get("interface_name") or observation.get("interface") or ""
    ).strip()
    normalized_interface = normalize_interface_name(interface_name).strip().casefold()
    raw_family = observation.get("address_family")
    try:
        address_family = int(raw_family or 0)
    except (TypeError, ValueError):
        address_family = 0

    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    unresolved = False
    for raw in interface_ip_observations:
        row = dict(raw)
        row_device_id = str(row.get("source_device_id") or row.get("device_id") or "").strip()
        row_interface = str(
            row.get("normalized_interface_name") or row.get("interface_name") or ""
        ).strip()
        normalized_row_interface = normalize_interface_name(row_interface).strip().casefold()
        if row_device_id != device_id or normalized_row_interface != normalized_interface:
            continue
        ip_value = str(row.get("ip_address") or row.get("address") or "").strip()
        try:
            ip_family = ipaddress.ip_address(ip_value).version
        except ValueError:
            unresolved = True
            continue
        if address_family in {4, 6} and ip_family != address_family:
            continue

        tenant_id = str(row.get("tenant_id") or row.get("security_tenant_id") or "").strip()
        site_id = str(
            row.get("asset_site_id") or row.get("device_site_id") or row.get("site_id") or ""
        ).strip()
        address_space_id = str(row.get("address_space_id") or "").strip()
        if not tenant_id or not site_id or not address_space_id:
            unresolved = True
            continue
        identity = (tenant_id, site_id, address_space_id)
        candidates.setdefault(identity, {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "address_space_id": address_space_id,
            "vrf_id": str(row.get("mapped_vrf_id") or row.get("vrf_id") or ""),
            "address_space_name": str(row.get("address_space_name") or ""),
            "context_source": str(row.get("context_source") or ""),
            "context_type": str(row.get("context_type") or "unknown"),
            "local_context_key": str(row.get("local_context_key") or ""),
        })

    base = {
        "source_device_id": device_id,
        "interface_name": interface_name,
        "normalized_interface_name": normalized_interface,
    }
    if not device_id or not normalized_interface:
        return {
            **base,
            "tenant_id": "",
            "site_id": "",
            "address_space_id": "",
            "vrf_id": "",
            "scope_status": "scope_pending",
            "scope_reason": "interface_snapshot_scope_missing",
        }
    if len(candidates) == 1 and not unresolved:
        mapped = next(iter(candidates.values()))
        return {**base, **mapped, "scope_status": "resolved", "scope_reason": ""}
    if len(candidates) > 1 or (candidates and unresolved):
        return {
            **base,
            "tenant_id": "",
            "site_id": "",
            "address_space_id": "",
            "vrf_id": "",
            "scope_status": "scope_pending",
            "scope_reason": "interface_snapshot_scope_ambiguous",
        }
    return {
        **base,
        "tenant_id": "",
        "site_id": "",
        "address_space_id": "",
        "vrf_id": "",
        "scope_status": "scope_pending",
        "scope_reason": "interface_snapshot_scope_missing",
    }
