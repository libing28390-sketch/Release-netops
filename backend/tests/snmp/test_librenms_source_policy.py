from __future__ import annotations

import json
import shutil
from pathlib import Path

from services import librenms_source_policy as policy
from services import librenms_wireless_rule_service as wireless
from services.librenms_source_policy import (
    LIBRENMS_BUNDLE_ROOT,
    PINNED_LIBRENMS_COMMIT,
    is_trusted_hardware_sensor,
    verified_librenms_mib_source_entries,
    verify_librenms_mib_rule,
    verify_librenms_os_rule,
)


def _source_manifest() -> dict:
    return json.loads((LIBRENMS_BUNDLE_ROOT / "source-manifest.json").read_text(encoding="utf-8"))


def _os_rule(os_key: str) -> dict:
    source = next(item for item in _source_manifest()["os_rule_sources"] if item["os_key"] == os_key)
    return {
        "source_type": "librenms_os_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "os_key": os_key,
        "source_path": source["source_path"],
        "adapter_source_files": source["adapter_source_files"],
        "mib_source_files": source["mib_source_files"],
    }


def _wireless_h3c_mib_rule() -> dict:
    return {
        "source_type": "librenms_mib_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "rule_key": "wireless_h3c_comware",
        "source_path": "mibs/comware/HH3C-DOT11-APMT-MIB",
        "mib_source_files": [
            "mibs/comware/HH3C-DOT11-ACMT-MIB",
            "mibs/comware/HH3C-DOT11-APMT-MIB",
            "mibs/comware/HH3C-DOT11-STATION-MIB",
        ],
    }


def test_verified_librenms_mib_entries_bind_to_manifest_path_and_hash():
    entries = verified_librenms_mib_source_entries(
        module_name="HH3C-DOT11-ACMT-MIB",
    )
    assert len(entries) == 1
    entry = entries[0]
    expected = "mibs/comware/HH3C-DOT11-ACMT-MIB"
    assert entry["upstream_path"] == expected
    assert verified_librenms_mib_source_entries(
        module_name="HH3C-DOT11-ACMT-MIB",
        relative_path=entry["bundle_path"].removeprefix("mibs/"),
        sha256=entry["sha256"],
    ) == entries
    assert verified_librenms_mib_source_entries(
        module_name="HH3C-DOT11-ACMT-MIB",
        relative_path="different/HH3C-DOT11-ACMT-MIB",
        sha256=entry["sha256"],
    ) == []


def test_pinned_h3c_wireless_mib_rule_requires_exact_pinned_mib_set():
    rule = _wireless_h3c_mib_rule()
    assert verify_librenms_mib_rule(rule)
    assert is_trusted_hardware_sensor(rule)
    assert not verify_librenms_mib_rule({**rule, "source_commit": "different-commit"})
    assert not verify_librenms_mib_rule({**rule, "rule_key": "wireless_unknown"})
    assert not verify_librenms_mib_rule({
        **rule,
        "mib_source_files": [*rule["mib_source_files"], "mibs/comware/UNLISTED-MIB"],
    })


def test_repeated_hardware_trust_checks_reuse_manifest_path_index():
    policy._manifest_source_index.cache_clear()
    rule = _wireless_h3c_mib_rule()

    assert verify_librenms_mib_rule(rule)
    first = policy._manifest_source_index.cache_info()
    assert verify_librenms_mib_rule(rule)
    second = policy._manifest_source_index.cache_info()

    assert second.hits > first.hits


