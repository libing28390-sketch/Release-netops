from __future__ import annotations

from services.ipam_fhrp_projection_service import resolve_current_fhrp_observation_scope


def _observation(*, family: int = 4, interface: str = "GigabitEthernet1/0/1") -> dict:
    return {
        "source_device_id": "fhrp-device-1",
        "interface_name": interface,
        "address_family": family,
    }


def _interface_row(
    ip: str,
    *,
    interface: str = "gi1/0/1",
    tenant: str = "tenant-1",
    site: str = "site-1",
    space: str = "space-1",
    context_key: str = "Blue",
) -> dict:
    return {
        "device_id": "fhrp-device-1",
        "normalized_interface_name": interface,
        "ip_address": ip,
        "tenant_id": tenant,
        "device_site_id": site,
        "address_space_id": space,
        "context_source": "cli",
        "context_type": "vrf",
        "local_context_key": context_key,
    }


def test_unique_latest_interface_scope_resolves_without_collapsing_multiple_ips() -> None:
    result = resolve_current_fhrp_observation_scope(
        _observation(),
        [
            _interface_row("192.0.2.1"),
            _interface_row("192.0.2.2"),
        ],
    )

    assert result["scope_status"] == "resolved"
    assert result["address_space_id"] == "space-1"
    assert result["local_context_key"] == "Blue"


def test_unknown_interface_context_never_defaults_to_global() -> None:
    result = resolve_current_fhrp_observation_scope(
        _observation(),
        [_interface_row("192.0.2.1", space="")],
    )

    assert result["scope_status"] == "scope_pending"
    assert result["address_space_id"] == ""
    assert result["scope_reason"] == "interface_snapshot_scope_missing"


def test_two_explicit_interface_scopes_remain_ambiguous() -> None:
    result = resolve_current_fhrp_observation_scope(
        _observation(),
        [
            _interface_row("192.0.2.1", space="space-1", context_key="Blue"),
            _interface_row("192.0.2.2", space="space-2", context_key="Green"),
        ],
    )

    assert result["scope_status"] == "scope_pending"
    assert result["address_space_id"] == ""
    assert result["scope_reason"] == "interface_snapshot_scope_ambiguous"


def test_address_family_selects_only_matching_interface_snapshot_rows() -> None:
    result = resolve_current_fhrp_observation_scope(
        _observation(family=6),
        [
            _interface_row("192.0.2.1", space="ipv4-space"),
            _interface_row("2001:db8::1", space="ipv6-space"),
        ],
    )

    assert result["scope_status"] == "resolved"
    assert result["address_space_id"] == "ipv6-space"


def test_fhrp_group_without_device_or_interface_identity_cannot_resolve() -> None:
    result = resolve_current_fhrp_observation_scope(
        {"source_device_id": "", "interface_name": "", "address_family": 4},
        [{"device_id": "", "normalized_interface_name": "", "ip_address": "192.0.2.1", "address_space_id": "space-1", "tenant_id": "tenant-1", "site_id": "site-1"}],
    )

    assert result["scope_status"] == "scope_pending"
    assert result["address_space_id"] == ""
