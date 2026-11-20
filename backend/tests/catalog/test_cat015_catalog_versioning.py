from __future__ import annotations

import copy

import pytest

from services.catalog_version_service import (
    CatalogVersionError,
    import_catalog_version,
    list_catalog_versions,
    preview_catalog_version,
    reset_catalog_version_state_for_tests,
    rollback_catalog_version,
)
from services.product_catalog_service import list_product_aliases, list_product_catalog


DEFAULT_USER = {"id": "cat015-maintainer", "role": "Administrator", "tenant_id": "tenant-default-reviewed"}


@pytest.fixture(autouse=True)
def reset_version_registry():
    reset_catalog_version_state_for_tests()
    yield
    reset_catalog_version_state_for_tests()


def _bundle(user: dict, version: str = "2026.08.09-rc1") -> dict:
    models = copy.deepcopy(list_product_catalog(user)["items"])
    aliases = [
        {
            "id": item["id"],
            "tenant_id": item["tenant_id"],
            "product_model_id": item["product_model_id"],
            "alias": item["alias"],
            "alias_kind": item["alias_kind"],
            "status": item.get("seed_status") or "draft",
        }
        for item in list_product_aliases(user)["items"]
    ]
    return {"version": version, "models": models, "aliases": aliases}


def test_cat015_preview_is_deterministic_and_does_not_activate_candidate():
    bundle = _bundle(DEFAULT_USER)
    bundle["models"][0]["display_name"] += " Release Candidate"
    history = list_catalog_versions(DEFAULT_USER)
    baseline = history["active_version_id"]
    baseline_snapshot = next(item for item in history["versions"] if item["version_id"] == baseline)
    assert baseline_snapshot["is_seed"] is True
    assert baseline_snapshot["model_count"] == 12
    assert baseline_snapshot["alias_count"] == 14
    preview = preview_catalog_version(DEFAULT_USER, bundle)
    assert preview["dry_run"] is True
    assert preview["valid"] is True
    assert preview["can_import"] is True
    assert preview["baseline"]["version_id"] == baseline
    assert preview["diff"]["counts"]["model"]["changed"] == 1
    assert list_catalog_versions(DEFAULT_USER)["active_version_id"] == baseline


def test_cat015_import_switches_active_snapshot_and_rollback_restores_seed():
    bundle = _bundle(DEFAULT_USER)
    original = list_product_catalog(DEFAULT_USER)["items"][0]["display_name"]
    bundle["models"][0]["display_name"] = original + " Imported"
    baseline = list_catalog_versions(DEFAULT_USER)["active_version_id"]
    audit_events: list[tuple[str, dict]] = []
    imported = import_catalog_version(
        DEFAULT_USER,
        bundle,
        expected_active_version_id=baseline,
        confirm=True,
        audit_writer=lambda operation, details: audit_events.append((operation, details)) or "audit-writer-1",
    )
    assert imported["imported"] is True
    assert audit_events[0][0] == "import"
    assert "secret" not in str(audit_events[0][1]).lower()
    assert list_product_catalog(DEFAULT_USER)["items"][0]["display_name"] == original + " Imported"
    rolled_back = rollback_catalog_version(
        DEFAULT_USER,
        baseline,
        expected_active_version_id=imported["active_version_id"],
        confirm=True,
        audit_writer=lambda operation, details: audit_events.append((operation, details)) or "audit-writer-2",
    )
    assert rolled_back["rolled_back"] is True
    assert list_product_catalog(DEFAULT_USER)["items"][0]["display_name"] == original
    history = list_catalog_versions(DEFAULT_USER)
    assert history["active_version_id"] == baseline
    assert len(history["audit_events"]) == 2


def test_cat015_import_requires_confirmation_and_optimistic_baseline():
    bundle = _bundle(DEFAULT_USER)
    with pytest.raises(CatalogVersionError) as unconfirmed:
        import_catalog_version(DEFAULT_USER, bundle, confirm=False)
    assert unconfirmed.value.code == "IMPORT_CONFIRMATION_REQUIRED"
    with pytest.raises(CatalogVersionError) as stale:
        import_catalog_version(DEFAULT_USER, bundle, expected_active_version_id="seed:stale", confirm=True)
    assert stale.value.code == "STALE_ACTIVE_VERSION"


