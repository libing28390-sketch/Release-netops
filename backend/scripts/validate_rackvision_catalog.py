"""Validate generated RackVision catalog invariants in CI or a release build."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-dir", type=Path, default=Path("assets/catalog"))
    args = parser.parse_args()
    root = args.catalog_dir
    manifest = json.loads((root / "catalog_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "catalog_summary.json").read_text(encoding="utf-8"))
    network = json.loads((root / "network_devices.json").read_text(encoding="utf-8"))
    rack_assets = json.loads((root / "rack_assets.json").read_text(encoding="utf-8"))
    cables = json.loads((root / "cables_optics.json").read_text(encoding="utf-8"))
    priorities = json.loads((root / "modeling_priorities.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "asset_registry.json").read_text(encoding="utf-8"))
    mapping = json.loads((root / "model_mapping.json").read_text(encoding="utf-8"))

    issues: list[str] = []
    if summary.get("sheet_index") != 0 or not summary.get("rows"):
        issues.append("catalog_summary.json must preserve the workbook explanation/KPI sheet")
    if manifest.get("summary", {}).get("records") != len(summary.get("rows") or []):
        issues.append("catalog summary count does not match manifest")
    expected_network = manifest["sheets"]["network_devices"]["records"]
    expected_mapping = manifest["registry"]["exact_sku_mappings"]
    if expected_network != 120 or expected_mapping != 120:
        issues.append("the reviewed workbook must contain 120 network exact-SKU rows/mappings")
    if len(mapping) != expected_mapping:
        issues.append("model_mapping.json count does not match manifest")
    for name, records in (
        ("network_devices", network),
        ("rack_assets", rack_assets),
        ("cables_optics", cables),
        ("modeling_priorities", priorities),
    ):
        expected = manifest["sheets"][name]["records"]
        if not isinstance(records, list) or len(records) != expected:
            issues.append(f"{name}.json count does not match manifest")
    network_keys = [str(item.get("catalog_key") or "") for item in network]
    if any(not key for key in network_keys) or len(network_keys) != len(set(network_keys)):
        issues.append("network device catalog keys must be present and unique")
    registry_keys = [str(item.get("asset_key") or "") for item in registry]
    if not all(registry_keys) or len(registry_keys) != len(set(registry_keys)):
        issues.append("asset registry keys must be present and unique")
    mapping_pairs = [(str(item.get("vendor") or "").casefold(), str(item.get("exact_model") or "").casefold()) for item in mapping]
    if any(not vendor or not model for vendor, model in mapping_pairs):
        issues.append("every model mapping requires vendor and exact_model")
    if len(mapping_pairs) != len(set(mapping_pairs)):
        issues.append("vendor/exact_model mappings must be unique")
    for entry in registry:
        status = str(entry.get("status") or "")
        if status not in {"draft", "review", "approved", "deprecated"}:
            issues.append(f"invalid registry status for {entry.get('asset_key')}")
        if status == "approved" and not entry.get("glb_path"):
            issues.append(f"approved asset has no glb_path: {entry.get('asset_key')}")
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(json.dumps({
        "valid": True,
        "network_devices": len(network),
        "rack_assets": len(rack_assets),
        "cables_optics": len(cables),
        "modeling_priorities": len(priorities),
        "registry_entries": len(registry),
        "mappings": len(mapping),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
