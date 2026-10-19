from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re


MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "vendor"
    / "librenms"
    / "source-manifest.json"
)
REPOSITORY_ROOT = MANIFEST_PATH.parents[3]


def test_manifest_distinguishes_platform_scope_from_upstream_tree() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["mibs"]

    assert manifest["mib_manifest_schema_version"] == 2
    assert "interface monitoring provenance is outside this manifest" in manifest["scope"]
    assert manifest["mib_scope_contract"]["field"] == "platform_vendor_scope"
    assert manifest["mib_scope_contract"]["rule_selection"].endswith(
        "not from platform_vendor_scope."
    )
    assert all("platform_vendor_scope" in entry for entry in entries)
    assert all("vendor_scope" not in entry for entry in entries)
    assert all(entry["upstream_path"].startswith("mibs/") for entry in entries)
    assert all(entry["bundle_path"].startswith("mibs/") for entry in entries)


def test_pinned_sources_disable_git_line_ending_conversion() -> None:
    attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "backend/vendor/librenms/resources/definitions/** -text" in attributes
    assert "backend/vendor/librenms/mibs/** -text" in attributes
    assert "backend/vendor/librenms/LibreNMS/**/*.php -text" in attributes


def test_wireless_dispatcher_is_pinned_and_manifest_lists_upstream_vendor_rules() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_path = "LibreNMS/Modules/Wireless.php"
    dispatcher = manifest["wireless_discovery"]
    assert dispatcher["dispatcher_path"] == source_path
    assert len(dispatcher["rule_keys"]) == 20
    assert "wireless_cisco_iosxe_cellular" in dispatcher["rule_keys"]
    assert "wireless_stellar" in dispatcher["rule_keys"]
    assert "wireless_h3c_comware" not in dispatcher["rule_keys"]

    entry = next(item for item in manifest["adapter_files"] if item["upstream_path"] == source_path)
    payload = (MANIFEST_PATH.parent / entry["bundle_path"]).read_bytes()
    assert len(manifest["adapter_files"]) == 29
    assert entry["size_bytes"] == len(payload)
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()


def test_cisco_cellular_trait_is_pinned_as_an_adapter_source() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_path = "LibreNMS/OS/Traits/CiscoCellular.php"

    entry = next(
        item for item in manifest["adapter_files"]
        if item["upstream_path"] == source_path
    )
    payload = (MANIFEST_PATH.parent / entry["bundle_path"]).read_bytes()

    assert entry["bundle_path"] == source_path
    assert entry["size_bytes"] == len(payload)
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()


def test_wireless_rule_mibs_are_within_the_existing_vendored_mib_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    upstream_mib_paths = {entry["upstream_path"] for entry in manifest["mibs"]}
    policy_path = REPOSITORY_ROOT / "backend" / "services" / "librenms_source_policy.py"
    source_policy = policy_path.read_text(encoding="utf-8")
    service_path = REPOSITORY_ROOT / "backend" / "services" / "librenms_wireless_rule_service.py"
    wireless_service = service_path.read_text(encoding="utf-8")

    for source in (source_policy, wireless_service):
        for line in source.splitlines():
            if '"mibs/' not in line:
                continue
            for quoted in re.findall(r'"(mibs/[^" ]+)"', line):
                if "{module}" in quoted:
                    prefix, suffix = quoted.split("{module}", 1)
                    assert any(
                        path.startswith(prefix) and path.endswith(suffix)
                        for path in upstream_mib_paths
                    ), quoted
                    continue
                if quoted not in upstream_mib_paths:
                    assert quoted.startswith("mibs/standard/") and any(
                        entry["upstream_path"] == quoted.removeprefix("mibs/standard/")
                        for entry in manifest["mibs"]
                    ), quoted


def test_manifest_documents_hp_and_fiberstore_cross_scope_mappings() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["mibs"]
    mappings = {
        mapping["upstream_tree"]: mapping
        for mapping in manifest["mib_scope_mappings"]
    }

    expected = {
        "mibs/hp": ("Aruba", "mibs/aruba/_upstream/hp", "procurve", 98),
        "mibs/fs": ("Ruijie", "mibs/ruijie/_upstream/fs", "fs-ruijie", 79),
    }
    for upstream_tree, (
        platform_scope,
        bundle_tree,
        os_profile,
        expected_count,
    ) in expected.items():
        mapping = mappings[upstream_tree]
        tree_entries = [
            entry
            for entry in entries
            if entry["upstream_path"].startswith(f"{upstream_tree}/")
        ]

        assert mapping["platform_vendor_scope"] == platform_scope
        assert mapping["bundle_tree"] == bundle_tree
        assert mapping["os_profiles"] == [os_profile]
        assert mapping["mib_count"] == expected_count == len(tree_entries)
        assert all(
            entry["platform_vendor_scope"] == platform_scope
            and entry["bundle_path"]
            == bundle_tree + entry["upstream_path"][len(upstream_tree):]
            for entry in tree_entries
        )