def test_manifest_path_index_rebuilds_when_manifest_signature_changes(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    manifest_path = root / "source-manifest.json"
    first_manifest = {
        "upstream_commit": PINNED_LIBRENMS_COMMIT,
        "mibs": [{"upstream_path": "mibs/first"}],
    }
    manifest_path.write_text(json.dumps(first_manifest), encoding="utf-8")

    first_stat = manifest_path.stat()
    first_index = policy._manifest_source_index(
        str(root.resolve()), first_stat.st_mtime_ns, first_stat.st_size, "mibs",
    )
    assert set(first_index) == {"mibs/first"}

    first_manifest["mibs"].append({"upstream_path": "mibs/second"})
    manifest_path.write_text(json.dumps(first_manifest), encoding="utf-8")
    second_stat = manifest_path.stat()
    second_index = policy._manifest_source_index(
        str(root.resolve()), second_stat.st_mtime_ns, second_stat.st_size, "mibs",
    )

    assert set(second_index) == {"mibs/first", "mibs/second"}


def test_pinned_huawei_vrp_wireless_rule_binds_php_reference_and_mibs():
    rule = {
        "source_type": "librenms_mib_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "rule_key": "wireless_huawei_vrp",
        "source_path": "LibreNMS/OS/Vrp.php",
        "adapter_source_files": [
            "LibreNMS/Modules/Wireless.php",
            "LibreNMS/OS/Vrp.php",
        ],
        "mib_source_files": [
            "mibs/huawei/HUAWEI-WLAN-GLOBAL-MIB",
            "mibs/huawei/HUAWEI-WLAN-AP-MIB",
            "mibs/huawei/HUAWEI-WLAN-AP-RADIO-MIB",
            "mibs/huawei/HUAWEI-WLAN-VAP-MIB",
        ],
    }
    assert verify_librenms_mib_rule(rule)
    assert not verify_librenms_mib_rule({
        **rule,
        "adapter_source_files": ["LibreNMS/OS/Comware.php"],
    })
    assert not verify_librenms_mib_rule({
        **rule,
        "adapter_source_files": ["LibreNMS/OS/Vrp.php"],
    })


def test_pinned_cisco_ios_wireless_rule_requires_association_mib_and_ios_source():
    rule = {
        "source_type": "librenms_mib_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "rule_key": "wireless_cisco_ios",
        "source_path": "LibreNMS/OS/Ios.php",
        "adapter_source_files": [
            "LibreNMS/Modules/Wireless.php",
            "LibreNMS/OS/Ios.php",
            "LibreNMS/OS/Shared/Cisco.php",
            "LibreNMS/OS/Traits/CiscoCellular.php",
        ],
        "mib_source_files": [
            "mibs/cisco/CISCO-DOT11-ASSOCIATION-MIB",
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
            "mibs/ENTITY-MIB",
        ],
    }
    assert verify_librenms_mib_rule(rule)
    assert not verify_librenms_mib_rule({
        **rule,
        "mib_source_files": ["mibs/cisco/CISCO-LWAPP-AP-MIB"],
    })
    assert not verify_librenms_mib_rule({
        **rule,
        "mib_source_files": [
            *rule["mib_source_files"],
            "mibs/cisco/UNLISTED-CISCO-MIB",
        ],
    })


def test_pinned_cisco_iosxe_cellular_rule_requires_trait_and_existing_cisco_mibs():
    rule = {
        "source_type": "librenms_mib_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "rule_key": "wireless_cisco_iosxe_cellular",
        "source_path": "LibreNMS/OS/Iosxe.php",
        "adapter_source_files": [
            "LibreNMS/Modules/Wireless.php",
            "LibreNMS/OS/Ciscowlc.php",
            "LibreNMS/OS/Iosxe.php",
            "LibreNMS/OS/Shared/Cisco.php",
            "LibreNMS/OS/Traits/CiscoCellular.php",
        ],
        "mib_source_files": [
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
            "mibs/ENTITY-MIB",
        ],
    }

    assert verify_librenms_mib_rule(rule)
    assert not verify_librenms_mib_rule({
        **rule,
        "adapter_source_files": [
            path for path in rule["adapter_source_files"]
            if path != "LibreNMS/OS/Traits/CiscoCellular.php"
        ],
    })
    assert not verify_librenms_mib_rule({
        **rule,
        "mib_source_files": [
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
        ],
    })


def test_every_added_wireless_profile_is_bound_to_exact_manifest_sources():
    profile_keys = [
        "aruba-instant", "arubaos", "ciscowlc", "ewc", "stellar", "ruckuswireless",
        "ruckuswireless-hotzone", "ruckuswireless-sz", "ruckuswireless-unleashed",
        "routeros", "airos", "unifi", "ciscosat", "airos-af", "airos-af-ltu",
        "airos-af60", "timos",
    ]
    for os_key in profile_keys:
        source = wireless._PROFILE_WIRELESS_RULES[os_key]["source_rule"]
        rule = {
            **source,
            "source_type": "librenms_mib_rule",
            "source_commit": PINNED_LIBRENMS_COMMIT,
        }
        assert verify_librenms_mib_rule(rule), os_key

    # IOS-XE inherits the pinned Cisco WLC wireless methods and is an explicit alias.
    assert wireless._PROFILE_WIRELESS_RULES["iosxe"]["alias_of"] == "ciscowlc"
    iosxe_source = (LIBRENMS_BUNDLE_ROOT / "LibreNMS/OS/Iosxe.php").read_text(encoding="utf-8")
    assert "class Iosxe extends Ciscowlc" in iosxe_source


def test_librenms_wireless_dispatcher_is_pinned_but_comware_has_no_os_wireless_rule():
    manifest = _source_manifest()
    dispatcher = "LibreNMS/Modules/Wireless.php"
    discovery = manifest["wireless_discovery"]
    assert discovery["dispatcher_path"] == dispatcher
    assert set(discovery["rule_keys"]) == policy._UPSTREAM_WIRELESS_RULE_KEYS
    assert "wireless_h3c_comware" not in discovery["rule_keys"]
    assert policy._verified_manifest_source(
        manifest, section="adapter_files", upstream_path=dispatcher,
    )

    dispatcher_source = (LIBRENMS_BUNDLE_ROOT / dispatcher).read_text(encoding="utf-8")
    comware_source = (LIBRENMS_BUNDLE_ROOT / "LibreNMS/OS/Comware.php").read_text(encoding="utf-8")
    assert "if ($os instanceof $typeInterface)" in dispatcher_source
    assert "$os->$function()" in dispatcher_source
    assert "class Comware extends OS implements MempoolsDiscovery, ProcessorDiscovery, TransceiverDiscovery" in comware_source
    assert "Wireless" not in comware_source


def _copy_rule_sources(tmp_path: Path) -> Path:
    manifest = _source_manifest()
    root = tmp_path / "librenms"
    root.mkdir()
    (root / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    required_entries = [
        *manifest["adapter_files"],
        *(
            entry
            for entry in manifest["mibs"]
            if entry["upstream_path"] in {
                path
                for source in manifest["os_rule_sources"]
                for path in source["mib_source_files"]
            }
        ),
    ]
    for entry in required_entries:
        source = LIBRENMS_BUNDLE_ROOT / entry["bundle_path"]
        destination = root / entry["bundle_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return root


def test_rule_sensor_must_point_to_a_hashed_librenms_os_discovery_definition() -> None:
    manifest = _source_manifest()
    discovery_source = next(
        item["upstream_path"]
        for item in manifest["rule_files"]
        if item["upstream_path"].startswith("resources/definitions/os_discovery/")
        and item["upstream_path"].endswith(".yaml")
    )
    assert is_trusted_hardware_sensor({
        "source_type": "librenms_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "source_path": discovery_source,
    })
    assert not is_trusted_hardware_sensor({
        "source_type": "librenms_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "source_path": discovery_source.replace("os_discovery", "os_detection"),
    })
    assert not is_trusted_hardware_sensor({
        "source_type": "librenms_rule",
        "source_commit": "different-commit",
        "source_path": discovery_source,
    })


def test_pinned_ios_and_comware_os_rules_verify_exact_adapter_and_mib_sources() -> None:
    ios = _os_rule("ios")
    comware = _os_rule("comware")

    assert verify_librenms_os_rule(ios)
    assert verify_librenms_os_rule(comware)
    assert is_trusted_hardware_sensor(ios)
    assert is_trusted_hardware_sensor({"source": comware})
    metadata_source = {
        "source_type": "librenms_os_rule",
        "component_class": "processor",
        "metadata": json.dumps({key: value for key, value in ios.items() if key != "source_type"}),
    }
    assert verify_librenms_os_rule(metadata_source)
    assert is_trusted_hardware_sensor(metadata_source)


def test_os_rule_verification_rejects_changed_commit_unlisted_paths_and_inexact_sets() -> None:
    valid = _os_rule("ios")
    assert not verify_librenms_os_rule({**valid, "source_commit": "different-commit"})
    assert not verify_librenms_os_rule({**valid, "os_key": "nxos"})
    assert not verify_librenms_os_rule({**valid, "source_path": "LibreNMS/OS/Unknown.php"})
    assert not verify_librenms_os_rule({
        **valid,
        "adapter_source_files": [*valid["adapter_source_files"], "LibreNMS/OS/Unknown.php"],
    })
    assert not verify_librenms_os_rule({
        **valid,
        "mib_source_files": [*valid["mib_source_files"], "mibs/cisco/UNLISTED-MIB"],
    })


def test_os_rule_verification_fails_when_a_pinned_php_source_is_tampered(tmp_path, monkeypatch) -> None:
    bundle_root = _copy_rule_sources(tmp_path)
    monkeypatch.setattr(policy, "LIBRENMS_BUNDLE_ROOT", bundle_root)

    source = bundle_root / "LibreNMS/OS/Ios.php"
    source.write_bytes(source.read_bytes() + b"\n// local tampering\n")

    assert not verify_librenms_os_rule(_os_rule("ios"))
    assert not is_trusted_hardware_sensor(_os_rule("ios"))


def test_os_rule_verification_fails_when_a_pinned_mib_is_tampered(tmp_path, monkeypatch) -> None:
    bundle_root = _copy_rule_sources(tmp_path)
    monkeypatch.setattr(policy, "LIBRENMS_BUNDLE_ROOT", bundle_root)

    source = bundle_root / "mibs/standard/_upstream/ENTITY-MIB"
    source.write_bytes(source.read_bytes() + b"\n-- local tampering\n")

    assert not verify_librenms_os_rule(_os_rule("comware"))


def test_os_rule_verification_rejects_an_unlisted_source_even_if_present_locally(tmp_path, monkeypatch) -> None:
    bundle_root = _copy_rule_sources(tmp_path)
    monkeypatch.setattr(policy, "LIBRENMS_BUNDLE_ROOT", bundle_root)
    unlisted = "LibreNMS/OS/Unknown.php"
    target = bundle_root / unlisted
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("<?php // not an allowlisted source\n", encoding="utf-8")
    altered = _os_rule("ios")
    altered["adapter_source_files"] = [*altered["adapter_source_files"], unlisted]

    assert not verify_librenms_os_rule(altered)


def test_legacy_php_adapter_label_remains_untrusted() -> None:
    adapter_source = "includes/discovery/sensors/current/comware.inc.php"
    sensor = {
        "source_type": "librenms_adapter",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "source_path": adapter_source,
        "adapter_source_files": [adapter_source],
    }
    assert not is_trusted_hardware_sensor(sensor)
    assert not is_trusted_hardware_sensor({**sensor, "source_type": "librenms_rule"})
    assert not is_trusted_hardware_sensor({**sensor, "source_type": "h3c_wireless"})
