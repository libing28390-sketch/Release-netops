"""Compatibility normalization for persisted SNMP exporter runtime files.

The control plane keeps extra metric metadata (for example ``unit`` and
``source_name``) for the UI and metric dictionary. Older runtime artifacts may
also use the pre-v0.23 ``source_indexes``/``lookup`` mapping syntax. The v0.26
snmp_exporter parser rejects those fields. Runtime artifacts are versioned and
survive image upgrades, so normalize only the shared runtime copy at application
startup; a later compile/publish still remains the source of truth for a new
version.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping

import yaml


RUNTIME_CONFIG_RELATIVE_PATH = Path("snmp_exporter") / "snmp.yml"
_EXPORTER_UNSUPPORTED_METRIC_FIELDS = ("unit", "source_name")
_LEGACY_LOOKUP_METADATA = {
    "ifName": ("1.3.6.1.2.1.31.1.1.1.1", "DisplayString"),
    "ifDescr": ("1.3.6.1.2.1.2.2.1.2", "DisplayString"),
}


def _drop_unsupported_metric_metadata(document: Mapping[str, Any]) -> int:
    modules = document.get("modules")
    if not isinstance(modules, Mapping):
        return 0
    removed = 0
    for module in modules.values():
        if not isinstance(module, Mapping):
            continue
        metrics = module.get("metrics")
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            for field in _EXPORTER_UNSUPPORTED_METRIC_FIELDS:
                if field in metric:
                    metric.pop(field, None)
                    removed += 1
    return removed


def _upgrade_legacy_lookups(document: Mapping[str, Any]) -> int:
    """Translate pre-v0.23 exporter lookup entries in persisted volumes."""
    modules = document.get("modules")
    if not isinstance(modules, Mapping):
        return 0

    lookup_metadata_by_module: dict[str, dict[str, tuple[str, str]]] = {}
    for module_name, module in modules.items():
        if not isinstance(module, Mapping):
            continue
        metrics = module.get("metrics")
        if not isinstance(metrics, list):
            continue
        lookup_metadata_by_module[str(module_name)] = {
            str(metric.get("name") or ""): (str(metric.get("oid") or ""), str(metric.get("type") or ""))
            for metric in metrics
            if isinstance(metric, Mapping) and metric.get("name") and metric.get("oid")
        }

    converted_count = 0
    for module_name, module in modules.items():
        if not isinstance(module, Mapping):
            continue
        metrics = module.get("metrics")
        if not isinstance(metrics, list):
            continue
        metadata = lookup_metadata_by_module.get(str(module_name), {})
        for metric in metrics:
            if not isinstance(metric, dict) or not isinstance(metric.get("lookups"), list):
                continue
            upgraded_lookups = []
            for lookup in metric["lookups"]:
                if not isinstance(lookup, Mapping) or not ({"source_indexes", "lookup"} & set(lookup)):
                    upgraded_lookups.append(lookup)
                    continue
                labelname = str(lookup.get("lookup") or "").strip()
                source_labels = lookup.get("source_indexes")
                target = metadata.get(labelname) or _LEGACY_LOOKUP_METADATA.get(labelname)
                if not labelname or not isinstance(source_labels, list) or target is None:
                    raise RuntimeError("legacy SNMP lookup cannot be mapped to the v0.26 schema")
                lookup_oid, lookup_type = target
                upgraded_lookups.append({
                    "labels": [str(label).strip() for label in source_labels],
                    "labelname": labelname,
                    "oid": str(lookup.get("oid") or lookup_oid),
                    "type": str(lookup.get("type") or lookup_type),
                })
                converted_count += 1
            metric["lookups"] = upgraded_lookups
    return converted_count


def normalize_snmp_runtime(root: str | Path) -> int:
    """Remove Nexora-only metric fields from the shared runtime config.

    Returns the number of removed fields.  The operation is atomic and is a
    no-op when the runtime file has not been created or has no extra fields.
    """

    config_path = Path(root) / RUNTIME_CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        return 0
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeError(f"cannot read SNMP runtime config ({type(exc).__name__})") from exc
    if not isinstance(document, Mapping):
        return 0
    removed = _drop_unsupported_metric_metadata(document)
    upgraded_lookups = _upgrade_legacy_lookups(document)
    if not removed and not upgraded_lookups:
        return 0
    temp_path = config_path.with_name(f".{config_path.name}.normalize-tmp")
    try:
        try:
            temp_path.write_text(
                yaml.safe_dump(dict(document), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
                newline="\n",
            )
            os.replace(temp_path, config_path)
        except OSError as exc:
            raise RuntimeError(f"cannot write SNMP runtime config ({type(exc).__name__})") from exc
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return removed + upgraded_lookups


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a shared SNMP exporter runtime artifact")
    parser.add_argument("--root", required=True, help="Monitoring artifact runtime root")
    args = parser.parse_args()
    try:
        changed = normalize_snmp_runtime(args.root)
    except RuntimeError as exc:
        # Never echo configuration contents: runtime files may contain SNMP
        # credentials.  The exporter will retain its normal parse error if the
        # file cannot be read and operators can inspect it through Docker logs.
        print(f"[Monitoring] runtime normalization skipped: {exc}")
        return 0
    if changed:
        print(f"[Monitoring] normalized legacy SNMP runtime fields: changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
