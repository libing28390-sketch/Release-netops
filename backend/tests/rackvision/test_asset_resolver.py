from __future__ import annotations

import json
from pathlib import Path

from services import rack_asset_resolver


ROOT = Path(__file__).resolve().parents[3]


def test_catalog_build_contains_all_workbook_rows_and_reusable_registry():
    manifest = json.loads((ROOT / "assets" / "catalog" / "catalog_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "assets" / "catalog" / "catalog_summary.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["records"] == len(summary["rows"])
    assert summary["sheet_index"] == 0
    assert manifest["sheets"]["network_devices"]["records"] == 120
    assert manifest["sheets"]["rack_assets"]["records"] == 59
    assert manifest["sheets"]["cables_optics"]["records"] == 34
    assert manifest["sheets"]["network_devices"]["incomplete_dimensions"] == 71
    assert manifest["registry"]["exact_sku_mappings"] == 120
    assert manifest["registry"]["reusable_asset_entries"] < 120


def test_exact_sku_resolves_to_family_asset_without_changing_identity():
    mapping = json.loads((ROOT / "assets" / "catalog" / "model_mapping.json").read_text(encoding="utf-8"))
    first = mapping[0]
    resolved = rack_asset_resolver.resolve_asset(
        vendor=first["vendor"],
        model=first["exact_model"],
        device_type="switch",
        height_u=1,
    )
    assert resolved["asset_key"] == first["asset_key"]
    assert resolved["resolution_level"] == "family"
    assert resolved["requested_model"] == first["exact_model"].casefold()


def test_unknown_model_never_returns_null_and_reports_generic_fallback():
    resolved = rack_asset_resolver.resolve_asset(
        vendor="unknown-vendor",
        model="unlisted-model",
        device_type="server",
        height_u=2,
    )
    assert resolved["asset_key"]
    assert resolved["resolution_level"] == "global_generic"
    assert resolved["fidelity"] == "generic"
    assert resolved["render_strategy"] in {"procedural", "procedural_until_glb_approved"}


def test_registry_model_alias_precedes_alphabetical_h3c_family_fallback():
    resolved = rack_asset_resolver.resolve_asset(
        vendor="H3C",
        model="S6800",
        device_type="switch",
        height_u=1,
    )
    assert resolved["asset_key"] == "h3c_s6800_family"
    assert resolved["resolution_level"] == "family"
    assert resolved["available"] is True
    assert resolved["render_strategy"] == "glb"


def test_generic_patch_panel_resolves_to_approved_glb():
    resolved = rack_asset_resolver.resolve_asset(
        vendor="Generic",
        model="Patch Panel 24P",
        device_type="patch_panel",
        height_u=1,
    )
    assert resolved["asset_key"] == "generic_patch_panel_cat6_24p"
    assert resolved["available"] is True
    assert resolved["render_strategy"] == "glb"


def test_chinese_patch_panel_label_resolves_to_same_approved_glb():
    resolved = rack_asset_resolver.resolve_asset(
        vendor="Generic",
        model="Cat6 24口 RJ45 配线架",
        device_type="配线架",
        height_u=1,
    )
    assert resolved["asset_key"] == "generic_patch_panel_cat6_24p"
    assert resolved["available"] is True
    assert resolved["render_strategy"] == "glb"


def test_approved_asset_availability_uses_published_path_not_ignored_build_output(tmp_path, monkeypatch):
    published_asset = tmp_path / "public" / "assets" / "3d" / "approved.glb"
    published_asset.parent.mkdir(parents=True)
    published_asset.write_bytes(b"glTF")
    monkeypatch.setattr(rack_asset_resolver, "_ROOT", tmp_path)

    assert rack_asset_resolver._available(
        {
            "status": "approved",
            "glb_path": "assets/build/glb/approved.glb",
            "public_path": "/assets/3d/approved.glb",
        }
    ) is True


def test_approved_asset_availability_rejects_public_path_escape(tmp_path, monkeypatch):
    (tmp_path / "outside.glb").write_bytes(b"glTF")
    monkeypatch.setattr(rack_asset_resolver, "_ROOT", tmp_path)

    assert rack_asset_resolver._available(
        {
            "status": "approved",
            "glb_path": "assets/build/glb/outside.glb",
            "public_path": "/../outside.glb",
        }
    ) is False