def test_cat015_preview_and_import_fail_closed_for_secrets_duplicates_and_preserve_historical_tenants():
    bundle = _bundle(DEFAULT_USER)
    bundle["models"][0]["metadata_secret"] = "do-not-accept"
    invalid = preview_catalog_version(DEFAULT_USER, bundle)
    assert invalid["valid"] is False
    assert invalid["validation"]["errors"][0]["code"] == "SECRET_FIELD_FORBIDDEN"

    duplicate = _bundle(DEFAULT_USER, "2026.08.09-duplicate")
    duplicate["models"].append(copy.deepcopy(duplicate["models"][0]))
    with pytest.raises(CatalogVersionError) as duplicate_error:
        import_catalog_version(DEFAULT_USER, duplicate, confirm=True)
    assert duplicate_error.value.code == "MODEL_DUPLICATE"

    historical = _bundle(DEFAULT_USER, "2026.08.09-historical-tenant")
    for model in historical["models"]:
        model["tenant_id"] = "tenant-history-a"
    for alias in historical["aliases"]:
        alias["tenant_id"] = "tenant-history-a"
    historical["models"].extend([
        {
            "product_model_id": "history-model-a-extra",
            "tenant_id": "tenant-history-a",
            "vendor_id": "arista",
            "vendor_name": "Arista",
            "family_code": "eos",
            "family_name": "EOS",
            "series_code": "7050",
            "series_name": "7050 Series",
            "model_code": "DCS-7050SX3-HISTORY-A",
            "display_name": "Historical tenant A model",
            "status": "active",
        },
        {
            "product_model_id": "history-model-b-extra",
            "tenant_id": "tenant-history-b",
            "vendor_id": "arista",
            "vendor_name": "Arista",
            "family_code": "eos",
            "family_name": "EOS",
            "series_code": "7050",
            "series_name": "7050 Series",
            "model_code": "DCS-7050SX3-HISTORY-B",
            "display_name": "Historical tenant B model",
            "status": "active",
        },
    ])
    historical["aliases"].extend([
        {
            "id": "history-alias-a-extra",
            "tenant_id": "tenant-history-a",
            "product_model_id": "history-model-a-extra",
            "alias": "History Shared Identity",
            "alias_kind": "exact",
            "status": "active",
        },
        {
            "id": "history-alias-b-extra",
            "tenant_id": "tenant-history-b",
            "product_model_id": "history-model-b-extra",
            "alias": "History Shared Identity",
            "alias_kind": "exact",
            "status": "active",
        },
    ])
    mismatch = copy.deepcopy(historical)
    mismatch["aliases"][-2]["tenant_id"] = "tenant-history-b"
    invalid_relation = preview_catalog_version(DEFAULT_USER, mismatch)
    assert invalid_relation["valid"] is False
    assert invalid_relation["validation"]["errors"][0]["code"] == "ALIAS_TENANT_MISMATCH"
    duplicate_alias = copy.deepcopy(historical)
    duplicate_alias["aliases"].append({
        "id": "history-alias-a-duplicate",
        "tenant_id": "tenant-history-a",
        "product_model_id": "history-model-a-extra",
        "alias": "History Shared Identity",
        "alias_kind": "exact",
        "status": "active",
    })
    invalid_duplicate = preview_catalog_version(DEFAULT_USER, duplicate_alias)
    assert invalid_duplicate["valid"] is False
    assert invalid_duplicate["validation"]["errors"][0]["code"] == "ALIAS_DUPLICATE_ACTIVE"
    canonical = preview_catalog_version(DEFAULT_USER, historical)
    tenant_variant = copy.deepcopy(historical)
    tenant_variant["models"][-1]["tenant_id"] = "tenant-history-c"
    tenant_variant["aliases"][-1]["tenant_id"] = "tenant-history-c"
    variant_preview = preview_catalog_version(DEFAULT_USER, tenant_variant)
    assert canonical["valid"] is True and variant_preview["valid"] is True
    assert canonical["candidate"]["content_hash"] != variant_preview["candidate"]["content_hash"]
    assert canonical["candidate"]["version_id"] != variant_preview["candidate"]["version_id"]
    historical["models"][0]["display_name"] += " Historical"
    imported = import_catalog_version(DEFAULT_USER, historical, confirm=True)
    from services.catalog_version_service import get_active_catalog_snapshot

    snapshot = get_active_catalog_snapshot(tenant_id="tenant-default")
    assert imported["tenant_id"] == "tenant-default"
    assert all(item["tenant_id"] in {"tenant-history-a", "tenant-history-b"} for item in snapshot["models"])
    assert all(item["tenant_id"] in {"tenant-history-a", "tenant-history-b"} for item in snapshot["aliases"])
    assert next(item for item in snapshot["aliases"] if item["id"] == "history-alias-a-extra")["tenant_id"] == "tenant-history-a"
    assert next(item for item in snapshot["aliases"] if item["id"] == "history-alias-b-extra")["tenant_id"] == "tenant-history-b"