def test_security_profiles_are_pinned_and_have_parsed_hardware_rules() -> None:
    from services.librenms_rule_service import parse_rules
    from services.snmp_vendor_registry import ASSET_SECURITY_VENDORS

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = {
        "acos": "A10 Networks",
        "barracudaspamfirewall": "Barracuda",
        "f5": "F5",
        "f5os": "F5",
        "fortigate": "Fortinet",
        "fortios": "Fortinet",
        "fortiadc": "Fortinet",
        "fortiap": "Fortinet",
        "fortiauthenticator": "Fortinet",
        "fortimail": "Fortinet",
        "fortisandbox": "Fortinet",
        "fortiswitch": "Fortinet",
        "fortiweb": "Fortinet",
        "fortiwlc": "Fortinet",
        "gaia": "Check Point",
        "secureplatform": "Check Point",
        "panos": "Palo Alto",
        "sophos-xg": "Sophos",
        "sonicwall": "SonicWall",
        "stoneos": "Hillstone",
    }

    assert manifest["asset_security_vendors"] == list(ASSET_SECURITY_VENDORS)
    assert {
        item["os_key"]: item["vendor"] for item in manifest["security_os_profiles"]
    } == expected

    bundle_rules = {
        item["os_key"]: item
        for item in parse_rules(MANIFEST_PATH.parent)
        if item["os_key"] in expected
    }
    assert set(bundle_rules) == set(expected)
    for os_key, vendor in expected.items():
        rule = bundle_rules[os_key]
        assert rule["vendor"] == vendor
        assert rule["source_commit"] == manifest["upstream_commit"]
        assert rule["identity_match"]["compatibility"] == "supported"
        assert any(
            rule["hardware_definitions"].get(section)
            for section in ("processors", "mempools", "sensors")
        )

    # PAN-OS keeps its upstream partial diagnostic: those two optional
    # conditions depend on model/version identity that may not be present.
    panos_diagnostics = {
        item["code"]
        for item in bundle_rules["panos"]["hardware_definitions"]["compatibility"]["diagnostics"]
    }
    assert panos_diagnostics == {"skip_device_field_requires_identity"}


