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


def _entry_is_verified(entry: Mapping[str, Any]) -> bool:
    bundle_path = _normalized_relative_path(entry.get("bundle_path"))
    upstream_path = _normalized_relative_path(entry.get("upstream_path"))
    expected_hash = str(entry.get("sha256") or "").strip().casefold()
    if not bundle_path or bundle_path != upstream_path or len(expected_hash) != 64:
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

    Only the structured YAML rule executor may create trusted hardware
    sensors. Local translations of upstream PHP adapters are not LibreNMS
    rules and deliberately fail closed along with legacy vendor collectors.
    """
    if not isinstance(sensor, Mapping):
        return False
    source_type = str(sensor.get("source_type") or "").strip().casefold()
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
    "is_trusted_hardware_sensor",
    "verify_bundled_rule",
]