def test_cat015_tenant_mismatch_stays_denied_when_tenant_isolation_is_enabled(monkeypatch):
    from core import rbac, tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rbac, "TENANT_ISOLATION_ENABLED", True)
    bundle = _bundle(DEFAULT_USER, "2026.08.09-isolated-cross-tenant")
    bundle["models"][0]["tenant_id"] = "tenant-other"
    with pytest.raises(CatalogVersionError) as tenant_error:
        import_catalog_version(DEFAULT_USER, bundle, confirm=True)
    assert tenant_error.value.code == "TENANT_SCOPE_DENIED"


def test_cat015_single_org_lists_and_rolls_back_the_original_historical_version_state(monkeypatch):
    from core import rbac, tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rbac, "TENANT_ISOLATION_ENABLED", True)
    owner = {"id": "version-history-a", "role": "Administrator", "tenant_id": "tenant-history-a"}
    bundle = {
        "version": "history-a-v1",
        "models": [{
            "product_model_id": "history-model-a",
            "tenant_id": "tenant-history-a",
            "vendor_id": "arista",
            "vendor_name": "Arista",
            "family_code": "eos",
            "family_name": "EOS",
            "series_code": "7050",
            "series_name": "7050 Series",
            "model_code": "DCS-7050SX3",
            "display_name": "History A model",
            "status": "active",
        }],
        "aliases": [{
            "id": "history-alias-a",
            "tenant_id": "tenant-history-a",
            "product_model_id": "history-model-a",
            "alias": "DCS-7050SX3",
            "alias_kind": "exact",
            "status": "draft",
        }],
    }
    baseline = list_catalog_versions(owner)["active_version_id"]
    imported = import_catalog_version(owner, bundle, expected_active_version_id=baseline, confirm=True)

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    monkeypatch.setattr(rbac, "TENANT_ISOLATION_ENABLED", False)
    reader = {"id": "version-history-reader", "role": "Administrator", "tenant_id": "tenant-history-b"}
    history = list_catalog_versions(reader)
    assert history["active_version_ids"]["tenant-history-a"] == imported["active_version_id"]
    historical = [item for item in history["versions"] if item["tenant_id"] == "tenant-history-a"]
    assert {item["version_id"] for item in historical} >= {baseline, imported["active_version_id"]}

    rolled_back = rollback_catalog_version(
        reader,
        baseline,
        expected_active_version_id=imported["active_version_id"],
        confirm=True,
    )
    assert rolled_back["tenant_id"] == "tenant-history-a"
    assert rolled_back["active_version_id"] == baseline
    assert list_catalog_versions(reader)["active_version_ids"]["tenant-history-a"] == baseline


def test_cat015_api_contract_and_permission_profile_are_explicit():
    from core.rbac import RECOMMENDED_ROLE_PROFILES, permission_catalog
    from api.knowledge_catalog import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge/catalog/versions") and "GET" in methods for path, methods in paths)
    assert any(path.endswith("/versions/preview") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/versions/import") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/versions/{version_id}/rollback") and "POST" in methods for path, methods in paths)
    assert set(permission_catalog()["knowledge_catalog"]) >= {"import", "rollback"}
    assert "import" not in RECOMMENDED_ROLE_PROFILES["Platform Viewer"]["knowledge_catalog"]
    assert set(RECOMMENDED_ROLE_PROFILES["Platform Maintainer"]["knowledge_catalog"]) >= {"import", "rollback"}
