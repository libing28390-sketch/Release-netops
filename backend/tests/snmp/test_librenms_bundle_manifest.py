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

    assert len(upstream_vendor_dirs) == 36
    assert len(platform_scopes - {"Standard"}) == 23
    assert {folder_name(scope) for scope in platform_scopes} == bundle_dirs
    assert len(manifest["asset_network_vendors"]) == 26
    assert len(manifest["vendors_with_upstream_os_profiles"]) == 25
    assert "Arista" in manifest["vendors_with_upstream_os_profiles"]
    assert "Edgecore" in manifest["vendors_with_upstream_os_profiles"]
    assert "DPtech" in manifest["asset_vendors_without_upstream_os_profiles"]
