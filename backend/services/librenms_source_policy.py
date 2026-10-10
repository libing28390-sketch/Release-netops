"""Strict provenance checks for the pinned LibreNMS hardware rule bundle."""

from __future__ import annotations

import hashlib
import json
import functools
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


PINNED_LIBRENMS_COMMIT = "6c26b4fe4a40f7b392c19c36a44257212736e38c"
LIBRENMS_BUNDLE_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "librenms"
_RULE_SOURCE_TYPES = frozenset({"librenms_rule"})
_OS_RULE_SOURCE_TYPE = "librenms_os_rule"
_OS_RULE_SOURCES: dict[str, dict[str, frozenset[str]]] = {
    "ios": {
        "source_path": frozenset({"LibreNMS/OS/Ios.php"}),
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Ios.php",
            "LibreNMS/OS/Shared/Cisco.php",
        }),
        "mib_source_files": frozenset({
            "mibs/cisco/CISCO-ENHANCED-MEMPOOL-MIB",
            "mibs/cisco/CISCO-ENTITY-QFP-MIB",
            "mibs/cisco/CISCO-MEMORY-POOL-MIB",
            "mibs/cisco/CISCO-PROCESS-MIB",
            "mibs/cisco/OLD-CISCO-CPU-MIB",
            "mibs/ENTITY-MIB",
        }),
    },
    "comware": {
        "source_path": frozenset({"LibreNMS/OS/Comware.php"}),
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Comware.php",
            "includes/discovery/sensors/temperature/comware.inc.php",
            "includes/discovery/sensors/dbm/comware.inc.php",
            "includes/discovery/sensors/voltage/comware.inc.php",
            "includes/discovery/sensors/current/comware.inc.php",
        }),
        "mib_source_files": frozenset({
            "mibs/comware/HH3C-ENTITY-EXT-MIB",
            "mibs/comware/HH3C-TRANSCEIVER-INFO-MIB",
            "mibs/ENTITY-MIB",
            "mibs/IF-MIB",
        }),
    },
}
_MIB_RULE_SOURCES: dict[str, dict[str, Any]] = {
    "wireless_h3c_comware": {
        "source_path": "mibs/comware/HH3C-DOT11-APMT-MIB",
        "mib_source_files": frozenset({
            "mibs/comware/HH3C-DOT11-ACMT-MIB",
            "mibs/comware/HH3C-DOT11-APMT-MIB",
            "mibs/comware/HH3C-DOT11-STATION-MIB",
        }),
    },
    "wireless_huawei_vrp": {
        "source_path": "LibreNMS/OS/Vrp.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Vrp.php"}),
        "mib_source_files": frozenset({
            "mibs/huawei/HUAWEI-WLAN-GLOBAL-MIB",
            "mibs/huawei/HUAWEI-WLAN-AP-MIB",
            "mibs/huawei/HUAWEI-WLAN-AP-RADIO-MIB",
            "mibs/huawei/HUAWEI-WLAN-VAP-MIB",
        }),
    },
    "wireless_cisco_ios": {
        "source_path": "LibreNMS/OS/Ios.php",
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Ios.php",
            "LibreNMS/OS/Shared/Cisco.php",
            "LibreNMS/OS/Traits/CiscoCellular.php",
        }),
        "mib_source_files": frozenset({
            "mibs/cisco/CISCO-DOT11-ASSOCIATION-MIB",
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
            "mibs/ENTITY-MIB",
        }),
    },
    "wireless_cisco_iosxe_cellular": {
        "source_path": "LibreNMS/OS/Iosxe.php",
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Ciscowlc.php",
            "LibreNMS/OS/Iosxe.php",
            "LibreNMS/OS/Shared/Cisco.php",
            "LibreNMS/OS/Traits/CiscoCellular.php",
        }),
        "mib_source_files": frozenset({
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
            "mibs/ENTITY-MIB",
        }),
    },
    "wireless_aruba_instant": {
        "source_path": "LibreNMS/OS/ArubaInstant.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/ArubaInstant.php"}),
        "mib_source_files": frozenset({"mibs/arubaos/AI-AP-MIB"}),
    },
    "wireless_arubaos": {
        "source_path": "LibreNMS/OS/Arubaos.php",
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Arubaos.php",
            "includes/polling/aruba-controller.inc.php",
        }),
        "mib_source_files": frozenset({
            "mibs/arubaos/WLSX-SWITCH-MIB",
            "mibs/arubaos/WLSX-WLAN-MIB",
            "mibs/arubaos/AI-AP-MIB",
        }),
    },
    "wireless_cisco_wlc": {
        "source_path": "LibreNMS/OS/Ciscowlc.php",
        "adapter_source_files": frozenset({
            "LibreNMS/OS/Ciscowlc.php",
            "LibreNMS/OS/Iosxe.php",
            "LibreNMS/OS/Shared/Cisco.php",
            "LibreNMS/OS/Traits/CiscoCellular.php",
        }),
        "mib_source_files": frozenset({
            "mibs/cisco/AIRESPACE-SWITCHING-MIB",
            "mibs/cisco/AIRESPACE-WIRELESS-MIB",
            "mibs/cisco/CISCO-LWAPP-AP-MIB",
            "mibs/cisco/CISCO-LWAPP-SYS-MIB",
            "mibs/cisco/CISCO-LWAPP-WLAN-MIB",
            "mibs/cisco/CISCO-WAN-3G-MIB",
            "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
            "mibs/ENTITY-MIB",
        }),
    },
    "wireless_extreme_ewc": {
        "source_path": "LibreNMS/OS/Ewc.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Ewc.php"}),
        "mib_source_files": frozenset({
            "mibs/ewc/HIPATH-WIRELESS-HWC-MIB",
            "mibs/ewc/HIPATH-WIRELESS-DOT11-EXTNS-MIB",
            "mibs/ewc/HIPATH-WIRELESS-SMI",
            "mibs/IEEE802dot11-MIB",
        }),
    },
    "wireless_stellar": {
        "source_path": "LibreNMS/OS/Stellar.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Stellar.php"}),
        "mib_source_files": frozenset({
            "mibs/nokia/stellar/ALCATEL-NGOAW-BASE-MIB",
            "mibs/nokia/stellar/ALCATEL-NGOAW-DEVICES-MIB",
            "mibs/nokia/stellar/OAW-AP1101",
            "mibs/nokia/stellar/OAW-AP1201",
            "mibs/nokia/stellar/OAW-AP1201BG",
            "mibs/nokia/stellar/OAW-AP1201H",
            "mibs/nokia/stellar/OAW-AP1201HL",
            "mibs/nokia/stellar/OAW-AP1201L",
            "mibs/nokia/stellar/OAW-AP1221",
            "mibs/nokia/stellar/OAW-AP1222",
            "mibs/nokia/stellar/OAW-AP1231",
            "mibs/nokia/stellar/OAW-AP1232",
            "mibs/nokia/stellar/OAW-AP1251",
            "mibs/nokia/stellar/OAW-AP1251D",
            "mibs/nokia/stellar/OAW-AP1321",
            "mibs/nokia/stellar/OAW-AP1322",
            "mibs/nokia/stellar/OAW-AP1361",
            "mibs/nokia/stellar/OAW-AP1361D",
            "mibs/nokia/stellar/OAW-AP1362",
        }),
    },
    "wireless_ruckus_zd": {
        "source_path": "LibreNMS/OS/Ruckuswireless.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Ruckuswireless.php"}),
        "mib_source_files": frozenset({
            "mibs/ruckus/RUCKUS-ZD-SYSTEM-MIB",
            "mibs/ruckus/RUCKUS-ZD-WLAN-MIB",
        }),
    },
    "wireless_ruckus_hotzone": {
        "source_path": "LibreNMS/OS/RuckuswirelessHotzone.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/RuckuswirelessHotzone.php"}),
        "mib_source_files": frozenset({"mibs/ruckus/RUCKUS-ZD-SYSTEM-MIB"}),
    },
    "wireless_ruckus_sz": {
        "source_path": "LibreNMS/OS/RuckuswirelessSz.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/RuckuswirelessSz.php"}),
        "mib_source_files": frozenset({
            "mibs/ruckus/RUCKUS-CTRL-MIB",
            "mibs/ruckus/RUCKUS-SZ-SYSTEM-MIB",
            "mibs/ruckus/RUCKUS-SZ-WLAN-MIB",
        }),
    },
    "wireless_ruckus_unleashed": {
        "source_path": "LibreNMS/OS/RuckuswirelessUnleashed.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/RuckuswirelessUnleashed.php"}),
        "mib_source_files": frozenset({"mibs/ruckus/RUCKUS-UNLEASHED-SYSTEM-MIB"}),
    },
    "wireless_mikrotik": {
        "source_path": "LibreNMS/OS/Routeros.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Routeros.php"}),
        "mib_source_files": frozenset({"mibs/mikrotik/MIKROTIK-MIB"}),
    },
    "wireless_ubiquiti_airos": {
        "source_path": "LibreNMS/OS/Airos.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Airos.php"}),
        "mib_source_files": frozenset({"mibs/ubnt/UBNT-AirMAX-MIB"}),
    },
    "wireless_ubiquiti_unifi": {
        "source_path": "LibreNMS/OS/Unifi.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Unifi.php"}),
        "mib_source_files": frozenset({"mibs/ubnt/UBNT-UniFi-MIB"}),
    },
    "wireless_cisco_satellite": {
        "source_path": "LibreNMS/OS/Ciscosat.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Ciscosat.php"}),
        "mib_source_files": frozenset({"mibs/cisco/CISCO-DMN-DSG-TUNING-MIB"}),
    },
    "wireless_ubiquiti_airfiber": {
        "source_path": "LibreNMS/OS/AirosAf.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/AirosAf.php"}),
        "mib_source_files": frozenset({"mibs/ubnt/UBNT-AirFIBER-MIB"}),
    },
    "wireless_ubiquiti_airfiber_ltu": {
        "source_path": "LibreNMS/OS/AirosAfLtu.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/AirosAfLtu.php"}),
        "mib_source_files": frozenset({"mibs/ubnt/UBNT-AFLTU-MIB"}),
    },
    "wireless_ubiquiti_airfiber_60": {
        "source_path": "LibreNMS/OS/AirosAf60.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/AirosAf60.php"}),
        "mib_source_files": frozenset({"mibs/ubnt/UI-AF60-MIB"}),
    },
    "wireless_nokia_timos": {
        "source_path": "LibreNMS/OS/Timos.php",
        "adapter_source_files": frozenset({"LibreNMS/OS/Timos.php"}),
        "mib_source_files": frozenset({
            "mibs/nokia/TIMETRA-CELLULAR-MIB",
            "mibs/nokia/ALU-MICROWAVE-MIB",
            "mibs/IF-MIB",
        }),
    },
}