def test_security_mib_closure_is_pinned_and_matches_asset_vendor_scopes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_scope_counts = {
        "A10 Networks": 2,
        "Barracuda": 0,
        "Check Point": 1,
        "F5": 4,
        "Fortinet": 13,
        "Hillstone": 4,
        "Palo Alto": 3,
        "Sophos": 1,
        "SonicWall": 4,
        "Standard": 11,
    }
    added_source_paths = {
        item["upstream_path"]: item
        for item in manifest["mibs"]
        if item["upstream_path"].startswith((
            "mibs/a10/", "mibs/checkpoint/", "mibs/f5/", "mibs/fortinet/",
            "mibs/hillstone/", "mibs/paloaltonetworks/", "mibs/sophos/",
            "mibs/sonicwall/",
        ))
        or item["upstream_path"] in {
            "mibs/HCNUM-TC", "mibs/INET-ADDRESS-MIB", "mibs/IPV6-TC",
            "mibs/RFC-1212", "mibs/RFC-1215", "mibs/RFC1155-SMI",
            "mibs/SNMPv2-CONF", "mibs/SNMPv2-MIB", "mibs/SNMPv2-SMI",
            "mibs/SNMPv2-TC", "mibs/UCD-SNMP-MIB",
        }
    }

    assert len(added_source_paths) == 43
    for item in added_source_paths.values():
        payload = (MANIFEST_PATH.parent / item["bundle_path"]).read_bytes()
        assert item["size_bytes"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
        assert item["upstream_path"].startswith("mibs/")
    for vendor, expected_count in expected_scope_counts.items():
        actual = sum(
            1 for item in added_source_paths.values()
            if item["platform_vendor_scope"] == vendor
        )
        assert actual == expected_count

    mappings = {
        item["upstream_tree"]: item
        for item in manifest["mib_scope_mappings"]
    }
    assert mappings["mibs/a10"]["platform_vendor_scope"] == "A10 Networks"
    assert mappings["mibs/checkpoint"]["platform_vendor_scope"] == "Check Point"
    assert mappings["mibs/paloaltonetworks"]["platform_vendor_scope"] == "Palo Alto"

    # Every executable security-rule MIB reference must be indexed. The sole
    # unresolved token is an optional FortiGate description label, not an OID.
    bundle_modules = {item["module"] for item in manifest["mibs"]}
    direct_modules: set[str] = set()
    for profile in manifest["security_os_profiles"]:
        discovery_path = (
            MANIFEST_PATH.parent
            / "resources"
            / "definitions"
            / "os_discovery"
            / f"{profile['os_key']}.yaml"
        )
        direct_modules.update(re.findall(
            r"([A-Za-z0-9_-]+)::",
            discovery_path.read_text(encoding="utf-8"),
        ))
    assert direct_modules - bundle_modules == {"InetAddress_FORTINET-FORTIGATE-MIB"}

    # All direct and transitive MIB IMPORTS resolve to a manifest-listed module.
    for item in added_source_paths.values():
        mib_text = (MANIFEST_PATH.parent / item["bundle_path"]).read_text(
            encoding="latin-1"
        )
        mib_text = re.sub(r"(?m)^\s*--[^\n]*", "", mib_text)
        imports = re.search(r"\bIMPORTS\b(.*?);", mib_text, flags=re.DOTALL | re.IGNORECASE)
        if imports is None:
            continue
        imported_modules = re.findall(
            r"\bFROM\s+([A-Za-z0-9_-]+)", imports.group(1), flags=re.IGNORECASE
        )
        assert set(imported_modules) <= bundle_modules, item["upstream_path"]


def test_manifest_explains_upstream_directory_count_vs_platform_vendor_scope() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["mibs"]
    upstream_vendor_dirs = {
        entry["upstream_path"].split("/")[1]
        for entry in entries
        if len(entry["upstream_path"].split("/")) > 2
    }
    platform_scopes = {entry["platform_vendor_scope"] for entry in entries}
    bundle_mib_root = MANIFEST_PATH.parent / "mibs"
    bundle_dirs = {path.name for path in bundle_mib_root.iterdir() if path.is_dir()}

    def folder_name(scope: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", scope.casefold()).strip("-")

    assert len(upstream_vendor_dirs) == 44
    assert len(platform_scopes - {"Standard"}) == 31
    assert {folder_name(scope) for scope in platform_scopes} == bundle_dirs
    assert len(manifest["asset_network_vendors"]) == 26
    assert len(manifest["vendors_with_upstream_os_profiles"]) == 25
    assert len(manifest["asset_security_vendors"]) == 15
    assert len(manifest["security_vendors_with_upstream_os_profiles"]) == 10
    assert len(manifest["security_vendors_with_bundled_hardware_rules"]) == 9
    assert len(manifest["security_vendors_without_upstream_os_profiles"]) == 5
    assert len(manifest["profiles"]) == 156
    assert len(manifest["rule_files"]) == 298
    assert len(manifest["mibs"]) == 2403
    assert "Arista" in manifest["vendors_with_upstream_os_profiles"]
    assert "Edgecore" in manifest["vendors_with_upstream_os_profiles"]
    assert "DPtech" in manifest["asset_vendors_without_upstream_os_profiles"]


def test_mib_sync_scope_accepts_the_security_asset_vendor_catalog() -> None:
    from api.devices import (
        _librenms_mib_sync_vendors,
        _mib_vendor_token,
        _platform_mib_vendor_map,
    )
    from services.librenms_mib_service import normalize_vendor_from_dir
    from services.mib_repository_service import vendor_name_from_key
    from services.snmp_vendor_registry import ASSET_SECURITY_VENDORS

    vendors = _librenms_mib_sync_vendors(["Cisco", "Fortinet"])
    vendor_tokens = [_mib_vendor_token(vendor) for vendor in vendors]
    allowed = _platform_mib_vendor_map(vendors)

    assert len(vendor_tokens) == len(set(vendor_tokens))
    assert all(_mib_vendor_token(vendor) in allowed for vendor in ASSET_SECURITY_VENDORS)
    assert allowed["a10networks"] == "A10 Networks"
    assert allowed["paloaltonetworks"] == "Palo Alto"
    assert normalize_vendor_from_dir("paloaltonetworks") == "Palo Alto"
    assert normalize_vendor_from_dir("hillstone") == "Hillstone"
    assert vendor_name_from_key("a10-networks") == "A10 Networks"
    assert vendor_name_from_key("check-point") == "Check Point"
