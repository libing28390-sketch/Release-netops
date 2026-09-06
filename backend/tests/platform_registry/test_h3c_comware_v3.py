from __future__ import annotations

from core.textfsm import (
    _template_platform_candidates,
    resolve_textfsm_parser_platform,
    resolve_textfsm_platform,
)
from services.operational_data_service import (
    _resolve_commands,
    resolve_device_platform_context,
)
from services.platform_identification_service import _inventory_profile_code
from services.platform_registry_service import (
    SYSTEM_PROFILES,
    get_profile_action_commands,
    platform_codes_match,
)


def test_h3c_v3_profile_uses_legacy_transport_and_command_contract():
    profile = next(item for item in SYSTEM_PROFILES if item["platform_code"] == "h3c_comware_v3")

    assert profile["vendor"] == "H3C"
    assert profile["connection_driver"] == "hp_comware"
    assert profile["parser_platform"] == "h3c_comware"
    actions = get_profile_action_commands(profile)
    assert actions["get_version"] == "display version"
    assert actions["get_bgp_neighbors"] == "display bgp peer"

    context = resolve_device_platform_context({
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v3",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    })
    assert context == {
        "raw_platform": "h3c_comware",
        "public_platform": "h3c_comware",
        "catalog_platform": "h3c_comware_v3",
        "parser_platform": "h3c_comware_v3",
        "parser_family": "h3c_comware",
        "profile_platform_code": "h3c_comware_v3",
        "connection_driver": "hp_comware",
    }
    assert _resolve_commands("h3c_comware_v3", ["bgp", "version"]) == {
        "bgp": ["display bgp peer"],
        "version": ["display version"],
    }


def test_h3c_v3_version_detection_and_template_fallback_are_explicit():
    assert _inventory_profile_code("h3c_comware", "3.10", "H3C") == (
        "h3c_comware_v3",
        "h3c_comware_v3",
    )
    assert resolve_textfsm_parser_platform("h3c_comware", "Comware 3.10") == "h3c_comware_v3"
    assert resolve_textfsm_platform("h3c_comware_v3") == "h3c_comware"
    assert _template_platform_candidates("h3c_comware_v3") == [
        "h3c_comware_v3",
        "h3c_comware_v5",
        "h3c_comware",
    ]


def test_h3c_v3_profile_matches_the_canonical_h3c_device_family():
    assert platform_codes_match(
        "h3c_comware",
        "h3c_comware_v3",
        "h3c_comware",
    )