_WIRELESS_DISPATCHER_SOURCE = "LibreNMS/Modules/Wireless.php"
_UPSTREAM_WIRELESS_RULE_KEYS = frozenset(
    rule_key for rule_key in _MIB_RULE_SOURCES if rule_key != "wireless_h3c_comware"
)
for _wireless_rule_key in _UPSTREAM_WIRELESS_RULE_KEYS:
    _MIB_RULE_SOURCES[_wireless_rule_key]["adapter_source_files"] = frozenset({
        *_MIB_RULE_SOURCES[_wireless_rule_key]["adapter_source_files"],
        _WIRELESS_DISPATCHER_SOURCE,
    })


@functools.lru_cache(maxsize=8)
def _read_manifest(root: str, mtime_ns: int, size: int) -> dict[str, Any] | None:
    try:
        value = json.loads((Path(root) / "source-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("upstream_commit") != PINNED_LIBRENMS_COMMIT:
        return None
    return value


def _manifest() -> dict[str, Any] | None:
    manifest_path = LIBRENMS_BUNDLE_ROOT / "source-manifest.json"
    try:
        stat = manifest_path.stat()
    except OSError:
        return None
    return _read_manifest(str(LIBRENMS_BUNDLE_ROOT.resolve()), stat.st_mtime_ns, stat.st_size)


def _normalized_relative_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return ""
    return path.as_posix()


@functools.lru_cache(maxsize=4096)
def _verified_file_hash(
    root: str,
    relative_path: str,
    expected_hash: str,
    expected_size: int | None,
    mtime_ns: int,
    actual_size: int,
) -> bool:
    target = (Path(root) / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        target.relative_to(Path(root).resolve())
        content = target.read_bytes()
    except (OSError, ValueError):
        return False
    if len(content) != actual_size:
        return False
    if expected_size is not None and len(content) != expected_size:
        return False
    return hashlib.sha256(content).hexdigest() == expected_hash


def _entry_is_verified(entry: Mapping[str, Any], *, allow_bundle_path_mapping: bool = False) -> bool:
    bundle_path = _normalized_relative_path(entry.get("bundle_path"))
    upstream_path = _normalized_relative_path(entry.get("upstream_path"))
    expected_hash = str(entry.get("sha256") or "").strip().casefold()
    if (
        not bundle_path
        or not upstream_path
        or (not allow_bundle_path_mapping and bundle_path != upstream_path)
        or len(expected_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_hash)
    ):
        return False
    root = LIBRENMS_BUNDLE_ROOT.resolve()
    target = (root / Path(*PurePosixPath(bundle_path).parts)).resolve()
    try:
        target.relative_to(root)
        stat = target.stat()
    except (OSError, ValueError):
        return False
    expected_size = entry.get("size_bytes")
    if expected_size is not None and not isinstance(expected_size, int):
        return False
    return _verified_file_hash(
        str(root), bundle_path, expected_hash, expected_size,
        stat.st_mtime_ns, stat.st_size,
    )


def _source_entries(manifest: Mapping[str, Any], key: str) -> dict[str, Mapping[str, Any]]:
    values = manifest.get(key)
    if not isinstance(values, list):
        return {}
    return {
        path: item
        for item in values
        if isinstance(item, Mapping)
        and (path := _normalized_relative_path(item.get("upstream_path")))
    }


@functools.lru_cache(maxsize=8)
def _source_index_for_manifest(
    root: str,
    mtime_ns: int,
    size: int,
) -> dict[str, Mapping[str, Any]]:
    manifest = _read_manifest(root, mtime_ns, size)
    if manifest is None:
        return {}
    return _source_entries(manifest, "rule_files")


def _verified_source_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    try:
        stat = (LIBRENMS_BUNDLE_ROOT / "source-manifest.json").stat()
    except OSError:
        return {}
    # The manifest argument is checked by _manifest() before this function is
    # called. Keying the parsed source index by its file signature avoids
    # rebuilding hundreds of lookup entries for every polled sensor.
    return _source_index_for_manifest(
        str(LIBRENMS_BUNDLE_ROOT.resolve()), stat.st_mtime_ns, stat.st_size,
    )


def _mapping_or_json(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _provenance_documents(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the top-level and supported nested source metadata objects."""
    documents: list[Mapping[str, Any]] = [value]
    pending = [value.get("source"), value.get("metadata"), value.get("rule_version")]
    seen: set[int] = {id(value)}
    while pending and len(documents) < 16:
        candidate = pending.pop(0)
        if not candidate or id(candidate) in seen:
            continue
        seen.add(id(candidate))
        document = _mapping_or_json(candidate)
        if not document:
            continue
        documents.append(document)
        pending.extend((document.get("source"), document.get("metadata")))
    return documents


def _freeze_provenance_value(value: Any) -> Any:
    """Convert JSON-shaped provenance values into stable, hashable values."""
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_provenance_value(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_provenance_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_provenance_value(item) for item in value), key=repr))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def hardware_sensor_trust_cache_key(sensor: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the complete provenance identity used by hardware trust checks.

    Sensor readings and identity labels are intentionally excluded so a scrape
    can reuse an unchanged source proof across many sensors from the same rule.
    Every field read by ``is_trusted_hardware_sensor`` and its provenance
    verifiers remains part of the key, including conflicts across nested source
    documents.
    """
    if not isinstance(sensor, Mapping):
        return ("invalid_sensor", _freeze_provenance_value(sensor))

    provenance_fields = (
        "adapter_source_files",
        "commit",
        "mib_source_files",
        "os_key",
        "rule_key",
        "source_commit",
        "source_path",
        "source_type",
    )
    documents = _provenance_documents(sensor)
    document_key = tuple(
        tuple(
            (field, _freeze_provenance_value(document[field]))
            for field in provenance_fields
            if field in document
        )
        for document in documents
    )
    legacy_rule_version = sensor.get("rule_version")
    if not isinstance(legacy_rule_version, str):
        legacy_rule_version = None
    return (document_key, ("legacy_rule_version", legacy_rule_version))


def _consistent_provenance_field(
    documents: list[Mapping[str, Any]],
    field: str,
) -> Any:
    values = [document[field] for document in documents if field in document and document[field] not in (None, "")]
    if not values:
        return None
    if field in {"adapter_source_files", "mib_source_files"}:
        normalized = [_normalized_path_set(value) for value in values]
        if any(item is None for item in normalized) or any(item != normalized[0] for item in normalized[1:]):
            return None
        return values[0]
    if any(value != values[0] for value in values[1:]):
        return None
    return values[0]


def _normalized_path_set(value: Any) -> frozenset[str] | None:
    if not isinstance(value, list) or not value:
        return None
    normalized = [_normalized_relative_path(item) for item in value]
    if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
        return None
    return frozenset(normalized)


def _verified_manifest_source(
    manifest: Mapping[str, Any],
    *,
    section: str,
    upstream_path: str,
    allow_bundle_path_mapping: bool = False,
) -> bool:
    try:
        stat = (LIBRENMS_BUNDLE_ROOT / "source-manifest.json").stat()
        root = str(LIBRENMS_BUNDLE_ROOT.resolve())
    except OSError:
        return False
    current_manifest = _read_manifest(root, stat.st_mtime_ns, stat.st_size)
    # Trust checks run once per sensor during a scrape. Build the manifest path
    # lookup once per manifest signature instead of rescanning every adapter/MIB
    # entry for every sensor. File contents are still revalidated below using
    # their current stat signature and SHA-256, so this cache never caches trust.
    if current_manifest is manifest:
        matching = _manifest_source_index(
            root, stat.st_mtime_ns, stat.st_size, section,
        ).get(upstream_path, ())
    else:
        values = manifest.get(section)
        if not isinstance(values, list):
            return False
        matching = tuple(
            entry for entry in values
            if isinstance(entry, Mapping)
            and _normalized_relative_path(entry.get("upstream_path")) == upstream_path
        )
    return any(
        _entry_is_verified(entry, allow_bundle_path_mapping=allow_bundle_path_mapping)
        for entry in matching
    )


@functools.lru_cache(maxsize=16)
def _manifest_source_index(
    root: str,
    mtime_ns: int,
    size: int,
    section: str,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    """Index source manifest entries by path without caching file verification."""
    manifest = _read_manifest(root, mtime_ns, size)
    values = manifest.get(section) if isinstance(manifest, Mapping) else None
    if not isinstance(values, list):
        return {}
    index: dict[str, list[Mapping[str, Any]]] = {}
    for entry in values:
        if not isinstance(entry, Mapping):
            continue
        path = _normalized_relative_path(entry.get("upstream_path"))
        if path:
            index.setdefault(path, []).append(entry)
    return {path: tuple(entries) for path, entries in index.items()}


def verified_librenms_mib_source_entries(
    *,
    module_name: str = "",
    upstream_path: str = "",
    relative_path: str = "",
    sha256: str = "",
) -> list[Mapping[str, Any]]:
    """Return manifest MIB entries whose bundled file and requested identity verify.

    ``relative_path`` and ``sha256`` match the imported MIB database row. A
    symbolic OID must resolve through this index so an uploaded or differently
    versioned MIB with the same symbol cannot silently win.
    """
    manifest = _manifest()
    values = manifest.get("mibs") if isinstance(manifest, Mapping) else None
    if not isinstance(values, list):
        return []

    expected_module = str(module_name or "").strip().casefold()
    expected_upstream = _normalized_relative_path(upstream_path) if upstream_path else ""
    expected_relative = _normalized_relative_path(relative_path) if relative_path else ""
    expected_hash = str(sha256 or "").strip().casefold()
    matches: list[Mapping[str, Any]] = []
    for entry in values:
        if not isinstance(entry, Mapping):
            continue
        source_path = _normalized_relative_path(entry.get("upstream_path"))
        bundle_path = _normalized_relative_path(entry.get("bundle_path"))
        if not source_path.startswith("mibs/"):
            continue
        if expected_upstream and source_path != expected_upstream:
            continue
        if expected_module and PurePosixPath(source_path).name.casefold() != expected_module:
            continue
        if expected_relative and bundle_path.removeprefix("mibs/") != expected_relative:
            continue
        if expected_hash and str(entry.get("sha256") or "").strip().casefold() != expected_hash:
            continue
        if _entry_is_verified(entry, allow_bundle_path_mapping=True):
            matches.append(entry)
    return matches


def verify_librenms_os_rule(rule_or_sensor: Mapping[str, Any]) -> bool:
    """Verify a narrowly allowlisted LibreNMS PHP OS rule and its MIB inputs."""
    if not isinstance(rule_or_sensor, Mapping):
        return False
    documents = _provenance_documents(rule_or_sensor)
    source_type = _consistent_provenance_field(documents, "source_type")
    if str(source_type or "").strip().casefold() != _OS_RULE_SOURCE_TYPE:
        return False
    source_commit = _consistent_provenance_field(documents, "source_commit")
    if str(source_commit or "").strip() != PINNED_LIBRENMS_COMMIT:
        return False
    os_key = str(_consistent_provenance_field(documents, "os_key") or "").strip().casefold()
    allowed = _OS_RULE_SOURCES.get(os_key)
    if allowed is None:
        return False
    manifest = _manifest()
    if manifest is None:
        return False

    source_path = _normalized_relative_path(_consistent_provenance_field(documents, "source_path"))
    if source_path not in allowed["source_path"]:
        return False
    adapter_paths = _normalized_path_set(
        _consistent_provenance_field(documents, "adapter_source_files")
    )
    mib_paths = _normalized_path_set(
        _consistent_provenance_field(documents, "mib_source_files")
    )
    if adapter_paths != allowed["adapter_source_files"] or mib_paths != allowed["mib_source_files"]:
        return False

    source_records = manifest.get("os_rule_sources")
    if not isinstance(source_records, list):
        return False
    matching_records = [
        record for record in source_records
        if isinstance(record, Mapping)
        and str(record.get("os_key") or "").strip().casefold() == os_key
    ]
    if len(matching_records) != 1:
        return False
    record = matching_records[0]
    manifest_source_path = _normalized_relative_path(record.get("source_path"))
    manifest_adapter_paths = _normalized_path_set(record.get("adapter_source_files"))
    manifest_mib_paths = _normalized_path_set(record.get("mib_source_files"))
    if (
        manifest_source_path != source_path
        or manifest_adapter_paths != allowed["adapter_source_files"]
        or manifest_mib_paths != allowed["mib_source_files"]
    ):
        return False

    for adapter_path in sorted(adapter_paths):
        if not _verified_manifest_source(
            manifest,
            section="adapter_files",
            upstream_path=adapter_path,
        ):
            return False
    for mib_path in sorted(mib_paths):
        if not mib_path.startswith("mibs/") or not _verified_manifest_source(
            manifest,
            section="mibs",
            upstream_path=mib_path,
            allow_bundle_path_mapping=True,
        ):
            return False
    return True


def verify_librenms_mib_rule(rule_or_sensor: Mapping[str, Any]) -> bool:
    """Verify a Python collector rule against an exact set of pinned LibreNMS MIBs."""
    if not isinstance(rule_or_sensor, Mapping):
        return False
    documents = _provenance_documents(rule_or_sensor)
    source_type = _consistent_provenance_field(documents, "source_type")
    if str(source_type or "").strip().casefold() != "librenms_mib_rule":
        return False
    if str(_consistent_provenance_field(documents, "source_commit") or "").strip() != PINNED_LIBRENMS_COMMIT:
        return False
    rule_key = str(_consistent_provenance_field(documents, "rule_key") or "").strip().casefold()
    allowed = _MIB_RULE_SOURCES.get(rule_key)
    manifest = _manifest()
    if allowed is None or manifest is None:
        return False
    source_path = _normalized_relative_path(_consistent_provenance_field(documents, "source_path"))
    mib_paths = _normalized_path_set(_consistent_provenance_field(documents, "mib_source_files"))
    if source_path != allowed["source_path"] or mib_paths != allowed["mib_source_files"]:
        return False
    expected_adapter_paths = allowed.get("adapter_source_files")
    adapter_paths = _normalized_path_set(
        _consistent_provenance_field(documents, "adapter_source_files")
    )
    wireless_discovery = manifest.get("wireless_discovery")
    if rule_key in _UPSTREAM_WIRELESS_RULE_KEYS:
        if (
            not isinstance(wireless_discovery, Mapping)
            or wireless_discovery.get("dispatcher_path") != _WIRELESS_DISPATCHER_SOURCE
            or set(wireless_discovery.get("rule_keys") or ()) != _UPSTREAM_WIRELESS_RULE_KEYS
            or _WIRELESS_DISPATCHER_SOURCE not in (expected_adapter_paths or ())
            or not _verified_manifest_source(
                manifest,
                section="adapter_files",
                upstream_path=_WIRELESS_DISPATCHER_SOURCE,
            )
        ):
            return False
    elif rule_key == "wireless_h3c_comware":
        if (
            not isinstance(wireless_discovery, Mapping)
            or _WIRELESS_DISPATCHER_SOURCE in (expected_adapter_paths or ())
            or "wireless_h3c_comware" in set(wireless_discovery.get("rule_keys") or ())
        ):
            return False
    if expected_adapter_paths is not None:
        if adapter_paths != expected_adapter_paths:
            return False
        for adapter_path in sorted(adapter_paths):
            if not _verified_manifest_source(
                manifest,
                section="adapter_files",
                upstream_path=adapter_path,
            ):
                return False
    elif adapter_paths is not None:
        return False
    for mib_path in sorted(mib_paths):
        if not mib_path.startswith("mibs/") or not _verified_manifest_source(
            manifest,
            section="mibs",
            upstream_path=mib_path,
            allow_bundle_path_mapping=True,
        ):
            return False
    return True


def _sensor_provenance(sensor: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    metadata = _mapping_or_json(sensor.get("metadata"))
    rule_version = _mapping_or_json(sensor.get("rule_version"))
    commit = str(
        sensor.get("source_commit")
        or metadata.get("source_commit")
        or rule_version.get("source_commit")
        or rule_version.get("commit")
        or (sensor.get("rule_version") if isinstance(sensor.get("rule_version"), str) else "")
        or ""
    ).strip()
    source_path = str(
        sensor.get("source_path")
        or metadata.get("source_path")
        or rule_version.get("source_path")
        or ""
    ).strip()
    source_files = sensor.get("adapter_source_files")
    if not isinstance(source_files, list):
        source_files = metadata.get("adapter_source_files")
    if not isinstance(source_files, list):
        source_files = rule_version.get("adapter_source_files")
    files = [str(item).strip() for item in source_files if str(item).strip()] if isinstance(source_files, list) else []
    return commit, source_path, files


def is_trusted_hardware_sensor(sensor: Mapping[str, Any]) -> bool:
    """Return whether a raw probe sensor or decoded database row has pinned provenance.

    Structured YAML rules and narrowly allowlisted, pinned LibreNMS OS PHP
    sources may create trusted hardware sensors. Other adapter labels and
    legacy vendor collectors fail closed.
    """
    if not isinstance(sensor, Mapping):
        return False
    documents = _provenance_documents(sensor)
    source_type = str(_consistent_provenance_field(documents, "source_type") or "").strip().casefold()
    if source_type == _OS_RULE_SOURCE_TYPE:
        return verify_librenms_os_rule(sensor)
    if source_type == "librenms_mib_rule":
        return verify_librenms_mib_rule(sensor)
    if source_type not in _RULE_SOURCE_TYPES:
        return False
    manifest = _manifest()
    if manifest is None:
        return False
    commit, source_path_value, source_files = _sensor_provenance(sensor)
    if commit != PINNED_LIBRENMS_COMMIT:
        return False
    source_path = _normalized_relative_path(source_path_value)
    if not source_path:
        return False
    if source_type in _RULE_SOURCE_TYPES and not (
        source_path.startswith("resources/definitions/os_discovery/")
        and source_path.endswith(".yaml")
    ):
        return False
    rule_entries = _verified_source_index(manifest)
    source_entry = rule_entries.get(source_path)
    if source_entry is None or not _entry_is_verified(source_entry):
        return False
    if source_files:
        for source_file in source_files:
            normalized = _normalized_relative_path(source_file)
            entry = rule_entries.get(normalized)
            if not normalized or entry is None or not _entry_is_verified(entry):
                return False
    return True


def verify_bundled_rule(rule: Mapping[str, Any]) -> bool:
    """Verify a resolved OS rule against the local pinned detection/discovery YAML."""
    if not isinstance(rule, Mapping):
        return False
    manifest = _manifest()
    if manifest is None or str(rule.get("source_commit") or "").strip() != PINNED_LIBRENMS_COMMIT:
        return False
    os_key = str(rule.get("os_key") or "").strip().casefold()
    profiles = manifest.get("profiles")
    if not os_key or not isinstance(profiles, list) or not any(
        isinstance(item, Mapping) and str(item.get("os_key") or "").casefold() == os_key
        for item in profiles
    ):
        return False
    rule_entries = _verified_source_index(manifest)
    detection_path = _normalized_relative_path(rule.get("source_path"))
    expected_detection_path = f"resources/definitions/os_detection/{os_key}.yaml"
    if detection_path != expected_detection_path:
        return False
    detection_entry = rule_entries.get(detection_path)
    if detection_entry is None or not _entry_is_verified(detection_entry):
        return False

    discovery_path = _normalized_relative_path(rule.get("discovery_source_path"))
    expected_discovery_path = f"resources/definitions/os_discovery/{os_key}.yaml"
    if discovery_path != expected_discovery_path:
        return False
    discovery_entry = rule_entries.get(discovery_path)
    hardware = rule.get("hardware_definitions")
    has_hardware = isinstance(hardware, Mapping) and any(
        isinstance(hardware.get(section), list) and hardware.get(section)
        for section in ("processors", "mempools", "sensors")
    )
    if discovery_entry is None:
        return not has_hardware and not (LIBRENMS_BUNDLE_ROOT / discovery_path).exists()
    return _entry_is_verified(discovery_entry)


__all__ = [
    "PINNED_LIBRENMS_COMMIT",
    "hardware_sensor_trust_cache_key",
    "is_trusted_hardware_sensor",
    "verify_librenms_os_rule",
    "verify_librenms_mib_rule",
    "verify_bundled_rule",
]
