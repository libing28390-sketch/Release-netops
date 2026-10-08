from __future__ import annotations

import json

from services.librenms_source_policy import (
    LIBRENMS_BUNDLE_ROOT,
    PINNED_LIBRENMS_COMMIT,
    is_trusted_hardware_sensor,
)


def _source_manifest() -> dict:
    return json.loads((LIBRENMS_BUNDLE_ROOT / "source-manifest.json").read_text(encoding="utf-8"))


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


def test_unbundled_php_adapter_path_is_not_a_trusted_hardware_rule() -> None:
    # This is an upstream PHP path, not an executable YAML rule in the bundle.
    adapter_source = "includes/discovery/sensors/current/comware.inc.php"
    sensor = {
        "source_type": "librenms_adapter",
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "source_path": adapter_source,
        "adapter_source_files": [adapter_source],
    }
    assert not is_trusted_hardware_sensor(sensor)
    assert not is_trusted_hardware_sensor({
        **sensor,
        "source_type": "librenms_rule",
    })
    assert not is_trusted_hardware_sensor({**sensor, "source_type": "h3c_wireless"})
